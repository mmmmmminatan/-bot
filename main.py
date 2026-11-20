import asyncio
import json
import math
import os
import random
import re
import traceback
import inspect
from pathlib import Path
from threading import Thread
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
import psycopg2


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

# 「あう」を検知（空白や記号を挟んでもOK）
pattern = re.compile(r"あう")

# あう検知メッセージ（黄色：未完了／緑色：完了）
def format_au_charge(amount):
    """万円単位の請求額を、日本語の億・万表記に整える。"""
    amount = int(amount)
    oku, man = divmod(amount, 10000)
    if oku and man:
        return f"{oku:,}億{man:,}万円"
    if oku:
        return f"{oku:,}億円"
    return f"{man:,}万円"


def make_au_message(user, amount, completed=False, charge_stats=None):
    if completed:
        embed = discord.Embed(
            title="✅ お支払い完了",
            description="お支払いが完了いたしました。\n※実際の請求・決済は発生していません。",
            color=discord.Color.green(),
        )
    else:
        description = (
            f"当サーバーの利用規約に違反しているため、{user.mention}に"
            f"**{format_au_charge(amount)}**の請求が届いてます。\n"
            "直ちに下のボタンからお支払いください。"
        )
        if charge_stats:
            description += (
                "\n\n📊 **請求額記録**"
                f"\n最高額：**{format_au_charge(charge_stats['max'])}**"
                f"\n最低額：**{format_au_charge(charge_stats['min'])}**"
            )
        embed = discord.Embed(
            title="⚠️ あうを検知しました ⚠️",
            description=description,
            color=discord.Color.gold(),
        )

    return embed


