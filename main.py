
import asyncio
import json
import os
import random
import re
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
COIN_LOGS_FILE = Path("coin_logs.json")
SETTINGS_FILE = Path("settings.json")

VALID_LINES = (1, 2, 3, 5)
MAX_BET = 1_000_000_000
MAX_LOGS = 10000

# 内部シンボルと通常表示
SYMBOLS = {
    "cherry": {
        "unicode": "🍒",
        "custom": "emoji_15",
        "payout": 2,
    },
    "lemon": {
        "unicode": "🍋",
        "custom": "emoji_13",
        "payout": 3,
    },
    "bell": {
        "unicode": "🔔",
        "custom": "emoji_14",
        "payout": 5,
    },
    "star": {
        "unicode": "⭐",
        "custom": "emoji_12",
        "payout": 10,
    },
    "seven": {
        "unicode": "7️⃣",
        "custom": "emoji_16",
        "payout": 50,
    },
}

LANE_PATTERNS = [
    ["cherry", "lemon", "star", "bell", "seven"],
    ["star", "cherry", "seven", "lemon", "bell"],
    ["bell", "seven", "lemon", "star", "cherry"],
]

# ==================================================
# Render Webサーバー
# ==================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!", 200


@app.route("/health")
def health():
    return "OK", 200


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

        print(f"[DATA ERROR] Invalid format: {path}")
        return default.copy()

    except FileNotFoundError:
        return default.copy()

    except json.JSONDecodeError:
        print(f"[DATA ERROR] Invalid JSON: {path}")
        return default.copy()

    except OSError:
        traceback.print_exc()
        return default.copy()


def save_json(path, data):
    temp = path.with_suffix(".tmp")

    try:
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)
        return True

    except Exception:
        print(f"[DATA SAVE ERROR] {path}")
        traceback.print_exc()
        return False


balances = load_json(DATA_FILE, {})
slot_positions = load_json(POSITIONS_FILE, {})
slot_logs = load_json(LOGS_FILE, [])
log_configs = load_json(CONFIG_FILE, {})
coin_logs = load_json(COIN_LOGS_FILE, [])
settings = load_json(SETTINGS_FILE, {})


def save_balances():
    return save_json(DATA_FILE, balances)


def save_positions():
    return save_json(POSITIONS_FILE, slot_positions)


def save_logs():
    return save_json(LOGS_FILE, slot_logs)


def save_configs():
    return save_json(CONFIG_FILE, log_configs)


def save_coin_logs():
    return save_json(COIN_LOGS_FILE, coin_logs)


def save_settings():
    return save_json(SETTINGS_FILE, settings)


# ==================================================
# サーバーごとの設定
# ==================================================

def get_guild_settings(guild_id):
    key = str(guild_id)

    if key not in settings or not isinstance(settings[key], dict):
        settings[key] = {}

    config = settings[key]

    config.setdefault("slot_mode", "stamp")
    config.setdefault("slot_enabled", True)
    config.setdefault("max_bet", MAX_BET)
    config.setdefault("currency_name", "コイン")

    if config["slot_mode"] not in ("stamp", "emoji"):
        config["slot_mode"] = "stamp"

    try:
        config["max_bet"] = max(
            1,
            min(int(config["max_bet"]), MAX_BET),
        )
    except (ValueError, TypeError):
        config["max_bet"] = MAX_BET

    if not isinstance(config["slot_enabled"], bool):
        config["slot_enabled"] = True

    if not isinstance(config["currency_name"], str):
        config["currency_name"] = "コイン"

    return config


# ==================================================
# 所持金
# ==================================================

def get_balance(user_id):
    key = str(user_id)

    if key not in balances:
        balances[key] = STARTING_BALANCE
        save_balances()

    return int(balances[key])


def set_balance(user_id, amount):
    balances[str(user_id)] = int(amount)

    if not save_balances():
        raise OSError("balances.json の保存に失敗したよ")


def is_owner(member):
    return any(
        role.name.lower() == OWNER_ROLE_NAME.lower()
        for role in getattr(member, "roles", [])
    )


# ==================================================
# Discord Bot
# ==================================================

