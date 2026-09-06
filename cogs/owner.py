"""Owner-only live configuration. Locked to config.OWNER_ID regardless of server roles or
Administrator permission -- this is separate from /grant-access and the staff/admin role system.

Note: config.json lives on the host's disk. On Render's free tier that disk is only wiped by a
full rebuild (a new deploy) -- not by an ordinary idle spin-down/wake -- so edits made here stick
across normal sleep cycles, but a future code push (or manual redeploy) resets config.json back to
whatever's committed on GitHub. Re-apply any live edits after a deploy if that happens.
"""

import json

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.checks import is_owner
from utils.embeds import brand_embed

# Sections that are better managed through their own dedicated command -- still readable here,
# but /config set nudges people toward the real thing instead of a blind overwrite.
_DISCOURAGED_KEYS = {"faq"}


def _walk_paths(node, prefix="", depth=0, max_depth=3):
    """Yield dotted key paths through nested dicts, for autocomplete (e.g. membership_tiers.vip.role_id)."""
    if depth >= max_depth or not isinstance(node, dict):
        return
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        yield path
        if isinstance(value, dict):
            yield from _walk_paths(value, path, depth + 1, max_depth)


def _get_path(node, path):
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(path)
        node = node[part]
    return node


def _set_path(node, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def _coerce(raw: str, current):
    """Best-effort coercion of a typed-in string to match the shape of the existing value."""
    if raw.strip().lower() == "null":
        return None
    if isinstance(current, bool):
        return raw.strip().lower() in ("true", "yes", "1", "on")
    if isinstance(current, list):
        items = [item.strip() for item in raw.split(",") if item.strip()]
        return [int(item) if item.lstrip("-").isdigit() else item for item in items]
    if isinstance(current, int):
        try:
            return int(raw)
        except ValueError:
            return raw
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


class Owner(commands.Cog):
    """Bot-owner-only tools -- currently just live config.json editing, no redeploy needed."""

    config_group = app_commands.Group(name="config", description="[Owner only] View or edit the bot's config live.")

    def __init__(self, bot):
        self.bot = bot

    async def autocomplete_key(self, interaction: discord.Interaction, current: str):
        matches = [p for p in _walk_paths(config.CONFIG) if current.lower() in p.lower()]
        return [app_commands.Choice(name=p, value=p) for p in matches[:25]]

    @config_group.command(name="list", description="[Owner] List every config key and its current value.")
    @is_owner()
    async def config_list(self, interaction: discord.Interaction):
        lines = []
        for key, value in config.CONFIG.items():
            preview = json.dumps(value, ensure_ascii=False)
            if len(preview) > 60:
                preview = preview[:57] + "..."
            lines.append(f"`{key}` = {preview}")
        embed = brand_embed(title="⚙️ Current Config", description="\n".join(lines))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name="get", description="[Owner] Show the current value of one config key.")
    @app_commands.describe(key="Config key -- e.g. mod_log_channel_id, or a dotted path like membership_tiers.vip.role_id")
    @app_commands.autocomplete(key=autocomplete_key)
    @is_owner()
    async def config_get(self, interaction: discord.Interaction, key: str):
        try:
            value = _get_path(config.CONFIG, key)
        except KeyError:
            await interaction.response.send_message(f"No such config key: `{key}`", ephemeral=True)
            return
        pretty = json.dumps(value, indent=2, ensure_ascii=False)
        await interaction.response.send_message(f"`{key}` =\n```json\n{pretty}\n```", ephemeral=True)

    @config_group.command(name="set", description="[Owner] Set a config key live and save it -- no redeploy needed.")
    @app_commands.describe(
        key="Config key -- e.g. mod_log_channel_id, or a dotted path like membership_tiers.vip.role_id",
        value="New value. Comma-separate for list fields, or 'null' to clear.",
    )
    @app_commands.autocomplete(key=autocomplete_key)
    @is_owner()
    async def config_set(self, interaction: discord.Interaction, key: str, value: str):
        try:
            current = _get_path(config.CONFIG, key)
        except KeyError:
            current = None

        if isinstance(current, dict):
            await interaction.response.send_message(
                f"`{key}` is a whole section, not a single value -- target a field inside it instead, "
                f"e.g. `{key}.some_field`.",
                ephemeral=True,
            )
            return

        new_value = _coerce(value, current)
        _set_path(config.CONFIG, key, new_value)

        with open(config.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config.CONFIG, f, indent=2, ensure_ascii=False)
            f.write("\n")
        config.reload_config()

        note = ""
        top_level = key.split(".")[0]
        if top_level in _DISCOURAGED_KEYS:
            note = f"\n\n⚠️ `{top_level}` is normally managed with its own command (e.g. /faq) -- double-check this did what you wanted."

        pretty = json.dumps(new_value, indent=2, ensure_ascii=False)
        await interaction.response.send_message(f"✅ `{key}` set to\n```json\n{pretty}\n```{note}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Owner(bot))
