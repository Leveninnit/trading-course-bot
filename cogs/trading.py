import random
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

from utils.embeds import brand_embed

# Common tickers -> CoinGecko coin IDs. Anything not in this map is looked up as a stock symbol instead.
CRYPTO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "SHIB": "shiba-inu",
    "TRX": "tron",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
    "NEAR": "near",
}

# Kept short (under 15 words each) -- a mix of correctly-attributed one-liners and unattributed proverbs.
QUOTES = [
    ("Price is what you pay. Value is what you get.", "Warren Buffett"),
    ("The stock market is a device for transferring money from the impatient to the patient.", "Warren Buffett"),
    ("Risk comes from not knowing what you're doing.", "Warren Buffett"),
    ("In investing, what is comfortable is rarely profitable.", "Robert Arnott"),
    ("The four most dangerous words in investing are: 'this time it's different.'", "Sir John Templeton"),
    ("An investment in knowledge pays the best interest.", "Benjamin Franklin"),
    ("Cut your losses short and let your winners run.", None),
    ("Plan your trade, then trade your plan.", None),
    ("The market can stay irrational longer than you can stay solvent.", "attributed to John Maynard Keynes"),
    ("Never risk more than you can afford to lose.", None),
]

NY_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)


def _format_price(value: float) -> str:
    """Scales decimal precision to the price so cheap tokens (e.g. SHIB) don't round to $0.00."""
    if value >= 1:
        return f"${value:,.2f}"
    if value >= 0.01:
        return f"${value:,.4f}"
    return f"${value:,.8f}"


class Trading(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

    async def _fetch_crypto_price(self, coingecko_id: str):
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": coingecko_id, "vs_currencies": "usd", "include_24hr_change": "true"}
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            return None
        entry = data.get(coingecko_id)
        if not entry or "usd" not in entry:
            return None
        return entry["usd"], entry.get("usd_24h_change")

    async def _fetch_stock_price(self, symbol: str):
        stooq_symbol = symbol.lower() if "." in symbol else f"{symbol.lower()}.us"
        url = "https://stooq.com/q/l/"
        params = {"s": stooq_symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"}
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError):
            return None

        lines = text.strip().splitlines()
        if len(lines) < 2:
            return None
        fields = lines[1].split(",")
        try:
            close = float(fields[6])
        except (IndexError, ValueError):
            return None
        if close <= 0:
            return None
        return close

    @app_commands.command(name="price", description="Look up a live crypto or stock price.")
    @app_commands.describe(ticker="A crypto ticker (BTC, ETH, ...) or a stock symbol (AAPL, TSLA, ...)")
    async def price(self, interaction: discord.Interaction, ticker: str):
        await interaction.response.defer()
        symbol = ticker.strip().upper()

        if symbol in CRYPTO_IDS:
            result = await self._fetch_crypto_price(CRYPTO_IDS[symbol])
            if result is None:
                await interaction.followup.send(f"Couldn't fetch a price for **{symbol}** right now. Try again shortly.")
                return
            price, change_24h = result
            change_line = f"\n**24h change:** {change_24h:+.2f}%" if change_24h is not None else ""
            embed = brand_embed(title=f"{symbol} / USD", description=f"**{_format_price(price)}**{change_line}")
            await interaction.followup.send(embed=embed)
            return

        price = await self._fetch_stock_price(symbol)
        if price is None:
            await interaction.followup.send(
                f"Couldn't find a price for **{symbol}**. Double-check the ticker -- this covers major exchanges only."
            )
            return
        embed = brand_embed(title=symbol, description=f"**{_format_price(price)}**")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="market-status", description="Check if the US stock market (NYSE) is open right now.")
    async def market_status(self, interaction: discord.Interaction):
        now_ny = datetime.now(NY_TZ)
        is_weekday = now_ny.weekday() < 5
        is_market_hours = MARKET_OPEN <= now_ny.time() <= MARKET_CLOSE
        is_open = is_weekday and is_market_hours
        current_line = f"Current time: {now_ny.strftime('%I:%M %p ET, %A')}"

        if is_open:
            title = "🟢 Market Open"
            description = f"NYSE is **open**. It closes at 4:00 PM ET.\n{current_line}"
        else:
            title = "🔴 Market Closed"
            description = (
                f"NYSE is **closed** right now.\nRegular hours are 9:30 AM-4:00 PM ET, Monday-Friday.\n{current_line}"
            )
        description += "\n\n*(Doesn't account for market holidays.)*"

        embed = brand_embed(title=title, description=description)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quote", description="Get a random trading/investing quote for motivation.")
    async def quote(self, interaction: discord.Interaction):
        text, author = random.choice(QUOTES)
        description = f'*"{text}"*'
        if author:
            description += f"\n— {author}"
        embed = brand_embed(title="💬 Trading Wisdom", description=description)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Trading(bot))