intents = discord.Intents.default()
intents.message_content = True


class CasinoBot(commands.Bot):
    async def setup_hook(self):
        print("[STARTUP] Syncing slash commands...")

        try:
            synced = await self.tree.sync()
            print(f"[SYNC OK] Synced {len(synced)} slash commands")

            for command in synced:
                print(f"[SYNC COMMAND] /{command.name}")

        except Exception:
            print("[SYNC ERROR]")
            traceback.print_exc()
            raise


bot = CasinoBot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    case_insensitive=True,
)


@bot.event
async def on_ready():
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(name=".Mbot help"),
    )

    print(f"[READY] Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"[READY] Connected to {len(bot.guilds)} server(s)")


@bot.event
async def on_disconnect():
    print("[DISCONNECT] Discord connection disconnected")


@bot.event
async def on_resumed():
    print("[RESUMED] Discord connection resumed")


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

    original = getattr(error, "original", error)

    print("[PREFIX COMMAND ERROR]")
    traceback.print_exception(
        type(original),
        original,
        original.__traceback__,
    )

    try:
        await ctx.send(f"⚠️ 実行エラー：{type(original).__name__}")
    except discord.HTTPException:
        pass


@bot.tree.error
async def slash_command_error(interaction, error):
    print(
        "[SLASH COMMAND ERROR]",
        getattr(interaction.command, "qualified_name", "unknown"),
    )

    traceback.print_exception(
        type(error),
        error,
        error.__traceback__,
    )

    original = getattr(error, "original", error)

    if isinstance(original, app_commands.MissingPermissions):
        message = "⛔ この操作に必要な権限がないよ。"
    else:
        message = f"⚠️ エラー：{type(original).__name__}"

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )
    except discord.HTTPException:
        traceback.print_exc()


# ==================================================
# スロット絵文字表示
# ==================================================

def get_symbol_text(guild, symbol_key):
    symbol = SYMBOLS[symbol_key]

    # 7️⃣の絵柄だけ、モードによって表示を変更する
    if symbol_key == "seven":
        if guild is None:
            return "7️⃣"

        config = get_guild_settings(guild.id)

        if config["slot_mode"] == "emoji":
            custom_emoji = discord.utils.get(
                guild.emojis,
                name="emoji_15",
            )

            if custom_emoji is not None:
                return str(custom_emoji)

            print(
                f"[EMOJI WARNING] emoji_15 not found "
                f"in guild {guild.id}; using 7️⃣"
            )

        return "7️⃣"

    # その他の絵柄は通常どおり
    if guild is not None:
        config = get_guild_settings(guild.id)

        if config["slot_mode"] == "emoji":
            custom_emoji = discord.utils.get(
                guild.emojis,
                name=symbol["custom"],
            )

            if custom_emoji is not None:
                return str(custom_emoji)

            print(
                f"[EMOJI WARNING] {symbol['custom']} not found "
                f"in guild {guild.id}; using Unicode"
            )

    return symbol["unicode"]


def render_grid(guild, grid):
    return "\n".join(
        " | ".join(get_symbol_text(guild, symbol) for symbol in row)
        for row in grid
    )


# ==================================================
# ログ送信先
# ==================================================

async def get_log_channel(guild):
    if guild is None:
        print("[LOG ERROR] Guild is None")
        return None

    channel_id = log_configs.get(str(guild.id))

    if not channel_id:
        print(f"[LOG ERROR] No log channel configured: {guild.id}")
        return None

    try:
        channel = guild.get_channel(int(channel_id))

        if channel is None:
            channel = await bot.fetch_channel(int(channel_id))

        if not isinstance(channel, discord.TextChannel):
            print("[LOG ERROR] Invalid text channel")
            return None

        me = guild.me

        if me is None:
            if bot.user is None:
                print("[LOG ERROR] Bot user unavailable")
                return None
            me = await guild.fetch_member(bot.user.id)

        perms = channel.permissions_for(me)

        if not (
            perms.view_channel
            and perms.send_messages
            and perms.embed_links
        ):
            print(
                "[LOG ERROR] Missing permissions: "
                f"view={perms.view_channel}, "
                f"send={perms.send_messages}, "
                f"embed={perms.embed_links}"
            )
            return None

        return channel

    except discord.Forbidden:
        print("[LOG ERROR] Forbidden while retrieving channel")
    except discord.NotFound:
        print("[LOG ERROR] Channel not found")
    except (ValueError, TypeError):
        print("[LOG ERROR] Invalid channel ID")
    except discord.HTTPException:
        print("[LOG ERROR] Discord HTTP error while retrieving channel")
        traceback.print_exc()
    except Exception:
        print("[LOG ERROR] Unexpected error while retrieving channel")
        traceback.print_exc()

    return None


