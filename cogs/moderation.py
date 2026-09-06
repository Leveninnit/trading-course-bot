import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord.ext import commands
from discord import app_commands

import config
from utils.embeds import brand_embed
from utils.checks import is_staff

INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)", re.IGNORECASE)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Rolling per-user timestamp windows for spam detection (in-memory; resets on restart, which is fine).
        self.message_times = defaultdict(lambda: deque(maxlen=10))

    async def _log(self, guild: discord.Guild, embed: discord.Embed):
        channel_id = config.get("mod_log_channel_id")
        if channel_id:
            channel = guild.get_channel(int(channel_id))
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    def _is_exempt(self, member: discord.Member) -> bool:
        if member.bot:
            return True
        if member.guild_permissions.administrator:
            return True
        staff_ids = set(config.get("staff_role_ids", []) + config.get("admin_role_ids", []))
        return bool(staff_ids & {r.id for r in member.roles})

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or not isinstance(message.author, discord.Member) or self._is_exempt(message.author):
            return

        content_lower = message.content.lower()

        for word in config.get("banned_words", []):
            if word and word.lower() in content_lower:
                await self._handle_violation(message, "Used a banned word or phrase.")
                return

        for domain in config.get("scam_domains", []):
            if domain and domain.lower() in content_lower:
                await self._handle_violation(message, "Posted a known scam/phishing domain.")
                return

        if not config.get("allow_invites", False) and INVITE_RE.search(message.content):
            await self._handle_violation(message, "Posted a Discord invite link.")
            return

        now = time.time()
        dq = self.message_times[message.author.id]
        dq.append(now)
        window = config.get("spam_window_seconds", 6)
        if len(dq) == dq.maxlen and (now - dq[0]) < window:
            await self._handle_spam(message)

    async def _handle_violation(self, message: discord.Message, reason: str):
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        await self.bot.db.add_mod_action(message.guild.id, message.author.id, self.bot.user.id, "auto-delete", reason)
        embed = brand_embed(
            title="🛡️ Auto-Moderation",
            description=f"{message.author.mention} in {message.channel.mention}\n**Reason:** {reason}",
        )
        await self._log(message.guild, embed)
        try:
            await message.channel.send(f"{message.author.mention}, that message was removed: {reason}", delete_after=8)
        except discord.HTTPException:
            pass

    async def _handle_spam(self, message: discord.Message):
        member = message.author
        timeout_seconds = config.get("spam_timeout_seconds", 60)
        try:
            await member.timeout(discord.utils.utcnow() + timedelta(seconds=timeout_seconds), reason="Spamming")
        except (discord.Forbidden, discord.HTTPException):
            pass
        try:
            await message.channel.send(f"{member.mention} please slow down!", delete_after=6)
        except discord.HTTPException:
            pass
        await self.bot.db.add_mod_action(message.guild.id, member.id, self.bot.user.id, "auto-timeout", "Spam detected")
        embed = brand_embed(title="🛡️ Anti-Spam", description=f"{member.mention} was timed out for spamming.")
        await self._log(message.guild, embed)

    # ---------------- Slash commands ----------------

    @app_commands.command(name="warn", description="[Staff] Warn a member.")
    @app_commands.describe(member="The member to warn", reason="Why you're warning them")
    @is_staff()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await self.bot.db.add_mod_action(interaction.guild.id, member.id, interaction.user.id, "warn", reason)
        count = await self.bot.db.count_warnings(interaction.guild.id, member.id)

        embed = brand_embed(
            title="⚠️ Member Warned",
            description=f"{member.mention} has been warned.\n**Reason:** {reason}\n**Total warnings:** {count}",
        )
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)
        try:
            await member.send(f"You were warned in **{interaction.guild.name}**: {reason}")
        except discord.Forbidden:
            pass

        threshold = config.get("warning_auto_timeout_threshold", 3)
        if threshold and count >= threshold:
            try:
                await member.timeout(discord.utils.utcnow() + timedelta(hours=1), reason="Reached warning threshold")
                await interaction.followup.send(
                    f"{member.mention} reached {count} warnings and was auto-timed out for 1 hour."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    @app_commands.command(name="warnings", description="[Staff] View a member's warnings.")
    @is_staff()
    async def warnings_cmd(self, interaction: discord.Interaction, member: discord.Member):
        rows = await self.bot.db.get_warnings(interaction.guild.id, member.id)
        if not rows:
            await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=True)
            return
        desc = "\n".join(f"**#{r['id']}** -- {r['reason']} (by <@{r['moderator_id']}>, {r['created_at']})" for r in rows)
        embed = brand_embed(title=f"Warnings for {member}", description=desc)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarnings", description="[Staff] Clear all warnings for a member.")
    @is_staff()
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        n = await self.bot.db.clear_warnings(interaction.guild.id, member.id)
        await interaction.response.send_message(f"Cleared {n} warning(s) for {member.mention}.", ephemeral=True)

    @app_commands.command(name="kick", description="[Staff] Kick a member.")
    @is_staff()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await member.kick(reason=reason)
        await self.bot.db.add_mod_action(interaction.guild.id, member.id, interaction.user.id, "kick", reason)
        embed = brand_embed(title="👢 Member Kicked", description=f"{member} was kicked.\n**Reason:** {reason}")
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

    @app_commands.command(name="ban", description="[Staff] Ban a member.")
    @app_commands.describe(delete_days="Delete this member's messages from the last N days (0-7)")
    @is_staff()
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
        delete_days: int = 0,
    ):
        seconds = min(max(delete_days, 0), 7) * 86400
        await member.ban(reason=reason, delete_message_seconds=seconds)
        await self.bot.db.add_mod_action(interaction.guild.id, member.id, interaction.user.id, "ban", reason)
        embed = brand_embed(title="🔨 Member Banned", description=f"{member} was banned.\n**Reason:** {reason}")
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

    @app_commands.command(name="timeout", description="[Staff] Timeout a member.")
    @is_staff()
    async def timeout_cmd(
        self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"
    ):
        await member.timeout(discord.utils.utcnow() + timedelta(minutes=minutes), reason=reason)
        await self.bot.db.add_mod_action(interaction.guild.id, member.id, interaction.user.id, "timeout", reason)
        embed = brand_embed(
            title="🔇 Member Timed Out",
            description=f"{member} was timed out for {minutes} minute(s).\n**Reason:** {reason}",
        )
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

    @app_commands.command(name="untimeout", description="[Staff] Remove a member's timeout.")
    @is_staff()
    async def untimeout_cmd(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await interaction.response.send_message(f"Removed timeout for {member.mention}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
