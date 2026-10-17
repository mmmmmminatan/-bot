
import asyncio
import json
import os
import random
from pathlib import Path
from threading import Thread

from flask import Flask
import discord
from discord.ext import commands

# =========================
# Render用Webサーバー
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!"

def run_web():
    port = int(os.getenv("PORT", "8080"))
    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
        use_reloader=False
    )

Thread(target=run_web, daemon=True).start()

# =========================
# Discord Bot設定
# =========================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    case_insensitive=True
)

# =========================
# 保存ファイル・基本設定
# =========================
BALANCE_FILE = Path("balances.json")
POSITION_FILE = Path("slot_positions.json")

STARTING_BALANCE = 1000
SLOT_LOCK = asyncio.Lock()

def load_json(path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, type(default)):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return default

balances = load_json(BALANCE_FILE, {})

saved_positions = load_json(
    POSITION_FILE,
    {"positions": [0, 0, 0]}
)

LANE_POSITIONS = saved_positions.get(
    "positions", [0, 0, 0]
)

if (
    not isinstance(LANE_POSITIONS, list)
    or len(LANE_POSITIONS) != 3
    or any(
        type(pos) is not int or not 0 <= pos < 5
        for pos in LANE_POSITIONS
    )
):
    LANE_POSITIONS = [0, 0, 0]

def save_balances():
    with BALANCE_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            balances,
            file,
            ensure_ascii=False,
            indent=2
        )

def save_positions():
    with POSITION_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {"positions": LANE_POSITIONS},
            file,
            ensure_ascii=False,
            indent=2
        )

def get_balance(user_id):
    key = str(user_id)

    if key not in balances:
        balances[key] = STARTING_BALANCE
        save_balances()

    return int(balances[key])

# =========================
# スロット設定
# =========================
LANE_PATTERNS = [
    ["🍒", "🍋", "⭐", "🔔", "7️⃣"],  # 左
    ["⭐", "🍒", "7️⃣", "🍋", "🔔"],  # 中央
    ["🔔", "7️⃣", "🍋", "⭐", "🍒"],  # 右
]

]

PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐": 10,
    "7️⃣": 50,
}

def make_display():
    rows = []

    for offset in (-1, 0, 1):
        row = []

        for lane in range(3):
            pattern = LANE_PATTERNS[lane]
            pos = LANE_POSITIONS[lane]

            row.append(
                pattern[(pos + offset) % len(pattern)]
            )

        rows.append("┃ " + " ┃ ".join(row) + " ┃")

    return "\n".join(rows)

def slot_message(bet, status):
    return (
        "🎰 **SLOT MACHINE** 🎰\n\n"
        "```text\n"
        f"{make_display()}\n"
        "```\n"
        f"💰 賭け金：**{bet:,} コイン**\n"
        f"{status}"
    )

# =========================
# .balance 所持金表示
# =========================
@bot.command(name="balance")
async def balance(ctx):
    money = get_balance(ctx.author.id)

    await ctx.send(
        f"💰 {ctx.author.mention} の所持金："
        f"**{money:,} コイン**"
    )

# =========================
# .slot 金額
# アニメーションなし・結果のみ
# =========================
@bot.command(name="slot")
async def slot(ctx, bet: int = None):

    if bet is None or bet <= 0:
        await ctx.send("使い方：`.slot 100`")
        return

    if bet > 1_000_000_000:
        await ctx.send(
            "❌ 賭け金は10億コイン以下にしてね。"
        )
        return

    async with SLOT_LOCK:
        user_id = str(ctx.author.id)
        money = get_balance(ctx.author.id)

        if bet > money:
            await ctx.send(
                f"❌ 所持金不足！現在は "
                f"**{money:,} コイン** だよ。"
            )
            return

        # 賭け金を先に差し引く
        balances[user_id] = money - bet

        # 3レーンの結果をランダムに決定
        center_symbols = [
            random.choice(LANE_PATTERNS[lane])
            for lane in range(3)
        ]

        # 結果を表示位置に反映
        for lane, symbol in enumerate(center_symbols):
            LANE_POSITIONS[lane] = (
                LANE_PATTERNS[lane].index(symbol)
            )

        # 当たり判定
        if (
            center_symbols[0]
            == center_symbols[1]
            == center_symbols[2]
        ):
            symbol = center_symbols[0]
            multiplier = PAYOUTS[symbol]
            payout = bet * multiplier

            result_text = (
                f"🎉 **大当たり！**\n"
                f"絵柄：{' '.join(center_symbols)}\n"
                f"倍率：**×{multiplier}**\n"
                f"配当：**{payout:,} コイン**"
            )
        else:
            payout = 0

            result_text = (
                f"❌ **ハズレ！**\n"
                f"中央の出目：{' '.join(center_symbols)}\n"
                f"**{bet:,} コイン** 消費！"
            )

        # 配当を加算
        balances[user_id] += payout

        # データ保存
        save_balances()
        save_positions()

        # 結果だけを1回で送信
        await ctx.send(
            slot_message(bet, result_text)
            + f"\n💰 残高："
            f"**{balances[user_id]:,} コイン**"
        )

# =========================
# .Payment @相手 金額
# ownerロール限定
# =========================
@bot.command(name="Payment")
async def payment(
    ctx,
    target: discord.Member = None,
    amount: int = None
):
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
        await ctx.send(
            "❌ Botには付与できないよ。"
        )
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

# =========================
# .help コマンド一覧
# =========================
@bot.command(name="help")
async def custom_help(ctx):
    embed = discord.Embed(
        title="📖 コマンド一覧",
        description="このBotで使えるコマンドだよ！",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="🎰 .slot 金額",
        value="コインを賭けてスロットを回す。",
        inline=False
    )

    embed.add_field(
        name="💰 .balance",
        value="自分の所持金を確認する。",
        inline=False
    )

    embed.add_field(
        name="👑 .Payment @相手 金額",
        value="コイン付与（ownerロール限定）。",
        inline=False
    )

    embed.add_field(
        name="📖 .help",
        value="コマンド一覧を表示する。",
        inline=False
    )

    await ctx.send(embed=embed)

# =========================
# Bot起動
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "環境変数 DISCORD_TOKEN が設定されていないよ！"
    )

bot.run(TOKEN)
