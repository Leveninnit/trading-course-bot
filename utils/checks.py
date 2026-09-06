import discord
from discord import app_commands

import config


def _has_any_role(member: discord.Member, role_ids) -> bool:
    ids = {int(r) for r in role_ids if r}
    if not ids:
        return False
    user_role_ids = {r.id for r in member.roles}
    return bool(ids & user_role_ids)


def is_staff():
    """Passes for server admins, or anyone holding a staff_role_id / admin_role_id from config.json."""

    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        if member.guild_permissions.administrator:
            return True
        staff_ids = list(config.get("staff_role_ids", [])) + list(config.get("admin_role_ids", []))
        return _has_any_role(member, staff_ids)

    return app_commands.check(predicate)


def is_admin():
    """Passes for server admins, or anyone holding an admin_role_id from config.json. Use for access/money commands."""

    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        if member.guild_permissions.administrator:
            return True
        return _has_any_role(member, config.get("admin_role_ids", []))

    return app_commands.check(predicate)


def is_owner():
    """Passes only for the hardcoded bot owner (config.OWNER_ID) -- independent of server roles or
    Administrator permission. Use for bot-level config commands that should never be delegable."""

    async def predicate(interaction: discord.Interaction) -> bool:
        return config.OWNER_ID is not None and interaction.user.id == config.OWNER_ID

    return app_commands.check(predicate)
