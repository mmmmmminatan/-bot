import asyncio
import json
import os
import random
import re
import traceback
from pathlib import Path
from threading import Thread
from datetime import datetime, timezone, timedelta

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

MAX_LOGS = 10000

# スロット・Payment・ログインボーナス共通のログ送信先
LOG_CHANNEL_ID = 1561184711571939438

BALANCES_FILE = Path("balances.json")
POSITIONS_FILE = Path("slot_positions.json")
SLOT_LOGS_FILE = Path("slot_logs.json")
LOG_CONFIG_FILE = Path("log_config.json")
COIN_LOGS_FILE = Path("coin_logs.json")
SETTINGS_FILE = Path("server_settings.json")

# ログインボーナス
DAILY_FILE = Path("daily_logs.json")
DAILY_REWARD = 1000
DAILY_STREAK_BONUS = 100
JST = timezone(timedelta(hours=9))

# 内部処理に使用する絵柄
SYMBOLS = ["🍒", "🍋", "⭐", "🔔", "7️⃣"]

PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐": 10,
    "7️⃣": 50,
}

# サーバー内のカスタム絵文字名
CUSTOM_EMOJI_NAMES = {
    "⭐": "emoji_12",
    "🍋": "emoji_13",
    "🔔": "emoji_14",
    "🍒": "emoji_15",
    "7️⃣": "emoji_16",
}

# 元の固定レーン
LANE_PATTERNS = [
    ["🍒", "🍋", "⭐", "🔔", "7️⃣"],
    ["⭐", "🍒", "7️⃣", "🍋", "🔔"],
    ["🔔", "7️⃣", "🍋", "⭐", "🍒"],
]

# 初期設定の出現比率
DEFAULT_WEIGHTS = {
    "🍒": 20,
    "🍋": 20,
    "⭐": 20,
    "🔔": 20,
    "7️⃣": 20,
}