# ==================================================
# スロット履歴
# ==================================================

def record_slot(data):
    slot_logs.append(data)

    if len(slot_logs) > MAX_LOGS:
        del slot_logs[:-MAX_LOGS]

    if not save_logs():
        raise OSError("slot_logs.json の保存に失敗したよ")


async def send_slot_log(guild, data):
    channel = await get_log_channel(guild)

    if channel is None:
        print("[SLOT LOG] No available log channel")
        return False

    currency = get_guild_settings(guild.id)["currency_name"]

    embed = discord.Embed(
        title="🎰 スロットログ",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )

    embed.add_field(
        name="プレイヤー",
        value=f"<@{data['user_id']}> (`{data['user_id']}`)",
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
        value=f"{data['total_bet']:,}{currency}",
        inline=True,
    )
    embed.add_field(
        name="配当",
        value=f"{data['winnings']:,}{currency}",
        inline=True,
    )
    embed.add_field(
        name="収支",
        value=f"{data['profit']:+,}{currency}",
        inline=True,
    )
    embed.add_field(
        name="回転前の所持金",
        value=f"{data['before']:,}{currency}",
        inline=True,
    )
    embed.add_field(
        name="回転後の所持金",
        value=f"{data['after']:,}{currency}",
        inline=True,
    )

    try:
        await channel.send(embed=embed)
        print(
            f"[SLOT LOG] Sent successfully "
            f"guild={guild.id} channel={channel.id}"
        )
        return True

    except discord.Forbidden:
        print("[SLOT LOG ERROR] Forbidden: check channel permissions")
    except discord.HTTPException as error:
        print(
            f"[SLOT LOG ERROR] HTTPException "
            f"status={error.status} code={error.code}"
        )
        traceback.print_exc()
    except Exception:
        print("[SLOT LOG ERROR] Unexpected exception")
        traceback.print_exc()

    return False


# ==================================================
# コイン増減ログ
# ==================================================

