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
# 基本設定
# ==================================================

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ROLE_NAME = "owner"
STARTING_BALANCE = 1000

MAX_BET = 1_000_000_000
MAX_LOGS = 10000

BALANCES_FILE = Path("balances.json")
POSITIONS_FILE = Path("slot_positions.json")
SLOT_LOGS_FILE = Path("slot_logs.json")
LOG_CONFIG_FILE = Path("log_config.json")
COIN_LOGS_FILE = Path("coin_logs.json")
SETTINGS_FILE = Path("server_settings.json")

SYMBOLS = ["🍒", "🍋", "⭐", "🔔", "7️⃣"]

PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐": 10,
    "7️⃣": 50,
}

# 元の固定レーン
LANE_PATTERNS = [
    ["🍒", "🍋", "⭐", "🔔", "7️⃣"],
    ["⭐", "🍒", "7️⃣", "🍋", "🔔"],
    ["🔔", "7️⃣", "🍋", "⭐", "🍒"],
]

# 初期設定の出現比率。比率なので合計100でなくてもOK
DEFAULT_WEIGHTS = {
    "🍒": 20,
    "🍋": 20,
    "⭐": 20,
    "🔔": 20,
    "7️⃣": 20,
}

DEFAULT_SERVER_SETTINGS = {
    "min_bet": 1,
    "max_bet": MAX_BET,
    "weights": DEFAULT_WEIGHTS.copy(),
    "slot_permission": "everyone",
    "maintenance": False,
}

# ==================================================
# JSON読み書き
# ==================================================

def load_json(path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
    except Exception:
        print(f"[JSON LOAD ERROR] {path}")
        traceback.print_exc()

    return default


def save_json(path, data):
    try:
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except Exception:
        print(f"[JSON SAVE ERROR] {path}")
        traceback.print_exc()


balances = load_json(BALANCES_FILE, {})
slot_positions = load_json(POSITIONS_FILE, {})
slot_logs = load_json(SLOT_LOGS_FILE, [])
log_configs = load_json(LOG_CONFIG_FILE, {})
coin_logs = load_json(COIN_LOGS_FILE, [])
server_settings = load_json(SETTINGS_FILE, {})


def get_balance(user_id):
    user_id = str(user_id)

    if user_id not in balances:
        balances[user_id] = STARTING_BALANCE
        save_json(BALANCES_FILE, balances)

    return int(balances[user_id])


def set_balance(user_id, amount):
    balances[str(user_id)] = int(amount)
    save_json(BALANCES_FILE, balances)


def get_server_settings(guild_id):
    """サーバー設定を取得。未設定の項目は初期値を使う。"""
    if guild_id is None:
        return DEFAULT_SERVER_SETTINGS.copy()

    guild_key = str(guild_id)

    if guild_key not in server_settings:
        server_settings[guild_key] = {}

    current = server_settings[guild_key]

    for key, value in DEFAULT_SERVER_SETTINGS.items():
        if key not in current:
            current[key] = (
                value.copy() if isinstance(value, dict) else value
            )

    if not isinstance(current.get("weights"), dict):
        current["weights"] = DEFAULT_WEIGHTS.copy()

    for symbol in SYMBOLS:
        current["weights"].setdefault(symbol, DEFAULT_WEIGHTS[symbol])

    save_json(SETTINGS_FILE, server_settings)
    return current


def save_server_settings(guild_id):
    if guild_id is not None:
        save_json(SETTINGS_FILE, server_settings)


# ==================================================
# Bot本体
# ==================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    case_insensitive=True,
)


@bot.event
async def on_ready():
    print(f"ログイン成功: {bot.user} ({bot.user.id})")

    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンド同期: {len(synced)}個")
    except Exception:
        print("[SLASH SYNC ERROR]")
        traceback.print_exc()


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    print(
        f"[MESSAGE] guild={message.guild.id if message.guild else 'DM'} "
        f"channel={message.channel.id} "
        f"user={message.author} "
        f"content={message.content[:150]}"
    )

    await bot.process_commands(message)


