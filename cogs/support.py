import io

import discord
from discord.ext import commands
from discord import app_commands

import config
from utils.embeds import brand_embed
from utils.checks import is_staff

TICKET_OPEN_CUSTOM_ID = "support:open_ticket"
TICKET_CLOSE_CUSTOM_ID = "support:close_ticket"


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id=TICKET_CLOSE_CUSTOM_ID)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        ticket = await bot.db.get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            await interaction.response.send_message("This isn't a ticket channel.", ephemeral=True)
            return
        await interaction.response.send_message("Closing this ticket and saving a transcript...")

        lines = []
        async for msg in interaction.channel.history(limit=None, oldest_first=True):
            lines.append(f"[{msg.created_at:%Y-%m-%d %H:%M}] {msg.author}: {msg.content}")
        transcript = "\n".join(lines) or "(no messages)"
        buffer = io.BytesIO(transcript.encode("utf-8"))
        file = discord.File(buffer, filename=f"transcript-{interaction.channel.name}.txt")

        log_channel_id = config.get("mod_log_channel_id")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(int(log_channel_id))
            if log_channel:
                try:
                    await log_channel.send(f"Ticket closed: {interaction.channel.name}", file=file)
                except discord.HTTPException:
                    pass

        await bot.db.close_ticket(ticket["id"], interaction.user.id)
        try:
            await interaction.channel.delete(reason="Ticket closed")
        except discord.HTTPException:
            pass


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Open a Ticket", style=discord.ButtonStyle.primary, custom_id=TICKET_OPEN_CUSTOM_ID)
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        existing = await bot.db.get_open_ticket(interaction.guild.id, interaction.user.id)
        if existing:
            channel = interaction.guild.get_channel(existing["channel_id"])
            if channel:
                await interaction.response.send_message(f"You already have an open ticket: {channel.mention}", ephemeral=True)
                return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        for role_id in config.get("ticket_support_role_ids", []):
            role = interaction.guild.get_role(int(role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        category_id = config.get("ticket_category_id")
        category = interaction.guild.get_channel(int(category_id)) if category_id else None

        try:
            channel = await interaction.guild.create_text_channel(
                name=f"ticket-{interaction.user.name}"[:100],
                category=category,
                overwrites=overwrites,
                reason=f"Ticket opened by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to create ticket channels -- ask a staff member for help.", ephemeral=True
            )
            return

        await bot.db.create_ticket(interaction.guild.id, channel.id, interaction.user.id)

        embed = brand_embed(
            title="🎫 Support Ticket",
            description=f"{interaction.user.mention} Thanks for reaching out! Describe your issue and a staff member will help shortly.",
        )
        await channel.send(embed=embed, view=TicketCloseView())
        await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)


class Support(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(TicketPanelView())
        bot.add_view(TicketCloseView())

    @commands.Cog.listener()
    async def on_ready(self):
        # Seed each guild's FAQ table from config.json defaults the first time we see it with no entries yet.
        for guild in self.bot.guilds:
            existing = await self.bot.db.get_faq(guild.id)
            if not existing:
                await self.bot.db.seed_faq_if_empty(guild.id, config.get("faq", {}))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        faq = await self.bot.db.get_faq(message.guild.id)
        if not faq:
            return
        content = message.content.lower().strip()
        for question, answer in faq.items():
            if question in content:
                embed = brand_embed(title="💡 FAQ", description=answer)
                try:
                    await message.reply(embed=embed, mention_author=False)
                except discord.HTTPException:
                    pass
                return

    @app_commands.command(name="post-ticket-panel", description="[Staff] Post the 'open a ticket' button in this channel.")
    @is_staff()
    async def post_ticket_panel(self, interaction: discord.Interaction):
        embed = brand_embed(title="🎫 Need help?", description="Click below to open a private ticket with staff.")
        await interaction.channel.send(embed=embed, view=TicketPanelView())
        await interaction.response.send_message("Posted the ticket panel.", ephemeral=True)

    @app_commands.command(name="announce", description="[Staff] Broadcast an announcement.")
    @is_staff()
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        message: str,
        ping_role: discord.Role = None,
    ):
        embed = brand_embed(title=title, description=message)
        content = ping_role.mention if ping_role else None
        try:
            await channel.send(content=content, embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(f"I can't post in {channel.mention}.", ephemeral=True)
            return
        await interaction.response.send_message(f"Announcement posted in {channel.mention}.", ephemeral=True)

    faq_group = app_commands.Group(name="faq", description="Manage FAQ auto-responses")

    @faq_group.command(name="add", description="[Staff] Add or update an FAQ trigger.")
    @is_staff()
    async def faq_add(self, interaction: discord.Interaction, trigger: str, answer: str):
        await self.bot.db.set_faq(interaction.guild.id, trigger.lower(), answer)
        await interaction.response.send_message(f"Saved FAQ trigger: `{trigger}`", ephemeral=True)

    @faq_group.command(name="remove", description="[Staff] Remove an FAQ trigger.")
    @is_staff()
    async def faq_remove(self, interaction: discord.Interaction, trigger: str):
        removed = await self.bot.db.delete_faq(interaction.guild.id, trigger.lower())
        await interaction.response.send_message("Removed." if removed else "Couldn't find that trigger.", ephemeral=True)

    @faq_group.command(name="list", description="List all FAQ triggers.")
    async def faq_list(self, interaction: discord.Interaction):
        faq = await self.bot.db.get_faq(interaction.guild.id)
        if not faq:
            await interaction.response.send_message("No FAQ entries yet.", ephemeral=True)
            return
        desc = "\n".join(f"- `{q}`" for q in faq)
        await interaction.response.send_message(embed=brand_embed(title="FAQ Triggers", description=desc), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Support(bot))
