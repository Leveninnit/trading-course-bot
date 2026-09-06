import random
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

import config
from utils.embeds import brand_embed
from utils.checks import is_staff
from utils.leveling import xp_threshold


class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id: int):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.enter.custom_id = f"giveaway:enter:{giveaway_id}"

    @discord.ui.button(label="🎉 Enter Giveaway", style=discord.ButtonStyle.primary)
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        added = await bot.db.add_giveaway_entry(self.giveaway_id, interaction.user.id)
        if added:
            await interaction.response.send_message("You're entered! Good luck 🍀", ephemeral=True)
        else:
            await interaction.response.send_message("You're already entered.", ephemeral=True)


class Engagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    async def cog_load(self):
        # Re-register persistent "Enter Giveaway" buttons for anything still running after a restart.
        active = await self.bot.db.get_active_giveaways()
        for g in active:
            self.bot.add_view(GiveawayView(g["id"]))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        cooldown = config.get("xp_cooldown_seconds", 60)
        amount = config.get("xp_per_message", 15)
        result = await self.bot.db.try_add_xp(message.guild.id, message.author.id, amount, cooldown)
        if result is None:
            return
        _xp, old_level, new_level = result
        if new_level > old_level:
            channel_id = config.get("level_up_channel_id")
            channel = message.guild.get_channel(int(channel_id)) if channel_id else message.channel
            if channel:
                embed = brand_embed(
                    title="🎉 Level Up!", description=f"{message.author.mention} just reached **Level {new_level}**!"
                )
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    @app_commands.command(name="rank", description="See your (or someone else's) level and XP.")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        xp, level = await self.bot.db.get_xp(interaction.guild.id, member.id)
        need = xp_threshold(level + 1)
        embed = brand_embed(title=f"{member.display_name}'s Rank", description=f"**Level:** {level}\n**XP:** {xp} / {need}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="See the server's XP leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_leaderboard(interaction.guild.id, limit=10)
        if not rows:
            await interaction.response.send_message("No activity yet!", ephemeral=True)
            return
        lines = [f"**{i}.** <@{user_id}> -- Level {level} ({xp} XP)" for i, (user_id, xp, level) in enumerate(rows, start=1)]
        embed = brand_embed(title="🏆 Leaderboard", description="\n".join(lines))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily XP reward (streaks earn bonus XP).")
    async def daily(self, interaction: discord.Interaction):
        base_xp = config.get("daily_base_xp", 50)
        bonus_xp = config.get("daily_streak_bonus_xp", 5)
        awarded, streak, seconds_left = await self.bot.db.claim_daily(
            interaction.guild.id, interaction.user.id, base_xp, bonus_xp
        )
        if awarded is None:
            hours, remainder = divmod(seconds_left, 3600)
            minutes = remainder // 60
            await interaction.response.send_message(
                f"You've already claimed today's reward. Come back in **{hours}h {minutes}m** "
                f"(current streak: {streak} 🔥).",
                ephemeral=True,
            )
            return
        embed = brand_embed(
            title="✅ Daily Reward Claimed!",
            description=f"You earned **{awarded} XP**!\n**Streak:** {streak} day(s) 🔥",
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="profile", description="View your (or someone else's) trading course profile.")
    async def profile(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        xp, level = await self.bot.db.get_xp(interaction.guild.id, member.id)
        need = xp_threshold(level + 1)
        membership = await self.bot.db.get_membership(interaction.guild.id, member.id)

        if membership:
            tier_cfg = config.get("membership_tiers", {}).get(membership["tier"], {})
            tier_label = tier_cfg.get("label", membership["tier"].title())
            if membership.get("expires_at"):
                expiry = f"<t:{int(membership['expires_at'])}:R>"
            else:
                expiry = "Never (lifetime)"
            membership_line = f"**{tier_label}** -- expires {expiry}"
        else:
            membership_line = "None"

        embed = brand_embed(title=f"{member.display_name}'s Profile")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=str(level), inline=True)
        embed.add_field(name="XP", value=f"{xp} / {need}", inline=True)
        embed.add_field(
            name="Joined Server",
            value=discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "Unknown",
            inline=True,
        )
        embed.add_field(name="Membership", value=membership_line, inline=False)
        await interaction.response.send_message(embed=embed)

    giveaway_group = app_commands.Group(name="giveaway", description="Manage giveaways")

    @giveaway_group.command(name="start", description="[Staff] Start a giveaway.")
    @is_staff()
    async def giveaway_start(self, interaction: discord.Interaction, prize: str, duration_minutes: int, winners: int = 1):
        end_time = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        embed = brand_embed(
            title="🎉 Giveaway!",
            description=(
                f"**Prize:** {prize}\n**Winners:** {winners}\n"
                f"**Ends:** <t:{int(end_time.timestamp())}:R>\n\nClick below to enter!"
            ),
        )
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        giveaway_id = await self.bot.db.create_giveaway(
            interaction.guild.id, interaction.channel.id, message.id, prize, winners, end_time.timestamp(), interaction.user.id
        )
        view = GiveawayView(giveaway_id)
        self.bot.add_view(view)
        await message.edit(view=view)

    @giveaway_group.command(name="end", description="[Staff] End a giveaway early.")
    @is_staff()
    async def giveaway_end(self, interaction: discord.Interaction, message_id: str):
        try:
            giveaway = await self.bot.db.get_giveaway_by_message(int(message_id))
        except ValueError:
            giveaway = None
        if not giveaway or giveaway["ended"]:
            await interaction.response.send_message("Couldn't find an active giveaway with that message ID.", ephemeral=True)
            return
        await self._finish_giveaway(giveaway)
        await interaction.response.send_message("Giveaway ended.", ephemeral=True)

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        now = datetime.now(timezone.utc).timestamp()
        active = await self.bot.db.get_active_giveaways()
        for g in active:
            if g["end_time"] <= now:
                await self._finish_giveaway(g)

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()

    async def _finish_giveaway(self, giveaway: dict):
        await self.bot.db.end_giveaway(giveaway["id"])
        entries = await self.bot.db.get_giveaway_entries(giveaway["id"])
        channel = self.bot.get_channel(giveaway["channel_id"])
        if not channel:
            return
        try:
            if not entries:
                await channel.send(f"No one entered the giveaway for **{giveaway['prize']}**. 😢")
                return
            winners = random.sample(entries, min(giveaway["winners_count"], len(entries)))
            mentions = ", ".join(f"<@{w}>" for w in winners)
            await channel.send(f"🎉 Congratulations {mentions}! You won **{giveaway['prize']}**!")
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Engagement(bot))