@bot.event
async def on_disconnect():
    print("[BOT] Discordから切断")


@bot.event
async def on_resumed():
    print("[BOT] Discordに再接続")


# ==================================================
# 権限チェック
# ==================================================

def has_owner_role(member):
    if not isinstance(member, discord.Member):
        return False

    return any(
        role.name.lower() == OWNER_ROLE_NAME.lower()
        for role in member.roles
    )


def is_admin(member):
    return (
        isinstance(member, discord.Member)
        and member.guild_permissions.administrator
    )


def is_admin_or_owner(member):
    return is_admin(member) or has_owner_role(member)


def can_use_slot(member, settings):
    """メンテナンス・スロット使用権限を確認する。"""

    # 管理者は設定確認や動作テストのため常に利用可能
    if is_admin(member):
        return True, None

    if settings.get("maintenance", False):
        return False, "現在メンテナンス中です。"

    permission = settings.get("slot_permission", "everyone")

    if permission == "admin":
        return False, "現在、スロットは管理者のみ利用できます。"

    if permission == "owner" and not has_owner_role(member):
        return False, f"`{OWNER_ROLE_NAME}` ロールを持つメンバーのみ利用できます。"

    return True, None


# ==================================================
# エラーハンドラー
# ==================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(
            f"引数が足りないよ。\nコマンド: `{ctx.prefix}{ctx.command}`",
            mention_author=False,
        )
        return

    if isinstance(error, commands.BadArgument):
        await ctx.reply(
            "入力内容が正しくないよ。数字やメンションを確認してね。",
            mention_author=False,
        )
        return

    if isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(
            f"少し待ってね。あと {error.retry_after:.1f} 秒で使えるよ。",
            mention_author=False,
        )
        return

    print("[COMMAND ERROR]")
    traceback.print_exception(
        type(error),
        error,
        error.__traceback__,
    )

    try:
        await ctx.reply(
            "コマンドの実行中にエラーが発生したよ。",
            mention_author=False,
        )
    except Exception:
        pass


@bot.tree.error
async def on_app_command_error(interaction, error):
    print("[SLASH COMMAND ERROR]")
    traceback.print_exception(
        type(error),
        error,
        error.__traceback__,
    )

    message = "スラッシュコマンドの実行中にエラーが発生したよ。"

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )
    except Exception:
        pass


# ==================================================
# ログチャンネル
# ==================================================

async def get_log_channel(guild):
    if guild is None:
        return None

    config = log_configs.get(str(guild.id), {})
    channel_id = config.get("channel_id")

    if not channel_id:
        return None

    channel = guild.get_channel(int(channel_id))

    if channel is None:
        try:
            channel = await guild.fetch_channel(int(channel_id))
        except Exception:
            return None

    if not isinstance(channel, discord.TextChannel):
        return None

    permissions = channel.permissions_for(guild.me)

    if not permissions.send_messages or not permissions.embed_links:
        return None

    return channel


def record_slot(data):
    slot_logs.append(data)

    if len(slot_logs) > MAX_LOGS:
        del slot_logs[:-MAX_LOGS]

    save_json(SLOT_LOGS_FILE, slot_logs)


def record_coin(data):
    coin_logs.append(data)

    if len(coin_logs) > MAX_LOGS:
        del coin_logs[:-MAX_LOGS]

    save_json(COIN_LOGS_FILE, coin_logs)


async def send_slot_log(guild, embed):
    channel = await get_log_channel(guild)

    if channel is None:
        return

    try:
        await channel.send(embed=embed)
    except Exception:
        print("[SLOT LOG SEND ERROR]")
        traceback.print_exc()


async def send_coin_log(guild, embed):
    channel = await get_log_channel(guild)

    if channel is None:
        return

    try:
        await channel.send(embed=embed)
    except Exception:
        print("[COIN LOG SEND ERROR]")
        traceback.print_exc()


# ==================================================
# スロット盤面
# ==================================================