# 最大賭け金の設定は撤廃
DEFAULT_SERVER_SETTINGS = {
    "min_bet": 1,
    "weights": DEFAULT_WEIGHTS.copy(),
    "slot_permission": "everyone",
    "maintenance": False,
    "emoji_mode": "unicode",
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
daily_data = load_json(DAILY_FILE, {})

# ログインボーナスの同時実行による二重受け取りを防止
DAILY_LOCK = asyncio.Lock()


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
        result = DEFAULT_SERVER_SETTINGS.copy()
        result["weights"] = DEFAULT_WEIGHTS.copy()
        return result

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

    if current.get("emoji_mode") not in ("unicode", "custom"):
        current["emoji_mode"] = "unicode"

    # 古い設定ファイルに max_bet が残っていても、
    # 現在の処理では参照しない。
    save_json(SETTINGS_FILE, server_settings)
    return current


def save_server_settings(guild_id):
    if guild_id is not None:
        save_json(SETTINGS_FILE, server_settings)


# ==================================================
# 絵柄の表示処理
# ==================================================

def find_custom_emoji(guild, symbol):
    """サーバー内から対応するカスタム絵文字を探す。"""

    if guild is None:
        return None

    emoji_name = CUSTOM_EMOJI_NAMES.get(symbol)

    if not emoji_name:
        return None

    for emoji in guild.emojis:
        if emoji.name == emoji_name:
            return emoji

    return None


def display_symbol(symbol, guild, settings):
    """画面表示用の絵柄を返す。"""

    if settings.get("emoji_mode", "unicode") == "custom":
        custom_emoji = find_custom_emoji(guild, symbol)

        if custom_emoji is not None:
            return str(custom_emoji)

    return symbol


def grid_text(grid, guild=None, settings=None):
    """盤面を表示用の文字列に変換する。"""

    if settings is None:
        settings = DEFAULT_SERVER_SETTINGS

    lines = []

    for row in grid:
        displayed_row = [
            display_symbol(symbol, guild, settings)
            for symbol in row
        ]

        lines.append("|" + "|".join(displayed_row) + "|")

    return "\n".join(lines)


def get_display_mode_name(settings):
    if settings.get("emoji_mode", "unicode") == "custom":
        return "サーバーのカスタム絵文字"

    return "通常の絵文字"


def get_custom_emoji_status(guild):
    """カスタム絵文字の登録状況を確認する。"""

    found = []
    missing = []

    for symbol in SYMBOLS:
        emoji_name = CUSTOM_EMOJI_NAMES[symbol]
        emoji = find_custom_emoji(guild, symbol)

        if emoji:
            found.append(f"{symbol} → {emoji_name}")
        else:
            missing.append(f"{symbol} → {emoji_name}")

    return found, missing


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
    print(f"固定ログチャンネルID: {LOG_CHANNEL_ID}")

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

    if is_admin(member):
        return True, None

    if settings.get("maintenance", False):
        return False, "現在メンテナンス中です。"

    permission = settings.get("slot_permission", "everyone")

    if permission == "admin":
        return False, "現在、スロットは管理者のみ利用できます。"

    if permission == "owner" and not has_owner_role(member):
        return False, (
            f"`{OWNER_ROLE_NAME}` ロールを持つメンバーのみ利用できます。"
        )

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
# ログチャンネル（固定）
# ==================================================

async def get_log_channel(guild):
    """
    スロットとPayment共通の固定ログチャンネルを取得する。
    log_config.jsonの設定には依存しない。
    """

    if guild is None:
        return None

    try:
        channel = bot.get_channel(LOG_CHANNEL_ID)

        if channel is None:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)

        if not isinstance(channel, discord.TextChannel):
            print(
                "[LOG ERROR] 指定先がテキストチャンネルではありません: "
                f"{LOG_CHANNEL_ID}"
            )
            return None

        if channel.guild.id != guild.id:
            print(
                "[LOG ERROR] 固定ログチャンネルが実行サーバーと異なります。"
                f"実行サーバー={guild.id}, "
                f"ログチャンネルのサーバー={channel.guild.id}"
            )
            return None

        me = channel.guild.me

        if me is None:
            print("[LOG ERROR] Botのサーバーメンバー情報を取得できません。")
            return None

        permissions = channel.permissions_for(me)

        if not permissions.view_channel:
            print("[LOG ERROR] ログチャンネルを見る権限がありません。")
            return None

        if not permissions.send_messages:
            print("[LOG ERROR] ログチャンネルに送信する権限がありません。")
            return None

        if not permissions.embed_links:
            print("[LOG ERROR] 埋め込みリンクの権限がありません。")
            return None

        return channel

    except discord.NotFound:
        print(
            f"[LOG ERROR] ログチャンネルが見つかりません: "
            f"{LOG_CHANNEL_ID}"
        )
    except discord.Forbidden:
        print(
            f"[LOG ERROR] ログチャンネルへのアクセスが拒否されました: "
            f"{LOG_CHANNEL_ID}"
        )
    except discord.HTTPException:
        print("[LOG ERROR] ログチャンネルの取得に失敗しました。")
        traceback.print_exc()
    except Exception:
        print("[LOG ERROR] ログチャンネル取得中に予期しないエラー。")
        traceback.print_exc()

    return None


def record_slot(data):
    data.setdefault(
        "timestamp",
        datetime.now(timezone.utc).timestamp(),
    )

    slot_logs.append(data)

    if len(slot_logs) > MAX_LOGS:
        del slot_logs[:-MAX_LOGS]

    save_json(SLOT_LOGS_FILE, slot_logs)


def record_coin(data):
    data.setdefault(
        "timestamp",
        datetime.now(timezone.utc).timestamp(),
    )

    coin_logs.append(data)

    if len(coin_logs) > MAX_LOGS:
        del coin_logs[:-MAX_LOGS]

    save_json(COIN_LOGS_FILE, coin_logs)


async def send_slot_log(guild, embed):
    channel = await get_log_channel(guild)

    if channel is None:
        print("[SLOT LOG] 固定ログチャンネルを取得できず、送信できませんでした。")
        return

    try:
        await channel.send(embed=embed)
        print(f"[SLOT LOG] 送信成功: channel={channel.id}")
    except Exception:
        print("[SLOT LOG SEND ERROR]")
        traceback.print_exc()


