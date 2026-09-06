import discord
from discord.ext import commands
from discord import app_commands

from utils.embeds import brand_embed


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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


async def setup(bot):
    await bot.add_cog(Utility(bot))
