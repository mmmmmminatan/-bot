
import asyncio
import json
import os
import random
import traceback
from pathlib import Path
from threading import Thread

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask

# ==================================================
# 設定
# ==================================================

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ROLE_NAME = "owner"
STARTING_BALANCE = 1000

DATA_FILE = Path("balances.json")
POSITIONS_FILE = Path("slot_positions.json")
LOGS_FILE = Path("slot_logs.json")
CONFIG_FILE = Path("log_config.json")

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

VALID_LINES = (1, 2, 3, 5)
MAX_BET = 1_000_000_000
MAX_LOGS = 10000

# ==================================================
# Render用Webサーバー
# ==================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!", 200


def run_web():
    port = int(os.getenv("PORT", "8080"))
    app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False,
    )


# ==================================================
# JSON読み書き
# ==================================================

def load_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, type(default)):
            return data

        print(f"Invalid data format: {path}")
        return default

    except FileNotFoundError:
        return default

    except json.JSONDecodeError:
        print(f"Invalid JSON: {path}")
        return default

    except OSError:
        traceback.print_exc()
        return default


def save_json(path, data):
    temp = path.with_suffix(".tmp")

    temp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temp.replace(path)


balances = load_json(DATA_FILE, {})
slot_positions = load_json(POSITIONS_FILE, {})
slot_logs = load_json(LOGS_FILE, [])
log_configs = load_json(CONFIG_FILE, {})

# ==================================================
# 所持金
# ==================================================

def save_balances():
    save_json(DATA_FILE, balances)


def save_positions():
    save_json(POSITIONS_FILE, slot_positions)


def save_logs():
    save_json(LOGS_FILE, slot_logs)


def save_configs():
    save_json(CONFIG_FILE, log_configs)


def get_balance(user_id):
    key = str(user_id)

    if key not in balances:
        balances[key] = STARTING_BALANCE
        save_balances()

    return int(balances[key])


def set_balance(user_id, amount):
    balances[str(user_id)] = int(amount)
    save_balances()


# ==================================================
# Discord Bot
# ==================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    case_insensitive=True,
)

_synced = False


@bot.event
async def on_ready():
    global _synced

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(name=".Mbot help"),
    )

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Connected to {len(bot.guilds)} server(s)")

    if not _synced:
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} slash command(s)")
            _synced = True
        except Exception:
            traceback.print_exc()


@bot.event
async def on_disconnect():
    print("Discord connection disconnected")


@bot.event
async def on_resumed():
    print("Discord connection resumed")


# ==================================================
# エラー処理
# ==================================================

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

    if isinstance(error, commands.CommandInvokeError):
        original = error.original

        print("===== COMMAND INVOKE ERROR =====")
        traceback.print_exception(
            type(original),
            original,
            original.__traceback__,
        )

        try:
            await ctx.send(
                f"⚠️ 実行エラー：`{type(original).__name__}`\n"
                f"詳細：`{str(original)[:400]}`"
            )
        except discord.HTTPException:
            pass

        return

    print(f"Command error: {repr(error)}")
    traceback.print_exception(
        type(error),
        error,
        error.__traceback__,
    )

    try:
        await ctx.send(
            f"⚠️ エラー：`{type(error).__name__}`"
        )
    except discord.HTTPException:
        pass


@bot.tree.error
async def slash_command_error(interaction, error):
    print("===== SLASH COMMAND ERROR =====")
    traceback.print_exception(
        type(error),
        error,
        error.__traceback__,
    )

    message = (
        f"⚠️ エラー：{type(error).__name__}"
    )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )
    except discord.HTTPException:
        pass


# ==================================================
# スロット履歴記録
# ==================================================

def record_slot(data):
    slot_logs.append(data)

    if len(slot_logs) > MAX_LOGS:
        del slot_logs[:-MAX_LOGS]

    save_logs()


