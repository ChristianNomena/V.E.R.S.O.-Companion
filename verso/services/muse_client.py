"""
V.E.R.S.O. - Meta Muse AI Client (Pillar 1: The Inverse OS)
Optimized client for the Meta Muse Responses API covering Slack intention
delegation, vocal assistance, and resilient local fallback.

Transport follows the official Meta example exactly: POST ``{base}/responses``
with ``{"model", "input": [{"role", "content": [{"type": "input_text",
"text"}]}], "stream": False}``.

Optimization strategy:
- Single shared ``requests.Session`` with connection pooling and automatic
  retries (exponential backoff on 429/5xx) instead of one-shot ``requests.post``.
- Bounded generation parameters (low temperature, capped output tokens) to
  cut cost and latency on short, deterministic drafts.
- Input truncation so a large clipboard paste can never explode token usage.
- Short-circuit for vocal approvals (no API call when the user just says yes).
- Small in-memory TTL cache to deduplicate identical suggestion requests.
- One shared ``_request`` transport helper (no duplicated request code).
"""

import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from verso.config import (
    META_MUSE_API_KEY,
    META_MUSE_ENDPOINT,
    MUSE_CACHE_MAX_ENTRIES,
    MUSE_CACHE_TTL_SECONDS,
    MUSE_MAX_INPUT_CHARS,
    MUSE_MAX_RETRIES,
    MUSE_MAX_TOKENS_FINALIZE,
    MUSE_MAX_TOKENS_SUGGESTION,
    MUSE_MODEL,
    MUSE_TEMPERATURE,
    MUSE_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Compact task-specific system prompts (fewer input tokens than one generic prompt).
SUGGESTION_SYSTEM_PROMPT = (
    "You are V.E.R.S.O., an ambient AI companion. "
    "Reply with a strict JSON object only, in English."
)
FINALIZE_SYSTEM_PROMPT = (
    "You are V.E.R.S.O., an ambient AI companion drafting short, professional, "
    "ready-to-send replies in English. Output only the final message text."
)

# Vocal approval detection. Single-word entries match on word boundaries so that
# e.g. "go" does not match "good". Multi-word entries match as phrases.
APPROVAL_WORDS = frozenset({"yes", "approve", "approved", "confirm", "confirmed", "ok", "okay", "go", "sure", "perfect"})
APPROVAL_PHRASES = ("sounds good", "send it", "do it")
_APPROVAL_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
_MAX_APPROVAL_WORDS = 6


def _truncate(text: str, max_chars: int = MUSE_MAX_INPUT_CHARS) -> str:
    """Clips oversized user content to bound token usage."""
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "…"


def _extract_sender(incoming_context: str) -> Tuple[str, str]:
    """Splits an incoming message to extract the sender name and clean text."""
    clean_msg = (incoming_context or "").strip()
    sender = ""
    if clean_msg.startswith("From ") and ":" in clean_msg:
        head, _, tail = clean_msg[len("From "):].partition(":")
        if head.strip() and tail.strip():
            sender = head.strip()
            clean_msg = tail.strip()
    elif ":" in clean_msg:
        possible_sender, _, rem = clean_msg.partition(":")
        parts = possible_sender.strip().split()
        if 1 <= len(parts) <= 4 and not possible_sender.lower().startswith("http"):
            sender = possible_sender.strip()
            clean_msg = rem.strip()

    # Strip notification wrappers like "Slack |", "Slack -", "Slack:"
    for prefix in ("Slack |", "Slack -", "Slack:", "Slack"):
        if sender.startswith(prefix):
            sender = sender[len(prefix):].strip()

    if not sender or sender.lower() in ("slack", "someone"):
        sender = "Someone"

    return sender, clean_msg


def _is_vocal_approval(user_speech: str) -> bool:
    """Returns True when the user simply approved the draft (no API call needed)."""
    lowered = (user_speech or "").lower().strip()
    if not lowered:
        return False
    words = _APPROVAL_WORD_RE.findall(lowered)
    if not words or len(words) > _MAX_APPROVAL_WORDS:
        return False
    if any(phrase in lowered for phrase in APPROVAL_PHRASES):
        return True
    return any(word in APPROVAL_WORDS for word in words)


def _parse_json_object(content: str) -> Dict[str, Any]:
    """Parses a JSON object, tolerating Markdown code fences around it."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Muse response is not a JSON object")
    return parsed


def _extract_output_text(data: Dict[str, Any]) -> str:
    """Extracts the assistant text from a Responses API body.

    Primary shape: ``{"output": [{"content": [{"type": "output_text",
    "text": ...}]}]}``. Also tolerates the legacy chat-completions shape
    (``{"choices": [{"message": {"content": ...}}]}``) as a fallback.
    """
    output = data.get("output")
    if isinstance(output, list):
        parts: List[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for block in item.get("content") or []:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        text = "".join(parts).strip()
        if text:
            return text
    try:
        legacy = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        legacy = ""
    if isinstance(legacy, str) and legacy.strip():
        return legacy.strip()
    raise ValueError("Muse response contains no readable output text")


class _TtlCache:
    """Minimal thread-safe TTL cache keyed by request fingerprint."""

    def __init__(self, max_entries: int, ttl_seconds: float) -> None:
        self._max_entries = max(1, max_entries)
        self._ttl = max(0.0, ttl_seconds)
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._store) >= self._max_entries:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]
            self._store[key] = (time.monotonic() + self._ttl, value)


class MuseClient:
    """Optimized client for the Meta Muse Responses API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: float = MUSE_TEMPERATURE,
        max_retries: int = MUSE_MAX_RETRIES,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.api_key = api_key or META_MUSE_API_KEY
        self.endpoint = endpoint or META_MUSE_ENDPOINT
        self.model_name = model_name or MUSE_MODEL
        self.timeout = MUSE_TIMEOUT if timeout is None else timeout
        self.temperature = temperature
        self._owns_session = session is None
        self._session = session or self._build_session(max_retries)
        self._suggestion_cache = _TtlCache(MUSE_CACHE_MAX_ENTRIES, MUSE_CACHE_TTL_SECONDS)

    @staticmethod
    def _build_session(max_retries: int) -> requests.Session:
        """Builds a pooled session with exponential-backoff retries on 429/5xx."""
        retry = Retry(
            total=max(0, max_retries),
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("POST",),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def close(self) -> None:
        """Releases the underlying HTTP session when owned by this client."""
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> "MuseClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    @property
    def is_configured(self) -> bool:
        """Returns True if API credentials are present."""
        return bool(self.api_key and self.endpoint)

    @property
    def responses_endpoint(self) -> str:
        """Returns the full Responses API URL (``{base}/responses``)."""
        base = (self.endpoint or "https://api.meta.ai/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]  # migrate legacy chat-style URL
        if base.endswith("/responses"):
            return base
        return f"{base}/responses"

    # -- Transport -----------------------------------------------------

    def _request(
        self,
        system_prompt: str,
        user_text: str,
        max_output_tokens: int,
    ) -> str:
        """Sends one Responses API request and returns the assistant text.

        Payload follows the official Meta example: ``model`` + ``input``
        content blocks + ``"stream": False`` (+ standard ``temperature`` and
        ``max_output_tokens`` bounds). Strict-JSON behavior is enforced via
        the prompt text and the tolerant ``_parse_json_object`` parser.
        """
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_text}],
                },
            ],
            "temperature": self.temperature,
            "max_output_tokens": max_output_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = self._session.post(
            self.responses_endpoint, json=payload, headers=headers, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage") or {}
        if usage:
            logger.debug(
                "Muse usage model=%s input=%s output=%s total=%s",
                self.model_name,
                usage.get("input_tokens", usage.get("prompt_tokens")),
                usage.get("output_tokens", usage.get("completion_tokens")),
                usage.get("total_tokens"),
            )
        return _extract_output_text(data)

    # -- Public API ----------------------------------------------------

    def generate_vocal_suggestion(self, incoming_context: str) -> Dict[str, str]:
        """
        Analyzes the incoming communication using the Muse Responses API.
        Returns:
            - sender: Name of sender (e.g. 'Sarah')
            - spoken_intro: Message read out loud to user
            - spoken_suggestion: Assistant's proposed action asked out loud
            - suggested_reply: Full textual drafted response
        """
        sender, clean_msg = _extract_sender(incoming_context)
        clipped = _truncate(clean_msg)

        def fallback() -> Dict[str, str]:
            return {
                "sender": sender,
                "spoken_intro": f"Message from {sender}: '{clipped}'",
                "spoken_suggestion": (
                    "I suggest replying that you are taking care of this right away. "
                    "What do you think?"
                ),
                "suggested_reply": (
                    f"Hello {sender}, thank you for reaching out! "
                    "I am taking care of this right away and will follow up shortly."
                ),
            }

        if not self.is_configured:
            return fallback()

        cache_key = hashlib.sha256(f"suggest:{sender}:{clipped}".encode("utf-8")).hexdigest()
        cached = self._suggestion_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        try:
            prompt = (
                f"New message from '{sender}': '{clipped}'.\n"
                'Return strict JSON with keys "spoken_intro" (one sentence reading '
                'the message), "spoken_suggestion" (one short question proposing a '
                'reply), "suggested_reply" (professional draft ready to send).'
            )
            content = self._request(
                SUGGESTION_SYSTEM_PROMPT,
                prompt,
                MUSE_MAX_TOKENS_SUGGESTION,
            )
            parsed = _parse_json_object(content)
            result = {
                "sender": sender,
                "spoken_intro": str(parsed.get("spoken_intro", "")).strip(),
                "spoken_suggestion": str(parsed.get("spoken_suggestion", "")).strip(),
                "suggested_reply": str(parsed.get("suggested_reply", "")).strip(),
            }
            if not result["spoken_intro"] or not result["suggested_reply"]:
                raise ValueError("Muse suggestion is missing required keys")
            self._suggestion_cache.put(cache_key, result)
            return dict(result)
        except Exception as exc:
            logger.warning("Muse (%s) request failed (%s), using fallback template.", self.model_name, exc)
            return fallback()

    def finalize_response(
        self,
        incoming_message: str,
        suggested_reply: str,
        user_speech: str,
    ) -> str:
        """
        Finalizes the draft response based on user's vocal feedback.
        If user approved ('yes', 'approve', 'confirm', 'go'), keeps suggested_reply
        without any API call. Otherwise refines the draft using Muse.
        """
        # Zero-cost path: plain approval reuses the existing draft.
        if _is_vocal_approval(user_speech):
            return suggested_reply

        clipped_incoming = _truncate(incoming_message)
        clipped_draft = _truncate(suggested_reply)
        clipped_directive = _truncate(user_speech)

        if not self.is_configured:
            return (
                "Hello,\n\n"
                f"Following up on your message: {clipped_directive}.\n\n"
                "Best regards."
            )

        try:
            prompt = (
                f"Incoming: '{clipped_incoming}'\n"
                f"Draft: '{clipped_draft}'\n"
                f"User directive: '{clipped_directive}'\n\n"
                "Rewrite the final reply per the directive."
            )
            content = self._request(
                FINALIZE_SYSTEM_PROMPT,
                prompt,
                MUSE_MAX_TOKENS_FINALIZE,
            )
            final = content.strip()
            if not final:
                raise ValueError("Muse returned an empty refinement")
            return final
        except Exception as exc:
            logger.warning("Muse (%s) refinement failed (%s), using direct template.", self.model_name, exc)
            return f"Hello,\n\nRegarding your message: {clipped_directive}.\n\nBest regards."

    def generate_response(
        self, prompt: str, context: Optional[str] = None
    ) -> Dict[str, Any]:
        """Backward compatibility for legacy worker calls."""
        incoming_text = context or prompt or "Incoming message"
        suggestion = self.generate_vocal_suggestion(incoming_text)
        return {
            "notification": "Slack response ready in V.E.R.S.O.",
            "action_title": f"Vocal Slack Exchange ({suggestion['sender']})",
            "content": suggestion["suggested_reply"],
        }

    def generate_quick_replies(self, incoming_context: str) -> Dict[str, Any]:
        """
        Generates 3 diverse quick response options for silent / non-vocal mode.
        Returns:
            - sender: Name of sender
            - summary: Short 1-sentence summary of the message
            - options: List of 3 distinct, professional ready-to-send options
        """
        sender, clean_msg = _extract_sender(incoming_context)
        clipped = _truncate(clean_msg)

        def fallback() -> Dict[str, Any]:
            return {
                "sender": sender,
                "summary": f"{sender}: {clipped}",
                "options": [
                    f"Hi {sender}, yes, sounds good! I will take care of this right away.",
                    f"Hi {sender}, I am currently busy in a meeting, but will follow up shortly.",
                    f"Hi {sender}, thanks for reaching out. Let me review and get back to you later today.",
                ],
            }

        if not self.is_configured:
            return fallback()

        cache_key = hashlib.sha256(f"quick_replies:{sender}:{clipped}".encode("utf-8")).hexdigest()
        cached = self._suggestion_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        try:
            prompt = (
                f"Incoming communication from '{sender}': '{clipped}'.\n"
                "Generate 3 diverse, professional quick reply options ready to send.\n"
                'Return strict JSON with keys: "options" (list of 3 strings), "summary" (short string).'
            )
            content = self._request(
                "You are V.E.R.S.O., generating quick reply options for incoming messages. Output strict JSON only.",
                prompt,
                800,
            )
            parsed = _parse_json_object(content)
            raw_options = parsed.get("options")
            if not isinstance(raw_options, list) or len(raw_options) < 2:
                raise ValueError("Muse returned invalid quick options list")
            result = {
                "sender": sender,
                "summary": str(parsed.get("summary", "")).strip(),
                "options": [str(opt).strip() for opt in raw_options[:3]],
            }
            self._suggestion_cache.put(cache_key, result)
            return dict(result)
        except Exception as exc:
            logger.warning("Muse (%s) quick replies request failed (%s), using fallback template.", self.model_name, exc)
            return fallback()
