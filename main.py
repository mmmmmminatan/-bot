
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
# スロット絵柄
# 各レーンの並びを別々にする
# =========================
LANE_PATTERNS = [
    ["🍒", "🍋", "⭐", "🔔", "7️⃣"],  # 左
    ["⭐", "🍒", "7️⃣", "🍋", "🔔"],  # 中央
    ["🔔", "7️⃣", "🍋", "⭐", "🍒"],  # 右
]

PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐": 10,
    "7️⃣": 50,
}

# =========================
# 3×3盤面を作る
# =========================
def make_grid():
    return [
        [
            LANE_PATTERNS[col][
                (LANE_POSITIONS[col] + offset) % 5
            ]
            for col in range(3)
        ]
        for offset in (-1, 0, 1)
    ]

def format_grid(grid):
    return "\n".join(
        "┃ " + " ┃ ".join(row) + " ┃"
        for row in grid
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
# .slot 賭け金 ライン数
#
# 1：真ん中
# 2：真ん中・上
# 3：上・真ん中・下
# 5：横3本・斜め2本
# =========================
@bot.command(name="slot")
async def slot(ctx, bet: int = None, lines: int = 1):

    if bet is None or bet <= 0:
        await ctx.send(
            "使い方：`.slot 100 1`\n"
            "ライン数：1・2・3・5"
        )
        return

    if bet > 1_000_000_000:
        await ctx.send(
            "❌ 賭け金は10億コイン以下にしてね。"
        )
        return

    if lines not in (1, 2, 3, 5):
        await ctx.send(
            "❌ ライン数は1・2・3・5から選んでね。"
        )
        return

    async with SLOT_LOCK:
        user_id = str(ctx.author.id)
        money = get_balance(ctx.author.id)

        total_bet = bet * lines

        if total_bet > 1_000_000_000:
            await ctx.send(
                "❌ 合計賭け金は10億コイン以下にしてね。"
            )
            return

        if total_bet > money:
            await ctx.send(
                f"❌ 所持金不足！\n"
                f"必要額：**{total_bet:,} コイン**\n"
                f"現在：**{money:,} コイン**"
            )
            return

        # 賭け金を差し引く
        balances[user_id] = money - total_bet

        # 各レーンの停止位置を独立して決める
        for lane in range(3):
            LANE_POSITIONS[lane] = random.randrange(5)

        grid = make_grid()

        # 当たり判定ライン
        all_lines = [
            ("真ん中", [(1, 0), (1, 1), (1, 2)]),
            ("上",     [(0, 0), (0, 1), (0, 2)]),
            ("下",     [(2, 0), (2, 1), (2, 2)]),
            ("斜め右", [(0, 0), (1, 1), (2, 2)]),
            ("斜め左", [(2, 0), (1, 1), (0, 2)]),
        ]

        # 指定ラインを有効化
        if lines == 1:
            active_lines = [all_lines[0]]
        elif lines == 2:
            active_lines = [all_lines[0], all_lines[1]]
        elif lines == 3:
            active_lines = all_lines[:3]
        else:
            active_lines = all_lines

        total_payout = 0
        win_results = []

        # ラインごとに独立して判定
        for line_name, coords in active_lines:
            symbols = [
                grid[row][col]
                for row, col in coords
            ]

            if symbols[0] == symbols[1] == symbols[2]:
                symbol = symbols[0]
                multiplier = PAYOUTS[symbol]

                # 配当は1ライン分の賭け金を基準に計算
                payout = bet * multiplier
                total_payout += payout

                win_results.append(
                    f"🎉 **{line_name}ライン当たり！**\n"
                    f"{' '.join(symbols)}\n"
                    f"倍率：×{multiplier}\n"
                    f"配当：**{payout:,} コイン**"
                )

        # 配当を加算
        balances[user_id] += total_payout

        # データを保存
        save_balances()
        save_positions()

        # 結果表示
        if win_results:
            result_text = (
                "🎊 **当たり！**\n\n"
                + "\n\n".join(win_results)
                + f"\n\n💰 合計配当："
                f"**{total_payout:,} コイン**"
            )
        else:
            result_text = (
                "❌ **ハズレ！**\n"
                "有効ラインに当たりはなかったよ。"
            )

        await ctx.send(
            "🎰 **SLOT MACHINE** 🎰\n\n"
            "```text\n"
            f"{format_grid(grid)}\n"
            "```\n"
            f"🎯 有効ライン：**{lines}本**\n"
            f"💰 1ラインの賭け金：**{bet:,} コイン**\n"
            f"💸 合計賭け金：**{total_bet:,} コイン**\n\n"
            f"{result_text}\n\n"
            f"💳 残高：**{balances[user_id]:,} コイン**"
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
    new_balance = current + amount

    balances[str(target.id)] = new_balance
    save_balances()

    await ctx.send(
        f"✅ **コイン付与完了！**\n"
        f"対象：{target.mention}\n"
        f"付与額：**{amount:,} コイン**\n"
        f"現在の残高：**{new_balance:,} コイン**"
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
        name="🎰 .slot 賭け金 ライン数",
        value=(
            "`.slot 100 1`：真ん中\n"
            "`.slot 100 2`：真ん中・上\n"
            "`.slot 100 3`：横3ライン\n"
            "`.slot 100 5`：横3＋斜め2ライン"
        ),
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
