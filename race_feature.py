import asyncio
import json
import os
import random
import secrets
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone

import discord
from discord import app_commands

DATA_DIR = Path(os.getenv("DATA_DIR", "."))
DATA_FILE = DATA_DIR / "race_feature.json"
configs = {}
tasks = {}
locks = {}
get_balance_fn = None
set_balance_fn = None
money_fn = None
restored = False

BETTING_SECONDS = 120
INTERVAL_SECONDS = 600
STEPS = 10
HORSES = ["サンダースター", "ミラクルラン", "ブルーファルコン", "ゴールドリーフ", "ナイトブレイズ", "スカイロード"]
HORSE_ODDS = [1.8, 2.2, 3.0, 3.8, 5.0, 7.0]
BOATS = ["1号艇", "2号艇", "3号艇", "4号艇", "5号艇", "6号艇"]
BOAT_ODDS = [1.8, 2.2, 3.0, 4.0, 5.0, 6.0]


def load_data():
    global configs
    try:
        if DATA_FILE.exists():
            with DATA_FILE.open("r", encoding="utf-8") as f:
                value = json.load(f)
            configs = value if isinstance(value, dict) else {}
    except Exception:
        print("[RACE LOAD ERROR]")
        traceback.print_exc()


def save_data():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp = DATA_FILE.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=2)
        temp.replace(DATA_FILE)
    except Exception:
        print("[RACE SAVE ERROR]")
        traceback.print_exc()


load_data()


def get_lock(gid):
    return locks.setdefault(str(gid), asyncio.Lock())


