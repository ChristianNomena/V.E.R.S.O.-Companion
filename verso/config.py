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
META_MUSE_API_KEY: str = os.getenv("META_MUSE_API_KEY", "")
META_MUSE_ENDPOINT: str = os.getenv("META_MUSE_ENDPOINT", "")