async def send_coin_log(guild, embed):
    channel = await get_log_channel(guild)

    if channel is None:
        print("[PAYMENT LOG] 固定ログチャンネルを取得できず、送信できませんでした。")
        return

    try:
        await channel.send(embed=embed)
        print(f"[PAYMENT LOG] 送信成功: channel={channel.id}")
    except Exception:
        print("[PAYMENT LOG SEND ERROR]")
        traceback.print_exc()


# ==================================================
# .daily（ログインボーナス）
# ==================================================

@bot.command(name="daily")
async def daily_command(ctx):
    if ctx.author.bot:
        return

    if ctx.guild is None:
        await ctx.reply(
            "このコマンドはサーバー内で使ってね。",
            mention_author=False,
        )
        return

    user_id = str(ctx.author.id)
    today = datetime.now(JST).date()
    today_text = today.isoformat()

    async with DAILY_LOCK:
        user_data = daily_data.get(user_id, {})

        last_date_text = user_data.get("last_date")

        try:
            streak = int(user_data.get("streak", 0))
        except (TypeError, ValueError):
            streak = 0

        # 今日すでに受け取っている場合
        if last_date_text == today_text:
            already_received = True
        else:
            already_received = False

            yesterday_text = (
                today - timedelta(days=1)
            ).isoformat()

            # 昨日受け取っていれば連続日数を継続
            if last_date_text == yesterday_text:
                streak += 1
            else:
                streak = 1

            # 基本報酬1000 + 連続日数×100
            reward = DAILY_REWARD + (
                streak * DAILY_STREAK_BONUS
            )

            current_balance = get_balance(ctx.author.id)
            new_balance = current_balance + reward

            # 残高を更新
            set_balance(ctx.author.id, new_balance)

            # ログイン状況を保存
            daily_data[user_id] = {
                "last_date": today_text,
                "streak": streak,
                "last_reward": reward,
                "last_balance": new_balance,
            }

            save_json(DAILY_FILE, daily_data)

            # 既存のコインログにも保存
            record_coin({
                "type": "daily",
                "timestamp": datetime.now(
                    timezone.utc
                ).timestamp(),
                "guild_id": ctx.guild.id,
                "user_id": ctx.author.id,
                "username": str(ctx.author),
                "amount": reward,
                "streak": streak,
                "balance": new_balance,
                "date": today_text,
            })

    if already_received:
        await ctx.reply(
            "今日はもうログインボーナスを受け取っているよ。",
            mention_author=False,
        )
        return

    # 指定された表示形式。余計な絵文字は追加しない。
    await ctx.reply(
        f"{streak}日目\n"
        f"増やした金額：+{reward:,} コイン",
        mention_author=False,
    )

    # 指定された固定ログチャンネルに送信
    channel = await get_log_channel(ctx.guild)

    if channel is None:
        print(
            "[DAILY LOG] 固定ログチャンネルを取得できませんでした。"
        )
        return

    try:
        await channel.send(
            f"ログインボーナス\n"
            f"やった人：{ctx.author.mention}\n"
            f"増やした金額：+{reward:,} コイン\n"
            f"何日目か：{streak}日目"
        )

        print(
            f"[DAILY LOG] 送信成功: "
            f"user={ctx.author.id}, "
            f"reward={reward}, streak={streak}"
        )

    except Exception:
        print("[DAILY LOG SEND ERROR]")
        traceback.print_exc()


# ==================================================
# .cash（残高確認）
# ==================================================

@bot.command(name="cash", aliases=["balance", "bal", "残高"])
async def cash_command(ctx, member: discord.Member = None):
    member = member or ctx.author
    amount = get_balance(member.id)

    embed = discord.Embed(
        title="💰 残高",
        description=(
            f"{member.mention} の残高："
            f"**{amount:,} コイン**"
        ),
        color=discord.Color.gold(),
    )

    await ctx.reply(embed=embed, mention_author=False)


# ==================================================
# /all cash（全メンバーの残高一覧）
# ==================================================

BALANCE_LIST_PER_PAGE = 15


