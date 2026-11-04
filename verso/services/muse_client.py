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

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
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
    MUSE_TRANSCRIBE_MODEL,
    MUSE_REASONING_EFFORT,
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


def _truncate_tail(text: str, max_chars: int) -> str:
    """Keeps the most recent tail of a chronological text (drops the oldest)."""
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return "…" + cleaned[-max_chars:].lstrip()


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

    if data.get("status") == "incomplete":
        inc = data.get("incomplete_details") or {}
        reason = inc.get("reason", "max_output_tokens")
        raise ValueError(f"Muse response incomplete ({reason})")

    raise ValueError("Muse response contains no readable output text")


# Screenshots attached to companion answers (Responses API input_image blocks).
MAX_COMPANION_IMAGE_BYTES = 8 * 1024 * 1024


def _load_image_block(path: str) -> Optional[Dict[str, Any]]:
    """Loads a screenshot file as an input_image content block, or None if unusable."""
    try:
        if not path or not os.path.isfile(path):
            return None
        if os.path.getsize(path) > MAX_COMPANION_IMAGE_BYTES:
            logger.debug("Skipping oversized screenshot: %s", path)
            return None
        with open(path, "rb") as handle:
            raw = handle.read()
        if not raw:
            return None
        encoded = base64.b64encode(raw).decode("ascii")
        return {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}"}
    except Exception as exc:
        logger.debug("Skipping unreadable screenshot %s: %s", path, exc)
        return None


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
        reasoning_effort: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or META_MUSE_API_KEY
        self.endpoint = endpoint or META_MUSE_ENDPOINT
        self.model_name = model_name or MUSE_MODEL
        self.timeout = MUSE_TIMEOUT if timeout is None else timeout
        self.temperature = temperature
        self.reasoning_effort = MUSE_REASONING_EFFORT if reasoning_effort is None else reasoning_effort
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

    @property
    def transcribe_endpoint(self) -> str:
        """Returns the Muse Voice Transcribe URL (``{base}/asr/transcribe``)."""
        base = (self.endpoint or "https://api.meta.ai/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        if base.endswith("/responses"):
            base = base[: -len("/responses")]
        if base.endswith("/asr/transcribe"):
            return base
        return f"{base}/asr/transcribe"

    def transcribe_audio(self, wav_path: str, session_id: Optional[str] = None) -> str:
        """Transcribes a WAV recording with Muse Voice Transcribe.

        Sends the official multipart request (JSON ``request`` part + WAV
        ``audio`` part) to ``POST {base}/asr/transcribe`` and returns the
        transcript text. Raises on missing credentials, transport, or HTTP
        errors so callers can fall back to another transcriber.
        The WAV must be mono 16-bit PCM at 16 kHz or 24 kHz.
        """
        if not self.is_configured:
            raise ValueError("Muse API is not configured (missing API key or endpoint)")
        if not wav_path or not os.path.isfile(wav_path):
            raise ValueError(f"Audio file not found: {wav_path}")

        request_payload = {
            "mode": "PUSH_TO_TALK",
            "model": MUSE_TRANSCRIBE_MODEL,
            "audioEncoding": "WAV",
            "languageBias": ["English"],
        }
        with open(wav_path, "rb") as audio_handle:
            files = {
                "request": (None, json.dumps(request_payload), "application/json"),
                "audio": (os.path.basename(wav_path), audio_handle, "audio/wav"),
            }
            resp = self._session.post(
                self.transcribe_endpoint,
                files=files,
                headers={"Authorization": f"Bearer {self.api_key}"},
                params={"sessionId": session_id or uuid.uuid4().hex},
                timeout=max(self.timeout, 30.0),
            )
        resp.raise_for_status()
        data = resp.json() or {}
        transcript = str(data.get("transcript") or "").strip()
        if not transcript and isinstance(data.get("turns"), list):
            transcript = " ".join(
                str(turn.get("transcript") or "").strip()
                for turn in data["turns"]
                if isinstance(turn, dict)
            ).strip()
        if not transcript:
            raise ValueError("Muse Voice Transcribe returned an empty transcript")
        return transcript

    # -- Transport -----------------------------------------------------

    def _build_payload(
        self,
        system_prompt: str,
        user_text: str,
        max_output_tokens: int,
        images: Optional[List[str]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        user_content: List[Dict[str, Any]] = [{"type": "input_text", "text": user_text}]
        if images:
            for image_path in images:
                image_block = _load_image_block(image_path)
                if image_block is not None:
                    user_content.append(image_block)
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            "temperature": self.temperature,
            "max_output_tokens": max_output_tokens,
            "stream": stream,
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        return payload

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        system_prompt: str,
        user_text: str,
        max_output_tokens: int,
        images: Optional[List[str]] = None,
    ) -> str:
        """Sends one Responses API request and returns the assistant text.

        Payload follows the official Meta example: ``model`` + ``input``
        content blocks + ``"stream": False`` (+ standard ``temperature`` and
        ``max_output_tokens`` bounds). Strict-JSON behavior is enforced via
        the prompt text and the tolerant ``_parse_json_object`` parser.
        Optional screenshot paths ride along as ``input_image`` blocks.
        """
        payload = self._build_payload(system_prompt, user_text, max_output_tokens, images)
        headers = self._headers()
        resp = self._session.post(
            self.responses_endpoint, json=payload, headers=headers, timeout=self.timeout
        )
        if (
            resp.status_code == 400
            and "reasoning" in payload
            and "reasoning" in resp.text.lower()
        ):
            payload.pop("reasoning", None)
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

    def _request_stream(
        self,
        system_prompt: str,
        user_text: str,
        max_output_tokens: int,
        images: Optional[List[str]] = None,
        on_delta: Optional[Any] = None,
    ) -> str:
        """Streaming variant of ``_request``: forwards text deltas as they arrive.

        Parses Server-Sent Events (``response.output_text.delta``). If the
        gateway answers with a plain JSON body instead of a stream, that body
        is parsed like a normal response. Raises on transport/HTTP errors or
        when the stream produced no text, so callers can fall back.
        """
        payload = self._build_payload(
            system_prompt, user_text, max_output_tokens, images, stream=True
        )
        resp = self._session.post(
            self.responses_endpoint,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
            stream=True,
        )
        resp.raise_for_status()
        content_type = ""
        try:
            content_type = str((resp.headers or {}).get("Content-Type", ""))
        except Exception:
            content_type = ""
        if "text/event-stream" not in content_type:
            return _extract_output_text(resp.json())

        parts: List[str] = []
        for raw_line in resp.iter_lines(decode_unicode=True):
            line = (raw_line or "").strip() if isinstance(raw_line, str) else ""
            if not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                event = json.loads(data_str)
            except (ValueError, TypeError):
                continue
            delta = ""
            if isinstance(event, dict):
                if event.get("type") == "response.output_text.delta":
                    delta = str(event.get("delta") or "")
                elif isinstance(event.get("delta"), str):
                    delta = event["delta"]
                elif event.get("choices"):
                    try:
                        delta = str(event["choices"][0]["delta"].get("content") or "")
                    except Exception:
                        delta = ""
            if delta:
                parts.append(delta)
                if on_delta is not None:
                    try:
                        on_delta(delta)
                    except Exception:
                        pass
        text = "".join(parts).strip()
        if not text:
            raise ValueError("Streaming response produced no text")
        return text

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

    # -- Pillar 2: Benevolent Partner -----------------------------------

    COMPANION_SYSTEM_PROMPT = (
        "You are V.E.R.S.O., a benevolent copilot: clear and straightforward. "
        "You have observed the user's recent activity (applications, windows, "
        "screenshots, clipboard). Reply in English, concisely, grounding every "
        "piece of advice in the observed facts. "
        "No superfluous greetings, no repetitive pleasantries. "
        "Never ask the user to paste code or share screenshots: work strictly "
        "with the observed timeline and attached screenshots. If the context is "
        "thin, say plainly what you can see and suggest keeping observation on longer."
    )
    SPONTANEOUS_SYSTEM_PROMPT = (
        "You are V.E.R.S.O., a benevolent copilot, silent by default. "
        "Analyze the activity timeline. If and only if you detect a "
        "high-value fact (prolonged stall, repeated attempts without progress, "
        "notable context switch, important milestone reached), reply with a "
        'strict JSON object {"speak": true, "message": "..."}: 1 to 2 '
        "constructive, concrete sentences in English. Otherwise reply exactly "
        '{"speak": false, "message": ""}. JSON object only.'
    )

    def evaluate_spontaneous(self, timeline: str) -> Dict[str, Any]:
        """
        Strictly arbitrates whether a spontaneous intervention is warranted.

        Returns {"speak": bool, "message": str}. Silence by default: any
        failure, empty timeline, or missing API key stays silent.
        """
        fallback: Dict[str, Any] = {"speak": False, "message": ""}
        if not self.is_configured:
            return dict(fallback)
        if not (timeline or "").strip():
            return dict(fallback)
        try:
            content = self._request(
                self.SPONTANEOUS_SYSTEM_PROMPT,
                f"Recent timeline:\n{_truncate_tail(timeline, 3000)}",
                MUSE_MAX_TOKENS_SUGGESTION,
            )
            parsed = _parse_json_object(content)
            if parsed.get("speak") is True and str(parsed.get("message", "")).strip():
                return {"speak": True, "message": str(parsed["message"]).strip()}
            return dict(fallback)
        except Exception as exc:
            logger.warning(
                "Muse (%s) spontaneous check failed (%s); staying silent.",
                self.model_name,
                exc,
            )
            return dict(fallback)

    def ask_companion(
        self,
        timeline: str,
        question: str,
        image_paths: Optional[List[str]] = None,
        on_delta: Optional[Any] = None,
    ) -> str:
        """
        Answers an on-demand question from the observed timeline and attached
        screenshots (English, copilot tone, grounded in observed facts).
        When ``on_delta`` is given, the answer is streamed and each text chunk
        is forwarded as it arrives (falling back to a plain request if the
        stream fails). Retries text-only if the vision request fails;
        elegant offline fallback.
        """
        question = (question or "").strip() or "What do you think?"
        clipped_timeline = _truncate_tail(timeline or "", 3000)

        seen: List[str] = []
        for line in (timeline or "").splitlines():
            head = line.split("]", 1)[-1].split("—", 1)[0].strip() if "]" in line else ""
            if head and head not in seen and head != "?":
                seen.append(head)
            if len(seen) >= 3:
                break
        apps = ", ".join(seen)

        def fallback() -> str:
            if apps:
                return (
                    "From what I observed this session "
                    f"({apps}), my take: keep going, and feel free to ask me again "
                    "once I am back online for a deeper analysis. (Offline mode)"
                )
            return (
                "I do not have enough observed context yet to give a useful opinion, "
                "and I am currently offline. Keep observation running for a few "
                "minutes. (Offline mode)"
            )

        if not self.is_configured:
            return fallback()

        prompt = (
            f"Observed context:\n{clipped_timeline}\n\n"
            f"User question: '{_truncate(question)}'\n\n"
            "Reply in English, concisely and grounded in the observed facts and screenshots."
        )
        images = [path for path in (image_paths or []) if path]
        max_tokens = max(MUSE_MAX_TOKENS_FINALIZE, 1500)

        def generate(with_images: Optional[List[str]]) -> str:
            if on_delta is not None:
                try:
                    return self._request_stream(
                        self.COMPANION_SYSTEM_PROMPT,
                        prompt,
                        max_tokens,
                        images=with_images,
                        on_delta=on_delta,
                    )
                except Exception as stream_exc:
                    logger.warning(
                        "Muse (%s) streaming failed (%s), retrying plain request.",
                        self.model_name,
                        stream_exc,
                    )
                    return self._request(
                        self.COMPANION_SYSTEM_PROMPT,
                        prompt,
                        max_tokens,
                        images=with_images,
                    )
            return self._request(
                self.COMPANION_SYSTEM_PROMPT,
                prompt,
                max_tokens,
                images=with_images,
            )

        try:
            content = generate(images or None)
        except Exception as exc:
            if not images:
                logger.warning(
                    "Muse (%s) companion answer failed (%s), using offline fallback.",
                    self.model_name,
                    exc,
                )
                return fallback()
            logger.warning(
                "Muse (%s) vision answer failed (%s), retrying text-only.",
                self.model_name,
                exc,
            )
            try:
                content = generate(None)
            except Exception as retry_exc:
                logger.warning(
                    "Muse (%s) text-only retry failed (%s), using offline fallback.",
                    self.model_name,
                    retry_exc,
                )
                return fallback()
        final = content.strip()
        if not final:
            logger.warning("Muse returned an empty companion answer, using offline fallback.")
            return fallback()
        return final
