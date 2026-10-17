
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

SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "7️⃣"]

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
# Flask（Render用）
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
# データ保存
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
# 共通エラー表示
# =========================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(
            "❓ コマンドが見つからないよ！\n"
            "`.Mbot help` で一覧を確認してね。"
        )
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"⚠️ 引数が足りないよ！\n"
            f"使い方：`.{ctx.command.qualified_name} {ctx.command.signature}`"
        )
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ 入力内容を確認してね。")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send("⏳ 少し待ってからもう一度試してね。")
    else:
        print(f"Command error: {repr(error)}")
        await ctx.send("⚠️ コマンド実行中にエラーが発生したよ。")

# =========================
# 所持金
# =========================

@bot.command(name="balance", help="自分の所持金を確認する")
async def balance(ctx):
    amount = get_balance(ctx.author.id)
    embed = discord.Embed(
        title="💰 所持金",
        description=f"{ctx.author.mention} の所持金：**{amount:,} コイン**",
        color=discord.Color.gold(),
    )
    await ctx.send(embed=embed)

# =========================
# スロット
# 使い方：.slot 賭け金 [ライン数]
# ライン数：1、2、3、5
# =========================

def make_grid(user_id):
    key = str(user_id)
    saved = slot_positions.get(key, [0, 0, 0])

    if not isinstance(saved, list) or len(saved) != 3:
        saved = [0, 0, 0]

    grid = []

    for row in range(3):
        line = []

        for lane in range(3):
            pattern = LANE_PATTERNS[lane]
            center = int(saved[lane]) % len(pattern)
            index = (center + row - 1) % len(pattern)
            line.append(pattern[index])

        grid.append(line)

    return grid

def spin_positions(user_id):
    key = str(user_id)
    positions = [
        random.randrange(len(LANE_PATTERNS[lane]))
        for lane in range(3)
    ]
    slot_positions[key] = positions
    save_positions()
    return positions

def grid_text(grid):
    return "\n".join(
        " | ".join(row)
        for row in grid
    )

def get_paylines(grid, line_count):
    lines = [
        grid[1],
    ]

    if line_count >= 2:
        lines.append(grid[0])

    if line_count >= 3:
        lines.append(grid[2])

    if line_count >= 5:
        lines.append([grid[0][0], grid[1][1], grid[2][2]])
        lines.append([grid[2][0], grid[1][1], grid[0][2]])

    return lines

@bot.command(
    name="slot",
    help="スロットを回す。例：.slot 100 3（100コインを3ライン）",
)
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
            f"💸 コインが足りないよ！\n"
            f"所持金：{balance_now:,}\n"
            f"必要額：{total_bet:,}"
        )
        return

    # 賭け金を先に引く
    set_balance(ctx.author.id, balance_now - total_bet)

    # 3リールをランダムに回す
    positions = spin_positions(ctx.author.id)

    grid = make_grid(ctx.author.id)
    active_lines = get_paylines(grid, lines)

    winnings = 0
    results = []

    for index, line in enumerate(active_lines, start=1):
        if line[0] == line[1] == line[2]:
            symbol = line[0]
            prize = bet * PAYOUTS[symbol]
            winnings += prize
            results.append(
                f"ライン{index}：{symbol} ×3 → **+{prize:,}**"
            )

    final_balance = get_balance(ctx.author.id) + winnings
    set_balance(ctx.author.id, final_balance)

    embed = discord.Embed(
        title="🎰 スロット結果",
        description=(
            f"```text\n{grid_text(grid)}\n```\n"
            f"賭け金：{bet:,} × {lines}ライン = {total_bet:,}\n"
            f"当たり配当：{winnings:,} コイン\n"
            f"収支：{winnings - total_bet:+,} コイン\n"
            f"残高：{final_balance:,} コイン"
        ),
        color=discord.Color.gold(),
    )

    if results:
        embed.add_field(
            name="🎉 当たり！",
            value="\n".join(results),
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
# 送金・コイン追加
# 使い方：.Payment @ユーザー 金額
# ownerロール限定
# =========================

@bot.command(
    name="Payment",
    help="ownerロール専用。指定したユーザーにコインを追加する",
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

    if amount <= 0 or amount > 1_000_000_000:
        await ctx.send("⚠️ 金額は1〜1,000,000,000にしてね。")
        return

    old_balance = get_balance(member.id)
    new_balance = old_balance + amount
    set_balance(member.id, new_balance)

    await ctx.send(
        f"💸 {member.mention} に **{amount:,} コイン**追加したよ！\n"
        f"変更前：{old_balance:,}\n"
        f"変更後：{new_balance:,}"
    )

# =========================
# コマンド一覧
# .Mbot help
# =========================

@bot.group(
    name="Mbot",
    invoke_without_command=True,
    help="Botのコマンド一覧を表示する",
)
async def mbot(ctx):
    await send_help(ctx)

@mbot.command(
    name="help",
    help="使用できるコマンド一覧を表示する",
)
async def mbot_help(ctx):
    await send_help(ctx)

async def send_help(ctx):
    embed = discord.Embed(
        title="🎰 コマンド一覧",
        description="このBotで使えるコマンドだよ！",
        color=discord.Color.gold(),
    )

    # 主要コマンドを自動取得
    for command in bot.walk_commands():
        if command.hidden:
            continue

        if command.parent is not None:
            # サブコマンドは下で追加する
            continue

        usage = f".{command.qualified_name}"
        if command.signature:
            usage += f" {command.signature}"

        description = command.help or "説明なし"

        embed.add_field(
            name=usage,
            value=description,
            inline=False,
        )

    # Mbot helpも明示的に案内
    embed.add_field(
        name=".Mbot help",
        value="コマンド一覧を表示する",
        inline=False,
    )

    await ctx.send(embed=embed)

# =========================
# 起動
# =========================

async def start_bot():
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN が設定されていないよ！"
            "RenderのEnvironmentで設定してね。"
        )

    await bot.start(TOKEN)

def run_bot():
    asyncio.run(start_bot())

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    run_bot()
