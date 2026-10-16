from __future__ import annotations
import os
from pathlib import Path

APP_NAME = "SteelMind AI"
APP_VERSION = "1.0.0"
DB_PATH = os.getenv("STEELMIND_DB_PATH", str(Path("data") / "steelmind.db"))
DEMO_SEED_ENABLED = os.getenv("STEELMIND_ENABLE_DEMO_SEED", "false").lower() in {"1", "true", "yes"}
API_BASE_URL = os.getenv("STEELMIND_API_URL", "http://127.0.0.1:8000")
DEFAULT_KERF_MM = float(os.getenv("STEELMIND_DEFAULT_KERF_MM", "3.0"))
DEFAULT_EDGE_TRIM_MM = float(os.getenv("STEELMIND_DEFAULT_EDGE_TRIM_MM", "10.0"))
LLM_ENABLED = os.getenv("STEELMIND_LLM_ENABLED", "false").lower() in {"1", "true", "yes"}
LLM_BASE_URL = os.getenv("STEELMIND_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_API_KEY = os.getenv("STEELMIND_LLM_API_KEY", "")
LLM_MODEL = os.getenv("STEELMIND_LLM_MODEL", "")
LLM_TIMEOUT_SECONDS = float(os.getenv("STEELMIND_LLM_TIMEOUT_SECONDS", "12"))
