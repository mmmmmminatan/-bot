import asyncio
import ipaddress
import json
import os
import socket
import tempfile
import traceback
from pathlib import Path
from urllib.parse import urlparse

import discord
from discord import app_commands
import yt_dlp

DATA_DIR = Path(os.getenv("DATA_DIR", "."))
CONFIG_FILE = DATA_DIR / "video_role_config.json"
DATABASE_URL = os.getenv("DATABASE_URL")
video_role_config = {}

# 一般向けの公開動画を扱う対応サイト
ALLOWED_HOSTS = (
    "youtube.com", "youtu.be", "x.com", "twitter.com",
    "tiktok.com", "instagram.com",
)


def load_config():
    global video_role_config
    value = {}
    try:
        if CONFIG_FILE.exists():
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            value = loaded if isinstance(loaded, dict) else {}
    except Exception:
        print("[VIDEO CONFIG LOAD ERROR]")
        traceback.print_exc()

    if DATABASE_URL:
        try:
            import psycopg2
            with psycopg2.connect(DATABASE_URL, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS bot_json_data (
                            data_key TEXT PRIMARY KEY,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute(
                        "SELECT payload FROM bot_json_data WHERE data_key = %s",
                        (str(CONFIG_FILE),),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        video_role_config = row[0] if isinstance(row[0], dict) else {}
                        return
                    cur.execute("""
                        INSERT INTO bot_json_data (data_key, payload)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (data_key) DO NOTHING
                    """, (str(CONFIG_FILE), json.dumps(value, ensure_ascii=False)))
        except Exception:
            print("[VIDEO CONFIG DATABASE LOAD ERROR]")
            traceback.print_exc()
    video_role_config = value


def save_config():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp = CONFIG_FILE.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(video_role_config, f, ensure_ascii=False, indent=2)
        temp.replace(CONFIG_FILE)
    except Exception:
        print("[VIDEO CONFIG JSON SAVE ERROR]")
        traceback.print_exc()

    if DATABASE_URL:
        try:
            import psycopg2
            with psycopg2.connect(DATABASE_URL, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS bot_json_data (
                            data_key TEXT PRIMARY KEY,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        INSERT INTO bot_json_data (data_key, payload, updated_at)
                        VALUES (%s, %s::jsonb, NOW())
                        ON CONFLICT (data_key)
                        DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                    """, (str(CONFIG_FILE), json.dumps(video_role_config, ensure_ascii=False)))
        except Exception:
            print("[VIDEO CONFIG DATABASE SAVE ERROR]")
            traceback.print_exc()


def validate_public_http_url(url):
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("http:// または https:// から始まるURLを指定してね。")

    host = parsed.hostname.rstrip(".").lower()
    if not any(host == domain or host.endswith("." + domain) for domain in ALLOWED_HOSTS):
        raise ValueError("対応している公開動画サイト（YouTube・X・TikTok・Instagram）のURLを指定してね。")
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("このURLは利用できないよ。")

    try:
        addresses = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except OSError:
        raise ValueError("URLのホスト名を確認できなかったよ。")

    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global:
            raise ValueError("公開されているWebサイトのURLだけ利用できるよ。")
    return parsed.geturl()


def download_mp4(url, max_bytes, directory):
    output_template = str(Path(directory) / "video.%(ext)s")
    options = {
        "format": "best[ext=mp4][acodec!=none]/best[ext=mp4]",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": max_bytes,
        "socket_timeout": 20,
        "retries": 1,
        "fragment_retries": 1,
        "restrictfilenames": True,
        "cachedir": False,
        "overwrites": True,
        "enable_file_urls": False,
        "ignoreerrors": False,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise RuntimeError("動画情報を取得できなかったよ。")
        if info.get("entries"):
            raise RuntimeError("複数動画のプレイリストには対応していないよ。")
        if int(info.get("age_limit") or 0) >= 18:
            raise RuntimeError("年齢制限のある動画は保存対象外だよ。")
        ydl.download([url])

    files = [
        p for p in Path(directory).glob("video.*")
        if p.is_file() and p.suffix.lower() == ".mp4"
    ]
    if not files:
        raise RuntimeError(
            "MP4形式で直接取得できる動画が見つからなかったよ。"
            "変換が必要な動画には現在対応していないよ。"
        )

    file_path = max(files, key=lambda p: p.stat().st_size)
    if file_path.stat().st_size > max_bytes:
        raise RuntimeError("動画がDiscordの添付ファイル上限を超えているよ。")
    return file_path


class VideoRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="動画保存を許可するロールを選択",
            min_values=0,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_role_id = self.values[0].id if self.values else None
        label = self.values[0].mention if self.values else "未設定（Botオーナーのみ）"
        await interaction.response.send_message(
            f"選択中：{label}\n「設定を保存」を押して確定してね。",
            ephemeral=True,
        )


class VideoRoleSaveButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="設定を保存",
            style=discord.ButtonStyle.success,
            emoji="💾",
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if interaction.user.id != view.owner_user_id:
            await interaction.response.send_message(
                "この設定を変更できるのはBotオーナー本人だけだよ。",
                ephemeral=True,
            )
            return

        gid = str(interaction.guild_id)
        video_role_config[gid] = {"role_id": view.selected_role_id}
        save_config()
        role = interaction.guild.get_role(view.selected_role_id) if view.selected_role_id else None
        await interaction.response.send_message(
            "✅ 設定を保存したよ。\n"
            f"利用可能ロール：{role.mention if role else '未設定（Botオーナーのみ）'}",
            ephemeral=True,
        )


class VideoSettingsView(discord.ui.LayoutView):
    def __init__(self, owner_user_id, current_role_id=None):
        super().__init__(timeout=300)
        self.owner_user_id = int(owner_user_id)
        self.selected_role_id = int(current_role_id) if current_role_id else None
        role_label = (
            f"<@&{self.selected_role_id}>"
            if self.selected_role_id
            else "未設定（Botオーナーのみ）"
        )

        container = discord.ui.Container()
        container.add_item(
            discord.ui.TextDisplay(
                "# 🎬 MINATANN 動画保存設定\n動画保存を利用できるロールを設定するよ。"
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(f"**現在の利用可能ロール：** {role_label}")
        )
        container.add_item(discord.ui.ActionRow(VideoRoleSelect()))
        container.add_item(discord.ui.ActionRow(VideoRoleSaveButton()))
        self.add_item(container)


def setup_video(bot, owner_user_id):
    owner_user_id = int(owner_user_id)
    load_config()

    @bot.tree.command(
        name="video",
        description="公開動画を保存、または動画保存の利用ロールを設定",
    )
    @app_commands.describe(url="保存したい公開動画のURL（省略すると設定画面）")
    async def video_command(interaction: discord.Interaction, url: str = None):
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で使ってね。",
                ephemeral=True,
            )
            return

        if url is None:
            if interaction.user.id != owner_user_id:
                await interaction.response.send_message(
                    "URLなしで設定画面を開けるのはBotオーナー本人だけだよ。",
                    ephemeral=True,
                )
                return

            config = video_role_config.get(str(interaction.guild.id), {})
            await interaction.response.send_message(
                view=VideoSettingsView(owner_user_id, config.get("role_id")),
                ephemeral=True,
            )
            return

        config = video_role_config.get(str(interaction.guild.id), {})
        role_id = config.get("role_id")
        is_owner = interaction.user.id == owner_user_id
        has_role = (
            role_id is not None
            and any(
                role.id == int(role_id)
                for role in getattr(interaction.user, "roles", [])
            )
        )
        if not (is_owner or has_role):
            await interaction.response.send_message(
                "この機能を使えるロールを持っていないよ。",
                ephemeral=True,
            )
            return

        try:
            safe_url = validate_public_http_url(url)
        except ValueError as error:
            await interaction.response.send_message(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        max_bytes = max(1, int(interaction.guild.filesize_limit))
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            with tempfile.TemporaryDirectory(prefix="minatann_video_") as temp_dir:
                file_path = await asyncio.to_thread(
                    download_mp4,
                    safe_url,
                    max_bytes,
                    temp_dir,
                )
                await interaction.channel.send(
                    content=f"🎬 {interaction.user.mention} が動画を保存したよ。",
                    file=discord.File(str(file_path), filename="video.mp4"),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            await interaction.followup.send(
                "✅ 動画をチャンネルに投稿したよ！",
                ephemeral=True,
            )
        except Exception as error:
            print(f"[VIDEO DOWNLOAD ERROR] {type(error).__name__}: {error}")
            await interaction.followup.send(
                f"❌ 動画を取得できなかったよ。\n理由：{str(error)[:700]}",
                ephemeral=True,
            )
