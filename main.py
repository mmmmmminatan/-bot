from flask import Flask
from threading import Thread
import os
import json
import random
from pathlib import Path

import discord
from discord.ext import commands

# --- Renderスリープ防止用のWebサーバー設定 ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Webサーバーをバックグラウンドで起動
keep_alive()
# ---------------------------------------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    case_insensitive=True  # 大文字・小文字を区別せずにコマンドを認識する設定
)

BALANCE_FILE = Path("balances.json")
STARTING_BALANCE = 1000

SLOT_EMOJIS = ["🍒", "🍋", "🔔", "⭐", "7️⃣"]

PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐": 10,
    "7️⃣": 50,
}


def load_balances():
    if not BALANCE_FILE.exists():
        return {}

    try:
        data = json.loads(
            BALANCE_FILE.read_text(encoding="utf-8")
        )
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


balances = load_balances()


def save_balances():
    BALANCE_FILE.write_text(
        json.dumps(
            balances,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def get_balance(user_id):
    key = str(user_id)

    if key not in balances:
        balances[key] = STARTING_BALANCE
        save_balances()

    return int(balances[key])


@bot.command(name="balance")
async def balance(ctx):
    money = get_balance(ctx.author.id)

    await ctx.send(
        f"💰 {ctx.author.mention} の所持金："
        f"**{money:,} コイン**"
    )


@bot.command(name="slot")
async def slot(ctx, bet: int = None):
    if bet is None or bet <= 0:
        await ctx.send("使い方：`.slot 100`")
        return

    money = get_balance(ctx.author.id)

    if bet > money:
        await ctx.send(
            f"❌ 所持金不足！現在は **{money:,} コイン** だよ。"
        )
        return

    # 3行×3列のスロット
    reels = [
        [random.choice(SLOT_EMOJIS) for _ in range(3)]
        for _ in range(3)
    ]

    winning_lines = []

    for row_index, row in enumerate(reels):
        if row[0] == row[1] == row[2]:
            winning_lines.append((row_index, row[0]))

    payout = sum(
        bet * PAYOUTS[symbol]
        for _, symbol in winning_lines
    )

    balances[str(ctx.author.id)] = money - bet + payout
    save_balances()

    display = "\n".join(
        "┃ " + " ┃ ".join(row) + " ┃"
        for row in reels
    )

    if winning_lines:
        details = "\n".join(
            f"🎉 {row_index + 1}行目：{symbol} "
            f"×{PAYOUTS[symbol]} → "
            f"**{bet * PAYOUTS[symbol]:,} コイン**"
            for row_index, symbol in winning_lines
        )

        result_text = (
            f"🎉 **当たり！**\n{details}\n"
            f"💰 合計配当：**{payout:,} コイン**"
        )
    else:
        result_text = (
            f"❌ ハズレ！ **{bet:,} コイン** 消費！"
        )

    new_balance = balances[str(ctx.author.id)]

    await ctx.send(
        f"🎰 **SLOT MACHINE** 🎰\n\n"
        f"```text\n{display}\n```\n"
        f"🎲 賭け金：**{bet:,} コイン**\n"
        f"{result_text}\n"
        f"💰 残高：**{new_balance:,} コイン**"
    )


@bot.command(name="Payment")
async def payment(
    ctx,
    target: discord.Member = None,
    amount: int = None
):
    # ownerロール限定
    if not isinstance(ctx.author, discord.Member):
        return

    if not any(
        role.name.lower() == "owner"
        for role in ctx.author.roles
    ):
        await ctx.send(
            "❌ このコマンドは owner ロール限定だよ。"
        )
        return

    if target is None or amount is None:
        await ctx.send(
            "使い方：`.Payment @相手 500`"
        )
        return

    if target.bot:
        await ctx.send("❌ Botには付与できないよ。")
        return

    if amount <= 0 or amount > 1_000_000_000:
        await ctx.send(
            "❌ 金額は1〜1,000,000,000で指定してね。"
        )
        return

    current = get_balance(target.id)
    balances[str(target.id)] = current + amount
    save_balances()

    await ctx.send(
        f"✅ **コイン付与完了！**\n"
        f"対象：{target.mention}\n"
        f"付与額：**{amount:,} コイン**\n"
        f"現在の残高："
        f"**{balances[str(target.id)]:,} コイン**"
    )


@bot.command(name="help")
async def custom_help(ctx):
    embed = discord.Embed(
        title="📖 コマンド一覧",
        description="このBotで使えるコマンドだよ！",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="🎰 .slot 金額",
        value="指定したコインを賭けてスロットを回す。",
        inline=False
    )

    embed.add_field(
        name="💰 .balance",
        value="自分の所持金を確認する。",
        inline=False
    )

    embed.add_field(
        name="👑 .Payment @相手 金額",
        value="相手にコインを付与する（ownerロール限定）。",
        inline=False
    )

    embed.add_field(
        name="📖 .help",
        value="コマンド一覧を表示する。",
        inline=False
    )

    await ctx.send(embed=embed)


bot.run(os.getenv("DISCORD_TOKEN"))
