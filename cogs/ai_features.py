import random

import discord
from discord.ext import commands
from discord import app_commands

from utils.embeds import brand_embed
from utils import ai

UNAVAILABLE_MESSAGE = (
    "🤖 AI features aren't set up yet -- a free API key needs to be added to the bot's "
    "environment. Ask a server admin about it!"
)

FINANCIAL_DISCLAIMER = "\n\n*This is educational information only, not financial advice.*"

EDUCATION_SYSTEM_PROMPT = (
    "You are a friendly trading and investing educator for a trading-course Discord community. "
    "Explain concepts clearly for beginners in plain language. Keep answers concise. Never give "
    "personalized financial advice, never recommend buying or selling any specific security, "
    "never predict future prices, and never tell someone what their own portfolio should look "
    "like. Stick to general, neutral education."
)

LESSON_TOPICS = [
    "diversification",
    "dollar-cost averaging",
    "compound interest",
    "risk management and position sizing",
    "the difference between stocks and ETFs",
    "what a P/E ratio tells you",
    "reading candlestick charts",
    "why stop-loss orders exist",
    "the difference between investing and trading",
    "market orders vs. limit orders",
    "what volatility means",
    "the difference between a bull market and a bear market",
    "emotional discipline and avoiding FOMO",
    "what an expense ratio is",
    "technical analysis vs. fundamental analysis",
]


class AIFeatures(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="explain", description="Get an AI-generated, beginner-friendly explanation of a trading/investing term."
    )
    @app_commands.describe(term="The term or concept to explain, e.g. 'RSI' or 'short selling'")
    async def explain(self, interaction: discord.Interaction, term: str):
        await interaction.response.defer()
        result = await ai.generate_text(
            f'Explain the trading/investing term or concept "{term}" to a complete beginner in '
            "3-5 short sentences.",
            system=EDUCATION_SYSTEM_PROMPT,
            max_tokens=220,
            temperature=0.7,
        )
        if not result:
            await interaction.followup.send(UNAVAILABLE_MESSAGE, ephemeral=True)
            return
        embed = brand_embed(title=f"📘 {term.strip().title()}", description=result)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="ask", description="Ask an AI trading/investing education question.")
    @app_commands.describe(question="Your question about trading, investing, or markets")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        result = await ai.generate_text(
            question,
            system=(
                EDUCATION_SYSTEM_PROMPT
                + " If asked for a personal recommendation, a prediction, or whether to buy/sell "
                "something specific, explain that you can't provide that and redirect to general "
                "educational concepts instead. Keep the whole answer under 150 words."
            ),
            max_tokens=300,
            temperature=0.7,
        )
        if not result:
            await interaction.followup.send(UNAVAILABLE_MESSAGE, ephemeral=True)
            return
        embed = brand_embed(title="🎓 Ask", description=f"**Q:** {question}\n\n{result}{FINANCIAL_DISCLAIMER}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="motivate", description="Get a fresh AI-generated pep talk for your trading journey.")
    async def motivate(self, interaction: discord.Interaction):
        await interaction.response.defer()
        result = await ai.generate_text(
            "Write a short, original, encouraging pep talk (2-4 sentences) for someone learning to "
            "trade or invest. Emphasize that consistency, discipline, and risk management matter "
            "more than quick wins. Do not mention specific securities and do not give financial advice.",
            system="You are an upbeat but realistic mentor for a trading-course Discord community.",
            max_tokens=150,
            temperature=1.0,
        )
        if not result:
            await interaction.followup.send(UNAVAILABLE_MESSAGE, ephemeral=True)
            return
        embed = brand_embed(title="🔥 You've Got This", description=result)
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="lesson", description="Get a random AI-generated mini-lesson on a trading/investing topic."
    )
    async def lesson(self, interaction: discord.Interaction):
        await interaction.response.defer()
        topic = random.choice(LESSON_TOPICS)
        result = await ai.generate_text(
            f"Write a short mini-lesson (4-6 sentences) teaching a beginner about: {topic}. "
            "Make it clear and practical.",
            system=EDUCATION_SYSTEM_PROMPT,
            max_tokens=280,
            temperature=0.7,
        )
        if not result:
            await interaction.followup.send(UNAVAILABLE_MESSAGE, ephemeral=True)
            return
        embed = brand_embed(title=f"📚 Mini-Lesson: {topic.title()}", description=result)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AIFeatures(bot))
