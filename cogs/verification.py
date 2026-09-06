import discord
from discord.ext import commands
from discord import app_commands

import config
from utils.embeds import brand_embed
from utils.checks import is_staff

RULES_ACCEPT_CUSTOM_ID = "verification:accept_rules"


class AcceptRulesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="I Accept the Rules & Risk Disclaimer", style=discord.ButtonStyle.success, custom_id=RULES_ACCEPT_CUSTOM_ID
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id = config.get("verified_role_id")
        if not role_id:
            await interaction.response.send_message("Verification isn't configured yet -- ask a staff member.", ephemeral=True)
            return
        role = interaction.guild.get_role(int(role_id))
        if role is None:
            await interaction.response.send_message(
                "Verification role not found -- ask a staff member to check config.json.", ephemeral=True
            )
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("You're already verified!", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="Accepted rules")
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to give you that role -- ask a staff member for help.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "You're verified! Welcome aboard -- head to the channel list to get started. 🎉", ephemeral=True
        )


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(AcceptRulesView())  # persistent across restarts

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        channel_id = config.get("welcome_channel_id")
        if channel_id:
            channel = member.guild.get_channel(int(channel_id))
            if channel:
                embed = brand_embed(
                    title="Welcome!",
                    description=(
                        f"Welcome to **{config.get('brand_name', 'the server')}**, {member.mention}! 👋\n\n"
                        "Head over to the rules channel and accept the rules to unlock the rest of the server."
                    ),
                )
                if member.display_avatar:
                    embed.set_thumbnail(url=member.display_avatar.url)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass
        try:
            await member.send(
                f"Welcome to **{config.get('brand_name', 'the server')}**! "
                "Please read and accept the rules in the server to get full access."
            )
        except discord.Forbidden:
            pass

    @app_commands.command(name="post-rules-gate", description="[Staff] Post the rules acceptance button in this channel.")
    @is_staff()
    async def post_rules_gate(self, interaction: discord.Interaction, rules_text: str = None):
        embed = brand_embed(
            title="📜 Server Rules & Risk Disclaimer",
            description=rules_text
            or (
                "By clicking below you agree to follow the server rules and understand that "
                "**nothing shared in this server is financial advice**. Trading involves risk, "
                "including the loss of your entire investment. Trade at your own discretion."
            ),
        )
        await interaction.channel.send(embed=embed, view=AcceptRulesView())
        await interaction.response.send_message("Posted the rules gate.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Verification(bot))
