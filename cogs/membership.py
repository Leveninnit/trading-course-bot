from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

import config
from utils.embeds import brand_embed
from utils.checks import is_admin


class Membership(commands.Cog):
    """Paid-tier access control. Not wired up to a payment processor yet (kept simple on purpose) --
    /grant-access is the one function a future Stripe/Whop webhook handler would call too."""

    def __init__(self, bot):
        self.bot = bot
        self.check_expirations.start()

    def cog_unload(self):
        self.check_expirations.cancel()

    def _tier_role(self, guild: discord.Guild, tier: str):
        tiers = config.get("membership_tiers", {})
        info = tiers.get(tier)
        if not info or not info.get("role_id"):
            return None
        return guild.get_role(int(info["role_id"]))

    @app_commands.command(name="grant-access", description="[Admin] Grant a membership tier to a member.")
    @app_commands.describe(
        member="Member to grant access to",
        tier="Tier key from config.json (e.g. premium, vip)",
        days="Days until expiry (leave blank for lifetime access)",
    )
    @is_admin()
    async def grant_access(self, interaction: discord.Interaction, member: discord.Member, tier: str, days: int = None):
        role = self._tier_role(interaction.guild, tier)
        if not role:
            tiers = ", ".join(config.get("membership_tiers", {}).keys()) or "(none configured yet)"
            await interaction.response.send_message(
                f"Unknown tier `{tier}`, or it has no role_id set in config.json. Configured tiers: {tiers}",
                ephemeral=True,
            )
            return

        await member.add_roles(role, reason=f"Granted by {interaction.user}")
        expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).timestamp() if days else None
        await self.bot.db.grant_membership(interaction.guild.id, member.id, tier, interaction.user.id, expires_at)

        expiry_text = f"expires <t:{int(expires_at)}:R>" if expires_at else "does not expire"
        embed = brand_embed(
            title="✅ Access Granted", description=f"{member.mention} was granted **{tier}** access ({expiry_text})."
        )
        await interaction.response.send_message(embed=embed)
        try:
            await member.send(f"You've been granted **{tier}** access in **{interaction.guild.name}**! 🎉")
        except discord.Forbidden:
            pass

    @app_commands.command(name="revoke-access", description="[Admin] Revoke a member's membership tier.")
    @is_admin()
    async def revoke_access(self, interaction: discord.Interaction, member: discord.Member):
        record = await self.bot.db.get_membership(interaction.guild.id, member.id)
        if not record:
            await interaction.response.send_message(f"{member.mention} doesn't have a tracked membership.", ephemeral=True)
            return
        role = self._tier_role(interaction.guild, record["tier"])
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason=f"Revoked by {interaction.user}")
            except discord.Forbidden:
                pass
        await self.bot.db.revoke_membership(interaction.guild.id, member.id)
        await interaction.response.send_message(f"Revoked access for {member.mention}.", ephemeral=True)

    @app_commands.command(name="membership", description="Check a member's membership status.")
    async def membership_status(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        record = await self.bot.db.get_membership(interaction.guild.id, member.id)
        if not record:
            await interaction.response.send_message(
                f"{member.mention} has no tracked membership (free/default access).", ephemeral=True
            )
            return
        expiry_text = f"<t:{int(record['expires_at'])}:F>" if record["expires_at"] else "Never (lifetime)"
        embed = brand_embed(
            title="Membership Status",
            description=f"**Member:** {member.mention}\n**Tier:** {record['tier']}\n**Expires:** {expiry_text}",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="extend-access", description="[Admin] Extend a member's access by N days.")
    @is_admin()
    async def extend_access(self, interaction: discord.Interaction, member: discord.Member, days: int):
        record = await self.bot.db.extend_membership(interaction.guild.id, member.id, days * 86400)
        if not record:
            await interaction.response.send_message(
                f"{member.mention} doesn't have a tracked membership yet -- use /grant-access first.", ephemeral=True
            )
            return
        expiry_text = f"<t:{int(record['expires_at'])}:F>" if record["expires_at"] else "Never (lifetime)"
        await interaction.response.send_message(
            f"Extended {member.mention}'s access. New expiry: {expiry_text}", ephemeral=True
        )

    @tasks.loop(hours=1)
    async def check_expirations(self):
        now = datetime.now(timezone.utc).timestamp()
        for guild in self.bot.guilds:
            expired = await self.bot.db.get_expired_memberships(guild.id, now)
            for record in expired:
                member = guild.get_member(record["user_id"])
                role = self._tier_role(guild, record["tier"])
                if member and role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Membership expired")
                    except discord.Forbidden:
                        pass
                await self.bot.db.revoke_membership(guild.id, record["user_id"])

                log_channel_id = config.get("mod_log_channel_id")
                if log_channel_id:
                    channel = guild.get_channel(int(log_channel_id))
                    if channel:
                        await channel.send(
                            embed=brand_embed(
                                title="⏰ Access Expired",
                                description=f"<@{record['user_id']}>'s **{record['tier']}** access expired and was removed.",
                            )
                        )
                if member:
                    try:
                        await member.send(f"Your **{record['tier']}** access in **{guild.name}** has expired.")
                    except discord.Forbidden:
                        pass

    @check_expirations.before_loop
    async def before_check_expirations(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Membership(bot))
