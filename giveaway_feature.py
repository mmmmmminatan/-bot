import asyncio
import json
import os
import random
import re
import secrets
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands

DATA_DIR = Path(os.getenv("DATA_DIR", "."))
GIVEAWAY_FILE = DATA_DIR / "giveaways.json"
giveaways = {}
locks = {}
tasks = {}
restored = False


def load_data():
    global giveaways
    try:
        if GIVEAWAY_FILE.exists():
            with GIVEAWAY_FILE.open("r", encoding="utf-8") as f:
                value = json.load(f)
            giveaways = value if isinstance(value, dict) else {}
    except Exception:
        print("[GIVEAWAY LOAD ERROR]")
        traceback.print_exc()


def save_data():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp = GIVEAWAY_FILE.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(giveaways, f, ensure_ascii=False, indent=2)
        temp.replace(GIVEAWAY_FILE)
    except Exception:
        print("[GIVEAWAY SAVE ERROR]")
        traceback.print_exc()


load_data()


def parse_duration(value):
    match = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", str(value).lower())
    if not match:
        return None
    seconds = int(match.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return seconds if 1 <= seconds <= 604800 else None


def get_lock(gid):
    return locks.setdefault(gid, asyncio.Lock())


def make_embed(data):
    active = data["status"] == "active"
    early = data["kind"] == "early"
    embed = discord.Embed(
        title="🎉 景品配布開催中！" if active else "🎊 景品配布終了！",
        color=discord.Color.gold() if active else discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="配布方式", value="早押し" if early else "通常", inline=True)
    embed.add_field(name="景品", value=data["prize"][:256], inline=True)
    embed.add_field(name="獲得人数" if early else "当選人数", value=str(data["winner_count"]), inline=True)
    if early:
        embed.add_field(name="獲得状況", value=f'{min(len(data["participants"]), data["winner_count"])} / {data["winner_count"]} 人', inline=True)
    else:
        end_at = int(data["end_at"])
        embed.add_field(name="終了時刻", value=f"<t:{end_at}:F>（<t:{end_at}:R>）", inline=False)
        embed.add_field(name="参加者", value=f'{len(data["participants"])} 人', inline=True)
    embed.add_field(name="主催者", value=f'<@{data["host_id"]}>', inline=True)
    if not active:
        winners = data.get("winners", [])
        if winners:
            label = "🎉 獲得者" if early else "🏆 当選者"
            embed.add_field(name=label, value="\n".join(f"<@{uid}>" for uid in winners), inline=False)
        else:
            embed.add_field(name="結果", value="参加者がいなかったため、当選者はいません。", inline=False)
    return embed


async def fetch_message(bot, data):
    channel = bot.get_channel(int(data["channel_id"]))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(data["channel_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    try:
        return await channel.fetch_message(int(data["message_id"]))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def update_message(bot, gid):
    data = giveaways.get(gid)
    if not data:
        return
    message = await fetch_message(bot, data)
    if message:
        try:
            await message.edit(
                embed=make_embed(data),
                view=GiveawayJoinView(bot, gid, disabled=data["status"] != "active"),
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"[GIVEAWAY EDIT ERROR] {error}")


async def finish_normal(bot, gid):
    async with get_lock(gid):
        data = giveaways.get(gid)
        if not data or data.get("status") != "active" or data.get("kind") != "normal":
            return
        people = list(dict.fromkeys(data.get("participants", [])))
        count = min(int(data["winner_count"]), len(people))
        data["winners"] = random.sample(people, count) if count else []
        data["status"] = "finished"
        data["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_data()
    await update_message(bot, gid)


async def timer_task(bot, gid):
    data = giveaways.get(gid)
    if not data or data.get("status") != "active":
        return
    wait = max(0, float(data["end_at"]) - datetime.now(timezone.utc).timestamp())
    await asyncio.sleep(wait)
    await finish_normal(bot, gid)


class GiveawayJoinView(discord.ui.View):
    def __init__(self, bot, gid, disabled=False):
        super().__init__(timeout=None)
        self.bot = bot
        self.gid = gid
        button = discord.ui.Button(
            label="参加する" if not disabled else "受付終了",
            style=discord.ButtonStyle.success if not disabled else discord.ButtonStyle.secondary,
            emoji="🎉",
            custom_id=f"giveaway:join:{gid}",
            disabled=disabled,
        )
        button.callback = self.join
        self.add_item(button)

    async def join(self, interaction):
        data = giveaways.get(self.gid)
        if not data or data.get("status") != "active":
            await interaction.response.send_message("この配布は既に終了しているよ。", ephemeral=True)
            return
        if interaction.guild_id != int(data["guild_id"]):
            await interaction.response.send_message("この配布は別のサーバーのものだよ。", ephemeral=True)
            return
        async with get_lock(self.gid):
            data = giveaways.get(self.gid)
            if not data or data.get("status") != "active":
                await interaction.response.send_message("この配布は既に終了しているよ。", ephemeral=True)
                return
            uid = str(interaction.user.id)
            if uid in data["participants"]:
                await interaction.response.send_message("既に参加済みだよ！", ephemeral=True)
                return
            if data["kind"] == "early" and len(data["participants"]) >= int(data["winner_count"]):
                await interaction.response.send_message("先着人数に達したため受付終了だよ。", ephemeral=True)
                return
            data["participants"].append(uid)
            if data["kind"] == "early":
                data["winners"] = list(data["participants"])
                if len(data["participants"]) >= int(data["winner_count"]):
                    data["status"] = "finished"
                    data["finished_at"] = datetime.now(timezone.utc).isoformat()
            save_data()
        await interaction.response.send_message(
            "🎉 景品を獲得したよ！" if data["kind"] == "early" else "参加を受け付けたよ！",
            ephemeral=True,
        )
        await update_message(self.bot, self.gid)


class GiveawayTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="通常", style=discord.ButtonStyle.primary, emoji="👥")
    async def normal(self, interaction, button):
        await interaction.response.send_modal(GiveawayModal("normal"))

    @discord.ui.button(label="早押し", style=discord.ButtonStyle.success, emoji="⚡")
    async def early(self, interaction, button):
        await interaction.response.send_modal(GiveawayModal("early"))


class GiveawayModal(discord.ui.Modal):
    def __init__(self, kind):
        self.kind = kind
        super().__init__(title="通常配布の設定" if kind == "normal" else "早押し配布の設定")
        self.prize = discord.ui.TextInput(label="景品", placeholder="例：Amazonギフトカード", max_length=100)
        self.count = discord.ui.TextInput(
            label="当選人数" if kind == "normal" else "先着人数",
            placeholder="例：3",
            max_length=3,
        )
        self.add_item(self.prize)
        self.add_item(self.count)
        if kind == "normal":
            self.duration = discord.ui.TextInput(
                label="時間（1s / 1m / 1h / 1d、最大7d）",
                placeholder="例：30m",
                max_length=8,
            )
            self.add_item(self.duration)

    async def on_submit(self, interaction):
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("サーバーのテキストチャンネルで使ってね。", ephemeral=True)
            return
        try:
            count = int(str(self.count.value).strip())
            if not 1 <= count <= 100:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("人数は1〜100の整数で入力してね。", ephemeral=True)
            return
        duration = None
        if self.kind == "normal":
            duration = parse_duration(self.duration.value)
            if duration is None:
                await interaction.response.send_message(
                    "時間の形式が違うよ。例：10s、5m、2h、1d。最大7dだよ。",
                    ephemeral=True,
                )
                return
        prize = str(self.prize.value).strip()
        if not prize:
            await interaction.response.send_message("景品名を入力してね。", ephemeral=True)
            return

        gid = secrets.token_hex(6)
        now = datetime.now(timezone.utc).timestamp()
        data = {
            "id": gid,
            "kind": self.kind,
            "prize": prize,
            "winner_count": count,
            "host_id": str(interaction.user.id),
            "guild_id": str(interaction.guild.id),
            "channel_id": str(interaction.channel.id),
            "message_id": None,
            "participants": [],
            "winners": [],
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.kind == "normal":
            data["end_at"] = now + duration

        await interaction.response.defer(ephemeral=True, thinking=True)
        message = await interaction.channel.send(
            embed=make_embed(data),
            view=GiveawayJoinView(interaction.client, gid),
        )
        data["message_id"] = str(message.id)
        giveaways[gid] = data
        save_data()
        if self.kind == "normal":
            tasks[gid] = asyncio.create_task(timer_task(interaction.client, gid))
        await interaction.followup.send("配布を開始したよ！", ephemeral=True)


async def restore(bot):
    global restored
    if restored:
        return
    restored = True
    for gid, data in list(giveaways.items()):
        if data.get("status") != "active" or not data.get("message_id"):
            continue
        try:
            bot.add_view(GiveawayJoinView(bot, gid))
            message = await fetch_message(bot, data)
            if data.get("kind") == "normal":
                tasks[gid] = asyncio.create_task(timer_task(bot, gid))
            elif data.get("kind") == "early" and len(data.get("participants", [])) >= int(data["winner_count"]):
                data["winners"] = list(data["participants"])
                data["status"] = "finished"
                save_data()
                await update_message(bot, gid)
        except Exception:
            print(f"[GIVEAWAY RESTORE ERROR] {gid}")
            traceback.print_exc()


def setup_giveaway(bot):
    group = app_commands.Group(name="giveaway", description="景品配布")

    @group.command(name="start", description="通常配布または早押し配布を開始する")
    async def start(interaction):
        await interaction.response.send_message(
            "配布の種類を選んでね。",
            view=GiveawayTypeView(),
            ephemeral=True,
        )

    bot.tree.add_command(group)
    bot.add_listener(lambda: restore(bot), "on_ready")
