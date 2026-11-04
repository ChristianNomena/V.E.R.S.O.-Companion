"""
V.E.R.S.O. - Application Configuration
Centralized configuration loader using python-dotenv.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Locate and load .env file from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()  # Default search in current environment

# Database Configuration
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///verso_companion.db")

# External AI Service (Meta Muse API)
DEFAULT_META_ENDPOINT = "https://api.meta.ai/v1"
META_MUSE_API_KEY: str = os.getenv("META_MUSE_API_KEY", "")
META_MUSE_ENDPOINT: str = os.getenv("META_MUSE_ENDPOINT", "").strip() or DEFAULT_META_ENDPOINT

# Muse generation tuning (cost/latency optimized defaults)
# Default model follows the official Meta API example.
MUSE_MODEL: str = os.getenv("MUSE_MODEL", "muse-wonder-1.0")
MUSE_TEMPERATURE: float = float(os.getenv("MUSE_TEMPERATURE", "0.3"))
MUSE_MAX_TOKENS_SUGGESTION: int = int(os.getenv("MUSE_MAX_TOKENS_SUGGESTION", "800"))
MUSE_MAX_TOKENS_FINALIZE: int = int(os.getenv("MUSE_MAX_TOKENS_FINALIZE", "800"))
MUSE_TIMEOUT: float = float(os.getenv("MUSE_TIMEOUT", "15.0"))
MUSE_MAX_RETRIES: int = int(os.getenv("MUSE_MAX_RETRIES", "2"))
MUSE_MAX_INPUT_CHARS: int = int(os.getenv("MUSE_MAX_INPUT_CHARS", "1500"))
MUSE_CACHE_TTL_SECONDS: float = float(os.getenv("MUSE_CACHE_TTL_SECONDS", "300.0"))
MUSE_CACHE_MAX_ENTRIES: int = int(os.getenv("MUSE_CACHE_MAX_ENTRIES", "64"))

# Text-to-Speech (TTS) Voice Configuration (Defaulting to native English voice)
TTS_VOICE_NAME: str = os.getenv("TTS_VOICE_NAME", "Samantha")
TTS_SPEECH_RATE: int = int(os.getenv("TTS_SPEECH_RATE", "185"))