class AllCashView(discord.ui.View):
    def __init__(self, ctx, pages, author_id):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.pages = pages
        self.page_index = 0
        self.author_id = author_id
        self.update_buttons()

    def update_buttons(self):
        self.previous_button.disabled = self.page_index <= 0
        self.next_button.disabled = (
            self.page_index >= len(self.pages) - 1
        )

    def make_embed(self):
        embed = discord.Embed(
            title="💰 全メンバーの残高一覧",
            description=self.pages[self.page_index],
            color=discord.Color.gold(),
        )

        embed.set_footer(
            text=f"{self.page_index + 1} / {len(self.pages)} ページ"
        )

        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "この一覧を操作できるのは実行した本人だけだよ。",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="前へ",
        emoji="◀️",
        style=discord.ButtonStyle.secondary,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.page_index -= 1
        self.update_buttons()

        await interaction.response.edit_message(
            embed=self.make_embed(),
            view=self,
        )

    @discord.ui.button(
        label="次へ",
        emoji="▶️",
        style=discord.ButtonStyle.secondary,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.page_index += 1
        self.update_buttons()

        await interaction.response.edit_message(
            embed=self.make_embed(),
            view=self,
        )


@bot.tree.command(
    name="all_cash",
    description="全メンバーの残高一覧を表示する（管理者・owner専用）",
)
@app_commands.checks.has_permissions(administrator=True)
async def all_cash_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "このコマンドはサーバー内で使ってね。",
            ephemeral=True,
        )
        return

    if not is_admin_or_owner(interaction.user):
        await interaction.response.send_message(
            f"このコマンドはサーバー管理者または `{OWNER_ROLE_NAME}` ロール専用だよ。",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        members = [
            member
            async for member in interaction.guild.fetch_members(limit=None)
            if not member.bot
        ]
    except Exception:
        print(
            "[ALL CASH] メンバー取得に失敗。"
            "キャッシュを使用します。"
        )
        traceback.print_exc()

        members = [
            member
            for member in interaction.guild.members
            if not member.bot
        ]

    members.sort(
        key=lambda m: (
            -int(balances.get(str(m.id), STARTING_BALANCE)),
            m.display_name.casefold(),
        )
    )

    if not members:
        await interaction.followup.send(
            "表示できるメンバーがいないよ。",
            ephemeral=True,
        )
        return

    lines = []

    for number, member in enumerate(members, start=1):
        amount = int(
            balances.get(str(member.id), STARTING_BALANCE)
        )

        lines.append(
            f"`{number:>3}.` {member.mention} — "
            f"**{amount:,} コイン**"
        )

    pages = [
        "\n".join(
            lines[index:index + BALANCE_LIST_PER_PAGE]
        )
        for index in range(0, len(lines), BALANCE_LIST_PER_PAGE)
    ]

    view = AllCashView(interaction, pages, interaction.user.id)

    await interaction.followup.send(
        embed=view.make_embed(),
        view=view,
        ephemeral=True,
    )


# ==================================================
# .slot
# 最高賭け金の制限なし
# ==================================================

@bot.command(name="slot")
async def slot_command(ctx, bet: int):
    if ctx.guild is None:
        await ctx.reply(
            "このコマンドはサーバー内で使ってね。",
            mention_author=False,
        )
        return

    settings = get_server_settings(ctx.guild.id)

    allowed, reason = can_use_slot(ctx.author, settings)

    if not allowed:
        await ctx.reply(reason, mention_author=False)
        return

    minimum = int(settings.get("min_bet", 1))

    if bet < minimum:
        await ctx.reply(
            f"最低賭け金は **{minimum:,} コイン** だよ。",
            mention_author=False,
        )
        return

    current_balance = get_balance(ctx.author.id)

    # 上限はないが、所持残高を超えた賭けはできない
    if bet > current_balance:
        await ctx.reply(
            f"残高が足りないよ！\n"
            f"残高：**{current_balance:,}** コイン",
            mention_author=False,
        )
        return

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

    new_balance = current_balance - bet
    payout = bet * multiplier

    if payout > 0:
        new_balance += payout

    set_balance(ctx.author.id, new_balance)

    profit = payout - bet

    if profit > 0:
        profit_text = f"+{profit:,}"
    elif profit < 0:
        profit_text = f"-{abs(profit):,}"
    else:
        profit_text = "±0"

    displayed_rows = []

    for row in grid:
        displayed_row = [
            display_symbol(symbol, ctx.guild, settings)
            for symbol in row
        ]

        displayed_rows.append(displayed_row)

    slot_display = (
        f"\\_\\_\\_SLOT\\_\\_\\_\n"
        f"|{'|'.join(displayed_rows[0])}|\n"
        f"|{'|'.join(displayed_rows[1])}|\n"
        f"|{'|'.join(displayed_rows[2])}|\n"
        f"￣￣￣￣￣￣\n"
        f"賭け金：{bet:,}コイン\n"
        f"収支：{profit_text}コイン\n"
        f"まわしたひと：{ctx.author.mention}"
    )

    if payout > 0:
        color = discord.Color.green()
    elif profit == 0:
        color = discord.Color.gold()
    else:
        color = discord.Color.red()

    embed = discord.Embed(
        description=slot_display,
        color=color,
    )

    await ctx.reply(
        embed=embed,
        mention_author=False,
    )

    displayed_grid = grid_text(
        grid,
        guild=ctx.guild,
        settings=settings,
    )

    log_data = {
        "type": "slot",
        "timestamp": datetime.now(timezone.utc).timestamp(),
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
        "emoji_mode": settings.get("emoji_mode", "unicode"),
    }

    record_slot(log_data)

    log_embed = discord.Embed(
        title="🎰 スロットログ",
        description=(
            f"ユーザー：{ctx.author.mention} (`{ctx.author.id}`)\n"
            f"賭け金：**{bet:,}**\n"
            f"配当：**{payout:,}**\n"
            f"収支：**{profit_text}**\n"
            f"残高：**{new_balance:,}**\n\n"
            f"{displayed_grid}"
        ),
        color=color,
    )

    await send_slot_log(ctx.guild, log_embed)


# ==================================================
# .Payment
# 付与額の上限なし
# ==================================================

@bot.command(name="Payment", aliases=["pay", "送金"])
async def payment_command(
    ctx,
    member: discord.Member,
    amount: int,
):
    if not has_owner_role(ctx.author):
        await ctx.reply(
            f"このコマンドは `{OWNER_ROLE_NAME}` ロール専用だよ。",
            mention_author=False,
        )
        return

    if member.bot:
        await ctx.reply(
            "Botには送金できないよ。",
            mention_author=False,
        )
        return

    if amount == 0:
        await ctx.reply(
            "金額は0以外にしてね。",
            mention_author=False,
        )
        return

    # 金額の上限チェックは撤廃
    # 正の値なら付与、負の値なら減額
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

    await ctx.reply(
        embed=embed,
        mention_author=False,
    )

    record_coin({
        "type": "payment",
        "timestamp": datetime.now(timezone.utc).timestamp(),
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

@bot.command(name="mhelp")
async def help_command(ctx):
    embed = discord.Embed(
        title="📖 コマンド一覧",
        description=(
            "**一般コマンド**\n"
            "`.slot 賭け金` — スロットを回す\n"
            "`.cash` — 自分の残高を見る\n"
            "`.cash @ユーザー` — 指定ユーザーの残高を見る\n"
            "`.daily` — ログインボーナスを受け取る\n"
            "`/all cash` — 全メンバーの残高一覧（管理者・owner専用）\n"
            "`.help` — この一覧を表示\n\n"
            "**owner only**\n"
            "`.Payment @ユーザー 金額` — 残高を増減する\n\n"
            "**owner only**\n"
            "`/setting` — Botの設定パネル\n"
            "`/log panel` — 固定ログ送信先の確認\n"
            "`/coinrecovery` — ログから残高を復旧"
        ),
        color=discord.Color.blurple(),
    )

    await ctx.reply(
        embed=embed,
        mention_author=False,
    )


# ==================================================
# .Mbot help
# ==================================================

@bot.group(name="Mbot", invoke_without_command=True)
async def mbot_group(ctx):
    await ctx.reply(
        "サブコマンドを指定してね。例：`.Mbot help`"
    )


@mbot_group.command(name="help")
async def mbot_help(ctx):
    await ctx.reply("ウンコブリー")


# ==================================================
# ログチャンネル選択UI（固定先の案内）
# ==================================================

class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="ログ送信先は固定されています",
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
                "サーバー管理者のみ確認できるよ。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"ログ送信先は固定されているよ。\n"
            f"スロットログ・Paymentログ共通："
            f"<#{LOG_CHANNEL_ID}>",
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
    description="固定ログ送信先を確認する",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def log_panel(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "サーバー内で使ってね。",
            ephemeral=True,
        )
        return

    channel = bot.get_channel(LOG_CHANNEL_ID)

    embed = discord.Embed(
        title="📝 固定ログ送信先",
        description=(
            f"スロットログとPaymentログは、"
            f"次のチャンネルに送信されるよ。\n\n"
            f"<#{LOG_CHANNEL_ID}>\n\n"
            f"チャンネルID：`{LOG_CHANNEL_ID}`"
        ),
        color=discord.Color.blurple(),
    )

    if channel is None:
        embed.add_field(
            name="状態",
            value="チャンネルを取得できません。IDとBotの権限を確認してね。",
            inline=False,
        )
    else:
        embed.add_field(
            name="状態",
            value="固定チャンネルを取得できました。",
            inline=False,
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


bot.tree.add_command(log_group)


# ==================================================
# /setting の各種モーダル
# 最大賭け金の設定は撤廃
# ==================================================

class BetSettingModal(discord.ui.Modal):
    def __init__(self, setting_type="min_bet"):
        self.setting_type = setting_type

        super().__init__(title="最低賭け金の設定")

        self.amount_input = discord.ui.TextInput(
            label="最低賭け金",
            placeholder="例：100",
            default="1",
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

        if amount < 1:
            await interaction.response.send_message(
                "最低賭け金は1以上にしてね。",
                ephemeral=True,
            )
            return

        settings = get_server_settings(interaction.guild.id)
        settings["min_bet"] = amount
        save_server_settings(interaction.guild.id)

        await interaction.response.send_message(
            f"最低賭け金を **{amount:,} コイン** に設定したよ。",
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
# 出目の絵文字タイプ設定
# ==================================================

class EmojiModeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="通常の絵文字",
                description="🍒 🍋 ⭐ 🔔 7️⃣ を使用する",
                value="unicode",
                emoji="🍒",
            ),
            discord.SelectOption(
                label="サーバーのカスタム絵文字",
                description="emoji_12〜emoji_16 を使用する",
                value="custom",
                emoji="⭐",
            ),
        ]

        super().__init__(
            placeholder="表示する絵文字タイプを選択",
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
                "サーバー管理者のみ変更できるよ。",
                ephemeral=True,
            )
            return

        selected_mode = self.values[0]
        settings = get_server_settings(interaction.guild.id)

        if selected_mode == "custom":
            found, missing = get_custom_emoji_status(interaction.guild)

            settings["emoji_mode"] = "custom"
            save_server_settings(interaction.guild.id)

            if missing:
                missing_text = "\n".join(missing)

                await interaction.response.send_message(
                    "カスタム絵文字モードに変更したよ。\n\n"
                    "ただし、次の絵文字はサーバー内で見つからなかったため、"
                    "通常の絵文字で表示するよ。\n"
                    f"{missing_text}\n\n"
                    "サーバー内の絵文字名が正しいか確認してね。",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "出目の表示を **サーバーのカスタム絵文字** "
                    "に変更したよ。\n"
                    "次のスロットから反映されるよ。",
                    ephemeral=True,
                )

        else:
            settings["emoji_mode"] = "unicode"
            save_server_settings(interaction.guild.id)

            await interaction.response.send_message(
                "出目の表示を **通常の絵文字** に変更したよ。\n"
                "次のスロットから反映されるよ。",
                ephemeral=True,
            )


class EmojiModeSettingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(EmojiModeSelect())


# ==================================================
# /setting 選択メニュー
# 最大賭け金の選択肢を削除
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
                label="絵柄・出現確率",
                description="スロットの絵柄ごとの比率を変更",
                value="weights",
                emoji="🎰",
            ),
            discord.SelectOption(
                label="出目の絵文字タイプ",
                description="通常の絵文字とカスタム絵文字を切り替え",
                value="emoji_mode",
                emoji="🎨",
            ),
            discord.SelectOption(
                label="ログ送信先",
                description="固定ログ送信先を確認",
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

        elif selected == "weights":
            await interaction.response.send_modal(
                WeightsSettingModal(settings["weights"])
            )

        elif selected == "emoji_mode":
            embed = discord.Embed(
                title="出目の絵文字タイプ",
                description=(
                    "スロット盤面に表示する絵文字を選択してね。\n\n"
                    "**通常の絵文字**\n"
                    "🍒 🍋 ⭐ 🔔 7️⃣\n\n"
                    "**サーバーのカスタム絵文字**\n"
                    "emoji_12〜emoji_16\n\n"
                    "変更は次のスロットから反映されるよ。"
                ),
                color=discord.Color.blurple(),
            )

            await interaction.response.send_message(
                embed=embed,
                view=EmojiModeSettingView(),
                ephemeral=True,
            )

        elif selected == "log_channel":
            await interaction.response.send_message(
                f"ログ送信先は固定されているよ。\n"
                f"スロットログ・Paymentログ・ログインボーナス共通："
                f"<#{LOG_CHANNEL_ID}>",
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
            f"スロット使用権限を **{labels[self.values[0]]}** "
            f"に変更したよ。",
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
            "メンテナンスモードを **ON** にしたよ。\n"
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
            "メンテナンスモードを **OFF** にしたよ。",
            ephemeral=True,
        )


# ==================================================
# /setting
# 最大賭け金の表示を削除
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
    log_channel = bot.get_channel(LOG_CHANNEL_ID)

    permission_labels = {
        "everyone": "全メンバー",
        "owner": "ownerロール以上",
        "admin": "管理者のみ",
    }

    embed = discord.Embed(
        title="Bot設定パネル",
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
            "ON"
            if settings.get("maintenance", False)
            else "OFF"
        ),
        inline=True,
    )

    embed.add_field(
        name="ログ送信先（固定）",
        value=(
            log_channel.mention
            if log_channel
            else f"チャンネルID: {LOG_CHANNEL_ID}"
        ),
        inline=True,
    )

    embed.add_field(
        name="出目の絵文字タイプ",
        value=get_display_mode_name(settings),
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
# JSONログ + Discord固定ログチャンネルから残高を復旧
# ==================================================

@bot.tree.command(
    name="coinrecovery",
    description="JSONとDiscordログから残高を復旧する",
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

    guild_id = interaction.guild.id
    latest_balances = {}
    combined_logs = []
    discord_log_count = 0
    json_log_count = 0
    errors = []

    # ----------------------------------------------
    # 1. JSONファイルのログを取得
    # ----------------------------------------------

    for item in slot_logs:
        try:
            if int(item.get("guild_id", 0)) == guild_id:
                combined_logs.append(item)
                json_log_count += 1
        except (TypeError, ValueError):
            continue

    for item in coin_logs:
        try:
            if int(item.get("guild_id", 0)) == guild_id:
                combined_logs.append(item)
                json_log_count += 1
        except (TypeError, ValueError):
            continue

    # ----------------------------------------------
    # 2. Discord固定ログチャンネルを取得
    # ----------------------------------------------

    channel = await get_log_channel(interaction.guild)

    if channel is None:
        errors.append(
            "固定ログチャンネルを取得できなかったよ。"
        )
    else:
        try:
            async for message in channel.history(
                limit=None,
                oldest_first=True,
            ):
                for embed in message.embeds:
                    title = embed.title or ""
                    description = embed.description or ""

                    # スロットログ
                    if "スロットログ" in title:
                        user_match = re.search(
                            r"ユーザー：.*?`(\d+)`",
                            description,
                        )
                        balance_match = re.search(
                            r"残高：\*\*([\d,]+)\*\*",
                            description,
                        )

                        if not user_match or not balance_match:
                            continue

                        user_id = user_match.group(1)
                        balance = int(
                            balance_match.group(1).replace(",", "")
                        )

                        combined_logs.append({
                            "type": "slot",
                            "timestamp": message.created_at.timestamp(),
                            "guild_id": guild_id,
                            "user_id": user_id,
                            "balance": balance,
                            "source": "discord",
                        })

                        discord_log_count += 1

                    # Paymentログ
                    elif "Paymentログ" in title:
                        user_match = re.search(
                            r"対象：.*?`(\d+)`",
                            description,
                        )
                        after_match = re.search(
                            r"変更後：\*\*([\d,]+)\*\*",
                            description,
                        )

                        if not user_match or not after_match:
                            continue

                        user_id = user_match.group(1)
                        balance = int(
                            after_match.group(1).replace(",", "")
                        )

                        combined_logs.append({
                            "type": "payment",
                            "timestamp": message.created_at.timestamp(),
                            "guild_id": guild_id,
                            "user_id": user_id,
                            "after": balance,
                            "source": "discord",
                        })

                        discord_log_count += 1

        except discord.Forbidden:
            errors.append(
                "ログチャンネルの閲覧権限または"
                "メッセージ履歴を読む権限がないよ。"
            )

        except discord.HTTPException:
            errors.append(
                "Discordからログを取得できなかったよ。"
            )
            traceback.print_exc()

        except Exception:
            errors.append(
                "ログの読み取り中にエラーが発生したよ。"
            )
            traceback.print_exc()

    # ----------------------------------------------
    # 3. ログを時刻順に並べて最新残高を計算
    # ----------------------------------------------

    combined_logs.sort(
        key=lambda item: float(item.get("timestamp", 0))
    )

    for item in combined_logs:
        user_id = item.get("user_id")

        if user_id is None:
            continue

        try:
            user_id = str(int(user_id))
        except (TypeError, ValueError):
            continue

        balance_value = None

        if "balance" in item:
            balance_value = item["balance"]
        elif "after" in item:
            balance_value = item["after"]

        if balance_value is None:
            continue

        try:
            latest_balances[user_id] = int(balance_value)
        except (TypeError, ValueError):
            continue

    # ----------------------------------------------
    # 4. 復旧対象がなければ終了
    # ----------------------------------------------

    if not latest_balances:
        message = (
            "復旧に使える残高ログが見つからなかったよ。\n\n"
            f"JSONログ件数：{json_log_count}\n"
            f"Discordログ件数：{discord_log_count}\n\n"
            "固定ログチャンネルにスロットログやPaymentログが"
            "残っているか確認してね。"
        )

        if errors:
            message += "\n\n確認事項：\n" + "\n".join(errors)

        await interaction.followup.send(
            message,
            ephemeral=True,
        )
        return

    # ----------------------------------------------
    # 5. 残高を保存
    # ----------------------------------------------

    restored_count = 0

    for user_id, amount in latest_balances.items():
        balances[user_id] = amount
        restored_count += 1

    save_json(BALANCES_FILE, balances)

    # ----------------------------------------------
    # 6. 結果を表示
    # ----------------------------------------------

    embed = discord.Embed(
        title="残高復旧完了",
        description=(
            f"復旧対象：**{restored_count}人**\n"
            f"JSONログ：**{json_log_count}件**\n"
            f"Discordログ：**{discord_log_count}件**\n\n"
            "確認できたログのうち、最も新しい残高を保存したよ。"
        ),
        color=discord.Color.green(),
    )

    if errors:
        embed.add_field(
            name="確認事項",
            value="\n".join(errors)[:1000],
            inline=False,
        )

    await interaction.followup.send(
        embed=embed,
        ephemeral=True,
    )


# ==================================================
# 設定の確認用コマンド
# 最大賭け金の表示を削除
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
        title="現在の設定",
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="最低賭け金",
        value=f"{int(settings['min_bet']):,}",
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
        value=(
            "ON" if settings.get("maintenance") else "OFF"
        ),
        inline=True,
    )

    embed.add_field(
        name="出目の絵文字タイプ",
        value=get_display_mode_name(settings),
        inline=True,
    )

    embed.add_field(
        name="絵柄ごとの比率",
        value=get_weights_text(settings["weights"]),
        inline=False,
    )

    embed.add_field(
        name="固定ログ送信先",
        value=f"<#{LOG_CHANNEL_ID}>",
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