"""
V.E.R.S.O. - Meta Muse AI Client
Handles communication with the external Meta Muse API,
"""

import logging
from typing import Any, Dict, Optional

import requests

from verso.config import META_MUSE_API_KEY, META_MUSE_ENDPOINT

logger = logging.getLogger(__name__)


class MuseClient:
    """Client for Meta Muse API with fallback support."""

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

    def generate_response(self, prompt: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Queries Meta Muse API or returns fallback if unavailable.
        """
        if not self.is_configured:
            logger.info("Meta Muse API not configured, using offline fallback.")
            return self._fallback_response(prompt, context)

        try:
            payload = {
                "prompt": prompt,
                "context": context or "",
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Meta Muse request failed (%s). Activating fallback mode.", exc)
            return self._fallback_response(prompt, context)

    def _fallback_response(self, prompt: str, context: Optional[str] = None) -> Dict[str, Any]:
        """Offline resilient fallback response."""
        return {
            "notification": "V.E.R.S.O. analyzed your context and prepared a document.",
            "action_title": "Proactive Contextual Analysis",
            "content": f"# V.E.R.S.O. Report\n\nAutomated analysis generated for: {context or 'Active Session'}\n\nKey recommendations and deliverables ready.",
            "is_fallback": True,
        }
