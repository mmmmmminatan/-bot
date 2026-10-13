import os
import random
import discord
from discord.ext import commands

# メッセージの内容を読み取る権限を有効化
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)

SLOT_EMOJIS = ["🍒", "🍋", "🔔", "⭐", "7️⃣"]

@bot.command()
async def slot(ctx):
    result = [random.choice(SLOT_EMOJIS) for _ in range(3)]
    await ctx.send("🎰 **SLOT** 🎰\n\n" + " | ".join(result))

bot.run(os.getenv("DISCORD_TOKEN"))
