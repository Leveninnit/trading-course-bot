import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

CONFIG_PATH = BASE_DIR / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID") or CONFIG.get("guild_id")
PORT = int(os.getenv("PORT", "8080"))

_owner_id_raw = os.getenv("OWNER_ID") or CONFIG.get("owner_id")
OWNER_ID = int(_owner_id_raw) if _owner_id_raw else None

# Optional -- AI-powered commands (/explain, /ask, /motivate, /lesson, and the upgraded /quote) are
# disabled gracefully if this isn't set. Uses OpenAI's API (platform.openai.com/api-keys) -- this is
# billed pay-as-you-go, not free, so keep an eye on usage/spend limits at platform.openai.com/usage.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get(key, default=None):
    return CONFIG.get(key, default)


def reload_config() -> dict:
    """Re-read config.json from disk (useful after editing it without restarting the bot)."""
    global CONFIG
    CONFIG = load_config()
    return CONFIG