class AuPaymentView(discord.ui.View):
    def __init__(self, guild_id, target_user_id, amount):
        super().__init__(timeout=300)
        self.guild_id = int(guild_id)
        self.target_user_id = int(target_user_id)
        self.amount = int(amount)
        self.paid = False

    @discord.ui.button(
        label="お支払い",
        style=discord.ButtonStyle.danger,
        emoji="💳",
    )
    async def pay_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message(
                "❌ このボタンは請求対象の本人だけが押せます。",
                ephemeral=True,
            )
            return

        if self.paid:
            await interaction.response.send_message(
                "この請求はすでに支払い済みとして記録されているよ。",
                ephemeral=True,
            )
            return

        # 支払いボタンによる支払い済み記録（Bot内の残高・現金は動かさない）
        record_au_payment(self.guild_id, self.target_user_id, self.amount)
        self.paid = True
        completed_embed = make_au_message(
            interaction.user, self.amount, completed=True
        )
        completed_embed.add_field(
            name="支払い記録",
            value=f"請求額：**{format_au_charge(self.amount)}**\n支払い済みとして記録したよ。",
            inline=False,
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=completed_embed,
            view=self,
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
        for bj_guild_id in (1573260159403294793, 1573260415474073660):
            try:
                guild_synced = await bot.tree.sync(guild=discord.Object(id=bj_guild_id))
                print(f"[BJ EMOJI] guild {bj_guild_id}: {len(guild_synced)} commands synced")
            except Exception:
                print(f"[BJ EMOJI] guild sync failed: {bj_guild_id}")
                traceback.print_exc()
        await restore_au_timeout_tasks()

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
            amount = random.randint(1, 1000)
            await message.channel.send(embed=make_au_message(message.author, amount), view=AuPaymentView(message.author.id, amount))

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
# JSON / Neon PostgreSQL 共通保存
# ==================================================

DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_JSON_TABLE = "bot_json_data"


def _ensure_json_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_json_data (
            data_key TEXT PRIMARY KEY,
            payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def load_json(path, default):
    data_key = str(path)
    file_data = default

    # まず既存JSONを読み込む。DBにまだデータがない場合の移行元として使う。
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                file_data = json.load(file)
    except Exception:
        print(f"[JSON LOAD ERROR] {path}")
        traceback.print_exc()

    if not DATABASE_URL:
        return file_data

    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                _ensure_json_table(cursor)
                cursor.execute(
                    "SELECT payload FROM bot_json_data WHERE data_key = %s",
                    (data_key,),
                )
                row = cursor.fetchone()

                if row is not None:
                    print(f"[DATABASE] Loaded: {data_key}")
                    return row[0]

                # 初回のみ、既存JSONの内容をNeonへ移行する。
                cursor.execute(
                    """
                    INSERT INTO bot_json_data (data_key, payload)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (data_key) DO NOTHING
                    """,
                    (data_key, json.dumps(file_data, ensure_ascii=False)),
                )
                print(f"[DATABASE] Migrated JSON: {data_key}")
                return file_data

    except Exception:
        print(f"[DATABASE LOAD ERROR] {data_key} — JSONバックアップを使用します。")
        traceback.print_exc()
        return file_data


def save_json(path, data):
    # JSONファイルにも常にバックアップを残す。
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except Exception:
        print(f"[JSON BACKUP SAVE ERROR] {path}")
        traceback.print_exc()

    if not DATABASE_URL:
        return

    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                _ensure_json_table(cursor)
                cursor.execute(
                    """
                    INSERT INTO bot_json_data (data_key, payload, updated_at)
                    VALUES (%s, %s::jsonb, NOW())
                    ON CONFLICT (data_key)
                    DO UPDATE SET
                        payload = EXCLUDED.payload,
                        updated_at = NOW()
                    """,
                    (str(path), json.dumps(data, ensure_ascii=False)),
                )
        print(f"[DATABASE] Saved: {path}")

    except Exception:
        print(f"[DATABASE SAVE ERROR] {path} — JSONバックアップは保存済みです。")
        traceback.print_exc()


# ==================================================
balances = load_json(BALANCES_FILE, {})
slot_positions = load_json(POSITIONS_FILE, {})
slot_logs = load_json(SLOT_LOGS_FILE, [])
log_configs = load_json(LOG_CONFIG_FILE, {})
coin_logs = load_json(COIN_LOGS_FILE, [])
server_settings = load_json(SETTINGS_FILE, {})
daily_data = load_json(DAILY_FILE, {})
guess_data = load_json(GUESS_FILE, {})
jackpot_data = load_json(JACKPOT_FILE, {"pool": 10000})
au_whitelist = set(str(user_id) for user_id in load_json(AU_WHITELIST_FILE, []))
AU_SETTINGS_FILE = Path(os.getenv("DATA_DIR", ".")) / "au_settings.json"
AU_TIMEOUTS_FILE = Path(os.getenv("DATA_DIR", ".")) / "au_timeout_records.json"
AU_DEBT_FILE = Path(os.getenv("DATA_DIR", ".")) / "au_debt_records.json"
au_settings = load_json(AU_SETTINGS_FILE, {})
au_timeout_records = load_json(AU_TIMEOUTS_FILE, {})
au_debt_records = load_json(AU_DEBT_FILE, {})
AU_TIMEOUT_TASKS = {}


def get_au_debt_record(guild_id, user_id):
    guild_data = au_debt_records.setdefault(str(guild_id), {})
    record = guild_data.setdefault(str(user_id), {
        "billed": 0,
        "paid": 0,
        "unpaid": 0,
        "bill_count": 0,
    })
    for key in ("billed", "paid", "unpaid", "bill_count"):
        try:
            record[key] = max(0, int(record.get(key, 0)))
        except (TypeError, ValueError):
            record[key] = 0
    return record


def record_au_charge(guild_id, user_id, amount):
    record = get_au_debt_record(guild_id, user_id)
    amount = max(0, int(amount))
    record["billed"] += amount
    record["unpaid"] += amount
    record["bill_count"] += 1
    save_json(AU_DEBT_FILE, au_debt_records)


def record_au_payment(guild_id, user_id, amount):
    record = get_au_debt_record(guild_id, user_id)
    amount = max(0, int(amount))
    paid_now = min(amount, record["unpaid"])
    record["paid"] += paid_now
    record["unpaid"] -= paid_now
    save_json(AU_DEBT_FILE, au_debt_records)
    return paid_now


def get_au_guild_debt_totals(guild_id):
    guild_data = au_debt_records.get(str(guild_id), {})
    totals = {"billed": 0, "paid": 0, "unpaid": 0, "bill_count": 0}
    for user_record in guild_data.values():
        for key in totals:
            try:
                totals[key] += max(0, int(user_record.get(key, 0)))
            except (TypeError, ValueError, AttributeError):
                pass
    return totals


def get_au_settings(guild_id):
    key = str(guild_id)
    config = au_settings.setdefault(key, {})
    config.setdefault("enabled", True)
    config.setdefault("timeout_enabled", False)
    config.setdefault("timeout_seconds", 60)
    config.setdefault("charge_limit", 1000)
    config.setdefault("show_charge_extremes", False)
    config.setdefault("charge_min", None)
    config.setdefault("charge_max", None)
    config.setdefault("timeout_exempt_channels", [])
    # 旧版の全サーバー共通ホワイトリストを初回だけ引き継ぐ
    config.setdefault("whitelist", sorted(au_whitelist, key=int))
    if not isinstance(config.get("whitelist"), list):
        config["whitelist"] = []
    if not isinstance(config.get("timeout_exempt_channels"), list):
        config["timeout_exempt_channels"] = []
    config["timeout_exempt_channels"] = sorted(
        set(str(x) for x in config["timeout_exempt_channels"] if str(x).isdigit()),
        key=int,
    )
    for stat_key in ("charge_min", "charge_max"):
        try:
            config[stat_key] = None if config.get(stat_key) is None else max(1, int(config[stat_key]))
        except (TypeError, ValueError):
            config[stat_key] = None
    try:
        config["timeout_seconds"] = max(1, min(86400, int(config.get("timeout_seconds", 60))))
    except (TypeError, ValueError):
        config["timeout_seconds"] = 60
    try:
        config["charge_limit"] = max(1, min(1000000, int(config.get("charge_limit", 1000))))
    except (TypeError, ValueError):
        config["charge_limit"] = 1000
    save_json(AU_SETTINGS_FILE, au_settings)
    return config


async def au_timeout_release_task(guild_id, user_id, release_at, discord_until):
    record_key = f"{guild_id}:{user_id}"
    try:
        wait_seconds = max(0, float(release_at) - datetime.now(timezone.utc).timestamp())
        await asyncio.sleep(wait_seconds)

        guild = bot.get_guild(int(guild_id))
        if guild is None:
            try:
                guild = await bot.fetch_guild(int(guild_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return

        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return

        current_until = member.timed_out_until
        if current_until is not None:
            expected = datetime.fromtimestamp(float(discord_until), timezone.utc)
            # Botが設定したタイムアウトのままの場合だけ解除する。
            # 管理者が手動で解除・延長した場合は上書きしない。
            if abs((current_until - expected).total_seconds()) <= 10:
                await member.timeout(None, reason="あう検知の設定時間が経過したため自動解除")

    except asyncio.CancelledError:
        raise
    except Exception:
        print(f"[AU TIMEOUT RELEASE ERROR] guild={guild_id} user={user_id}")
        traceback.print_exc()
    finally:
        au_timeout_records.pop(record_key, None)
        save_json(AU_TIMEOUTS_FILE, au_timeout_records)
        AU_TIMEOUT_TASKS.pop(record_key, None)


def schedule_au_timeout_release(guild_id, user_id, release_at, discord_until):
    record_key = f"{guild_id}:{user_id}"
    old_task = AU_TIMEOUT_TASKS.get(record_key)
    if old_task and not old_task.done():
        old_task.cancel()
    AU_TIMEOUT_TASKS[record_key] = asyncio.create_task(
        au_timeout_release_task(guild_id, user_id, release_at, discord_until)
    )


async def restore_au_timeout_tasks():
    # 再起動・再デプロイ後も、保存済みの解除予定を復元する。
    for record_key, record in list(au_timeout_records.items()):
        try:
            guild_id, user_id = record_key.split(":", 1)
            schedule_au_timeout_release(
                guild_id,
                user_id,
                float(record["release_at"]),
                float(record["discord_until"]),
            )
        except (KeyError, TypeError, ValueError):
            print(f"[AU TIMEOUT] 不正な解除記録を削除: {record_key}")
            au_timeout_records.pop(record_key, None)
    save_json(AU_TIMEOUTS_FILE, au_timeout_records)


async def apply_au_timeout(member, seconds):
    guild_id = str(member.guild.id)
    user_id = str(member.id)
    record_key = f"{guild_id}:{user_id}"

    if record_key in au_timeout_records:
        return False, "このメンバーには既にあう検知のタイムアウトが設定されています。"

    bot_member = member.guild.me
    if bot_member is None or not bot_member.guild_permissions.moderate_members:
        return False, "Botに「メンバーをタイムアウト」の権限がありません。"
    if member.top_role >= bot_member.top_role:
        return False, "Botより上位または同じロールのメンバーにはタイムアウトを設定できません。"

    now = datetime.now(timezone.utc)
    # Discord APIの最短時間制限を避けるため、Discord側は1時間に設定し、
    # 指定秒数後にBotが自動解除する。
    discord_expiry = now + timedelta(seconds=max(3600, int(seconds) + 60))
    release_at = now.timestamp() + int(seconds)

    try:
        await member.timeout(discord_expiry, reason=f"あう検知（設定時間: {seconds}秒）")
        au_timeout_records[record_key] = {
            "release_at": release_at,
            "discord_until": discord_expiry.timestamp(),
        }
        save_json(AU_TIMEOUTS_FILE, au_timeout_records)
        schedule_au_timeout_release(
            guild_id, user_id, release_at, discord_expiry.timestamp()
        )
        return True, None
    except discord.Forbidden:
        return False, "権限不足でタイムアウトできませんでした。"
    except discord.HTTPException:
        return False, "Discord側でエラーが発生し、タイムアウトできませんでした。"

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

    message = "🚫Only Minatan can use this command."

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
    print(
        f"[MESSAGE] guild={message.guild.id if message.guild else 'DM'} "
        f"channel={message.channel.id} "
        f"user={message.author} "
        f"content={message.content[:150]}"
    )
    # Botのメッセージはここで終了（上の大量メンション検知だけ実施）    if message.author.bot:
        return

    # サーバーごとの「あう」検知設定
    if message.guild is not None and pattern.search(message.content):
        config = get_au_settings(message.guild.id)
        user_id = str(message.author.id)

        if config.get("enabled", True) and user_id not in config.get("whitelist", []):
            charge_limit = max(1, min(1000000, int(config.get("charge_limit", 1000))))
            amount = random.randint(1, charge_limit)
            try:
                record_au_charge(message.guild.id, message.author.id, amount)
                previous_min = config.get("charge_min")
                previous_max = config.get("charge_max")
                config["charge_min"] = amount if previous_min is None else min(int(previous_min), amount)
                config["charge_max"] = amount if previous_max is None else max(int(previous_max), amount)
                save_json(AU_SETTINGS_FILE, au_settings)

                charge_stats = None
                if config.get("show_charge_extremes", False):
                    charge_stats = {
                        "min": config["charge_min"],
                        "max": config["charge_max"],
                    }
                await message.channel.send(
                    embed=make_au_message(
                        message.author, amount, charge_stats=charge_stats
                    ),
                    view=AuPaymentView(message.guild.id, message.author.id, amount),
                )
                print("[AU DETECTED] あうを検知しました")

                if (
                    config.get("timeout_enabled", False)
                    and str(message.channel.id) not in config.get("timeout_exempt_channels", [])
                    and isinstance(message.author, discord.Member)
                ):
                    seconds = max(1, min(86400, int(config.get("timeout_seconds", 60))))
                    success, error_message = await apply_au_timeout(message.author, seconds)
                    if success:
                        await message.channel.send(
                            f"⏱️ {message.author.mention} を **{seconds}秒間** タイムアウトしました。"
                        )
                    else:
                        print(f"[AU TIMEOUT] {error_message}")
            except Exception:
                print("[AU DETECTION ERROR]")
                traceback.print_exc()

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
        command_name = ctx.command.name if ctx.command else ""
        missing_name = error.param.name

        # コマンドごとに、足りない項目を分かりやすく案内する
        if command_name == "give":
            if missing_name == "member":
                message = "送金相手が足りないよ！\n使い方：`.give @相手 金額`\n例：`.give @user 100`"
            else:
                message = "送金する金額が足りないよ！\n使い方：`.give @相手 金額`\n例：`.give @user 100`"
        elif command_name == "th":
            if missing_name == "bet":
                message = "賭け金が足りないよ！\n使い方：`.th 賭け金 1〜9`\n例：`.th 100 3`"
            else:
                message = "レーン番号が足りないよ！1〜9の番号を入力してね。\n例：`.th 100 3`"
        else:
            argument_names = {
                "bet": "賭け金",
                "amount": "金額",
                "target": "相手",
                "user": "ユーザー",
                "member": "メンバー",
                "lane": "レーン番号",
                "color": "色",
                "choice": "選択肢",
                "reason": "理由",
                "message": "メッセージ",
            }
            missing_label = argument_names.get(missing_name, missing_name)
            message = (
                f"「{missing_label}」が足りないよ！\n"
                f"コマンド：`{ctx.prefix}{command_name}`"
            )

        await ctx.reply(message, mention_author=False)
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

            if house_result is not None:                description += (
                    f"\n胴元の変動：**{money_change(house_result['change'])}**"                    f"\n胴元の残高：**{money(house_result['after'])}**"
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

@bot.command(name="color", aliases=["色当て", "redblue", "cl"])
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
# .dice 4個のサイコロゲーム（賭け金なし）
# ==================================================

DICE_COLORS = {
    "a": {"name": "赤", "emoji": "🔴", "custom": "aka"},
    "b": {"name": "青", "emoji": "🔵", "custom": "ao"},
    "y": {"name": "黄色", "emoji": "🟡", "custom": "kiro"},
    "o": {"name": "オレンジ", "emoji": "🟠", "custom": "orengi"},
    "g": {"name": "緑", "emoji": "🟢", "custom": "midori"},
    "p": {"name": "紫", "emoji": "🟣", "custom": "murasaki"},
}

DICE_ROLLING_EMOJI = "<a:emoji_31:1572239943718150164>"

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
            placeholder="次に狙う色を選んでね",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.game_view
        if interaction.user.id != view.player_id:
            await interaction.response.send_message(
                "このゲームを操作できるのは開始した本人だけだよ。",
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


class DiceGameView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.player_id = ctx.author.id
        self.guild = ctx.guild
        self.finished = False
        self.message = None
        self.round_number = 0

    def roll_dice(self):
        return [random.choice(list(DICE_COLORS.keys())) for _ in range(4)]

    def format_dice(self, dice):
        return " ".join(get_dice_emoji(self.guild, color) for color in dice)

    def make_rolling_embed(self, chosen_color):
        return discord.Embed(
            description=" ".join([DICE_ROLLING_EMOJI] * 4),
            color=discord.Color.blurple(),
        )

    def make_result_embed(self, dice, chosen_color, count):
        if count in (1, 4):
            color = discord.Color.green()
        elif count in (2, 3):
            color = discord.Color.blurple()
        else:
            color = discord.Color.red()

        return discord.Embed(
            description=self.format_dice(dice),
            color=color,
        )

    async def show_roll(self, chosen_color, interaction=None):
        self.round_number += 1
        self.clear_items()
        rolling_embed = self.make_rolling_embed(chosen_color)

        if interaction is not None:
            await interaction.response.edit_message(
                content=None,
                embed=rolling_embed,
                view=None,
            )
        else:
            await self.message.edit(
                content=None,
                embed=rolling_embed,
                view=None,
            )

        await asyncio.sleep(1)

        dice = self.roll_dice()
        count = dice.count(chosen_color)
        result_embed = self.make_result_embed(dice, chosen_color, count)

        if count in (2, 3):
            self.add_item(DiceColorSelect(self))

        await self.message.edit(
            content=None,
            embed=result_embed,
            view=self if count in (2, 3) else None,
        )

        if count in (0, 1, 4):
            self.finished = True
            self.stop()

    async def roll_again(self, interaction, chosen_color):
        await self.show_roll(chosen_color, interaction=interaction)

    async def on_timeout(self):
        if self.finished or self.message is None:
            return
        self.finished = True
        self.stop()
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(
                content=None,
                embed=discord.Embed(
                    title="⏰ 時間切れ",
                    description="ゲームを終了したよ。",
                    color=discord.Color.orange(),
                ),
                view=self,
            )
        except (discord.NotFound, discord.HTTPException):
            pass


@bot.command(name="dice", aliases=["mdice", "ダイス", "サイコロ"])
async def dice_command(ctx, color_text: str = None):
    if ctx.guild is None:
        await ctx.reply(
            "このコマンドはサーバー内で使ってね。",
            mention_author=False,
        )
        return

    color_key = (color_text or "").strip().lower()
    if color_key not in DICE_COLORS:
        await ctx.reply(
            "色を選んでね！\n"
            "`a` 赤 / `b` 青 / `y` 黄色 / "
            "`o` オレンジ / `g` 緑 / `p` 紫\n"
            "例：`.dice a`",
            mention_author=False,
        )
        return

    view = DiceGameView(ctx)
    view.round_number = 1
    message = await ctx.reply(
        embed=view.make_rolling_embed(color_key),
        mention_author=False,
    )
    view.round_number = 0
    view.message = message
    await view.show_roll(color_key)

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


class MineGameView(discord.ui.LayoutView):
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
        self.multiplier = 1.0
        self.inline_cashout_button = None
        self.cell_buttons = {}
        self.cell_select = None

        for index in range(self.total_cells):
            button = ui.Button(
                label="？",
                style=discord.ButtonStyle.secondary,
                custom_id=f"mine:{self.player_id}:{index}",
            )

            async def cell_callback(interaction, cell_index=index):
                await self.open_cell(interaction, cell_index)

            button.callback = cell_callback
            self.cell_buttons[index] = button

        if size != 5:
            cashout_button = ui.Button(
                label="Cash Out",
                emoji="💵",
                style=discord.ButtonStyle.success,
                disabled=True,
                custom_id=f"minecashout_inline:{self.player_id}",
            )
            cashout_button.callback = self.inline_cashout_callback
            self.inline_cashout_button = cashout_button

        self.rebuild_container()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "このゲームを操作できるのは賭けた本人だけだよ。",
                ephemeral=True,
            )
            return False
        if self.finished:
            await interaction.response.send_message(
                "このゲームはもう終了しているよ。",
                ephemeral=True,
            )
            return False
        return True

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

    def rebuild_container(self, status="playing", result_text=None):
        self.clear_items()

        opened_count = len(self.opened_safe)
        safe_symbols = (
            f"💵 **{sum(1 for v in self.cell_symbols.values() if v == '💵')}**　"
            f"💍 **{sum(1 for v in self.cell_symbols.values() if v == '💍')}**　"
            f"💎 **{sum(1 for v in self.cell_symbols.values() if v == '💎')}**"
        )

        if status == "playing":
            current_payout = int(self.bet * self.multiplier) if opened_count else 0
            next_multiplier = self.next_multiplier()
            display_text = (
                f"## 💣 MINES\n"
                f"{self.ctx.author.mention} マスを選んでね！\n"
                "爆弾を引く前に「Cash Out」でいつでも終了できるよ。\n\n"
                f"💵 **賭け金**：{money(self.bet)}\n"
                f"🧩 **盤面**：{self.size}×{self.size}\n"
                f"💣 **爆弾**：{self.bomb_count}個\n"
                f"📈 **現在の倍率**：{self.multiplier:.2f}倍\n"
                f"💰 **現在の精算額**：{money(current_payout)}\n"
                f"➡️ **次のマス**：{next_multiplier:.2f}倍 / {money(int(self.bet * next_multiplier))}\n"
                f"🎲 **出目**：{safe_symbols}\n"
                f"開いた安全マス：**{opened_count}/{self.safe_total}**"
            )
        else:
            payout = int(self.bet * self.multiplier) if status == "win" else (self.bet if status == "timeout" else 0)
            profit = payout - self.bet
            title = "🎉 MINES — CLEAR!" if status == "win" else "💥 MINES — BOOM!" if status == "lose" else "⏰ MINES — TIME UP"
            display_text = (
                f"## {title}\n"
                f"{result_text or 'ゲーム終了！'}\n\n"
                f"👤 {self.ctx.author.mention}\n"
                f"💵 **賭け金**：{money(self.bet)}　💰 **払戻し**：{money(payout)}\n"
                f"📊 **収支**：{money_change(profit)}　📈 **最終倍率**：{self.multiplier:.2f}倍\n"
                f"🧩 **盤面**：{self.size}×{self.size} / 💣 **爆弾**：{self.bomb_count}個\n"
                f"💎 **安全マス**：{opened_count}/{self.safe_total}\n"
                f"🎲 **出目内訳**：{safe_symbols}\n"
                f"🏦 **終了後残高**：{money(get_balance(self.player_id))}"
            )

        components = [ui.TextDisplay(display_text)]
        for row_start in range(0, self.total_cells, self.size):
            row_buttons = [
                self.cell_buttons[index]
                for index in range(row_start, min(row_start + self.size, self.total_cells))
            ]
            components.append(ui.ActionRow(*row_buttons))

        if self.inline_cashout_button:
            components.append(ui.ActionRow(self.inline_cashout_button))

        self.add_item(ui.Container(*components))

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
        if len(self.opened_safe) >= self.safe_total:
            await interaction.response.defer()
            await self.finish_game("win", "🏆 すべての安全マスを開いたよ！")
            return

        payout = int(self.bet * self.multiplier)
        self.rebuild_container()
        await interaction.response.edit_message(view=self)

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
        self.rebuild_container(result, result_text)
        try:
            if self.message:
                await self.message.edit(view=self)
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


@bot.command(name="mine", aliases=["マイン", "m"])
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
    try:
        message = await ctx.reply(view=view, mention_author=False)
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

    # 1回のスピンの合計賭け金は$30まで
    if total_bet > 30:
        msg = "スロットの最高賭け金は1回あたり **$30** だよ。"
        if interaction:
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx.reply(msg, mention_author=False)
        return

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

    # 表示専用のニアミス演出。抽選結果 grid と配当計算には一切触れない
    visual_grid = [row[:] for row in grid]
    payline_rows = []
    if line_choice >= 1:
        payline_rows.append((1, 1, 1))
    if line_choice >= 2:
        payline_rows.extend([(0, 0, 0), (2, 2, 2)])
    if line_choice >= 3:
        payline_rows.extend([(0, 1, 2), (2, 1, 0)])
    for row_positions in payline_rows:
        left_symbol = grid[row_positions[0]][0]
        middle_symbol = grid[row_positions[1]][1]        right_symbol = grid[row_positions[2]][2]

        # 777 / JP の2つがリーチして外れた場合だけ、右レーンの隣の段に表示
        if (
            left_symbol == middle_symbol
            and left_symbol in ("7️⃣", "JP")
            and right_symbol != left_symbol
        ):
            right_payline_row = row_positions[2]
            near_row = right_payline_row - 1 if right_payline_row == 2 else right_payline_row + 1
            visual_grid[near_row][2] = left_symbol

    displayed_rows = [
        [display_symbol(symbol, ctx.guild, settings) for symbol in row]
        for row in visual_grid
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
        f"{left_top} {'|'.join(displayed_rows[0])} {right_top} {gray_emoji * (len(jp_nums) + 2)}\n"
        f"{left_mid} {'|'.join(displayed_rows[1])} {right_mid} {jp_display_parts}{gray_emoji}\n"
        f"{left_bot} {'|'.join(displayed_rows[2])} {right_bot} {gray_emoji * (len(jp_nums) + 2)}\n"
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
            f"{left_top} {reel_rows[0]} {right_top} {gray_emoji * 2}\n"
            f"{left_mid} {reel_rows[1]} {right_mid} {jp_display_parts}{gray_emoji}\n"
            f"{left_bot} {reel_rows[2]} {right_bot} {gray_emoji * 2}\n"
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
@bot.command(name="slot", aliases=["s"])
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
# .scratch スクラッチゲーム
# ==================================================

SCRATCH_SYMBOLS = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん") + ["🤓"]
SCRATCH_USER_LOCKS = {}

def get_scratch_lock(user_id):
    user_id = int(user_id)
    if user_id not in SCRATCH_USER_LOCKS:
        SCRATCH_USER_LOCKS[user_id] = asyncio.Lock()
    return SCRATCH_USER_LOCKS[user_id]


def get_scratch_multiplier(result):
    # 100倍：指定された3文字の組み合わせ
    if result in ("あう🤓", "うお🤓", "おう🤓", "まんこ", "ちんこ", "うんこ"):
        return 100, "🎉 JACKPOT！"

    # 30倍：🤓が先頭または真ん中にある指定の組み合わせ
    if result in (
        "🤓あう", "🤓おう", "🤓うお",
        "あ🤓う", "お🤓う", "う🤓お",
    ):
        return 30, "🤓 BONUS！"

    # 10倍：3マスすべて同じ文字
    if result[0] == result[1] == result[2]:
        return 10, "🎊 3つ揃い！"

    # 3倍：同じ文字が隣り合って2つ
    if result[0] == result[1] or result[1] == result[2]:
        return 3, "✨ 2連続！"

    return 0, "はずれ"


@bot.command(name="scratch", aliases=["スクラッチ"])
async def scratch_command(ctx, bet_text: str = None):
    if ctx.author.bot:
        return
    if ctx.guild is None:
        await ctx.reply("このコマンドはサーバー内で使ってね。", mention_author=False)
        return
    if bet_text is None:
        await ctx.reply("賭け金を指定してね！\n例：`.scratch 100` または `.scratch all`", mention_author=False)
        return

    bet = resolve_bet(ctx.author.id, bet_text)
    if bet is None or bet <= 0:
        await ctx.reply("賭け金は1以上の数字か `all` で指定してね。\n例：`.scratch 100`", mention_author=False)
        return

    lock = get_scratch_lock(ctx.author.id)
    async with lock:
        balance_before = get_balance(ctx.author.id)
        if bet > balance_before:
            await ctx.reply(
                f"残高が足りないよ！\n必要額：**{money(bet)}**\n残高：**{money(balance_before)}**",
                mention_author=False,
            )
            return

        result = "".join(random.choice(SCRATCH_SYMBOLS) for _ in range(3))
        multiplier, result_label = get_scratch_multiplier(result)
        returned = bet * multiplier
        profit = returned - bet
        balance_after = balance_before - bet + returned

        set_balance(ctx.author.id, balance_after)
        transfer_to_house(
            player_id=ctx.author.id,
            profit=profit,
            guild_id=ctx.guild.id,
            game="scratch",
        )

        record_coin({
            "type": "scratch",
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "guild_id": ctx.guild.id,
            "user_id": ctx.author.id,
            "username": str(ctx.author),
            "bet": bet,
            "result": result,
            "multiplier": multiplier,
            "returned": returned,
            "profit": profit,
            "before": balance_before,
            "after": balance_after,
        })

    embed = discord.Embed(
        title="🎟️ スクラッチ結果",
        description=(
            f"**{ctx.author.display_name} の結果**\n\n"
            f"╭─────┬─────┬─────╮\n"
            f"│　**{result[0]}**　│　**{result[1]}**　│　**{result[2]}**　│\n"
            f"╰─────┴─────┴─────╯\n\n"
            f"**{result_label}**\n"
            f"倍率：**{multiplier}倍**\n"
            f"賭け金：**{money(bet)}**\n"
            f"返却：**{money(returned)}**\n"
            f"利益：**{money_change(profit)}**\n"
            f"残高：**{money(balance_after)}**"
        ),
        color=discord.Color.gold() if multiplier >= 30 else (
            discord.Color.green() if multiplier > 0 else discord.Color.red()
        ),
    )
    await ctx.reply(embed=embed, mention_author=False)

    log_embed = discord.Embed(
        title="🎟️ スクラッチログ",
        description=(
            f"ユーザー：{ctx.author.mention} (`{ctx.author.id}`)\n"
            f"出目：**{result}**\n"
            f"倍率：**{multiplier}倍**\n"
            f"賭け金：**{money(bet)}**\n"
            f"返却：**{money(returned)}**\n"
            f"利益：**{money_change(profit)}**\n"
            f"残高：**{money(balance_after)}**"
        ),
        color=discord.Color.gold(),
    )
    await send_coin_log(ctx.guild, log_embed)


# ==================================================
# /decidecash 指定したユーザーの残高を設定
# ==================================================

@bot.tree.command(
    name="decidecash",
    description="指定したユーザーの残高を設定する（オーナー本人専用）",
)
@app_commands.describe(
    target="残高を設定する対象のユーザー",
    amount="設定する金額",
)
async def decidecash_command(interaction: discord.Interaction, target: discord.User, amount: int):
    if not await require_owner(interaction):
        return

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
# .give ユーザー間送金（送信者の確認ボタン付き）
# ==================================================

class GiveConfirmView(discord.ui.View):
    def __init__(self, sender, recipient, amount):
        super().__init__(timeout=120)
        self.sender_id = sender.id
        self.sender = sender
        self.recipient = recipient
        self.amount = int(amount)
        self.completed = False
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.sender_id:
            await interaction.response.send_message(
                "この送金を操作できるのは送信者だけだよ。",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="送る", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.completed:
            await interaction.response.send_message("この送金はすでに処理済みだよ。", ephemeral=True)
            return

        sender_before = get_balance(self.sender_id)
        if sender_before < self.amount:
            self.completed = True
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content="残高が足りないため、送金できなかったよ。",
                embed=None,
                view=self,
            )
            return

        # この時点で初めて残高を移動する
        recipient_before = get_balance(self.recipient.id)
        sender_after = sender_before - self.amount
        recipient_after = recipient_before + self.amount
        self.completed = True
        set_balance(self.sender_id, sender_after)
        set_balance(self.recipient.id, recipient_after)

        for item in self.children:
            item.disabled = True

        embed = discord.Embed(
            title="✅ 送金完了",
            description=(
                f"送信者：{self.sender.mention}\n"
                f"受取人：{self.recipient.mention}\n"
                f"送金額：**{money(self.amount)}**\n"
                f"送信者の残高：**{money(sender_after)}**"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(content=None, embed=embed, view=self)

        record_coin({
            "type": "give",
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "guild_id": interaction.guild.id if interaction.guild else None,
            "user_id": self.sender_id,
            "username": str(self.sender),
            "recipient_id": self.recipient.id,
            "recipient_name": str(self.recipient),
            "amount": self.amount,
            "sender_before": sender_before,
            "sender_after": sender_after,
            "recipient_before": recipient_before,
            "recipient_after": recipient_after,
        })

        if interaction.guild is not None:
            await send_coin_log(
                interaction.guild,
                discord.Embed(
                    title="💸 Give送金ログ",
                    description=(
                        f"送信者：{self.sender.mention} (`{self.sender_id}`)\n"
                        f"受取人：{self.recipient.mention} (`{self.recipient.id}`)\n"
                        f"送金額：**{money(self.amount)}**\n"
                        f"送金後残高：**{money(sender_after)}**\n"
                        f"受取後残高：**{money(recipient_after)}**"
                    ),
                    color=discord.Color.blurple(),
                ),
            )

    @discord.ui.button(label="送らない", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.completed:
            await interaction.response.send_message("この送金はすでに処理済みだよ。", ephemeral=True)
            return

        self.completed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="送金をキャンセルしたよ。残高は変わっていないよ。",
            embed=None,
            view=self,
        )

    async def on_timeout(self):
        if self.completed:
            return
        self.completed = True
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content="確認時間が過ぎたため、送金をキャンセルしたよ。残高は変わっていないよ。",
                    embed=None,
                    view=self,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass


@bot.command(name="give")
async def give_command(ctx: commands.Context, member: discord.Member, amount_text: str):
    """他のメンバーへ残高を送る（例：.give @user 100）"""
    if ctx.guild is None:
        await ctx.reply("サーバー内で使ってね。", mention_author=False)
        return

    if member.bot:
        await ctx.reply("Botには送金できないよ。", mention_author=False)
        return

    if member.id == ctx.author.id:
        await ctx.reply("自分自身には送金できないよ。", mention_author=False)
        return

    try:
        amount = parse_money_text(amount_text)
    except (TypeError, ValueError):
        await ctx.reply("金額は数字で入力してね。例：`.give @user 100`", mention_author=False)
        return

    if amount <= 0:
        await ctx.reply("送金額は1以上を指定してね。", mention_author=False)
        return

    current_balance = get_balance(ctx.author.id)
    if current_balance < amount:
        await ctx.reply(
            f"残高が足りないよ。\n現在の残高：**{money(current_balance)}**\n送金額：**{money(amount)}**",
            mention_author=False,
        )
        return

    view = GiveConfirmView(ctx.author, member, amount)
    embed = discord.Embed(
        title="💸 送金の確認",
        description=(
            f"送信者：{ctx.author.mention}\n"
            f"受取人：{member.mention}\n"
            f"送金額：**{money(amount)}**\n"
            f"現在の残高：**{money(current_balance)}**\n\n"
            "この内容で送金する？\n"
            "「送る」を押すまで残高は変わらないよ。"
        ),
        color=discord.Color.gold(),
    )
    view.message = await ctx.reply(embed=embed, view=view, mention_author=False)


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
            "**💰 残高・送金**\n"
            "`.cash` / `.bal` — 自分の残高を確認\n"
            "`.cash @ユーザー` — 相手の残高を確認\n"
            "`.give @ユーザー 金額` — 相手に送金（確認ボタン付き）\n"
            "`.daily` — ログインボーナスを受け取る\n\n"
            "**🎮 ゲーム**\n"
            "`.slot 賭け金 [ライン数]` — スロット（`.s`でも可）\n"
            "`.slothelp` — スロットの遊び方\n"
            "`.jackpot` / `.jp` — ジャックポットの積立額を確認\n"
            "`.color 賭け金` — 🌝🌚の2択ゲーム（`.cl`でも可）\n"
            "`.mine 賭け金 サイズ 爆弾数` — マインズ（`.m`でも可）\n"
            "`.mdice 賭け金 色` — 色ダイス（r/b/y/o/g/p）\n"
            "`.bj 賭け金` — ブラックジャック\n"
            "`.r 賭け金 対象` — ルーレット（数字0〜36・色・奇偶など）\n"
            "`.hl [賭け金]` — HIGH&LOW（省略時100、`all`対応）\n"
            "`.th 賭け金 1〜9` — TREASURE HUNT\n\n"
            "**📖 ヘルプ**\n"
            "`.mhelp` / `.help` — このコマンド一覧を表示"
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

        await interaction.response.send_message(            embed=discord.Embed(
                title="🎰 出現比率を更新したよ",
                description=get_weights_text(parsed),
                color=discord.Color.green(),            ),
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
                    elif "HIGH&LOW" in title:
                        user_match = re.search(r"ユーザー：.*?`(\d+)`", description)
                        if "ベットログ" in title:
                            balance_match = re.search(
                                r"ベット後残高：\*\*([+-]?\$?[\d,]+)\*\*",
                                description,
                            )
                        else:
                            balance_match = re.search(
                                r"残高：\*\*([+-]?\$?[\d,]+)\*\*",
                                description,
                            )
                        if user_match and balance_match:
                            combined_logs.append({
                                "timestamp": message.created_at.timestamp(),
                                "user_id": user_match.group(1),
                                "balance": parse_money_text(balance_match.group(1)),
                            })

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
# /au setting — あう検知設定を1か所に集約
# ==================================================

class AuTimeoutModal(discord.ui.Modal, title="タイムアウト時間の設定"):
    seconds = discord.ui.TextInput(
        label="タイムアウト時間（秒）",
        placeholder="1〜86400（例：5）",
        min_length=1,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        try:
            seconds = int(str(self.seconds.value).strip())
        except ValueError:
            await interaction.response.send_message("秒数は数字で入力してね。", ephemeral=True)
            return
        if not 1 <= seconds <= 86400:
            await interaction.response.send_message("1〜86400秒の範囲で指定してね。", ephemeral=True)
            return
        config = get_au_settings(interaction.guild.id)
        config["timeout_seconds"] = seconds
        save_json(AU_SETTINGS_FILE, au_settings)
        await interaction.response.send_message(
            f"✅ あう検知のタイムアウト時間を **{seconds}秒** に設定したよ。",
            ephemeral=True,
        )


class AuChargeLimitModal(discord.ui.Modal, title="1回あたりの請求上限設定"):
    limit = discord.ui.TextInput(
        label="請求上限（万円）",
        placeholder="1〜1000000（例：1000）",
        min_length=1,
        max_length=7,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        try:
            limit = int(str(self.limit.value).replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("上限は数字で入力してね。", ephemeral=True)
            return
        if not 1 <= limit <= 1000000:
            await interaction.response.send_message("1〜1000000万円の範囲で指定してね。", ephemeral=True)
            return

        config = get_au_settings(interaction.guild.id)
        config["charge_limit"] = limit
        save_json(AU_SETTINGS_FILE, au_settings)
        await interaction.response.send_message(
            f"✅ あう送信1回あたりの請求上限を **{format_au_charge(limit)}** に設定したよ。",
            ephemeral=True,
        )


class AuTimeoutExemptChannelModal(discord.ui.Modal):
    def __init__(self, action):
        self.action = action
        title = "タイムアウト除外チャンネルを追加" if action == "add" else "タイムアウト除外チャンネルを削除"
        super().__init__(title=title)
        self.channel_id = discord.ui.TextInput(
            label="チャンネルID または #チャンネル",
            placeholder="チャンネルIDを入力",
            min_length=1,
            max_length=25,
        )
        self.add_item(self.channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return

        raw_id = re.sub(r"[^0-9]", "", str(self.channel_id.value).strip())
        if not raw_id:
            await interaction.response.send_message("チャンネルIDかチャンネルメンションを入力してね。", ephemeral=True)
            return
        channel = interaction.guild.get_channel(int(raw_id))
        if channel is None:
            await interaction.response.send_message("このサーバー内にそのチャンネルが見つからないよ。", ephemeral=True)
            return

        config = get_au_settings(interaction.guild.id)
        channels = set(str(x) for x in config.get("timeout_exempt_channels", []))
        if self.action == "add":
            channels.add(raw_id)
            result = f"✅ {channel.mention} をあうタイムアウト対象外にしたよ。"
        else:
            if raw_id not in channels:
                await interaction.response.send_message("そのチャンネルは除外登録されていないよ。", ephemeral=True)
                return
            channels.remove(raw_id)
            result = f"✅ {channel.mention} をタイムアウト対象外から削除したよ。"

        config["timeout_exempt_channels"] = sorted(channels, key=int)
        save_json(AU_SETTINGS_FILE, au_settings)
        await interaction.response.send_message(result, ephemeral=True)


class AuWhitelistModal(discord.ui.Modal):
    def __init__(self, action):
        self.action = action
        title = "ホワイトリストに追加" if action == "add" else "ホワイトリストから削除"
        super().__init__(title=title)
        self.user_id = discord.ui.TextInput(
            label="ユーザーID",
            placeholder="DiscordユーザーIDを入力",
            min_length=17,
            max_length=20,
        )
        self.add_item(self.user_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        raw_id = str(self.user_id.value).strip()
        if not raw_id.isdigit():
            await interaction.response.send_message("ユーザーIDは数字で入力してね。", ephemeral=True)
            return

        config = get_au_settings(interaction.guild.id)
        whitelist = set(str(x) for x in config.get("whitelist", []))
        if self.action == "add":
            whitelist.add(raw_id)
            result = f"✅ <@{raw_id}> をこのサーバーのホワイトリストに追加したよ。"
        else:
            if raw_id not in whitelist:
                await interaction.response.send_message("そのユーザーは登録されていないよ。", ephemeral=True)
                return
            whitelist.remove(raw_id)
            result = f"✅ <@{raw_id}> をこのサーバーのホワイトリストから削除したよ。"

        config["whitelist"] = sorted(whitelist, key=int)
        save_json(AU_SETTINGS_FILE, au_settings)
        await interaction.response.send_message(result, ephemeral=True)


class AuSettingPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction):
        if not await require_owner(interaction):
            return False
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="検知 ON / OFF", style=discord.ButtonStyle.primary, row=0)
    async def toggle_detection(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = get_au_settings(interaction.guild.id)
        config["enabled"] = not config.get("enabled", True)
        save_json(AU_SETTINGS_FILE, au_settings)
        await interaction.response.send_message(
            f"あう検知を **{'ON' if config['enabled'] else 'OFF'}** にしたよ。",
            ephemeral=True,
        )

    @discord.ui.button(label="タイムアウト ON / OFF", style=discord.ButtonStyle.danger, row=0)
    async def toggle_timeout(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = get_au_settings(interaction.guild.id)
        config["timeout_enabled"] = not config.get("timeout_enabled", False)
        save_json(AU_SETTINGS_FILE, au_settings)
        await interaction.response.send_message(
            f"自動タイムアウトを **{'ON' if config['timeout_enabled'] else 'OFF'}** にしたよ。",
            ephemeral=True,
        )

    @discord.ui.button(label="時間を設定", style=discord.ButtonStyle.secondary, row=1)
    async def set_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuTimeoutModal())

    @discord.ui.button(label="WL追加", style=discord.ButtonStyle.success, row=1)
    async def add_whitelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuWhitelistModal("add"))

    @discord.ui.button(label="WL削除", style=discord.ButtonStyle.secondary, row=1)
    async def remove_whitelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuWhitelistModal("remove"))

    @discord.ui.button(label="請求上限を設定", style=discord.ButtonStyle.primary, row=2)
    async def set_charge_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuChargeLimitModal())

    @discord.ui.button(label="最高・最低表示 ON / OFF", style=discord.ButtonStyle.primary, row=2)
    async def toggle_charge_extremes(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = get_au_settings(interaction.guild.id)
        config["show_charge_extremes"] = not config.get("show_charge_extremes", False)
        save_json(AU_SETTINGS_FILE, au_settings)
        await interaction.response.send_message(
            f"請求額の最高・最低表示を **{'ON' if config['show_charge_extremes'] else 'OFF'}** にしたよ。",
            ephemeral=True,
        )

    @discord.ui.button(label="最高・最低リセット", style=discord.ButtonStyle.danger, row=2)
    async def reset_charge_extremes(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = get_au_settings(interaction.guild.id)
        config["charge_min"] = None
        config["charge_max"] = None
        save_json(AU_SETTINGS_FILE, au_settings)
        await interaction.response.send_message(
            "✅ このサーバーの請求額の最高・最低記録をリセットしたよ。次の請求から新しく記録するね。",
            ephemeral=True,
        )

    @discord.ui.button(label="除外CH追加", style=discord.ButtonStyle.success, row=3)
    async def add_timeout_exempt_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuTimeoutExemptChannelModal("add"))

    @discord.ui.button(label="除外CH削除", style=discord.ButtonStyle.secondary, row=3)
    async def remove_timeout_exempt_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuTimeoutExemptChannelModal("remove"))

    @discord.ui.button(label="除外CH一覧", style=discord.ButtonStyle.secondary, row=4)
    async def list_timeout_exempt_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = get_au_settings(interaction.guild.id)
        channel_ids = config.get("timeout_exempt_channels", [])
        if not channel_ids:
            await interaction.response.send_message("タイムアウト対象外チャンネルはまだ登録されていないよ。", ephemeral=True)
            return
        lines = []
        for channel_id in channel_ids[:80]:
            channel = interaction.guild.get_channel(int(channel_id))
            lines.append(channel.mention if channel else f"チャンネルID: {channel_id}（見つからない）")
        embed = discord.Embed(
            title="⏱️ あうタイムアウト対象外チャンネル",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"登録数：{len(channel_ids)}チャンネル")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="WL一覧", style=discord.ButtonStyle.secondary, row=4)
    async def list_whitelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = get_au_settings(interaction.guild.id)
        user_ids = sorted(set(str(x) for x in config.get("whitelist", [])), key=int)
        if not user_ids:
            await interaction.response.send_message("このサーバーのホワイトリストは空だよ。", ephemeral=True)
            return
        lines = [f"<@{user_id}>（{user_id}）" for user_id in user_ids[:80]]
        embed = discord.Embed(
            title="📋 あう検知ホワイトリスト",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"登録者数：{len(user_ids)}人")
        await interaction.response.send_message(embed=embed, ephemeral=True)


au_group = app_commands.Group(name="au", description="あう検知の設定")


@au_group.command(name="debt", description="請求額・支払い済み・未払いの集計を確認")
@app_commands.describe(member="個人別の集計を確認するメンバー（省略するとサーバー全体）")
async def au_debt_command(
    interaction: discord.Interaction,
    member: discord.Member | None = None,
):
    if not await require_owner(interaction):
        return
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
        return

    if member is not None:
        record = get_au_debt_record(interaction.guild.id, member.id)
        embed = discord.Embed(
            title="📊 あう請求・支払い集計",
            description=f"対象：{member.mention}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="請求された額（累計）", value=f"**{format_au_charge(record['billed'])}**", inline=True)
        embed.add_field(name="支払った額（累計）", value=f"**{format_au_charge(record['paid'])}**", inline=True)
        embed.add_field(name="未払い額", value=f"**{format_au_charge(record['unpaid'])}**", inline=True)
        embed.add_field(name="請求回数", value=f"{record['bill_count']}回", inline=True)
    else:
        totals = get_au_guild_debt_totals(interaction.guild.id)
        embed = discord.Embed(
            title="📊 サーバー全体のあう請求・支払い集計",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="請求された額（累計）", value=f"**{format_au_charge(totals['billed'])}**", inline=True)
        embed.add_field(name="支払った額（累計）", value=f"**{format_au_charge(totals['paid'])}**", inline=True)
        embed.add_field(name="未払い額", value=f"**{format_au_charge(totals['unpaid'])}**", inline=True)
        embed.add_field(name="請求回数", value=f"{totals['bill_count']}回", inline=True)
        embed.add_field(name="集計対象", value=f"{len(au_debt_records.get(str(interaction.guild.id), {}))}人", inline=True)

    embed.set_footer(text="支払いボタンの記録を集計。Bot内の残高・現金は変更しません。")
    await interaction.response.send_message(embed=embed, ephemeral=True)



# ==================================================
# 借金ランキング（現在額・累計額）
# ==================================================

def get_au_debt_ranking_rows(guild_id, ranking_type):
    """サーバー内の借金記録からランキングを作る。"""
    guild_data = au_debt_records.get(str(guild_id), {})
    field = "unpaid" if ranking_type == "current" else "billed"
    rows = []

    for user_id, record in guild_data.items():
        if not isinstance(record, dict):
            continue
        try:
            amount = max(0, int(record.get(field, 0)))
        except (TypeError, ValueError):
            amount = 0

        # 現在額は未払い0円を除外。累計は請求履歴がある人だけ表示。
        if amount > 0:
            rows.append((str(user_id), amount))

    rows.sort(key=lambda item: (-item[1], int(item[0]) if item[0].isdigit() else 0))
    return rows


class AuDebtRankingView(discord.ui.View):
    def __init__(self, ctx, ranking_type, rows):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.ranking_type = ranking_type
        self.rows = rows
        self.page = 0
        self.per_page = 10
        self.message = None
        self.update_buttons()

    @property
    def max_page(self):
        return max(0, (len(self.rows) - 1) // self.per_page)

    def update_buttons(self):
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.max_page

    def make_embed(self):
        is_current = self.ranking_type == "current"
        title = "💸 現在の借金ランキング" if is_current else "🏆 累計借金ランキング"
        field = "unpaid" if is_current else "billed"
        start = self.page * self.per_page
        page_rows = self.rows[start:start + self.per_page]

        if page_rows:
            lines = []
            for index, (user_id, amount) in enumerate(page_rows, start=start + 1):
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, f"**{index}.**")
                lines.append(f"{medal} <@{user_id}> — **{format_au_charge(amount)}**")
            description = "\n".join(lines)
        else:
            description = "ランキング対象者はいないよ。"

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.gold() if is_current else discord.Color.blurple(),
        )
        embed.set_footer(
            text=f"対象：このサーバーのみ / {self.page + 1}ページ目・全{self.max_page + 1}ページ"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "このランキングのページ操作は、表示した本人だけが使えるよ。",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="前へ", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="次へ", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.max_page, self.page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass


async def send_au_debt_ranking(ctx, ranking_type):
    if ctx.guild is None:
        await ctx.send("このコマンドはサーバー内で使ってね。")
        return

    rows = get_au_debt_ranking_rows(ctx.guild.id, ranking_type)
    view = AuDebtRankingView(ctx, ranking_type, rows)
    view.message = await ctx.send(embed=view.make_embed(), view=view)


@bot.command(name="debtランキング", aliases=["debt_rank", "借金ランキング"])
async def au_current_debt_ranking_command(ctx: commands.Context):
    """現在の未払い借金ランキングを表示する。"""
    await send_au_debt_ranking(ctx, "current")


@bot.command(name="debt累計ランキング", aliases=["debt_totalランキング", "累計借金ランキング"])
async def au_total_debt_ranking_command(ctx: commands.Context):
    """累計請求額ランキングを表示する。"""
    await send_au_debt_ranking(ctx, "total")


@bot.command(name="debt自分", aliases=["debt_me", "自分の借金"])
async def au_my_debt_command(ctx: commands.Context):
    """自分の請求額・支払い済み・未払い額を表示する。"""
    if ctx.guild is None:
        await ctx.send("このコマンドはサーバー内で使ってね。")
        return

    record = au_debt_records.get(str(ctx.guild.id), {}).get(str(ctx.author.id), {})
    def safe_amount(key):
        try:
            return max(0, int(record.get(key, 0)))
        except (TypeError, ValueError, AttributeError):
            return 0

    embed = discord.Embed(
        title="📊 自分の借金状況",
        description=f"対象：{ctx.author.mention}",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="現在の未払い額", value=f"**{format_au_charge(safe_amount('unpaid'))}**", inline=True)
    embed.add_field(name="請求された額（累計）", value=f"**{format_au_charge(safe_amount('billed'))}**", inline=True)
    embed.add_field(name="支払った額（累計）", value=f"**{format_au_charge(safe_amount('paid'))}**", inline=True)
    embed.add_field(name="請求回数", value=f"{safe_amount('bill_count')}回", inline=True)
    await ctx.send(embed=embed)


@au_group.command(name="setting", description="あう検知・タイムアウト・ホワイトリスト・請求上限を設定")
async def au_setting_command(interaction: discord.Interaction):
    if not await require_owner(interaction):
        return
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
        return

    config = get_au_settings(interaction.guild.id)
    whitelist_count = len(config.get("whitelist", []))
    timeout_text = (
        f"ON（{config.get('timeout_seconds', 60)}秒）"
        if config.get("timeout_enabled", False)
        else "OFF"
    )
    embed = discord.Embed(
        title="😅 あう検知設定",
        description="下のボタンから、このサーバーの設定を変更できるよ。",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="あう検知", value="ON" if config.get("enabled", True) else "OFF", inline=True)
    embed.add_field(name="自動タイムアウト", value=timeout_text, inline=True)
    embed.add_field(name="ホワイトリスト", value=f"{whitelist_count}人", inline=True)
    embed.add_field(
        name="1回あたりの請求上限",
        value=format_au_charge(config.get("charge_limit", 1000)),
        inline=True,
    )
    min_charge = config.get("charge_min")
    max_charge = config.get("charge_max")
    extremes_text = (
        f"最高：{format_au_charge(max_charge)} / 最低：{format_au_charge(min_charge)}"
        if min_charge is not None and max_charge is not None
        else "まだ記録なし"
    )
    exempt_count = len(config.get("timeout_exempt_channels", []))
    embed.add_field(
        name="請求額の最高・最低",
        value=f"表示：{'ON' if config.get('show_charge_extremes', False) else 'OFF'}\n{extremes_text}",
        inline=True,
    )
    embed.add_field(name="タイムアウト対象外CH", value=f"{exempt_count}チャンネル", inline=True)
    embed.add_field(
        name="タイムアウト仕様",
        value="1〜86400秒で指定可能。Discord側は1時間に設定し、指定時間後に自動解除するよ。",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, view=AuSettingPanelView(), ephemeral=True)


bot.tree.add_command(au_group)


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

                    elif "HIGH&LOW" in title:
                        user_match = re.search(r"ユーザー：.*?`(\d+)`", description)
                        if "ベットログ" in title:
                            balance_match = re.search(                                r"ベット後残高：\*\*([+-]?\$?[\d,]+)\*\*",
                                description,
                            )
                        else:
                            balance_match = re.search(                                r"残高：\*\*([+-]?\$?[\d,]+)\*\*",
                                description,
                            )
                        if user_match and balance_match:
                            combined_logs.append({
                                "type": "highlow",
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
from io import BytesIO
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
# ブラックジャック用カスタム絵文字
# ==========================================

BJ_EMOJI_GUILD_SPLITS = {
    1573260159403294793: range(625, 652),
    1573260415474073660: range(652, 679),
}
BJ_EMOJI_MAP_FILE = Path(os.getenv("DATA_DIR", ".")) / "bj_emoji_map.json"
BJ_EMOJI_DONE_FILE = Path(os.getenv("DATA_DIR", ".")) / "bj_emoji_registration_done.json"
bj_emoji_map = load_json(BJ_EMOJI_MAP_FILE, {})
bj_emoji_registration_done = load_json(BJ_EMOJI_DONE_FILE, False)


def get_bj_emoji(file_number):
    data = bj_emoji_map.get(str(int(file_number)))
    if not isinstance(data, dict):
        return None
    emoji_id = data.get("id")
    emoji_name = data.get("name")
    if not emoji_id or not emoji_name:
        return None
    return f"<:{emoji_name}:{emoji_id}>"


def get_card_emoji(suit, value):
    path = get_card_image_path(suit, value)
    match = re.search(r"IMG_(\d+)\.png$", path)
    if not match:
        return None
    return get_bj_emoji(int(match.group(1)))


def prepare_bj_emoji_image(path):
    """カード全体を切らずに透明背景の128x128絵文字画像へ収める。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"カード画像が見つかりません: {path}")

    with Image.open(path) as source:
        card = source.convert("RGBA")
        resampling = getattr(Image, "Resampling", Image)
        card.thumbnail((112, 112), resampling.LANCZOS)
        # 余白は完全な透明にし、カード画像の見た目はそのまま残す。
        canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        x = (128 - card.width) // 2
        y = (128 - card.height) // 2
        canvas.alpha_composite(card, (x, y))
        buffer = BytesIO()
        canvas.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


@app_commands.guilds(
    discord.Object(id=1573260159403294793),
    discord.Object(id=1573260415474073660),
)
@bot.tree.command(
    name="bj-emoji-register",
    description="ブラックジャックのカード絵文字54個を2つのサーバーに登録する（一度だけ）",
)
async def register_bj_emojis(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild.id not in BJ_EMOJI_GUILD_SPLITS:
        await interaction.response.send_message(
            "このコマンドは指定された2つのサーバーでのみ使えます。",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    target_guilds = {}
    prepared = {}
    try:
        # 登録前に両サーバーの権限・空き枠・全画像をまとめて確認する
        for guild_id, file_numbers in BJ_EMOJI_GUILD_SPLITS.items():
            guild = bot.get_guild(guild_id)
            if guild is None:
                raise RuntimeError(f"Botがサーバー {guild_id} に参加していません。")

            bot_member = guild.get_member(bot.user.id) if bot.user else None
            if bot_member is None or not bot_member.guild_permissions.manage_emojis_and_stickers:
                raise RuntimeError(
                    f"サーバー {guild_id} でBotに「絵文字とスタンプの管理」権限がありません。"
                )

            wanted_names = {f"bj_{number}" for number in file_numbers}
            existing = {
                emoji.name: emoji
                for emoji in guild.emojis
                if emoji.name in wanted_names
            }
            missing = [
                number for number in file_numbers
                if f"bj_{number}" not in existing
            ]
            available = guild.emoji_limit - len(guild.emojis)
            if len(missing) > available:
                raise RuntimeError(
                    f"サーバー {guild_id} の空き枠不足。必要: {len(missing)}個 / 空き: {available}個"
                )

            target_guilds[guild_id] = (guild, existing)
            for number in file_numbers:
                prepared[number] = prepare_bj_emoji_image(
                    f"cards/IMG_{number:04d}.png"
                )

    except Exception as error:
        await interaction.edit_original_response(
            content=f"登録前チェックで停止したよ。\n{error}"
        )
        return

    new_map = dict(bj_emoji_map)
    completed = 0
    failed = []
    total = sum(len(numbers) for numbers in BJ_EMOJI_GUILD_SPLITS.values())

    for guild_id, file_numbers in BJ_EMOJI_GUILD_SPLITS.items():
        guild, existing = target_guilds[guild_id]
        for number in file_numbers:
            name = f"bj_{number}"
            emoji = existing.get(name)

            if emoji is None:
                # 一時的なDiscord側エラーだけ最大3回まで再試行する。
                for attempt in range(3):
                    try:
                        emoji = await guild.create_custom_emoji(
                            name=name,
                            image=prepared[number],
                            reason="ブラックジャック用カード絵文字の一括登録",
                        )
                        break
                    except discord.HTTPException as error:
                        if error.status not in (500, 502, 503, 504) or attempt == 2:
                            failed.append(f"{name}: {error}")
                            break
                        await asyncio.sleep(1.5 * (attempt + 1))
                    except Exception as error:
                        failed.append(f"{name}: {error}")
                        break

            if emoji is not None:
                new_map[str(number)] = {
                    "guild_id": guild_id,
                    "id": emoji.id,
                    "name": emoji.name,
                }
                completed += 1

            # 3個ごとに進捗を更新。大量の編集リクエストも避ける。
            if completed % 3 == 0 or completed == total or (number == list(file_numbers)[-1]):
                status = f"絵文字登録中：{completed}/{total}個"
                if failed:
                    status += f"\n失敗：{len(failed)}個（最後まで続けるよ）"
                try:
                    await interaction.edit_original_response(content=status)
                except discord.HTTPException:
                    pass

        # サーバーごとに途中経過を保存し、失敗時も成功分を失わない
        save_json(BJ_EMOJI_MAP_FILE, new_map)

    bj_emoji_map.clear()
    bj_emoji_map.update(new_map)

    if not failed and completed == total:
        save_json(BJ_EMOJI_DONE_FILE, True)
        bj_emoji_registration_done = True
        for guild_id in BJ_EMOJI_GUILD_SPLITS:
            await bot.tree.sync(guild=discord.Object(id=guild_id))
        await interaction.edit_original_response(
            content=(
                f"登録完了！ {completed}/{total}個\n"
                "サーバー①：27個\nサーバー②：27個"
            )
        )
    else:
        save_json(BJ_EMOJI_DONE_FILE, False)
        bj_emoji_registration_done = False
        detail = "\n".join(failed[:12])
        await interaction.edit_original_response(
            content=(
                f"登録処理終了：成功 {completed}/{total}個、失敗 {len(failed)}個。\n"
                "成功したIDは保存済み。もう一度コマンドを実行すると、残りだけ登録するよ。\n"
                + detail
            )[:1900]
        )


@app_commands.guilds(
    discord.Object(id=1573260159403294793),
    discord.Object(id=1573260415474073660),
)
@bot.tree.command(
    name="bj-emoji-delete",
    description="ブラックジャック用のカード絵文字54個を両サーバーから削除する",
)
async def delete_bj_emojis(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild.id not in BJ_EMOJI_GUILD_SPLITS:
        await interaction.response.send_message(
            "このコマンドは指定された2つのサーバーでのみ使えます。",
            ephemeral=True,
        )
        return

    if interaction.user.id != OWNER_USER_ID:
        await interaction.response.send_message(
            "この操作はBot所有者だけが実行できます。",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    deleted = 0
    errors = []

    for guild_id, file_numbers in BJ_EMOJI_GUILD_SPLITS.items():
        guild = bot.get_guild(guild_id)
        if guild is None:
            errors.append(f"サーバー {guild_id}: Botが参加していません")
            continue

        bot_member = guild.get_member(bot.user.id) if bot.user else None
        if bot_member is None or not bot_member.guild_permissions.manage_emojis_and_stickers:
            errors.append(f"サーバー {guild_id}: Botに絵文字管理権限がありません")
            continue

        target_names = {f"bj_{number}" for number in file_numbers}
        for emoji in list(guild.emojis):
            if emoji.name not in target_names:
                continue
            try:
                await emoji.delete(reason="ブラックジャックカード絵文字の透明背景版へ入れ替え")
                deleted += 1
            except Exception as error:
                errors.append(f"{guild.name}/{emoji.name}: {error}")

    # 登録済みIDを破棄し、透明背景版を再登録できる状態に戻す
    new_map = {
        key: value for key, value in bj_emoji_map.items()
        if not (str(key).isdigit() and 625 <= int(key) <= 678)
    }
    save_json(BJ_EMOJI_MAP_FILE, new_map)
    bj_emoji_map.clear()
    bj_emoji_map.update(new_map)
    save_json(BJ_EMOJI_DONE_FILE, False)
    bj_emoji_registration_done = False

    result = f"削除した絵文字: {deleted}/54個"
    if errors:
        result += "\n一部削除できなかったよ:\n" + "\n".join(errors[:8])
    else:
        result += "\n54個の登録枠を空けたよ。次に /bj-emoji-register を実行してね。"
    await interaction.followup.send(result[:1900], ephemeral=True)


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

        # Add transparent side margins so Discord displays the cards smaller.
        margin = table_img.width // 3
        padded_img = Image.new(
            "RGBA",
            (table_img.width + margin * 2, table_img.height),
            (0, 0, 0, 0)
        )
        padded_img.paste(table_img, (margin, 0), table_img)
        table_img = padded_img

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
                f"{card['suit'].upper()} {card['val']}"
                for card in self.player_hand
            )

            # ディーラーの手札
            dealer_cards = ", ".join(
                f"{card['suit'].upper()} {card['val']}"
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
            "You cannot control another player's game.",
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

            result = "DEALER BUSTS — YOU WIN! 🎉"
            outcome = "win"

        elif p_score > d_score:

            result = "YOU WIN! 🏆"
            outcome = "win"

        elif p_score < d_score:

            result = "YOU LOSE 😢"
            outcome = "lose"

        else:

            result = "PUSH 🤝"
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
                "TIMEOUT — BET FORFEITED",
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
        label="HIT",
        style=discord.ButtonStyle.green
    )
    async def hit(
        self,        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.defer()

        async with self.lock:

            if self.game_over:

                await self.send_error(
                    interaction,
                    "This game has ended."
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
                        "BUST — YOU LOSE 😭",
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
                    "An error occurred."
                )

    # ======================================
    # スタンド    # ======================================

    @discord.ui.button(
        label="STAND",
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
                    "This game has ended."
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
                    "An error occurred."
                )

    # ======================================
    # ダブルダウン
    # ======================================

    @discord.ui.button(
        label="DOUBLE",
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
                    "This game has ended."
                )
                return

            # 使用済みなら拒否
            if self.doubled_down or not self.can_double_down:

                button.disabled = True

                await self.send_error(
                    interaction,
                    "Double is not available."
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
                        f"Insufficient balance.\n"
                        f"Additional amount required: {bj_money(additional_bet)}\n"
                        f"Current balance: {bj_money(current_balance)}"
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
                        "DOUBLE BUST — YOU LOSE 😭",
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
            title="🃏 BLACKJACK",
            color=color
        )

        p_score = calculate_hand(self.player_hand)
        d_score = calculate_hand(self.dealer_hand)

        # ----------------------------------
        # ディーラーのカード（カスタム絵文字）
        # ----------------------------------

        if game_over:
            dealer_text = f"HAND (TOTAL: {d_score})"
            dealer_emojis = [
                get_card_emoji(card["suit"], card["val"])
                or f"{card['suit'].upper()} {card['val']}"
                for card in self.dealer_hand
            ]
            d_cards_str = " ".join(dealer_emojis)
        else:
            dealer_text = "HAND (2ND CARD HIDDEN)"
            first_card = self.dealer_hand[0]
            first_emoji = (
                get_card_emoji(first_card["suit"], first_card["val"])
                or f"{first_card['suit'].upper()} {first_card['val']}"
            )
            back_emoji = get_card_emoji("back", 0) or "HIDDEN"
            d_cards_str = f"{first_emoji} {back_emoji}"

        # ----------------------------------
        # プレイヤーのカード（カスタム絵文字）
        # ----------------------------------

        player_emojis = [
            get_card_emoji(card["suit"], card["val"])
            or f"{card['suit'].upper()} {card['val']}"
            for card in self.player_hand
        ]
        p_cards_str = " ".join(player_emojis)

        files = []

        # ----------------------------------
        # 手札表示
        # ----------------------------------

        embed.add_field(
            name=f"DEALER {dealer_text}",
            value=d_cards_str,
            inline=False
        )

        embed.add_field(
            name=f"PLAYER HAND (TOTAL: {p_score})",
            value=p_cards_str,
            inline=False
        )

        # ----------------------------------
        # 賭け金表示
        # ----------------------------------

        embed.add_field(
            name="💰 BET",
            value=bj_money(self.bet),
            inline=True
        )

        if self.doubled_down:

            embed.add_field(
                name="EXTRA BET",
                value=bj_money(self.original_bet),
                inline=True
            )

        # ----------------------------------
        # 終了後
        # ----------------------------------

        if game_over:

            embed.add_field(
                name="RESULT",
                value=self.final_result,
                inline=False
            )

            embed.add_field(
                name="📊 PROFIT",
                value=f"**{bj_money_change(self.final_profit)}**",
                inline=True
            )

            embed.add_field(
                name="💵 RETURN",
                value=f"**{bj_money(self.final_returned)}**",
                inline=True
            )

            embed.set_footer(
                text="BLACKJACK • GAME OVER"
            )

        else:

            embed.add_field(
                name="🎮 ACTIONS",
                value=(
                    "HIT: Draw a card\n"
                    "STAND: Keep your hand\n"
                    "DOUBLE: Double your bet and draw one card"
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
            f"Insufficient balance.\n"
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
                "BOTH BLACKJACK — PUSH 🤝",
                "push"
            )

        elif player_bj:

            view.finish_game(
                "NATURAL BLACKJACK — YOU WIN! 🎉",
                "bj"
            )

        elif dealer_bj:

            view.finish_game(
                "DEALER BLACKJACK — YOU LOSE",
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

        print(f"[BJ START ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

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
                description=(                    f"ユーザー：{ctx.author.mention} (`{ctx.author.id}`)\n"
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
# 所持金管理システム（必要に応じて既存のDBや別ファイルのものに変更してください）
# ==================================================
USER_BALANCES = {}  # ユーザーID: 所持金 の辞書


def get_user_balance(user_id: int) -> int:
  # 初期所持金は 1000 コインとする
  return USER_BALANCES.get(user_id, 1000)


def update_user_balance(user_id: int, amount: int):
  current = get_user_balance(user_id)
  USER_BALANCES[user_id] = current + amount


import asyncio
import os
import random
import discord
from discord.ext import commands

# ==================================================
# 共通の所持金管理（本来の残高と完全共有）
# ==================================================
# balances / get_balance / set_balance は上部の共通残高システムを使用する。
# ここでJSONを再読み込みすると、メモリ上の最新残高を古い内容で上書きする
# 原因になるため、再読み込みや関数の再定義はしない。

def update_user_balance(user_id: int, amount: int):
  current = get_balance(user_id)
  set_balance(user_id, current + int(amount))


import asyncio
import os
import random
from discord import ui
import discord
from PIL import Image

# ==================================================
# ハイ＆ロー 設定
# ==================================================

HL_SUITS = ["spade", "club", "diamond", "heart"]
HL_RANKS = {
    1: "A",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "10",
    11: "J",
    12: "Q",
    13: "K",
}


def hl_make_deck():
  deck = [
      {"suit": suit, "val": value} for suit in HL_SUITS for value in HL_RANKS
  ]
  deck.extend([
      {"suit": "joker", "val": "JOKER"},
      {"suit": "joker", "val": "JOKER"},
  ])
  random.shuffle(deck)
  return deck


def hl_card_label(card):
  if card["suit"] == "joker":
    return "🃏 JOKER"
  suit_symbols = {
      "spade": "♠",
      "club": "♣",
      "diamond": "♦",
      "heart": "♥",
  }
  return f"{suit_symbols[card['suit']]} {HL_RANKS[card['val']]}"


def hl_card_image_path(card):
  return get_card_image_path(card["suit"], card["val"])


def calculate_odds(deck: list, current_card: dict, high: bool) -> float:
  """残りデッキと現在のカードから、HIGH/LOWのオッズ（倍率）を確率に基づいて計算する"""
  if current_card["suit"] == "joker":
    return 2.0

  old_val = current_card["val"]
  total_remaining = len(deck)
  if total_remaining == 0:
    return 1.0

  count_target = 0
  for card in deck:
    if card["suit"] == "joker":
      continue
    if high and card["val"] > old_val:
      count_target += 1
    elif not high and card["val"] < old_val:
      count_target += 1

  if count_target == 0:
    return 0.0

  probability = count_target / total_remaining
  raw_odds = 1.0 / probability
  odds = round(raw_odds * 0.95, 2)

  return max(odds, 1.05)


class HighLowButton(ui.Button):

  def __init__(self, label, style, action_type, disabled=False):
    super().__init__(label=label, style=style, disabled=disabled)
    self.action_type = action_type

  async def callback(self, interaction: discord.Interaction):
    view: HighLowView = self.view
    if self.action_type == "high":
      await view.choose(interaction, True)
    elif self.action_type == "low":
      await view.choose(interaction, False)
    elif self.action_type == "same":
      await view.choose(interaction, None)
    elif self.action_type == "fin":
      await view.finish(
          interaction,
          f"ゲームを終了して精算したよ！連続正解：**{view.streak}回**",
          won=True,
      )


class HighLowView(discord.ui.LayoutView):

  def __init__(self, owner_id: int, deck: list, current: dict, bet: int, guild):
    super().__init__(timeout=180)
    self.owner_id = owner_id
    self.guild = guild
    self.deck = deck
    self.current = current
    self.bet = bet
    self.current_prize = bet
    self.streak = 0
    self.finished = False
    self.end_status = None
    self.final_profit = 0
    self.image_path = f"cards/hl_{id(self)}.png"
    self.lock = asyncio.Lock()

    self.render_cards(show_back=True)
    self.rebuild_container()

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    if interaction.user.id != self.owner_id:
      await interaction.response.send_message(
          "このハイ＆ローを開始した人だけ操作できます。",
          ephemeral=True,
      )
      return False
    if self.finished:
      await interaction.response.send_message(
          "This game has ended.",
          ephemeral=True,
      )
      return False
    return True

  def render_cards(self, show_back=True):
    paths = [hl_card_image_path(self.current)]
    if show_back:
      paths.append(get_card_image_path("back", 0))
    image = merge_horizontal(paths)
    if image is None:
      return False

    margin = image.width // 2 if not show_back else image.width // 4
    canvas = Image.new(
        "RGB",
        (image.width + margin * 2, image.height),
        (0, 128, 0),
    )
    if image.mode == "RGBA":
      canvas.paste(image, (margin, 0), image)
    else:
      canvas.paste(image, (margin, 0))
    image = canvas

    image.save(self.image_path, format="PNG")
    return True

  def rebuild_container(self, show_back=True):
    self.clear_items()

    high_odds = calculate_odds(self.deck, self.current, True)
    low_odds = calculate_odds(self.deck, self.current, False)

    if self.finished:
      result_line = f"### {self.end_status}"
      won_value = f"+{self.final_profit:,}$" if self.final_profit > 0 else "0$"
      desc_text = (
          f"{result_line}\n\n"
          f"**Bet** : **{self.bet:,}$**\n"
          f"**Won** : **{won_value}**"
      )
      if self.end_status != "Cash out":
        desc_text += (
            f"\n\n**Odds**\n"
            f"HIGH : **{high_odds}x**\n"
            f"LOW : **{low_odds}x**\n"
            f"SAME : **10x**"
        )
    else:
      desc_text = (
          f"### HIGH&LOW\n\n"
          f"**Combo** : **{self.streak}**\n"
          f"**Bet** : **{self.bet:,}$**\n"
          f"**Won** : **{int(self.current_prize):,}$**\n\n"
          f"**Odds**\n"
          f"HIGH : **{high_odds}x**\n"
          f"LOW : **{low_odds}x**\n"
          f"SAME : **10x**"
      )

    accent_color = None
    if self.finished:
      if self.end_status == "Lose":
        accent_color = discord.Color.red()
      elif self.end_status == "Cash out":
        accent_color = discord.Color.green()

    container = ui.Container(
        ui.TextDisplay(desc_text),
        ui.MediaGallery(
            discord.MediaGalleryItem(
                media=f"attachment://{os.path.basename(self.image_path)}"
            )
        ),
        ui.TextDisplay(f"-# {len(self.deck)} cards"),
        ui.ActionRow(
            HighLowButton(
                "HIGH",
                discord.ButtonStyle.success,
                "high",
                disabled=self.finished,
            ),
            HighLowButton(
                "LOW", discord.ButtonStyle.danger, "low", disabled=self.finished
            ),
            HighLowButton(
                "SAME", discord.ButtonStyle.primary, "same", disabled=self.finished
            ),
            HighLowButton(
                "FIN",
                discord.ButtonStyle.secondary,
                "fin",
                disabled=self.finished,
            ),
        ),
        accent_color=accent_color,
    )

    self.add_item(container)

  async def update_message(
      self, interaction, description, show_back=True, disable=False
  ):
    self.rebuild_container(show_back=show_back)
    file = discord.File(
        self.image_path, filename=os.path.basename(self.image_path)
    )

    await interaction.response.edit_message(
        view=self,
        attachments=[file],
    )

  async def finish(self, interaction, message, won=False):
    if self.finished:
      return
    self.finished = True

    final_payout = int(self.current_prize) if won else 0
    self.end_status = "Cash out" if won else "Lose"
    self.final_profit = final_payout - self.bet if won else 0
    if final_payout > 0:
      update_user_balance(self.owner_id, final_payout)

    final_balance = get_balance(self.owner_id)
    if self.guild is not None:
      record_coin({
          "type": "highlow_settlement",
          "guild_id": self.guild.id,
          "user_id": str(self.owner_id),
          "balance": final_balance,
      })
    profit = final_payout - self.bet
    if won:
      message += f"\n\n💰 **+{final_payout:,} コイン** を獲得しました！（所持金: {final_balance:,} コイン）"
    else:
      message += f"\n\n💸 賭け金 **{self.bet:,} コイン** を失いました…（所持金: {final_balance:,} コイン）"

    if self.guild is not None:
      await send_coin_log(
          self.guild,
          discord.Embed(
              title="🃏 HIGH&LOW 精算ログ",
              description=(
                  f"ユーザー：<@{self.owner_id}> (`{self.owner_id}`)\n"
                  f"賭け金：**{money(self.bet)}**\n"
                  f"配当：**{money(final_payout)}**\n"
                  f"収支：**{money_change(profit)}**\n"
                  f"残高：**{money(final_balance)}**\n"
                  f"Combo：**{self.streak}**"
              ),
              color=discord.Color.green() if won else discord.Color.red(),
          ),
      )

    await self.update_message(
        interaction, message, show_back=False, disable=True
    )

  async def choose(self, interaction, high=None):
    async with self.lock:
      if self.finished:
        await interaction.response.send_message(
            "This game has ended.",
            ephemeral=True,
        )
        return

      if not self.deck:
        await self.finish(
            interaction,
            f"山札がなくなったよ！連続正解：**{self.streak}回**",
            won=True,
        )
        return

      odds = None if high is None else calculate_odds(self.deck, self.current, high)
      if high is not None and odds <= 0.0:
        await interaction.response.send_message(
            "その選択肢に該当するカードが残っていません！別のほうを選んでね。",
            ephemeral=True,
        )
        return

      next_card = self.deck.pop()
      old_rank = self.current["val"]
      next_rank = next_card["val"]

      if self.current["suit"] == "joker" or next_card["suit"] == "joker":
        self.current = next_card
        self.render_cards(show_back=True)
        await self.update_message(
            interaction,
            f"🃏 ジョーカー！引き分けだよ。連続正解数と賞金はそのまま。\n次のカードは HIGH？ LOW？",
        )
        return

      if high is None:
        self.current = next_card
        self.render_cards(show_back=False)
        if old_rank == next_rank:
          self.current_prize = self.bet * 10
          await self.finish(
              interaction,
              f"🎯 SAME成功！同じ数字だよ！**10倍払い出し**！",
              won=True,
          )
        else:
          await self.finish(
              interaction,
              f"❌ SAME失敗！次のカードは **{hl_card_label(next_card)}** でした。",
              won=False,
          )
        return

      if old_rank == next_rank:
        self.current = next_card
        self.render_cards(show_back=True)
        await self.update_message(
            interaction,
            f"同じ数字なので引き分け！連続正解数と賞金はそのまま。\n次のカードは HIGH？ LOW？",
        )
        return

      correct = (next_rank > old_rank) if high else (next_rank < old_rank)
      self.current = next_card
      self.render_cards(show_back=True)

      if correct:
        self.streak += 1
        earned_bonus = int(self.bet * (odds - 1.0))
        if earned_bonus < 1:
          earned_bonus = 1
        self.current_prize += earned_bonus

        await self.update_message(
            interaction,
            f"✅ 正解！(+{earned_bonus:,}コイン / オッズ{odds}倍) 次のカードは **{hl_card_label(next_card)}**！\n次のカードは HIGH？ LOW？",
        )
      else:
        await self.finish(
            interaction,
            f"❌ 不正解！次のカードは **{hl_card_label(next_card)}** でした。\n連続正解：**{self.streak}回**",
            won=False,
        )

  async def on_timeout(self):
    if not self.finished:
      self.finished = True
      final_balance = get_balance(self.owner_id)
      if self.guild is not None:
        record_coin({
            "type": "highlow_timeout",
            "guild_id": self.guild.id,
            "user_id": str(self.owner_id),
            "balance": final_balance,
        })
        await send_coin_log(
            self.guild,
            discord.Embed(
                title="🃏 HIGH&LOW タイムアウトログ",
                description=(
                    f"ユーザー：<@{self.owner_id}> (`{self.owner_id}`)\n"
                    f"賭け金：**{money(self.bet)}**\n"
                    f"配当：**{money(0)}**\n"
                    f"収支：**{money_change(-self.bet)}**\n"
                    f"残高：**{money(final_balance)}**\n"
                    f"Combo：**{self.streak}**"
                ),
                color=discord.Color.red(),
            ),
        )
    try:
      if os.path.exists(self.image_path):
        os.remove(self.image_path)
    except OSError:
      pass


# ==================================================
# ==================================================
# TREASURE HUNT
# ==================================================

TH_LANES = 9
TH_GREEN_DEPTH = 3
TH_BROWN_DEPTH = 6
TH_LANE_LABELS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"]
active_treasure_hunt_users = set()


class TreasureHuntView(discord.ui.View):
    def __init__(self, ctx, bet_amount, lane):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.owner_id = ctx.author.id
        self.guild = ctx.guild
        self.bet = int(bet_amount)
        self.lock = asyncio.Lock()
        self.finished = False
        self.message = None
        self.selected_lane = int(lane) - 1
        self.total_digs = 0
        self.profit = 0
        self.found = []

        # 緑3段のどこか1マスに💰
        self.money_cell = (
            random.randrange(TH_LANES),
            random.randrange(TH_GREEN_DEPTH),
        )

        # 各レーンは30%の確率で💎なし、70%の確率で💎を1個配置
        self.diamonds = {
            lane: (None if random.random() < 0.30 else random.randrange(TH_BROWN_DEPTH))
            for lane in range(TH_LANES)
        }

        # 宝箱は25%の確率で1個だけ配置
        # 配置する場合、80%の確率でダイヤと同じレーンの「ダイヤより下」に置く
        self.chest = None
        if random.random() < 0.25:
            below_diamond_positions = [
                (lane, depth)
                for lane in range(TH_LANES)
                for depth in range(TH_BROWN_DEPTH)
                if self.diamonds[lane] is not None
                and depth > self.diamonds[lane]
            ]

            all_possible_positions = [
                (lane, depth)
                for lane in range(TH_LANES)
                for depth in range(TH_BROWN_DEPTH)
                if self.diamonds[lane] != depth
            ]

            if below_diamond_positions and random.random() < 0.80:
                self.chest = random.choice(below_diamond_positions)
            else:
                self.chest = random.choice(all_possible_positions)

        # 各レーンは50%の確率で、茶色6段のどこかに岩を1個配置
        self.rocks = set()
        for lane in range(TH_LANES):
            if random.random() < 0.5:
                possible = [
                    depth for depth in range(TH_BROWN_DEPTH)
                    if self.diamonds[lane] != depth
                    and self.chest != (lane, depth)
                ]
                if possible:
                    self.rocks.add((lane, random.choice(possible)))

        # 選んだレーンの掘削位置。0〜2=緑、3〜8=茶色
        self.depths = [0] * TH_LANES
        self.revealed = [
            [None for _ in range(TH_GREEN_DEPTH + TH_BROWN_DEPTH)]
            for _ in range(TH_LANES)
        ]

        self.add_item(TreasureHuntDigButton())
        self.add_item(TreasureHuntAllDigButton())
        self.add_item(TreasureHuntFinButton())

    def render_map(self, reveal_all=False):
        # Discord上で数字と9列をそろえるため、等幅コードブロックで表示
        lines = [" ".join(TH_LANE_LABELS)]
        for depth in range(TH_GREEN_DEPTH + TH_BROWN_DEPTH):
            row = []
            for lane in range(TH_LANES):
                cell = self.revealed[lane][depth]
                if reveal_all and depth < TH_GREEN_DEPTH:
                    if self.money_cell == (lane, depth):
                        cell = "💰"
                    elif cell is None:
                        cell = "🟩"
                elif reveal_all and depth >= TH_GREEN_DEPTH:
                    brown_depth = depth - TH_GREEN_DEPTH
                    if self.diamonds[lane] == brown_depth:
                        cell = "💎"
                    elif self.chest == (lane, brown_depth):
                        cell = "🪎"
                    elif (lane, brown_depth) in self.rocks:
                        cell = "🪨"
                    elif cell is None:
                        cell = "🟫"
                elif cell is None:
                    cell = "🟩" if depth < TH_GREEN_DEPTH else "🟫"
                row.append(cell)
            lines.append("".join(row))
        return chr(96) * 3 + "\n" + "\n".join(lines) + "\n" + chr(96) * 3

    def make_embed(self, status=None, reveal_all=False):
        embed = discord.Embed(
            title="⛏️ TREASURE HUNT",
            description=self.render_map(reveal_all=reveal_all),
            color=discord.Color.gold() if self.finished else discord.Color.green(),
        )
        lane_text = TH_LANE_LABELS[self.selected_lane] if self.selected_lane is not None else "-"
        result_text = status or ("\n".join(self.found[-3:]) if self.found else "-")
        embed.add_field(
            name="STATUS",
            value=(
                f"Bet : {money(self.bet)}\n"
                f"Digs : {self.total_digs}\n"
                f"Won : {money_change(self.profit)}\n"
                f"Balance : {money(get_balance(self.owner_id))}\n"
                f"LANE : {lane_text}\n"
                f"Result : {result_text}"
            ),
            inline=False,
        )
        return embed

    async def select_lane(self, interaction, lane):
        async with self.lock:
            if self.finished:
                await interaction.response.send_message("This game has ended.", ephemeral=True)
                return
            if self.selected_lane is not None and self.selected_lane != lane:
                await interaction.response.send_message(
                    f"レーン{TH_LANE_LABELS[self.selected_lane]}を選択済みだよ。他のレーンには変更できないよ。",
                    ephemeral=True,
                )
                return
            self.selected_lane = lane
            # レーン選択後は①〜⑨の選択ボタンを表示から取り除く
            for item in list(self.children):
                if isinstance(item, TreasureHuntLaneButton):
                    self.remove_item(item)
            await interaction.response.edit_message(
                embed=self.make_embed(f"レーン {TH_LANE_LABELS[lane]} を選択したよ。DIGで掘ってね。"),
                view=self,
            )

    async def dig_selected(self, interaction):
        await self.dig_lane(interaction, max_cells=1)

    async def dig_all_selected(self, interaction):
        await self.dig_lane(interaction, max_cells=None)

    async def dig_lane(self, interaction, max_cells=1):
        async with self.lock:
            if self.finished:
                await interaction.response.send_message("This game has ended.", ephemeral=True)
                return

            lane = self.selected_lane
            total_depth = TH_GREEN_DEPTH + TH_BROWN_DEPTH
            start_depth = self.depths[lane]
            if start_depth >= total_depth:
                await interaction.response.send_message("このレーンは一番下まで掘り終わっているよ。", ephemeral=True)
                return

            end_depth = total_depth if max_cells is None else min(total_depth, start_depth + max_cells)
            # ALL DIGは残りマスをまとめて掘る。必要額を先に確認し、不足時は何も掘らない。
            total_cost = 0
            for depth in range(start_depth, end_depth):
                brown_depth = depth - TH_GREEN_DEPTH
                is_rock = depth >= TH_GREEN_DEPTH and (lane, brown_depth) in self.rocks
                total_cost += self.bet * (2 if is_rock else 1)

            balance = get_balance(self.owner_id)
            if balance < total_cost:
                await interaction.response.send_message(
                    f"残高が足りないよ。必要額：**{money(total_cost)}** / 残高：**{money(balance)}**",
                    ephemeral=True,
                )
                return

            # ALL DIGは処理に時間がかかるため、先に応答を確定してUnknown interactionを防ぐ
            await interaction.response.defer()

            results = []
            for depth in range(start_depth, end_depth):
                brown_depth = depth - TH_GREEN_DEPTH
                is_rock = depth >= TH_GREEN_DEPTH and (lane, brown_depth) in self.rocks
                dig_cost = self.bet * 2 if is_rock else self.bet

                set_balance(self.owner_id, get_balance(self.owner_id) - dig_cost)
                self.profit -= dig_cost
                self.total_digs += 1

                result = None
                if depth < TH_GREEN_DEPTH:
                    if self.money_cell == (lane, depth):
                        multiplier = random.randint(9, 15)
                        payout = self.bet * multiplier
                        set_balance(self.owner_id, get_balance(self.owner_id) + payout)
                        self.profit += payout
                        result = f"💰 Green Money **{multiplier}x** / **+{money(payout)}**"
                        self.found.append(result)
                        self.revealed[lane][depth] = "💰"
                    else:
                        self.revealed[lane][depth] = "⬛"
                else:
                    if is_rock:
                        self.revealed[lane][depth] = "🪨"
                        result = f"🪨 ROCK / Dig cost **{money(dig_cost)} (2x)**"
                    elif self.diamonds[lane] == brown_depth:
                        diamond_type = random.choices(
                            ["Small Dia", "Medium Dia", "BIG Dia"],
                            weights=[75, 24, 1],
                            k=1,
                        )[0]
                        multiplier = {
                            "Small Dia": 5,
                            "Medium Dia": 15,
                            "BIG Dia": 75,
                        }[diamond_type]
                        payout = self.bet * multiplier
                        set_balance(self.owner_id, get_balance(self.owner_id) + payout)
                        self.profit += payout
                        result = f"💎 **{diamond_type}** / **{multiplier}x** / **+{money(payout)}**"
                        self.found.append(result)
                        self.revealed[lane][depth] = "💎"
                    elif self.chest == (lane, brown_depth):
                        payout = self.bet * 150
                        set_balance(self.owner_id, get_balance(self.owner_id) + payout)
                        self.profit += payout
                        result = f"🪎 **TREASURE CHEST** / **150x** / **+{money(payout)}**"
                        self.found.append(result)
                        self.revealed[lane][depth] = "🪎"
                    else:
                        self.revealed[lane][depth] = "⬛"

                self.depths[lane] = depth + 1
                if result:
                    results.append(result)

                current_balance = get_balance(self.owner_id)
                record_coin({
                    "type": "treasure_hunt_dig",
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                    "guild_id": self.guild.id if self.guild else None,
                    "user_id": str(self.owner_id),
                    "username": str(self.ctx.author),
                    "bet": self.bet,
                    "dig_cost": dig_cost,
                    "lane": lane + 1,
                    "depth": depth + 1,
                    "balance": current_balance,
                    "profit": self.profit,
                })

            if self.depths[lane] >= total_depth:
                self.finished = True
                active_treasure_hunt_users.discard(self.owner_id)
                for item in self.children:
                    item.disabled = True
                results.append("このレーンを最後まで掘ったよ。")
                await interaction.edit_original_response(
                    embed=self.make_embed("\n".join(results) or "ALL DIG 完了。", reveal_all=True),
                    view=self,
                )
                await self.send_final_log("レーン完掘")
                return

            if max_cells is None:
                status = f"ALL DIG — {end_depth - start_depth}マス掘ったよ。"
            else:
                status = f"レーン {TH_LANE_LABELS[lane]} を1マス掘ったよ。"
            if results:
                status += "\n" + "\n".join(results)
            await interaction.edit_original_response(embed=self.make_embed(status), view=self)

    async def finish_game(self, interaction):
        async with self.lock:
            if self.finished:
                await interaction.response.send_message("This game has ended.", ephemeral=True)
                return
            self.finished = True
            active_treasure_hunt_users.discard(self.owner_id)
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                embed=self.make_embed("FIN — ゲーム終了。本来の宝の位置を公開したよ。", reveal_all=True),
                view=self,
            )
            await self.send_final_log("FIN")

    async def send_final_log(self, reason):
        if self.guild is None:
            return
        try:
            await send_coin_log(
                self.guild,
                discord.Embed(
                    title="⛏️ TREASURE HUNT LOG",
                    description=(
                        f"ユーザー：{self.ctx.author.mention} (`{self.owner_id}`)\n"
                        f"BET / DIG：**{money(self.bet)}**\n"
                        f"Digs：**{self.total_digs}**\n"
                        f"Won：**{money_change(self.profit)}**\n"
                        f"残高：**{money(get_balance(self.owner_id))}**\n"
                        f"終了理由：{reason}"
                    ),
                    color=discord.Color.green() if self.profit >= 0 else discord.Color.red(),
                ),
            )
        except Exception:
            print("[TREASURE HUNT LOG ERROR]")
            traceback.print_exc()

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        active_treasure_hunt_users.discard(self.owner_id)
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    embed=self.make_embed("TIMEOUT — ゲーム終了。宝の位置を公開したよ。", reveal_all=True),
                    view=self,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self.send_final_log("タイムアウト")


class TreasureHuntLaneButton(discord.ui.Button):
    def __init__(self, lane):
        super().__init__(
            label=TH_LANE_LABELS[lane],
            style=discord.ButtonStyle.success,
            row=lane // 5,
        )
        self.lane = lane

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message("このゲームを開始した人だけ操作できるよ。", ephemeral=True)
            return
        await view.select_lane(interaction, self.lane)


class TreasureHuntDigButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="DIG", style=discord.ButtonStyle.primary, row=2)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.owner_id:
            await interaction.response.send_message("このゲームを開始した人だけ操作できるよ。", ephemeral=True)
            return
        await self.view.dig_selected(interaction)


class TreasureHuntAllDigButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="ALL DIG", style=discord.ButtonStyle.success, row=2)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.owner_id:
            await interaction.response.send_message("このゲームを開始した人だけ操作できるよ。", ephemeral=True)
            return
        await self.view.dig_all_selected(interaction)


class TreasureHuntFinButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="FIN", style=discord.ButtonStyle.danger, row=2)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.owner_id:
            await interaction.response.send_message("このゲームを開始した人だけ操作できるよ。", ephemeral=True)
            return
        await self.view.finish_game(interaction)


@bot.command(name="th")
async def treasure_hunt_command(ctx: commands.Context, bet: str, lane: str):
    """宝探しゲームを開始（例：.th 100 1）"""
    if ctx.guild is None:
        await ctx.send("サーバー内で使ってね。")
        return
    try:
        bet_amount = int(str(bet).replace(",", "").strip())
        lane_number = int(str(lane).strip())
    except (TypeError, ValueError):
        await ctx.send("使い方：`.th 賭け金 1〜9`（例：`.th 100 3`）")
        return
    if bet_amount <= 0:
        await ctx.send("賭け金は1以上を指定してください。")
        return
    if lane_number < 1 or lane_number > TH_LANES:
        await ctx.send("レーンは1〜9から選んでね。")
        return
    if ctx.author.id in active_treasure_hunt_users:
        await ctx.send("すでにTREASURE HUNTをプレイ中だよ。")
        return

    # レーンはコマンドで指定。開始時には残高を引かず、DIG時に徴収する。
    view = TreasureHuntView(ctx, bet_amount, lane_number)
    active_treasure_hunt_users.add(ctx.author.id)
    try:
        view.message = await ctx.send(
            embed=view.make_embed(f"レーン {TH_LANE_LABELS[lane_number - 1]} を選択。DIGで掘ってね。"),
            view=view,
        )
    except Exception:
        active_treasure_hunt_users.discard(ctx.author.id)
        raise


@bot.command(name="hl", aliases=["highlow"])
async def highlow_command(ctx: commands.Context, bet: str = "100"):  """ハイ＆ローを開始（例: !hl 500, !hl all）"""
  balance = get_balance(ctx.author.id)

  # 「all」が指定された場合の判定
  if bet.lower() == "all":
    if balance <= 250000:
      bet_amount = balance
    else:
      bet_amount = 250000
  else:
    try:
      bet_amount = int(bet)
    except ValueError:
      await ctx.send(
          "賭け金には数値を指定するか、`all` を指定してください。",
          ephemeral=True,
      )
      return

  if bet_amount <= 0:
    await ctx.send("賭け金は1以上の数値を指定してください。", ephemeral=True)
    return

  if balance < bet_amount:
    await ctx.send(
        f"所持金が足りません！ 現在の所持金: **{balance:,} コイン**",
        ephemeral=True,
    )
    return

  # 本来の残高から賭け金を差し引く
  update_user_balance(ctx.author.id, -bet_amount)
  balance_after_bet = get_balance(ctx.author.id)

  if ctx.guild is not None:
    record_coin({
        "type": "highlow_bet",
        "guild_id": ctx.guild.id,
        "user_id": str(ctx.author.id),
        "balance": balance_after_bet,
    })
    await send_coin_log(
        ctx.guild,
        discord.Embed(
            title="🃏 HIGH&LOW ベットログ",
            description=(
                f"ユーザー：{ctx.author.mention} (`{ctx.author.id}`)\n"
                f"賭け金：**{money(bet_amount)}**\n"
                f"ベット後残高：**{money(balance_after_bet)}**"
            ),
            color=discord.Color.orange(),
        ),
    )

  deck = hl_make_deck()
  current = deck.pop()
  view = HighLowView(ctx.author.id, deck, current, bet_amount, ctx.guild)

  # HighLowView は LayoutView（Components V2）なので、通常の Embed は渡さず
  # View 内の Container とカード画像ファイルをそのまま送信する。
  try:
    if not os.path.exists(view.image_path):
      raise FileNotFoundError(f"HIGH&LOW card image not found: {view.image_path}")

    await ctx.send(
        file=discord.File(view.image_path, filename=os.path.basename(view.image_path)),
        view=view,
    )
  except Exception:
    # 開始画面の送信に失敗した場合は、先に徴収したベットを返金する。
    update_user_balance(ctx.author.id, bet_amount)
    raise


# ==================================================
# 景品配布機能
# ==================================================
from giveaway_feature import setup_giveaway
from race_feature import setup_race

setup_giveaway(bot, get_balance, set_balance, send_coin_log, OWNER_USER_ID)
setup_race(bot, get_balance, set_balance, money)


# ==================================================
# 大量メンション対策設定コマンド
# ==================================================

# スラッシュコマンド共通制限
# ==================================================

async def server_owner_slash_check(interaction: discord.Interaction):
    # 既存のBot所有者専用コマンドは、従来の require_owner 判定に任せる
    command = interaction.command
    if command is not None:
        try:
            callback_source = inspect.getsource(command.callback)
        except (OSError, TypeError):
            callback_source = ""

        if "require_owner(" in callback_source:
            return True

    # サーバー内の通常スラッシュコマンドは、そのサーバーのオーナーのみ
    if interaction.guild is None:
        await interaction.response.send_message(
            "このコマンドはサーバー内のオーナーだけが使えます。",
            ephemeral=True,
        )
        return False

    if interaction.user.id != interaction.guild.owner_id:
        message = "❌ このスラッシュコマンドを使えるのは、このサーバーのオーナーだけです。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False

    return True


# CommandTreeの共通チェックとして登録
bot.tree.interaction_check = server_owner_slash_check




# ==================================================
# 起動
# ==================================================

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。")

    Thread(target=run_web, daemon=True).start()
    bot.run(TOKEN)