async def send_slot_log(guild, data):
    if guild is None:
        return

    channel_id = log_configs.get(str(guild.id))

    if not channel_id:
        return

    channel = guild.get_channel(int(channel_id))

    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except (discord.HTTPException, discord.Forbidden):
            print("Log channel unavailable:", channel_id)
            return

    embed = discord.Embed(
        title="🎰 スロットログ",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )

    embed.add_field(
        name="プレイヤー",
        value=(
            f"<@{data['user_id']}> "
            f"(`{data['user_id']}`)"
        ),
        inline=False,
    )

    embed.add_field(
        name="スロット結果",
        value=f"```text\n{data['grid']}\n```",
        inline=False,
    )

    embed.add_field(
        name="賭け金",
        value=f"{data['bet']:,} × {data['lines']}ライン",
        inline=True,
    )

    embed.add_field(
        name="合計賭け金",
        value=f"{data['total_bet']:,}コイン",
        inline=True,
    )

    embed.add_field(
        name="配当",
        value=f"{data['winnings']:,}コイン",
        inline=True,
    )

    embed.add_field(
        name="収支",
        value=f"{data['profit']:+,}コイン",
        inline=True,
    )

    embed.add_field(
        name="回転前の所持金",
        value=f"{data['before']:,}コイン",
        inline=True,
    )

    embed.add_field(
        name="回転後の所持金",
        value=f"{data['after']:,}コイン",
        inline=True,
    )

    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        print(
            "Cannot send slot log. Check channel permissions:",
            channel_id,
        )
    except discord.HTTPException:
        traceback.print_exc()


# ==================================================
# .balance
# ==================================================

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


# ==================================================
# スロット計算
# ==================================================

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


# ==================================================
# .slot 賭け金 [ライン数]
# ==================================================

@bot.command(
    name="slot",
    help="スロット。例：.slot 100 3",
)
async def slot(ctx, bet: int, lines: int = 1):
    if bet <= 0 or bet > MAX_BET:
        await ctx.send(
            "⚠️ 賭け金は1〜1,000,000,000にしてね。"
        )
        return

    if lines not in VALID_LINES:
        await ctx.send(
            "⚠️ ライン数は1、2、3、5から選んでね。"
        )
        return

    total_bet = bet * lines
    before = get_balance(ctx.author.id)

    if total_bet > before:
        await ctx.send(
            f"💸 コインが足りないよ！\n"
            f"所持金：{before:,}\n"
            f"必要額：{total_bet:,}"
        )
        return

    # 賭け金を引く
    set_balance(
        ctx.author.id,
        before - total_bet,
    )

    positions = [
        random.randrange(len(pattern))
        for pattern in LANE_PATTERNS
    ]

    slot_positions[str(ctx.author.id)] = positions
    save_positions()

    grid = make_grid(positions)
    paylines = get_paylines(grid, lines)

    winnings = 0
    hits = []

    for index, line in enumerate(paylines, start=1):
        if line[0] == line[1] == line[2]:
            symbol = line[0]
            prize = bet * PAYOUTS[symbol]
            winnings += prize

            hits.append(
                f"ライン{index}：{symbol} ×3 "
                f"→ +{prize:,}コイン"
            )

    after = before - total_bet + winnings

    set_balance(ctx.author.id, after)

    rendered_grid = grid_text(grid)

    # 履歴をファイルに保存
    log_data = {
        "timestamp": discord.utils.utcnow().isoformat(),
        "guild_id": ctx.guild.id if ctx.guild else None,
        "channel_id": ctx.channel.id,
        "user_id": ctx.author.id,
        "username": str(ctx.author),
        "bet": bet,
        "lines": lines,
        "total_bet": total_bet,
        "grid": rendered_grid,
        "winnings": winnings,
        "profit": winnings - total_bet,
        "before": before,
        "after": after,
    }

    try:
        record_slot(log_data)
    except OSError:
        traceback.print_exc()

    # スロット結果を表示
    embed = discord.Embed(
        title="🎰 スロット結果",
        description=(
            f"```text\n{rendered_grid}\n```\n"
            f"賭け金：{bet:,} × {lines}ライン\n"
            f"合計賭け金：{total_bet:,}コイン\n"
            f"配当：{winnings:,}コイン\n"
            f"収支：{winnings - total_bet:+,}コイン\n"
            f"回転前：{before:,}コイン\n"
            f"回転後：{after:,}コイン"
        ),
        color=discord.Color.gold(),
    )

    embed.add_field(
        name="🎉 当たり！" if hits else "結果",
        value=(
            "\n".join(hits)
            if hits
            else "今回はハズレ！また挑戦してね。"
        ),
        inline=False,
    )

    await ctx.send(embed=embed)

    # ログ送信に失敗してもスロット結果は維持
    try:
        await send_slot_log(ctx.guild, log_data)
    except Exception:
        traceback.print_exc()