def make_grid(positions, weights=None):
    """
    3レーン×3段の盤面を生成する。

    初期確率では元の固定レーンを使用する。
    管理者が確率を変更した場合は、その比率でレーンを生成する。
    """

    patterns = LANE_PATTERNS

    if weights:
        normalized = {
            symbol: max(0, int(weights.get(symbol, 0)))
            for symbol in SYMBOLS
        }

        if sum(normalized.values()) > 0:
            patterns = [
                random.choices(
                    SYMBOLS,
                    weights=[normalized[symbol] for symbol in SYMBOLS],
                    k=len(LANE_PATTERNS[lane_index]),
                )
                for lane_index in range(3)
            ]

    grid = []

    for row_offset in [-1, 0, 1]:
        row = []

        for lane_index in range(3):
            pattern = patterns[lane_index]
            position = positions[lane_index]
            row.append(pattern[(position + row_offset) % len(pattern)])

        grid.append(row)

    return grid


def grid_text(grid):
    return "\n".join(
        " | ".join(row)
        for row in grid
    )


def get_paylines(grid):
    """中央の横一列を配当判定に使う。"""
    return [grid[1]]


def get_weights_text(weights):
    total = sum(max(0, int(weights.get(symbol, 0))) for symbol in SYMBOLS)

    if total <= 0:
        return "確率設定が不正です。"

    lines = []

    for symbol in SYMBOLS:
        weight = max(0, int(weights.get(symbol, 0)))
        percentage = weight / total * 100
        lines.append(f"{symbol}：比率 {weight}（約 {percentage:.1f}%）")

    return "\n".join(lines)


# ==================================================
# .balance
# ==================================================

@bot.command(name="balance", aliases=["bal", "残高"])
async def balance_command(ctx, member: discord.Member = None):
    member = member or ctx.author
    amount = get_balance(member.id)

    embed = discord.Embed(
        title="💰 残高",
        description=f"{member.mention} の残高：**{amount:,} コイン**",
        color=discord.Color.gold(),
    )

    await ctx.reply(embed=embed, mention_author=False)


# ==================================================
# .slot
# ==================================================

