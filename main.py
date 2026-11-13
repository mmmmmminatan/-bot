import asyncio
import json
import math
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


# ==========================================
# 1. ボットの基本設定
# ==========================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    case_insensitive=True,
)

# ==========================================
# 2. あう検知設定
# ==========================================

# 「あう」「au」「㋐㋒」などを検知（記号・空白を挟んでもOK、逆順は対象外）
pattern = re.compile(r"[あアぁァ㋐aAａＡ][\W_]*[うウぅゥ㋒uUｕＵ]", re.IGNORECASE)

# 返信する文章
REPLY_TEXT = (
    "😅😅😅😅😅😅😅😅😅😅😅😅😅\n"
    "😅✋⚠️あうを検知しました⚠️✋😅\n"
    "😅😅😅😅😅😅😅😅😅😅😅😅😅"
)

# ==========================================
# 3. 起動イベント
# ==========================================

@bot.event
async def on_ready():
    print(f"ログイン成功: {bot.user} ({bot.user.id})")

    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンド同期: {len(synced)}個")

    except Exception:
        print("[SLASH SYNC ERROR]")
        traceback.print_exc()

# ==========================================
# 4. メッセージ検知イベント
# ==========================================

@bot.event
async def on_message(message):

    # Bot自身・ほかのBotには反応しない
    if message.author.bot:
        return

    # メッセージ受信ログ
    print(f"受信メッセージ: {message.content}")

    # あうを検知
    if pattern.search(message.content):

        try:
            await message.channel.send(REPLY_TEXT)

            print("あうを検知して返信しました！")

        except Exception:
            print("[REPLY ERROR]")
            traceback.print_exc()

    # MINESだけは先頭の . を省略しても起動できるようにする
    # 例: mine all 3 1 / mine 250000 3 1
    original_content = message.content
    if re.match(r"^mine(?:\s|$)", original_content, re.IGNORECASE):
        message.content = "." + original_content

    try:
        # ほかのコマンドも動かす
        await bot.process_commands(message)
    finally:
        message.content = original_content


# ==================================================
# 基本設定
# ==================================================

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_USER_ID = 1325449934236942392
OWNER_ROLE_NAME = "owner"

STARTING_BALANCE = 1000
MAX_LOGS = 10000
LOG_CHANNEL_ID = 1561184711571939438

BALANCES_FILE = Path("balances.json")
POSITIONS_FILE = Path("slot_positions.json")
SLOT_LOGS_FILE = Path("slot_logs.json")
LOG_CONFIG_FILE = Path("log_config.json")
COIN_LOGS_FILE = Path("coin_logs.json")
SETTINGS_FILE = Path("server_settings.json")
DAILY_FILE = Path("daily_logs.json")
GUESS_FILE = Path("guess_data.json")
JACKPOT_FILE = Path("jackpot_data.json")
WELCOME_LOG_FILE = Path(os.getenv("DATA_DIR", ".")) / "welcome_log_configs.json"
# RenderのPersistent Diskを /data にマウントし、DATA_DIR=/data を設定すると再デプロイ後も保持される
AU_WHITELIST_FILE = Path(os.getenv("DATA_DIR", ".")) / "au_whitelist.json"

DAILY_REWARD = 1000
DAILY_STREAK_BONUS = 100
JST = timezone(timedelta(hours=9))

SYMBOLS = ["🍒", "🍋", "⭐", "🔔", "7️⃣", "💣", "JP"]


PAYOUTS = {
    "🍒": 5,
    "🍋": 8,
    "🔔": 10,
    "⭐": 25,
    "7️⃣": 45,
    "💣": 35,
    "JP": 75,
}


CUSTOM_EMOJI_NAMES = {
    "⭐": "emoji_12",
    "🍋": "emoji_13",
    "🔔": "emoji_14",
    "🍒": "emoji_15",
    "7️⃣": "emoji_16",
    "💣": "emoji_19",
}


LANE_PATTERNS = [
    ["🍒", "🍋", "💣", "🔔", "7️⃣", "JP"],
    ["⭐", "🍒", "💣", "🍋", "🔔", "7️⃣"],
    ["💣", "7️⃣", "🍋", "JP", "🍒", "🔔"],
]


DEFAULT_WEIGHTS = {
    "🍒": 20,
    "🍋": 20,
    "⭐": 20,
    "🔔": 20,
    "7️⃣": 20,
    "💣": 20,
    "JP": 5,
}


DEFAULT_SERVER_SETTINGS = {
    "min_bet": 1,
    "weights": DEFAULT_WEIGHTS.copy(),
    "slot_permission": "everyone",
    "maintenance": False,
    "emoji_mode": "custom",
}
# ==================================================
# 数字カスタム絵文字（0〜9）
# ==================================================

NUMBER_EMOJIS = {
    0: "<:0_:1564500720936427590>",
    1: "<:1_:1564500738808225812>",
    2: "<:2_:1564500764758646834>",
    3: "<:3_:1564500782492028958>",
    4: "<:4_:1564500797889454080>",
    5: "<:5_:1564500816658829312>",
    6: "<:6_:1564500833775788133>",
    7: "<:7_:1564500859595915334>",
    8: "<:8_:1564500891284021261>",
    9: "<:9_:1564500923068448798>",
}

def number_emoji(value):
    return "".join(
        NUMBER_EMOJIS[int(char)] if char.isdigit() else char
        for char in str(value)
    )
# ==================================================
# 金額表示
# ==================================================

def money(amount):
    amount = int(amount)
    if amount < 0:
        return f"-${abs(amount):,}"
    return f"${amount:,}"

def money_change(amount):
    amount = int(amount)
    if amount > 0:
        return f"+${amount:,}"
    if amount < 0:
        return f"-${abs(amount):,}"
    return "±$0"

def parse_money_text(value):
    value = str(value).strip()
    value = value.replace("$", "").replace(",", "").replace(" ", "")
    if value.startswith("＋"):
        value = "+" + value[1:]
    return int(value)

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
        path.parent.mkdir(parents=True, exist_ok=True)
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
guess_data = load_json(GUESS_FILE, {})
jackpot_data = load_json(JACKPOT_FILE, {"pool": 10000})
welcome_log_configs = load_json(WELCOME_LOG_FILE, {})
au_whitelist = set(str(user_id) for user_id in load_json(AU_WHITELIST_FILE, []))

DAILY_LOCK = asyncio.Lock()
GUESS_LOCKS = {}
AUTO_COIN_RECOVERY_DONE = False

def get_jackpot_pool():
    if "pool" not in jackpot_data:
        jackpot_data["pool"] = 10000
        save_json(JACKPOT_FILE, jackpot_data)
    return int(jackpot_data["pool"])

def add_jackpot_pool(amount):
    current = get_jackpot_pool()
    jackpot_data["pool"] = current + int(amount)
    save_json(JACKPOT_FILE, jackpot_data)
    return jackpot_data["pool"]

def reset_jackpot_pool(amount=10000):
    jackpot_data["pool"] = int(amount)
    save_json(JACKPOT_FILE, jackpot_data)

def get_balance(user_id):
    user_id = str(user_id)
    if user_id not in balances:
        balances[user_id] = STARTING_BALANCE
        save_json(BALANCES_FILE, balances)

    try:
        return int(balances[user_id])
    except (TypeError, ValueError):
        balances[user_id] = STARTING_BALANCE
        save_json(BALANCES_FILE, balances)
        return STARTING_BALANCE

def set_balance(user_id, amount):
    balances[str(user_id)] = int(amount)
    save_json(BALANCES_FILE, balances)

def get_server_settings(guild_id):
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
            current[key] = value.copy() if isinstance(value, dict) else value

    if not isinstance(current.get("weights"), dict):
        current["weights"] = DEFAULT_WEIGHTS.copy()

    for symbol in SYMBOLS:
        current["weights"].setdefault(symbol, DEFAULT_WEIGHTS[symbol])

    if current.get("emoji_mode") not in ("unicode", "custom"):
        current["emoji_mode"] = "unicode"

    save_json(SETTINGS_FILE, server_settings)
    return current

def save_server_settings(guild_id):
    if guild_id is not None:
        save_json(SETTINGS_FILE, server_settings)

# ==================================================
# 賭け金の入力処理
# ==================================================

def resolve_bet(user_id, bet_text):
    bet_text = str(bet_text).strip()
    if bet_text.casefold() == "all":
        return get_balance(user_id)

    try:
        return int(bet_text)
    except (TypeError, ValueError):
        return None

# ==================================================
# ★ ここにジャックポット判定用の関数を置く
# ==================================================

def check_jackpot(bet_amount):
    if 1 <= bet_amount <= 9:
        chance = 10000
    elif 10 <= bet_amount <= 99:
        chance = 2500
    elif 100 <= bet_amount <= 499:
        chance = 500
    elif bet_amount >= 500:
        chance = 1  # 500以上ならいくらであっても 1/250
    else:
        chance = None

    if chance is None:
        return False

    return random.randint(1, chance) == 1


# ==================================================
# 権限チェック
# ==================================================

def is_owner_user(user):
    return getattr(user, "id", None) == OWNER_USER_ID

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
    return is_owner_user(member)

def can_use_slot(member, settings):
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

async def require_owner(interaction):
    if is_owner_user(interaction.user):
        return True

    message = "このコマンドを使えるのは指定されたオーナー本人だけだよ。"

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)

    return False

# ==================================================
# 絵柄の表示処理
# ==================================================

def find_custom_emoji(guild, symbol):
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
    if symbol == "JP":
        return "<:emoji_20:1565598463154982972>"
    if settings.get("emoji_mode", "unicode") == "custom":
        custom_emoji = find_custom_emoji(guild, symbol)
        if custom_emoji is not None:
            return str(custom_emoji)
    return symbol


def grid_text(grid, guild=None, settings=None):
    if settings is None:
        settings = DEFAULT_SERVER_SETTINGS

    lines = []
    for row in grid:
        displayed_row = [
            number_emoji(symbol)
            if str(symbol).isdigit()
            else display_symbol(symbol, guild, settings)
            for symbol in row
        ]
        lines.append("|" + "|".join(displayed_row) + "|")

    return "\n".join(lines)


def get_display_mode_name(settings):
    if settings.get("emoji_mode", "unicode") == "custom":
        return "サーバーのカスタム絵文字"
    return "通常の絵文字"

def get_custom_emoji_status(guild):
    found = []
    missing = []

    for symbol in SYMBOLS:
        if symbol == "JP":
            continue
        emoji_name = CUSTOM_EMOJI_NAMES.get(symbol)
        emoji = find_custom_emoji(guild, symbol)
        if emoji:
            found.append(f"{symbol} → {emoji_name}")
        else:
            missing.append(f"{symbol} → {emoji_name}")

    return found, missing

def get_weights_text(weights):
    return "\n".join(
        f"{symbol}：{int(weights.get(symbol, 0))}"
        for symbol in SYMBOLS
    )

# ==================================================
# スロット盤面生成
# ==================================================

def weighted_symbol_order(weights):
    remaining = SYMBOLS.copy()
    result = []

    while remaining:
        available_weights = []

        for symbol in remaining:
            try:
                weight = max(0, int(weights.get(symbol, 0)))
            except (TypeError, ValueError):
                weight = 0
            available_weights.append(weight)

        if sum(available_weights) <= 0:
            chosen = random.choice(remaining)
        else:
            chosen = random.choices(
                remaining,
                weights=available_weights,
                k=1,
            )[0]

        result.append(chosen)
        remaining.remove(chosen)

    return result

def make_grid(positions, weights):
    columns = []

    for index in range(3):
        pattern = weighted_symbol_order(weights)

        try:
            position = int(positions[index]) % len(pattern)
        except (IndexError, TypeError, ValueError):
            position = 0

        rotated = pattern[position:] + pattern[:position]
        columns.append(rotated[:3])

    return [
        [columns[column][row] for column in range(3)]
        for row in range(3)
    ]

def get_paylines(grid, line_choice):
    if len(grid) < 3:
        return []
    
    paylines = []
    if line_choice >= 1:
        paylines.append([grid[1][0], grid[1][1], grid[1][2]])
        
    if line_choice >= 2:
        paylines.append([grid[0][0], grid[0][1], grid[0][2]])
        paylines.append([grid[2][0], grid[2][1], grid[2][2]])
        
    if line_choice >= 3:
        paylines.append([grid[0][0], grid[1][1], grid[2][2]])
        paylines.append([grid[2][0], grid[1][1], grid[0][2]])
        
    return paylines

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
    print(f"オーナー専用ID: {OWNER_USER_ID}")

    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンド同期: {len(synced)}個")
    except Exception:
        print("[SLASH SYNC ERROR]")
        traceback.print_exc()

    for guild_key, game in guess_data.items():
        try:
            guild = bot.get_guild(int(guild_key))
            if guild is None:
                continue

            channel = guild.get_channel(int(game.get("channel_id", 0)))
            if channel is None or not isinstance(channel, discord.TextChannel):
                continue

            await set_guess_channel_locked(
                channel,
                locked=not bool(game.get("active", False)),
            )
        except Exception:
            print("[GUESS RESTORE ERROR]")
            traceback.print_exc()

    global AUTO_COIN_RECOVERY_DONE

    if not AUTO_COIN_RECOVERY_DONE:
        AUTO_COIN_RECOVERY_DONE = True

        for guild in bot.guilds:
            try:
                result = await recover_coins_for_guild(guild)
                print(
                    f"[COIN RECOVERY] "
                    f"{guild.name}: {result}"
                )
            except Exception:
                print("[COIN RECOVERY ERROR]")
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

    # ホワイトリスト登録者は「あう」検知の対象外
    if str(message.author.id) not in au_whitelist and pattern.search(message.content):
        await message.channel.send(REPLY_TEXT)
        print("[AU DETECTED] あうを検知しました")

    # 既存機能
    await process_guess_message(message)
    await bot.process_commands(message)

@bot.event
async def on_disconnect():
    print("[BOT] Discordから切断")

@bot.event
async def on_resumed():
    print("[BOT] Discordに再接続")

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
    traceback.print_exception(type(error), error, error.__traceback__)

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
    traceback.print_exception(type(error), error, error.__traceback__)

    message = "スラッシュコマンドの実行中にエラーが発生したよ。"

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        pass

# ==================================================
# 固定ログチャンネル
# ==================================================

async def get_log_channel(guild):
    if guild is None:
        return None

    try:
        channel = bot.get_channel(LOG_CHANNEL_ID)

        if channel is None:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)

        if not isinstance(channel, discord.TextChannel):
            print("[LOG ERROR] 指定先がテキストチャンネルではありません。")
            return None

        me = channel.guild.me
        if me is None:
            print("[LOG ERROR] Botのサーバーメンバー情報を取得できません。")
            return None

        permissions = channel.permissions_for(me)

        if not permissions.view_channel or not permissions.send_messages:
            print("[LOG ERROR] ログチャンネルの閲覧または送信権限がありません。")
            return None

        return channel

    except discord.NotFound:
        print(f"[LOG ERROR] チャンネルが見つかりません: {LOG_CHANNEL_ID}")
    except discord.Forbidden:
        print("[LOG ERROR] ログチャンネルへのアクセスが拒否されました。")
    except discord.HTTPException:
        print("[LOG ERROR] ログチャンネルの取得に失敗しました。")
        traceback.print_exc()
    except Exception:
        print("[LOG ERROR] ログチャンネル取得中に予期しないエラー。")
        traceback.print_exc()

    return None

def record_slot(data):
    data.setdefault("timestamp", datetime.now(timezone.utc).timestamp())
    slot_logs.append(data)

    if len(slot_logs) > MAX_LOGS:
        del slot_logs[:-MAX_LOGS]

    save_json(SLOT_LOGS_FILE, slot_logs)

def record_coin(data):
    data.setdefault("timestamp", datetime.now(timezone.utc).timestamp())
    coin_logs.append(data)

    if len(coin_logs) > MAX_LOGS:
        del coin_logs[:-MAX_LOGS]

    save_json(COIN_LOGS_FILE, coin_logs)

# ==================================================
# 胴元システム
# ==================================================

def transfer_to_house(player_id, profit, guild_id=None, game="game"):
    player_id = int(player_id)
    profit = int(profit)

    if player_id == OWNER_USER_ID or profit == 0:
        return None

    owner_before = get_balance(OWNER_USER_ID)
    owner_change = -profit
    owner_after = owner_before + owner_change

    set_balance(OWNER_USER_ID, owner_after)

    record_coin({
        "type": "house_transfer",
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "guild_id": guild_id,
        "user_id": OWNER_USER_ID,
        "username": "owner",
        "player_id": player_id,
        "game": game,
        "player_profit": profit,
        "amount": owner_change,
        "before": owner_before,
        "after": owner_after,
    })

    print(
        f"[HOUSE] game={game} player={player_id} "
        f"player_profit={profit:+,} owner_change={owner_change:+,} "
        f"owner_balance={owner_after:,}"
    )

    return {
        "before": owner_before,
        "change": owner_change,
        "after": owner_after,
    }

async def send_slot_log(guild, embed):
    channel = await get_log_channel(guild)

    if channel is None:
        print("[SLOT LOG] メインサーバーの固定ログチャンネルを取得できず、送信できませんでした。")
        return

    try:
        if guild is not None:
            embed.add_field(
                name="プレイしたサーバー",
                value=f"{guild.name} (ID: {guild.id})",
                inline=False,
            )
        await channel.send(embed=embed)
        print(f"[SLOT LOG] メインサーバーへ送信成功: channel={channel.id}")
    except Exception:
        print("[SLOT LOG SEND ERROR]")
        traceback.print_exc()

async def send_coin_log(guild, embed):
    channel = await get_log_channel(guild)

    if channel is None:
        print("[COIN LOG] メインサーバーの固定ログチャンネルを取得できず、送信できませんでした。")
        return

    try:
        if guild is not None:
            embed.add_field(
                name="プレイしたサーバー",
                value=f"{guild.name} (ID: {guild.id})",
                inline=False,
            )
        await channel.send(embed=embed)
        print(f"[COIN LOG] メインサーバーへ送信成功: channel={channel.id}")
    except Exception:
        print("[COIN LOG SEND ERROR]")
        traceback.print_exc()

# ==================================================
# /guess 数字・言葉当てゲーム
# ==================================================

def get_guess_lock(guild_id):
    key = str(guild_id)
    if key not in GUESS_LOCKS:
        GUESS_LOCKS[key] = asyncio.Lock()
    return GUESS_LOCKS[key]

async def set_guess_channel_locked(channel, locked):
    guild = channel.guild
    me = guild.me

    if me is None:
        raise RuntimeError("Botのサーバー情報を取得できません。")

    permissions = channel.permissions_for(me)
    if not permissions.manage_channels:
        raise PermissionError("Botに「チャンネルの管理」権限が必要です。")

    overwrite = channel.overwrites_for(guild.default_role)
    overwrite.send_messages = not locked

    await channel.set_permissions(
        guild.default_role,
        overwrite=overwrite,
        reason="数字・言葉当てゲームの開催状態変更",
    )

class GuessConfigModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="数字・言葉当ての設定")
        self.parent_view = view

        if view.mode == "number":
            self.minimum_input = discord.ui.TextInput(
                label="最小値",
                placeholder="例：1",
                required=True,
                max_length=15,
            )
            self.maximum_input = discord.ui.TextInput(
                label="最大値",
                placeholder="例：100",
                required=True,
                max_length=15,
            )
            self.answer_input = discord.ui.TextInput(
                label="正解の数字",
                placeholder="範囲内の数字",
                required=True,
                max_length=15,
            )

            self.add_item(self.minimum_input)
            self.add_item(self.maximum_input)
            self.add_item(self.answer_input)
        else:
            self.answer_input = discord.ui.TextInput(
                label="正解の言葉",
                placeholder="正解となる言葉を入力",
                required=True,
                max_length=100,
            )
            self.add_item(self.answer_input)

        self.reward_input = discord.ui.TextInput(
            label="賞金（整数）",
            placeholder="例：1000",
            required=True,
            max_length=15,
        )
        self.add_item(self.reward_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "サーバー管理者だけが設定できるよ。",
                ephemeral=True,
            )
            return

        if interaction.user.id != self.parent_view.owner_id:
            await interaction.response.send_message(
                "この設定パネルを開いた管理者だけが設定できるよ。",
                ephemeral=True,
            )
            return

        try:
            reward = int(str(self.reward_input.value).strip())
            if reward < 0:
                raise ValueError

            if self.parent_view.mode == "number":
                minimum = int(str(self.minimum_input.value).strip())
                maximum = int(str(self.maximum_input.value).strip())
                answer_number = int(str(self.answer_input.value).strip())

                if minimum > maximum:
                    raise ValueError

                if not minimum <= answer_number <= maximum:
                    await interaction.response.send_message(
                        "正解の数字は最小値と最大値の範囲内にしてね。",
                        ephemeral=True,
                    )
                    return

                self.parent_view.minimum = minimum
                self.parent_view.maximum = maximum
                self.parent_view.answer = str(answer_number)
            else:
                answer = str(self.answer_input.value).strip()
                if not answer:
                    raise ValueError
                self.parent_view.answer = answer

            self.parent_view.reward = reward
            self.parent_view.configured = True

        except ValueError:
            await interaction.response.send_message(
                "入力が正しくないよ。整数や数字の範囲を確認してね。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "設定を保存したよ！\n"
            f"ゲーム：{'数字当て' if self.parent_view.mode == 'number' else '言葉当て'}\n"
            f"賞金：**{money(reward)}**\n"
            "設定パネルの「スタート」を押してね。",
            ephemeral=True,
        )

class GuessModeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="ゲームの種類を選択",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="数字当て",
                    value="number",
                    description="最小値・最大値・正解の数字を設定",
                    emoji="🔢",
                ),
                discord.SelectOption(
                    label="言葉当て",
                    value="word",
                    description="正解となる言葉を設定",
                    emoji="🔤",
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if interaction.user.id != view.owner_id or not is_admin(interaction.user):
            await interaction.response.send_message(
                "この設定を操作できるのは、パネルを開いた管理者だけだよ。",
                ephemeral=True,
            )
            return

        view.mode = self.values[0]
        view.configured = False

        await interaction.response.send_message(
            f"{'数字当て' if view.mode == 'number' else '言葉当て'}を選択したよ。\n"
            "「正解・賞金を設定」から内容を入力してね。",
            ephemeral=True,
        )

class GuessSetupView(discord.ui.View):
    def __init__(self, owner_id, channel):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.channel = channel
        self.mode = "number"
        self.minimum = None
        self.maximum = None
        self.answer = None
        self.reward = None
        self.configured = False
        self.started = False
        self.add_item(GuessModeSelect())

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id or not is_admin(interaction.user):
            await interaction.response.send_message(
                "このパネルを操作できるのは、開いた管理者だけだよ。",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="正解・賞金を設定",
        style=discord.ButtonStyle.primary,
        emoji="⚙️",
    )
    async def configure_button(self, interaction, button):
        await interaction.response.send_modal(GuessConfigModal(self))

    @discord.ui.button(
        label="スタート",
        style=discord.ButtonStyle.success,
        emoji="▶️",
    )
    async def start_button(self, interaction, button):
        if self.started:
            await interaction.response.send_message(
                "この設定パネルでは、すでに開始しているよ。",
                ephemeral=True,
            )
            return

        if not self.configured or self.answer is None or self.reward is None:
            await interaction.response.send_message(
                "先にゲーム種類を選んで、正解と賞金を設定してね。",
                ephemeral=True,
            )
            return

        guild_key = str(interaction.guild.id)
        existing = guess_data.get(guild_key, {})

        if existing.get("active", False):
            await interaction.response.send_message(
                "このサーバーでは、すでにゲームを開催中だよ。",
                ephemeral=True,
            )
            return

        try:
            await set_guess_channel_locked(self.channel, False)
        except Exception as error:
            await interaction.response.send_message(
                f"チャンネルを開けなかったよ。\n"
                f"Botの権限を確認してね。\n`{error}`",
                ephemeral=True,
            )
            return

        guess_data[guild_key] = {
            "channel_id": self.channel.id,
            "host_id": self.owner_id,
            "mode": self.mode,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "answer": self.answer,
            "reward": self.reward,
            "active": True,
            "finished": False,
            "started_at": datetime.now(timezone.utc).timestamp(),
        }
        save_json(GUESS_FILE, guess_data)

        self.started = True
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=(
                "✅ **ゲームを開始したよ！**\n"
                f"回答チャンネル：{self.channel.mention}\n"
                f"ゲーム：{'数字当て' if self.mode == 'number' else '言葉当て'}\n"
                f"賞金：**{money(self.reward)}**\n"
                "回答チャンネルで答えを送信してね。"
            ),
            view=self,
        )

        await self.channel.send(
            f"🎮 **数字・言葉当てゲーム開始！**\n"
            f"賞金：**{money(self.reward)}**\n"
            + (
                f"範囲：**{self.minimum}〜{self.maximum}**"
                if self.mode == "number"
                else "正解の言葉を当ててね！"
            )
        )

async def process_guess_message(message):
    if message.guild is None:
        return

    if message.author.bot:
        return

    guild_key = str(message.guild.id)
    game = guess_data.get(guild_key)

    if not game or not game.get("active", False):
        return

    if int(game.get("channel_id", 0)) != message.channel.id:
        return

    async with get_guess_lock(message.guild.id):
        game = guess_data.get(guild_key)

        if not game or not game.get("active", False):
            return

        content = message.content.strip()
        answer = str(game.get("answer", ""))

        if game.get("mode") == "number":
            try:
                correct = int(content) == int(answer)
            except (TypeError, ValueError):
                correct = False
        else:
            correct = content.casefold() == answer.casefold()

        if not correct:
            return

        try:
            await message.add_reaction("🎉")
        except (discord.Forbidden, discord.HTTPException):
            print("[GUESS] 正解メッセージへのリアクションに失敗しました。")

        game["active"] = False
        game["finished"] = True
        game["winner_id"] = message.author.id
        game["finished_at"] = datetime.now(timezone.utc).timestamp()
        save_json(GUESS_FILE, guess_data)

        reward = max(0, int(game.get("reward", 0)))
        before = get_balance(message.author.id)
        after = before + reward
        set_balance(message.author.id, after)

        record_coin({
            "type": "guess_reward",
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "guild_id": message.guild.id,
            "channel_id": message.channel.id,
            "user_id": message.author.id,
            "username": str(message.author),
            "mode": game.get("mode"),
            "answer": answer,
            "amount": reward,
            "before": before,
            "after": after,
        })

        try:
            await set_guess_channel_locked(message.channel, True)
        except Exception:
            print("[GUESS] 正解後のチャンネルロックに失敗しました。")
            traceback.print_exc()

        await message.channel.send(
            f"🎉 **正解！**\n"
            f"正解者：{message.author.mention}\n"
            f"賞金：**{money_change(reward)}**\n"
            f"現在の残高：**{money(after)}**"
        )

        log_embed = discord.Embed(
            title="🎉 数字・言葉当てゲーム報酬ログ",
            description=(
                f"正解者：{message.author.mention} (`{message.author.id}`)\n"
                f"回答チャンネル：{message.channel.mention}\n"
                f"ゲーム種類：{'数字当て' if game.get('mode') == 'number' else '言葉当て'}\n"
                f"正解：`{answer}`\n"
                f"賞金：**{money_change(reward)}**\n"
                f"変更前：**{money(before)}**\n"
                f"変更後：**{money(after)}**"
            ),
            color=discord.Color.green(),
        )
        await send_coin_log(message.guild, log_embed)

guess_group = app_commands.Group(
    name="guess",
    description="数字・言葉当てゲームを管理する",
)

@guess_group.command(
    name="setup",
    description="数字・言葉当てゲームの設定パネルを開く",
)
async def guess_setup_command(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            "サーバーのテキストチャンネルで使ってね。",
            ephemeral=True,
        )
        return

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "サーバー管理者だけがゲームを設定できるよ。",
            ephemeral=True,
        )
        return

    guild_key = str(interaction.guild.id)
    current = guess_data.get(guild_key, {})

    if current.get("active", False):
        await interaction.response.send_message(
            "このサーバーでは、すでにゲームを開催中だよ。",
            ephemeral=True,
        )
        return

    channel = interaction.channel

    try:
        await set_guess_channel_locked(channel, True)
    except Exception as error:
        await interaction.response.send_message(
            f"回答チャンネルをロックできなかったよ。\n"
            f"Botの権限を確認してね。\n`{error}`",
            ephemeral=True,
        )
        return

    guess_data[guild_key] = {
        "channel_id": channel.id,
        "host_id": interaction.user.id,
        "active": False,
        "finished": False,
    }
    save_json(GUESS_FILE, guess_data)

    view = GuessSetupView(interaction.user.id, channel)

    await interaction.response.send_message(
        f"🎮 **数字・言葉当てゲーム設定**\n"
        f"回答チャンネル：{channel.mention}\n"
        "ゲーム種類を選び、「正解・賞金を設定」を押してね。\n"
        "設定後に「スタート」を押すと回答受付が始まるよ。\n\n"
        "※設定中は回答チャンネルをロックしているよ。",
        view=view,
        ephemeral=True,
    )

@guess_group.command(
    name="stop",
    description="開催中または設定中の数字・言葉当てゲームを停止する",
)
async def guess_stop_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "サーバー内で使ってね。",
            ephemeral=True,
        )
        return

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "サーバー管理者だけが停止できるよ。",
            ephemeral=True,
        )
        return

    game = guess_data.get(str(interaction.guild.id))

    if not game:
        await interaction.response.send_message(
            "停止できるゲーム設定がないよ。",
            ephemeral=True,
        )
        return

    channel = interaction.guild.get_channel(int(game.get("channel_id", 0)))

    game["active"] = False
    game["finished"] = True
    save_json(GUESS_FILE, guess_data)

    if channel is not None:
        try:
            await set_guess_channel_locked(channel, True)
        except Exception as error:
            await interaction.response.send_message(
                "ゲームは停止したけど、チャンネルをロックできなかったよ。\n"
                f"Botの権限を確認してね。\n`{error}`",
                ephemeral=True,
            )
            return

        try:
            await channel.send(
                f"🛑 管理者 {interaction.user.mention} がゲームを停止したよ。"
            )
        except discord.HTTPException:
            pass

    await interaction.response.send_message(
        "ゲームを停止したよ。回答チャンネルをロックしたよ。",
        ephemeral=True,
    )

bot.tree.add_command(guess_group)

# ==================================================
# .daily ログインボーナス
# ==================================================

@bot.command(name="daily")
async def daily_command(ctx):
    if ctx.author.bot:
        return

    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。", mention_author=False)
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

        if last_date_text == today_text:
            already_received = True
            reward = 0
        else:
            already_received = False
            yesterday_text = (today - timedelta(days=1)).isoformat()
            streak = streak + 1 if last_date_text == yesterday_text else 1
            reward = DAILY_REWARD + streak * DAILY_STREAK_BONUS

            current_balance = get_balance(ctx.author.id)
            new_balance = current_balance + reward
            set_balance(ctx.author.id, new_balance)

            daily_data[user_id] = {
                "last_date": today_text,
                "streak": streak,
                "last_reward": reward,
                "last_balance": new_balance,
            }
            save_json(DAILY_FILE, daily_data)

            record_coin({
                "type": "daily",
                "timestamp": datetime.now(timezone.utc).timestamp(),
                "guild_id": ctx.guild.id,
                "user_id": ctx.author.id,
                "username": str(ctx.author),
                "amount": reward,
                "streak": streak,
                "balance": new_balance,
                "date": today_text,
            })

    if already_received:
        await ctx.reply("今日はもうログインボーナスを受け取っているよ。", mention_author=False)
        return

    await ctx.reply(
        f"{streak}日目\n増やした金額：{money_change(reward)}",
        mention_author=False,
    )

    channel = await get_log_channel(ctx.guild)
    if channel is not None:
        try:
            # 埋め込み（Embed）を作成
            embed = discord.Embed(
                title="🎁 ログインボーナスログ",
                description=(
                    f"やった人：{ctx.author.mention} (`{ctx.author.id}`)\n"
                    f"増やした金額：**{money_change(reward)}**\n"
                    f"何日目か：**{streak}日目**\n"
                    f"現在の残高：**{money(new_balance)}**"
                ),
                color=discord.Color.green(),
            )
            # embed引数で送信
            await channel.send(embed=embed)
        except Exception:
            print("[DAILY LOG SEND ERROR]")
            traceback.print_exc()

# ==================================================
# .jackpot ジャックポット確認コマンド
# ==================================================

@bot.command(name="jackpot", aliases=["jp", "ジャックポット"])
async def jackpot_command(ctx):
    pool = get_jackpot_pool()
    embed = discord.Embed(
        title="🎰 JACKPOT POOL 🎰",
        description=f"現在のジャックポット積立金:\n**💰 {money(pool)}**\n\n*(スロットを回すたび賭け金の10%が蓄積され、<:emoji_20:1565598463154982972> が揃うと総取りできるよ！)*",
        color=discord.Color.gold(),
    )
    await ctx.reply(embed=embed, mention_author=False)

# ==================================================
# .color 2択ゲーム
# ==================================================

