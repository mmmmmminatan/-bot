
import asyncio
import json
import os
import random
from pathlib import Path
from threading import Thread

import discord
from discord.ext import commands
from flask import Flask

# =========================
# 設定
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ROLE_NAME = "owner"
STARTING_BALANCE = 1000

DATA_FILE = Path("balances.json")
POSITIONS_FILE = Path("slot_positions.json")

LANE_PATTERNS = [
    ["🍒", "🍋", "⭐", "🔔", "7️⃣"],
    ["⭐", "🍒", "7️⃣", "🍋", "🔔"],
    ["🔔", "7️⃣", "🍋", "⭐", "🍒"],
]

PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐": 10,
    "7️⃣": 50,
}

# =========================
# Render用Webサーバー
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!"

def run_web():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

# =========================
# Discord Bot
# =========================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    case_insensitive=True,
)

# =========================
# データ読み込み・保存
# =========================

def load_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

balances = load_json(DATA_FILE, {})
slot_positions = load_json(POSITIONS_FILE, {})

def save_balances():
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(balances, f, ensure_ascii=False, indent=2)

def save_positions():
    with POSITIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump(slot_positions, f, ensure_ascii=False, indent=2)

def get_balance(user_id):
    key = str(user_id)

    if key not in balances:
        balances[key] = STARTING_BALANCE
        save_balances()

    return int(balances[key])

def set_balance(user_id, amount):
    balances[str(user_id)] = int(amount)
    save_balances()

# =========================
# エラー処理
# =========================

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

    print(f"Command error: {repr(error)}")
    await ctx.send("⚠️ エラーが発生したよ。")

# =========================
# 所持金確認
# .balance
# =========================

@bot.command(
    name="balance",
    help="自分の所持金を確認する",
)
async def balance(ctx):
    amount = get_balance(ctx.author.id)

    embed = discord.Embed(
        title="💰 所持金",
        description=(
            f"{ctx.author.mention} の所持金："
            f"**{amount:,} コイン**"
        ),
        color=discord.Color.gold(),
    )

    await ctx.send(embed=embed)

# =========================
# スロット
# .slot 賭け金 [ライン数]
# ライン数：1、2、3、5
# =========================

def make_grid(positions):
    grid = []

    for row in range(3):
        current_row = []

        for lane in range(3):
            pattern = LANE_PATTERNS[lane]
            center = positions[lane]
            index = (center + row - 1) % len(pattern)
            current_row.append(pattern[index])

        grid.append(current_row)

    return grid

def grid_text(grid):
    return "\n".join(
        " | ".join(row)
        for row in grid
    )

def get_paylines(grid, line_count):
    lines = [grid[1]]

    if line_count >= 2:
        lines.append(grid[0])

    if line_count >= 3:
        lines.append(grid[2])

    if line_count >= 5:
        lines.append([
            grid[0][0],
            grid[1][1],
            grid[2][2],
        ])

        lines.append([
            grid[2][0],
            grid[1][1],
            grid[0][2],
        ])

    return lines

@bot.command(
    name="slot",
    help="スロットを回す。例：.slot 100 3",
)
async def slot(ctx, bet: int, lines: int = 1):
    if bet <= 0:
        await ctx.send("⚠️ 賭け金は1以上にしてね。")
        return

    if lines not in (1, 2, 3, 5):
        await ctx.send("⚠️ ライン数は1、2、3、5から選んでね。")
        return

    total_bet = bet * lines
    current_balance = get_balance(ctx.author.id)

    if total_bet > current_balance:
        await ctx.send(
            f"💸 コインが足りないよ！\n"
            f"所持金：{current_balance:,}\n"
            f"必要額：{total_bet:,}"
        )
        return

    # 賭け金を差し引く
    set_balance(
        ctx.author.id,
        current_balance - total_bet,
    )

    # 各リールの停止位置をランダムに決定
    positions = [
        random.randrange(len(pattern))
        for pattern in LANE_PATTERNS
    ]

    slot_positions[str(ctx.author.id)] = positions
    save_positions()

    grid = make_grid(positions)
    paylines = get_paylines(grid, lines)

    winnings = 0
    hit_results = []

    for index, line in enumerate(paylines, start=1):
        if line[0] == line[1] == line[2]:
            symbol = line[0]
            prize = bet * PAYOUTS[symbol]
            winnings += prize

            hit_results.append(
                f"ライン{index}：{symbol} ×3 → +{prize:,}コイン"
            )

    final_balance = get_balance(ctx.author.id) + winnings
    set_balance(ctx.author.id, final_balance)

    embed = discord.Embed(
        title="🎰 スロット結果",
        description=(
            f"```text\n{grid_text(grid)}\n```\n"
            f"賭け金：{bet:,} × {lines}ライン\n"
            f"合計賭け金：{total_bet:,}コイン\n"
            f"配当：{winnings:,}コイン\n"
            f"収支：{winnings - total_bet:+,}コイン\n"
            f"残高：{final_balance:,}コイン"
        ),
        color=discord.Color.gold(),
    )

    if hit_results:
        embed.add_field(
            name="🎉 当たり！",
            value="\n".join(hit_results),
            inline=False,
        )
    else:
        embed.add_field(
            name="結果",
            value="今回はハズレ！また挑戦してね。",
            inline=False,
        )

    await ctx.send(embed=embed)

# =========================
# コイン追加
# .Payment @ユーザー 金額
# ownerロール限定
# =========================

@bot.command(
    name="Payment",
    help="ownerロール専用。ユーザーにコインを追加する",
)
async def payment(ctx, member: discord.Member, amount: int):
    is_owner = any(
        role.name.lower() == OWNER_ROLE_NAME.lower()
        for role in getattr(ctx.author, "roles", [])
    )

    if not is_owner:
        await ctx.send("⛔ このコマンドはownerロール専用だよ。")
        return

    if member.bot:
        await ctx.send("⚠️ Botにはコインを追加できないよ。")
        return

    if amount < 1 or amount > 1_000_000_000:
        await ctx.send("⚠️ 金額は1〜1,000,000,000にしてね。")
        return

    old_balance = get_balance(member.id)
    new_balance = old_balance + amount

    set_balance(member.id, new_balance)

    await ctx.send(
        f"💸 {member.mention} に **{amount:,}コイン**追加したよ！\n"
        f"変更前：{old_balance:,}\n"
        f"変更後：{new_balance:,}"
    )

# =========================
# .Mbot help
# 必ず「ウンコブリー」と返信
# =========================

@bot.command(
    name="Mbot",
    help="ヘルプコマンド",
)
async def mbot(ctx, *, args=""):
    if args.strip().lower() == "help":
        await ctx.send("ウンコブリー 💩")
    else:
        await ctx.send("使い方：`.Mbot help`")

# =========================
# 起動
# =========================

async def start_bot():
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN が設定されていないよ。"
            "RenderのEnvironmentを確認してね。"
        )

    await bot.start(TOKEN)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    asyncio.run(start_bot())
