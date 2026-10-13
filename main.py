
import os
import random
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)

@bot.event
async def on_ready():
    print(f"ログイン成功: {bot.user}")

@bot.command()
async def slot(ctx):
    symbols = ["🍒", "🍋", "🔔", "💎", "7️⃣"]
    result = [random.choice(symbols) for _ in range(3)]

    if len(set(result)) == 1:
        message = "🎉 大当たり！"
    elif len(set(result)) == 2:
        message = "✨ もう少し！"
    else:
        message = "🎰 はずれ！"

    await ctx.send(
        f"🎰 **ROYAL CASINO**\n"
        f"╭─────────╮\n"
        f"│ {'　'.join(result)} │\n"
        f"╰─────────╯\n"
        f"{message}"
    )

@bot.command()
async def blackjack(ctx):
    cards = [random.randint(1, 11) for _ in range(2)]
    total = sum(cards)

    await ctx.send(
        f"🃏 **BLACKJACK 練習モード**\n"
        f"カード: {cards[0]} と {cards[1]}\n"
        f"合計: **{total}**\n"
        "今回はカードの合計を試す練習モードだよ！"
    )

bot.run(os.environ["DISCORD_TOKEN"])

