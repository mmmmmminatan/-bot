import os
import random
import discord
from discord.ext import commands

bot = commands.Bot(command_prefix=".", intents=discord.Intents.default())

SLOT_EMOJIS = ["🍒", "🍋", "🔔", "⭐", "7️⃣"]

@bot.command()
async def slot(ctx):
    result = [random.choice(SLOT_EMOJIS) for _ in range(3)]
    await ctx.send("🎰 **SLOT** 🎰\n\n" + " | ".join(result))

# 環境変数からトークンを読み込む
bot.run(os.getenv("DISCORD_TOKEN"))
