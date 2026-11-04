"""
V.E.R.S.O. - Meta Muse AI Client (Pillar 1: The Inverse OS)
Handles communication with the external Meta Muse API (Muse Spark 1.3)
for Slack intention delegation, vocal assistance, and local resilient fallback.
"""

import json
import logging
from typing import Any, Dict, Optional

import requests

from verso.config import META_MUSE_API_KEY, META_MUSE_ENDPOINT

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are V.E.R.S.O. (Vigilant Empathetic Real-time System Orchestrator).
You are an ambient AI companion who proactively speaks to the user upon incoming Slack communications.
You read the message out loud, suggest a sensible response, and refine it based on what the user speaks back.
"""


class MuseClient:
    """Client for Meta Muse API (Muse Spark 1.3) with resilient fallback support."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model_name: str = "muse-spark-1.3",
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key or META_MUSE_API_KEY
        self.endpoint = endpoint or META_MUSE_ENDPOINT
        self.model_name = model_name
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Returns True if API credentials are present."""
        return bool(self.api_key and self.endpoint)

    @property
    def chat_endpoint(self) -> str:
        """Returns the full chat completions URL."""
        base = (self.endpoint or "https://api.meta.ai/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def generate_vocal_suggestion(self, incoming_context: str) -> Dict[str, str]:
        """
        Analyzes the incoming communication using Muse Spark 1.3.
        Returns:
            - sender: Name of sender (e.g. 'Sarah')
            - spoken_intro: Message read out loud to user
            - spoken_suggestion: Assistant's proposed action asked out loud
            - suggested_reply: Full textual drafted response
        """
        # Extract sender if present
        clean_msg = incoming_context.strip()
        sender = "Slack"
        if "From " in clean_msg and ":" in clean_msg:
            try:
                parts = clean_msg.split("From ", 1)[1].split(":", 1)
                sender = parts[0].strip()
                clean_msg = parts[1].strip()
            except Exception:
                pass

        if not self.is_configured:
            # Resilient intelligent fallback in English
            return {
                "sender": sender,
                "spoken_intro": f"Message from {sender}: '{clean_msg}'",
                "spoken_suggestion": "I suggest replying that you are taking care of this right away. What do you think?",
                "suggested_reply": f"Hello {sender}, thank you for reaching out! I am taking care of this right away and will follow up shortly.",
            }

        try:
            prompt = (
                f"A new communication arrived: '{clean_msg}' from '{sender}'.\n"
                "Respond with a strict JSON object with these exact keys:\n"
                '- "spoken_intro": Short sentence reading the message in natural English to the user.\n'
                '- "spoken_suggestion": Short question in natural English proposing a helpful response.\n'
                '- "suggested_reply": Professional and friendly response draft ready to send.\n'
            )
            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.post(self.chat_endpoint, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            parsed["sender"] = sender
            return parsed
        except Exception as exc:
            logger.warning("Muse Spark 1.3 request failed (%s), using resilient voice template.", exc)
            return {
                "sender": sender,
                "spoken_intro": f"Message from {sender}: '{clean_msg}'",
                "spoken_suggestion": "I suggest confirming receipt and following up soon. What do you think?",
                "suggested_reply": f"Hello {sender}, message received! I will take care of this and follow up shortly.",
            }

    def finalize_response(
        self,
        incoming_message: str,
        suggested_reply: str,
        user_speech: str,
    ) -> str:
        """
        Finalizes the draft response based on user's vocal feedback.
        If user approved ('yes', 'approve', 'confirm', 'go'), keeps suggested_reply.
        If user gave counter-instructions, refines draft using Muse Spark 1.3.
        """
        user_lower = user_speech.lower().strip()
        approvals = ["yes", "approve", "confirm", "ok", "go", "sure", "sounds good", "send it", "do it", "perfect"]

        if any(w in user_lower for w in approvals) and len(user_lower.split()) <= 6:
            return suggested_reply

        if not self.is_configured:
            # Fallback adapting to custom instruction
            return (
                f"Hello,\n\n"
                f"Following up on your message: {user_speech.strip()}.\n\n"
                f"Best regards."
            )

        try:
            prompt = (
                f"Original incoming message: '{incoming_message}'\n"
                f"Initially suggested response: '{suggested_reply}'\n"
                f"User vocal directive: '{user_speech}'\n\n"
                "Draft the final Slack message following the user's vocal instruction. "
                "Output only the final message text in English, clear, professional, and ready to send."
            )
            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.post(self.chat_endpoint, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            logger.warning("Muse Spark refinement failed (%s), using direct template.", exc)
            return f"Hello,\n\nRegarding your message: {user_speech.strip()}.\n\nBest regards."

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