@bot.command(name="slot")
async def slot_command(ctx, bet: int):
    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。")
        return

    settings = get_server_settings(ctx.guild.id)

    allowed, reason = can_use_slot(ctx.author, settings)

    if not allowed:
        await ctx.reply(reason)
        return

    minimum = int(settings.get("min_bet", 1))
    maximum = int(settings.get("max_bet", MAX_BET))

    if bet < minimum:
        await ctx.reply(
            f"最低賭け金は **{minimum:,} コイン** だよ。"
        )
        return

    if bet > maximum:
        await ctx.reply(
            f"最大賭け金は **{maximum:,} コイン** だよ。"
        )
        return

    if bet > MAX_BET:
        await ctx.reply(
            f"賭け金は最大 **{MAX_BET:,} コイン** までだよ。"
        )
        return

    current_balance = get_balance(ctx.author.id)

    if bet > current_balance:
        await ctx.reply(
            f"残高が足りないよ！\n"
            f"残高：**{current_balance:,}** コイン"
        )
        return

    # 3レーンそれぞれの停止位置
    positions = [
        random.randrange(len(LANE_PATTERNS[index]))
        for index in range(3)
    ]

    slot_positions[str(ctx.author.id)] = positions
    save_json(POSITIONS_FILE, slot_positions)

    weights = settings.get("weights", DEFAULT_WEIGHTS)
    grid = make_grid(positions, weights)
    paylines = get_paylines(grid)

    winning_symbol = None
    multiplier = 0

    for line in paylines:
        if line[0] == line[1] == line[2]:
            winning_symbol = line[0]
            multiplier = PAYOUTS.get(winning_symbol, 0)
            break

    # 賭け金を引いてから、配当を加算
    new_balance = current_balance - bet
    payout = bet * multiplier

    if payout > 0:
        new_balance += payout

    set_balance(ctx.author.id, new_balance)

    profit = payout - bet

    if payout > 0:
        result_text = (
            f"🎉 **当たり！**\n"
            f"絵柄：{winning_symbol}\n"
            f"倍率：**{multiplier}倍**\n"
            f"配当：**{payout:,} コイン**"
        )
        color = discord.Color.green()
    else:
        result_text = (
            "残念！今回は当たりなし。\n"
            f"損失：**{bet:,} コイン**"
        )
        color = discord.Color.red()

    embed = discord.Embed(
        title="🎰 スロット結果",
        description=(
            f"プレイヤー：{ctx.author.mention}\n"
            f"賭け金：**{bet:,} コイン**\n\n"
            f"```text\n{grid_text(grid)}\n```\n"
            f"{result_text}\n\n"
            f"収支：**{profit:+,} コイン**\n"
            f"現在の残高：**{new_balance:,} コイン**"
        ),
        color=color,
    )

    await ctx.reply(embed=embed, mention_author=False)

    log_data = {
        "type": "slot",
        "guild_id": ctx.guild.id,
        "user_id": ctx.author.id,
        "username": str(ctx.author),
        "bet": bet,
        "payout": payout,
        "profit": profit,
        "balance": new_balance,
        "grid": grid,
        "winning_symbol": winning_symbol,
        "multiplier": multiplier,
    }

    record_slot(log_data)

    log_embed = discord.Embed(
        title="🎰 スロットログ",
        description=(
            f"ユーザー：{ctx.author.mention} (`{ctx.author.id}`)\n"
            f"賭け金：**{bet:,}**\n"
            f"配当：**{payout:,}**\n"
            f"収支：**{profit:+,}**\n"
            f"残高：**{new_balance:,}**\n\n"
            f"```text\n{grid_text(grid)}\n```"
        ),
        color=color,
    )

    await send_slot_log(ctx.guild, log_embed)


# ==================================================
# .Payment
# ==================================================

@bot.command(name="Payment", aliases=["pay", "送金"])
async def payment_command(
    ctx,
    member: discord.Member,
    amount: int,
):
    if not has_owner_role(ctx.author):
        await ctx.reply(
            f"このコマンドは `{OWNER_ROLE_NAME}` ロール専用だよ。"
        )
        return

    if member.bot:
        await ctx.reply("Botには送金できないよ。")
        return

    if amount == 0:
        await ctx.reply("金額は0以外にしてね。")
        return

    if abs(amount) > MAX_BET:
        await ctx.reply(
            f"金額は ±{MAX_BET:,} コイン以内にしてね。"
        )
        return

    before = get_balance(member.id)
    after = before + amount

    set_balance(member.id, after)

    embed = discord.Embed(
        title="💸 Payment",
        description=(
            f"対象：{member.mention}\n"
            f"変更額：**{amount:+,} コイン**\n"
            f"変更前：**{before:,} コイン**\n"
            f"変更後：**{after:,} コイン**\n"
            f"実行者：{ctx.author.mention}"
        ),
        color=discord.Color.blurple(),
    )

    await ctx.reply(embed=embed, mention_author=False)

    record_coin({
        "type": "payment",
        "guild_id": ctx.guild.id if ctx.guild else None,
        "user_id": member.id,
        "username": str(member),
        "actor_id": ctx.author.id,
        "actor_name": str(ctx.author),
        "amount": amount,
        "before": before,
        "after": after,
    })

    log_embed = discord.Embed(
        title="💸 Paymentログ",
        description=(
            f"対象：{member.mention} (`{member.id}`)\n"
            f"実行者：{ctx.author.mention} (`{ctx.author.id}`)\n"
            f"変更額：**{amount:+,}**\n"
            f"変更前：**{before:,}**\n"
            f"変更後：**{after:,}**"
        ),
        color=discord.Color.blurple(),
    )

    if ctx.guild:
        await send_coin_log(ctx.guild, log_embed)


