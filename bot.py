import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import Database
from keep_alive import start_keep_alive_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("bot")

INITIAL_EXTENSIONS = [
    "cogs.verification",
    "cogs.moderation",
    "cogs.engagement",
    "cogs.support",
    "cogs.membership",
    "cogs.owner",
    "cogs.trading",
    "cogs.utility",
    "cogs.ai_features",
]


class TradingCourseBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.db = Database("data/bot.sqlite3")

    async def setup_hook(self):
        await self.db.init()

        for extension in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(extension)
                log.info("Loaded extension %s", extension)
            except Exception:
                log.exception("Failed to load extension %s", extension)

        guild_id = config.GUILD_ID
        if guild_id:
            guild_obj = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            log.info("Synced %d commands to guild %s (instant)", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (can take up to an hour to appear everywhere)", len(synced))

        await start_keep_alive_server(config.PORT)

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        try:
            await self.change_presence(
                activity=discord.Activity(type=discord.ActivityType.watching, name="the markets 📈")
            )
        except discord.HTTPException:
            pass


bot = TradingCourseBot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        message = "You don't have permission to use this command."
    else:
        message = "Something went wrong running that command."
        log.exception("Unhandled app command error", exc_info=error)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


def main():
    if not config.DISCORD_TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Add it to your .env file (local) or your host's environment variables."
        )
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
