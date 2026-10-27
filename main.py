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

DAILY_REWARD = 1000
DAILY_STREAK_BONUS = 100
JST = timezone(timedelta(hours=9))

SYMBOLS = ["🍒", "🍋", "⭐", "🔔", "7️⃣", "💣"]  # 💣を追加


PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐": 10,
    "7️⃣": 50,
    "💣": 20,  # ← 💣の配当倍率を追加
}


CUSTOM_EMOJI_NAMES = {
    "⭐": "emoji_12",
    "🍋": "emoji_13",
    "🔔": "emoji_14",
    "🍒": "emoji_15",
    "7️⃣": "emoji_16",
    "💣": "emoji_19",  # ← カスタム絵文字名を追加
}


LANE_PATTERNS = [
    ["🍒", "🍋", "💣", "🔔", "7️⃣", "⭐️"],
    ["⭐", "🍒", "💣", "🍋", "🔔", "7️⃣"],
    ["💣", "7️⃣", "🍋", "⭐", "🍒", "🔔"],
]


DEFAULT_WEIGHTS = {
    "🍒": 20,
    "🍋": 20,
    "⭐": 20,
    "🔔": 20,
    "7️⃣": 20,
    "💣": 20,  # ← 出現比率を追加（合計が気になる場合は他の数値を調整してもOKです）
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

DAILY_LOCK = asyncio.Lock()
GUESS_LOCKS = {}
AUTO_COIN_RECOVERY_DONE = False

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
        emoji_name = CUSTOM_EMOJI_NAMES[symbol]
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
    # 1: 真ん中（横1本）
    if line_choice >= 1:
        paylines.append([grid[1][0], grid[1][1], grid[1][2]])
        
    # 2: 上・中・下（横3本）
    if line_choice >= 2:
        paylines.append([grid[0][0], grid[0][1], grid[0][2]]) # 上段
        paylines.append([grid[2][0], grid[2][1], grid[2][2]]) # 下段
        
    # 3: 上・中・下 ＋ 斜め2本（計5本）
    if line_choice >= 3:
        paylines.append([grid[0][0], grid[1][1], grid[2][2]]) # 斜め（左上→右下）
        paylines.append([grid[2][0], grid[1][1], grid[0][2]]) # 斜め（左下→右上）
        
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

    # 再起動後、保存されているゲームの状態に合わせて権限を復旧
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

        if channel.guild.id != guild.id:
            print("[LOG ERROR] 固定ログチャンネルが実行サーバーと異なります。")
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
        print("[COIN LOG] 固定ログチャンネルを取得できず、送信できませんでした。")
        return

    try:
        await channel.send(embed=embed)
        print(f"[COIN LOG] 送信成功: channel={channel.id}")
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
    """@everyone の送信権限を切り替える。他の権限設定は維持する。"""
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

# ==================================================
# 修正済み：正解したメッセージにだけ🎉を付ける
# ==================================================

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
        # ロック取得後にゲーム状態を再確認する
        game = guess_data.get(guild_key)

        if not game or not game.get("active", False):
            return

        content = message.content.strip()
        answer = str(game.get("answer", ""))

        # 正解判定
        if game.get("mode") == "number":
            try:
                correct = int(content) == int(answer)
            except (TypeError, ValueError):
                correct = False
        else:
            correct = content.casefold() == answer.casefold()

        # 不正解ならリアクションも報酬処理も行わない
        if not correct:
            return

        # 正解メッセージにだけ🎉を付ける
        try:
            await message.add_reaction("🎉")
        except (discord.Forbidden, discord.HTTPException):
            print("[GUESS] 正解メッセージへのリアクションに失敗しました。")

        # 二重当選を防ぐため、先に終了状態を保存する
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
            f"Botに「チャンネルの管理」権限があるか確認してね。\n`{error}`",
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

@bot.command(name="mdaily")
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
            await channel.send(
                f"ログインボーナス\n"
                f"やった人：{ctx.author.mention}\n"
                f"増やした金額：{money_change(reward)}\n"
                f"何日目か：{streak}日目"
            )
        except Exception:
            print("[DAILY LOG SEND ERROR]")
            traceback.print_exc()

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
    minimum = int(settings.get("min_bet", 1))

    if bet < minimum:
        await ctx.reply(f"最低賭け金は {money(minimum)} だよ。", mention_author=False)
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
    """サーバーのカスタム絵文字があれば使い、なければ通常絵文字を使う。"""
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
            placeholder="再抽選する色を選んでね",
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
        """4個のサイコロを振り、各サイコロの色を返す。"""
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
            # 再抽選でも2〜3個なら負け
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

        # タイムアウト時も賭け金は返さない
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

    # 賭け金はゲーム開始時に一度だけ引く
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
        # 初回で決着した場合も、残高には徴収後の金額が入っている
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

        # 初回の徴収分を含む現在残高を基準に、配当を反映
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

    # 2〜3個の場合、同じゲーム内で再抽選用の色選択を出す
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
        # ゲーム表示に失敗した場合は賭け金を返す
        latest_balance = get_balance(ctx.author.id)
        set_balance(ctx.author.id, latest_balance + bet)
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
# .slot スロット
# ==================================================

@bot.command(name="slot")
async def slot_command(ctx, bet_text: str, lines_text: str = "1"):
    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。", mention_author=False)
        return

    settings = get_server_settings(ctx.guild.id)
    allowed, reason = can_use_slot(ctx.author, settings)

    if not allowed:
        await ctx.reply(reason, mention_author=False)
        return

    # 1ラインあたりの賭け金
    base_bet = resolve_bet(ctx.author.id, bet_text)
    if base_bet is None:
        await ctx.reply("賭け金は数字か `all` で指定してね。\n例：`.slot 100 3`", mention_author=False)
        return

    # ライン数の指定 (1, 2, 3)
    try:
        line_choice = int(lines_text)
        if line_choice not in (1, 2, 3):
            raise ValueError
    except ValueError:
        await ctx.reply("ライン数は `1`（真ん中）、`2`（上下中）、`3`（上下中＋斜め）のいずれかで指定してね。\n例：`.slot 100 2`", mention_author=False)
        return

    # ライン数に応じた総賭け金の倍率（1→1倍, 2→3倍, 3→5倍）
    line_multipliers = {1: 1, 2: 3, 3: 5}
    active_lines_count = line_multipliers[line_choice]
    total_bet = base_bet * active_lines_count

    if total_bet <= 0:
        await ctx.reply("賭け金に使える残高がないよ。", mention_author=False)
        return

    minimum = int(settings.get("min_bet", 1))
    if base_bet < minimum:
        await ctx.reply(f"1ラインあたりの最低賭け金は **{money(minimum)}** だよ。", mention_author=False)
        return

    current_balance = get_balance(ctx.author.id)
    if total_bet > current_balance:
        await ctx.reply(f"残高が足りないよ！\n必要額（総額）：**{money(total_bet)}**\n残高：**{money(current_balance)}**", mention_author=False)
        return

    positions = [random.randrange(len(LANE_PATTERNS[index])) for index in range(3)]
    slot_positions[str(ctx.author.id)] = positions
    save_json(POSITIONS_FILE, slot_positions)

    weights = settings.get("weights", DEFAULT_WEIGHTS)
    grid = make_grid(positions, weights)
    
    # 選択されたライン数に応じて有効なラインを取得
    paylines = get_paylines(grid, line_choice)

    winning_symbol = None
    multiplier = 0
    total_payout = 0

    # すべての有効ラインをチェックして当たりの配当を合算
    for line in paylines:
        if line[0] == line[1] == line[2]:
            sym = line[0]
            mult = PAYOUTS.get(sym, 0)
            total_payout += base_bet * mult
            winning_symbol = sym # ログ用

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

    # 賭け金と獲得額をそれぞれ3桁の文字列に変換
    bet_money_str = f"{total_bet:03d}"
    won_money_str = f"{total_payout:03d}"

    # それぞれ1桁ずつに分解して個別の絵文字に変換
    b1 = number_emoji(bet_money_str[0])
    b2 = number_emoji(bet_money_str[1])
    b3 = number_emoji(bet_money_str[2])

    w1 = number_emoji(won_money_str[0])
    w2 = number_emoji(won_money_str[1])
    w3 = number_emoji(won_money_str[2])

    # 左右のプレート絵文字の定義
    left_top = "<:emoji_20:1564565447448199220>"
    left_mid = "<:emoji_22:1564567674162516089>"
    left_bot = "<:emoji_20:1564565432327741440>"

    right_top = "<:emoji_21:1564565471817244832>"
    right_mid = "<:emoji_22:1564567647927017522>"
    right_bot = "<:emoji_22:1564565484307877988>"

    # BET行・WON行用のパーツ
    bet_label_emoji = "<:emoji_24:1564584196926611516>"
    won_label_emoji = "<:emoji_27:1564590865165328455>"
    gray_emoji = "<:emoji_25:1564584610820657203>"

    # 【構成】
    # 1. 出目（3行）
    # 2. BET行（BET絵文字 ＋ 数字3つ ＋ 灰色絵文字 ※数字間の線なし）
    # 3. WON行（WON絵文字 ＋ 数字3つ ＋ 灰色絵文字 ※数字間の線なし）
    slot_display = (
        f"{left_top} {'|'.join(displayed_rows[0])} {right_top}\n"
        f"{left_mid} {'|'.join(displayed_rows[1])} {right_mid}\n"
        f"{left_bot} {'|'.join(displayed_rows[2])} {right_bot}\n"
        f"{bet_label_emoji} {b1}{b2}{b3} {gray_emoji}\n"
        f"{won_label_emoji} {w1}{w2}{w3} {gray_emoji}\n"
        f"まわしたひと：{ctx.author.mention}"
    )


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
# .Payment 残高の増減
# ==================================================

@bot.command(name="Payment", aliases=["pay", "送金"])
async def payment_command(ctx, member: discord.Member, amount: int):
    if not is_owner_user(ctx.author):
        await ctx.reply("このコマンドを使えるのは指定されたオーナー本人だけだよ。", mention_author=False)
        return

    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。", mention_author=False)
        return

    if member.bot:
        await ctx.reply("Botには送金できないよ。", mention_author=False)
        return

    if amount == 0:
        await ctx.reply("金額は0以外にしてね。", mention_author=False)
        return

    before = get_balance(member.id)
    after = before + amount
    set_balance(member.id, after)

    embed = discord.Embed(
        title="💸 Payment",
        description=(
            f"対象：{member.mention}\n変更額：**{money_change(amount)}**\n"
            f"変更前：**{money(before)}**\n変更後：**{money(after)}**\n"
            f"実行者：{ctx.author.mention}"
        ),
        color=discord.Color.blurple(),
    )
    await ctx.reply(embed=embed, mention_author=False)

    record_coin({
        "type": "payment",
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "guild_id": ctx.guild.id,
        "user_id": member.id,
        "username": str(member),
        "actor_id": ctx.author.id,
        "actor_name": str(ctx.author),
        "amount": amount,
        "before": before,
        "after": after,
    })

    await send_coin_log(
        ctx.guild,
        discord.Embed(
            title="💸 Paymentログ",
            description=(
                f"対象：{member.mention} (`{member.id}`)\n"
                f"実行者：{ctx.author.mention} (`{ctx.author.id}`)\n"
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
            "`.color 賭け金` — 🌝🌚の2択ゲーム\n"
            "`.color all` — 所持金を全額賭ける\n"
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
            "* 7️⃣ ＝ **50倍**\n\n"
            f"※1ラインあたりの最低賭け金：**{money(minimum)}**\n"
            "※所持金を全額賭けたいときは、数字の代わりに `all` が使えるよ！"
        ),
        color=discord.Color.gold(),
    )
    await ctx.reply(embed=embed, mention_author=False)

# ==================================================
# /setting モーダル
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
        if not await require_owner(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        try:
            amount = int(str(self.amount_input.value).strip())
        except ValueError:
            await interaction.response.send_message("整数で入力してね。", ephemeral=True)
            return

        if amount < 1:
            await interaction.response.send_message("最低賭け金は1以上にしてね。", ephemeral=True)
            return

        settings = get_server_settings(interaction.guild.id)
        settings["min_bet"] = amount
        save_server_settings(interaction.guild.id)

        await interaction.response.send_message(
            f"最低賭け金を **{money(amount)}** に設定したよ。",
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
                "例：`🍒=20,🍋=20,⭐=20,🔔=20,7️⃣=20`\n"
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

# ==================================================
# 出目の絵文字タイプ設定
# ==================================================

class EmojiModeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="表示する絵文字タイプを選択",
            min_values=1,
            max_values=1,
            options=[
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
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        selected_mode = self.values[0]
        settings = get_server_settings(interaction.guild.id)
        settings["emoji_mode"] = selected_mode
        save_server_settings(interaction.guild.id)

        if selected_mode == "custom":
            _, missing = get_custom_emoji_status(interaction.guild)
            if missing:
                await interaction.response.send_message(
                    "カスタム絵文字モードに変更したよ。\n\n"
                    "見つからない絵文字は通常の絵文字で表示するよ。\n"
                    + "\n".join(missing),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "出目の表示を **サーバーのカスタム絵文字** に変更したよ。",
                    ephemeral=True,
                )
        else:
            await interaction.response.send_message(
                "出目の表示を **通常の絵文字** に変更したよ。",
                ephemeral=True,
            )

class EmojiModeSettingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(EmojiModeSelect())

# ==================================================
# /setting 選択メニュー
# ==================================================

class SettingActionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="最低賭け金", description="最低賭け金を変更", value="min_bet", emoji="🪙"),
            discord.SelectOption(label="絵柄・出現確率", description="絵柄ごとの比率を変更", value="weights", emoji="🎰"),
            discord.SelectOption(label="出目の絵文字タイプ", description="絵文字の種類を切り替え", value="emoji_mode", emoji="🎨"),
            discord.SelectOption(label="ログ送信先", description="固定ログ送信先を確認", value="log_channel", emoji="📝"),
            discord.SelectOption(label="コマンド使用権限", description="スロットの利用権限を変更", value="permissions", emoji="🔐"),
            discord.SelectOption(label="メンテナンスモード", description="一般メンバーのスロットを停止・再開", value="maintenance", emoji="🛠️"),
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
            await interaction.response.send_modal(BetSettingModal("min_bet"))
        elif selected == "weights":
            await interaction.response.send_modal(WeightsSettingModal(settings["weights"]))
        elif selected == "emoji_mode":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="出目の絵文字タイプ",
                    description=(
                        "スロット盤面に表示する絵文字を選択してね。\n\n"
                        "**通常の絵文字**\n🍒 🍋 ⭐ 🔔 7️⃣\n\n"
                        "**サーバーのカスタム絵文字**\nemoji_12〜emoji_16"
                    ),
                    color=discord.Color.blurple(),
                ),
                view=EmojiModeSettingView(),
                ephemeral=True,
            )
        elif selected == "log_channel":
            await interaction.response.send_message(
                f"ログ送信先は固定されているよ。\n<#{LOG_CHANNEL_ID}>",
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
        super().__init__(
            placeholder="利用できるメンバーを選択",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="全メンバー", description="全員が使える", value="everyone", emoji="👥"),
                discord.SelectOption(label="ownerロール以上", description="ownerロールまたは管理者", value="owner", emoji="👑"),
                discord.SelectOption(label="管理者のみ", description="サーバー管理者のみ", value="admin", emoji="🔐"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
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
    log_channel = bot.get_channel(LOG_CHANNEL_ID)

    permission_labels = {
        "everyone": "全メンバー",
        "owner": "ownerロール以上",
        "admin": "管理者のみ",
    }

    embed = discord.Embed(
        title="Bot設定パネル",
        description="下のメニューから変更したい設定を選んでね。",
        color=discord.Color.blurple(),
    )

    embed.add_field(name="最低賭け金", value=money(int(settings["min_bet"])), inline=True)
    embed.add_field(
        name="スロット使用権限",
        value=permission_labels.get(settings.get("slot_permission", "everyone"), "全メンバー"),
        inline=True,
    )
    embed.add_field(name="メンテナンス", value="ON" if settings.get("maintenance", False) else "OFF", inline=True)
    embed.add_field(
        name="ログ送信先（固定）",
        value=log_channel.mention if log_channel else f"チャンネルID: {LOG_CHANNEL_ID}",
        inline=True,
    )
    embed.add_field(name="出目の絵文字タイプ", value=get_display_mode_name(settings), inline=True)
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

# ==================================================
# 起動
# ==================================================

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。")

    Thread(target=run_web, daemon=True).start()
    bot.run(TOKEN)