class ColorBetView(discord.ui.View):
    def __init__(self, ctx, bet):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.bet = bet
        self.finished = False
        self.message = None

    async def choose_color(self, interaction, chosen_color):
        if self.finished:
            await interaction.response.send_message("このゲームはもう終了しているよ。", ephemeral=True)
            return

        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("このゲームを操作できるのは賭けた本人だけだよ。", ephemeral=True)
            return

        self.finished = True
        winning_color = random.choice(["🌝", "🌚"])
        won = chosen_color == winning_color
        current_balance = get_balance(interaction.user.id)

        if won:
            payout = self.bet * 2
            new_balance = current_balance + payout
            profit = self.bet
            result_text = f"🎉 **当たり！**\n正解：{winning_color}\n配当：{money_change(payout)}"
            color = discord.Color.green()
        else:
            payout = 0
            new_balance = current_balance
            profit = -self.bet
            result_text = f"💸 **ハズレ！**\n正解：{winning_color}\n損失：{money_change(-self.bet)}"
            color = discord.Color.red()

        set_balance(interaction.user.id, new_balance)

        house_result = transfer_to_house(
            interaction.user.id,
            profit,
            interaction.guild.id if interaction.guild else None,
            "color",
        )

        for item in self.children:
            item.disabled = True

        house_text = ""
        if house_result is not None:
            house_text = (
                f"\n胴元の残高変動：{money_change(house_result['change'])}"
                f"\n胴元の残高：{money(house_result['after'])}"
            )

        embed = discord.Embed(
            title="🌝🌚 2択ゲーム",
            description=(
                f"プレイヤー：{interaction.user.mention}\n"
                f"選んだ色：{chosen_color}\n\n{result_text}\n\n"
                f"賭け金：{money(self.bet)}\n収支：{money_change(profit)}\n"
                f"残高：{money(new_balance)}{house_text}"
            ),
            color=color,
        )

        await interaction.response.edit_message(embed=embed, view=self)

        record_coin({
            "type": "color",
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "guild_id": interaction.guild.id if interaction.guild else None,
            "user_id": interaction.user.id,
            "username": str(interaction.user),
            "bet": self.bet,
            "chosen_color": chosen_color,
            "winning_color": winning_color,
            "won": won,
            "payout": payout,
            "amount": profit,
            "profit": profit,
            "balance": new_balance,
        })

        if interaction.guild is not None:
            description = (
                f"ユーザー：{interaction.user.mention} (`{interaction.user.id}`)\n"
                f"選択：{chosen_color}\n正解：{winning_color}\n"
                f"結果：{'当たり' if won else 'ハズレ'}\n"
                f"賭け金：**{money(self.bet)}**\n配当：**{money(payout)}**\n"
                f"収支：**{money_change(profit)}**\n残高：**{money(new_balance)}**"
            )

            if house_result is not None:
                description += (
                    f"\n胴元の変動：**{money_change(house_result['change'])}**"
                    f"\n胴元の残高：**{money(house_result['after'])}**"
                )

            await send_coin_log(
                interaction.guild,
                discord.Embed(
                    title="🌝🌚 2択ゲームログ",
                    description=description,
                    color=color,
                ),
            )

    @discord.ui.button(label="表", emoji="🌝", style=discord.ButtonStyle.danger)
    async def red_button(self, interaction, button):
        await self.choose_color(interaction, "🌝")

    @discord.ui.button(label="裏", emoji="🌚", style=discord.ButtonStyle.primary)
    async def blue_button(self, interaction, button):
        await self.choose_color(interaction, "🌚")

    async def on_timeout(self):
        if self.finished:
            return

        self.finished = True
        current_balance = get_balance(self.ctx.author.id)
        refunded_balance = current_balance + self.bet
        set_balance(self.ctx.author.id, refunded_balance)

        for item in self.children:
            item.disabled = True

        embed = discord.Embed(
            title="🌝🌚 2択ゲーム",
            description=(
                f"プレイヤー：{self.ctx.author.mention}\n\n"
                "時間切れ！今回はゲームをキャンセルしたよ。\n"
                f"賭け金 **{money(self.bet)}** を返したよ。\n"
                f"残高：**{money(refunded_balance)}**"
            ),
            color=discord.Color.gold(),
        )

        if self.message is not None:
            try:
                await self.message.edit(embed=embed, view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

        record_coin({
            "type": "color_refund",
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "guild_id": self.ctx.guild.id if self.ctx.guild else None,
            "user_id": self.ctx.author.id,
            "username": str(self.ctx.author),
            "bet": self.bet,
            "amount": self.bet,
            "balance": refunded_balance,
        })

        if self.ctx.guild is not None:
            await send_coin_log(
                self.ctx.guild,
                discord.Embed(
                    title="🌝🌚 2択ゲーム返金ログ",
                    description=(
                        f"ユーザー：{self.ctx.author.mention} (`{self.ctx.author.id}`)\n"
                        "理由：選択時間切れ\n"
                        f"返金額：**{money(self.bet)}**\n"
                        f"残高：**{money(refunded_balance)}**"
                    ),
                    color=discord.Color.gold(),
                ),
            )

@bot.command(name="color", aliases=["色当て", "redblue"])
async def color_command(ctx, bet_text: str):
    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。", mention_author=False)
        return

    bet = resolve_bet(ctx.author.id, bet_text)
    if bet is None:
        await ctx.reply("賭け金は数字か `all` で指定してね。\n例：`.color 500` / `.color all`", mention_author=False)
        return

    if bet <= 0:
        await ctx.reply("賭け金に使える残高がないよ。", mention_author=False)
        return

    settings = get_server_settings(ctx.guild.id)
    bet_limits = settings.get("bet_limits", {})
    color_limit = bet_limits.get("color", {"min": 0, "max": "inf"})
    
    min_bet = color_limit.get("min", 0)
    max_bet = color_limit.get("max", "inf")

    if bet < min_bet:
        max_str = "無制限" if max_bet == "inf" else money(max_bet)
        await ctx.reply(f"カラーの最低賭け金は **{money(min_bet)}** だよ。", mention_author=False)
        return

    if max_bet != "inf" and bet > max_bet:
        await ctx.reply(f"カラーの最高賭け金は **{money(max_bet)}** までだよ。", mention_author=False)
        return

    current_balance = get_balance(ctx.author.id)
    if bet > current_balance:
        await ctx.reply(f"残高が足りないよ！\n残高：{money(current_balance)}", mention_author=False)
        return

    set_balance(ctx.author.id, current_balance - bet)

    embed = discord.Embed(
        title="🌝🌚 2択ゲーム",
        description=(
            f"プレイヤー：{ctx.author.mention}\n賭け金：**{money(bet)}**\n\n"
            "🌝 表か 🌚 裏を選んでね！\n"
            "当たりなら賭け金込みで2倍が戻るよ。\n"
            "ハズレなら賭け金を失うよ。\n\n"
            "60秒以内に選んでね。時間切れは返金されるよ。"
        ),
        color=discord.Color.blurple(),
    )

    view = ColorBetView(ctx, bet)

    try:
        message = await ctx.reply(embed=embed, view=view, mention_author=False)
        view.message = message
    except Exception:
        current_balance = get_balance(ctx.author.id)
        set_balance(ctx.author.id, current_balance + bet)
        raise

# ==================================================
# .dice 4個のサイコロゲーム
# ==================================================

DICE_COLORS = {
    "r": {"name": "赤", "emoji": "🔴", "custom": "aka"},
    "b": {"name": "青", "emoji": "🔵", "custom": "ao"},
    "y": {"name": "黄色", "emoji": "🟡", "custom": "kiro"},
    "o": {"name": "オレンジ", "emoji": "🟠", "custom": "orengi"},
    "g": {"name": "緑", "emoji": "🟢", "custom": "midori"},
    "p": {"name": "紫", "emoji": "🟣", "custom": "murasaki"},
}

def get_dice_emoji(guild, color_key):
    color = DICE_COLORS[color_key]
    if guild is not None:
        for emoji in guild.emojis:
            if emoji.name == color["custom"]:
                return str(emoji)
    return color["emoji"]

class DiceColorSelect(discord.ui.Select):
    def __init__(self, game_view):
        self.game_view = game_view
        options = [
            discord.SelectOption(
                label=data["name"],
                value=key,
                emoji=data["emoji"],
            )
            for key, data in DICE_COLORS.items()
        ]
        super().__init__(
            placeholder="再抽選する色を選ね",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.game_view

        if interaction.user.id != view.player_id:
            await interaction.response.send_message(
                "このゲームを操作できるのは賭けた本人だけだよ。",
                ephemeral=True,
            )
            return

        if view.finished:
            await interaction.response.send_message(
                "このゲームはもう終了しているよ。",
                ephemeral=True,
            )
            return

        await view.roll_again(interaction, self.values[0])

class DiceBetView(discord.ui.View):
    def __init__(self, ctx, bet, first_color):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.bet = bet
        self.player_id = ctx.author.id
        self.guild = ctx.guild
        self.first_color = first_color
        self.finished = False
        self.reroll_used = False
        self.message = None

    def roll_dice(self):
        return [
            random.choice(list(DICE_COLORS.keys()))
            for _ in range(4)
        ]

    def format_dice(self, dice):
        return " ".join(
            get_dice_emoji(self.guild, color)
            for color in dice
        )

    async def finish_game(self, interaction, dice, chosen_color, count, result):
        if self.finished:
            return

        self.finished = True
        self.stop()

        current_balance = get_balance(self.player_id)

        if result == "lose":
            payout = 0
            profit = -self.bet
            new_balance = current_balance
            result_text = (
                "💸 **負け！**\n"
                f"選んだ色：{DICE_COLORS[chosen_color]['name']}\n"
                f"一致した数：{count}個\n"
                f"損失：**{money(self.bet)}**"
            )
            embed_color = discord.Color.red()

        elif result == "double":
            payout = self.bet * 2
            profit = payout - self.bet
            new_balance = current_balance + payout
            result_text = (
                "🎉 **当たり！**\n"
                f"選んだ色：{DICE_COLORS[chosen_color]['name']}\n"
                f"一致した数：{count}個\n"
                f"配当：**{money(payout)}**"
            )
            embed_color = discord.Color.green()

        else:
            payout = self.bet * 3
            profit = payout - self.bet
            new_balance = current_balance + payout
            result_text = (
                "🎉 **大当たり！**\n"
                f"選んだ色：{DICE_COLORS[chosen_color]['name']}\n"
                f"一致した数：{count}個\n"
                f"配当：**{money(payout)}**"
            )
            embed_color = discord.Color.green()

        set_balance(self.player_id, new_balance)

        house_result = transfer_to_house(
            player_id=self.player_id,
            profit=profit,
            guild_id=self.guild.id if self.guild else None,
            game="dice",
        )

        for item in self.children:
            item.disabled = True

        house_text = ""
        if house_result is not None:
            house_text = (
                f"\n胴元の残高変動：**{money_change(house_result['change'])}**"
                f"\n胴元の残高：**{money(house_result['after'])}**"
            )

        embed = discord.Embed(
            title="🎲 4個のサイコロ",
            description=(
                f"プレイヤー：{self.ctx.author.mention}\n"
                f"賭け金：**{money(self.bet)}**\n\n"
                f"{self.format_dice(dice)}\n\n"
                f"{result_text}\n\n"
                f"収支：**{money_change(profit)}**\n"
                f"残高：**{money(new_balance)}**"
                f"{house_text}"
            ),
            color=embed_color,
        )

        await interaction.response.edit_message(embed=embed, view=self)

        record_coin({
            "type": "dice",
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "guild_id": self.guild.id if self.guild else None,
            "user_id": self.player_id,
            "username": str(self.ctx.author),
            "bet": self.bet,
            "first_color": self.first_color,
            "chosen_color": chosen_color,
            "dice": dice,
            "match_count": count,
            "reroll_used": self.reroll_used,
            "payout": payout,
            "profit": profit,
            "amount": profit,
            "balance": new_balance,
        })

        if self.guild is not None:
            log_description = (
                f"ユーザー：{self.ctx.author.mention} (`{self.player_id}`)\n"
                f"賭け金：**{money(self.bet)}**\n"
                f"選択色：{DICE_COLORS[chosen_color]['name']}\n"
                f"出目：{self.format_dice(dice)}\n"
                f"一致数：{count}個\n"
                f"再抽選：{'あり' if self.reroll_used else 'なし'}\n"
                f"配当：**{money(payout)}**\n"
                f"収支：**{money_change(profit)}**\n"
                f"残高：**{money(new_balance)}**"
            )

            if house_result is not None:
                log_description += (
                    f"\n胴元の残高変動：**{money_change(house_result['change'])}**"
                    f"\n胴元の残高：**{money(house_result['after'])}**"
                )

            await send_coin_log(
                self.guild,
                discord.Embed(
                    title="🎲 サイコロゲームログ",
                    description=log_description,
                    color=embed_color,
                ),
            )

    async def roll_again(self, interaction, chosen_color):
        if self.finished:
            await interaction.response.send_message(
                "このゲームはもう終了しているよ。",
                ephemeral=True,
            )
            return

        if self.reroll_used:
            await interaction.response.send_message(
                "再抽選は1回までだよ。",
                ephemeral=True,
            )
            return

        self.reroll_used = True
        dice = self.roll_dice()
        count = dice.count(chosen_color)

        if count == 0:
            result = "lose"
        elif count == 1:
            result = "double"
        elif count == 4:
            result = "triple"
        else:
            result = "lose"

        await self.finish_game(
            interaction,
            dice,
            chosen_color,
            count,
            result,
        )

    async def on_timeout(self):
        if self.finished:
            return

        self.finished = True
        self.stop()

        for item in self.children:
            item.disabled = True

        if self.message is not None:
            try:
                await self.message.edit(
                    content="⏰ 時間切れ！ゲームは終了したよ。賭け金は返金されないよ。",
                    embed=None,
                    view=self,
                )
            except (discord.NotFound, discord.HTTPException):
                pass

@bot.command(name="mdice", aliases=["ダイス", "サイコロ"])
async def dice_command(ctx, bet_text: str, color_text: str):
    if ctx.guild is None:
        await ctx.reply(
            "このコマンドはサーバー内で使ってね。",
            mention_author=False,
        )
        return

    color_key = color_text.strip().lower()

    if color_key not in DICE_COLORS:
        await ctx.reply(
            "色の指定が違うよ！\n"
            "`r` 赤 / `b` 青 / `y` 黄色 / "
            "`o` オレンジ / `g` 緑 / `p` 紫\n"
            "例：`.dice 100 r`",
            mention_author=False,
        )
        return

    bet = resolve_bet(ctx.author.id, bet_text)

    if bet is None:
        await ctx.reply(
            "賭け金は数字か `all` で指定してね。\n"
            "例：`.dice 100 r` / `.dice all b`",
            mention_author=False,
        )
        return

    if bet <= 0:
        await ctx.reply(
            "賭け金に使える残高がないよ。",
            mention_author=False,
        )
        return

    settings = get_server_settings(ctx.guild.id)
    minimum = int(settings.get("min_bet", 1))

    if bet < minimum:
        await ctx.reply(
            f"最低賭け金は **{money(minimum)}** だよ。",
            mention_author=False,
        )
        return

    current_balance = get_balance(ctx.author.id)

    if bet > current_balance:
        await ctx.reply(
            f"残高が足りないよ！\n残高：**{money(current_balance)}**",
            mention_author=False,
        )
        return

    set_balance(ctx.author.id, current_balance - bet)

    view = DiceBetView(ctx, bet, color_key)
    dice = view.roll_dice()
    count = dice.count(color_key)

    if count == 0:
        result = "lose"
    elif count == 1:
        result = "double"
    elif count == 4:
        result = "triple"
    else:
        result = None

    if result is not None:
        embed = discord.Embed(
            title="🎲 4個のサイコロ",
            description=(
                f"プレイヤー：{ctx.author.mention}\n"
                f"賭け金：**{money(bet)}**\n\n"
                f"{view.format_dice(dice)}\n\n"
                f"選んだ色：{DICE_COLORS[color_key]['name']}\n"
                f"一致した数：{count}個"
            ),
            color=discord.Color.blurple(),
        )

        message = await ctx.reply(
            embed=embed,
            mention_author=False,
        )
        view.message = message

        if result == "lose":
            payout = 0
            profit = -bet
            new_balance = current_balance - bet
            result_text = "💸 **負け！賭け金を失ったよ。**"
            embed_color = discord.Color.red()
        elif result == "double":
            payout = bet * 2
            profit = payout - bet
            new_balance = current_balance - bet + payout
            result_text = f"🎉 **当たり！賭け金の2倍、{money(payout)}を付与！**"
            embed_color = discord.Color.green()
        else:
            payout = bet * 3
            profit = payout - bet
            new_balance = current_balance - bet + payout
            result_text = f"🎉 **大当たり！賭け金の3倍、{money(payout)}を付与！**"
            embed_color = discord.Color.green()

        set_balance(ctx.author.id, new_balance)

        house_result = transfer_to_house(
            player_id=ctx.author.id,
            profit=profit,
            guild_id=ctx.guild.id,
            game="dice",
        )

        house_text = ""
        if house_result is not None:
            house_text = (
                f"\n胴元の残高変動：**{money_change(house_result['change'])}**"
                f"\n胴元の残高：**{money(house_result['after'])}**"
            )

        final_embed = discord.Embed(
            title="🎲 4個のサイコロ",
            description=(
                f"プレイヤー：{ctx.author.mention}\n"
                f"賭け金：**{money(bet)}**\n\n"
                f"{view.format_dice(dice)}\n\n"
                f"{result_text}\n"
                f"選んだ色：{DICE_COLORS[color_key]['name']}\n"
                f"一致した数：{count}個\n"
                f"収支：**{money_change(profit)}**\n"
                f"残高：**{money(new_balance)}**"
                f"{house_text}"
            ),
            color=embed_color,
        )

        await message.edit(embed=final_embed)

        record_coin({
            "type": "dice",
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "guild_id": ctx.guild.id,
            "user_id": ctx.author.id,
            "username": str(ctx.author),
            "bet": bet,
            "first_color": color_key,
            "chosen_color": color_key,
            "dice": dice,
            "match_count": count,
            "reroll_used": False,
            "payout": payout,
            "profit": profit,
            "amount": profit,
            "balance": new_balance,
        })

        if ctx.guild is not None:
            log_description = (
                f"ユーザー：{ctx.author.mention} (`{ctx.author.id}`)\n"
                f"賭け金：**{money(bet)}**\n"
                f"選択色：{DICE_COLORS[color_key]['name']}\n"
                f"出目：{view.format_dice(dice)}\n"
                f"一致数：{count}個\n"
                f"配当：**{money(payout)}**\n"
                f"収支：**{money_change(profit)}**\n"
                f"残高：**{money(new_balance)}**"
            )

            if house_result is not None:
                log_description += (
                    f"\n胴元の残高変動：**{money_change(house_result['change'])}**"
                    f"\n胴元の残高：**{money(house_result['after'])}**"
                )

            await send_coin_log(
                ctx.guild,
                discord.Embed(
                    title="🎲 サイコロゲームログ",
                    description=log_description,
                    color=embed_color,
                ),
            )

        return

    view.add_item(DiceColorSelect(view))

    embed = discord.Embed(
        title="🎲 4個のサイコロ",
        description=(
            f"プレイヤー：{ctx.author.mention}\n"
            f"賭け金：**{money(bet)}**\n\n"
            f"{view.format_dice(dice)}\n\n"
            f"最初に選んだ色：{DICE_COLORS[color_key]['name']}\n"
            f"一致した数：{count}個\n\n"
            "🔄 **再抽選！**\n"
            "次に狙う色を選んでね。\n"
            "追加の賭け金は必要ないよ。\n"
            "再抽選でも2〜3個なら負けになるよ。"
        ),
        color=discord.Color.gold(),
    )

    try:
        message = await ctx.reply(
            embed=embed,
            view=view,
            mention_author=False,
        )
        view.message = message
    except Exception:
        latest_balance = get_balance(ctx.author.id)
        set_balance(ctx.author.id, latest_balance + bet)
        raise

# ==================================================
# .mine 爆弾ゲーム
# ==================================================

active_mine_users = set()


async def send_mine_log(guild, embed):
    # MINESのログは、ゲームを遊んだサーバーに関係なく
    # LOG_CHANNEL_IDで指定したメインサーバーのチャンネルへ送信する。
    try:
        if guild is not None:
            embed.add_field(
                name="プレイしたサーバー",
                value=f"{guild.name} (ID: {guild.id})",
                inline=False,
            )

        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)

        if not isinstance(channel, discord.TextChannel):
            print("[MINE LOG ERROR] 固定ログ送信先がテキストチャンネルではありません。")
            return

        me = channel.guild.me
        if me is None:
            print("[MINE LOG ERROR] メインサーバーのBotメンバー情報を取得できません。")
            return

        permissions = channel.permissions_for(me)
        if not permissions.view_channel or not permissions.send_messages:
            print("[MINE LOG ERROR] メインサーバーのログチャンネルへの閲覧・送信権限がありません。")
            return

        await channel.send(embed=embed)
        print(f"[MINE LOG] メインサーバーへ送信成功: channel={channel.id}")
    except discord.NotFound:
        print(f"[MINE LOG ERROR] メインサーバーのログチャンネルが見つかりません: {LOG_CHANNEL_ID}")
    except discord.Forbidden:
        print("[MINE LOG ERROR] メインサーバーのログチャンネルへのアクセスが拒否されました。")
    except discord.HTTPException:
        print("[MINE LOG ERROR] ログ送信中にDiscord APIエラーが発生しました。")
        traceback.print_exc()
    except Exception:
        print("[MINE LOG ERROR] ログ送信中に予期しないエラーが発生しました。")
        traceback.print_exc()


class MineCashoutView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game
        button = discord.ui.Button(
            label="💰 精算",
            style=discord.ButtonStyle.success,
            disabled=True,
            custom_id=f"minecashout:{game.player_id}",
        )
        button.callback = self.cashout_callback
        self.add_item(button)
        self.button = button

    async def cashout_callback(self, interaction):
        await self.game.cashout(interaction)


class MineGameView(discord.ui.View):
    def __init__(self, ctx, bet, size, bomb_count):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.player_id = ctx.author.id
        self.guild = ctx.guild
        self.bet = bet
        self.size = size
        self.total_cells = size * size
        self.bomb_count = bomb_count
        self.safe_total = self.total_cells - bomb_count
        self.bombs = set(random.sample(range(self.total_cells), bomb_count))
        self.opened_safe = set()
        self.cell_symbols = {}
        self.multiplier_adjustment = 0.0
        self.finished = False
        self.message = None
        self.cashout_message = None
        self.multiplier = 1.0
        self.cashout_view = None
        self.inline_cashout_button = None
        self.cell_buttons = {}
        self.cell_select = None
        button_cell_limit = self.total_cells

        for index in range(button_cell_limit):
            button = discord.ui.Button(
                label="？",
                style=discord.ButtonStyle.secondary,
                row=index // size,
                custom_id=f"mine:{self.player_id}:{index}",
            )

            async def cell_callback(interaction, cell_index=index):
                await self.open_cell(interaction, cell_index)

            button.callback = cell_callback
            self.add_item(button)
            self.cell_buttons[index] = button

        if size != 5:
            cashout_button = discord.ui.Button(
                label="Cash Out",
                emoji="💵",
                style=discord.ButtonStyle.success,
                disabled=True,
                row=size,
                custom_id=f"minecashout_inline:{self.player_id}",
            )
            cashout_button.callback = self.inline_cashout_callback
            self.add_item(cashout_button)
            self.inline_cashout_button = cashout_button

    async def inline_cashout_callback(self, interaction):
        await self.cashout(interaction)

    def base_multiplier(self, opened):
        if opened <= 0:
            return 1.0
        denominator = math.comb(self.total_cells, opened)
        numerator = math.comb(self.safe_total, opened)
        return round(0.85 * denominator / numerator, 2)

    def current_multiplier(self):
        opened = len(self.opened_safe)
        return max(0.01, round(self.base_multiplier(opened) + self.multiplier_adjustment, 2))

    def next_multiplier(self):
        opened = len(self.opened_safe) + 1
        if opened > self.safe_total:
            return self.multiplier
        return max(0.01, round(self.base_multiplier(opened) + self.multiplier_adjustment, 2))

    def make_embed(self, status="playing", result_text=None):
        if status == "playing":
            color = discord.Color.blurple()
            title = "💣 MINES"
            description = "マスを選んでね！爆弾を引くと賭け金を失うよ。"
        elif status == "win":
            color = discord.Color.green()
            title = "🎉 MINES — CLEAR!"
            description = result_text or "ゲームクリア！"
        elif status == "lose":
            color = discord.Color.red()
            title = "💥 MINES — BOOM!"
            description = result_text or "爆弾を引いてしまったよ。"
        else:
            color = discord.Color.orange()
            title = "⏰ MINES — TIME UP"
            description = result_text or "時間切れでゲーム終了。賭け金は返金したよ。"

        embed = discord.Embed(title=title, description=description, color=color)
        embed.description = (
            f"💣 {self.ctx.author.mention} started a mines game.\n\n"
            f"**Bet:** `{self.bet:,}`　 **Mines:** `{self.bomb_count}`\n"
            f"**Cash Out:** `{int(self.bet * self.multiplier) if self.opened_safe else 0}` `({self.multiplier if self.opened_safe else 0:.3f}x)`\n"
            f"**Next:** `{int(self.bet * self.next_multiplier())}` `({self.next_multiplier():.3f}x)`"
            if status == "playing" else description
        )
        # 終了画面はスマホでも縦に長くならないよう、情報を短い行にまとめる。
        if status != "playing":
            embed.description = (
                f"{description}\n\n"
                f"👤 {self.ctx.author.mention}　💵 **{money(self.bet)}**\n"
                f"🧩 **{self.size}×{self.size}**　💣 **{self.bomb_count}個**　"
                f"💎 **{len(self.opened_safe)}/{self.safe_total}**\n"
                f"📈 **{self.multiplier:.2f}倍**　"
                f"💵 **{sum(1 for v in self.cell_symbols.values() if v == '💵')}** "
                f"💍 **{sum(1 for v in self.cell_symbols.values() if v == '💍')}** "
                f"💎 **{sum(1 for v in self.cell_symbols.values() if v == '💎')}**"
            )
        return embed

    def reveal_board(self, exploded_index=None):
        for index, item in self.cell_buttons.items():
            item.disabled = True
            if index == exploded_index:
                item.label = "💥"
                item.style = discord.ButtonStyle.danger
            elif index in self.bombs:
                item.label = "💣"
                item.style = discord.ButtonStyle.danger
            elif index in self.opened_safe:
                item.label = self.cell_symbols.get(index, "💵")
                item.style = discord.ButtonStyle.success
            else:
                item.label = "・"
                item.style = discord.ButtonStyle.secondary

        if self.cell_select:
            options = []
            for option in self.cell_select.options:
                index = int(option.value)
                row_col = f"{index // self.size + 1}行{index % self.size + 1}列"
                if index == exploded_index:
                    label, emoji = f"💥 {row_col}", "💥"
                elif index in self.bombs:
                    label, emoji = f"💣 {row_col}", "💣"
                elif index in self.opened_safe:
                    symbol = self.cell_symbols.get(index, "💵")
                    label, emoji = f"{symbol} {row_col}", symbol
                else:
                    label, emoji = f"・ {row_col}", "▫️"
                options.append(discord.SelectOption(label=label, value=str(index), emoji=emoji))
            self.cell_select.options = options
            self.cell_select.disabled = True
            self.cell_select.placeholder = "ゲーム終了"
    async def open_cell(self, interaction, index):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("このゲームを操作できるのは賭けた本人だけだよ。", ephemeral=True)
            return
        if self.finished:
            await interaction.response.send_message("このゲームはもう終了しているよ。", ephemeral=True)
            return
        if index in self.opened_safe:
            await interaction.response.send_message("そのマスはもう開いているよ。", ephemeral=True)
            return

        if index in self.bombs:
            await interaction.response.defer()
            await self.finish_game(
                "lose",
                "💥 爆弾を引いたため賭け金を失ったよ。",
                exploded_index=index,
            )
            return

        # 安全マスを開いたときの出目。💵=変化なし、💍=±0.05倍、💎=+0.1倍
        symbol = random.choice(["💵", "💍", "💎"])
        adjustment = 0.0
        if symbol == "💍":
            adjustment = random.choice([-0.05, 0.05])
        elif symbol == "💎":
            adjustment = 0.1

        self.opened_safe.add(index)
        self.cell_symbols[index] = symbol
        self.multiplier_adjustment = round(self.multiplier_adjustment + adjustment, 2)
        self.multiplier = self.current_multiplier()

        if index in self.cell_buttons:
            button = self.cell_buttons[index]
            button.label = symbol
            button.style = discord.ButtonStyle.success
            button.disabled = True
        if self.cell_select:
            options = []
            for option in self.cell_select.options:
                cell_index = int(option.value)
                if cell_index == index:
                    opened_symbol = self.cell_symbols.get(cell_index, "💵")
                    options.append(discord.SelectOption(
                        label=f"{opened_symbol} {cell_index // self.size + 1}行{cell_index % self.size + 1}列",
                        value=str(cell_index),
                        emoji=opened_symbol,
                    ))
                else:
                    options.append(option)
            self.cell_select.options = options

        if self.inline_cashout_button:
            self.inline_cashout_button.disabled = False
        if self.cashout_view:
            self.cashout_view.button.disabled = False
            if self.cashout_message:
                try:
                    await self.cashout_message.edit(view=self.cashout_view)
                except discord.HTTPException:
                    pass

        if len(self.opened_safe) >= self.safe_total:
            await interaction.response.defer()
            await self.finish_game("win", "🏆 すべての安全マスを開いたよ！")
            return

        payout = int(self.bet * self.multiplier)
        embed = self.make_embed()
        symbol_change = f"{adjustment:+.1f}" if adjustment else "±0.0"
        embed.add_field(
            name="今回の出目",
            value=f"{symbol}（倍率 {symbol_change}倍）",
            inline=True,
        )
        embed.add_field(name="現在の精算額", value=money(payout), inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    async def cashout(self, interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("このゲームを操作できるのは賭けた本人だけだよ。", ephemeral=True)
            return
        if self.finished:
            await interaction.response.send_message("このゲームはもう終了しているよ。", ephemeral=True)
            return
        if not self.opened_safe:
            await interaction.response.send_message("まず安全マスを1つ以上開いてね。", ephemeral=True)
            return
        await interaction.response.defer()
        await self.finish_game("win", "💰 好きなタイミングで精算したよ！")

    async def finish_game(self, result, result_text, exploded_index=None):
        if self.finished:
            return
        self.finished = True
        active_mine_users.discard(self.player_id)

        current_balance = get_balance(self.player_id)
        if result == "win":
            payout = int(self.bet * self.multiplier)
            new_balance = current_balance + payout
            profit = payout - self.bet
        elif result == "timeout":
            payout = self.bet
            new_balance = current_balance + self.bet
            profit = 0
        else:
            payout = 0
            new_balance = current_balance
            profit = -self.bet

        set_balance(self.player_id, new_balance)
        house_result = transfer_to_house(
            self.player_id,
            profit,
            self.guild.id if self.guild else None,
            "mine",
        )

        self.reveal_board(exploded_index=exploded_index)
        if self.inline_cashout_button:
            self.inline_cashout_button.disabled = True
        if self.cashout_view:
            self.cashout_view.button.disabled = True
            if self.cashout_message:
                try:
                    await self.cashout_message.edit(view=self.cashout_view)
                except discord.HTTPException:
                    pass
        if result == "win":
            result_text += f"\n払い戻し：**{money(payout)}**\n利益：**{money_change(profit)}**"
        elif result == "timeout":
            result_text += f"\n返金：**{money(payout)}**"
        else:
            result_text += f"\n損失：**{money_change(profit)}**"

        embed = self.make_embed(result, result_text)
        embed.description += (
            f"\n💰 **払戻し：{money(payout)}**"
            f"　📊 **収支：{money_change(profit)}**"
            f"\n🏦 **終了後残高：{money(new_balance)}**"
        )
        try:
            if self.message:
                await self.message.edit(embed=embed, view=self)
        except (discord.NotFound, discord.HTTPException):
            pass

        log_embed = discord.Embed(
            title=f"💣 MINES ゲームログ — {result.upper()}",
            description=f"プレイヤー：{self.ctx.author.mention}",
            color=discord.Color.green() if result == "win" else discord.Color.orange() if result == "timeout" else discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        log_embed.add_field(name="プレイしたサーバー", value=f"{self.guild.name} (ID: {self.guild.id})" if self.guild else "不明", inline=False)
        log_embed.add_field(name="ユーザー名", value=str(self.ctx.author), inline=True)
        log_embed.add_field(name="ユーザーID", value=str(self.player_id), inline=True)
        log_embed.add_field(name="賭け金", value=money(self.bet), inline=True)
        log_embed.add_field(name="盤面", value=f"{self.size}×{self.size}", inline=True)
        log_embed.add_field(name="爆弾の数", value=f"{self.bomb_count}個", inline=True)
        log_embed.add_field(name="開いた安全マス", value=f"{len(self.opened_safe)} / {self.safe_total}", inline=True)
        log_embed.add_field(name="最終倍率", value=f"{self.multiplier:.2f}倍", inline=True)
        log_embed.add_field(
            name="出目内訳",
            value=(
                f"💵 {sum(1 for v in self.cell_symbols.values() if v == '💵')}個 / "
                f"💍 {sum(1 for v in self.cell_symbols.values() if v == '💍')}個 / "
                f"💎 {sum(1 for v in self.cell_symbols.values() if v == '💎')}個"
            ),
            inline=True,
        )
        log_embed.add_field(name="払い戻し", value=money(payout), inline=True)
        log_embed.add_field(name="利益 / 損失", value=money_change(profit), inline=True)
        log_embed.add_field(name="終了後の残高", value=money(new_balance), inline=False)
        if house_result is not None:
            log_embed.add_field(name="胴元の残高変動", value=money_change(house_result["change"]), inline=True)
        await send_mine_log(self.guild, log_embed)

    async def on_timeout(self):
        if not self.finished:
            await self.finish_game("timeout", "時間切れになったため賭け金を返金したよ。")


@bot.command(name="mine", aliases=["マイン"])
async def mine_command(ctx, bet_text: str, size: int, bomb_count: int):
    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。", mention_author=False)
        return
    if ctx.author.id in active_mine_users:
        await ctx.reply("すでにマインズをプレイ中だよ！先に今のゲームを終わらせてね。", mention_author=False)
        return
    if not 3 <= size <= 4:
        await ctx.reply("マスのサイズは3か4で指定してね（例：.mine 1000 3 3）。5×5は現在利用できないよ。", mention_author=False)
        return

    total_cells = size * size
    if not 1 <= bomb_count <= total_cells - 1:
        await ctx.reply(f"爆弾の数は1〜{total_cells - 1}個で指定してね。", mention_author=False)
        return

    current_balance = get_balance(ctx.author.id)
    # MINESの最大賭け金は250,000。all指定でも上限を超えない。
    if str(bet_text).strip().casefold() == "all":
        bet = min(current_balance, 250000)
    else:
        bet = resolve_bet(ctx.author.id, bet_text)

    if bet is None or bet <= 0:
        await ctx.reply("賭け金は1以上の数字か all で指定してね。", mention_author=False)
        return
    if bet > 250000:
        await ctx.reply("MINESの最大賭け金は **250,000** だよ。", mention_author=False)
        return

    if bet > current_balance:
        await ctx.reply(f"残高が足りないよ！\n残高：**{money(current_balance)}**", mention_author=False)
        return

    set_balance(ctx.author.id, current_balance - bet)
    active_mine_users.add(ctx.author.id)
    view = MineGameView(ctx, bet, size, bomb_count)
    embed = view.make_embed()
    embed.add_field(name="現在の精算額", value=money(bet), inline=False)
    try:
        message = await ctx.reply(embed=embed, view=view, mention_author=False)
        view.message = message
    except Exception:
        view.finished = True
        active_mine_users.discard(ctx.author.id)
        set_balance(ctx.author.id, get_balance(ctx.author.id) + bet)
        if view.message:
            for item in view.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            try:
                await view.message.edit(content="ゲームの開始に失敗したため賭け金を返金したよ。", embed=None, view=view)
            except discord.HTTPException:
                pass
        raise


# ==================================================
# .cash 残高確認
# ==================================================

@bot.command(name="cash", aliases=["balance", "bal", "残高"])
async def cash_command(ctx, member: discord.Member = None):
    member = member or ctx.author
    amount = get_balance(member.id)

    embed = discord.Embed(
        title="💰 残高",
        description=f"{member.mention} の残高：**{money(amount)}**",
        color=discord.Color.gold(),
    )
    await ctx.reply(embed=embed, mention_author=False)

# ==================================================
# /all_cash 全メンバーの残高一覧
# ==================================================

BALANCE_LIST_PER_PAGE = 15

class AllCashView(discord.ui.View):
    def __init__(self, pages, author_id):
        super().__init__(timeout=180)
        self.pages = pages
        self.page_index = 0
        self.author_id = author_id
        self.update_buttons()

    def update_buttons(self):
        self.previous_button.disabled = self.page_index <= 0
        self.next_button.disabled = self.page_index >= len(self.pages) - 1

    def make_embed(self):
        embed = discord.Embed(
            title="💰 全メンバーの残高一覧",
            description=self.pages[self.page_index],
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"{self.page_index + 1} / {len(self.pages)} ページ")
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "この一覧を操作できるのは実行した本人だけだよ。",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="前へ", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction, button):
        self.page_index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="次へ", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction, button):
        self.page_index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

@bot.tree.command(
    name="all_cash",
    description="全メンバーの残高一覧を表示する（オーナー本人専用）",
)
async def all_cash_command(interaction: discord.Interaction):
    if not await require_owner(interaction):
        return

    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内で使ってね。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        members = [
            member async for member in interaction.guild.fetch_members(limit=None)
            if not member.bot
        ]
    except Exception:
        print("[ALL CASH] メンバー取得に失敗。キャッシュを使用します。")
        traceback.print_exc()
        members = [member for member in interaction.guild.members if not member.bot]

    members.sort(
        key=lambda member: (
            -int(balances.get(str(member.id), STARTING_BALANCE)),
            member.display_name.casefold(),
        )
    )

    if not members:
        await interaction.followup.send("表示できるメンバーがいないよ。", ephemeral=True)
        return

    lines = []
    for number, member in enumerate(members, start=1):
        amount = int(balances.get(str(member.id), STARTING_BALANCE))
        lines.append(f"`{number:>3}.` {member.mention} — **{money(amount)}**")

    pages = [
        "\n".join(lines[index:index + BALANCE_LIST_PER_PAGE])
        for index in range(0, len(lines), BALANCE_LIST_PER_PAGE)
    ]

    view = AllCashView(pages, interaction.user.id)
    await interaction.followup.send(embed=view.make_embed(), view=view, ephemeral=True)

# ==================================================
# 1. スロット用 View (もう一度回すボタン)
# ==================================================
class SlotView(discord.ui.View):
    def __init__(self, original_author_id, base_bet, line_choice):
        super().__init__(timeout=180)
        self.original_author_id = original_author_id
        self.base_bet = base_bet
        self.line_choice = line_choice

    @discord.ui.button(label="もう一度回す", style=discord.ButtonStyle.primary, emoji="🎰")
    async def spin_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_author_id:
            await interaction.response.send_message("他の人が回したスロのボタンは押せないよ！自分のコマンドで回してね。", ephemeral=True)
            return

        ctx = await interaction.client.get_context(interaction.message)
        ctx.author = interaction.user
        ctx.guild = interaction.guild

        await execute_slot(ctx, self.base_bet, self.line_choice, interaction=interaction)


# ==================================================
# 2. スロット実行の共通処理
# ==================================================
async def execute_slot(ctx, base_bet, line_choice, interaction=None):
    settings = get_server_settings(ctx.guild.id)
    allowed, reason = can_use_slot(ctx.author, settings)

    if not allowed:
        if interaction:
            await interaction.response.send_message(reason, ephemeral=True)
        else:
            await ctx.reply(reason, mention_author=False)
        return

    active_lines_count = line_choice
    total_bet = base_bet * line_choice

    if total_bet <= 0:
        msg = "賭け金に使える残高がないよ。"
        if interaction:
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx.reply(msg, mention_author=False)
        return

    minimum = int(settings.get("min_bet", 1))
    if base_bet < minimum:
        msg = f"1ラインあたりの最低賭け金は **{money(minimum)}** だよ。"
        if interaction:
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx.reply(msg, mention_author=False)
        return

    current_balance = get_balance(ctx.author.id)
    if total_bet > current_balance:
        msg = f"残高が足りないよ！\n必要額（総額）：**{money(total_bet)}**\n残高：**{money(current_balance)}**"
        if interaction:
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx.reply(msg, mention_author=False)
        return

    jp_contribution = max(1, int(total_bet * 0.1))
    add_jackpot_pool(jp_contribution)

    positions = [random.randrange(len(LANE_PATTERNS[index])) for index in range(3)]
    slot_positions[str(ctx.author.id)] = positions
    save_json(POSITIONS_FILE, slot_positions)

    weights = settings.get("weights", DEFAULT_WEIGHTS)
    grid = make_grid(positions, weights)
    
    paylines = get_paylines(grid, line_choice)

    # 777 / JACKPOT のリーチなら、右レーン停止前に少し間を作る
    special_reach = any(
        line[0] == line[1] and line[0] in ("7️⃣", "JP")
        for line in paylines
    )

    winning_symbol = None
    total_payout = 0
    hit_jackpot = False

    for line in paylines:
        if line[0] == line[1] == line[2]:
            sym = line[0]
            mult = PAYOUTS.get(sym, 0)
            total_payout += base_bet * mult
            winning_symbol = sym
            if sym == "JP":
                hit_jackpot = True

    jackpot_won_amount = 0
    if hit_jackpot:
        jackpot_won_amount = get_jackpot_pool()
        total_payout += jackpot_won_amount
        reset_jackpot_pool(10000)

    new_balance = current_balance - total_bet
    if total_payout > 0:
        new_balance += total_payout

    set_balance(ctx.author.id, new_balance)
    profit = total_payout - total_bet

    house_result = transfer_to_house(
        player_id=ctx.author.id,
        profit=profit,
        guild_id=ctx.guild.id,
        game="slot",
    )

    profit_text = money_change(profit)
    displayed_rows = [
        [display_symbol(symbol, ctx.guild, settings) for symbol in row]
        for row in grid
    ]

    # ジャックポットのプール金額を数字絵文字に変換
    jp_pool_val = get_jackpot_pool()
    jp_pool_str = f"{jp_pool_val}"
    jp_nums = [number_emoji(ch) for ch in jp_pool_str]
    jp_display_parts = "<:emoji_20:1565598463154982972>" + "".join(jp_nums)

    # 桁数が大きくなっても小さくなってもエラーにならないように安全に処理
    bet_money_str = str(total_bet)[-3:].zfill(3)
    won_money_str = str(max(0, total_payout))[-5:].zfill(5)
    
    bal_str = str(abs(int(new_balance)))
    if len(bal_str) > 11:
        bal_money_str = bal_str[-11:]
    else:
        bal_money_str = bal_str.zfill(11)

    b = [number_emoji(ch) for ch in bet_money_str]
    w = [number_emoji(ch) for ch in won_money_str]
    c = [number_emoji(ch) for ch in bal_money_str]

    left_top = "<:emoji_20:1564565447448199220>"
    left_mid = "<:emoji_22:1564567674162516089>"
    left_bot = "<:emoji_20:1564565432327741440>"

    right_top = "<:emoji_21:1564565471817244832>"
    right_mid = "<:emoji_22:1564567647927017522>"
    right_bot = "<:emoji_22:1564565484307877988>"

    bet_label_emoji = "<:emoji_24:1564584196926611516>"
    won_label_emoji = "<:emoji_27:1564590865165328455>"
    credit_label_emoji = "<:emoji_28:1564643181700849765>"
    gray_emoji = "<:emoji_25:1564584610820657203>"
    
    top_bottom_gray = f"{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}"
    divider_gray = f"{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}{gray_emoji}"

    # スロット盤面の右側（青線部分）にJP絵文字と数値を配置し、指定された箇所にグレーを配置
    slot_display = (
        f"{top_bottom_gray}\n"
        f"{left_top} {'|'.join(displayed_rows[0])} {right_top} {gray_emoji}\n"
        f"{left_mid} {'|'.join(displayed_rows[1])} {right_mid} {jp_display_parts}{gray_emoji}\n"
        f"{left_bot} {'|'.join(displayed_rows[2])} {right_bot} {gray_emoji}\n"
        f"{top_bottom_gray}\n"
        f"{bet_label_emoji}{b[0]}{b[1]}{b[2]}{gray_emoji}{won_label_emoji}{w[0]}{w[1]}{w[2]}{w[3]}{w[4]}{gray_emoji}{gray_emoji}\n"
        f"{divider_gray}\n"
        f"{credit_label_emoji}{c[0]}{c[1]}{c[2]}{c[3]}{c[4]}{c[5]}{c[6]}{c[7]}{c[8]}{c[9]}{c[10]}{gray_emoji}\n"
        f"{top_bottom_gray}"
    )


    if hit_jackpot:
        color = discord.Color.from_rgb(255, 215, 0)
    elif total_payout > 0:
        color = discord.Color.green()
    elif profit == 0:
        color = discord.Color.gold()
    else:
        color = discord.Color.red()

    embed = discord.Embed(description=slot_display, color=color)
    if hit_jackpot:
        embed.set_author(name="🎉 JACKPOT WINNER!! 🎉", icon_url=ctx.author.display_avatar.url if hasattr(ctx.author, "display_avatar") else None)

    view = SlotView(ctx.author.id, base_bet, line_choice)
    # 回転演出中は再スピンボタンを無効化
    view.spin_again.disabled = True

    # 通常起動・「もう一度回す」の両方で共通のリール演出を使う
    spin_emoji = "<a:emoji_34:1570925093058781264>"

    def make_reel_animation_embed(revealed_columns):
        reel_rows = []
        for row_index in range(3):
            cells = [
                displayed_rows[row_index][column_index]
                if column_index < revealed_columns
                else spin_emoji
                for column_index in range(3)
            ]
            reel_rows.append("|".join(cells))

        animation_display = (
            f"{top_bottom_gray}\n"
            f"{left_top} {reel_rows[0]} {right_top} {gray_emoji}\n"
            f"{left_mid} {reel_rows[1]} {right_mid} {jp_display_parts}{gray_emoji}\n"
            f"{left_bot} {reel_rows[2]} {right_bot} {gray_emoji}\n"
            f"{top_bottom_gray}\n"
            f"{bet_label_emoji}{b[0]}{b[1]}{b[2]}{gray_emoji}{won_label_emoji}{w[0]}{w[1]}{w[2]}{w[3]}{w[4]}{gray_emoji}{gray_emoji}\n"
            f"{divider_gray}\n"
            f"{credit_label_emoji}{c[0]}{c[1]}{c[2]}{c[3]}{c[4]}{c[5]}{c[6]}{c[7]}{c[8]}{c[9]}{c[10]}{gray_emoji}\n"
            f"{top_bottom_gray}"
        )
        # 回転中は結果を予想できないよう、右レーン停止まですべて灰色
        animation_embed = discord.Embed(
            description=animation_display,
            color=discord.Color.dark_grey(),
        )
        return animation_embed

    if interaction:
        # ボタンからの再スピンも同じメッセージを編集して演出する
        await interaction.response.edit_message(
            embed=make_reel_animation_embed(0),
            view=view,
        )
        await asyncio.sleep(0.3)
        await interaction.message.edit(embed=make_reel_animation_embed(1), view=view)
        await asyncio.sleep(0.3)
        await interaction.message.edit(embed=make_reel_animation_embed(2), view=view)
        if special_reach:
            await asyncio.sleep(0.8)
        await asyncio.sleep(0.3)
        view.spin_again.disabled = False
        await interaction.message.edit(embed=embed, view=view)
    else:
        spin_message = await ctx.reply(
            embed=make_reel_animation_embed(0),
            mention_author=False,
        )
        await asyncio.sleep(0.3)
        await spin_message.edit(embed=make_reel_animation_embed(1))
        await asyncio.sleep(0.3)
        await spin_message.edit(embed=make_reel_animation_embed(2))
        if special_reach:
            await asyncio.sleep(0.8)
        await asyncio.sleep(0.3)
        view.spin_again.disabled = False
        await spin_message.edit(embed=embed, view=view)

    displayed_grid = grid_text(grid, guild=ctx.guild, settings=settings)

    log_data = {
        "type": "slot",
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "guild_id": ctx.guild.id,
        "user_id": ctx.author.id,
        "username": str(ctx.author),
        "bet": total_bet,
        "payout": total_payout,
        "profit": profit,
        "balance": new_balance,
        "grid": grid,
        "line_choice": line_choice,
        "emoji_mode": settings.get("emoji_mode", "unicode"),
    }

    if house_result is not None:
        log_data["house_change"] = house_result["change"]
        log_data["house_balance"] = house_result["after"]

    record_slot(log_data)

    log_description = (
        f"ユーザー：{ctx.author.mention} (`{ctx.author.id}`)\n"
        f"選択ライン：{line_choice} （{active_lines_count}ライン）\n"
        f"賭け金（総額）：**{money(total_bet)}**\n配当：**{money(total_payout)}**\n"
        f"収支：**{profit_text}**\n残高：**{money(new_balance)}**\n"
    )

    if hit_jackpot:
        log_description += f"\n🏆 **ジャックポット獲得！賞金: {money(jackpot_won_amount)}**\n"

    log_description += f"\n{displayed_grid}"

    if house_result is not None:
        log_description += (
            f"\n\n胴元の残高変動：**{money_change(house_result['change'])}**\n"
            f"胴元の残高：**{house_result['after']}**"
        )

    await send_slot_log(
        ctx.guild,
        discord.Embed(title="🎰 スロットログ", description=log_description, color=color),
    )


# ==================================================
# 3. .slot コマンド本体
# ==================================================
@bot.command(name="slot")
async def slot_command(ctx, bet_text: str, lines_text: str = "1"):
    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。", mention_author=False)
        return

    base_bet = resolve_bet(ctx.author.id, bet_text)
    if base_bet is None:
        await ctx.reply("賭け金は数字か `all` で指定してね。\n例：`.slot 3 3`", mention_author=False)
        return

    try:
        line_choice = int(lines_text)
        if line_choice not in (1, 2, 3):
            raise ValueError
    except ValueError:
        await ctx.reply("ライン数は `1`（真ん中）、`2`（上下中）、`3`（上下中＋斜め）のいずれかで指定してね。\n例：`.slot 3 3`", mention_author=False)
        return

    await execute_slot(ctx, base_bet, line_choice)

# ==================================================
# /decidecash 指定したユーザーの残高を設定
# ==================================================

@bot.tree.command(
    name="decidecash",
    description="指定したユーザーの残高を設定する（管理者専用）",
)
@app_commands.describe(
    target="残高を設定する対象のユーザー",
    amount="設定する金額",
)
@app_commands.default_permissions(administrator=True)
async def decidecash_command(interaction: discord.Interaction, target: discord.User, amount: int):
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
        return

    if target.bot:
        await interaction.response.send_message("Botの残高は設定できないよ。", ephemeral=True)
        return

    if amount < 0:
        await interaction.response.send_message("残高にマイナスの値は設定できないよ。", ephemeral=True)
        return

    before = get_balance(target.id)
    set_balance(target.id, amount)

    embed = discord.Embed(
        title="💰 残高設定",
        description=(
            f"対象：{target.mention}\n"
            f"設定金額：**{money(amount)}**\n"
            f"変更前：**{money(before)}**\n"
            f"実行者：{interaction.user.mention}"
        ),
        color=discord.Color.gold(),
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

    # 履歴用データに記録
    record_coin({
        "type": "decidecash",
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "guild_id": interaction.guild.id,
        "user_id": target.id,
        "username": str(target),
        "actor_id": interaction.user.id,
        "actor_name": str(interaction.user),
        "amount": amount,
        "before": before,
        "after": amount,
    })

    # 固定ログチャンネルへ通知
    await send_coin_log(
        interaction.guild,
        discord.Embed(
            title="💰 Decidecashログ",
            description=(
                f"対象：{target.mention} (`{target.id}`)\n"
                f"実行者：{interaction.user.mention} (`{interaction.user.id}`)\n"
                f"設定金額：**{money(amount)}**\n"
                f"変更前：**{money(before)}**\n"
                f"変更後：**{money(amount)}**"
            ),
            color=discord.Color.gold(),
        ),
    )


# ==================================================
# /payment 残高の増減（スラッシュコマンド版）
# ==================================================

@bot.tree.command(
    name="payment",
    description="指定したメンバーの残高を増減させる（オーナー本人専用）",
)
@app_commands.describe(
    member="対象のメンバー",
    amount="変更する金額（プラスまたはマイナス）",
)
async def payment_command(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not await require_owner(interaction):
        return

    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内で使ってね。", ephemeral=True)
        return

    if member.bot:
        await interaction.response.send_message("Botには送金できないよ。", ephemeral=True)
        return

    if amount == 0:
        await interaction.response.send_message("金額は0以外にしてね。", ephemeral=True)
        return

    before = get_balance(member.id)
    after = before + amount
    set_balance(member.id, after)

    embed = discord.Embed(
        title="💸 Payment",
        description=(
            f"対象：{member.mention}\n変更額：**{money_change(amount)}**\n"
            f"変更前：**{money(before)}**\n変更後：**{money(after)}**\n"
            f"実行者：{interaction.user.mention}"
        ),
        color=discord.Color.blurple(),
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

    record_coin({
        "type": "payment",
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "guild_id": interaction.guild.id,
        "user_id": member.id,
        "username": str(member),
        "actor_id": interaction.user.id,
        "actor_name": str(interaction.user),
        "amount": amount,
        "before": before,
        "after": after,
    })

    await send_coin_log(
        interaction.guild,
        discord.Embed(
            title="💸 Paymentログ",
            description=(
                f"対象：{member.mention} (`{member.id}`)\n"
                f"実行者：{interaction.user.mention} (`{interaction.user.id}`)\n"
                f"変更額：**{money_change(amount)}**\n"
                f"変更前：**{money(before)}**\n変更後：**{money(after)}**"
            ),
            color=discord.Color.blurple(),
        ),
    )


# ==================================================
# .help / .mhelp
# ==================================================

@bot.command(name="mhelp", aliases=["help"])
async def help_command(ctx):
    embed = discord.Embed(
        title="📖 コマンド一覧",
        description=(
            "**一般コマンド**\n"
            "`.slot 賭け金` — スロットを回す\n"
            "`.slot all` — 所持金を全額賭ける\n"
            "`.jackpot` — ジャックポットの蓄積額を確認する\n"
            "`.color 賭け金` — 🌝🌚の2択ゲーム\n"
            "`.color all` — 所持金を全額賭ける\n"
            "`.mine 賭け金 サイズ 爆弾数` — 爆弾ゲーム（例：`.mine 1000 3 6`）\n"
            "`.cash` — 自分の残高を見る\n"
            "`.cash @ユーザー` — 指定ユーザーの残高を見る\n"
            "`.mdaily` — ログインボーナス\n"
            "`/settinginfo` — 現在の設定\n"
            "`/guess setup` — 数字・言葉当てゲームの設定（管理者）\n"
            "`/guess stop` — ゲーム停止（管理者）\n\n"
            "**オーナー本人専用**\n"
            "`.Payment @ユーザー 金額` — 残高を増減\n"
            "`/all_cash` — 全メンバーの残高一覧\n"
            "`/setting` — Botの設定パネル\n"
            "`/log panel` — 固定ログ送信先の確認\n"
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
            placeholder="ログ送信先は固定されています",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        if not await require_owner(interaction):
            return

        await interaction.response.send_message(
            "ログ送信先は固定されているよ。\n"
            f"スロットログ・Paymentログ・ログインボーナス共通：<#{LOG_CHANNEL_ID}>",
            ephemeral=True,
        )

class LogChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(LogChannelSelect())

# ==================================================
# /log panel
# ==================================================

log_group = app_commands.Group(name="log", description="ログ設定")

@log_group.command(name="panel", description="固定ログ送信先を確認する（オーナー本人専用）")
async def log_panel(interaction: discord.Interaction):
    if not await require_owner(interaction):
        return

    if interaction.guild is None:
        await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
        return

    channel = bot.get_channel(LOG_CHANNEL_ID)

    embed = discord.Embed(
        title="📝 固定ログ送信先",
        description=(
            "スロットログ・Paymentログ・ログインボーナスは、"
            "次のチャンネルに送信されるよ。\n\n"
            f"<#{LOG_CHANNEL_ID}>\n\nチャンネルID：`{LOG_CHANNEL_ID}`"
        ),
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="状態",
        value=(
            "固定チャンネルを取得できました。"
            if channel is not None
            else "チャンネルを取得できません。IDとBotの権限を確認してね。"
        ),
        inline=False,
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.tree.add_command(log_group)

# ==================================================
# .slothelp スロットの説明
# ==================================================

@bot.command(name="slothelp", aliases=["スロットヘルプ", "slot_help"])
async def slot_help_command(ctx):
    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。", mention_author=False)
        return

    settings = get_server_settings(ctx.guild.id)
    minimum = int(settings.get("min_bet", 1))

    embed = discord.Embed(
        title="🎰 スロットの遊び方・ルール",
        description=(
            "選んだライン数に応じて、当たり判定のラインと総賭け金が変わるよ！\n\n"
            "**【コマンドの使い方】**\n"
            "`.slot 賭け金 ライン数`\n"
            "例：`.slot 100 2` （1ラインあたり100コインで、2を指定）\n\n"
            "**【選べるライン数】**\n"
            "* **`1`（1ライン）**: 真ん中の横1列（総賭け金 = 1倍）\n"
            "* **`2`（3ライン）**: 上・中・下の横3列（総賭け金 = 3倍）\n"
            "* **`3`（5ライン）**: 上・中・下 ＋ 斜め2本（総賭け金 = 5倍）\n\n"
            "**【配当倍率】**\n"
            "* 🍒 ＝ **2倍**\n"
            "* 🍋 ＝ **3倍**\n"
            "* 🔔 ＝ **5倍**\n"
            "* 💣 ＝ **20倍**\n"
            "* ⭐ ＝ **10倍**\n"
            "* 7️⃣ ＝ **50倍**\n"
            f"* <:emoji_20:1565598463154982972> ＝ **100倍 ＋ ジャックポット全額**\n\n"
            f"※1ラインあたりの最低賭け金：**{money(minimum)}**\n"
            "※所持金を全額賭けたいときは、数字の代わりに `all` が使えるよ！"
        ),
        color=discord.Color.gold(),
    )
    await ctx.reply(embed=embed, mention_author=False)

# ==================================================
# /setting モーダル・サブメニュー（スロット詳細設定対応版）
# ==================================================

# --- 賭け金設定 ---
class GameBetSettingModal(discord.ui.Modal):
    def __init__(self, game_key, game_name):
        self.game_key = game_key
        self.game_name = game_name
        super().__init__(title=f"{game_name}の賭け金設定")

        self.min_bet_input = discord.ui.TextInput(
            label="最低賭け金（0以上の整数）",
            placeholder="例：0",
            default="0",
            required=True,
            min_length=1,
            max_length=15,
        )
        self.max_bet_input = discord.ui.TextInput(
            label="最高賭け金（整数 または inf で無制限）",
            placeholder="例：10000 または inf",
            default="inf",
            required=True,
            min_length=1,
            max_length=15,
        )

        self.add_item(self.min_bet_input)
        self.add_item(self.max_bet_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        try:
            min_val = int(str(self.min_bet_input.value).strip())
            if min_val < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("最低賭け金は0以上の整数で入力してね。", ephemeral=True)
            return

        max_raw = str(self.max_bet_input.value).strip().lower()
        if max_raw in ("inf", "infinity", "無制限"):
            max_val = "inf"
        else:
            try:
                max_val = int(max_raw)
                if max_val < min_val:
                    await interaction.response.send_message("最高賭け金は最低賭け金以上の数値にしてね。", ephemeral=True)
                    return
            except ValueError:
                await interaction.response.send_message("最高賭け金は整数、または無制限にする場合は `inf` と入力してね。", ephemeral=True)
                return

        settings = get_server_settings(interaction.guild.id)
        if "bet_limits" not in settings or not isinstance(settings["bet_limits"], dict):
            settings["bet_limits"] = {}

        settings["bet_limits"][self.game_key] = {
            "min": min_val,
            "max": max_val
        }
        if self.game_key == "slot":
            settings["min_bet"] = min_val

        save_server_settings(interaction.guild.id)

        max_text = "無制限 (inf)" if max_val == "inf" else money(max_val)
        await interaction.response.send_message(
            f"**{self.game_name}** の賭け金設定を変更したよ！\n"
            f"最低賭け金：**{money(min_val)}**\n"
            f"最高賭け金：**{max_text}**",
            ephemeral=True,
        )

class GameSelectForBetView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.select(
        placeholder="対象のゲームを選択してね",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="スロット", value="slot", emoji="🎰"),
            discord.SelectOption(label="カラー", value="color", emoji="🌝"),
            discord.SelectOption(label="ブラックジャック", value="bj", emoji="🃏"),
            discord.SelectOption(label="ルーレット", value="roulette", emoji="🎡"),  # 👈 追加
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not await require_owner(interaction):
            return

        game_map = {
            "slot": "スロット",
            "color": "カラー",
            "bj": "ブラックジャック",
            "roulette": "ルーレット",  # 👈 追加
        }
        chosen_key = select.values[0]
        chosen_name = game_map[chosen_key]

        await interaction.response.send_modal(GameBetSettingModal(chosen_key, chosen_name))

# --- 出目排出確率設定 ---
class WeightsSettingModal(discord.ui.Modal):
    def __init__(self, current_weights):
        super().__init__(title="出目排出確率の設定")

        current_value = ",".join(
            f"{symbol}={current_weights.get(symbol, 0)}"
            for symbol in SYMBOLS
        )

        self.weights_input = discord.ui.TextInput(
            label="絵柄ごとの比率",
            placeholder="🍒=20,🍋=20,⭐=20,🔔=20,7️⃣=20,💣=20,JP=5",
            default=current_value,
            required=True,
            max_length=200,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.weights_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        raw = str(self.weights_input.value).strip()
        parsed = {}

        try:
            for part in raw.split(","):
                if "=" not in part:
                    raise ValueError

                symbol, value = part.split("=", 1)
                symbol = symbol.strip()
                value = int(value.strip())

                if symbol not in SYMBOLS or value < 0 or value > 1000:
                    raise ValueError

                parsed[symbol] = value

            if any(symbol not in parsed for symbol in SYMBOLS) or sum(parsed.values()) <= 0:
                raise ValueError

        except ValueError:
            await interaction.response.send_message(
                "入力形式が正しくないよ。\n"
                "例：`🍒=20,🍋=20,⭐=20,🔔=20,7️⃣=20,💣=20,JP=5`\n"
                "各数値は0〜1000で、合計を1以上にしてね。",
                ephemeral=True,
            )
            return

        settings = get_server_settings(interaction.guild.id)
        settings["weights"] = parsed
        save_server_settings(interaction.guild.id)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎰 出現比率を更新したよ",
                description=get_weights_text(parsed),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


# --- ペイアウト倍率設定 ---
class PayoutsSettingModal(discord.ui.Modal):
    def __init__(self, current_payouts):
        super().__init__(title="ペイアウト倍率の設定")

        current_value = ",".join(
            f"{symbol}={current_payouts.get(symbol, PAYOUTS.get(symbol, 0))}"
            for symbol in SYMBOLS
        )

        self.payouts_input = discord.ui.TextInput(
            label="各絵柄が揃った時の配当倍率",
            placeholder="🍒=5,🍋=8,🔔=10,⭐=25,7️⃣=45,💣=35,JP=75",
            default=current_value,
            required=True,
            max_length=200,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.payouts_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        raw = str(self.payouts_input.value).strip()
        parsed = {}

        try:
            for part in raw.split(","):
                if "=" not in part:
                    raise ValueError

                symbol, value = part.split("=", 1)
                symbol = symbol.strip()
                value = int(value.strip())

                if symbol not in SYMBOLS or value < 0:
                    raise ValueError

                parsed[symbol] = value

            if any(symbol not in parsed for symbol in SYMBOLS):
                raise ValueError

        except ValueError:
            await interaction.response.send_message(
                "入力形式が正しくないよ。\n"
                "例：`🍒=5,🍋=8,🔔=10,⭐=25,7️⃣=45,💣=35,JP=75`\n"
                "各倍率は0以上の整数で入力してね。",
                ephemeral=True,
            )
            return

        settings = get_server_settings(interaction.guild.id)
        settings["payouts"] = parsed
        save_server_settings(interaction.guild.id)

        # グローバル変数 PAYOUTS も更新（サーバー個別に反映）
        PAYOUTS.update(parsed)

        payout_text = "\n".join(f"{s}：{v}倍" for s, v in parsed.items())
        await interaction.response.send_message(
            embed=discord.Embed(
                title="💰 ペイアウト倍率を更新したよ",
                description=payout_text,
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


# --- JP初期値設定（カラーJP拡張対応） ---
class JPInitialSettingModal(discord.ui.Modal):
    def __init__(self, jp_key="red", jp_name="RED JP"):
        self.jp_key = jp_key
        self.jp_name = jp_name
        super().__init__(title=f"{jp_name} 初期値の設定")

        self.initial_input = discord.ui.TextInput(
            label=f"{jp_name} の初期積立金額",
            placeholder="例：10000",
            default="10000",
            required=True,
            min_length=1,
            max_length=15,
        )
        self.add_item(self.initial_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return

        try:
            val = int(str(self.initial_input.value).strip())
            if val < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("金額は0以上の整数で入力してね。", ephemeral=True)
            return

        # JPデータの更新
        jackpot_data[f"initial_{self.jp_key}"] = val
        save_json(JACKPOT_FILE, jackpot_data)

        await interaction.response.send_message(
            f"**{self.jp_name}** の初期金額を **{money(val)}** に設定したよ！\n"
            f"※次回JPリセット（当選時）からこの初期値が適用されます。",
            ephemeral=True,
        )


class JPColorSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.select(
        placeholder="設定したいJPを選択してね",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="RED JP", value="red", description="RED JPの初期金額を設定", emoji="🔴"),
            # 将来追加する場合の例:
            # discord.SelectOption(label="BLUE JP", value="blue", description="BLUE JPの初期金額を設定", emoji="🔵"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not await require_owner(interaction):
            return

        jp_map = {
            "red": "RED JP",
            # "blue": "BLUE JP",
        }
        chosen_key = select.values[0]
        chosen_name = jp_map[chosen_key]

        await interaction.response.send_modal(JPInitialSettingModal(chosen_key, chosen_name))


# --- スロットサブメニュー選択View ---
class SlotSubMenuSelectView(discord.ui.View):
    def __init__(self, current_settings):
        super().__init__(timeout=180)
        self.current_settings = current_settings

    @discord.ui.select(
        placeholder="スロットの変更項目を選んでね",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="出目排出確率", description="絵柄ごとの出現比率を変更", value="weights", emoji="🎲"),
            discord.SelectOption(label="ペイアウト倍率", description="揃った時の獲得倍率を変更", value="payouts", emoji="💰"),
            discord.SelectOption(label="JP", description="ジャックポットの初期値を設定", value="jp", emoji="🎰"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not await require_owner(interaction):
            return

        chosen = select.values[0]
        if chosen == "weights":
            await interaction.response.send_modal(WeightsSettingModal(self.current_settings.get("weights", DEFAULT_WEIGHTS)))
        elif chosen == "payouts":
            current_p = self.current_settings.get("payouts", PAYOUTS)
            await interaction.response.send_modal(PayoutsSettingModal(current_p))
        elif chosen == "jp":
            await interaction.response.send_message(
                "設定するジャックポットを選択してね。",
                view=JPColorSelectView(),
                ephemeral=True
            )


# ==================================================
# /setting メイン選択メニュー
# ==================================================

class SettingActionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="賭け金", description="ゲームごとの最低・最高賭け金を変更", value="min_bet", emoji="🪙"),
            discord.SelectOption(label="スロット", description="確率・ペイアウト・JPを設定", value="slot_settings", emoji="🎰"),
            discord.SelectOption(label="メンテナンス", description="一般メンバーのスロットを停止・再開", value="maintenance", emoji="🛠️"),
        ]

        super().__init__(
            placeholder="変更する設定を選んでね",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        selected = self.values[0]
        settings = get_server_settings(interaction.guild.id)

        if selected == "min_bet":
            await interaction.response.send_message(
                "賭け金を変更したいゲームを選んでね。",
                view=GameSelectForBetView(),
                ephemeral=True,
            )
        elif selected == "slot_settings":
            await interaction.response.send_message(
                "スロットの設定項目を選んでね。",
                view=SlotSubMenuSelectView(settings),
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
# メンテナンスモード
# ==================================================

class MaintenanceSettingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="メンテナンス開始", style=discord.ButtonStyle.danger, emoji="🔴")
    async def enable_maintenance(self, interaction, button):
        if not await require_owner(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        settings = get_server_settings(interaction.guild.id)
        settings["maintenance"] = True
        save_server_settings(interaction.guild.id)

        await interaction.response.send_message(
            "メンテナンスモードを **ON** にしたよ。\n一般メンバーはスロットを使えなくなるよ。",
            ephemeral=True,
        )

    @discord.ui.button(label="メンテナンス終了", style=discord.ButtonStyle.success, emoji="🟢")
    async def disable_maintenance(self, interaction, button):
        if not await require_owner(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        settings = get_server_settings(interaction.guild.id)
        settings["maintenance"] = False
        save_server_settings(interaction.guild.id)

        await interaction.response.send_message(
            "メンテナンスモードを **OFF** にしたよ。",
            ephemeral=True,
        )

async def recover_coins_for_guild(guild):
    guild_id = guild.id
    latest_balances = {}
    combined_logs = []

    for item in slot_logs + coin_logs:
        try:
            if int(item.get("guild_id", 0)) == guild_id:
                combined_logs.append(item)
        except (TypeError, ValueError, AttributeError):
            continue

    channel = await get_log_channel(guild)
    if channel is not None:
        try:
            async for message in channel.history(limit=None, oldest_first=True):
                for embed in message.embeds:
                    title = embed.title or ""
                    description = embed.description or ""

                    if "スロットログ" in title:
                        user_match = re.search(r"ユーザー：.*?`(\d+)`", description)
                        balance_match = re.search(
                            r"残高：\*\*([+-]?\$?[\d,]+)\*\*",
                            description,
                        )
                    elif "Paymentログ" in title:
                        user_match = re.search(r"対象：.*?`(\d+)`", description)
                        balance_match = re.search(
                            r"変更後：\*\*([+-]?\$?[\d,]+)\*\*",
                            description,
                        )
                    elif "胴元残高ログ" in title:
                        user_match = re.search(r"オーナーID：`(\d+)`", description)
                        balance_match = re.search(
                            r"変更後：\*\*([+-]?\$?[\d,]+)\*\*",
                            description,
                        )
                    else:
                        continue

                    if user_match and balance_match:
                        combined_logs.append({
                            "timestamp": message.created_at.timestamp(),
                            "user_id": user_match.group(1),
                            "balance": parse_money_text(balance_match.group(1)),
                        })
        except discord.Forbidden:
            print("[COIN RECOVERY] ログ閲覧権限がありません")
            return "権限エラー"
        except discord.HTTPException:
            traceback.print_exc()
            return "Discord取得エラー"

    combined_logs.sort(
        key=lambda item: float(item.get("timestamp", 0))
    )

    for item in combined_logs:
        try:
            user_id = str(int(item["user_id"]))
            amount = int(item.get("balance", item.get("after")))
            latest_balances[user_id] = amount
        except (KeyError, TypeError, ValueError):
            continue

    if not latest_balances:
        return "復旧ログなし"

    balances.update(latest_balances)
    save_json(BALANCES_FILE, balances)

    return f"{len(latest_balances)}人の残高を復旧"

# ==================================================
# /whitelist あう検知ホワイトリスト（Botオーナー専用）
# ==================================================

whitelist_group = app_commands.Group(
    name="whitelist",
    description="あう検知ホワイトリストを管理する",
)


@whitelist_group.command(name="add", description="ユーザーをあう検知ホワイトリストに登録する")
@app_commands.describe(user="ホワイトリストに登録するユーザー")
async def whitelist_add(
    interaction: discord.Interaction,
    user: discord.Member,
):
    if not await require_owner(interaction):
        return

    user_id = str(user.id)
    if user_id in au_whitelist:
        await interaction.response.send_message(
            f"{user.mention} は既にホワイトリストに登録されているよ。",
            ephemeral=True,
        )
        return

    au_whitelist.add(user_id)
    save_json(AU_WHITELIST_FILE, sorted(au_whitelist, key=int))

    await interaction.response.send_message(
        f"✅ {user.mention} をあう検知ホワイトリストに登録したよ！\n"
        "このユーザーのメッセージでは「あう」検知に反応しなくなるよ。",
        ephemeral=True,
    )


@whitelist_group.command(name="remove", description="ユーザーをあう検知ホワイトリストから解除する")
@app_commands.describe(user="ホワイトリストから解除するユーザー")
async def whitelist_remove(
    interaction: discord.Interaction,
    user: discord.Member,
):
    if not await require_owner(interaction):
        return

    user_id = str(user.id)
    if user_id not in au_whitelist:
        await interaction.response.send_message(
            f"{user.mention} はホワイトリストに登録されていないよ。",
            ephemeral=True,
        )
        return

    au_whitelist.remove(user_id)
    save_json(AU_WHITELIST_FILE, sorted(au_whitelist, key=int))

    await interaction.response.send_message(
        f"✅ {user.mention} をホワイトリストから解除したよ！",
        ephemeral=True,
    )


@whitelist_group.command(name="list", description="あう検知ホワイトリストの登録者一覧を表示する")
async def whitelist_list(interaction: discord.Interaction):
    if not await require_owner(interaction):
        return

    if not au_whitelist:
        await interaction.response.send_message(
            "ホワイトリストの登録者はいないよ。",
            ephemeral=True,
        )
        return

    user_ids = sorted(au_whitelist, key=int)
    lines = [f"<@{user_id}>  (ID: {user_id})" for user_id in user_ids]

    embed = discord.Embed(
        title="📋 あう検知ホワイトリスト",
        description="\n".join(lines[:80]),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"登録者数：{len(user_ids)}人")
    if len(lines) > 80:
        embed.add_field(
            name="表示について",
            value=f"先頭80人を表示中。残り {len(lines) - 80} 人は省略したよ。",
            inline=False,
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(whitelist_group)


# ==================================================
# /setting
# ==================================================

@bot.tree.command(name="setting", description="Botの設定パネルを開く（オーナー本人専用）")
async def setting_command(interaction: discord.Interaction):
    if not await require_owner(interaction):
        return

    if interaction.guild is None:
        await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
        return

    settings = get_server_settings(interaction.guild.id)
    bet_limits = settings.get("bet_limits", {})

    def format_limit(game_key):
        limits = bet_limits.get(game_key, {})
        min_v = limits.get("min", 0)
        max_v = limits.get("max", "inf")
        max_str = "無制限" if max_v == "inf" else money(max_v)
        return f"最低: {money(min_v)} / 最高: {max_str}"

    embed = discord.Embed(
        title="Bot設定パネル",
        description="下のメニューから変更したい設定を選んでね。",
        color=discord.Color.blurple(),
    )

    embed.add_field(name="🎰 スロット賭け金", value=format_limit("slot"), inline=True)
    embed.add_field(name="🌝 カラー賭け金", value=format_limit("color"), inline=True)
    embed.add_field(name="🃏 BJ賭け金", value=format_limit("bj"), inline=True)
    embed.add_field(name="メンテナンス", value="ON" if settings.get("maintenance", False) else "OFF", inline=True)
    embed.add_field(name="絵柄・出現比率", value=get_weights_text(settings["weights"]), inline=False)

    await interaction.response.send_message(embed=embed, view=SettingPanelView(), ephemeral=True)


# ==================================================
# /coinrecovery
# ==================================================

@bot.tree.command(
    name="coinrecovery",
    description="JSONとDiscordログから残高を復旧する（オーナー本人専用）",
)
async def coinrecovery_command(interaction: discord.Interaction):
    if not await require_owner(interaction):
        return

    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内で使ってね。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    guild_id = interaction.guild.id
    latest_balances = {}
    combined_logs = []
    discord_log_count = 0
    json_log_count = 0
    errors = []

    for item in slot_logs:
        try:
            if int(item.get("guild_id", 0)) == guild_id:
                combined_logs.append(item)
                json_log_count += 1
        except (TypeError, ValueError, AttributeError):
            continue

    for item in coin_logs:
        try:
            if int(item.get("guild_id", 0)) == guild_id:
                combined_logs.append(item)
                json_log_count += 1
        except (TypeError, ValueError, AttributeError):
            continue

    channel = await get_log_channel(interaction.guild)

    if channel is None:
        errors.append("固定ログチャンネルを取得できなかったよ。")
    else:
        try:
            async for message in channel.history(limit=None, oldest_first=True):
                for embed in message.embeds:
                    title = embed.title or ""
                    description = embed.description or ""

                    if "スロットログ" in title:
                        user_match = re.search(r"ユーザー：.*?`(\d+)`", description)
                        balance_match = re.search(r"残高：\*\*([+-]?\$?[\d,]+)\*\*", description)

                        if user_match and balance_match:
                            combined_logs.append({
                                "type": "slot",
                                "timestamp": message.created_at.timestamp(),
                                "guild_id": guild_id,
                                "user_id": user_match.group(1),
                                "balance": parse_money_text(balance_match.group(1)),
                                "source": "discord",
                            })
                            discord_log_count += 1

                    elif "Paymentログ" in title:
                        user_match = re.search(r"対象：.*?`(\d+)`", description)
                        after_match = re.search(r"変更後：\*\*([+-]?\$?[\d,]+)\*\*", description)

                        if user_match and after_match:
                            combined_logs.append({
                                "type": "payment",
                                "timestamp": message.created_at.timestamp(),
                                "guild_id": guild_id,
                                "user_id": user_match.group(1),
                                "after": parse_money_text(after_match.group(1)),
                                "source": "discord",
                            })
                            discord_log_count += 1

                    elif "胴元残高ログ" in title:
                        user_match = re.search(r"オーナーID：`(\d+)`", description)
                        after_match = re.search(r"変更後：\*\*([+-]?\$?[\d,]+)\*\*", description)

                        if user_match and after_match:
                            combined_logs.append({
                                "type": "house_transfer",
                                "timestamp": message.created_at.timestamp(),
                                "guild_id": guild_id,
                                "user_id": user_match.group(1),
                                "after": parse_money_text(after_match.group(1)),
                                "source": "discord",
                            })
                            discord_log_count += 1

        except discord.Forbidden:
            errors.append("ログチャンネルの閲覧権限またはメッセージ履歴を読む権限がないよ。")
        except discord.HTTPException:
            errors.append("Discordからログを取得できなかったよ。")
            traceback.print_exc()
        except Exception:
            errors.append("ログの読み取り中にエラーが発生したよ。")
            traceback.print_exc()

    combined_logs.sort(key=lambda item: float(item.get("timestamp", 0)))

    for item in combined_logs:
        user_id = item.get("user_id")
        if user_id is None:
            continue

        try:
            user_id = str(int(user_id))
        except (TypeError, ValueError):
            continue

        balance_value = item.get("balance", item.get("after"))
        if balance_value is None:
            continue

        try:
            latest_balances[user_id] = int(balance_value)
        except (TypeError, ValueError):
            continue

    if not latest_balances:
        message = (
            "復旧に使える残高ログが見つからなかったよ。\n\n"
            f"JSONログ件数：{json_log_count}\nDiscordログ件数：{discord_log_count}\n\n"
            "固定ログチャンネルにスロットログやPaymentログが残っているか確認してね。"
        )

        if errors:
            message += "\n\n確認事項：\n" + "\n".join(errors)

        await interaction.followup.send(message, ephemeral=True)
        return

    for user_id, amount in latest_balances.items():
        balances[user_id] = amount

    save_json(BALANCES_FILE, balances)

    embed = discord.Embed(
        title="残高復旧完了",
        description=(
            f"復旧対象：**{len(latest_balances)}人**\n"
            f"JSONログ：**{json_log_count}件**\n"
            f"Discordログ：**{discord_log_count}件**\n\n"
            "確認できたログのうち、最も新しい残高を保存したよ。"
        ),
        color=discord.Color.green(),
    )

    if errors:
        embed.add_field(name="確認事項", value="\n".join(errors)[:1000], inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)

# ==================================================
# /settinginfo 設定の確認
# ==================================================

@bot.tree.command(name="settinginfo", description="現在のBot設定を表示する")
async def setting_info_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
        return

    settings = get_server_settings(interaction.guild.id)

    permission_labels = {
        "everyone": "全メンバー",
        "owner": "ownerロール以上",
        "admin": "管理者のみ",
    }

    embed = discord.Embed(title="現在の設定", color=discord.Color.blurple())
    embed.add_field(name="最低賭け金", value=money(int(settings["min_bet"])), inline=True)
    embed.add_field(
        name="使用権限",
        value=permission_labels.get(settings.get("slot_permission", "everyone"), "全メンバー"),
        inline=True,
    )
    embed.add_field(name="メンテナンス", value="ON" if settings.get("maintenance") else "OFF", inline=True)
    embed.add_field(name="出目の絵文字タイプ", value=get_display_mode_name(settings), inline=True)
    embed.add_field(name="絵柄ごとの比率", value=get_weights_text(settings["weights"]), inline=False)
    embed.add_field(name="固定ログ送信先", value=f"<#{LOG_CHANNEL_ID}>", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

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
    app.run(host="0.0.0.0", port=port, use_reloader=False)


# ==========================================
# ブラックジャック関連機能（ダブルダウン・終了ログ対応完全版）
# ==========================================

from PIL import Image
import os
import random
import asyncio
import discord

# ==========================================
# 設定
# ==========================================

BJ_TIMEOUT = 300

active_blackjack_users = set()

# ==========================================
# 金額表示
# ==========================================

def bj_money(amount):
    return f"${amount:,}"


def bj_money_change(amount):
    if amount > 0:
        return f"+${amount:,}"
    elif amount < 0:
        return f"-${abs(amount):,}"
    return "±$0"


# ==========================================
# カード画像
# ==========================================

def get_card_image_path(suit, value):

    if suit == "back":
        return "cards/IMG_0678.png"

    if suit == "joker":
        return "cards/IMG_0677.png"

    suit_offsets = {
        "spade": 625,
        "club": 638,
        "diamond": 651,
        "heart": 664
    }

    if suit in suit_offsets:

        val_map = {
            "A": 1,
            "J": 11,
            "Q": 12,
            "K": 13
        }

        if isinstance(value, str) and value.upper() in val_map:
            val = val_map[value.upper()]
        else:
            val = int(value)

        file_num = suit_offsets[suit] + (val - 1)

        return f"cards/IMG_{file_num:04d}.png"

    return "cards/IMG_0678.png"


# ==========================================
# 横並び画像作成
# ==========================================

def merge_horizontal(image_paths):

    try:

        if not image_paths:
            return None

        images = []

        for path in image_paths:

            if not os.path.exists(path):
                print(f"[BJ IMAGE ERROR] File not found: {path}")
                return None

            with Image.open(path) as source:
                images.append(source.convert("RGBA"))

        h = max(img.height for img in images)

        resized_images = []

        for img in images:

            if img.height != h:
                new_width = int(img.width * h / img.height)
                img = img.resize((new_width, h))

            resized_images.append(img)

        total_width = sum(img.width for img in resized_images)

        merged_img = Image.new(
            "RGBA",
            (total_width, h),
            (0, 0, 0, 0)
        )

        x_offset = 0

        for img in resized_images:

            merged_img.paste(
                img,
                (x_offset, 0),
                img
            )

            x_offset += img.width

        return merged_img

    except Exception as e:

        print(f"[BJ HORIZONTAL ERROR] {e}")
        return None


# ==========================================
# 上下合体画像作成
# ==========================================

def create_bj_table_image(
    dealer_paths,
    player_paths,
    output_path
):

    try:

        img_dealer = merge_horizontal(dealer_paths)
        img_player = merge_horizontal(player_paths)

        if img_dealer is None or img_player is None:
            return None

        max_width = max(
            img_dealer.width,
            img_player.width
        )

        total_height = (
            img_dealer.height +
            img_player.height
        )

        table_img = Image.new(
            "RGBA",
            (max_width, total_height),
            (0, 0, 0, 0)
        )

        d_x = (max_width - img_dealer.width) // 2
        p_x = (max_width - img_player.width) // 2

        table_img.paste(
            img_dealer,
            (d_x, 0),
            img_dealer
        )

        table_img.paste(
            img_player,
            (p_x, img_dealer.height),
            img_player
        )

        os.makedirs("cards", exist_ok=True)

        table_img.save(output_path)

        return output_path

    except Exception as e:

        print(f"[BJ TABLE ERROR] {e}")
        return None


# ==========================================
# 手札合計計算
# ==========================================

def calculate_hand(hand):

    score = 0
    aces = 0

    for card in hand:

        val = card["val"]

        if val in ["J", "Q", "K"]:
            score += 10

        elif val == "A":
            score += 11
            aces += 1

        else:
            score += int(val)

    while score > 21 and aces > 0:
        score -= 10
        aces -= 1

    return score


# ==========================================
# ブラックジャック判定
# ==========================================

def is_blackjack(hand):

    if len(hand) != 2:
        return False

    values = [card["val"] for card in hand]

    has_ace = "A" in values

    has_ten = any(
        val in ["10", "J", "Q", "K"]
        for val in values
    )

    return has_ace and has_ten


# ==========================================
# ブラックジャック画面
# ==========================================

class BlackjackView(discord.ui.View):

    def __init__(
        self,
        ctx,
        deck,
        player_hand,
        dealer_hand,
        bet
    ):

        super().__init__(timeout=BJ_TIMEOUT)

        self.ctx = ctx
        self.deck = deck

        self.player_hand = player_hand
        self.dealer_hand = dealer_hand

        # 元の賭け金
        self.original_bet = bet

        # 現在の合計賭け金
        self.bet = bet

        self.message = None
        self.lock = asyncio.Lock()

        self.game_over = False
        self.settled = False

        self.user_id = ctx.author.id

        # ダブルダウン使用済みか
        self.doubled_down = False

        # 最初の2枚の状態でのみ使用可能
        self.can_double_down = True

        # ログ二重送信防止
        self.log_sent = False

        self.image_path = f"cards/bj_table_{id(self)}.png"

    # --------------------------------------
    # 勝敗決済
    # --------------------------------------

    def settle_game(self, outcome):

        if self.settled:
            return 0, 0

        if outcome == "bj":

            # ブラックジャック：2.5倍返却
            returned = self.bet * 5 // 2

        elif outcome == "win":

            # 通常勝利：2倍返却
            returned = self.bet * 2

        elif outcome == "push":

            # 引き分け：全額返却
            returned = self.bet

        else:

            # 敗北：返却なし
            returned = 0

        profit = returned - self.bet

        # 残高更新
        current_balance = get_balance(self.user_id)

        set_balance(
            self.user_id,
            current_balance + returned
        )

        # 残高更新成功後に決済済みにする
        self.settled = True

        active_blackjack_users.discard(self.user_id)

        return profit, returned

    # --------------------------------------
    # ゲーム終了処理
    # --------------------------------------

    def finish_game(self, result, outcome):

        if self.game_over:
            return

        profit, returned = self.settle_game(outcome)

        self.game_over = True

        self.can_double_down = False

        for child in self.children:
            child.disabled = True

        if outcome in ["win", "bj"]:
            color = discord.Color.green()

        elif outcome == "lose":
            color = discord.Color.red()

        else:
            color = discord.Color.light_grey()

        self.final_profit = profit
        self.final_returned = returned

        self.final_result = result
        self.final_color = color

    # --------------------------------------
    # 終了ログ送信
    # --------------------------------------

    async def send_bj_log(self):

        # 未決済・送信済みなら何もしない
        if self.log_sent or not self.settled:
            return

        self.log_sent = True

        try:

            channel = bot.get_channel(LOG_CHANNEL_ID)

            if channel is None:
                channel = await bot.fetch_channel(LOG_CHANNEL_ID)

            # プレイヤーの手札
            player_cards = ", ".join(
                f"{card['suit']}の{card['val']}"
                for card in self.player_hand
            )

            # ディーラーの手札
            dealer_cards = ", ".join(
                f"{card['suit']}の{card['val']}"
                for card in self.dealer_hand
            )

            hand_text = (
                f"**プレイヤー：** {player_cards} "
                f"({calculate_hand(self.player_hand)})\n"
                f"**ディーラー：** {dealer_cards} "
                f"({calculate_hand(self.dealer_hand)})"
            )

            # 決済後の残高
            balance = get_balance(self.user_id)

            embed = discord.Embed(
                title="🃏 ブラックジャック終了ログ",
                color=self.final_color
            )

            embed.add_field(
                name="ログ名",
                value=self.ctx.author.display_name,
                inline=False
            )

            embed.add_field(
                name="手札",
                value=hand_text,
                inline=False
            )

            embed.add_field(
                name="利益",
                value=bj_money_change(self.final_profit),
                inline=True
            )

            embed.add_field(
                name="返却",
                value=bj_money(self.final_returned),
                inline=True
            )

            embed.add_field(
                name="残高",
                value=bj_money(balance),
                inline=True
            )

            if self.ctx.guild is not None:
                embed.add_field(
                    name="プレイしたサーバー",
                    value=f"{self.ctx.guild.name} (ID: {self.ctx.guild.id})",
                    inline=False,
                )

            await channel.send(embed=embed)

        except Exception as e:

            print(f"[BJ LOG ERROR] {e}")

    # --------------------------------------
    # 山札確認
    # --------------------------------------

    def check_deck(self):

        if not self.deck:
            raise RuntimeError("山札がなくなりました。")

    # --------------------------------------
    # 操作できる人を制限
    # --------------------------------------

    async def interaction_check(self, interaction):

        if interaction.user.id == self.user_id:
            return True

        await interaction.response.send_message(
            "他の人のゲームには干渉できません！",
            ephemeral=True
        )

        return False

    # --------------------------------------
    # ディーラーの勝負処理
    # --------------------------------------

    def resolve_dealer(self):

        while calculate_hand(self.dealer_hand) < 17:

            self.check_deck()

            self.dealer_hand.append(
                self.deck.pop()
            )

        p_score = calculate_hand(self.player_hand)
        d_score = calculate_hand(self.dealer_hand)

        if d_score > 21:

            result = "ディーラーがバースト！あなたの勝ちです！ 🎉"
            outcome = "win"

        elif p_score > d_score:

            result = "あなたの勝ちです！ 🏆"
            outcome = "win"

        elif p_score < d_score:

            result = "あなたの負けです… 😢"
            outcome = "lose"

        else:

            result = "引き分け (Push) です！ 🤝"
            outcome = "push"

        self.finish_game(result, outcome)

    # --------------------------------------
    # 操作エラー表示
    # --------------------------------------

    async def send_error(self, interaction, message):

        try:

            await interaction.followup.send(
                message,
                ephemeral=True
            )

        except discord.HTTPException:
            pass

    # --------------------------------------
    # タイムアウト
    # --------------------------------------

    async def on_timeout(self):

        async with self.lock:

            if self.game_over:
                return

            self.finish_game(
                "操作時間切れ！賭け金は没収されました。",
                "lose"
            )

            # 終了ログ
            await self.send_bj_log()

            embed, files = self.create_embed_and_files(
                game_over=True
            )

            if self.message:

                try:

                    await self.message.edit(
                        embed=embed,
                        attachments=files,
                        view=self
                    )

                except discord.HTTPException as e:

                    print(f"[BJ TIMEOUT ERROR] {e}")

            self.stop()

    # ======================================
    # ヒット
    # ======================================

    @discord.ui.button(
        label="ヒット (Hit)",
        style=discord.ButtonStyle.green
    )
    async def hit(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.defer()

        async with self.lock:

            if self.game_over:

                await self.send_error(
                    interaction,
                    "このゲームは終了しています。"
                )
                return

            try:

                # ヒットしたらダブルダウン不可
                self.can_double_down = False
                self.double_down.disabled = True

                self.check_deck()

                self.player_hand.append(
                    self.deck.pop()
                )

                p_score = calculate_hand(
                    self.player_hand
                )

                if p_score > 21:

                    self.finish_game(
                        "バースト！あなたの負けです… 😭",
                        "lose"
                    )

                # ゲーム終了時だけログ送信
                if self.game_over:
                    await self.send_bj_log()

                embed, files = self.create_embed_and_files(
                    game_over=self.game_over
                )

                await interaction.edit_original_response(
                    embed=embed,
                    attachments=files,
                    view=self
                )

                if self.game_over:
                    self.stop()

            except Exception as e:

                print(f"[BJ HIT ERROR] {e}")

                await self.send_error(
                    interaction,
                    "処理中にエラーが発生しました。"
                )

    # ======================================
    # スタンド
    # ======================================

    @discord.ui.button(
        label="スタンド (Stand)",
        style=discord.ButtonStyle.blurple
    )
    async def stand(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.defer()

        async with self.lock:

            if self.game_over:

                await self.send_error(
                    interaction,
                    "このゲームは終了しています。"
                )
                return

            try:

                # スタンドしたらダブルダウン不可
                self.can_double_down = False
                self.double_down.disabled = True

                self.resolve_dealer()

                # 終了ログ
                await self.send_bj_log()

                embed, files = self.create_embed_and_files(
                    game_over=True
                )

                await interaction.edit_original_response(
                    embed=embed,
                    attachments=files,
                    view=self
                )

                self.stop()

            except Exception as e:

                print(f"[BJ STAND ERROR] {e}")

                await self.send_error(
                    interaction,
                    "処理中にエラーが発生しました。"
                )

    # ======================================
    # ダブルダウン
    # ======================================

    @discord.ui.button(
        label="ダブルダウン (×2)",
        style=discord.ButtonStyle.red
    )
    async def double_down(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.defer()

        async with self.lock:

            if self.game_over:

                await self.send_error(
                    interaction,
                    "このゲームは終了しています。"
                )
                return

            # 使用済みなら拒否
            if self.doubled_down or not self.can_double_down:

                button.disabled = True

                await self.send_error(
                    interaction,
                    "ダブルダウンは使用できません。"
                )
                return

            try:

                # 追加で必要な金額
                additional_bet = self.original_bet

                current_balance = get_balance(self.user_id)

                # 残高確認
                if current_balance < additional_bet:

                    await self.send_error(
                        interaction,
                        f"残高不足です！\n"
                        f"追加で必要な金額：{bj_money(additional_bet)}\n"
                        f"現在の残高：{bj_money(current_balance)}"
                    )
                    return

                # ==================================
                # 二重使用防止
                # ==================================

                self.doubled_down = True
                self.can_double_down = False

                # 即座にボタン無効化
                button.disabled = True

                # ヒット・スタンドも無効化
                self.hit.disabled = True
                self.stand.disabled = True

                # ==================================
                # 追加賭け金徴収
                # ==================================

                set_balance(
                    self.user_id,
                    current_balance - additional_bet
                )

                # 合計賭け金を2倍にする
                self.bet += additional_bet

                # ==================================
                # カードを1枚だけ引く
                # ==================================

                self.check_deck()

                self.player_hand.append(
                    self.deck.pop()
                )

                p_score = calculate_hand(
                    self.player_hand
                )

                # ==================================
                # 自動勝負
                # ==================================

                if p_score > 21:

                    self.finish_game(
                        "ダブルダウン後にバースト！あなたの負けです… 😭",
                        "lose"
                    )

                else:

                    self.resolve_dealer()

                # 終了ログ
                await self.send_bj_log()

                embed, files = self.create_embed_and_files(
                    game_over=True
                )

                await interaction.edit_original_response(
                    embed=embed,
                    attachments=files,
                    view=self
                )

                self.stop()

            except Exception as e:

                print(f"[BJ DOUBLE DOWN ERROR] {e}")

                await self.send_error(
                    interaction,
                    "ダブルダウンの処理中にエラーが発生しました。"
                )

    # ======================================
    # Embed・画像作成
    # ======================================

    def create_embed_and_files(self, game_over=False):

        color = (
            self.final_color
            if game_over and self.settled
            else discord.Color.gold()
        )

        embed = discord.Embed(
            title="🃏 ブラックジャック",
            color=color
        )

        p_score = calculate_hand(self.player_hand)
        d_score = calculate_hand(self.dealer_hand)

        # ----------------------------------
        # ディーラーのカード
        # ----------------------------------

        if game_over:

            dealer_text = f"手札（合計: {d_score}）"

            dealer_paths = [
                get_card_image_path(
                    c["suit"],
                    c["val"]
                )
                for c in self.dealer_hand
            ]

            d_cards_str = ", ".join(
                [
                    f"{c['suit']}の{c['val']}"
                    for c in self.dealer_hand
                ]
            )

        else:

            dealer_text = "手札（2枚目は裏面）"

            dealer_paths = [
                get_card_image_path(
                    self.dealer_hand[0]["suit"],
                    self.dealer_hand[0]["val"]
                ),
                get_card_image_path("back", 0)
            ]

            d_cards_str = (
                f"{self.dealer_hand[0]['suit']}の"
                f"{self.dealer_hand[0]['val']}, 裏面"
            )

        # ----------------------------------
        # プレイヤーのカード
        # ----------------------------------

        player_paths = [
            get_card_image_path(
                c["suit"],
                c["val"]
            )
            for c in self.player_hand
        ]

        p_cards_str = ", ".join(
            [
                f"{c['suit']}の{c['val']}"
                for c in self.player_hand
            ]
        )

        # ----------------------------------
        # 画像作成
        # ----------------------------------

        table_image_path = create_bj_table_image(
            dealer_paths,
            player_paths,
            self.image_path
        )

        files = []

        if table_image_path:

            files.append(
                discord.File(
                    table_image_path,
                    filename="table.png"
                )
            )

            embed.set_image(
                url="attachment://table.png"
            )

        # ----------------------------------
        # 手札表示
        # ----------------------------------

        embed.add_field(
            name=f"ディーラーの{dealer_text}",
            value=d_cards_str,
            inline=False
        )

        embed.add_field(
            name=f"プレイヤーの手札（合計: {p_score}）",
            value=p_cards_str,
            inline=False
        )

        # ----------------------------------
        # 賭け金表示
        # ----------------------------------

        embed.add_field(
            name="💰 合計賭け金",
            value=bj_money(self.bet),
            inline=True
        )

        if self.doubled_down:

            embed.add_field(
                name="追加賭け金",
                value=bj_money(self.original_bet),
                inline=True
            )

        # ----------------------------------
        # 終了後
        # ----------------------------------

        if game_over:

            embed.add_field(
                name="【試合結果】",
                value=self.final_result,
                inline=False
            )

            embed.add_field(
                name="📊 今回の利益",
                value=f"**{bj_money_change(self.final_profit)}**",
                inline=True
            )

            embed.add_field(
                name="💵 返却額",
                value=f"**{bj_money(self.final_returned)}**",
                inline=True
            )

            embed.set_footer(
                text="ブラックジャック • GAME OVER"
            )

        else:

            embed.add_field(
                name="🎮 操作",
                value=(
                    "ヒット：カードを引く\n"
                    "スタンド：現在の手札で勝負\n"
                    "ダブルダウン：賭け金を2倍にして1枚だけ引く"
                ),
                inline=False
            )

        return embed, files


# ==========================================
# ブラックジャック開始コマンド
# ==========================================

@bot.command(name="bj")
async def blackjack(ctx, bet: int = None):

    user_id = ctx.author.id

    # --------------------------------------
    # 賭け金確認
    # --------------------------------------

    if bet is None:
        await ctx.send("使い方：`.bj 1000`")
        return

    # サーバーの設定（最低・最高賭け金）を取得
    settings = get_server_settings(ctx.guild.id)
    bet_limits = settings.get("bet_limits", {})
    bj_limit = bet_limits.get("bj", {"min": 0, "max": "inf"})
    
    min_bet = bj_limit.get("min", 0)
    max_bet = bj_limit.get("max", "inf")

    if bet < min_bet:
        await ctx.send(f"ブラックジャックの最低賭け金は **{bj_money(min_bet)}** です。")
        return

    if max_bet != "inf" and bet > max_bet:
        max_str = bj_money(max_bet)
        await ctx.send(f"ブラックジャックの最高賭け金は **{max_str}** までです。")
        return

    # --------------------------------------
    # 同時ゲーム防止
    # --------------------------------------

    if user_id in active_blackjack_users:

        await ctx.send(
            "既にブラックジャックをプレイ中です！"
        )
        return

    # --------------------------------------
    # 残高確認
    # --------------------------------------

    balance = get_balance(user_id)

    if balance < bet:

        await ctx.send(
            f"残高不足です！\n"
            f"必要額：{bj_money(bet)}\n"
            f"現在の残高：{bj_money(balance)}"
        )
        return

    # --------------------------------------
    # ゲーム開始
    # --------------------------------------

    active_blackjack_users.add(user_id)

    try:

        set_balance(
            user_id,
            balance - bet
        )

        # ----------------------------------
        # 山札作成
        # ----------------------------------

        suits = [
            "spade",
            "club",
            "diamond",
            "heart"
        ]

        values = [
            "A", "2", "3", "4", "5",
            "6", "7", "8", "9", "10",
            "J", "Q", "K"
        ]

        deck = [
            {"suit": s, "val": v}
            for s in suits
            for v in values
        ]

        random.shuffle(deck)

        # ----------------------------------
        # 初期手札
        # ----------------------------------

        player_hand = [
            deck.pop(),
            deck.pop()
        ]

        dealer_hand = [
            deck.pop(),
            deck.pop()
        ]

        # ----------------------------------
        # View作成
        # ----------------------------------

        view = BlackjackView(
            ctx,
            deck,
            player_hand,
            dealer_hand,
            bet
        )

        # ----------------------------------
        # 初期BJ判定
        # ----------------------------------

        player_bj = is_blackjack(player_hand)
        dealer_bj = is_blackjack(dealer_hand)

        if player_bj and dealer_bj:

            view.finish_game(
                "両者ブラックジャック！引き分けです！ 🤝",
                "push"
            )

        elif player_bj:

            view.finish_game(
                "ナチュラルブラックジャック！あなたの勝ちです！ 🎉",
                "bj"
            )

        elif dealer_bj:

            view.finish_game(
                "ディーラーがブラックジャック！あなたの負けです。",
                "lose"
            )

        # ----------------------------------
        # Embed作成
        # ----------------------------------

        embed, files = view.create_embed_and_files(
            game_over=view.game_over
        )

        if files:

            view.message = await ctx.send(
                embed=embed,
                files=files,
                view=view
            )

        else:

            view.message = await ctx.send(
                embed=embed,
                view=view
            )

        # 初期ブラックジャックなどで即終了した場合
        if view.game_over:
            await view.send_bj_log()
            view.stop()

    except Exception as e:

        print(f"[BJ START ERROR] {e}")

        # 開始失敗時の返金
        if 'view' not in locals() or not view.settled:

            try:

                current_balance = get_balance(user_id)

                set_balance(
                    user_id,
                    current_balance + bet
                )

            except Exception as refund_error:

                print(f"[BJ REFUND ERROR] {refund_error}")

            active_blackjack_users.discard(user_id)

        await ctx.send(
            "ブラックジャックの開始に失敗しました。"
        )
        
from PIL import Image, ImageDraw
import os

from PIL import Image, ImageDraw
import os

from PIL import Image, ImageDraw
import os

import os
import random
import asyncio
import math
from datetime import datetime, timezone
import discord
from PIL import Image, ImageDraw

# ==================================================
# 🎡 ルーレットゲーム（ボール位置・半径調整完了版）
# ==================================================

# ジャックポットのプール管理用関数
def get_jackpot_pool():
    if "pool" not in jackpot_data:
        jackpot_data["pool"] = 10000
        save_json(JACKPOT_FILE, jackpot_data)
    return int(jackpot_data["pool"])

def add_jackpot_pool(amount):
    current = get_jackpot_pool()
    jackpot_data["pool"] = current + int(amount)
    save_json(JACKPOT_FILE, jackpot_data)
    return jackpot_data["pool"]

def reset_jackpot_pool(amount=10000):
    jackpot_data["pool"] = int(amount)
    save_json(JACKPOT_FILE, jackpot_data)


# 各ベット位置の正確な座標マップ（ベット確認用のテーブル画像サイズ: 1070 × 607 用）
ROULETTE_COORDINATES = {
    # 色（ダイヤの位置）
    "red": (469, 119),
    "black": (600, 119),
    
    # 奇数・偶数・ハイロー・ダースなど（外側エリアの座標）
    "even": (300, 119),
    "odd": (700, 119),
    "1 to 18": (180, 119),
    "19 to 36": (820, 119),
    "1 to 12": (300, 550),
    "13 to 24": (535, 550),
    "25 to 36": (770, 550),
    
    # 0の位置
    0: (108, 294),
}

# 1〜36 の数字座標を辞書に一気にマージ
ROULETTE_COORDINATES.update({
    1: (174, 383),  2: (174, 295),  3: (174, 206),
    4: (240, 383),  5: (240, 295),  6: (240, 206),
    7: (306, 383),  8: (306, 295),  9: (306, 206),
    10: (372, 383), 11: (372, 295), 12: (372, 206),
    13: (437, 383), 14: (437, 295), 15: (437, 206),
    16: (503, 383), 17: (503, 295), 18: (503, 206),
    19: (568, 383), 20: (568, 295), 21: (568, 206),
    22: (634, 383), 23: (634, 295), 24: (634, 206),
    25: (700, 383), 26: (700, 295), 27: (700, 206),
    28: (765, 383), 29: (765, 295), 30: (765, 206),
    31: (831, 383), 32: (831, 295), 33: (831, 206),
    34: (897, 383), 35: (897, 295), 36: (897, 206),
})

# ヨーロピアンルーレットのホイール上の数字の並び順（時計回り）
WHEEL_NUMBERS = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 
    10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]


def generate_roulette_table_image(target_key):
    """
    【ベット確認用】指定されたテーブル上の位置にチップを置いて画像を生成する
    """
    board_path = "cards/IMG_0715.jpeg"
    chip_path = "cards/IMG_0730.jpeg"
    
    if not os.path.exists(board_path) or not os.path.exists(chip_path):
        return None
        
    base_image = Image.open(board_path).convert("RGBA")
    
    chip_img = Image.open(chip_path).convert("RGBA")
    chip_size = 40
    chip_img = chip_img.resize((chip_size, chip_size), Image.Resampling.LANCZOS)
    
    mask = Image.new("L", (chip_size, chip_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, chip_size, chip_size), fill=255)
    
    rounded_chip = Image.new("RGBA", (chip_size, chip_size))
    rounded_chip.paste(chip_img, (0, 0), mask=mask)
    
    target_clean = str(target_key).strip().lower()
    
    if target_clean.isdigit():
        lookup_key = int(target_clean)
    else:
        lookup_key = target_clean
    
    if lookup_key in ROULETTE_COORDINATES:
        x, y = ROULETTE_COORDINATES[lookup_key]
        paste_x = x - chip_size // 2
        paste_y = y - chip_size // 2
        base_image.paste(rounded_chip, (paste_x, paste_y), mask=rounded_chip)
        
    output_path = "cards/current_roulette_board.png"
    os.makedirs("cards", exist_ok=True)
    base_image.save(output_path)
    
    return output_path


def remove_ball_background(ball_path, output_path="cards/transparent_ball.png"):
    """
    金色のボール画像（IMG_0751.jpeg）の白い背景を透明にして保存する
    """
    if not os.path.exists(ball_path):
        return None
        
    img = Image.open(ball_path).convert("RGBA")
    datas = img.getdata()
    
    new_data = []
    for item in datas:
        if item[0] > 220 and item[1] > 220 and item[2] > 220:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
            
    img.putdata(new_data)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


def generate_wheel_result_image(landed_number):
    """
    【結果発表用】円形ホイール（IMG_0734.jpeg）の白背景を透過し、赤黒数字の帯の上にボールを置く
    """
    wheel_path = "cards/IMG_0734.jpeg" 
    raw_ball_path = "cards/IMG_0751.jpeg"      
    
    ball_path = remove_ball_background(raw_ball_path, "cards/transparent_ball.png")
    
    if not os.path.exists(wheel_path) or not ball_path:
        return None

    base_image = Image.open(wheel_path).convert("RGBA")
    
    # ホイール側の白背景を透明化
    datas = base_image.getdata()
    new_data = []
    for item in datas:
        if item[0] > 220 and item[1] > 220 and item[2] > 220:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    base_image.putdata(new_data)

    width, height = base_image.size
    center_x = width / 2
    center_y = height / 2
    
    # ▼【調整】赤黒数字の帯の位置に合うように半径を外側（0.42）に広げました
    radius = min(width, height) * 0.24  
    
    try:
        index = WHEEL_NUMBERS.index(int(landed_number))
    except ValueError:
        return None
        
    angle_deg = (index * (360 / len(WHEEL_NUMBERS))) - 90
    angle_rad = math.radians(angle_deg)
    
    ball_x = center_x + radius * math.cos(angle_rad)
    ball_y = center_y + radius * math.sin(angle_rad)
    
    ball_img = Image.open(ball_path).convert("RGBA")
    
    # ボールのサイズ（全体の約5.5%）
    ball_size = int(min(width, height) * 0.04)  
    ball_img = ball_img.resize((ball_size, ball_size), Image.Resampling.LANCZOS)
    
    paste_x = int(ball_x - ball_size / 2)
    paste_y = int(ball_y - ball_size / 2)
    base_image.paste(ball_img, (paste_x, paste_y), mask=ball_img)
    
    output_path = "cards/current_wheel_result.png"
    os.makedirs("cards", exist_ok=True)
    base_image.save(output_path)
    
    return output_path


ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_BLACK = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}


# 1. ベット確認用のボタン View
class RouletteConfirmView(discord.ui.View):
    def __init__(self, ctx, bet, target_clean, target_raw):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.bet = bet
        self.target_clean = target_clean
        self.target_raw = target_raw
        self.confirmed = False
        self.message = None

    @discord.ui.button(label="確認（ルーレット開始）", style=discord.ButtonStyle.green, emoji="🎡")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("他の人のゲームのボタンは押せないよ！", ephemeral=True)
            return

        if self.confirmed:
            return
        self.confirmed = True

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(content="🎡 ルーレットを回転中...", embed=None, view=self, attachments=[])
        await execute_roulette_game(self.ctx, interaction.message, self.bet, self.target_clean, self.target_raw)

    async def on_timeout(self):
        if not self.confirmed:
            for child in self.children:
                child.disabled = True
            if self.message:
                try:
                    await self.message.edit(content="⏰ 時間切れでキャンセルされたよ。", view=self, attachments=[])
                except:
                    pass


# 2. ルーレットのメイン処理（ボタン押下後）
async def execute_roulette_game(ctx, message, bet, target_clean, target_raw):
    current_balance = get_balance(ctx.author.id)
    if bet > current_balance:
        await message.edit(content=f"残高が足りないよ！\n残高：**{money(current_balance)}**", view=None)
        return

    set_balance(ctx.author.id, current_balance - bet)

    landed_number = random.randint(0, 36)
    if landed_number == 0:
        landed_color = "green"
        color_emoji = "🟢"
    elif landed_number in ROULETTE_RED:
        landed_color = "red"
        color_emoji = "🔴"
    else:
        landed_color = "black"
        color_emoji = "⚫"

    bet_type = None
    bet_value = None

    if target_clean.isdigit():
        num = int(target_clean)
        if 0 <= num <= 36:
            bet_type = "number"
            bet_value = num
    elif target_clean in ["red", "赤"]:
        bet_type = "color"
        bet_value = "red"
    elif target_clean in ["black", "黒"]:
        bet_type = "color"
        bet_value = "black"
    elif target_clean in ["odd", "奇数"]:
        bet_type = "even_odd"
        bet_value = "odd"
    elif target_clean in ["even", "偶数"]:
        bet_type = "even_odd"
        bet_value = "even"
    elif target_clean in ["1 to 18", "19 to 36"]:
        bet_type = "high_low"
        bet_value = target_clean
    elif target_clean in ["1 to 12", "13 to 24", "25 to 36"]:
        bet_type = "dozen"
        bet_value = target_clean

    won = False
    multiplier = 0

    if bet_type == "number" and bet_value == landed_number:
        won = True
        multiplier = 36
    elif bet_type == "color" and bet_value == landed_color:
        won = True
        multiplier = 2
    elif bet_type == "even_odd" and landed_number != 0:
        if bet_value == "odd" and landed_number % 2 != 0:
            won = True
            multiplier = 2
        elif bet_value == "even" and landed_number % 2 == 0:
            won = True
            multiplier = 2
    elif bet_type == "high_low" and landed_number != 0:
        if bet_value == "1 to 18" and 1 <= landed_number <= 18:
            won = True
            multiplier = 2
        elif bet_value == "19 to 36" and 19 <= landed_number <= 36:
            won = True
            multiplier = 2
    elif bet_type == "dozen" and landed_number != 0:
        if bet_value == "1 to 12" and 1 <= landed_number <= 12:
            won = True
            multiplier = 3
        elif bet_value == "13 to 24" and 13 <= landed_number <= 24:
            won = True
            multiplier = 3
        elif bet_value == "25 to 36" and 25 <= landed_number <= 36:
            won = True
            multiplier = 3

    payout = bet * multiplier if won else 0
    profit = payout - bet
    new_balance = (current_balance - bet) + payout
    set_balance(ctx.author.id, new_balance)

    transfer_to_house(
        player_id=ctx.author.id,
        profit=profit,
        guild_id=ctx.guild.id if ctx.guild else None,
        game="roulette",
    )

    # 🔄 回転中のGIF演出（IMG_0745.gif を使用）
    spinning_gif_path = "cards/IMG_0745.gif"
    if os.path.exists(spinning_gif_path):
        try:
            await message.edit(
                content=None,
                embed=discord.Embed(title="🎡 ルーレット回転中...").set_image(url="attachment://spin.gif"),
                attachments=[discord.File(spinning_gif_path, filename="spin.gif")]
            )
        except:
            pass
    
    # ⏱️ 1.5秒間回転させる
    await asyncio.sleep(1.5)

    # 🎯【結果発表】円形ホイールの赤黒数字帯の上にボールを置いた画像を生成
    board_image_path = generate_wheel_result_image(landed_number)
    files = []
    if board_image_path and os.path.exists(board_image_path):
        files.append(discord.File(board_image_path, filename="roulette_result.png"))

    color = discord.Color.green() if won else discord.Color.red()
    result_text = f"🎉 **当たり！ 配当: {money(payout)}**" if won else "💸 **ハズレ…**"

    embed = discord.Embed(
        title="🎰 ルーレット結果",
        description=(
            f"プレイヤー：{ctx.author.mention}\n"
            f"賭けた内容：`{target_raw}` ({money(bet)})\n\n"
            f"🎯 出目：**{color_emoji} {landed_number}**\n\n"
            f"{result_text}\n"
            f"収支：**{money_change(profit)}**\n"
            f"残高：**{money(new_balance)}**"
        ),
        color=color,
    )
    
    if files:
        embed.set_image(url="attachment://roulette_result.png")

    await message.edit(content=None, embed=embed, attachments=files if files else [], view=None)

    record_coin({
        "type": "roulette",
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "guild_id": ctx.guild.id if ctx.guild else None,
        "user_id": ctx.author.id,
        "username": str(ctx.author),
        "bet": bet,
        "target": target_raw,
        "landed": f"{color_emoji}{landed_number}",
        "won": won,
        "payout": payout,
        "profit": profit,
        "balance": new_balance,
    })

    if ctx.guild is not None:
        await send_coin_log(
            ctx.guild,
            discord.Embed(
                title="🎰 ルーレットログ",
                description=(
                    f"ユーザー：{ctx.author.mention} (`{ctx.author.id}`)\n"
                    f"賭け金：**{money(bet)}** | 賭け先：`{target_raw}`\n"
                    f"結果：{color_emoji} **{landed_number}** ({'当たり' if won else 'ハズレ'})\n"
                    f"配当：**{money(payout)}** | 収支：**{money_change(profit)}**\n"
                    f"残高：**{money(new_balance)}**"
                ),
                color=color,
            ),
        )


# 3. ルーレットコマンド本体（ベット確認画面 ＋ チップ配置画像表示）
@bot.command(name="roulette", aliases=["r", "ルーレット"])
async def roulette_command(ctx, bet_text: str = None, target: str = None):
    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。", mention_author=False)
        return

    if bet_text is None or target is None:
        await ctx.reply(
            "【ルーレットの使い方】\n"
            "`.r <賭け金> <賭ける対象>`\n\n"
            "**賭け方の種類:**\n"
            "・数字（0〜36）: 例 `.r 100 7` （配当 36倍）\n"
            "・色（red / black / 赤 / 黒）: 例 `.r 100 red` （配当 2倍）\n"
            "・奇数/偶数（odd / even / 奇数 / 偶数）: 例 `.r 100 even` （配当 2倍）",
            mention_author=False,
        )
        return

    bet = resolve_bet(ctx.author.id, bet_text)
    if bet is None or bet <= 0:
        await ctx.reply("賭け金は正の数字か `all` で指定してね。", mention_author=False)
        return

    settings = get_server_settings(ctx.guild.id)
    bet_limits = settings.get("bet_limits", {})
    roulette_limit = bet_limits.get("roulette", {"min": 0, "max": "inf"})
    
    min_bet = roulette_limit.get("min", 0)
    max_bet = roulette_limit.get("max", "inf")

    if bet < min_bet:
        await ctx.reply(f"ルーレットの最低賭け金は **{money(min_bet)}** だよ。", mention_author=False)
        return

    if max_bet != "inf" and bet > max_bet:
        max_str = money(max_bet)
        await ctx.reply(f"ルーレットの最高賭け金は **{max_str}** までだよ。", mention_author=False)
        return

    current_balance = get_balance(ctx.author.id)
    if bet > current_balance:
        await ctx.reply(f"残高が足りないよ！\n残高：**{money(current_balance)}**", mention_author=False)
        return

    target_clean = target.strip().lower()
    valid_target = False
    if target_clean.isdigit() and 0 <= int(target_clean) <= 36:
        valid_target = True
    elif target_clean in ["red", "black", "赤", "黒", "odd", "even", "奇数", "偶数", "1 to 18", "19 to 36", "1 to 12", "13 to 24", "25 to 36"]:
        valid_target = True

    if not valid_target:
        await ctx.reply("賭ける対象が正しくないよ。（数字: 0-36, 色: red/black, 奇偶: odd/even など）", mention_author=False)
        return

    # 🎡 自分が賭けた位置にチップが置かれたボード画像を生成
    board_image_path = generate_roulette_table_image(target_clean)
    files = []
    if board_image_path and os.path.exists(board_image_path):
        files.append(discord.File(board_image_path, filename="roulette_confirm.png"))

    embed = discord.Embed(
        title="🎡 ルーレット ベット確認",
        description=(
            f"プレイヤー：{ctx.author.mention}\n"
            f"賭け金：**{money(bet)}**\n"
            f"賭け先：`{target}`\n\n"
            "内容とチップの位置を確認して下のボタンを押してね！"
        ),
        color=discord.Color.blurple()
    )
    
    if files:
        embed.set_image(url="attachment://roulette_confirm.png")

    view = RouletteConfirmView(ctx, bet, target_clean, target)
    msg = await ctx.reply(embed=embed, files=files if files else [], view=view, mention_author=False)
    view.message = msg



# ==================================================
# 交換リクエスト・仲介システム
# ==================================================

EXCHANGE_MEDIATOR_ROLE_NAME = "仲介"
EXCHANGE_CATEGORY_ID = 1556346079883296850
EXCHANGE_REQUESTS_FILE = Path("exchange_requests.json")
exchange_requests = load_json(EXCHANGE_REQUESTS_FILE, {})
if not isinstance(exchange_requests, dict):
    exchange_requests = {}

EXCHANGE_TYPES = [
    ("ゲーム内アイテム交換", "ゲーム内アイテムの交換"),
    ("キャラクター交換", "キャラクター・スキンなどの交換"),
    ("コイン交換", "Bot内コインの交換"),
    ("その他", "上記以外の交換・依頼"),
]

def save_exchange_requests():
    save_json(EXCHANGE_REQUESTS_FILE, exchange_requests)

def is_exchange_mediator(member):
    return (
        isinstance(member, discord.Member)
        and any(role.name == EXCHANGE_MEDIATOR_ROLE_NAME for role in member.roles)
    )

def get_exchange_request(request_id):
    return exchange_requests.get(str(request_id))

def make_exchange_embed(request_id, data):
    status = data.get("status", "pending")
    status_text = {
        "pending": "🕒 承認待ち",
        "approved": "✅ 承認済み",
        "rejected": "❌ 却下",
        "error": "⚠️ チャンネル作成エラー",
    }.get(status, status)
    embed = discord.Embed(
        title=f"交換リクエスト #{request_id}",
        color=discord.Color.orange() if status == "pending" else (
            discord.Color.green() if status == "approved" else discord.Color.red()
        ),
    )
    embed.add_field(name="申請者", value=f"<@{data['requester_id']}>", inline=True)
    embed.add_field(name="種類", value=data.get("type", "未設定"), inline=True)
    embed.add_field(name="状態", value=status_text, inline=True)
    embed.add_field(name="内容", value=data.get("details", "なし")[:1000], inline=False)
    if data.get("mediator_id"):
        embed.add_field(name="担当仲介者", value=f"<@{data['mediator_id']}>", inline=True)
    if data.get("partner_id"):
        embed.add_field(name="交換相手", value=f"<@{data['partner_id']}>", inline=True)
    if data.get("channel_id"):
        embed.add_field(name="専用チャンネル", value=f"<#{data['channel_id']}>", inline=False)
    return embed

async def update_exchange_approval_message(guild, request_id):
    data = get_exchange_request(request_id)
    if not data:
        return
    channel = guild.get_channel(int(data.get("approval_channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(int(data.get("approval_message_id", 0)))
        view = ExchangeApprovalView(request_id) if data.get("status") == "pending" else None
        await message.edit(embed=make_exchange_embed(request_id, data), view=view)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        print(f"[EXCHANGE] 承認メッセージ更新失敗: {request_id}")

class ExchangeDetailsModal(discord.ui.Modal):
    def __init__(self, exchange_type, partner_id):
        super().__init__(title="交換リクエスト内容を入力")
        self.exchange_type = exchange_type
        self.partner_id = int(partner_id)
        self.details = discord.ui.TextInput(
            label="交換したい内容・条件",
            placeholder="例：アイテムAとアイテムBを交換したい",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
        )
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        partner = interaction.guild.get_member(self.partner_id)
        if partner is None:
            try:
                partner = await interaction.guild.fetch_member(self.partner_id)
            except (discord.NotFound, discord.HTTPException):
                partner = None

        if partner is None or partner.bot or partner.id == interaction.user.id:
            await interaction.response.send_message(
                "選択した交換相手が見つからないか、自分自身が選ばれているよ。もう一度やり直してね。",
                ephemeral=True,
            )
            return

        request_id = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        while request_id in exchange_requests:
            request_id = str(int(request_id) + 1)

        data = {
            "requester_id": interaction.user.id,
            "partner_id": partner.id,
            "type": self.exchange_type,
            "details": str(self.details.value).strip(),
            "status": "pending",
            "guild_id": interaction.guild.id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        exchange_requests[request_id] = data
        save_exchange_requests()

        try:
            category = interaction.guild.get_channel(EXCHANGE_CATEGORY_ID)
            if not isinstance(category, discord.CategoryChannel):
                raise RuntimeError(f"交換用カテゴリが見つからないよ: {EXCHANGE_CATEGORY_ID}")

            mediator_role = discord.utils.get(
                interaction.guild.roles,
                name=EXCHANGE_MEDIATOR_ROLE_NAME,
            )
            if mediator_role is None:
                raise RuntimeError("「仲介」ロールが見つからないよ。")

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                mediator_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                ),
            }
            bot_member = interaction.guild.me
            if bot_member is not None:
                overwrites[bot_member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_channels=True,
                    manage_messages=True,
                )

            approval_channel = await interaction.guild.create_text_channel(
                name=f"request-{request_id[-8:]}",
                category=category,
                overwrites=overwrites,
                topic=f"交換リクエスト #{request_id} | 承認待ち",
                reason=f"交換リクエスト #{request_id} の承認用チャンネル",
            )
            data["approval_channel_id"] = approval_channel.id
            message = await approval_channel.send(
                content="📨 **新しい交換リクエストが届いたよ！「仲介」ロールの人は内容を確認してね。**",
                embed=make_exchange_embed(request_id, data),
                view=ExchangeApprovalView(request_id),
            )
            data["approval_message_id"] = message.id
            save_exchange_requests()
            await interaction.response.send_message(
                f"リクエストを送信したよ！受付番号：**#{request_id}**\n"
                f"交換相手：{partner.mention}\n"
                "仲介担当が確認中だよ。承認されたら2人がこのチャンネルを見られるようになるよ。",
                ephemeral=True,
            )
        except (discord.Forbidden, discord.HTTPException, RuntimeError) as error:
            data["status"] = "error"
            save_exchange_requests()
            print(f"[EXCHANGE APPROVAL CHANNEL ERROR] {error}")
            await interaction.response.send_message(
                "承認用チャンネルを作れなかったよ。カテゴリID・「仲介」ロール・Botのチャンネル管理権限を確認してね。",
                ephemeral=True,
            )


class ExchangeTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, description=description, value=label)
            for label, description in EXCHANGE_TYPES
        ]
        super().__init__(
            placeholder="どんなリクエストか選んでね",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="exchange:type_select",
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.exchange_type = self.values[0]
        await interaction.response.defer()


class ExchangePartnerSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="交換相手を選んでね",
            min_values=1,
            max_values=1,
            custom_id="exchange:partner_select",
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if selected.bot:
            await interaction.response.send_message("Botは交換相手に指定できないよ。", ephemeral=True)
            return
        if selected.id == interaction.user.id:
            await interaction.response.send_message("自分自身は交換相手に指定できないよ。", ephemeral=True)
            return
        self.view.partner_id = selected.id
        await interaction.response.defer()


class ExchangeTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.exchange_type = None
        self.partner_id = None
        self.add_item(ExchangeTypeSelect())
        self.add_item(ExchangePartnerSelect())

    @discord.ui.button(
        label="次へ：内容を入力",
        style=discord.ButtonStyle.success,
        custom_id="exchange:continue_request",
    )
    async def continue_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.exchange_type is None:
            await interaction.response.send_message("リクエストの種類を選んでね。", ephemeral=True)
            return
        if self.partner_id is None:
            await interaction.response.send_message("交換相手を選んでね。", ephemeral=True)
            return
        await interaction.response.send_modal(
            ExchangeDetailsModal(self.exchange_type, self.partner_id)
        )


class ExchangePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="交換をリクエストする",
        style=discord.ButtonStyle.primary,
        emoji="🤝",
        custom_id="exchange:open_request",
    )
    async def open_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        await interaction.response.send_message(
            "① リクエストの種類を選択\n② 交換相手をメンバー一覧から選択\n③「次へ」を押して内容を入力してね。",
            view=ExchangeTypeView(),
            ephemeral=True,
        )


async def create_exchange_channel(interaction: discord.Interaction, request_id: str):
    data = get_exchange_request(request_id)
    if not data or data.get("status") != "pending":
        await interaction.followup.send("このリクエストは既に処理済みだよ。", ephemeral=True)
        return
    if interaction.guild is None or not is_exchange_mediator(interaction.user):
        await interaction.followup.send("「仲介」ロールを持つ人だけ承認できるよ。", ephemeral=True)
        return

    requester_id = int(data["requester_id"])
    partner_id = int(data["partner_id"])
    if partner_id == requester_id:
        await interaction.followup.send("交換相手の指定が正しくないため、処理できないよ。", ephemeral=True)
        return

    requester = interaction.guild.get_member(requester_id)
    partner = interaction.guild.get_member(partner_id)
    if requester is None:
        try:
            requester = await interaction.guild.fetch_member(requester_id)
        except (discord.NotFound, discord.HTTPException):
            requester = None
    if partner is None:
        try:
            partner = await interaction.guild.fetch_member(partner_id)
        except (discord.NotFound, discord.HTTPException):
            partner = None

    if requester is None or partner is None or partner.bot:
        await interaction.followup.send(
            "申請者または交換相手がサーバー内にいないため、承認できないよ。",
            ephemeral=True,
        )
        return

    approval_channel = interaction.guild.get_channel(int(data.get("approval_channel_id", 0)))
    if not isinstance(approval_channel, discord.TextChannel):
        await interaction.followup.send("承認用チャンネルが見つからないよ。", ephemeral=True)
        return

    try:
        await approval_channel.set_permissions(
            requester,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        )
        await approval_channel.set_permissions(
            partner,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        )

        # 承認後は「仲介」ロール全員ではなく、承認した仲介者1人だけ残す
        mediator_role = discord.utils.get(
            interaction.guild.roles,
            name=EXCHANGE_MEDIATOR_ROLE_NAME,
        )
        if mediator_role is not None:
            await approval_channel.set_permissions(
                mediator_role,
                view_channel=False,
                send_messages=False,
                read_message_history=False,
            )
        await approval_channel.set_permissions(
            interaction.user,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
        )

        data["status"] = "approved"
        data["mediator_id"] = interaction.user.id
        data["channel_id"] = approval_channel.id
        save_exchange_requests()

        close_message = await approval_channel.send(
            f"🎉 **この交換リクエストは承認されたよ！**\n"
            f"**受け入れた仲介者：** {interaction.user.mention}\n"
            f"**交換する2人：** {requester.mention}・{partner.mention}\n\n"
            "これからは申請者・交換相手・担当仲介者がこのチャンネルを使えるよ。",
            view=ExchangeCloseView(request_id),
        )
        data["close_message_id"] = close_message.id
        save_exchange_requests()
        await update_exchange_approval_message(interaction.guild, request_id)
        await interaction.followup.send(
            f"承認完了！{requester.mention} と {partner.mention} が {approval_channel.mention} を見られるようになったよ。",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "権限を変更できなかったよ。Botに「チャンネルの管理」権限があるか確認してね。",
            ephemeral=True,
        )
    except discord.HTTPException as error:
        print(f"[EXCHANGE APPROVAL ERROR] {error}")
        await interaction.followup.send("承認処理中にエラーが発生したよ。", ephemeral=True)


class ExchangeCloseView(discord.ui.View):
    def __init__(self, request_id):
        super().__init__(timeout=None)
        self.request_id = str(request_id)

    @discord.ui.button(
        label="チャンネルを閉じる（削除）",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="exchange:close_channel",
    )
    async def close_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_exchange_mediator(interaction.user):
            await interaction.response.send_message(
                "「仲介」ロールを持つ人だけがチャンネルを削除できるよ。",
                ephemeral=True,
            )
            return

        data = get_exchange_request(self.request_id)
        if not data or data.get("status") != "approved":
            await interaction.response.send_message(
                "このリクエストは承認済みではないよ。",
                ephemeral=True,
            )
            return

        if interaction.channel is None or interaction.channel.id != int(data.get("channel_id", 0)):
            await interaction.response.send_message(
                "このボタンは対象の交換チャンネルでは使えないよ。",
                ephemeral=True,
            )
            return

        channel = interaction.channel
        await interaction.response.send_message(
            "この交換チャンネルを削除するね。",
            ephemeral=True,
        )
        try:
            await channel.delete(reason=f"交換リクエスト #{self.request_id} を仲介ロールの操作で終了")
            data["status"] = "closed"
            data["closed_by"] = interaction.user.id
            data["closed_at"] = datetime.now(timezone.utc).isoformat()
            save_exchange_requests()
        except discord.Forbidden:
            await interaction.followup.send(
                "削除できなかったよ。Botに「チャンネルの管理」権限があるか確認してね。",
                ephemeral=True,
            )
        except discord.HTTPException as error:
            print(f"[EXCHANGE CLOSE ERROR] {error}")
            await interaction.followup.send(
                "チャンネル削除中にエラーが発生したよ。",
                ephemeral=True,
            )


class ExchangeApprovalView(discord.ui.View):
    def __init__(self, request_id):
        super().__init__(timeout=None)
        self.request_id = str(request_id)

    async def interaction_check(self, interaction: discord.Interaction):
        if not is_exchange_mediator(interaction.user):
            await interaction.response.send_message(
                "この操作は「仲介」ロールを持つ人だけ使えるよ。",
                ephemeral=True,
            )
            return False
        data = get_exchange_request(self.request_id)
        if not data or data.get("status") != "pending":
            await interaction.response.send_message("このリクエストは既に処理済みだよ。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="承認", style=discord.ButtonStyle.success, custom_id="exchange:approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_exchange_channel(interaction, self.request_id)

    @discord.ui.button(label="却下", style=discord.ButtonStyle.danger, custom_id="exchange:reject")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = get_exchange_request(self.request_id)
        data["status"] = "rejected"
        data["mediator_id"] = interaction.user.id
        save_exchange_requests()
        await interaction.response.edit_message(
            content="❌ この交換リクエストは却下されたよ。",
            embed=make_exchange_embed(self.request_id, data),
            view=None,
        )
        approval_channel = interaction.guild.get_channel(int(data.get("approval_channel_id", 0))) if interaction.guild else None
        if isinstance(approval_channel, discord.TextChannel):
            await approval_channel.send(
                f"❌ **このリクエストは却下されたよ。**\n"
                f"**却下した仲介者：** {interaction.user.mention}"
            )


async def restore_exchange_views():
    bot.add_view(ExchangePanelView())
    for request_id, data in exchange_requests.items():
        if data.get("status") == "pending" and data.get("approval_message_id"):
            try:
                bot.add_view(
                    ExchangeApprovalView(request_id),
                    message_id=int(data["approval_message_id"]),
                )
            except Exception:
                print(f"[EXCHANGE VIEW RESTORE ERROR] {request_id}")
        elif data.get("status") == "approved" and data.get("close_message_id"):
            try:
                bot.add_view(
                    ExchangeCloseView(request_id),
                    message_id=int(data["close_message_id"]),
                )
            except Exception:
                print(f"[EXCHANGE CLOSE VIEW RESTORE ERROR] {request_id}")

async def exchange_views_ready():
    if getattr(bot, "_exchange_views_registered", False):
        return
    bot._exchange_views_registered = True
    await restore_exchange_views()

bot.add_listener(exchange_views_ready, "on_ready")

@bot.command(name="exchange_panel", aliases=["交換パネル"])
@commands.has_permissions(administrator=True)
async def exchange_panel_command(ctx):
    embed = discord.Embed(
        title="🤝 交換リクエスト",
        description=(
            "交換・依頼をしたい人は下のボタンを押してね。\n"
            "種類を選び、内容を入力すると仲介担当へ申請が送られるよ。\n\n"
            "仲介担当は「仲介」ロールを持つメンバーだよ。"
        ),
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed, view=ExchangePanelView())


# /request ch で交換リクエストパネルを設置
request_group = app_commands.Group(
    name="request",
    description="リクエスト関連の操作",
)

@request_group.command(
    name="ch",
    description="このチャンネルに交換リクエストパネルを設置する",
)
@app_commands.default_permissions(administrator=True)
async def request_channel_command(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            "サーバーのテキストチャンネルで使ってね。",
            ephemeral=True,
        )
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "このコマンドはサーバー管理者だけが使えるよ。",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="🤝 交換リクエスト",
        description=(
            "交換・依頼をしたい人は下のボタンを押してね。\n"
            "種類を選び、内容を入力すると仲介担当へ申請が送られるよ。\n\n"
            "仲介担当は「仲介」ロールを持つメンバーだよ。"
        ),
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(
        "このチャンネルに交換リクエストパネルを設置したよ！",
        ephemeral=True,
    )
    await interaction.channel.send(embed=embed, view=ExchangePanelView())


bot.tree.add_command(request_group)


# ==================================================
# /welcome log 入退出ログ設定
# ==================================================

welcome_group = app_commands.Group(
    name="welcome",
    description="参加・退出ログの設定",
)


@welcome_group.command(
    name="log",
    description="このチャンネルをメンバー参加・退出ログの送信先に設定する",
)
@app_commands.describe(channel="ログを送信するチャンネル（省略すると現在のチャンネル）")
@app_commands.default_permissions(administrator=True)
async def welcome_log_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "このコマンドはサーバー内で使ってね。",
            ephemeral=True,
        )
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "この設定はサーバー管理者だけが使えるよ。",
            ephemeral=True,
        )
        return

    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        await interaction.response.send_message(
            "ログ送信先にはテキストチャンネルを指定してね。",
            ephemeral=True,
        )
        return

    bot_member = interaction.guild.me
    if bot_member is None:
        await interaction.response.send_message(
            "Botのメンバー情報を取得できなかったよ。",
            ephemeral=True,
        )
        return

    permissions = target.permissions_for(bot_member)
    if not permissions.view_channel or not permissions.send_messages or not permissions.embed_links:
        await interaction.response.send_message(
            "Botにこのチャンネルの「チャンネルを見る」「メッセージを送信」「埋め込みリンク」の権限が必要だよ。",
            ephemeral=True,
        )
        return

    welcome_log_configs[str(interaction.guild.id)] = target.id
    save_json(WELCOME_LOG_FILE, welcome_log_configs)

    embed = discord.Embed(
        title="✅ 入退出ログを設定したよ！",
        description=(
            f"送信先：{target.mention}\n\n"
            "🟩 **参加ログ：緑色の埋め込み**\n"
            "🟥 **退出ログ：赤色の埋め込み**\n\n"
            "これからメンバーが参加・退出すると、自動でここに記録するよ。"
        ),
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(welcome_group)


@bot.event
async def on_member_join(member: discord.Member):
    channel_id = welcome_log_configs.get(str(member.guild.id))
    if not channel_id:
        return

    channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            print(f"[WELCOME LOG] 参加ログ送信先を取得できません: {channel_id}")
            return

    if not isinstance(channel, discord.TextChannel):
        return

    created_at = member.created_at.astimezone(JST).strftime("%Y/%m/%d %H:%M:%S")
    joined_at = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
    member_count = member.guild.member_count or "不明"

    embed = discord.Embed(
        title="📥 メンバー参加",
        description=f"{member.mention} がサーバーに参加しました！",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ユーザー名", value=f"{member}（{member.name}）", inline=True)
    embed.add_field(name="ユーザーID", value=f"`{member.id}`", inline=True)
    embed.add_field(name="アカウント作成日時", value=created_at, inline=False)
    embed.add_field(name="参加日時", value=joined_at, inline=False)
    embed.add_field(name="現在のメンバー数", value=str(member_count), inline=True)
    embed.set_footer(text=f"JOIN • {member.guild.name}")

    try:
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"[WELCOME LOG JOIN ERROR] {error}")


@bot.event
async def on_member_remove(member: discord.Member):
    channel_id = welcome_log_configs.get(str(member.guild.id))
    if not channel_id:
        return

    channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            print(f"[WELCOME LOG] 退出ログ送信先を取得できません: {channel_id}")
            return

    if not isinstance(channel, discord.TextChannel):
        return

    created_at = member.created_at.astimezone(JST).strftime("%Y/%m/%d %H:%M:%S")
    left_at = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
    member_count = member.guild.member_count or "不明"

    embed = discord.Embed(
        title="📤 メンバー退出",
        description=f"**{discord.utils.escape_markdown(str(member))}** がサーバーを退出しました。",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ユーザー名", value=f"{member}（{member.name}）", inline=True)
    embed.add_field(name="ユーザーID", value=f"`{member.id}`", inline=True)
    embed.add_field(name="アカウント作成日時", value=created_at, inline=False)
    embed.add_field(name="退出日時", value=left_at, inline=False)
    embed.add_field(name="退出後のメンバー数", value=str(member_count), inline=True)
    embed.set_footer(text=f"LEAVE • {member.guild.name}")

    try:
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"[WELCOME LOG LEAVE ERROR] {error}")


# ==================================================
# /servers Botの参加サーバー数（オーナー専用）
# ==================================================

@bot.tree.command(
    name="servers",
    description="Botが現在参加しているサーバー数を表示する",
)
async def servers_command(interaction: discord.Interaction):
    if not await require_owner(interaction):
        return

    embed = discord.Embed(
        title="🤖 Bot サーバー情報",
        description=f"現在参加しているサーバー数：\n## {len(bot.guilds):,} サーバー",
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="コマンド実行時点の最新情報")

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ==================================================
# 景品配布機能
# ==================================================
from giveaway_feature import setup_giveaway
from race_feature import setup_race

setup_giveaway(bot, get_balance, set_balance, send_coin_log)
setup_race(bot, get_balance, set_balance, money)


# ==================================================
# 起動
# ==================================================

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。")

    Thread(target=run_web, daemon=True).start()
    bot.run(TOKEN)
