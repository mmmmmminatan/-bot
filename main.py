
import asyncio
import json
import os
import random
from pathlib import Path
from threading import Thread

import discord
from discord.ext import commands
from flask import Flask

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ROLE_NAME = "owner"
STARTING_BALANCE = 1000

DATA_FILE = Path("balances.json")

SYMBOLS = ["🍒", "🍋", "⭐", "🔔", "7️⃣"]
PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐": 10,
    "7️⃣": 50,
}

# Render用Webサーバー
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!", 200

def run_web():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# Discord Bot
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    case_insensitive=True,
)

# 所持金データ
def load_balances():
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

balances = load_balances()

def save_balances():
    temp = DATA_FILE.with_suffix(".tmp")
    temp.write_text(
        json.dumps(balances, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(DATA_FILE)

def get_balance(user_id):
    key = str(user_id)
    if key not in balances:
        balances[key] = STARTING_BALANCE
        save_balances()
    return int(balances[key])

def set_balance(user_id, amount):
    balances[str(user_id)] = int(amount)
    save_balances()

# 起動状態
@bot.event
async def on_ready():
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(name=".Mbot help"),
    )
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Connected to {len(bot.guilds)} server(s)")

# エラー表示
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ 必要な情報が足りないよ！")
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ 入力内容を確認してね！")
        return

    import traceback
    traceback.print_exception(
        type(error), error, error.__traceback__
    )
    await ctx.send(
        f"⚠️ エラー内容：{type(error).__name__}"
    )

# .balance
@bot.command(name="balance")
async def balance(ctx):
    amount = get_balance(ctx.author.id)
    await ctx.send(
        f"💰 {ctx.author.mention} の所持金：**{amount:,} コイン**"
    )

# .slot 賭け金 [ライン数]
@bot.command(name="slot")
async def slot(ctx, bet: int, lines: int = 1):
    if bet <= 0:
        await ctx.send("⚠️ 賭け金は1以上にしてね。")
        return

    if lines not in (1, 2, 3, 5):
        await ctx.send("⚠️ ライン数は1、2、3、5から選んでね。")
        return

    total_bet = bet * lines
    balance_now = get_balance(ctx.author.id)

    if total_bet > balance_now:
        await ctx.send(
            f"💸 コイン不足！所持金：{balance_now:,} / "
            f"必要額：{total_bet:,}"
        )
        return

    # 先に賭け金を引く
    set_balance(ctx.author.id, balance_now - total_bet)

    grid = [
        [random.choice(SYMBOLS) for _ in range(3)]
        for _ in range(3)
    ]

    paylines = [grid[1]]

    if lines >= 2:
        paylines.append(grid[0])
    if lines >= 3:
        paylines.append(grid[2])
    if lines >= 5:
        paylines.extend([
            [grid[0][0], grid[1][1], grid[2][2]],
            [grid[2][0], grid[1][1], grid[0][2]],
        ])

    winnings = 0
    hits = []

    for i, line in enumerate(paylines, 1):
        if line[0] == line[1] == line[2]:
            prize = bet * PAYOUTS[line[0]]
            winnings += prize
            hits.append(
                f"ライン{i}：{line[0]} ×3 → +{prize:,}コイン"
            )

    final_balance = get_balance(ctx.author.id) + winnings
    set_balance(ctx.author.id, final_balance)

    result = "\n".join(" | ".join(row) for row in grid)

    embed = discord.Embed(
        title="🎰 スロット結果",
        description=(
            f"```text\n{result}\n```\n"
            f"1ラインあたり：{bet:,}コイン\n"
            f"ライン数：{lines}\n"
            f"合計賭け金：{total_bet:,}コイン\n"
            f"配当：{winnings:,}コイン\n"
            f"収支：{winnings - total_bet:+,}コイン\n"
            f"残高：{final_balance:,}コイン"
        ),
        color=discord.Color.gold(),
    )

    embed.add_field(
        name="🎉 当たり！" if hits else "結果",
        value="\n".join(hits) if hits else "今回はハズレ！",
        inline=False,
    )
    await ctx.send(embed=embed)

# .Payment @ユーザー 金額（ownerロール限定）
@bot.command(name="Payment")
async def payment(ctx, member: discord.Member, amount: int):
    is_owner = any(
        role.name.lower() == OWNER_ROLE_NAME
        for role in getattr(ctx.author, "roles", [])
    )

    if not is_owner:
        await ctx.send("⛔ ownerロール専用だよ。")
        return

    if member.bot:
        await ctx.send("⚠️ Botにはコインを追加できないよ。")
        return

    if not 1 <= amount <= 1_000_000_000:
        await ctx.send("⚠️ 金額は1〜1,000,000,000にしてね。")
        return

    old = get_balance(member.id)
    new = old + amount
    set_balance(member.id, new)

    await ctx.send(
        f"💸 {member.mention} に **{amount:,}コイン**追加！\n"
        f"変更前：{old:,}\n変更後：{new:,}"
    )

# .Mbot help → ウンコブリー
@bot.command(name="Mbot")
async def mbot(ctx, *, args=""):
    if args.strip().lower() == "help":
        await ctx.send("ウンコブリー")
    else:
        await ctx.send("使い方：`.Mbot help`")

# .help
@bot.command(name="help")
async def help_command(ctx):
    await ctx.send(
        "📘 コマンド一覧\n"
        "`.balance` 所持金確認\n"
        "`.slot 100` 1ライン\n"
        "`.slot 100 3` 3ライン\n"
        "`.slot 100 5` 5ライン\n"
        "`.Payment @ユーザー 100` コイン追加（ownerのみ）\n"
        "`.Mbot help` ウンコブリー"
    )

# 起動
async def start_bot():
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN が設定されていないよ。"
            "RenderのEnvironmentを確認してね。"
        )

    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    asyncio.run(start_bot())
