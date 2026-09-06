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


def get(key, default=None):
    return CONFIG.get(key, default)


def reload_config() -> dict:
    """Re-read config.json from disk (useful after editing it without restarting the bot)."""
    global CONFIG
    CONFIG = load_config()
    return CONFIG
