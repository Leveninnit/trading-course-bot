import asyncio
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
STICKY_DEBOUNCE_SECONDS = 3


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Rolling per-user timestamp windows for spam detection (in-memory; resets on restart, which is fine).
        self.message_times = defaultdict(lambda: deque(maxlen=10))
        # Channel IDs with a sticky repost already scheduled, so a burst of messages only reposts once.
        self._sticky_pending = set()

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

    @commands.Cog.listener(name="on_message")
    async def _sticky_repost(self, message: discord.Message):
        """Keeps this channel's sticky message (if any) pinned to the bottom by reposting it after new activity."""
        if message.guild is None or message.author.bot:
            return

        channel_id = message.channel.id
        sticky = await self.bot.db.get_sticky(message.guild.id, channel_id)
        if not sticky:
            return

        if channel_id in self._sticky_pending:
            return
        self._sticky_pending.add(channel_id)
        asyncio.create_task(self._repost_sticky_after_delay(message.guild.id, message.channel))

    async def _repost_sticky_after_delay(self, guild_id, channel):
        try:
            await asyncio.sleep(STICKY_DEBOUNCE_SECONDS)
            sticky = await self.bot.db.get_sticky(guild_id, channel.id)
            if not sticky:
                return

            if sticky.get("last_message_id"):
                try:
                    old_msg = await channel.fetch_message(sticky["last_message_id"])
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

            embed = brand_embed(title="📌 Sticky Message", description=sticky["content"])
            try:
                sent = await channel.send(embed=embed)
                await self.bot.db.update_sticky_message(guild_id, channel.id, sent.id)
            except discord.HTTPException:
                pass
        finally:
            self._sticky_pending.discard(channel.id)

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

    @app_commands.command(name="purge", description="[Staff] Bulk-delete recent messages in this channel.")
    @app_commands.describe(amount="How many messages to delete (1-100)")
    @is_staff()
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount)
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to delete messages here.", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send(
                "Couldn't delete those messages (Discord can only bulk-delete messages younger than 14 days).",
                ephemeral=True,
            )
            return
        await self.bot.db.add_mod_action(
            interaction.guild.id, interaction.user.id, interaction.user.id, "purge", f"Purged {len(deleted)} message(s)"
        )
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} message(s).", ephemeral=True)

    @app_commands.command(name="slowmode", description="[Staff] Set this channel's slowmode delay.")
    @app_commands.describe(seconds="Delay between messages, in seconds (0 disables it, max 21600)")
    @is_staff()
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await interaction.response.send_message("Slowmode disabled for this channel.")
        else:
            await interaction.response.send_message(f"Slowmode set to {seconds} second(s) for this channel.")

    @app_commands.command(name="lock", description="[Staff] Lock this channel so @everyone can't send messages.")
    @is_staff()
    async def lock(self, interaction: discord.Interaction, reason: str = "No reason provided"):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason)
        embed = brand_embed(
            title="🔒 Channel Locked", description=f"{interaction.channel.mention} has been locked.\n**Reason:** {reason}"
        )
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

    @app_commands.command(name="unlock", description="[Staff] Unlock this channel.")
    @is_staff()
    async def unlock(self, interaction: discord.Interaction):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        embed = brand_embed(title="🔓 Channel Unlocked", description=f"{interaction.channel.mention} has been unlocked.")
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

    sticky_group = app_commands.Group(name="sticky", description="[Staff] Manage this channel's sticky message")

    @sticky_group.command(name="set", description="[Staff] Post a sticky message that stays at the bottom of this channel.")
    @app_commands.describe(message="The content of the sticky message")
    @is_staff()
    async def sticky_set(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        old = await self.bot.db.get_sticky(interaction.guild.id, interaction.channel.id)
        if old and old.get("last_message_id"):
            try:
                old_msg = await interaction.channel.fetch_message(old["last_message_id"])
                await old_msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        embed = brand_embed(title="📌 Sticky Message", description=message)
        sent = await interaction.channel.send(embed=embed)
        await self.bot.db.set_sticky(interaction.guild.id, interaction.channel.id, message, interaction.user.id, sent.id)
        await interaction.followup.send(
            "Sticky message set for this channel. It'll repost itself to stay at the bottom.", ephemeral=True
        )

    @sticky_group.command(name="remove", description="[Staff] Remove this channel's sticky message.")
    @is_staff()
    async def sticky_remove(self, interaction: discord.Interaction):
        sticky = await self.bot.db.get_sticky(interaction.guild.id, interaction.channel.id)
        if not sticky:
            await interaction.response.send_message("This channel doesn't have a sticky message.", ephemeral=True)
            return
        if sticky.get("last_message_id"):
            try:
                old_msg = await interaction.channel.fetch_message(sticky["last_message_id"])
                await old_msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self.bot.db.remove_sticky(interaction.guild.id, interaction.channel.id)
        await interaction.response.send_message("Sticky message removed.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