# ==================================================
# .help
# ==================================================

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="📖 コマンド一覧",
        description=(
            "**一般コマンド**\n"
            "`.slot 賭け金` — スロットを回す\n"
            "`.balance` — 自分の残高を見る\n"
            "`.balance @ユーザー` — 指定ユーザーの残高を見る\n"
            "`.help` — この一覧を表示\n\n"
            "**ownerロール専用**\n"
            "`.Payment @ユーザー 金額` — 残高を増減する\n\n"
            "**サーバー管理者向け**\n"
            "`/setting` — Botの設定パネル\n"
            "`/log panel` — ログ送信先設定\n"
            "`/coinrecovery` — ログから残高を復旧"
        ),
        color=discord.Color.blurple(),
    )

    await ctx.reply(embed=embed, mention_author=False)


# ==================================================
# .Mbot help
# ==================================================

@bot.group(name="Mbot", invoke_without_command=True)
async def mbot_group(ctx):
    await ctx.reply("サブコマンドを指定してね。例：`.Mbot help`")


@mbot_group.command(name="help")
async def mbot_help(ctx):
    await ctx.reply("ウンコブリー")


# ==================================================
# ログチャンネル選択UI
# ==================================================

class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="ログ送信先チャンネルを選択",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で使ってね。",
                ephemeral=True,
            )
            return

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "サーバー管理者のみ変更できるよ。",
                ephemeral=True,
            )
            return

        channel = self.values[0]

        log_configs[str(interaction.guild.id)] = {
            "channel_id": channel.id
        }
        save_json(LOG_CONFIG_FILE, log_configs)

        await interaction.response.send_message(
            f"ログ送信先を {channel.mention} に設定したよ。",
            ephemeral=True,
        )


class LogChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(LogChannelSelect())


# ==================================================
# /log panel
# ==================================================

log_group = app_commands.Group(
    name="log",
    description="ログ設定",
)


@log_group.command(
    name="panel",
    description="ログ送信先を設定する",
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
        title="📝 ログ設定パネル",
        description="ログを送信するチャンネルを選択してね。",
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=LogChannelView(),
        ephemeral=True,
    )


bot.tree.add_command(log_group)


# ==================================================
# /setting の各種モーダル
# ==================================================

class BetSettingModal(discord.ui.Modal):
    def __init__(self, setting_type):
        self.setting_type = setting_type

        if setting_type == "min_bet":
            title = "最低賭け金の設定"
            label = "最低賭け金"
        else:
            title = "最大賭け金の設定"
            label = "最大賭け金"

        super().__init__(title=title)

        self.amount_input = discord.ui.TextInput(
            label=label,
            placeholder="例：100",
            default=str(
                1 if setting_type == "min_bet" else MAX_BET
            ),
            required=True,
            min_length=1,
            max_length=15,
        )

        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で使ってね。",
                ephemeral=True,
            )
            return

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "サーバー管理者のみ変更できるよ。",
                ephemeral=True,
            )
            return

        try:
            amount = int(str(self.amount_input.value).strip())
        except ValueError:
            await interaction.response.send_message(
                "整数で入力してね。",
                ephemeral=True,
            )
            return

        if amount < 1 or amount > MAX_BET:
            await interaction.response.send_message(
                f"1〜{MAX_BET:,} の範囲で入力してね。",
                ephemeral=True,
            )
            return

        settings = get_server_settings(interaction.guild.id)

        if self.setting_type == "min_bet":
            current_max = int(settings["max_bet"])

            if amount > current_max:
                await interaction.response.send_message(
                    "最低賭け金は最大賭け金以下にしてね。",
                    ephemeral=True,
                )
                return

            settings["min_bet"] = amount
            message = f"最低賭け金を **{amount:,} コイン** に設定したよ。"

        else:
            current_min = int(settings["min_bet"])

            if amount < current_min:
                await interaction.response.send_message(
                    "最大賭け金は最低賭け金以上にしてね。",
                    ephemeral=True,
                )
                return

            settings["max_bet"] = amount
            message = f"最大賭け金を **{amount:,} コイン** に設定したよ。"

        save_server_settings(interaction.guild.id)

        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


