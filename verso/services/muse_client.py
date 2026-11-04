"""
V.E.R.S.O. - Meta Muse AI Client (Pillar 1: The Inverse OS)
Handles communication with the external Meta Muse API for Slack intention delegation,
with local resilient fallback support.
"""

import json
import logging
from typing import Any, Dict, Optional

import requests

from verso.config import META_MUSE_API_KEY, META_MUSE_ENDPOINT

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are V.E.R.S.O. (Vigilant Empathetic Real-time System Orchestrator).
Your role: Silently assist the user by analyzing incoming Slack communications and crafting clear, professional, and empathetic draft responses.
You must output a strict JSON object with the following keys:
- "notification": Concise push notification alert (e.g. "Slack response draft ready in deliverables/SLACK_DRAFT.md").
- "action_title": Short descriptive title of the action (e.g. "Drafted Slack Response").
- "content": Clean, complete Markdown deliverable with the incoming context and the ready-to-use draft response.
"""


class MuseClient:
    """Client for Meta Muse API with fallback support for offline resilience."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key or META_MUSE_API_KEY
        self.endpoint = endpoint or META_MUSE_ENDPOINT
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Returns True if API credentials are present."""
        return bool(self.api_key and self.endpoint)

    def generate_response(
        self, prompt: str, context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Queries Meta Muse API or returns a structured fallback if unavailable.
        """
        if not self.is_configured:
            logger.info("Meta Muse API credentials absent, using offline fallback.")
            return self._fallback_response(prompt, context)

        try:
            payload = {
                "system_instruction": SYSTEM_PROMPT,
                "prompt": prompt,
                "context": context or "",
                "response_format": "json",
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.post(
                self.endpoint, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "content" in data:
                return data
            # If wrapped in string
            if isinstance(data, str):
                return json.loads(data)
            return self._fallback_response(prompt, context)
        except Exception as exc:
            logger.warning(
                "Meta Muse request failed (%s). Activating resilient fallback mode.",
                exc,
            )
            return self._fallback_response(prompt, context)

    def _fallback_response(
        self, prompt: str, context: Optional[str] = None
    ) -> Dict[str, Any]:
        """Offline resilient fallback response producing a clean Slack draft."""
        incoming_text = context or prompt or "Incoming message"

        content = (
            "# Slack Response Draft\n\n"
            "## Incoming Context\n"
            f"> {incoming_text}\n\n"
            "## Proposed Response (Ready to Send)\n"
            "Hello! Thank you for the update. I have reviewed the details and I am taking care of this right away. "
            "I'll follow up with you as soon as it's completed.\n\n"
            "---\n"
            "*Generated silently by V.E.R.S.O.*\n"
        )

        return {
            "notification": "Slack draft ready in deliverables/SLACK_DRAFT.md",
            "action_title": "Draft Slack Response",
            "content": content,
            "is_fallback": True,
        }