async def send_coin_log(
    guild,
    user_id,
    username,
    operator_id,
    action,
    before,
    change,
    after,
):
    print(
        f"[COIN LOG] Starting: guild={getattr(guild, 'id', None)}, "
        f"user={user_id}, operator={operator_id}, "
        f"action={action}, change={change}"
    )

    entry = {
        "timestamp": discord.utils.utcnow().isoformat(),
        "guild_id": guild.id if guild else None,
        "user_id": str(user_id),
        "username": username,
        "operator_id": str(operator_id),
        "action": action,
        "before": int(before),
        "change": int(change),
        "after": int(after),
    }

    coin_logs.append(entry)

    if len(coin_logs) > MAX_LOGS:
        del coin_logs[:-MAX_LOGS]

    if not save_coin_logs():
        print("[COIN LOG ERROR] Failed to save coin_logs.json")

    try:
        channel = await get_log_channel(guild)

        if channel is None:
            print(
                "[COIN LOG ERROR] No available log channel. "
                "Check /log panel configuration and permissions."
            )
            return False

        currency = (
            get_guild_settings(guild.id)["currency_name"]
            if guild else "コイン"
        )

        embed = discord.Embed(
            title="💰 コイン増減ログ",
            color=discord.Color.green() if change > 0 else discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(name="操作", value=action, inline=True)
        embed.add_field(
            name="対象者",
            value=f"<@{user_id}> (`{user_id}`)",
            inline=False,
        )
        embed.add_field(
            name="操作した人",
            value=f"<@{operator_id}> (`{operator_id}`)",
            inline=False,
        )
        embed.add_field(
            name="変更前の所持金",
            value=f"{before:,} {currency}",
            inline=True,
        )
        embed.add_field(
            name="増減",
            value=f"{change:+,} {currency}",
            inline=True,
        )
        embed.add_field(
            name="変更後の所持金",
            value=f"{after:,} {currency}",
            inline=True,
        )

        await channel.send(embed=embed)

        print(
            f"[COIN LOG] Sent successfully "
            f"guild={guild.id} channel={channel.id} "
            f"user={user_id} change={change}"
        )
        return True

    except discord.Forbidden:
        print("[COIN LOG ERROR] Forbidden: check channel permissions")
        traceback.print_exc()
    except discord.HTTPException as error:
        print(
            f"[COIN LOG ERROR] HTTPException "
            f"status={error.status} code={error.code}"
        )
        traceback.print_exc()
    except Exception as error:
        print(
            f"[COIN LOG ERROR] Unexpected "
            f"{type(error).__name__}: {error}"
        )
        traceback.print_exc()

    return False


# ==================================================
# .balance
# ==================================================

@bot.command(name="balance", help="自分の所持金を確認する")
async def balance(ctx):
    amount = get_balance(ctx.author.id)

    config = (
        get_guild_settings(ctx.guild.id)
        if ctx.guild else {"currency_name": "コイン"}
    )

    embed = discord.Embed(
        title="💰 所持金",
        description=(
            f"{ctx.author.mention} の所持金："
            f"**{amount:,} {config['currency_name']}**"
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
            index = (positions[lane] + row - 1) % len(pattern)
            current_row.append(pattern[index])

        grid.append(current_row)

    return grid


def grid_text(grid, guild=None):
    return "\n".join(
        " | ".join(get_symbol_text(guild, symbol) for symbol in row)
        for row in grid
    )


def get_paylines(grid, line_count):
    lines = [grid[1]]

    if line_count >= 2:
        lines.append(grid[0])

    if line_count >= 3:
        lines.append(grid[2])

    if line_count >= 5:
        lines.append([grid[0][0], grid[1][1], grid[2][2]])
        lines.append([grid[2][0], grid[1][1], grid[0][2]])

    return lines


# ==================================================
# .slot 賭け金 [ライン数]
# ==================================================

@bot.command(name="slot", help="例：.slot 100 3")
async def slot(ctx, bet: int, lines: int = 1):
    if ctx.guild is None:
        await ctx.send("サーバー内で使ってね。")
        return

    config = get_guild_settings(ctx.guild.id)
    currency = config["currency_name"]

    if not config["slot_enabled"]:
        await ctx.send("⚠️ 現在スロットは停止中だよ。")
        return

    if bet <= 0 or bet > int(config["max_bet"]):
        await ctx.send(
            f"⚠️ 賭け金は1〜{config['max_bet']:,}にしてね。"
        )
        return

    if lines not in VALID_LINES:
        await ctx.send("⚠️ ライン数は1、2、3、5から選んでね。")
        return

    total_bet = bet * lines
    before = get_balance(ctx.author.id)

    if total_bet > before:
        await ctx.send(
            f"💸 {currency}が足りないよ！\n"
            f"所持金：{before:,}\n"
            f"必要額：{total_bet:,}"
        )
        return

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
            prize = bet * SYMBOLS[symbol]["payout"]
            winnings += prize

            hits.append(
                f"ライン{index}："
                f"{get_symbol_text(ctx.guild, symbol)} ×3 "
                f"→ +{prize:,}{currency}"
            )

    after = before - total_bet + winnings

    try:
        set_balance(ctx.author.id, after)
    except Exception:
        print("[SLOT ERROR] Failed to save balance")
        traceback.print_exc()
        await ctx.send("⚠️ 所持金の保存に失敗したよ。")
        return

    rendered_grid = grid_text(grid, ctx.guild)

    log_data = {
        "timestamp": discord.utils.utcnow().isoformat(),
        "guild_id": ctx.guild.id,
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
    except Exception:
        print("[SLOT HISTORY ERROR]")
        traceback.print_exc()

    embed = discord.Embed(
        title="🎰 スロット結果",
        description=(
            f"{rendered_grid}\n\n"
            f"賭け金：{bet:,} × {lines}ライン\n"
            f"合計賭け金：{total_bet:,}{currency}\n"
            f"配当：{winnings:,}{currency}\n"
            f"収支：{winnings - total_bet:+,}{currency}\n"
            f"回転前：{before:,}{currency}\n"
            f"回転後：{after:,}{currency}"
        ),
        color=discord.Color.gold(),
    )

    embed.add_field(
        name="🎉 当たり！" if hits else "結果",
        value="\n".join(hits) if hits else "今回はハズレ！また挑戦してね。",
        inline=False,
    )

    await ctx.send(embed=embed)

    try:
        await send_slot_log(ctx.guild, log_data)
    except Exception:
        print("[SLOT LOG UNEXPECTED ERROR]")
        traceback.print_exc()


# ==================================================
# .Payment @ユーザー 金額
# ==================================================

@bot.command(
    name="Payment",
    help="ownerロール専用。コインを追加・減額する",
)
async def payment(ctx, member: discord.Member, amount: int):
    print(
        f"[PAYMENT] Command received: "
        f"operator={ctx.author.id}, "
        f"target={getattr(member, 'id', None)}, "
        f"amount={amount}, guild={getattr(ctx.guild, 'id', None)}"
    )

    if not is_owner(ctx.author):
        await ctx.send("⛔ このコマンドはownerロール専用だよ。")
        print("[PAYMENT] Rejected: owner role missing")
        return

    if member.bot:
        await ctx.send("⚠️ Botの残高は変更できないよ。")
        return

    if amount == 0 or abs(amount) > MAX_BET:
        await ctx.send("⚠️ 金額は ±1〜1,000,000,000 にしてね。")
        return

    before = get_balance(member.id)
    after = before + amount

    if after < 0:
        await ctx.send("❌ 所持金がマイナスになるため変更できないよ。")
        return

    try:
        set_balance(member.id, after)
    except Exception:
        print("[PAYMENT ERROR] Failed to save balance")
        traceback.print_exc()
        await ctx.send(
            "⚠️ 残高の保存に失敗したよ。RenderのLogsを確認してね。"
        )
        return

    action = "コイン追加" if amount > 0 else "コイン減額"
    log_sent = False

    try:
        log_sent = await send_coin_log(
            guild=ctx.guild,
            user_id=member.id,
            username=str(member),
            operator_id=ctx.author.id,
            action=action,
            before=before,
            change=amount,
            after=after,
        )
    except Exception:
        print("[PAYMENT ERROR] send_coin_log raised an exception")
        traceback.print_exc()

    currency = (
        get_guild_settings(ctx.guild.id)["currency_name"]
        if ctx.guild else "コイン"
    )

    message = (
        f"✅ {member.mention} の残高を変更したよ！\n"
        f"変更前：**{before:,} {currency}**\n"
        f"増減：**{amount:+,} {currency}**\n"
        f"変更後：**{after:,} {currency}**"
    )

    if log_sent:
        message += "\n📋 ログチャンネルへの送信：成功"
    else:
        message += (
            "\n⚠️ 残高変更は完了したけど、"
            "ログチャンネルへの送信は失敗したよ。"
            "\nRenderのLogsで `[COIN LOG ERROR]` を確認してね。"
        )

    try:
        await ctx.send(message)
    except discord.HTTPException:
        print("[PAYMENT ERROR] Failed to send command result")
        traceback.print_exc()

    print(
        f"[PAYMENT COMPLETE] target={member.id} "
        f"before={before} change={amount} after={after} "
        f"log_sent={log_sent}"
    )


# ==================================================
# .Mbot help
# ==================================================

@bot.command(name="Mbot", help="ヘルプコマンド")
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
        "`.Payment @ユーザー -100` コイン減額（ownerのみ）\n"
        "`.Mbot help` ウンコブリー\n"
        "`/setting` Bot設定パネル\n"
        "`/log panel` ログ設定\n"
        "`/coinrecovery` 残高を復元"
    )


# ==================================================
# /setting：モーダル
# ==================================================

class MaxBetModal(discord.ui.Modal, title="最大賭け金の設定"):
    max_bet = discord.ui.TextInput(
        label="最大賭け金",
        placeholder="例：1000000",
        min_length=1,
        max_length=10,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not is_owner(interaction.user):
            await interaction.response.send_message(
                "⛔ ownerロール専用だよ。",
                ephemeral=True,
            )
            return

        try:
            value = int(str(self.max_bet).strip())
        except ValueError:
            await interaction.response.send_message(
                "数字を入力してね。",
                ephemeral=True,
            )
            return

        if not 1 <= value <= MAX_BET:
            await interaction.response.send_message(
                f"1〜{MAX_BET:,} の範囲で設定してね。",
                ephemeral=True,
            )
            return

        config = get_guild_settings(interaction.guild.id)
        config["max_bet"] = value

        if not save_settings():
            await interaction.response.send_message(
                "⚠️ 設定の保存に失敗したよ。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ 最大賭け金を **{value:,}** に設定したよ。",
            ephemeral=True,
        )


class CurrencyModal(discord.ui.Modal, title="通貨名の設定"):
    currency_name = discord.ui.TextInput(
        label="通貨名",
        placeholder="例：コイン",
        min_length=1,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not is_owner(interaction.user):
            await interaction.response.send_message(
                "⛔ ownerロール専用だよ。",
                ephemeral=True,
            )
            return

        value = str(self.currency_name).strip()

        if not value:
            await interaction.response.send_message(
                "通貨名を入力してね。",
                ephemeral=True,
            )
            return

        config = get_guild_settings(interaction.guild.id)
        config["currency_name"] = value

        if not save_settings():
            await interaction.response.send_message(
                "⚠️ 設定の保存に失敗したよ。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ 通貨名を **{value}** に変更したよ。",
            ephemeral=True,
        )


# ==================================================
# /setting：モード選択
# ==================================================

class SlotModeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="スタンプモード",
                value="stamp",
                description="7️⃣を使う",
                emoji="7️⃣",
            ),
            discord.SelectOption(
                label="絵文字モード",
                value="emoji",
                description="7️⃣の絵柄にemoji_15を使う",
                emoji="🍒",
            ),
        ]

        super().__init__(
            placeholder="スロット表示モードを選択",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None or not is_owner(interaction.user):
            await interaction.response.send_message(
                "⛔ ownerロール専用だよ。",
                ephemeral=True,
            )
            return

        config = get_guild_settings(interaction.guild.id)
        config["slot_mode"] = self.values[0]

        if not save_settings():
            await interaction.response.send_message(
                "⚠️ 設定の保存に失敗したよ。",
                ephemeral=True,
            )
            return

        mode_name = (
            "スタンプモード（7️⃣）"
            if self.values[0] == "stamp"
            else "絵文字モード（emoji_15）"
        )

        await interaction.response.send_message(
            f"✅ 表示モードを **{mode_name}** に変更したよ！",
            ephemeral=True,
        )


class SettingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(SlotModeSelect())

    async def interaction_check(self, interaction: discord.Interaction):
        if not is_owner(interaction.user):
            await interaction.response.send_message(
                "⛔ ownerロール専用だよ。",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="スロット ON/OFF",
        style=discord.ButtonStyle.primary,
        emoji="🎰",
        row=1,
    )
    async def toggle_slot(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で使ってね。",
                ephemeral=True,
            )
            return

        config = get_guild_settings(interaction.guild.id)
        config["slot_enabled"] = not config["slot_enabled"]

        if not save_settings():
            await interaction.response.send_message(
                "⚠️ 設定の保存に失敗したよ。",
                ephemeral=True,
            )
            return

        state = "ON" if config["slot_enabled"] else "OFF"

        await interaction.response.send_message(
            f"🎰 スロットを **{state}** にしたよ。",
            ephemeral=True,
        )

    @discord.ui.button(
        label="最大賭け金",
        style=discord.ButtonStyle.secondary,
        emoji="💰",
        row=1,
    )
    async def set_max_bet(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(MaxBetModal())

    @discord.ui.button(
        label="通貨名",
        style=discord.ButtonStyle.secondary,
        emoji="🪙",
        row=2,
    )
    async def set_currency(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(CurrencyModal())


@bot.tree.command(
    name="setting",
    description="Botの設定パネルを開く",
)
async def setting_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "サーバー内で使ってね。",
            ephemeral=True,
        )
        return

    if not is_owner(interaction.user):
        await interaction.response.send_message(
            "⛔ この設定パネルはownerロール専用だよ。",
            ephemeral=True,
        )
        return

    config = get_guild_settings(interaction.guild.id)

    mode_name = (
        "スタンプモード（7️⃣）"
        if config["slot_mode"] == "stamp"
        else "絵文字モード（emoji_15）"
    )
    slot_state = "ON" if config["slot_enabled"] else "OFF"

    embed = discord.Embed(
        title="⚙️ Bot設定パネル",
        description=(
            f"**スロット表示モード：** {mode_name}\n"
            f"**スロット：** {slot_state}\n"
            f"**最大賭け金：** {config['max_bet']:,}\n"
            f"**通貨名：** {config['currency_name']}\n\n"
            "下のメニューから変更してね。"
        ),
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=SettingView(),
        ephemeral=True,
    )


# ==================================================
# /log panel：チャンネル選択
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
        try:
            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )
        except discord.HTTPException:
            traceback.print_exc()
            return

        try:
            guild = interaction.guild

            if guild is None:
                await interaction.followup.send(
                    "⚠️ サーバー内で使ってね。",
                    ephemeral=True,
                )
                return

            if not is_owner(interaction.user):
                await interaction.followup.send(
                    "⛔ ownerロール専用だよ。",
                    ephemeral=True,
                )
                return

            selected = self.values[0]

            if not isinstance(selected, discord.TextChannel):
                await interaction.followup.send(
                    "通常のテキストチャンネルを選んでね。",
                    ephemeral=True,
                )
                return

            me = guild.me

            if me is None:
                me = await guild.fetch_member(bot.user.id)

            perms = selected.permissions_for(me)

            if not (
                perms.view_channel
                and perms.send_messages
                and perms.embed_links
            ):
                await interaction.followup.send(
                    "⚠️ Botにチャンネル閲覧・メッセージ送信・"
                    "埋め込みリンクの権限が必要だよ。",
                    ephemeral=True,
                )
                return

            guild_key = str(guild.id)
            old_value = log_configs.get(guild_key)
            log_configs[guild_key] = selected.id

            if not save_configs():
                if old_value is None:
                    log_configs.pop(guild_key, None)
                else:
                    log_configs[guild_key] = old_value

                await interaction.followup.send(
                    "⚠️ 設定ファイルの保存に失敗したよ。",
                    ephemeral=True,
                )
                return

            print(
                f"[LOG SELECT OK] Guild={guild.id}, "
                f"Channel={selected.id}, Name={selected.name}"
            )

            await interaction.followup.send(
                f"✅ ログ送信先を {selected.mention} に設定したよ！",
                ephemeral=True,
            )

        except Exception as error:
            print(
                f"[LOG SELECT ERROR] {type(error).__name__}: {error}"
            )
            traceback.print_exc()

            try:
                await interaction.followup.send(
                    f"⚠️ チャンネル設定中にエラーが起きたよ："
                    f"`{type(error).__name__}`",
                    ephemeral=True,
                )
            except Exception:
                traceback.print_exc()


class LogPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(LogChannelSelect())


log_group = app_commands.Group(
    name="log",
    description="コインログの設定",
)


@log_group.command(
    name="panel",
    description="ログ送信先を設定する",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def log_panel(interaction: discord.Interaction):
    print(
        f"[DEBUG] /log panel received "
        f"user={interaction.user.id} guild={interaction.guild_id}"
    )

    await interaction.response.send_message(
        "ログを送信するチャンネルを選択してね。",
        view=LogPanelView(),
        ephemeral=True,
    )


bot.tree.add_command(log_group)


# ==================================================
# /coinrecovery
# ==================================================

@bot.tree.command(
    name="coinrecovery",
    description="ログチャンネルから全員の残高を復元",
)
@app_commands.describe(
    channel="コインログが保存されているチャンネル"
)
@app_commands.checks.has_permissions(administrator=True)
async def coinrecovery(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
):
    await interaction.response.defer(
        ephemeral=True,
        thinking=True,
    )

    if interaction.guild is None:
        await interaction.followup.send(
            "サーバー内で実行してね。",
            ephemeral=True,
        )
        return

    me = interaction.guild.me

    if me is None:
        me = await interaction.guild.fetch_member(bot.user.id)

    perms = channel.permissions_for(me)

    if not perms.view_channel or not perms.read_message_history:
        await interaction.followup.send(
            "Botにログチャンネルの閲覧権限と"
            "履歴読み取り権限が必要だよ。",
            ephemeral=True,
        )
        return

    latest = {}
    scanned = 0

    try:
        async for message in channel.history(
            limit=None,
            oldest_first=True,
        ):
            if bot.user is None or message.author.id != bot.user.id:
                continue

            for embed in message.embeds:
                title = embed.title or ""
                fields = {
                    field.name: field.value
                    for field in embed.fields
                }

                user_id = None
                balance_text = None

                if title == "🎰 スロットログ":
                    player_text = fields.get("プレイヤー", "")
                    match = re.search(
                        r"\(`?(\d{15,25})`?\)",
                        player_text,
                    )

                    if match:
                        user_id = match.group(1)

                    balance_text = fields.get("回転後の所持金", "")

                elif title == "💰 コイン増減ログ":
                    player_text = fields.get("対象者", "")
                    match = re.search(
                        r"\(`?(\d{15,25})`?\)",
                        player_text,
                    )

                    if match:
                        user_id = match.group(1)

                    balance_text = fields.get("変更後の所持金", "")

                if not user_id or not balance_text:
                    continue

                match = re.search(r"([\d,]+)", balance_text)

                if not match:
                    continue

                try:
                    user_id = str(int(user_id))
                    amount = int(match.group(1).replace(",", ""))
                except ValueError:
                    continue

                if amount < 0:
                    continue

                latest[user_id] = amount
                scanned += 1

    except discord.Forbidden:
        await interaction.followup.send(
            "ログを読み取れなかったよ。Botの権限を確認してね。",
            ephemeral=True,
        )
        return

    except discord.HTTPException as error:
        print("[COIN RECOVERY HTTP ERROR]")
        traceback.print_exc()

        await interaction.followup.send(
            f"ログ取得エラー：{type(error).__name__}",
            ephemeral=True,
        )
        return

    except Exception:
        print("[COIN RECOVERY ERROR]")
        traceback.print_exc()

        await interaction.followup.send(
            "⚠️ 復元中に予期しないエラーが起きたよ。",
            ephemeral=True,
        )
        return

    if not latest:
        await interaction.followup.send(
            "復元できるログが見つからなかったよ。\n"
            "正しいログチャンネルを選択しているか確認してね。",
            ephemeral=True,
        )
        return

    try:
        for user_id, amount in latest.items():
            set_balance(user_id, amount)

    except Exception:
        print("[COIN RECOVERY SAVE ERROR]")
        traceback.print_exc()

        await interaction.followup.send(
            "⚠️ 残高の保存に失敗したよ。",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"✅ 残高の復元が完了したよ！\n"
        f"復元人数：**{len(latest)}人**\n"
        f"読み取った記録：**{scanned}件**\n"
        f"ログチャンネル：{channel.mention}\n\n"
        "ログがないユーザーの残高は変更していないよ。",
        ephemeral=True,
    )


# ==================================================
# 起動
# ==================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN が設定されていないよ。"
        "RenderのEnvironmentを確認してね。"
    )


if __name__ == "__main__":
    Thread(
        target=run_web,
        daemon=True,
    ).start()

    bot.run(TOKEN)
