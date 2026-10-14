
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
# Webサーバー
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


def keep_alive():
    Thread(target=run_web, daemon=True).start()


keep_alive()


# =========================
# Discord Bot
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
# データ保存
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
        type(p) is not int or not 0 <= p < 5
        for p in LANE_POSITIONS
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
    ["🍒", "🍋", "⭐️", "🔔", "7️⃣"],
    ["7️⃣", "⭐️", "🍋", "🍒", "🔔"],
    ["🔔", "🍒", "7️⃣", "🍋", "⭐️"],
]

PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐️": 10,
    "7️⃣": 50,
}

LANE_NAMES = ["左", "中央", "右"]


def make_display():
    rows = []

    for offset in (-1, 0, 1):
        row = []

        for lane in range(3):
            pattern = LANE_PATTERNS[lane]
            pos = LANE_POSITIONS[lane]
            symbol = pattern[(pos + offset) % len(pattern)]
            row.append(symbol)

        rows.append("┃ " + " ┃ ".join(row) + " ┃")

    return "\n".join(rows)


# =========================
# 所持金
# =========================

@bot.command(name="balance")
async def balance(ctx):
    money = get_balance(ctx.author.id)

    await ctx.send(
        f"💰 {ctx.author.mention} の所持金："
        f"**{money:,} コイン**"
    )


# =========================
# スロット
# =========================

@bot.command(name="slot")
async def slot(ctx, bet: int = None):
    global LANE_POSITIONS

    if bet is None or bet <= 0:
        await ctx.send("使い方：`.slot 100`")
        return

    if bet > 1_000_000_000:
        await ctx.send("❌ 賭け金は10億コイン以下にしてね。")
        return

    async with SLOT_LOCK:
        money = get_balance(ctx.author.id)

        if bet > money:
            await ctx.send(
                f"❌ 所持金不足！現在は **{money:,} コイン** だよ。"
            )
            return

        # 賭け金を引く
        balances[str(ctx.author.id)] = money - bet
        save_balances()

        # 各レーンの移動量は10〜20マス
        steps = [random.randint(10, 20) for _ in range(3)]

        # 3レーン同時に回転開始
        message = await ctx.send(
            f"🎰 **SLOT MACHINE** 🎰\n\n"
            f"```text\n{make_display()}\n```\n"
            f"🎲 賭け金：**{bet:,} コイン**\n"
            f"🔄 3レーン回転中..."
        )

        # 短時間で高速回転
        # 3レーンとも同時に進み、それぞれの停止位置で止まる
        max_steps = max(steps)

        for step in range(1, max_steps + 1):
            for lane in range(3):
                if step <= steps[lane]:
                    LANE_POSITIONS[lane] = (
                        LANE_POSITIONS[lane] + 1
                    ) % len(LANE_PATTERNS[lane])

            # 表示更新を減らして高速化
            if step % 3 == 0 or step == max_steps:
                await message.edit(
                    content=(
                        f"🎰 **SLOT MACHINE** 🎰\n\n"
                        f"```text\n{make_display()}\n```\n"
                        f"🎲 賭け金：**{bet:,} コイン**\n"
                        f"🔄 回転中..."
                    )
                )
                await asyncio.sleep(0.06)

        # 各レーンの停止位置を保存
        save_positions()

        # 左→中央→右の順番に停止表示
        for lane in range(3):
            await message.edit(
                content=(
                    f"🎰 **SLOT MACHINE** 🎰\n\n"
                    f"```text\n{make_display()}\n```\n"
                    f"🎲 賭け金：**{bet:,} コイン**\n"
                    f"🛑 {LANE_NAMES[lane]}レーン停止！"
                )
            )
            await asyncio.sleep(0.12)

        # 中央の横一列で判定
        center_symbols = [
            LANE_PATTERNS[lane][LANE_POSITIONS[lane]]
            for lane in range(3)
        ]

        if center_symbols[0] == center_symbols[1] == center_symbols[2]:
            symbol = center_symbols[0]
            payout = bet * PAYOUTS[symbol]

            result_text = (
                f"🎉 **大当たり！**\n"
                f"絵柄：{' '.join(center_symbols)}\n"
                f"配当：**{payout:,} コイン**"
            )
        else:
            payout = 0

            result_text = (
                f"❌ **ハズレ！**\n"
                f"中央の出目：{' '.join(center_symbols)}\n"
                f"**{bet:,} コイン** 消費！"
            )

        balances[str(ctx.author.id)] += payout
        save_balances()

        new_balance = balances[str(ctx.author.id)]

        await message.edit(
            content=(
                f"🎰 **SLOT MACHINE** 🎰\n\n"
                f"```text\n{make_display()}\n```\n"
                f"🎲 賭け金：**{bet:,} コイン**\n"
                f"{result_text}\n"
                f"💰 残高：**{new_balance:,} コイン**"
            )
        )


# =========================
# コイン付与（owner限定）
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
        await ctx.send("使い方：`.Payment @相手 500`")
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


# =========================
# ヘルプ
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