class WeightsSettingModal(discord.ui.Modal):
    def __init__(self, current_weights):
        super().__init__(title="スロット確率の設定")

        current_value = ",".join(
            f"{symbol}={current_weights.get(symbol, 0)}"
            for symbol in SYMBOLS
        )

        self.weights_input = discord.ui.TextInput(
            label="絵柄ごとの比率",
            placeholder="🍒=20,🍋=20,⭐=20,🔔=20,7️⃣=20",
            default=current_value,
            required=True,
            max_length=200,
            style=discord.TextStyle.paragraph,
        )

        self.add_item(self.weights_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で使ってね。",
                ephemeral=True,
            )
            return

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "サーバー管理者のみ変更できるよ。",
                ephemeral=True,
            )
            return

        raw = str(self.weights_input.value).strip()
        parsed = {}

        try:
            parts = raw.split(",")

            for part in parts:
                if "=" not in part:
                    raise ValueError

                symbol, value = part.split("=", 1)
                symbol = symbol.strip()
                value = int(value.strip())

                if symbol not in SYMBOLS:
                    raise ValueError

                if value < 0 or value > 1000:
                    raise ValueError

                parsed[symbol] = value

            if any(symbol not in parsed for symbol in SYMBOLS):
                raise ValueError

            if sum(parsed.values()) <= 0:
                raise ValueError

        except ValueError:
            await interaction.response.send_message(
                "入力形式が正しくないよ。\n"
                "例：`🍒=20,🍋=20,⭐=20,🔔=20,7️⃣=20`\n"
                "各数値は0〜1000で、合計を1以上にしてね。",
                ephemeral=True,
            )
            return

        settings = get_server_settings(interaction.guild.id)
        settings["weights"] = parsed
        save_server_settings(interaction.guild.id)

        embed = discord.Embed(
            title="🎰 出現比率を更新したよ",
            description=get_weights_text(parsed),
            color=discord.Color.green(),
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )


# ==================================================
# /setting 選択メニュー
# ==================================================

class SettingActionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="最低賭け金",
                description="スロットの最低賭け金を変更",
                value="min_bet",
                emoji="🪙",
            ),
            discord.SelectOption(
                label="最大賭け金",
                description="スロットの最大賭け金を変更",
                value="max_bet",
                emoji="💰",
            ),
            discord.SelectOption(
                label="絵柄・出現確率",
                description="スロットの絵柄ごとの比率を変更",
                value="weights",
                emoji="🎰",
            ),
            discord.SelectOption(
                label="ログ送信先",
                description="ログチャンネルを変更",
                value="log_channel",
                emoji="📝",
            ),
            discord.SelectOption(
                label="コマンド使用権限",
                description="スロットを使えるメンバーを変更",
                value="permissions",
                emoji="🔐",
            ),
            discord.SelectOption(
                label="メンテナンスモード",
                description="一般メンバーのスロットを停止・再開",
                value="maintenance",
                emoji="🛠️",
            ),
        ]

        super().__init__(
            placeholder="変更する設定を選択してね",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で使ってね。",
                ephemeral=True,
            )
            return

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "サーバー管理者のみ設定を変更できるよ。",
                ephemeral=True,
            )
            return

        selected = self.values[0]
        settings = get_server_settings(interaction.guild.id)

        if selected == "min_bet":
            await interaction.response.send_modal(
                BetSettingModal("min_bet")
            )

        elif selected == "max_bet":
            await interaction.response.send_modal(
                BetSettingModal("max_bet")
            )

        elif selected == "weights":
            await interaction.response.send_modal(
                WeightsSettingModal(settings["weights"])
            )

        elif selected == "log_channel":
            embed = discord.Embed(
                title="📝 ログ送信先設定",
                description="ログを送るチャンネルを選んでね。",
                color=discord.Color.blurple(),
            )

            await interaction.response.send_message(
                embed=embed,
                view=LogChannelView(),
                ephemeral=True,
            )

        elif selected == "permissions":
            await interaction.response.send_message(
                "スロットを利用できるメンバーを選択してね。",
                view=PermissionSettingView(),
                ephemeral=True,
            )

        elif selected == "maintenance":
            await interaction.response.send_message(
                "メンテナンスモードを切り替えるよ。",
                view=MaintenanceSettingView(),
                ephemeral=True,
            )


class SettingPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(SettingActionSelect())


# ==================================================
# スロット使用権限の設定
# ==================================================

class PermissionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="全メンバー",
                description="全員がスロットを使える",
                value="everyone",
                emoji="👥",
            ),
            discord.SelectOption(
                label="ownerロール以上",
                description="ownerロールまたは管理者のみ",
                value="owner",
                emoji="👑",
            ),
            discord.SelectOption(
                label="管理者のみ",
                description="サーバー管理者のみ",
                value="admin",
                emoji="🔐",
            ),
        ]

        super().__init__(
            placeholder="利用できるメンバーを選択",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None or not is_admin(interaction.user):
            await interaction.response.send_message(
                "サーバー管理者のみ変更できるよ。",
                ephemeral=True,
            )
            return

        settings = get_server_settings(interaction.guild.id)
        settings["slot_permission"] = self.values[0]
        save_server_settings(interaction.guild.id)

        labels = {
            "everyone": "全メンバー",
            "owner": "ownerロール以上",
            "admin": "管理者のみ",
        }

        await interaction.response.send_message(
            f"スロット使用権限を **{labels[self.values[0]]}** に変更したよ。",
            ephemeral=True,
        )


class PermissionSettingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(PermissionSelect())


# ==================================================
# メンテナンスモード
# ==================================================

class MaintenanceSettingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(
        label="メンテナンス開始",
        style=discord.ButtonStyle.danger,
        emoji="🔴",
    )
    async def enable_maintenance(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.guild is None or not is_admin(interaction.user):
            await interaction.response.send_message(
                "サーバー管理者のみ変更できるよ。",
                ephemeral=True,
            )
            return

        settings = get_server_settings(interaction.guild.id)
        settings["maintenance"] = True
        save_server_settings(interaction.guild.id)

        await interaction.response.send_message(
            "🔴 メンテナンスモードを **ON** にしたよ。\n"
            "一般メンバーはスロットを使えなくなるよ。管理者は利用可能。",
            ephemeral=True,
        )

    @discord.ui.button(
        label="メンテナンス終了",
        style=discord.ButtonStyle.success,
        emoji="🟢",
    )
    async def disable_maintenance(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.guild is None or not is_admin(interaction.user):
            await interaction.response.send_message(
                "サーバー管理者のみ変更できるよ。",
                ephemeral=True,
            )
            return

        settings = get_server_settings(interaction.guild.id)
        settings["maintenance"] = False
        save_server_settings(interaction.guild.id)

        await interaction.response.send_message(
            "🟢 メンテナンスモードを **OFF** にしたよ。",
            ephemeral=True,
        )


# ==================================================
# /setting
# ==================================================

@bot.tree.command(
    name="setting",
    description="Botの設定パネルを開く",
)
@app_commands.checks.has_permissions(administrator=True)
async def setting_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "サーバー内で使ってね。",
            ephemeral=True,
        )
        return

    settings = get_server_settings(interaction.guild.id)

    log_config = log_configs.get(str(interaction.guild.id), {})
    channel_id = log_config.get("channel_id")
    log_channel = (
        interaction.guild.get_channel(int(channel_id))
        if channel_id
        else None
    )

    permission_labels = {
        "everyone": "全メンバー",
        "owner": "ownerロール以上",
        "admin": "管理者のみ",
    }

    embed = discord.Embed(
        title="⚙️ Bot設定パネル",
        description=(
            "下のメニューから変更したい設定を選んでね。\n"
            "設定の変更はサーバー管理者のみ可能だよ。"
        ),
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="最低賭け金",
        value=f"{int(settings['min_bet']):,} コイン",
        inline=True,
    )

    embed.add_field(
        name="最大賭け金",
        value=f"{int(settings['max_bet']):,} コイン",
        inline=True,
    )

    embed.add_field(
        name="スロット使用権限",
        value=permission_labels.get(
            settings.get("slot_permission", "everyone"),
            "全メンバー",
        ),
        inline=True,
    )

    embed.add_field(
        name="メンテナンス",
        value=(
            "🔴 ON"
            if settings.get("maintenance", False)
            else "🟢 OFF"
        ),
        inline=True,
    )

    embed.add_field(
        name="ログ送信先",
        value=log_channel.mention if log_channel else "未設定",
        inline=True,
    )

    embed.add_field(
        name="絵柄・出現比率",
        value=get_weights_text(settings["weights"]),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        view=SettingPanelView(),
        ephemeral=True,
    )


# ==================================================
# /coinrecovery
# ==================================================

@bot.tree.command(
    name="coinrecovery",
    description="ログを使って残高を復旧する",
)
@app_commands.checks.has_permissions(administrator=True)
async def coinrecovery_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "サーバー内で使ってね。",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    # 保存済みログを時系列に並べ、各ユーザーの最新残高を採用
    latest_balances = {}

    combined_logs = []

    for item in slot_logs:
        if item.get("guild_id") == interaction.guild.id:
            combined_logs.append(item)

    for item in coin_logs:
        if item.get("guild_id") == interaction.guild.id:
            combined_logs.append(item)

    # 過去ログに時刻がある場合は時刻順にする
    combined_logs.sort(key=lambda item: item.get("timestamp", 0))

    for item in combined_logs:
        user_id = item.get("user_id")
        if user_id is None:
            continue

        # slotログはbalance、Paymentログはafterを保持
        if "balance" in item:
            latest_balances[str(user_id)] = int(item["balance"])
        elif "after" in item:
            latest_balances[str(user_id)] = int(item["after"])

    if not latest_balances:
        await interaction.followup.send(
            "復旧に使えるログが見つからなかったよ。",
            ephemeral=True,
        )
        return

    balances.update(latest_balances)
    save_json(BALANCES_FILE, balances)

    await interaction.followup.send(
        f"✅ 残高を復旧したよ。\n"
        f"復旧対象：**{len(latest_balances)}人**",
        ephemeral=True,
    )


# ==================================================
# 設定の確認用コマンド
# ==================================================

@bot.tree.command(
    name="settinginfo",
    description="現在のBot設定を表示する",
)
async def setting_info_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "サーバー内で使ってね。",
            ephemeral=True,
        )
        return

    settings = get_server_settings(interaction.guild.id)

    permission_labels = {
        "everyone": "全メンバー",
        "owner": "ownerロール以上",
        "admin": "管理者のみ",
    }

    embed = discord.Embed(
        title="⚙️ 現在の設定",
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="最低賭け金",
        value=f"{int(settings['min_bet']):,}",
        inline=True,
    )

    embed.add_field(
        name="最大賭け金",
        value=f"{int(settings['max_bet']):,}",
        inline=True,
    )

    embed.add_field(
        name="使用権限",
        value=permission_labels.get(
            settings.get("slot_permission", "everyone"),
            "全メンバー",
        ),
        inline=True,
    )

    embed.add_field(
        name="メンテナンス",
        value="ON" if settings.get("maintenance") else "OFF",
        inline=True,
    )

    embed.add_field(
        name="絵柄ごとの比率",
        value=get_weights_text(settings["weights"]),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ==================================================
# Flask（Renderの稼働確認用）
# ==================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!"


@app.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False,
    )


# ==================================================
# 起動
# ==================================================

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "環境変数 DISCORD_TOKEN が設定されていません。"
        )

    Thread(target=run_web, daemon=True).start()
    bot.run(TOKEN)