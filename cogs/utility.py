import re
import time

import discord
from discord.ext import commands, tasks
from discord import app_commands

from utils.embeds import brand_embed

POLL_NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

_DURATION_RE = re.compile(r"^(\d+)\s*([smhd]?)$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "": 60}  # a bare number means minutes
MAX_REMINDER_SECONDS = 60 * 60 * 24 * 30  # 30 days


def parse_duration(text: str) -> int:
    """Parses strings like '10', '10m', '2h', '1d', '45s' into a number of seconds.

    A bare number (no letter suffix) is treated as minutes. Raises ValueError on anything else.
    """
    match = _DURATION_RE.match(text.strip())
    if not match:
        raise ValueError(f"Unrecognized duration: {text!r}")
    amount, unit = match.groups()
    seconds = int(amount) * _UNIT_SECONDS[unit.lower()]
    if seconds <= 0:
        raise ValueError("Duration must be positive")
    return seconds


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    @app_commands.command(name="userinfo", description="See information about yourself or another member.")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
        roles_text = ", ".join(roles) if roles else "None"
        if len(roles_text) > 1024:
            roles_text = roles_text[:1000] + "... (truncated)"

        embed = brand_embed(title=str(member))
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Nickname", value=member.nick or "None", inline=True)
        embed.add_field(name="Bot?", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, style="R"), inline=True)
        embed.add_field(
            name="Joined Server",
            value=discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "Unknown",
            inline=True,
        )
        embed.add_field(name=f"Roles ({len(roles)})", value=roles_text, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="See information about this server.")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = brand_embed(title=guild.name)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="Members", value=str(guild.member_count), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, style="R"), inline=True)
        embed.add_field(name="Text Channels", value=str(len(guild.text_channels)), inline=True)
        embed.add_field(name="Voice Channels", value=str(len(guild.voice_channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        embed.add_field(
            name="Boost Level",
            value=f"Level {guild.premium_tier} ({guild.premium_subscription_count} boosts)",
            inline=True,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Get someone's avatar in full size.")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = brand_embed(title=f"{member.display_name}'s Avatar")
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="poll", description="Start a quick community poll.")
    @app_commands.describe(
        question="The poll question",
        option1="First option",
        option2="Second option",
        option3="Third option (optional)",
        option4="Fourth option (optional)",
        option5="Fifth option (optional)",
    )
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str = None,
        option4: str = None,
        option5: str = None,
    ):
        options = [o for o in [option1, option2, option3, option4, option5] if o]
        lines = [f"{POLL_NUMBER_EMOJIS[i]} {opt}" for i, opt in enumerate(options)]
        embed = brand_embed(title=f"📊 {question}", description="\n".join(lines))
        embed.set_footer(text=f"Poll started by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        for i in range(len(options)):
            try:
                await message.add_reaction(POLL_NUMBER_EMOJIS[i])
            except discord.HTTPException:
                pass

    @app_commands.command(name="remindme", description="Get a DM reminder after a delay.")
    @app_commands.describe(
        when="How long from now, e.g. '10m', '2h', '1d' (a bare number means minutes)",
        text="What to remind you about",
    )
    async def remindme(self, interaction: discord.Interaction, when: str, text: str):
        try:
            seconds = parse_duration(when)
        except ValueError:
            await interaction.response.send_message(
                "Couldn't understand that duration. Try something like `10m`, `2h`, or `1d`.", ephemeral=True
            )
            return

        if seconds > MAX_REMINDER_SECONDS:
            await interaction.response.send_message(
                "The longest reminder I can set is 30 days out.", ephemeral=True
            )
            return

        remind_at = time.time() + seconds
        await self.bot.db.add_reminder(
            interaction.guild.id if interaction.guild else None,
            interaction.user.id,
            interaction.channel.id if interaction.channel else None,
            text,
            remind_at,
        )
        await interaction.response.send_message(
            f"Got it! I'll DM you <t:{int(remind_at)}:R> to remind you.", ephemeral=True
        )

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        due = await self.bot.db.get_due_reminders(time.time())
        for r in due:
            await self.bot.db.delete_reminder(r["id"])
            user = self.bot.get_user(r["user_id"])
            if user is None:
                try:
                    user = await self.bot.fetch_user(r["user_id"])
                except discord.HTTPException:
                    continue
            embed = brand_embed(title="⏰ Reminder", description=r["content"])
            try:
                await user.send(embed=embed)
            except discord.HTTPException:
                pass

    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Utility(bot))
