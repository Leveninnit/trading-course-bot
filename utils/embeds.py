from datetime import datetime, timezone

import discord

import config


def brand_color() -> discord.Color:
    raw = config.get("brand_color", "0xF1C40F")
    try:
        value = int(str(raw), 16) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError):
        value = 0xF1C40F
    return discord.Color(value)


def brand_embed(title: str = None, description: str = None, color: discord.Color = None) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color or brand_color(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=config.get("brand_name", "Trading Course"))
    return embed