def make_event(kind):
    names, odds = (HORSES, HORSE_ODDS) if kind == "horse" else (BOATS, BOAT_ODDS)
    entries = [{"name": name, "odds": odds[i]} for i, name in enumerate(names)]
    if kind == "horse":
        random.shuffle(entries)
    return {
        "id": secrets.token_hex(5), "kind": kind, "entries": entries,
        "status": "betting", "open_until": time.time() + BETTING_SECONDS,
        "bets": {}, "message_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def make_embed(event):
    horse = event["kind"] == "horse"
    label = "競馬" if horse else "ボートレース"
    icon = "🏇" if horse else "🚤"
    status = event["status"]
    title = f"{icon} {label} " + (
        "投票受付中！" if status == "betting" else
        "レース中！" if status == "running" else "結果発表！"
    )
    color = discord.Color.gold() if status == "betting" else (
        discord.Color.blue() if status == "running" else discord.Color.green()
    )
    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    if status == "betting":
        embed.description = (
            f"投票締切：<t:{int(event['open_until'])}:R>\n"
            "出走者のボタンを押して、賭ける仮想コイン数を入力してね。\n"
            "1人1回まで・Bot内の仮想コイン専用"
        )
    elif status == "running":
        embed.description = "投票締切！レース開始！"
    else:
        winner = event.get("winner_index")
        if winner is None:
            embed.description = "レース中止"
        else:
            entry = event["entries"][winner]
            embed.description = f"優勝：**{entry['name']}**（{entry['odds']}倍）"

    entry_lines = []
    for i, entry in enumerate(event["entries"]):
        marker = " 🏆" if status == "finished" and event.get("winner_index") == i else ""
        entry_lines.append(f"**{i + 1}. {entry['name']}** — {entry['odds']}倍{marker}")
    embed.add_field(name="出走一覧", value="\n".join(entry_lines), inline=False)

    bets = event.get("bets", {})
    total = sum(int(b.get("amount", 0)) for b in bets.values())
    embed.add_field(name="投票人数", value=f"{len(bets)}人", inline=True)
    embed.add_field(name="投票総額", value=money_fn(total), inline=True)

    if status == "finished":
        winners = event.get("winners", [])
        embed.add_field(name="的中者", value=f"{len(winners)}人", inline=True)
        if winners:
            lines = [
                f"<@{w['user_id']}>：{money_fn(w['payout'])}（利益 {money_fn(w['payout'] - w['amount'])}）"
                for w in winners[:10]
            ]
            embed.add_field(name="配当", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="配当", value="的中者なし", inline=False)
    embed.set_footer(text="Bot内の仮想コインのみ")
    return embed


def render_track(event, positions):
    icon = "🐎" if event["kind"] == "horse" else "🚤"
    return "\n".join(
        f"{i + 1}. {entry['name']}  " + ("·" * positions[i]) + icon
        for i, entry in enumerate(event["entries"])
    )


def make_track_embed(event, positions, finished=False):
    title = "🏁 レース終了！" if finished else "🏁 レース進行中！"
    embed = discord.Embed(
        title=title,
        description="\u0060\u0060\u0060\n" + render_track(event, positions) + "\n\u0060\u0060\u0060",
        color=discord.Color.green() if finished else discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="レース実況")
    return embed


class BetModal(discord.ui.Modal):
    def __init__(self, guild_id, event_id, entry_index):
        super().__init__(title="仮想コインを投票")
        self.guild_id = str(guild_id)
        self.event_id = str(event_id)
        self.entry_index = int(entry_index)
        self.amount = discord.ui.TextInput(label="賭けるコイン数", placeholder="例：100", max_length=12)
        self.add_item(self.amount)

    async def on_submit(self, interaction):
        gid = self.guild_id
        config = configs.get(gid)
        event = config.get("active") if config else None
        if not event or event.get("id") != self.event_id or event.get("status") != "betting":
            await interaction.response.send_message("このレースの投票は終了したよ。", ephemeral=True)
            return
        if interaction.guild_id is None or str(interaction.guild_id) != gid:
            await interaction.response.send_message("このサーバーのレースではないよ。", ephemeral=True)
            return
        try:
            amount = int(str(self.amount.value).replace(",", "").strip())
            if amount < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("1以上の整数で入力してね。", ephemeral=True)
            return

        async with get_lock(gid):
            config = configs.get(gid)
            event = config.get("active") if config else None
            if not event or event.get("id") != self.event_id or event.get("status") != "betting":
                await interaction.response.send_message("このレースの投票は終了したよ。", ephemeral=True)
                return
            if time.time() >= float(event["open_until"]):
                await interaction.response.send_message("投票締切を過ぎているよ。", ephemeral=True)
                return
            uid = str(interaction.user.id)
            if uid in event["bets"]:
                await interaction.response.send_message("このレースには既に投票済みだよ。", ephemeral=True)
                return
            if not 0 <= self.entry_index < len(event["entries"]):
                await interaction.response.send_message("出走者が見つからないよ。", ephemeral=True)
                return
            balance = int(get_balance_fn(uid))
            if amount > balance:
                await interaction.response.send_message(
                    f"コインが足りないよ。残高：{money_fn(balance)}", ephemeral=True
                )
                return
            set_balance_fn(uid, balance - amount)
            event["bets"][uid] = {"entry_index": self.entry_index, "amount": amount}
            save_data()

        chosen = event["entries"][self.entry_index]["name"]
        await interaction.response.send_message(
            f"{chosen} に {money_fn(amount)} 投票したよ！残高：{money_fn(balance - amount)}",
            ephemeral=True,
        )


class RaceBetView(discord.ui.View):
    def __init__(self, guild_id, event, disabled=False):
        super().__init__(timeout=None)
        self.guild_id = str(guild_id)
        self.event_id = str(event["id"])
        for index, entry in enumerate(event["entries"]):
            button = discord.ui.Button(
                label=f"{index + 1}. {entry['name']}",
                style=discord.ButtonStyle.primary,
                custom_id=f"race:{self.event_id}:{index}",
                disabled=disabled,
                row=index // 3,
            )

            async def callback(interaction, selected_index=index):
                config = configs.get(self.guild_id)
                active = config.get("active") if config else None
                if not active or active.get("id") != self.event_id or active.get("status") != "betting":
                    await interaction.response.send_message("このレースの投票は終了したよ。", ephemeral=True)
                    return
                await interaction.response.send_modal(
                    BetModal(self.guild_id, self.event_id, selected_index)
                )

            button.callback = callback
            self.add_item(button)


async def fetch_text_channel(bot, channel_id):
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    return channel if isinstance(channel, discord.TextChannel) else None


async def run_race(bot, guild_id):
    gid = str(guild_id)
    config = configs.get(gid)
    if not config or not config.get("enabled"):
        return
    channel = await fetch_text_channel(bot, config["channel_id"])
    if channel is None:
        config["enabled"] = False
        save_data()
        print(f"[RACE] invalid channel for guild={gid}")
        return

    kind = config.get("next_kind", "horse")
    event = make_event(kind)
    config["next_kind"] = "boat" if kind == "horse" else "horse"
    config["active"] = event
    save_data()

    message = await channel.send(embed=make_embed(event), view=RaceBetView(gid, event))
    event["message_id"] = str(message.id)
    save_data()

    await asyncio.sleep(BETTING_SECONDS)
    if event.get("status") != "betting":
        return
    event["status"] = "running"
    save_data()
    await message.edit(embed=make_embed(event), view=RaceBetView(gid, event, disabled=True))

    positions = [0] * len(event["entries"])
    track_message = await channel.send(embed=make_track_embed(event, positions))
    for step in range(STEPS):
        for i in range(len(positions)):
            positions[i] = min(STEPS, positions[i] + random.choice([0, 1, 1, 1, 2]))
        if step < STEPS - 1:
            await track_message.edit(embed=make_track_embed(event, positions))
            await asyncio.sleep(0.65)

    odds = [float(entry["odds"]) for entry in event["entries"]]
    winner_index = random.choices(
        range(len(event["entries"])), weights=[1.0 / value for value in odds], k=1
    )[0]
    positions[winner_index] = STEPS
    event["status"] = "finished"
    event["winner_index"] = winner_index
    event["winners"] = []
    for uid, bet in list(event.get("bets", {}).items()):
        if int(bet["entry_index"]) == winner_index:
            amount = int(bet["amount"])
            payout = int(amount * odds[winner_index])
            set_balance_fn(uid, int(get_balance_fn(uid)) + payout)
            event["winners"].append({"user_id": uid, "amount": amount, "payout": payout})
    event["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_data()
    await track_message.edit(embed=make_track_embed(event, positions, finished=True))
    await message.edit(
        embed=make_embed(event),
        view=RaceBetView(gid, event, disabled=True),
    )
    config["active"] = None
    save_data()


async def guild_scheduler(bot, guild_id):
    gid = str(guild_id)
    try:
        while True:
            config = configs.get(gid)
            if not config or not config.get("enabled"):
                return
            next_at = float(config.get("next_at", time.time()))
            if next_at > time.time():
                await asyncio.sleep(next_at - time.time())
            config = configs.get(gid)
            if not config or not config.get("enabled"):
                return
            start_at = float(config.get("next_at", time.time()))
            await run_race(bot, gid)
            config = configs.get(gid)
            if not config or not config.get("enabled"):
                return
            next_at = start_at + INTERVAL_SECONDS
            while next_at <= time.time():
                next_at += INTERVAL_SECONDS
            config["next_at"] = next_at
            save_data()
    except asyncio.CancelledError:
        raise
    except Exception:
        print(f"[RACE SCHEDULER ERROR] guild={gid}")
        traceback.print_exc()
        config = configs.get(gid)
        event = config.get("active") if config else None
        if event:
            if event.get("status") != "finished":
                for uid, bet in event.get("bets", {}).items():
                    try:
                        set_balance_fn(uid, int(get_balance_fn(uid)) + int(bet["amount"]))
                    except Exception:
                        print(f"[RACE ERROR REFUND] user={uid}")
                        traceback.print_exc()
            config["active"] = None
            save_data()
        if config and config.get("enabled"):
            config["next_at"] = time.time() + INTERVAL_SECONDS
            save_data()
            tasks[gid] = asyncio.create_task(guild_scheduler(bot, gid))
    finally:
        if tasks.get(gid) is asyncio.current_task():
            tasks.pop(gid, None)


async def start_scheduler(bot, guild_id):
    gid = str(guild_id)
    current = tasks.get(gid)
    if current and not current.done():
        return
    tasks[gid] = asyncio.create_task(guild_scheduler(bot, gid))


async def restore(bot):
    global restored
    if restored:
        return
    restored = True
    # 中断されたレースの投票コインは全額返却
    for gid, config in list(configs.items()):
        event = config.get("active")
        if event:
            if event.get("status") != "finished":
                for uid, bet in event.get("bets", {}).items():
                    try:
                        set_balance_fn(uid, int(get_balance_fn(uid)) + int(bet["amount"]))
                    except Exception:
                        print(f"[RACE REFUND ERROR] user={uid}")
                        traceback.print_exc()
            config["active"] = None
            save_data()
    for gid, config in list(configs.items()):
        if config.get("enabled"):
            await start_scheduler(bot, gid)


def setup_race(bot, get_balance, set_balance, money):
    global get_balance_fn, set_balance_fn, money_fn
    get_balance_fn = get_balance
    set_balance_fn = set_balance
    money_fn = money

    group = app_commands.Group(name="racechannel", description="競馬・ボートレースの開催チャンネル設定")

    @group.command(name="set", description="自動レースの告知チャンネルを設定する")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild_id is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        gid = str(interaction.guild_id)
        config = configs.setdefault(gid, {})
        config["channel_id"] = str(channel.id)
        config["enabled"] = True
        config.setdefault("next_kind", "horse")
        config["next_at"] = time.time()
        config.setdefault("active", None)
        save_data()
        await start_scheduler(bot, gid)
        await interaction.response.send_message(
            f"開催チャンネルを {channel.mention} に設定したよ！\n"
            "競馬から開始して、10分おきに交互に自動開催するよ。",
            ephemeral=True,
        )

    @group.command(name="info", description="自動レースの設定を確認する")
    async def info(interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        config = configs.get(str(interaction.guild_id))
        if not config or not config.get("enabled"):
            await interaction.response.send_message("自動開催は設定されていないよ。", ephemeral=True)
            return
        next_name = "競馬" if config.get("next_kind", "horse") == "horse" else "ボートレース"
        next_at = int(config.get("next_at", time.time()))
        await interaction.response.send_message(
            f"開催チャンネル：<#{config['channel_id']}>\n次回開催：{next_name}\n予定時刻：<t:{next_at}:F>（<t:{next_at}:R>）",
            ephemeral=True,
        )

    @group.command(name="off", description="自動レースの次回以降の開催を停止する")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def off(interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        config = configs.get(str(interaction.guild_id))
        if not config or not config.get("enabled"):
            await interaction.response.send_message("自動開催は既に停止しているよ。", ephemeral=True)
            return
        config["enabled"] = False
        save_data()
        await interaction.response.send_message(
            "自動開催を停止したよ。進行中のレースは結果発表後に停止するよ。",
            ephemeral=True,
        )

    bot.tree.add_command(group)

    async def race_on_ready():
        await restore(bot)

    bot.add_listener(race_on_ready, "on_ready")