# ==================================================
# .Payment @ユーザー 金額
# ==================================================

@bot.command(
    name="Payment",
    help="ownerロール専用。ユーザーにコインを追加",
)
async def payment(ctx, member: discord.Member, amount: int):
    is_owner = any(
        role.name.lower() == OWNER_ROLE_NAME.lower()
        for role in getattr(ctx.author, "roles", [])
    )

    if not is_owner:
        await ctx.send(
            "⛔ このコマンドはownerロール専用だよ。"
        )
        return

    if member.bot:
        await ctx.send(
            "⚠️ Botにはコインを追加できないよ。"
        )
        return

    if amount < 1 or amount > MAX_BET:
        await ctx.send(
            "⚠️ 金額は1〜1,000,000,000にしてね。"
        )
        return

    old_balance = get_balance(member.id)
    new_balance = old_balance + amount

    set_balance(member.id, new_balance)

    await ctx.send(
        f"💸 {member.mention} に **{amount:,}コイン**追加！\n"
        f"変更前：{old_balance:,}\n"
        f"変更後：{new_balance:,}"
    )


# ==================================================
# .Mbot help
# ==================================================

@bot.command(
    name="Mbot",
    help="ヘルプコマンド",
)
async def mbot(ctx, *, args=""):
    if args.strip().lower() == "help":
        await ctx.send("ウンコブリー")
    else:
        await ctx.send("使い方：`.Mbot help`")


# ==================================================
# .help
# ==================================================

@bot.command(name="help")
async def help_command(ctx):
    await ctx.send(
        "📘 コマンド一覧\n"
        "`.balance` 所持金確認\n"
        "`.slot 100` 1ラインスロット\n"
        "`.slot 100 3` 3ラインスロット\n"
        "`.slot 100 5` 5ラインスロット\n"
        "`.Payment @ユーザー 100` コイン追加（ownerのみ）\n"
        "`.Mbot help` ウンコブリー\n"
        "`/log panel` ログ設定パネル"
    )


# ==================================================
# /log panel
# ログ送信先チャンネルを選ぶ
# ==================================================

class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="ログ送信先チャンネルを選択",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で使ってね。",
                ephemeral=True,
            )
            return

        selected = self.values[0]

        log_configs[str(interaction.guild.id)] = selected.id

        try:
            save_configs()
        except OSError:
            traceback.print_exc()
            await interaction.response.send_message(
                "⚠️ 設定の保存に失敗したよ。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ ログ送信先を {selected.mention} に設定したよ！\n"
            "次回からスロット結果を自動記録するね。",
            ephemeral=True,
        )


class LogPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(LogChannelSelect())


log_group = app_commands.Group(
    name="log",
    description="スロットログの設定",
)


@log_group.command(
    name="panel",
    description="ログ送信先を設定するパネルを表示",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def log_panel(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "サーバー内で使ってね。",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="⚙️ スロットログ設定",
        description=(
            "下のメニューからログ送信先を選んでね。\n\n"
            "記録する内容：\n"
            "・プレイヤー\n"
            "・賭け金とライン数\n"
            "・スロットの絵柄\n"
            "・配当と収支\n"
            "・回転前と回転後の所持金\n\n"
            "設定はサーバーごとに保存されるよ。"
        ),
        color=discord.Color.blue(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=LogPanelView(),
        ephemeral=True,
    )


bot.tree.add_command(log_group)


@log_panel.error
async def log_panel_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(
        error,
        app_commands.MissingPermissions,
    ):
        message = (
            "⛔ このコマンドはサーバー管理権限が必要だよ。"
        )
    else:
        traceback.print_exception(
            type(error),
            error,
            error.__traceback__,
        )
        message = (
            f"⚠️ エラー：{type(error).__name__}"
        )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )
    except discord.HTTPException:
        pass


# ==================================================
# 起動
# ==================================================

async def start_bot():
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN が設定されていないよ。"
            "RenderのEnvironmentを確認してね。"
        )

    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    Thread(
        target=run_web,
        daemon=True,
    ).start()

    asyncio.run(start_bot())
