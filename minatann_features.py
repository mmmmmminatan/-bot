import os
import base64
import hashlib
import io
import json
import logging
import threading
import asyncio
import random
import re
import traceback
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncpg
from flask import Flask

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("minatann-benri-bot")


def register_minatann_features(bot):
    """Register MINATANN convenience features on the supplied Mbot instance."""
    from video_feature import setup_video
    BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "1325449934236942392"))
    setup_video(bot, BOT_OWNER_ID)
    TOKEN = os.getenv("DISCORD_TOKEN")
    CONFIG_FILE = "welcome_config.json"
    GUESS_FILE = "guess_data.json"
    
    web_app = Flask(__name__)
    
    
    @web_app.get("/")
    def health_check():
        return "Minatann便利bot is alive!", 200
    
    
    def run_web_server():
        port = int(os.getenv("PORT", "10000"))
        web_app.run(host="0.0.0.0", port=port, use_reloader=False)
    
    
    def load_config():
        # 設定の正本はNeon。起動前は空で初期化し、Neon復元後に置き換える。
        return {}
    
    
    config = load_config()
    
    
    def save_guild_config(guild_id: int):
        return save_json(CONFIG_FILE, config)
    
    
    
    
    def get_log_channel(guild_id: int):
        data = config.get(str(guild_id))
        if not data or not data.get("enabled", True):
            return None
        channel_id = data.get("channel_id")
        if not channel_id:
            return None
        channel = bot.get_channel(int(channel_id))
        return channel if isinstance(channel, discord.TextChannel) else None
    
    
    def make_member_embed(member: discord.Member, joined: bool):
        if joined:
            title = "Welcome!"
            description = f"{member.mention} がサーバーに参加しました！"
            color = discord.Color.green()
            timestamp = member.joined_at or datetime.now(timezone.utc)
            event_label = "参加日時"
        else:
            title = "Goodbye"
            description = f"**{discord.utils.escape_markdown(member.display_name)}** がサーバーを退出しました。"
            color = discord.Color.red()
            timestamp = datetime.now(timezone.utc)
            event_label = "退出日時"
    
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=timestamp
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="ユーザー",
            value=f"{member} ({member.mention})" if joined else str(member),
            inline=False
        )
        embed.add_field(name="ユーザーID", value=f"`{member.id}`", inline=True)
        embed.add_field(
            name=event_label,
            value=discord.utils.format_dt(timestamp, style="F"),
            inline=True
        )
        if joined:
            embed.add_field(
                name="現在のメンバー数",
                value=f"`{member.guild.member_count or '不明'}` 人",
                inline=True
            )
            embed.add_field(
                name="アカウント作成日",
                value=discord.utils.format_dt(member.created_at, style="D"),
                inline=True
            )
        else:
            embed.add_field(
                name="退出後のメンバー数",
                value=f"`{member.guild.member_count or '不明'}` 人",
                inline=True
            )
        embed.set_footer(text=f"{member.guild.name} • Minatann便利bot")
        return embed
    
    
    @bot.listen()
    async def on_ready():
        logger.info("ログイン成功: %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
        try:
            synced = await bot.tree.sync()
            logger.info("スラッシュコマンド同期完了: %s件", len(synced))
            if not spam_announcement_loop.is_running():
                spam_announcement_loop.start()
            if not getattr(bot, "_ticket_views_registered", False):
                bot.add_view(TicketPanelView())
                bot.add_view(TicketChannelView())
                bot.add_view(VerifyPanelView())
                bot.add_view(AchievementPanelView())
                bot._ticket_views_registered = True
        except Exception:
            logger.exception("スラッシュコマンド同期エラー")
    
    
    @bot.listen()
    async def on_member_join(member: discord.Member):
        channel = get_log_channel(member.guild.id)
        if channel is not None:
            try:
                await channel.send(embed=make_member_embed(member, joined=True))
            except discord.HTTPException:
                logger.exception("参加ログの送信に失敗")
    
    
    @bot.listen()
    async def on_member_remove(member: discord.Member):
        channel = get_log_channel(member.guild.id)
        if channel is not None:
            try:
                await channel.send(embed=make_member_embed(member, joined=False))
            except discord.HTTPException:
                logger.exception("退出ログの送信に失敗")
    
    
    
    
    # ==================================================
    # Ticket Panel（Neon保存）
    # ==================================================
    TICKET_PANEL_FILE = Path("ticket_panels.json")
    ticket_panel_settings = {}
    
    
    class TicketChannelView(discord.ui.View):
        def __init__(self, disabled=False):
            super().__init__(timeout=None)
            self.close_button.disabled = disabled
    
        @discord.ui.button(label="チケットを閉じる", style=discord.ButtonStyle.danger,
                           custom_id="minatann:ticket:close")
        async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            guild = interaction.guild
            channel = interaction.channel
            if guild is None or not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message("チケットチャンネル内で使ってね。", ephemeral=True)
                return
            settings = ticket_panel_settings.get(str(guild.id), {})
            topic = channel.topic or ""
            match = re.search(r"ticket_owner:(\d+)", topic)
            owner_id = int(match.group(1)) if match else 0
            staff_ids = {int(x) for x in settings.get("staff_role_ids", [])}
            is_staff = (
                interaction.user.id == guild.owner_id
                or interaction.user.guild_permissions.administrator
                or any(r.id in staff_ids for r in getattr(interaction.user, "roles", []))
            )
            if interaction.user.id != owner_id and not is_staff:
                await interaction.response.send_message("チケット作成者または担当スタッフだけ閉じられるよ。", ephemeral=True)
                return
            # 指定された担当ロール（またはサーバー管理者）が閉じた場合はチャンネルごと削除
            if is_staff:
                await interaction.response.send_message("🔒 担当スタッフがチケットを閉じました。このチャンネルを削除します。", ephemeral=True)
                try:
                    await channel.delete(reason=f"Ticket closed and deleted by staff {interaction.user} ({interaction.user.id})")
                except discord.HTTPException:
                    await interaction.followup.send("チャンネルを削除できなかったよ。Botの「チャンネルの管理」権限を確認してね。", ephemeral=True)
                return
    
            # チケット作成者が閉じた場合は、従来どおり履歴を残して閉じる
            owner = guild.get_member(owner_id)
            try:
                if owner is not None:
                    await channel.set_permissions(owner, view_channel=False, send_messages=False)
                await channel.edit(
                    name=f"closed-{channel.name}"[:100],
                    topic=f"{topic} | ticket_closed:true",
                    reason=f"Ticket closed by {interaction.user} ({interaction.user.id})",
                )
            except discord.HTTPException:
                await interaction.response.send_message("チケットを閉じられなかったよ。Botの権限を確認してね。", ephemeral=True)
                return
            await interaction.response.edit_message(
                content=f"🔒 {interaction.user.mention} がチケットを閉じました。履歴はチャンネルに残っています。",
                view=TicketChannelView(disabled=True),
            )
    
    
    class TicketPanelView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
    
        @discord.ui.button(label="チケットを作成", style=discord.ButtonStyle.primary,
                           custom_id="minatann:ticket:create")
        async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
                return
            settings = ticket_panel_settings.get(str(guild.id))
            if not settings:
                await interaction.response.send_message("チケット設定が見つからないよ。管理者に再設定をお願いしてね。", ephemeral=True)
                return
            category = guild.get_channel(int(settings.get("category_id", 0)))
            if not isinstance(category, discord.CategoryChannel):
                await interaction.response.send_message("チケット作成先カテゴリーが見つからないよ。", ephemeral=True)
                return
            for existing in category.text_channels:
                match = re.search(r"ticket_owner:(\d+)", existing.topic or "")
                if match and int(match.group(1)) == interaction.user.id and "ticket_closed:true" not in (existing.topic or ""):
                    await interaction.response.send_message(f"未対応のチケットがあるよ: {existing.mention}", ephemeral=True)
                    return
            bot_member = guild.me
            if bot_member is None or not bot_member.guild_permissions.manage_channels:
                await interaction.response.send_message("Botに「チャンネルの管理」権限を付けてね。", ephemeral=True)
                return
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True,
                    attach_files=True, embed_links=True
                ),
                bot_member: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
                ),
            }
            for role_id in settings.get("staff_role_ids", []):
                role = guild.get_role(int(role_id))
                if role is not None:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    )
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                ticket = await guild.create_text_channel(
                    name=f"ticket-{interaction.user.name}"[:90],
                    category=category,
                    overwrites=overwrites,
                    topic=f"ticket_owner:{interaction.user.id}",
                    reason=f"Ticket opened by {interaction.user} ({interaction.user.id})",
                )
                await ticket.send(
                    content=f"{interaction.user.mention} チケットを作成しました。担当スタッフが確認します。",
                    view=TicketChannelView(),
                )
            except discord.Forbidden:
                await interaction.followup.send("チケットを作成できなかったよ。Botの「チャンネルの管理」権限を確認してね。", ephemeral=True)
                return
            except discord.HTTPException:
                await interaction.followup.send("チケット作成に失敗したよ。少し待ってから試してね。", ephemeral=True)
                return
            await interaction.followup.send(f"🎫 チケットを作成したよ: {ticket.mention}", ephemeral=True)
    
    
    class TicketPanelSetupView(discord.ui.View):
        def __init__(self, guild, panel_channel, category, title, detail, button_text, user_id):
            super().__init__(timeout=300)
            self.guild = guild
            self.panel_channel = panel_channel
            self.category = category
            self.title = title
            self.detail = detail
            self.button_text = button_text
            self.user_id = user_id
            self.staff_roles = []
            self.role_select = discord.ui.RoleSelect(
                placeholder="アクセス可能な担当ロールを複数選択（必須）",
                min_values=1, max_values=25,
            )
            self.role_select.callback = self.select_roles
            self.add_item(self.role_select)
    
        async def select_roles(self, interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("この設定画面を開いた人だけ操作できるよ。", ephemeral=True)
                return
            self.staff_roles = list(self.role_select.values)
            await interaction.response.edit_message(
                content="✅ 担当ロールを選択したよ。確認して「パネルを設置」を押してね。",
                view=self,
            )
    
        @discord.ui.button(label="パネルを設置", style=discord.ButtonStyle.success, row=1)
        async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("この設定画面を開いた人だけ操作できるよ。", ephemeral=True)
                return
            if not self.staff_roles:
                await interaction.response.send_message("担当ロールを最低1つ選択してね。", ephemeral=True)
                return
            bot_member = self.guild.me
            if bot_member is None or not bot_member.guild_permissions.manage_channels:
                await interaction.response.send_message("Botに「チャンネルの管理」権限を付けてね。", ephemeral=True)
                return
            perms = self.panel_channel.permissions_for(bot_member)
            if not (perms.view_channel and perms.send_messages):
                await interaction.response.send_message("パネル設置先でBotに「チャンネルを見る・メッセージ送信」の権限が必要だよ。", ephemeral=True)
                return
            key = str(self.guild.id)
            old = ticket_panel_settings.get(key)
            data = {
                "panel_channel_id": self.panel_channel.id,
                "category_id": self.category.id,
                "title": self.title,
                "detail": self.detail,
                "button_text": self.button_text,
                "staff_role_ids": [r.id for r in self.staff_roles],
            }
            ticket_panel_settings[key] = data
            if not save_json(TICKET_PANEL_FILE, ticket_panel_settings):
                if old is None:
                    ticket_panel_settings.pop(key, None)
                else:
                    ticket_panel_settings[key] = old
                await interaction.response.send_message("❌ チケット設定をNeonに保存できなかったよ。", ephemeral=True)
                return
            view = TicketPanelView()
            view.children[0].label = self.button_text
            try:
                message = await self.panel_channel.send(
                    embed=discord.Embed(
                        title=self.title,
                        description=self.detail,
                        color=discord.Color.blurple(),
                    ),
                    view=view,
                )
            except discord.HTTPException:
                await interaction.response.send_message("パネルを設置できなかったよ。チャンネル権限を確認してね。", ephemeral=True)
                return
            data["panel_message_id"] = message.id
            save_json(TICKET_PANEL_FILE, ticket_panel_settings)
            await interaction.response.edit_message(
                content=f"✅ パネルを {self.panel_channel.mention} に設置したよ！\nチケット作成先: **{self.category.name}**\n担当ロール: {', '.join(r.name for r in self.staff_roles)}",
                view=None,
            )
    
    
    ticket_group = app_commands.Group(name="ticket", description="チケット管理")
    
    
    @ticket_group.command(name="panel", description="必須項目を設定してチケットパネルを設置")
    @app_commands.describe(
        panel_channel="パネルを設置するチャンネル（必須）",
        ticket_category="チケット作成先カテゴリー（必須）",
        title="埋め込みの題名（必須）",
        detail="パネルの詳細説明（必須・通常の文章）",
        button_text="ボタンに表示する文字（必須）",
    )
    async def ticket_panel_command(
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel,
        ticket_category: discord.CategoryChannel,
        title: app_commands.Range[str, 1, 100],
        detail: app_commands.Range[str, 1, 1800],
        button_text: app_commands.Range[str, 1, 80],
    ):
        guild = interaction.guild
        if guild is None or panel_channel.guild.id != guild.id or ticket_category.guild.id != guild.id:
            await interaction.response.send_message("同じサーバー内のチャンネルとカテゴリーを指定してね。", ephemeral=True)
            return
        title = title.strip()
        detail = detail.strip()
        button_text = button_text.strip()
        if not title or not detail or not button_text:
            await interaction.response.send_message("題名・詳細・ボタンの文字はすべて必須だよ。", ephemeral=True)
            return
        if len(f"### {title}\n{detail}") > 2000:
            await interaction.response.send_message("題名と詳細を合わせて2,000文字以内にしてね。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**パネル設置先:** {panel_channel.mention}\n"
            f"**チケット作成先:** {ticket_category.name}\n"
            f"**題名:** {title}\n"
            f"**詳細:** {detail}\n"
            f"**ボタンの文字:** {button_text}\n\n"
            "最後に、チケットへアクセスできる担当ロールを1つ以上選択してね（複数選択OK）。",
            view=TicketPanelSetupView(guild, panel_channel, ticket_category, title, detail, button_text, interaction.user.id),
            ephemeral=True,
        )
    
    
    bot.tree.add_command(ticket_group)
    
    
    # ==================================================
    # Role Panel（最大15ロール・Neon保存）
    # ==================================================
    ROLE_PANEL_FILE = Path("role_panels.json")
    role_panel_settings = {}
    
    
    def build_role_panel_embed(guild: discord.Guild, panel_data: dict):
        embed = discord.Embed(
            title="🎭 ロール付与パネル",
            description="下のボタンを押すと、対応するロールが付与されます。",
            color=discord.Color.blurple(),
        )
        for item in panel_data.get("roles", [])[:15]:
            role = guild.get_role(int(item.get("role_id", 0)))
            if role is None:
                role_name = "削除されたロール"
                count = 0
            else:
                role_name = role.name
                count = sum(1 for member in guild.members if role in member.roles)
            description = str(item.get("description") or "NO")
            embed.add_field(
                name=f"{role_name}　｜　{count:,}人",
                value=description[:1024],
                inline=False,
            )
        embed.set_footer(text=f"{guild.name} • ボタンを押すとロールを取得できます")
        return embed
    
    
    async def refresh_role_panel(guild: discord.Guild):
        data = role_panel_settings.get(str(guild.id))
        if not data:
            return
        channel = guild.get_channel(int(data.get("channel_id", 0)))
        message_id = data.get("message_id")
        if not isinstance(channel, discord.TextChannel) or not message_id:
            return
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(embed=build_role_panel_embed(guild, data))
        except discord.NotFound:
            logger.warning("Role Panelのメッセージが見つかりません: guild=%s", guild.id)
        except discord.HTTPException:
            logger.exception("Role Panelの人数更新に失敗: guild=%s", guild.id)
    
    
    class RolePanelButton(discord.ui.Button):
        def __init__(self, guild_id: int, item: dict):
            role_id = int(item["role_id"])
            index = int(item["index"])
            label = f"{index} | {str(item.get('name') or 'ロール')}"
            super().__init__(
                label=label[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"minatann_role_panel:{guild_id}:{role_id}",
                row=(index - 1) // 3,
            )
            self.guild_id = guild_id
            self.role_id = role_id
    
        async def callback(self, interaction: discord.Interaction):
            guild = interaction.guild
            if guild is None or guild.id != self.guild_id:
                await interaction.response.send_message("このパネルは設置されたサーバーで使ってね。", ephemeral=True)
                return
            role = guild.get_role(self.role_id)
            if role is None:
                await interaction.response.send_message("このロールは削除されているよ。管理者に再設定してもらってね。", ephemeral=True)
                return
            bot_member = guild.me
            if bot_member is None or not bot_member.guild_permissions.manage_roles or role >= bot_member.top_role:
                await interaction.response.send_message("Botのロール管理権限、またはロールの上下関係を確認してね。", ephemeral=True)
                return
            member = guild.get_member(interaction.user.id)
            if member is None:
                try:
                    member = await guild.fetch_member(interaction.user.id)
                except discord.HTTPException:
                    await interaction.response.send_message("メンバー情報を取得できなかったよ。もう一度試してね。", ephemeral=True)
                    return
            try:
                if role in member.roles:
                    await member.remove_roles(role, reason="ロール付与パネルから解除")
                    result_text = f"➖ {role.mention} を外したよ！"
                else:
                    await member.add_roles(role, reason="ロール付与パネルから付与")
                    result_text = f"✅ {role.mention} を付与したよ！"
            except discord.Forbidden:
                await interaction.response.send_message("ロールを変更できなかったよ。Botの権限とロール位置を確認してね。", ephemeral=True)
                return
            except discord.HTTPException:
                await interaction.response.send_message("ロールの変更に失敗したよ。少し待ってから試してね。", ephemeral=True)
                return
            await interaction.response.send_message(result_text, ephemeral=True)
            await refresh_role_panel(guild)
    
    
    class RolePanelView(discord.ui.View):
        def __init__(self, guild_id: int, roles: list):
            super().__init__(timeout=None)
            for item in roles[:15]:
                self.add_item(RolePanelButton(guild_id, item))
    
    
    async def restore_role_panel_views():
        for guild_key, data in role_panel_settings.items():
            try:
                guild_id = int(guild_key)
                roles = data.get("roles", [])
                if roles:
                    bot.add_view(RolePanelView(guild_id, roles), message_id=int(data["message_id"]) if data.get("message_id") else None)
            except Exception:
                logger.exception("Role Panelのボタン復元に失敗: guild=%s", guild_key)
    
    
    class RolePanelSetupFlow:
        def __init__(self, guild: discord.Guild, channel: discord.TextChannel, user_id: int):
            self.guild = guild
            self.channel = channel
            self.user_id = user_id
            self.roles = []
            self.role_ids = set()
    
    
    async def publish_role_panel(interaction: discord.Interaction, flow: RolePanelSetupFlow):
        guild = flow.guild
        try:
            await guild.chunk(cache=True)
        except Exception:
            logger.warning("Role Panel設置前のメンバー一覧取得に失敗: guild=%s", guild.id)
    
        old_data = role_panel_settings.get(str(guild.id), {})
        old_channel = guild.get_channel(int(old_data.get("channel_id", 0))) if old_data.get("channel_id") else None
        if isinstance(old_channel, discord.TextChannel) and old_data.get("message_id"):
            try:
                old_message = await old_channel.fetch_message(int(old_data["message_id"]))
                await old_message.delete()
            except discord.HTTPException:
                pass
    
        panel_data = {"channel_id": flow.channel.id, "roles": flow.roles}
        try:
            message = await flow.channel.send(
                embed=build_role_panel_embed(guild, panel_data),
                view=RolePanelView(guild.id, flow.roles),
            )
        except discord.HTTPException:
            await interaction.followup.send("❌ パネルを送信できなかったよ。チャンネル権限を確認してね。", ephemeral=True)
            return
    
        panel_data["message_id"] = message.id
        role_panel_settings[str(guild.id)] = panel_data
        if not save_json(ROLE_PANEL_FILE, role_panel_settings):
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            role_panel_settings.pop(str(guild.id), None)
            await interaction.followup.send("❌ Role Panelの設定をNeonに登録できなかったよ。", ephemeral=True)
            return
    
        await interaction.followup.send(
            f"✅ {len(flow.roles)}個のロールを登録して、{flow.channel.mention} にパネルを設置したよ！\n"
            "同じボタンをもう一度押すとロールを外せるよ。人数も自動更新されるよ。",
            ephemeral=True,
        )
    
    
    class RolePanelDescriptionModal(discord.ui.Modal):
        def __init__(self, flow: RolePanelSetupFlow, role: discord.Role):
            super().__init__(title=f"{len(flow.roles) + 1}番目のロールの説明")
            self.flow = flow
            self.role = role
            self.description = discord.ui.TextInput(
                label="このロールの説明（任意）",
                placeholder="説明なしの場合は空欄、または NO",
                required=False,
                max_length=1024,
                style=discord.TextStyle.paragraph,
            )
            self.add_item(self.description)
    
        async def on_submit(self, interaction: discord.Interaction):
            if interaction.user.id != self.flow.user_id:
                await interaction.response.send_message("この設定画面を開いた人だけ操作できるよ。", ephemeral=True)
                return
            description = str(self.description.value or "").strip()
            if not description or description.lower() == "no":
                description = "NO"
            self.flow.roles.append({
                "index": len(self.flow.roles) + 1,
                "role_id": self.role.id,
                "name": self.role.name,
                "description": description[:1024],
            })
            self.flow.role_ids.add(self.role.id)
    
            if len(self.flow.roles) >= 15:
                await interaction.response.defer(ephemeral=True, thinking=True)
                await publish_role_panel(interaction, self.flow)
                return
    
            await interaction.response.send_message(
                f"✅ {len(self.flow.roles)}番目のロール「{self.role.name}」を設定したよ。\n"
                f"次は{len(self.flow.roles) + 1}番目のロールを選んでね。設定を終える場合は「設置完了」を押してね。",
                view=RolePanelSetupView(self.flow),
                ephemeral=True,
            )
    
    
    class RolePanelRoleSelect(discord.ui.RoleSelect):
        def __init__(self, flow: RolePanelSetupFlow):
            super().__init__(
                placeholder=f"{len(flow.roles) + 1}番目のロールを選択",
                min_values=1,
                max_values=1,
                row=0,
            )
            self.flow = flow
    
        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.flow.user_id:
                await interaction.response.send_message("この設定画面を開いた人だけ操作できるよ。", ephemeral=True)
                return
            role = self.values[0]
            bot_member = self.flow.guild.me
            if role.id in self.flow.role_ids:
                await interaction.response.send_message("そのロールはすでに登録済みだよ。別のロールを選んでね。", ephemeral=True)
                return
            if bot_member is None or not bot_member.guild_permissions.manage_roles:
                await interaction.response.send_message("Botに「ロールの管理」権限を付けてね。", ephemeral=True)
                return
            if role.is_default() or role.managed or role >= bot_member.top_role:
                await interaction.response.send_message("そのロールは付与できないよ。Botより下の通常ロールを選んでね。", ephemeral=True)
                return
            await interaction.response.send_modal(RolePanelDescriptionModal(self.flow, role))
    
    
    class RolePanelSetupView(discord.ui.View):
        def __init__(self, flow: RolePanelSetupFlow):
            super().__init__(timeout=600)
            self.flow = flow
            self.add_item(RolePanelRoleSelect(flow))
    
        @discord.ui.button(label="設置完了", style=discord.ButtonStyle.success, row=1)
        async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.flow.user_id:
                await interaction.response.send_message("この設定画面を開いた人だけ操作できるよ。", ephemeral=True)
                return
            if not self.flow.roles:
                await interaction.response.send_message("最低1個はロールを設定してね。", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            await publish_role_panel(interaction, self.flow)
    
    
    role_group = app_commands.Group(name="role", description="ロール付与パネル")
    
    
    @role_group.command(name="panel", description="順番にロールと説明を設定して付与パネルを設置")
    async def role_panel_command(interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("サーバーのテキストチャンネルで使ってね。", ephemeral=True)
            return
        if not (interaction.user.id == guild.owner_id or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("サーバーオーナーまたは管理者のみ設定できるよ。", ephemeral=True)
            return
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message("Botに「ロールの管理」権限を付けてね。", ephemeral=True)
            return
        flow = RolePanelSetupFlow(guild, interaction.channel, interaction.user.id)
        await interaction.response.send_message(
            "まず1番目のロールを選択してね。選択すると、そのロールの説明入力に進むよ。\n"
            "説明を空欄にするか「NO」と入力すると説明なしになるよ。最大15個まで設定できるよ。",
            view=RolePanelSetupView(flow),
            ephemeral=True,
        )
    
    
    
    @role_group.command(name="give", description="指定したメンバーにロールを付与")
    @app_commands.describe(
        role="付与するロール",
        member="ロールを渡す相手",
    )
    async def role_give_command(
        interaction: discord.Interaction,
        role: discord.Role,
        member: discord.Member,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
    
        if not (
            interaction.user.id == guild.owner_id
            or interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "サーバーオーナーまたは管理者のみ使用できるよ。",
                ephemeral=True,
            )
            return
    
        if role.is_default() or role.managed:
            await interaction.response.send_message(
                "EveryoneロールやBot管理のロールは付与できないよ。",
                ephemeral=True,
            )
            return
    
        if role.permissions.administrator:
            await interaction.response.send_message(
                "⛔ 管理者権限を持つロールは安全のため付与できないよ。",
                ephemeral=True,
            )
            return
    
        bot_member = guild.me
        if (
            bot_member is None
            or not bot_member.guild_permissions.manage_roles
            or role >= bot_member.top_role
        ):
            await interaction.response.send_message(
                "Botに「ロールの管理」権限を付けて、付与するロールよりBotのロールを上にしてね。",
                ephemeral=True,
            )
            return
    
        if role in member.roles:
            await interaction.response.send_message(
                f"{member.mention} はすでに {role.mention} を持っているよ。",
                ephemeral=True,
            )
            return
    
        try:
            await member.add_roles(
                role,
                reason=f"/role give 実行者: {interaction.user} ({interaction.user.id})",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "ロールを付与できなかったよ。Botの権限とロール位置を確認してね。",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "ロールの付与に失敗したよ。少し待ってからもう一度試してね。",
                ephemeral=True,
            )
            return
    
        await interaction.response.send_message(
            f"✅ {member.mention} に {role.mention} を付与したよ！",
            ephemeral=True,
        )
    
    
    bot.tree.add_command(role_group)
    
    
    @bot.listen("on_member_update")
    async def role_panel_member_update(before: discord.Member, after: discord.Member):
        changed_ids = {role.id for role in before.roles} ^ {role.id for role in after.roles}
        data = role_panel_settings.get(str(after.guild.id))
        if data and changed_ids.intersection(int(item["role_id"]) for item in data.get("roles", [])):
            await refresh_role_panel(after.guild)
    
    
    @bot.listen("on_member_join")
    async def role_panel_member_join(member: discord.Member):
        if str(member.guild.id) in role_panel_settings:
            await refresh_role_panel(member.guild)
    
    
    @bot.listen("on_member_remove")
    async def role_panel_member_remove(member: discord.Member):
        if str(member.guild.id) in role_panel_settings:
            await refresh_role_panel(member.guild)
    
    
    # ==================================================
    # Server Logs
    # ==================================================
    SERVER_LOGS_FILE = Path("server_logs.json")
    server_logs_settings = {}
    
    
    def get_server_logs_config(guild_id: int):
        return server_logs_settings.get(str(guild_id), {})
    
    
    async def send_server_log(guild: discord.Guild, title: str, description: str, color=None):
        cfg = get_server_logs_config(guild.id)
        channel_id = cfg.get("channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(
            title=title,
            description=discord.utils.escape_mentions(description)[:4000],
            color=color or discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.exception("Server Logsの送信に失敗")
    
    
    @bot.listen("on_raw_message_delete")
    async def server_logs_message_delete(payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = bot.get_guild(payload.guild_id)
        if guild is None or not get_server_logs_config(guild.id).get("message_delete", False):
            return
        cached = payload.cached_message
        if cached is None:
            description = f"チャンネル： <#{payload.channel_id}>\nメッセージID： `{payload.message_id}`\n※キャッシュがないため本文は取得できません。"
        else:
            author = f"{cached.author}（{cached.author.mention}）"
            body = cached.content or "（本文なし）"
            description = f"投稿者：{author}\nチャンネル：{cached.channel.mention}\n内容：{body[:1500]}"
        await send_server_log(guild, "🗑️ メッセージ削除", description, discord.Color.red())
    
    
    @bot.listen("on_raw_reaction_add")
    async def server_logs_reaction_add(payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        guild = bot.get_guild(payload.guild_id)
        if guild is None or not get_server_logs_config(guild.id).get("reaction_add", False):
            return
        user = guild.get_member(payload.user_id)
        if user is not None and user.bot:
            return
        await send_server_log(
            guild, "➕ リアクション追加",
            f"ユーザー：{user or payload.user_id}\nチャンネル：<#{payload.channel_id}>\n絵文字：{payload.emoji}\nメッセージID：`{payload.message_id}`"
        )
    
    
    @bot.listen("on_member_update")
    async def server_logs_timeout(before: discord.Member, after: discord.Member):
        cfg = get_server_logs_config(after.guild.id)
        if not cfg.get("timeout", False):
            return
        old_until = before.timed_out_until
        new_until = after.timed_out_until
        if old_until == new_until:
            return
        if new_until is not None and (old_until is None or new_until > old_until):
            detail = f"{after.mention} がタイムアウトされました。解除予定：{discord.utils.format_dt(new_until, style='F')}"
            title = "⏳ タイムアウト"
        elif old_until is not None and new_until is None:
            detail = f"{after.mention} のタイムアウトが解除されました。"
            title = "✅ タイムアウト解除"
        else:
            detail = f"{after.mention} のタイムアウト期限が変更されました。"
            title = "⏳ タイムアウト変更"
        await send_server_log(after.guild, title, detail)
    
    
    @bot.listen("on_voice_state_update")
    async def server_logs_voice(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        cfg = get_server_logs_config(member.guild.id)
        if not cfg.get("voice_join_leave", False) or before.channel == after.channel:
            return
        if before.channel is None and after.channel is not None:
            detail = f"{member.mention} が {after.channel.mention} に参加しました。"
            title = "🔊 VC参加"
        elif before.channel is not None and after.channel is None:
            detail = f"{member.mention} が {before.channel.name} から退出しました。"
            title = "🔈 VC退出"
        else:
            detail = f"{member.mention} が {before.channel.name} から {after.channel.mention} に移動しました。"
            title = "🔀 VC移動"
        await send_server_log(member.guild, title, detail)
    
    
    @bot.listen("on_member_join")
    async def server_logs_member_join(member: discord.Member):
        if get_server_logs_config(member.guild.id).get("member_join_leave", False):
            await send_server_log(
                member.guild, "📥 サーバー参加",
                f"{member.mention}（{member}）がサーバーに参加しました。\nアカウント作成：{discord.utils.format_dt(member.created_at, style='F')}",
                discord.Color.green(),
            )
    
    
    @bot.listen("on_member_remove")
    async def server_logs_member_leave(member: discord.Member):
        if get_server_logs_config(member.guild.id).get("member_join_leave", False):
            await send_server_log(
                member.guild, "📤 サーバー退出",
                f"{discord.utils.escape_markdown(str(member))} がサーバーを退出しました。",
                discord.Color.red(),
            )
    
    
    server_group = app_commands.Group(name="server", description="サーバー設定")
    SERVER_LOGS_MODE = [
        app_commands.Choice(name="今の設定", value="current"),
        app_commands.Choice(name="新規設定", value="new"),
    ]
    
    
    @server_group.command(name="logs", description="サーバーログの送信先と記録項目を設定")
    @app_commands.choices(mode=SERVER_LOGS_MODE)
    @app_commands.describe(
        mode="現在の設定を確認するか、新しく設定するか",
        channel="ログを送信するテキストチャンネル",
        message_delete="メッセージ削除ログ",
        reaction_add="リアクション追加ログ",
        timeout="タイムアウトログ",
        member_join_leave="サーバー入退出ログ",
        voice_join_leave="VC入退出ログ",
    )
    async def server_logs_command(
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        channel: discord.TextChannel = None,
        message_delete: bool = None,
        reaction_add: bool = None,
        timeout: bool = None,
        member_join_leave: bool = None,
        voice_join_leave: bool = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message("サーバーオーナーまたは管理者のみ設定できるよ。", ephemeral=True)
            return
    
        key = str(interaction.guild.id)
        cfg = get_server_logs_config(interaction.guild.id)
    
        if mode.value == "current":
            target = interaction.guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None
            if not cfg:
                await interaction.response.send_message("まだサーバーログは設定されていないよ。", ephemeral=True)
                return
            def state(label, field):
                return f"{label}：{'ON' if cfg.get(field, False) else 'OFF'}"
            await interaction.response.send_message(
                "**📋 現在のServer Logs設定**\n"
                f"送信先：{target.mention if target else '未設定'}\n"
                + "\n".join([
                    state("メッセージ削除", "message_delete"),
                    state("リアクション追加", "reaction_add"),
                    state("タイムアウト", "timeout"),
                    state("サーバー入退出", "member_join_leave"),
                    state("VC入退出", "voice_join_leave"),
                ]),
                ephemeral=True,
            )
            return
    
        if channel is None:
            await interaction.response.send_message("新規設定ではログ送信先チャンネルを指定してね。", ephemeral=True)
            return
        bot_member = interaction.guild.me
        perms = channel.permissions_for(bot_member) if bot_member else None
        if perms is None or not (perms.view_channel and perms.send_messages and perms.embed_links):
            await interaction.response.send_message("Botにチャンネル閲覧・メッセージ送信・埋め込みリンク権限が必要だよ。", ephemeral=True)
            return
    
        server_logs_settings[key] = {
            "channel_id": channel.id,
            "message_delete": bool(message_delete),
            "reaction_add": bool(reaction_add),
            "timeout": bool(timeout),
            "member_join_leave": bool(member_join_leave),
            "voice_join_leave": bool(voice_join_leave),
        }
        if not save_json(SERVER_LOGS_FILE, server_logs_settings):
            await interaction.response.send_message("❌ Neonへの保存登録に失敗したよ。", ephemeral=True)
            return
        await interaction.response.send_message(
            "✅ **Server Logsを設定したよ！**\n"
            f"送信先：{channel.mention}\n"
            f"メッセージ削除：{'ON' if message_delete else 'OFF'}\n"
            f"リアクション追加：{'ON' if reaction_add else 'OFF'}\n"
            f"タイムアウト：{'ON' if timeout else 'OFF'}\n"
            f"サーバー入退出：{'ON' if member_join_leave else 'OFF'}\n"
            f"VC入退出：{'ON' if voice_join_leave else 'OFF'}",
            ephemeral=True,
        )
    
    
    bot.tree.add_command(server_group)
    
    
    WELCOME_ACTIONS = [
        app_commands.Choice(name="送信するチャンネルを設定", value="set"),
        app_commands.Choice(name="ログの送信を停止", value="stop"),
        app_commands.Choice(name="ログの送信を開始", value="start"),
    ]
    
    
    @bot.tree.command(name="welcome", description="参加・退出ログの設定")
    @app_commands.describe(
        action="実行する操作",
        channel="ログを送信するテキストチャンネル（設定時のみ）"
    )
    @app_commands.choices(action=WELCOME_ACTIONS)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_command(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: discord.TextChannel = None
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で使ってね。", ephemeral=True
            )
            return
    
        guild_id = interaction.guild.id
        key = str(guild_id)
    
        if action.value == "set":
            if channel is None:
                await interaction.response.send_message(
                    "チャンネル設定を選んだ場合は、送信先チャンネルも指定してね。",
                    ephemeral=True
                )
                return
            bot_member = interaction.guild.me
            if bot_member is None:
                await interaction.response.send_message(
                    "Botのメンバー情報を取得できなかったよ。", ephemeral=True
                )
                return
            permissions = channel.permissions_for(bot_member)
            if not (
                permissions.view_channel
                and permissions.send_messages
                and permissions.embed_links
            ):
                await interaction.response.send_message(
                    "Botに「チャンネルを見る」「メッセージを送信」「埋め込みリンク」の権限が必要だよ。",
                    ephemeral=True
                )
                return
            old = config.get(key, {})
            config[key] = {
                "channel_id": channel.id,
                "enabled": bool(old.get("enabled", True)),
            }
            config[key]["enabled"] = True
            if not save_guild_config(guild_id):
                await interaction.response.send_message("❌ Neonへの保存登録に失敗したよ。", ephemeral=True)
                return
            await interaction.response.send_message(
                f"✅ Welcome Logの送信先を {channel.mention} に設定したよ！",
                ephemeral=True
            )
            return
    
        if key not in config or not config[key].get("channel_id"):
            await interaction.response.send_message(
                "先に「送信するチャンネルを設定」してね。", ephemeral=True
            )
            return
    
        config[key]["enabled"] = action.value == "start"
        if not save_guild_config(guild_id):
            await interaction.response.send_message("❌ Neonへの保存登録に失敗したよ。", ephemeral=True)
            return
    
        if action.value == "stop":
            message = "⏸️ Welcome Logの送信を停止したよ。"
        else:
            message = "▶️ Welcome Logの送信を開始したよ。"
        await interaction.response.send_message(message, ephemeral=True)
    
    
    
    # ==================================================
    # 賞金なし・残高なしの数字／言葉当てゲーム
    # ==================================================
    
    def load_guess_data():
        # 設定の正本はNeon。起動前は空で初期化し、Neon復元後に置き換える。
        return {}
    
    
    guess_data = load_guess_data()
    guess_locks = {}
    
    
    def save_guess_data():
        return save_json(GUESS_FILE, guess_data)
    
    
    guess_group = app_commands.Group(
        name="guess",
        description="賞金なしの数字・言葉当てゲーム",
    )
    
    
    @guess_group.command(name="setup", description="このチャンネルで当てゲームを開始")
    @app_commands.describe(
        mode="数字当てか言葉当てか選択",
        answer="正解（数字当ての場合は数字）",
        minimum="数字当ての最小値（省略時は1）",
        maximum="数字当ての最大値（省略時は100）",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="数字当て", value="number"),
        app_commands.Choice(name="言葉当て", value="word"),
    ])
    @app_commands.default_permissions(manage_guild=True)
    async def guess_setup(
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        answer: str,
        minimum: app_commands.Range[int, 0, 1000000] = 1,
        maximum: app_commands.Range[int, 1, 1000000] = 100,
    ):
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("サーバーのテキストチャンネルで使ってね。", ephemeral=True)
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("サーバー管理権限が必要だよ。", ephemeral=True)
            return
    
        answer = answer.strip()
        if not answer:
            await interaction.response.send_message("正解を入力してね。", ephemeral=True)
            return
    
        if mode.value == "number":
            try:
                numeric_answer = int(answer)
            except ValueError:
                await interaction.response.send_message("数字当ての正解には整数を入力してね。", ephemeral=True)
                return
            if minimum >= maximum or not minimum <= numeric_answer <= maximum:
                await interaction.response.send_message("範囲または正解の数字を確認してね。最小値は最大値より小さく、正解は範囲内にしてね。", ephemeral=True)
                return
            answer = str(numeric_answer)
    
        key = str(interaction.guild.id)
        guess_data[key] = {
            "active": True,
            "channel_id": interaction.channel.id,
            "host_id": interaction.user.id,
            "mode": mode.value,
            "answer": answer,
            "minimum": int(minimum),
            "maximum": int(maximum),
        }
        if not save_guess_data():
            guess_data.pop(key, None)
            await interaction.response.send_message("❌ Neonへの保存登録に失敗したよ。", ephemeral=True)
            return
    
        mode_label = "数字当て" if mode.value == "number" else "言葉当て"
        rule = f"範囲：**{minimum}〜{maximum}**" if mode.value == "number" else "正解の言葉を送信してね！"
        await interaction.response.send_message(
            f"🎮 **{mode_label}ゲーム開始！**\n回答チャンネル：{interaction.channel.mention}\n{rule}\n\n正解者が出るとゲーム終了！賞金・残高の変動はありません。",
            ephemeral=False,
        )
    
    
    @guess_group.command(name="stop", description="開催中の当てゲームを終了")
    @app_commands.default_permissions(manage_guild=True)
    async def guess_stop(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("サーバー管理権限が必要だよ。", ephemeral=True)
            return
        key = str(interaction.guild.id)
        game = guess_data.get(key)
        if not game or not game.get("active"):
            await interaction.response.send_message("開催中のゲームはないよ。", ephemeral=True)
            return
        game["active"] = False
        game.pop("answer", None)
        save_guess_data()
        await interaction.response.send_message("🛑 当てゲームを終了したよ。")
    
    
    bot.tree.add_command(guess_group)
    
    
    
    
    async def process_guess_message(message: discord.Message):
        if message.guild is None or message.author.bot:
            return
    
        key = str(message.guild.id)
        game = guess_data.get(key)
        if not game or not game.get("active"):
            return
        if int(game.get("channel_id", 0)) != message.channel.id:
            return
    
        lock = guess_locks.setdefault(message.guild.id, asyncio.Lock())
        async with lock:
            game = guess_data.get(key)
            if not game or not game.get("active"):
                return
            if int(game.get("channel_id", 0)) != message.channel.id:
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
    
            game["active"] = False
            game.pop("answer", None)
            save_guess_data()
            await message.channel.send(
                f"🎉 **正解！**\n正解者：{message.author.mention}\nゲーム終了！"
            )
    
    
    
    # ==================================================
    # サーバー別レベルシステム（Neon保存）
    # ==================================================
    LEVEL_SETTINGS_FILE = "level_settings.json"
    LEVEL_DATA_FILE = "level_data.json"
    level_settings = {}
    level_data = {}
    level_locks = {}
    
    # 一時ニックネーム（Neon保存）
    TEMP_NICKNAMES_FILE = "temporary_nicknames.json"
    temporary_nicknames = {}
    
    
    def get_level_settings(guild_id: int):
        key = str(guild_id)
        cfg = level_settings.get(key)
        if not isinstance(cfg, dict):
            cfg = {"max_level": 10, "milestones": {}}
            level_settings[key] = cfg
        cfg.setdefault("max_level", 10)
        cfg.setdefault("milestones", {})
        return cfg
    
    
    def get_level_record(guild_id: int, user_id: int):
        guild_key = str(guild_id)
        user_key = str(user_id)
        guild_data = level_data.setdefault(guild_key, {})
        record = guild_data.setdefault(user_key, {"messages": 0, "level": 0})
        try:
            record["messages"] = max(0, int(record.get("messages", 0)))
        except (TypeError, ValueError):
            record["messages"] = 0
        try:
            record["level"] = max(0, int(record.get("level", 0)))
        except (TypeError, ValueError):
            record["level"] = 0
        return record
    
    
    def get_level_from_messages(cfg: dict, messages: int) -> int:
        max_level = max(1, min(10, int(cfg.get("max_level", 10))))
        reached = 0
        milestones = cfg.get("milestones", {})
        for level in range(1, max_level + 1):
            item = milestones.get(str(level), {})
            threshold = item.get("messages") if isinstance(item, dict) else None
            if threshold is None:
                continue
            try:
                threshold = int(threshold)
            except (TypeError, ValueError):
                continue
            if threshold > 0 and messages >= threshold:
                reached = level
        return reached
    
    
    async def apply_level_reward_role(member: discord.Member, new_level: int):
        cfg = get_level_settings(member.guild.id)
        milestones = cfg.get("milestones", {})
        configured_role_ids = set()
        target_role = None
    
        for level_key, item in milestones.items():
            if not isinstance(item, dict) or not item.get("role_id"):
                continue
            try:
                role_id = int(item["role_id"])
                configured_role_ids.add(role_id)
                if int(level_key) == new_level:
                    target_role = member.guild.get_role(role_id)
            except (TypeError, ValueError):
                continue
    
        bot_member = member.guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            logger.warning("レベル報酬ロールを変更できません（manage_rolesなし）: guild=%s", member.guild.id)
            return
    
        if target_role is not None and (target_role >= bot_member.top_role or target_role.managed):
            logger.warning("レベル報酬ロールがBotより上位または管理ロールです: role=%s", target_role.id)
            target_role = None
    
        removable = [
            role for role in member.roles
            if role.id in configured_role_ids
            and role < bot_member.top_role
            and not role.managed
        ]
        try:
            if removable:
                await member.remove_roles(*removable, reason="レベル報酬ロールの置き換え")
            if target_role is not None and target_role not in member.roles:
                await member.add_roles(target_role, reason=f"レベル{new_level}到達")
        except discord.Forbidden:
            logger.warning("レベル報酬ロールの付与・削除に失敗（権限不足）: guild=%s user=%s", member.guild.id, member.id)
        except discord.HTTPException:
            logger.exception("レベル報酬ロールの更新に失敗")
    
    
    async def process_level_message(message: discord.Message):
        if message.guild is None or message.author.bot or message.webhook_id is not None:
            return
        if not isinstance(message.author, discord.Member):
            return
    
        guild_id = message.guild.id
        if str(guild_id) not in level_settings:
            return
        user_id = message.author.id
        lock = level_locks.setdefault((guild_id, user_id), asyncio.Lock())
        async with lock:
            cfg = get_level_settings(guild_id)
            record = get_level_record(guild_id, user_id)
            old_level = int(record.get("level", 0))
            record["messages"] += 1
            new_level = get_level_from_messages(cfg, record["messages"])
            record["level"] = new_level
    
            if not save_json(LEVEL_DATA_FILE, level_data):
                logger.error("レベルデータをNeon保存キューへ登録できませんでした")
                return
    
            if new_level > old_level:
                await apply_level_reward_role(message.author, new_level)
                milestone = cfg.get("milestones", {}).get(str(new_level), {})
                role_id = milestone.get("role_id") if isinstance(milestone, dict) else None
                role = message.guild.get_role(int(role_id)) if role_id else None
                role_text = f"\n報酬ロール：**{discord.utils.escape_markdown(discord.utils.escape_mentions(role.name))}**" if role else ""
                await message.channel.send(
                    f"🎉 {message.author.mention} が **レベル{new_level}** に到達したよ！"
                    f"\n累計メッセージ数：**{record['messages']:,}回**"
                    f"{role_text}"
                )
    
    
    lv_group = app_commands.Group(name="lv", description="サーバー別レベルシステム")
    
    
    @lv_group.command(name="setup", description="このサーバーのレベル・必要送信数・報酬ロールを設定")
    @app_commands.guild_only()
    @app_commands.describe(
        max_level="レベル上限（1〜10）",
        lv1_messages="Lv.1になる累計送信数（未設定ならスキップ）",
        lv1_role="Lv.1到達時の報酬ロール",
        lv2_messages="Lv.2になる累計送信数（未設定ならスキップ）",
        lv2_role="Lv.2到達時の報酬ロール",
        lv3_messages="Lv.3になる累計送信数（未設定ならスキップ）",
        lv3_role="Lv.3到達時の報酬ロール",
        lv4_messages="Lv.4になる累計送信数（未設定ならスキップ）",
        lv4_role="Lv.4到達時の報酬ロール",
        lv5_messages="Lv.5になる累計送信数（未設定ならスキップ）",
        lv5_role="Lv.5到達時の報酬ロール",
        lv6_messages="Lv.6になる累計送信数（未設定ならスキップ）",
        lv6_role="Lv.6到達時の報酬ロール",
        lv7_messages="Lv.7になる累計送信数（未設定ならスキップ）",
        lv7_role="Lv.7到達時の報酬ロール",
        lv8_messages="Lv.8になる累計送信数（未設定ならスキップ）",
        lv8_role="Lv.8到達時の報酬ロール",
        lv9_messages="Lv.9になる累計送信数（未設定ならスキップ）",
        lv9_role="Lv.9到達時の報酬ロール",
        lv10_messages="Lv.10になる累計送信数（未設定ならスキップ）",
        lv10_role="Lv.10到達時の報酬ロール",
    )
    async def lv_setup_command(
        interaction: discord.Interaction,
        max_level: app_commands.Range[int, 1, 10],
        lv1_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv1_role: discord.Role | None = None,
        lv2_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv2_role: discord.Role | None = None,
        lv3_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv3_role: discord.Role | None = None,
        lv4_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv4_role: discord.Role | None = None,
        lv5_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv5_role: discord.Role | None = None,
        lv6_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv6_role: discord.Role | None = None,
        lv7_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv7_role: discord.Role | None = None,
        lv8_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv8_role: discord.Role | None = None,
        lv9_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv9_role: discord.Role | None = None,
        lv10_messages: app_commands.Range[int, 1, 100000000] | None = None,
        lv10_role: discord.Role | None = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        if not (interaction.user.id == guild.owner_id or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("サーバーオーナーまたは管理者だけ設定できるよ。", ephemeral=True)
            return
    
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message("Botに「ロールの管理」権限を付けてね。", ephemeral=True)
            return
    
        raw = {
            1: (lv1_messages, lv1_role), 2: (lv2_messages, lv2_role),
            3: (lv3_messages, lv3_role), 4: (lv4_messages, lv4_role),
            5: (lv5_messages, lv5_role), 6: (lv6_messages, lv6_role),
            7: (lv7_messages, lv7_role), 8: (lv8_messages, lv8_role),
            9: (lv9_messages, lv9_role), 10: (lv10_messages, lv10_role),
        }
        milestones = {}
        used_roles = set()
        previous_threshold = 0
        for level in range(1, 11):
            messages, role = raw[level]
            if level > max_level and (messages is not None or role is not None):
                await interaction.response.send_message(
                    f"レベル上限がLv.{max_level}なので、Lv.{level}の設定は入力しないでね。",
                    ephemeral=True,
                )
                return
            if messages is not None:
                if int(messages) <= previous_threshold:
                    await interaction.response.send_message(
                        "必要送信数は、設定したレベル順に必ず大きくしてね。未設定レベルは飛ばせるよ。",
                        ephemeral=True,
                    )
                    return
                previous_threshold = int(messages)
            if role is not None:
                if role.is_default() or role.managed or role.permissions.administrator or role >= bot_member.top_role:
                    await interaction.response.send_message(
                        f"{role.mention} は報酬ロールに設定できないよ。Botより下位の通常ロールを選んでね。",
                        ephemeral=True,
                    )
                    return
                if role.id in used_roles:
                    await interaction.response.send_message("同じロールを複数のレベルに設定できないよ。", ephemeral=True)
                    return
                used_roles.add(role.id)
            if messages is not None or role is not None:
                milestones[str(level)] = {
                    "messages": int(messages) if messages is not None else None,
                    "role_id": role.id if role is not None else None,
                }
    
        if not any(item.get("messages") for item in milestones.values()):
            await interaction.response.send_message("少なくとも1つのレベルに必要送信数を設定してね。", ephemeral=True)
            return
    
        level_settings[str(guild.id)] = {
            "max_level": int(max_level),
            "milestones": milestones,
        }
        if not save_json(LEVEL_SETTINGS_FILE, level_settings):
            await interaction.response.send_message("❌ レベル設定をNeonに保存できなかったよ。", ephemeral=True)
            return
    
        lines = [f"**レベル上限：** Lv.{max_level}"]
        for level in range(1, int(max_level) + 1):
            item = milestones.get(str(level), {})
            count = item.get("messages")
            role_id = item.get("role_id")
            role = guild.get_role(int(role_id)) if role_id else None
            count_text = f"{int(count):,}回" if count is not None else "未設定（スキップ）"
            role_text = role.mention if role else "未設定"
            lines.append(f"Lv.{level}：{count_text} / 報酬ロール：{role_text}")
    
        embed = discord.Embed(
            title="📈 レベル設定を保存したよ",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="必要送信数はサーバー内の累計。設定したレベルだけ到達するよ。")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    
    @lv_group.command(name="show", description="自分または指定メンバーのレベルを確認")
    @app_commands.guild_only()
    @app_commands.describe(member="レベルを確認するメンバー（省略すると自分）")
    async def lv_show_command(
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        target = member or interaction.user
        record = get_level_record(guild.id, target.id)
        cfg = get_level_settings(guild.id)
        next_level = None
        next_count = None
        for level in range(int(record["level"]) + 1, int(cfg.get("max_level", 10)) + 1):
            item = cfg.get("milestones", {}).get(str(level), {})
            if isinstance(item, dict) and item.get("messages") is not None:
                next_level = level
                next_count = int(item["messages"])
                break
        description = (
            f"**レベル：** Lv.{record['level']}\n"
            f"**累計送信数：** {record['messages']:,}回\n"
        )
        if next_level is not None:
            remaining = max(0, next_count - int(record["messages"]))
            description += f"**次の目標：** Lv.{next_level}（あと{remaining:,}回）"
        else:
            description += "**次の目標：** なし（上限または未設定）"
        embed = discord.Embed(
            title=f"📊 {target.display_name} のレベル",
            description=description,
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    
    @lv_group.command(name="ranking", description="このサーバーのレベルランキング")
    @app_commands.guild_only()
    async def lv_ranking_command(interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        rows = []
        for user_id, record in level_data.get(str(guild.id), {}).items():
            if not isinstance(record, dict):
                continue
            rows.append((str(user_id), int(record.get("level", 0)), int(record.get("messages", 0))))
        rows.sort(key=lambda row: (-row[1], -row[2]))
        lines = [
            f"**{index}.** <@{user_id}> — Lv.{level}（{messages:,}回）"
            for index, (user_id, level, messages) in enumerate(rows[:20], start=1)
        ]
        embed = discord.Embed(
            title="🏆 サーバーレベルランキング",
            description="\n".join(lines) if lines else "まだランキングデータがないよ。",
            color=discord.Color.gold(),
        )
        embed.set_footer(text="このサーバーのメンバーだけを集計")
        await interaction.response.send_message(embed=embed)
    
    
    bot.tree.add_command(lv_group)
    
    
    # ==================================================
    # 一時ニックネーム（30分で元に戻す）
    # ==================================================
    def save_temporary_nicknames():
        return save_json(TEMP_NICKNAMES_FILE, temporary_nicknames)
    
    
    @bot.command(name="nicck")
    async def temporary_nickname_command(ctx: commands.Context, member: discord.Member, *, nickname: str):
        if ctx.guild is None:
            return
        nickname = nickname.strip()
        if not nickname or len(nickname) > 32:
            await ctx.reply("ニックネームは1〜32文字で入力してね。", mention_author=False)
            return
        if member.id == ctx.guild.owner_id or member.bot:
            await ctx.reply("サーバーオーナーまたはBotのニックネームは変更できないよ。", mention_author=False)
            return
    
        bot_member = ctx.guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_nicknames:
            await ctx.reply("Botに「ニックネームの管理」権限が必要だよ。", mention_author=False)
            return
        if member.top_role >= bot_member.top_role:
            await ctx.reply("そのメンバーのロールがBotと同じか上位なので変更できないよ。", mention_author=False)
            return
    
        key = f"{ctx.guild.id}:{member.id}"
        previous = temporary_nicknames.get(key)
        # すでに一時変更中なら、最初に保存した元のニックネームを維持する
        original_nick = previous.get("original_nick") if isinstance(previous, dict) else member.nick
        try:
            await member.edit(nick=nickname, reason=f"Temporary nickname set by {ctx.author} for 30 minutes")
        except discord.Forbidden:
            await ctx.reply("ニックネームを変更できなかったよ。Botの権限とロール位置を確認してね。", mention_author=False)
            return
        except discord.HTTPException:
            await ctx.reply("ニックネームの変更に失敗したよ。", mention_author=False)
            return
    
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp()
        temporary_nicknames[key] = {
            "guild_id": ctx.guild.id,
            "user_id": member.id,
            "original_nick": original_nick,
            "temporary_nick": nickname,
            "expires_at": expires_at,
        }
        if not save_temporary_nicknames():
            temporary_nicknames.pop(key, None)
            try:
                await member.edit(nick=original_nick, reason="Temporary nickname could not be saved")
            except discord.HTTPException:
                logger.exception("一時ニックネーム保存失敗後の復元にも失敗")
            await ctx.reply("Neonへの保存に失敗したため、変更を取り消したよ。", mention_author=False)
            return
    
        await ctx.reply(
            f"✅ {member.mention} のニックネームを **{discord.utils.escape_markdown(nickname)}** に変更したよ。\n30分後に元へ戻すね。",
            mention_author=False,
        )
    
    
    @tasks.loop(seconds=30)
    async def temporary_nickname_expiry_loop():
        now = datetime.now(timezone.utc).timestamp()
        changed = False
        for key, record in list(temporary_nicknames.items()):
            if not isinstance(record, dict):
                temporary_nicknames.pop(key, None)
                changed = True
                continue
            try:
                expires_at = float(record.get("expires_at", 0))
                guild_id = int(record.get("guild_id", 0))
                user_id = int(record.get("user_id", 0))
            except (TypeError, ValueError):
                temporary_nicknames.pop(key, None)
                changed = True
                continue
            if expires_at > now:
                continue
    
            guild = bot.get_guild(guild_id)
            member = guild.get_member(user_id) if guild else None
            if member is not None:
                # 途中で本人や管理者がニックネームを変えていた場合は上書きしない
                if member.nick == record.get("temporary_nick"):
                    try:
                        await member.edit(
                            nick=record.get("original_nick"),
                            reason="Temporary nickname expired after 30 minutes",
                        )
                    except discord.Forbidden:
                        logger.warning("一時ニックネームを元に戻せません（権限/ロール位置）: %s", key)
                        continue
                    except discord.HTTPException:
                        logger.exception("一時ニックネームの復元に失敗: %s", key)
                        continue
            temporary_nicknames.pop(key, None)
            changed = True
    
        if changed:
            save_temporary_nicknames()
    
    
    @temporary_nickname_expiry_loop.before_loop
    async def before_temporary_nickname_expiry_loop():
        await bot.wait_until_ready()
    
    
    
    @bot.listen()
    async def on_message(message: discord.Message):
        if message.author.bot:
            return
    
        if await process_anti_spam_message(message):
            return
    
        antimalware_triggered = await process_antimalware_message(message)
        if not antimalware_triggered:
            await process_anti_mention(message)
            try:
                await process_level_message(message)
            except Exception:
                logger.exception("レベルメッセージ処理に失敗")
    
        if message.guild is not None and pattern.search(message.content):
            config = get_au_settings(message.guild.id)
            user_id = str(message.author.id)
            if config.get("enabled", True) and user_id not in config.get("whitelist", []):
                try:
                    charge_limit = max(1, min(1000000, int(config.get("charge_limit", 1000))))
                    amount = random.randint(1, charge_limit)
                    record_au_charge(message.guild.id, message.author.id, amount)
                    previous_min = config.get("charge_min")
                    previous_max = config.get("charge_max")
                    config["charge_min"] = amount if previous_min is None else min(int(previous_min), amount)
                    config["charge_max"] = amount if previous_max is None else max(int(previous_max), amount)
                    save_json(AU_SETTINGS_FILE, au_settings)
                    charge_stats = None
                    if config.get("show_charge_extremes", False):
                        charge_stats = {"min": config["charge_min"], "max": config["charge_max"]}
                    await message.channel.send(
                        embed=make_au_message(message.author, amount, charge_stats=charge_stats),
                        view=AuPaymentView(message.guild.id, message.author.id, amount),
                    )
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
                        elif error_message:
                            logger.warning("あうタイムアウト: %s", error_message)
                except Exception:
                    logger.exception("あう検知処理に失敗")
    
        await process_guess_message(message)
        
    
    
    
    # ==================================================
    # マルウェア・迷惑投稿の自動検知（設定はNeonへ保存）
    # ==================================================
    def normalize_antimalware_text(value: str) -> str:
        value = str(value or "").casefold()
        value = re.sub(r"[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]", "", value)
        return re.sub(r"\s+", " ", value).strip()
    
    
    def get_antimalware_config(guild_id: int):
        key = str(guild_id)
        data = antimalware_settings.get(key)
        if not isinstance(data, dict):
            data = {
                "enabled": False,
                "timeout_minutes": 10,
                "images": [],
                "words": [ANTIMALWARE_DEFAULT_PHRASE],
                "log_channel_id": None,
            }
            antimalware_settings[key] = data
        data.setdefault("enabled", False)
        data.setdefault("timeout_minutes", 10)
        data.setdefault("images", [])
        data.setdefault("words", [ANTIMALWARE_DEFAULT_PHRASE])
        data.setdefault("log_channel_id", None)
        return data
    
    
    async def process_antimalware_message(message: discord.Message) -> bool:
        if message.guild is None or not isinstance(message.author, discord.Member):
            return False
        guild = message.guild
        member = message.author
        cfg = get_antimalware_config(guild.id)
        if not cfg.get("enabled", False) or member.bot:
            return False
        if member.id == guild.owner_id or member.guild_permissions.administrator:
            return False
    
        reasons = []
        if message.mention_everyone:
            reasons.append("@everyone / @here")
    
        normalized_content = normalize_antimalware_text(message.content)
        for word in cfg.get("words", []):
            normalized_word = normalize_antimalware_text(word)
            if normalized_word and normalized_word in normalized_content:
                reasons.append("登録された文章")
                break
    
        registered_hashes = {
            str(item.get("sha256"))
            for item in cfg.get("images", [])
            if isinstance(item, dict) and item.get("sha256")
        }
        if registered_hashes:
            image_attachments = [
                attachment for attachment in message.attachments
                if (attachment.content_type or "").lower().startswith("image/")
            ]
            if image_attachments:
                # 画像が複数枚ある投稿は、添付された画像がすべて登録画像と一致した場合だけ
                # 「登録画像のみの投稿」として検知する。未登録画像が1枚でも混ざれば画像理由では処分しない。
                all_images_registered = True
                for attachment in image_attachments:
                    if attachment.size > 8 * 1024 * 1024:
                        all_images_registered = False
                        break
                    try:
                        raw = await attachment.read(use_cached=True)
                        if hashlib.sha256(raw).hexdigest() not in registered_hashes:
                            all_images_registered = False
                            break
                    except (discord.HTTPException, OSError):
                        logger.exception("マルウェア検知用画像の取得に失敗")
                        all_images_registered = False
                        break
                if all_images_registered:
                    reasons.append("登録された画像（添付画像すべて一致）")
    
        if not reasons:
            return False
    
        try:
            timeout_minutes = max(1, min(40320, int(cfg.get("timeout_minutes", 10))))
        except (TypeError, ValueError):
            timeout_minutes = 10
    
        bot_member = guild.me
        timeout_ok = (
            bot_member is not None
            and bot_member.guild_permissions.moderate_members
            and member.top_role < bot_member.top_role
        )
        action_errors = []
        if timeout_ok:
            try:
                await member.timeout(
                    discord.utils.utcnow() + timedelta(minutes=timeout_minutes),
                    reason="MINATANN自動検知: " + ", ".join(reasons),
                )
            except (discord.Forbidden, discord.HTTPException):
                action_errors.append("タイムアウトに失敗")
                logger.exception("マルウェア検知のタイムアウトに失敗")
        else:
            action_errors.append("Botの権限またはロール階層を確認してね")
    
        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            action_errors.append("投稿の削除に失敗")
            logger.exception("マルウェア検知投稿の削除に失敗")
    
        log_text = (
            f"🚨 **自動検知**\n"
            f"対象：{member.mention} ({member.id})\n"
            f"検知理由：{', '.join(reasons)}\n"
            f"タイムアウト：{'成功' if timeout_ok and not action_errors else '要確認'}（{timeout_minutes}分）"
        )
        log_channel_id = cfg.get("log_channel_id")
        log_channel = guild.get_channel(int(log_channel_id)) if log_channel_id else None
        if isinstance(log_channel, discord.TextChannel):
            try:
                await log_channel.send(log_text)
            except discord.HTTPException:
                logger.exception("マルウェア検知ログの送信に失敗")
        else:
            try:
                await message.channel.send(
                    f"🚨 {member.mention} の投稿を検知しました。"
                    f"理由：{', '.join(reasons)}。{timeout_minutes}分のタイムアウト処理を実行しました。"
                )
            except discord.HTTPException:
                logger.exception("マルウェア検知通知の送信に失敗")
    
        if action_errors:
            logger.warning("マルウェア検知の処理に要確認事項: %s", "; ".join(action_errors))
        return True
    
    
    anti_group = app_commands.Group(
        name="anti",
        description="MINATANNの迷惑投稿・マルウェア対策",
    )
    
    
    @anti_group.command(name="malware", description="自動検知の全設定をまとめて操作")
    @app_commands.guild_only()
    @app_commands.choices(action=[
        app_commands.Choice(name="有効化", value="enable"),
        app_commands.Choice(name="停止", value="disable"),
        app_commands.Choice(name="設定確認", value="status"),
        app_commands.Choice(name="タイムアウト時間を変更", value="timeout"),
        app_commands.Choice(name="検知画像を追加", value="add_image"),
        app_commands.Choice(name="検知画像を削除", value="remove_image"),
        app_commands.Choice(name="検知文章を追加", value="add_word"),
        app_commands.Choice(name="検知文章を削除", value="remove_word"),
        app_commands.Choice(name="ログチャンネルを設定", value="log_channel"),
    ])
    @app_commands.describe(
        action="実行する操作",
        minutes="タイムアウト時間（1〜40320分）",
        image1="登録する画像1（8MB以下）",
        image2="登録する画像2（8MB以下）",
        image3="登録する画像3（8MB以下）",
        image4="登録する画像4（8MB以下）",
        number="削除する画像番号（1〜4）",
        text="追加または削除する検知文章",
        channel="検知ログの送信先",
    )
    async def anti_malware(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        minutes: app_commands.Range[int, 1, 40320] | None = None,
        image1: discord.Attachment | None = None,
        image2: discord.Attachment | None = None,
        image3: discord.Attachment | None = None,
        image4: discord.Attachment | None = None,
        number: app_commands.Range[int, 1, 4] | None = None,
        text: str | None = None,
        channel: discord.TextChannel | None = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        user = interaction.user
        if not (user.id == guild.owner_id or user.guild_permissions.administrator):
            await interaction.response.send_message("サーバーオーナーまたは管理者だけが設定できるよ。", ephemeral=True)
            return
    
        cfg = get_antimalware_config(guild.id)
        operation = action.value
    
        if operation == "enable":
            cfg["enabled"] = True
            save_json(ANTIMALWARE_FILE, antimalware_settings)
            await interaction.response.send_message("自動検知を有効にしたよ。", ephemeral=True)
            return
    
        if operation == "disable":
            cfg["enabled"] = False
            save_json(ANTIMALWARE_FILE, antimalware_settings)
            await interaction.response.send_message("自動検知を停止したよ。", ephemeral=True)
            return
    
        if operation == "status":
            log_id = cfg.get("log_channel_id")
            log_channel = guild.get_channel(int(log_id)) if log_id else None
            await interaction.response.send_message(
                f"**MINATANN 自動検知設定**\n"
                f"状態：{'ON' if cfg.get('enabled') else 'OFF'}\n"
                f"タイムアウト：{cfg.get('timeout_minutes', 10)}分\n"
                f"登録画像：{len(cfg.get('images', []))}/4枚\n"
                f"登録文章：{len(cfg.get('words', []))}件\n"
                f"@everyone / @here：検知対象\n"
                f"ログ先：{log_channel.mention if log_channel else '未設定'}",
                ephemeral=True,
            )
            return
    
        if operation == "timeout":
            if minutes is None:
                await interaction.response.send_message("minutes に時間を入力してね。", ephemeral=True)
                return
            cfg["timeout_minutes"] = int(minutes)
            save_json(ANTIMALWARE_FILE, antimalware_settings)
            await interaction.response.send_message(f"タイムアウト時間を **{minutes}分** に設定したよ。", ephemeral=True)
            return
    
        if operation == "add_image":
            selected_images = [item for item in (image1, image2, image3, image4) if item is not None]
            if not selected_images:
                await interaction.response.send_message("image1〜image4 に登録する画像を添付してね。", ephemeral=True)
                return
            for attachment in selected_images:
                if not (attachment.content_type or "").lower().startswith("image/") or attachment.size > 8 * 1024 * 1024:
                    await interaction.response.send_message("すべて画像ファイル（各8MB以下）にしてね。", ephemeral=True)
                    return
            images = cfg.setdefault("images", [])
            if len(images) + len(selected_images) > 4:
                await interaction.response.send_message(f"あと{4 - len(images)}枚登録できるよ。選択した画像が上限を超えているよ。", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                pending = []
                known_hashes = {item.get("sha256") for item in images if isinstance(item, dict)}
                for attachment in selected_images:
                    raw = await attachment.read(use_cached=True)
                    digest = hashlib.sha256(raw).hexdigest()
                    if digest in known_hashes:
                        continue
                    known_hashes.add(digest)
                    pending.append({"sha256": digest, "filename": attachment.filename[:100]})
            except (discord.HTTPException, OSError):
                await interaction.followup.send("画像を読み込めなかったよ。登録内容は変更していないよ。", ephemeral=True)
                return
            if not pending:
                await interaction.followup.send("選択した画像はすべて登録済みだよ。", ephemeral=True)
                return
            images.extend(pending)
            save_json(ANTIMALWARE_FILE, antimalware_settings)
            await interaction.followup.send(f"{len(pending)}枚の画像をまとめて登録したよ（{len(images)}/4枚）。", ephemeral=True)
            return
    
        if operation == "remove_image":
            if number is None:
                await interaction.response.send_message("number に削除する画像番号を入力してね。", ephemeral=True)
                return
            images = cfg.setdefault("images", [])
            if number > len(images):
                await interaction.response.send_message("その番号の画像は登録されていないよ。", ephemeral=True)
                return
            removed = images.pop(number - 1)
            save_json(ANTIMALWARE_FILE, antimalware_settings)
            await interaction.response.send_message(
                f"{discord.utils.escape_markdown(removed.get('filename', '画像'))} を削除したよ。",
                ephemeral=True,
            )
            return
    
        if operation in ("add_word", "remove_word"):
            if not text or not normalize_antimalware_text(text):
                await interaction.response.send_message("text に文章を入力してね。", ephemeral=True)
                return
            words = cfg.setdefault("words", [])
            normalized = normalize_antimalware_text(text)
            if operation == "add_word":
                if any(normalize_antimalware_text(item) == normalized for item in words):
                    await interaction.response.send_message("その文章はすでに登録されているよ。", ephemeral=True)
                    return
                if len(words) >= 20:
                    await interaction.response.send_message("登録できる文章は最大20件だよ。", ephemeral=True)
                    return
                words.append(text[:200])
                save_json(ANTIMALWARE_FILE, antimalware_settings)
                await interaction.response.send_message("検知する文章を追加したよ。", ephemeral=True)
            else:
                before = len(words)
                cfg["words"] = [item for item in words if normalize_antimalware_text(item) != normalized]
                if len(cfg["words"]) == before:
                    await interaction.response.send_message("その文章は登録されていないよ。", ephemeral=True)
                    return
                save_json(ANTIMALWARE_FILE, antimalware_settings)
                await interaction.response.send_message("検知文章を削除したよ。", ephemeral=True)
            return
    
        if operation == "log_channel":
            if channel is None:
                await interaction.response.send_message("channel にログ先を指定してね。", ephemeral=True)
                return
            cfg["log_channel_id"] = channel.id
            save_json(ANTIMALWARE_FILE, antimalware_settings)
            await interaction.response.send_message(f"検知ログを {channel.mention} に送るよ。", ephemeral=True)
            return
    
    
    bot.tree.add_command(anti_group)
    
    
    # ==================================================
    # Neon保存（JSONファイルへの書き込みは行わない）
    # ==================================================
    def load_json(path, default):
        """旧JSONファイルは使用しない。互換初期化用に既定値を返す。"""
        return default
    
    
    JSON_STORE_FILE_KEYS = {
        "welcome_config.json": "welcome_config",
        "guess_data.json": "guess_data",
        "au_settings.json": "au_settings",
        "au_timeout_records.json": "au_timeout_records",
        "au_debt_records.json": "au_debt_records",
        "au_whitelist.json": "au_whitelist",
        "anti_mention_settings.json": "anti_mention_settings",
        "exchange_requests.json": "exchange_requests",
        "count_channels.json": "count_channels",
        "antimalware_settings.json": "antimalware_settings",
        "server_logs.json": "server_logs",
        "role_panels.json": "role_panels",
        "ticket_panels.json": "ticket_panels",
        "level_settings.json": "level_settings",
        "level_data.json": "level_data",
        "temporary_nicknames.json": "temporary_nicknames",
        "verify_settings.json": "verify_settings",
        "achievement_settings.json": "achievement_settings",
        "polls.json": "polls",
        "spam_settings.json": "spam_settings",
        "anti_spam_settings.json": "anti_spam_settings",
    }
    _json_store_lock = asyncio.Lock()
    _json_store_ready = False
    _json_store_pending = {}
    
    
    async def _write_json_store_value(key: str, payload: str):
        if _tiktok_db_pool is None:
            raise RuntimeError("Neon接続プールが初期化されていません")
        async with _json_store_lock:
            async with _tiktok_db_pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO minatann_json_store (setting_key, data, updated_at)
                    VALUES ($1, $2::jsonb, NOW())
                    ON CONFLICT (setting_key)
                    DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                    """,
                    key,
                    payload,
                )
    
    
    async def _flush_json_store_key(key: str):
        while key in _json_store_pending:
            payload = _json_store_pending.pop(key)
            try:
                await _write_json_store_value(key, payload)
            except Exception:
                logger.exception("Neon設定保存失敗: %s", key)
                # 次回の保存で再試行できるようにする
                _json_store_pending.setdefault(key, payload)
                return
    
    
    def save_json(path, value):
        """互換用の同期関数。データはメモリからNeonへ非同期保存する。"""
        filename = Path(path).name
        key = JSON_STORE_FILE_KEYS.get(filename)
        if key is None:
            logger.error("Neon保存先が未登録: %s", filename)
            return False
        try:
            if filename == "au_whitelist.json":
                value = list(value)
            payload = json.dumps(value, ensure_ascii=False)
            _json_store_pending[key] = payload
            if _json_store_ready:
                asyncio.get_running_loop().create_task(_flush_json_store_key(key))
            return True
        except Exception:
            logger.exception("Neon保存タスクの登録に失敗: %s", filename)
            return False
    
    
    def is_owner_user(user):
        return getattr(user, "id", None) == 1325449934236942392
    
    
    async def require_owner(interaction):
        if is_owner_user(interaction.user):
            return True
        message = "この設定はBot所有者だけが変更できます。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False
    
    
    pattern = re.compile(r"あう")
    AU_SETTINGS_FILE = Path("au_settings.json")
    AU_TIMEOUTS_FILE = Path("au_timeout_records.json")
    AU_DEBT_FILE = Path("au_debt_records.json")
    AU_WHITELIST_FILE = Path("au_whitelist.json")
    ANTI_MENTION_FILE = Path("anti_mention_settings.json")
    ANTIMALWARE_FILE = Path("antimalware_settings.json")
    ANTIMALWARE_DEFAULT_PHRASE = "# Check my bi0 😁"
    antimalware_settings = load_json(ANTIMALWARE_FILE, {})
    AU_TIMEOUT_TASKS = {}
    au_whitelist = set(str(x) for x in load_json(AU_WHITELIST_FILE, []))
    au_settings = load_json(AU_SETTINGS_FILE, {})
    au_timeout_records = load_json(AU_TIMEOUTS_FILE, {})
    au_debt_records = load_json(AU_DEBT_FILE, {})
    anti_mention_settings = load_json(ANTI_MENTION_FILE, {})
    ANTI_SPAM_FILE = "anti_spam_settings.json"
    anti_spam_settings = load_json(ANTI_SPAM_FILE, {})
    anti_spam_histories = {}
    
    
    def format_au_charge(amount):
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
    
        @discord.ui.button(label="お支払い", style=discord.ButtonStyle.danger, emoji="💳")
        async def pay_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.target_user_id:
                await interaction.response.send_message("❌ このボタンは請求対象の本人だけが押せます。", ephemeral=True)
                return
            if self.paid:
                await interaction.response.send_message("この請求はすでに支払い済みとして記録されているよ。", ephemeral=True)
                return
            record_au_payment(self.guild_id, self.target_user_id, self.amount)
            self.paid = True
            completed_embed = make_au_message(interaction.user, self.amount, completed=True)
            completed_embed.add_field(
                name="支払い記録",
                value=f"請求額：**{format_au_charge(self.amount)}**\n支払い済みとして記録したよ。",
                inline=False,
            )
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=completed_embed, view=self)
    
    
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
    
    
    
    
    async def process_anti_mention(message: discord.Message):
        if message.guild is None:
            return
        guild = message.guild
        author = message.author
        config = anti_mention_settings.get(
            str(guild.id),
            {"mention_threshold": 5, "timeout_minutes": 10},
        )
        try:
            mention_threshold = max(1, int(config.get("mention_threshold", 5)))
            timeout_minutes = max(1, min(40320, int(config.get("timeout_minutes", 10))))
        except (TypeError, ValueError):
            mention_threshold, timeout_minutes = 5, 10
    
        unique_mention_count = len({member.id for member in message.mentions})
        triggered = message.mention_everyone or unique_mention_count >= mention_threshold
        is_exempt = (
            author.id == guild.owner_id
            or (isinstance(author, discord.Member) and author.guild_permissions.administrator)
        )
        if not triggered or is_exempt or author.bot or not isinstance(author, discord.Member):
            return
    
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.moderate_members:
            logger.warning("大量メンション対策: Botにタイムアウト権限がありません")
            return
        if author.top_role >= bot_member.top_role:
            logger.warning("大量メンション対策: ロール階層のためタイムアウト不可: %s", author)
            return
        try:
            await author.timeout(
                discord.utils.utcnow() + timedelta(minutes=timeout_minutes),
                reason=f"大量メンション自動対策 (everyone/here={message.mention_everyone}, unique_mentions={unique_mention_count})",
            )
            await message.channel.send(
                f"🚫 {author.display_name} を大量メンションのため {timeout_minutes}分間タイムアウトしました。"
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("大量メンションのタイムアウト処理に失敗")
    
    
    @bot.tree.command(
        name="antimention",
        description="大量メンションの検知人数とタイムアウト時間を設定します",
    )
    @app_commands.describe(
        mention_threshold="タイムアウト対象にするメンション人数（1〜100人）",
        timeout_minutes="タイムアウトする時間（1〜40320分）",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def antimention_command(
        interaction: discord.Interaction,
        mention_threshold: app_commands.Range[int, 1, 100],
        timeout_minutes: app_commands.Range[int, 1, 40320],
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内で使ってね。",
                ephemeral=True,
            )
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("サーバー管理権限が必要だよ。", ephemeral=True)
            return
    
        guild_key = str(interaction.guild.id)
        anti_mention_settings[guild_key] = {
            "mention_threshold": int(mention_threshold),
            "timeout_minutes": int(timeout_minutes),
        }
        save_json(ANTI_MENTION_FILE, anti_mention_settings)
    
        await interaction.response.send_message(
            "✅ 大量メンション対策を設定しました。\n"
            f"検知人数：**{mention_threshold}人以上**（同じ人の重複は1人として計算）\n"
            f"タイムアウト：**{timeout_minutes}分**\n"
            "対象：@everyone / @here / 設定人数以上のユーザーメンション\n"
            "除外：サーバーオーナー・管理者権限を持つメンバー",
            ephemeral=True,
        )
    
    
    @bot.tree.command(
        name="untimeout",
        description="指定したメンバーのタイムアウトを解除します",
    )
    @app_commands.describe(
        member="タイムアウトを解除するメンバー",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    async def unantimention_command(
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内で使ってね。",
                ephemeral=True,
            )
            return
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message("メンバーをタイムアウトできる権限が必要だよ。", ephemeral=True)
            return
    
        # 既にタイムアウトされていない場合
        timed_out_until = member.timed_out_until
        if timed_out_until is None or timed_out_until <= datetime.now(timezone.utc):
            await interaction.response.send_message(
                f"ℹ️ {member.mention} はタイムアウトされていません。",
                ephemeral=True,
            )
            return
    
        try:
            await member.timeout(
                None,
                reason=f"Timeout解除（実行者: {interaction.user}）",
            )
            await interaction.response.send_message(
                f"✅ {member.mention} のタイムアウトを解除しました。",
            )
            # 成功通知は5秒後に自動削除
            try:
                response_message = await interaction.original_response()
                await response_message.delete(delay=5)
            except discord.HTTPException:
                pass
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ 解除できませんでした。Botに「メンバーをタイムアウト」の権限があるか、対象メンバーのロールがBotより下か確認してね。",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Discord側でエラーが発生したため、タイムアウトを解除できませんでした。",
                ephemeral=True,
            )
    
    
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
    
    
    class AuPanelButton(discord.ui.Button):
        def __init__(self, label, style, action):
            super().__init__(label=label, style=style)
            self.action = action
    
        async def callback(self, interaction: discord.Interaction):
            if not await require_owner(interaction):
                return
            if interaction.guild is None:
                await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
                return
    
            config = get_au_settings(interaction.guild.id)
            action = self.action
    
            if action == "toggle_detection":
                config["enabled"] = not config.get("enabled", True)
                save_json(AU_SETTINGS_FILE, au_settings)
                await interaction.response.edit_message(view=AuSettingPanelView(interaction.guild.id))
            elif action == "toggle_timeout":
                config["timeout_enabled"] = not config.get("timeout_enabled", False)
                save_json(AU_SETTINGS_FILE, au_settings)
                await interaction.response.edit_message(view=AuSettingPanelView(interaction.guild.id))
            elif action == "set_time":
                await interaction.response.send_modal(AuTimeoutModal())
            elif action == "wl_add":
                await interaction.response.send_modal(AuWhitelistModal("add"))
            elif action == "wl_remove":
                await interaction.response.send_modal(AuWhitelistModal("remove"))
            elif action == "wl_list":
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
            elif action == "charge_limit":
                await interaction.response.send_modal(AuChargeLimitModal())
            elif action == "toggle_extremes":
                config["show_charge_extremes"] = not config.get("show_charge_extremes", False)
                save_json(AU_SETTINGS_FILE, au_settings)
                await interaction.response.edit_message(view=AuSettingPanelView(interaction.guild.id))
            elif action == "reset_extremes":
                config["charge_min"] = None
                config["charge_max"] = None
                save_json(AU_SETTINGS_FILE, au_settings)
                await interaction.response.edit_message(view=AuSettingPanelView(interaction.guild.id))
            elif action == "exempt_add":
                await interaction.response.send_modal(AuTimeoutExemptChannelModal("add"))
            elif action == "exempt_remove":
                await interaction.response.send_modal(AuTimeoutExemptChannelModal("remove"))
            elif action == "exempt_list":
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
    
    
    class AuSettingPanelView(discord.ui.LayoutView):
        def __init__(self, guild_id: int):
            super().__init__(timeout=300)
    
            config = get_au_settings(guild_id)
            timeout_text = (
                f"ON（{config.get('timeout_seconds', 60)}秒）"
                if config.get("timeout_enabled", False)
                else "OFF"
            )
            detection_text = "ON" if config.get("enabled", True) else "OFF"
            whitelist_count = len(set(str(x) for x in config.get("whitelist", [])))
            charge_limit = format_au_charge(config.get("charge_limit", 1000))
            min_charge = config.get("charge_min")
            max_charge = config.get("charge_max")
            extremes_text = (
                f"最高：{format_au_charge(max_charge)} / 最低：{format_au_charge(min_charge)}"
                if min_charge is not None and max_charge is not None
                else "まだ記録なし"
            )
            exempt_count = len(config.get("timeout_exempt_channels", []))
    
            container = discord.ui.Container(
                discord.ui.TextDisplay(
                    "# 🛡️ au-spam 設定\n"
                    "自動請求・タイムアウト等の設定を管理します。"
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 🤖 自動タイムアウト\n"
                    f"検知：**{detection_text}** ／ 状態：**{timeout_text}**"
                ),
                discord.ui.ActionRow(
                    AuPanelButton("検知 ON / OFF", discord.ButtonStyle.primary, "toggle_detection"),
                    AuPanelButton("タイムアウト ON / OFF", discord.ButtonStyle.danger, "toggle_timeout"),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 👥 ホワイトリスト\n"
                    f"登録数：**{whitelist_count}人**"
                ),
                discord.ui.ActionRow(
                    AuPanelButton("WL追加", discord.ButtonStyle.success, "wl_add"),
                    AuPanelButton("WL削除", discord.ButtonStyle.secondary, "wl_remove"),
                    AuPanelButton("WL一覧", discord.ButtonStyle.secondary, "wl_list"),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 📈 請求上限\n"
                    f"1回あたりの請求上限：**{charge_limit}**"
                ),
                discord.ui.ActionRow(
                    AuPanelButton("請求上限を設定", discord.ButtonStyle.primary, "charge_limit"),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 💰 請求額の範囲\n"
                    f"表示：**{'ON' if config.get('show_charge_extremes', False) else 'OFF'}**\n"
                    f"{extremes_text}"
                ),
                discord.ui.ActionRow(
                    AuPanelButton("最高・最低表示 ON / OFF", discord.ButtonStyle.primary, "toggle_extremes"),
                    AuPanelButton("最高・最低リセット", discord.ButtonStyle.danger, "reset_extremes"),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 🎯 タイムアウト対象外チャンネル\n"
                    f"登録数：**{exempt_count}チャンネル**"
                ),
                discord.ui.ActionRow(
                    AuPanelButton("除外CH追加", discord.ButtonStyle.success, "exempt_add"),
                    AuPanelButton("除外CH削除", discord.ButtonStyle.secondary, "exempt_remove"),
                    AuPanelButton("除外CH一覧", discord.ButtonStyle.secondary, "exempt_list"),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 🕒 タイムアウト仕様\n"
                    "1〜86400秒で指定可能。Discord側は1時間に設定し、指定時間後に自動解除するよ。"
                ),
                discord.ui.ActionRow(
                    AuPanelButton("時間を設定", discord.ButtonStyle.secondary, "set_time"),
                ),
                accent_color=discord.Color.blurple(),
            )
            self.add_item(container)
    
    
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
    
    
    @bot.command(name="au_debt_rank", aliases=["あう借金ランキング"])
    async def au_current_debt_ranking_command(ctx: commands.Context):
        """現在の未払い借金ランキングを表示する。"""
        await send_au_debt_ranking(ctx, "current")
    
    
    @bot.command(name="au_debt_total_rank", aliases=["あう累計借金ランキング"])
    async def au_total_debt_ranking_command(ctx: commands.Context):
        """累計請求額ランキングを表示する。"""
        await send_au_debt_ranking(ctx, "total")
    
    
    @bot.command(name="au_debt_me", aliases=["あう自分の借金"])
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
    
        await interaction.response.send_message(
            view=AuSettingPanelView(interaction.guild.id),
            ephemeral=True,
        )
    
    bot.tree.add_command(au_group)
    
    
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
    
    
    async def exchange_views_ready():
        if not _json_store_ready:
            return
        if getattr(bot, '_exchange_views_registered', False):
            return
        bot._exchange_views_registered = True
        await restore_exchange_views()
    
    bot.add_listener(exchange_views_ready, 'on_ready')
    
    
    # ==================================================
    # サーバー人数・Bot・チャンネル・ロールのカウントボイス
    # ==================================================
    COUNT_CHANNELS_FILE = "count_channels.json"
    count_channel_data = load_json(COUNT_CHANNELS_FILE, {})
    if not isinstance(count_channel_data, dict):
        count_channel_data = {}
    
    
    COUNT_TYPES = [
        app_commands.Choice(name="Member Count（メンバー数）", value="member"),
        app_commands.Choice(name="Bot Count（Bot数）", value="bot"),
        app_commands.Choice(name="Channel Count（チャンネル数）", value="channel"),
        app_commands.Choice(name="Role Count（ロール数）", value="role"),
    ]
    
    
    def get_count_channel_name(guild: discord.Guild, count_type: str) -> str:
        if count_type == "member":
            # メンバー数はBotを除いた人数
            count = sum(1 for member in guild.members if not member.bot)
            return f"👥 Member Count：{count}"
        if count_type == "bot":
            count = sum(1 for member in guild.members if member.bot)
            return f"🤖 Bot Count：{count}"
        if count_type == "channel":
            return f"💬 Channel Count：{len(guild.channels)}"
        if count_type == "role":
            # @everyoneロールは数えない
            return f"🎭 Role Count：{max(0, len(guild.roles) - 1)}"
        raise ValueError("Unknown count type")
    
    
    def save_count_channel_data() -> bool:
        return save_json(COUNT_CHANNELS_FILE, count_channel_data)
    
    
    async def refresh_count_channels(guild: discord.Guild):
        guild_key = str(guild.id)
        configured = count_channel_data.get(guild_key, {})
        if not isinstance(configured, dict):
            return
        changed = False
        for count_type, channel_id in list(configured.items()):
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.VoiceChannel):
                configured.pop(count_type, None)
                changed = True
                continue
            try:
                new_name = get_count_channel_name(guild, count_type)
                if channel.name != new_name:
                    await channel.edit(name=new_name, reason="MINATANN count channel auto update")
            except discord.Forbidden:
                logger.warning("カウントチャンネルを更新できません（権限不足）: guild=%s", guild.id)
            except discord.HTTPException:
                logger.exception("カウントチャンネル更新失敗: guild=%s", guild.id)
        if changed:
            if not configured:
                count_channel_data.pop(guild_key, None)
            save_count_channel_data()
    
    
    async def refresh_all_count_channels():
        for guild in bot.guilds:
            await refresh_count_channels(guild)
    
    
    any_group = app_commands.Group(
        name="any",
        description="サーバーのカウント機能",
    )
    
    
    @any_group.command(name="count", description="カウント用ボイスチャンネルを作成・設定")
    @app_commands.describe(count_type="ボイスチャンネルに表示するカウント")
    @app_commands.choices(count_type=COUNT_TYPES)
    async def any_count_command(
        interaction: discord.Interaction,
        count_type: app_commands.Choice[str],
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
    
        # Discordの応答期限切れを防ぐ
        await interaction.response.defer(ephemeral=True, thinking=True)
    
        try:
            guild_key = str(guild.id)
            configured = count_channel_data.setdefault(guild_key, {})
            key = count_type.value
    
            # メンバー一覧の取得は時間がかかることがあるため、8秒で打ち切ってキャッシュを使う
            try:
                await asyncio.wait_for(guild.chunk(cache=True), timeout=8)
            except (asyncio.TimeoutError, discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "メンバー情報の最新化を省略し、キャッシュ人数でカウントします: guild=%s",
                    guild.id,
                )
    
            existing_id = configured.get(key)
            existing_channel = guild.get_channel(int(existing_id)) if existing_id else None
            channel_name = get_count_channel_name(guild, key)
    
            if isinstance(existing_channel, discord.VoiceChannel):
                await existing_channel.edit(
                    name=channel_name,
                    reason="MINATANN count channel setup/update",
                )
                channel = existing_channel
                action_text = "既存のカウントチャンネルを更新したよ"
            else:
                channel = await guild.create_voice_channel(
                    name=channel_name,
                    reason=f"MINATANN {key} count channel",
                )
                configured[key] = channel.id
    
            if not save_count_channel_data():
                await interaction.followup.send(
                    "チャンネルは作成・更新できたけど、設定の保存登録に失敗したよ。管理者に知らせてね。",
                    ephemeral=True,
                )
                return
    
            await interaction.followup.send(
                f"✅ {action_text}！\n{channel.mention}\n"
                "ほかの種類も続けて設定できるよ。人数・チャンネル・ロールの変化に合わせて名前を自動更新するよ。",
                ephemeral=True,
            )
    
        except discord.Forbidden:
            await interaction.followup.send(
                "ボイスチャンネルを作成・編集できなかったよ。Botに「チャンネルの管理」権限を付けてね。",
                ephemeral=True,
            )
        except discord.HTTPException:
            logger.exception("カウントチャンネル設定に失敗")
            await interaction.followup.send(
                "Discordとの通信中にエラーが発生したよ。少し待ってからもう一度試してね。",
                ephemeral=True,
            )
        except Exception:
            logger.exception("カウントチャンネル設定で予期しないエラー")
            await interaction.followup.send(
                "設定中に予期しないエラーが発生したよ。ログを確認するね。",
                ephemeral=True,
            )
    
    bot.tree.add_command(any_group)
    
    
    @bot.listen("on_ready")
    async def count_channels_on_ready():
        await refresh_all_count_channels()
    
    
    @bot.listen("on_member_join")
    async def count_channels_member_join(member: discord.Member):
        await asyncio.sleep(1)
        await refresh_count_channels(member.guild)
    
    
    @bot.listen("on_member_remove")
    async def count_channels_member_remove(member: discord.Member):
        await asyncio.sleep(1)
        await refresh_count_channels(member.guild)
    
    
    @bot.listen("on_guild_channel_create")
    async def count_channels_channel_create(channel):
        await refresh_count_channels(channel.guild)
    
    
    @bot.listen("on_guild_channel_delete")
    async def count_channels_channel_delete(channel):
        await refresh_count_channels(channel.guild)
    
    
    @bot.listen("on_guild_role_create")
    async def count_channels_role_create(role):
        await refresh_count_channels(role.guild)
    
    
    @bot.listen("on_guild_role_delete")
    async def count_channels_role_delete(role):
        await refresh_count_channels(role.guild)
    
    
    @bot.tree.command(name="minatann_servers", description="移行元MINATANNのサーバー数を表示")
    async def servers_command(interaction: discord.Interaction):
        server_count = len(bot.guilds)
        embed = discord.Embed(
            title="🌐 MINATANN サーバー参加状況",
            description=f"現在、**{server_count:,} サーバー**に参加しているよ！",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="MINATANN便利bot")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
            message = "このBotのコマンドはサーバーオーナーまたは管理者だけが使えるよ。"
        else:
            logger.error(
                "スラッシュコマンドエラー",
                exc_info=(type(error), error, error.__traceback__)
            )
            message = "エラーが発生したよ。時間をおいてもう一度試してね。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    
    
    @bot.listen()
    async def on_command_error(ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("このBotのコマンドはサーバーオーナーまたは管理者だけが使えるよ。")
            return
        logger.error(
            "プレフィックスコマンドエラー",
            exc_info=(type(error), error, error.__traceback__),
        )
    
    
    
    
    # ==================================================
    # 実績記入フォーム（Neon保存）
    # ==================================================
    achievement_settings = {}
    poll_data = {}
    
    
    class AchievementModal(discord.ui.Modal, title="実績記入フォーム"):
        product_name = discord.ui.TextInput(label="商品名", placeholder="商品名を入力", required=True, max_length=100)
        quantity = discord.ui.TextInput(label="個数", placeholder="例：2", required=True, max_length=8)
        rating = discord.ui.TextInput(label="評価（1〜5）", placeholder="1〜5の数字で入力", required=True, max_length=1)
        impression = discord.ui.TextInput(
            label="感想", placeholder="商品の感想を入力",
            style=discord.TextStyle.paragraph, required=True, max_length=1000,
        )
    
        async def on_submit(self, interaction: discord.Interaction):
            if interaction.guild is None:
                await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
                return
            quantity_text = str(self.quantity.value).strip()
            rating_text = str(self.rating.value).strip()
            if not quantity_text.isdigit() or int(quantity_text) < 1:
                await interaction.response.send_message("個数は1以上の数字で入力してね。", ephemeral=True)
                return
            if rating_text not in ("1", "2", "3", "4", "5"):
                await interaction.response.send_message("評価は1〜5の数字で入力してね。", ephemeral=True)
                return
    
            cfg = achievement_settings.get(str(interaction.guild.id), {})
            output_channel = interaction.guild.get_channel(int(cfg.get("output_channel_id", 0)))
            if not isinstance(output_channel, discord.TextChannel):
                await interaction.response.send_message("実績の投稿先チャンネルが見つからないよ。管理者に再設定をお願いしてね。", ephemeral=True)
                return
    
            score = int(rating_text)
            stars = "⭐️" * score + "⭐︎" * (5 - score)
            rating_faces = {
                1: "😩",
                2: "😞",
                3: "😐",
                4: "🙂",
                5: "😊",
            }
            rating_display = f"{stars} {rating_faces[score]}"
            embed = discord.Embed(title="📦 実績報告", color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
            embed.add_field(name="商品名", value=str(self.product_name.value).strip(), inline=False)
            embed.add_field(name="個数", value=f"{int(quantity_text)}個", inline=True)
            embed.add_field(name="評価", value=rating_display, inline=True)
            embed.add_field(name="感想", value=str(self.impression.value).strip(), inline=False)
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            embed.set_footer(text=f"投稿者：{interaction.user}")
            try:
                await output_channel.send(embed=embed)
            except discord.Forbidden:
                await interaction.response.send_message("実績を投稿できなかったよ。Botのチャンネル権限を確認してね。", ephemeral=True)
                return
            except discord.HTTPException:
                await interaction.response.send_message("実績の投稿に失敗したよ。もう一度試してね。", ephemeral=True)
                return
            await interaction.response.send_message(f"✅ 実績を {output_channel.mention} に投稿したよ。", ephemeral=True)
    
    
    class AchievementPanelView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
    
        @discord.ui.button(label="実績を記入する", style=discord.ButtonStyle.success,
                           custom_id="minatann_achievement:open", emoji="📝")
        async def open_achievement(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.guild is None:
                await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
                return
            if not achievement_settings.get(str(interaction.guild.id)):
                await interaction.response.send_message("実績フォームが設定されていないよ。管理者に設定をお願いしてね。", ephemeral=True)
                return
            await interaction.response.send_modal(AchievementModal())
    
    
    achievement_group = app_commands.Group(name="achievement", description="実績記入フォームの設定")
    
    
    @achievement_group.command(name="setup", description="実績フォームの設置先と投稿先を設定")
    @app_commands.describe(
        panel_channel="実績記入ボタンを設置するチャンネル",
        output_channel="記入された実績を投稿するチャンネル",
    )
    async def achievement_setup(
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel,
        output_channel: discord.TextChannel,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        bot_member = interaction.guild.me
        if bot_member is None:
            await interaction.response.send_message("Botのメンバー情報を取得できなかったよ。", ephemeral=True)
            return
        panel_perms = panel_channel.permissions_for(bot_member)
        output_perms = output_channel.permissions_for(bot_member)
        if not (panel_perms.view_channel and panel_perms.send_messages and panel_perms.embed_links):
            await interaction.response.send_message("パネル設置先で閲覧・送信・埋め込みリンク権限が必要だよ。", ephemeral=True)
            return
        if not (output_perms.view_channel and output_perms.send_messages and output_perms.embed_links):
            await interaction.response.send_message("実績投稿先で閲覧・送信・埋め込みリンク権限が必要だよ。", ephemeral=True)
            return
    
        guild_key = str(interaction.guild.id)
        previous = achievement_settings.get(guild_key)
        achievement_settings[guild_key] = {"panel_channel_id": panel_channel.id, "output_channel_id": output_channel.id}
        if not save_json("achievement_settings.json", achievement_settings):
            if previous is None:
                achievement_settings.pop(guild_key, None)
            else:
                achievement_settings[guild_key] = previous
            await interaction.response.send_message("Neonへの設定保存に失敗したよ。", ephemeral=True)
            return
    
        embed = discord.Embed(
            title="📝 実績記入",
            description="下のボタンから商品名・個数・評価（1〜5）・感想を入力してください。",
            color=discord.Color.blurple(),
        )
        try:
            await panel_channel.send(embed=embed, view=AchievementPanelView())
        except discord.HTTPException:
            if previous is None:
                achievement_settings.pop(guild_key, None)
            else:
                achievement_settings[guild_key] = previous
            save_json("achievement_settings.json", achievement_settings)
            await interaction.response.send_message("パネルの設置に失敗したよ。チャンネル権限を確認してね。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ パネル：{panel_channel.mention}\n実績投稿先：{output_channel.mention}", ephemeral=True
        )
    
    
    bot.tree.add_command(achievement_group)
    
    
    # ==================================================
    # クイズ認証
    # ==================================================
    verify_settings = {}
    
    
    def normalize_verify_answer(value: str) -> str:
        return re.sub(r"\s+", "", str(value)).casefold()
    
    
    class VerifyAnswerModal(discord.ui.Modal, title="認証クイズ"):
        answer = discord.ui.TextInput(
            label="回答",
            placeholder="答えを入力",
            required=True,
            max_length=200,
        )
    
        def __init__(self, question: str, correct_answer: str, role_id: int):
            # Discordのモーダルタイトルに問題文を表示する（タイトル上限45文字）
            super().__init__(title=str(question)[:45] or "認証クイズ")
            self.question = question
            self.correct_answer = correct_answer
            self.role_id = int(role_id)
    
        async def on_submit(self, interaction: discord.Interaction):
            if interaction.guild is None:
                await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
                return
            if normalize_verify_answer(self.answer.value) != normalize_verify_answer(self.correct_answer):
                await interaction.response.send_message("❌ 不正解。認証ボタンからもう一度挑戦してね。", ephemeral=True)
                return
    
            role = interaction.guild.get_role(self.role_id)
            if role is None:
                await interaction.response.send_message("認証ロールが見つからないよ。管理者に設定を確認してね。", ephemeral=True)
                return
            member = interaction.guild.get_member(interaction.user.id)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(interaction.user.id)
                except discord.HTTPException:
                    await interaction.response.send_message("メンバー情報を取得できなかったよ。", ephemeral=True)
                    return
            if role in member.roles:
                await interaction.response.send_message("すでに認証済みだよ。", ephemeral=True)
                return
            try:
                await member.add_roles(role, reason="クイズ認証に正解")
            except discord.Forbidden:
                await interaction.response.send_message("Botのロール権限とロールの上下関係を確認してね。", ephemeral=True)
                return
            except discord.HTTPException:
                await interaction.response.send_message("ロール付与に失敗したよ。もう一度試してね。", ephemeral=True)
                return
            await interaction.response.send_message(f"✅ 正解！ {role.mention} を付与したよ。", ephemeral=True)
    
    
    class VerifyPanelView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
    
        @discord.ui.button(
            label="認証する",
            style=discord.ButtonStyle.success,
            custom_id="minatann_verify:begin",
            emoji="🔐",
        )
        async def begin_verify(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.guild is None:
                await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
                return
            cfg = verify_settings.get(str(interaction.guild.id), {})
            questions = cfg.get("questions", [])
            if not questions:
                await interaction.response.send_message("認証クイズが設定されていないよ。", ephemeral=True)
                return
            question = random.choice(questions)
            await interaction.response.send_modal(
                VerifyAnswerModal(question["q"], question["a"], cfg["role_id"])
            )
    
    
    verify_group = app_commands.Group(name="verify", description="クイズ認証の設定")
    
    
    @verify_group.command(name="setup", description="認証パネルとクイズを設定")
    @app_commands.describe(
        channel="認証パネルを設置するチャンネル",
        role="正解した人に付与するロール",
        questions="問題を1行ずつ入力（複数可）",
        answers="問題と同じ順番で正解を1行ずつ入力",
    )
    async def verify_setup(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        questions: str,
        answers: str,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        q_list = [x.strip() for x in questions.splitlines() if x.strip()]
        a_list = [x.strip() for x in answers.splitlines() if x.strip()]
        if not q_list or len(q_list) != len(a_list):
            await interaction.response.send_message("問題と答えは同じ行数で入力してね。", ephemeral=True)
            return
        if len(q_list) > 30:
            await interaction.response.send_message("一度に登録できるのは最大30問だよ。", ephemeral=True)
            return
        bot_member = interaction.guild.me
        if role.is_default() or role.managed or bot_member is None or role >= bot_member.top_role:
            await interaction.response.send_message("Botより下にある付与可能なロールを指定してね。", ephemeral=True)
            return
    
        verify_settings[str(interaction.guild.id)] = {
            "channel_id": channel.id,
            "role_id": role.id,
            "questions": [{"q": q, "a": a} for q, a in zip(q_list, a_list)],
        }
        if not save_json("verify_settings.json", verify_settings):
            await interaction.response.send_message("Neonへの設定保存に失敗したよ。", ephemeral=True)
            return
    
        embed = discord.Embed(
            title="🔐 クイズ認証",
            description="「認証する」ボタンを押してクイズに正解すると、認証ロールが付与されます。",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="登録問題数", value=f"{len(q_list)}問")
        try:
            await channel.send(embed=embed, view=VerifyPanelView())
        except discord.Forbidden:
            await interaction.response.send_message("そのチャンネルに送信する権限がないよ。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ {channel.mention} に認証パネルを設置したよ（{len(q_list)}問）。",
            ephemeral=True,
        )
    
    
    bot.tree.add_command(verify_group)
    
    
    # ==================================================
    # TikTok 動画投稿・LIVE通知（サーバー／チャンネル別）
    # ==================================================
    TIKTOK_POLL_SECONDS = 120
    
    # TikTok通知設定の正本はMINATANN専用Neon PostgreSQL
    TIKTOK_DATABASE_URL = os.getenv("DATABASE_URL")
    TIKTOK_DB_KEY = "main"
    _tiktok_db_pool = None
    _tiktok_db_lock = asyncio.Lock()
    tiktok_notify_data = {}
    
    
    
    async def restore_all_json_settings():
        """すべてのアプリ設定をNeonから復元する。"""
        nonlocal config, guess_data, au_settings, au_timeout_records
        nonlocal au_debt_records, au_whitelist, anti_mention_settings
        nonlocal exchange_requests, count_channel_data, antimalware_settings, server_logs_settings, role_panel_settings, ticket_panel_settings, level_settings, level_data, temporary_nicknames, verify_settings, achievement_settings, poll_data, spam_settings, _json_store_ready
    
        if _tiktok_db_pool is None:
            logger.error("各種設定をNeonから復元できない: DB接続プールなし")
            return False
    
        settings = {
            "welcome_config": config,
            "guess_data": guess_data,
            "au_settings": au_settings,
            "au_timeout_records": au_timeout_records,
            "au_debt_records": au_debt_records,
            "au_whitelist": list(au_whitelist),
            "anti_mention_settings": anti_mention_settings,
            "exchange_requests": exchange_requests,
            "count_channels": count_channel_data,
            "antimalware_settings": antimalware_settings,
            "server_logs": server_logs_settings,
            "role_panels": role_panel_settings,
            "ticket_panels": ticket_panel_settings,
            "level_settings": level_settings,
            "level_data": level_data,
            "temporary_nicknames": temporary_nicknames,
            "verify_settings": verify_settings,
            "achievement_settings": achievement_settings,
            "polls": poll_data,
            "spam_settings": spam_settings,
        }
    
        try:
            async with _tiktok_db_pool.acquire() as connection:
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS minatann_json_store (
                        setting_key TEXT PRIMARY KEY,
                        data JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
    
                restored = {}
                migrated = []
                for key, current_value in settings.items():
                    row = await connection.fetchrow(
                        "SELECT data FROM minatann_json_store WHERE setting_key = $1",
                        key,
                    )
                    if row is None:
                        # モジュール起動時に旧JSONから読み込んだ値を初回だけNeonへ移行する
                        legacy_value = current_value
                        if key == "welcome_config" and not isinstance(legacy_value, dict):
                            legacy_value = {}
                        if key in ("guess_data", "au_settings", "au_timeout_records",
                                   "au_debt_records", "anti_mention_settings",
                                   "exchange_requests", "count_channels", "level_settings", "level_data", "temporary_nicknames", "verify_settings", "achievement_settings", "polls", "spam_settings") and not isinstance(legacy_value, dict):
                            legacy_value = {}
                        if key == "au_whitelist" and not isinstance(legacy_value, list):
                            legacy_value = list(current_value)
                        payload = json.dumps(legacy_value, ensure_ascii=False)
                        await connection.execute(
                            """
                            INSERT INTO minatann_json_store (setting_key, data, updated_at)
                            VALUES ($1, $2::jsonb, NOW())
                            ON CONFLICT (setting_key) DO NOTHING
                            """,
                            key,
                            payload,
                        )
                        value = legacy_value
                        migrated.append(key)
                    else:
                        value = row["data"]
                        if isinstance(value, str):
                            value = json.loads(value)
                    restored[key] = value
    
            config = restored["welcome_config"]
            guess_data = restored["guess_data"]
            au_settings = restored["au_settings"]
            au_timeout_records = restored["au_timeout_records"]
            au_debt_records = restored["au_debt_records"]
            au_whitelist = set(str(x) for x in restored["au_whitelist"])
            anti_mention_settings = restored["anti_mention_settings"]
            exchange_requests = restored["exchange_requests"]
            count_channel_data = restored["count_channels"]
            antimalware_settings = restored["antimalware_settings"]
            server_logs_settings = restored["server_logs"]
            role_panel_settings = restored["role_panels"]
            ticket_panel_settings = restored["ticket_panels"]
            level_settings = restored["level_settings"]
            level_data = restored["level_data"]
            temporary_nicknames = restored["temporary_nicknames"]
            verify_settings = restored["verify_settings"]
            achievement_settings = restored["achievement_settings"]
            poll_data = restored["polls"]
            spam_settings = restored["spam_settings"]
    
            _json_store_ready = True
            # Neon復元後に発生していた保存要求があればNeonへ反映
            for pending_key in list(_json_store_pending):
                asyncio.get_running_loop().create_task(_flush_json_store_key(pending_key))
    
            # 全設定の復元が成功した後に限り、旧JSONファイルを削除する
            legacy_files = [
                "welcome_config.json", "guess_data.json", "au_settings.json",
                "au_timeout_records.json", "au_debt_records.json",
                "au_whitelist.json", "anti_mention_settings.json",
                "exchange_requests.json", "count_channels.json",
                "antimalware_settings.json", "server_logs.json", "role_panels.json", "ticket_panels.json",
                "level_settings.json", "level_data.json", "temporary_nicknames.json",
            ]
            for filename in legacy_files:
                try:
                    Path(filename).unlink(missing_ok=True)
                except Exception:
                    logger.exception("旧JSONファイル削除失敗: %s", filename)
    
            logger.info(
                "各種設定をNeonから復元完了: %s種類（初回移行: %s種類）",
                len(restored),
                len(migrated),
            )
            return True
        except Exception:
            _json_store_ready = False
            logger.exception("各種設定のNeon復元に失敗")
            return False
    
    
    async def restore_tiktok_notify_data():
        """NeonからTikTok通知設定を読み込む。初回のみ旧JSONを移行する。"""
        nonlocal tiktok_notify_data, _tiktok_db_pool
    
        if not TIKTOK_DATABASE_URL:
            logger.error("TikTok設定をNeonから読み込めない: DATABASE_URLが未設定")
            return False
    
        try:
            if _tiktok_db_pool is None:
                _tiktok_db_pool = await asyncpg.create_pool(
                    dsn=TIKTOK_DATABASE_URL,
                    min_size=1,
                    max_size=3,
                    command_timeout=30,
                )
    
            async with _tiktok_db_lock:
                async with _tiktok_db_pool.acquire() as connection:
                    await connection.execute("""
                        CREATE TABLE IF NOT EXISTS minatann_tiktok_notify_settings (
                            setting_key TEXT PRIMARY KEY,
                            data JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
    
                    row = await connection.fetchrow(
                        "SELECT data FROM minatann_tiktok_notify_settings WHERE setting_key = $1",
                        TIKTOK_DB_KEY,
                    )
    
                    if row is None:
                        # Neonにまだ設定行がない場合は空で初期化する。
                        tiktok_notify_data = {}
                        await connection.execute(
                            """
                            INSERT INTO minatann_tiktok_notify_settings
                                (setting_key, data, updated_at)
                            VALUES ($1, $2::jsonb, NOW())
                            ON CONFLICT (setting_key) DO NOTHING
                            """,
                            TIKTOK_DB_KEY,
                            json.dumps(tiktok_notify_data, ensure_ascii=False),
                        )
                        logger.info("TikTok通知設定をNeonに新規初期化")
                    else:
                        stored = row["data"]
                        if isinstance(stored, str):
                            stored = json.loads(stored)
                        tiktok_notify_data = stored if isinstance(stored, dict) else {}
    
            logger.info(
                "TikTok通知設定をNeonから復元完了: %sサーバー",
                len(tiktok_notify_data),
            )
            return True
        except Exception:
            logger.exception("TikTok設定のNeon復元に失敗")
            return False
    
    
    async def save_tiktok_notify_data():
        """TikTok通知設定をNeonへ保存する。ローカルJSON/GitHubは使用しない。"""
        if _tiktok_db_pool is None:
            logger.error("TikTok設定をNeonへ保存できない: DB接続が未初期化")
            return False
    
        try:
            payload = json.dumps(tiktok_notify_data, ensure_ascii=False)
            async with _tiktok_db_lock:
                async with _tiktok_db_pool.acquire() as connection:
                    await connection.execute(
                        """
                        INSERT INTO minatann_tiktok_notify_settings
                            (setting_key, data, updated_at)
                        VALUES ($1, $2::jsonb, NOW())
                        ON CONFLICT (setting_key)
                        DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                        """,
                        TIKTOK_DB_KEY,
                        payload,
                    )
            return True
        except Exception:
            logger.exception("TikTok設定のNeon保存に失敗")
            return False
    
    
    def normalize_tiktok_username(value: str):
        value = (value or "").strip()
        value = value.split("?")[0].rstrip("/")
        if "tiktok.com/@" in value:
            value = value.split("tiktok.com/@", 1)[1]
        value = value.lstrip("@").strip()
        if not re.fullmatch(r"[A-Za-z0-9._]{2,24}", value):
            return None
        return value
    
    
    def get_tiktok_subscriptions():
        subscriptions = []
        for guild_id, channels in tiktok_notify_data.items():
            if not isinstance(channels, dict):
                continue
            for channel_id, users in channels.items():
                if not isinstance(users, dict):
                    continue
                for username, settings in users.items():
                    if isinstance(settings, dict):
                        subscriptions.append((str(guild_id), str(channel_id), username, settings))
        return subscriptions
    
    
    async def fetch_tiktok_latest_video(username: str):
        # TikWMが403を返す場合に備え、RSSHubの複数インスタンスを順番に試す
        rss_instances = [
            "https://rsshub.cups.moe",
            "https://rsshub.cmyr.dev",
            "https://rsshub.isrss.com",
            "https://rsshub.ktachibana.party",
            "https://rsshub.joshrandall.net",
        ]
        timeout = aiohttp.ClientTimeout(total=25)
        errors = []
    
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for base_url in rss_instances:
                feed_url = f"{base_url}/tiktok/user/@{username}"
                try:
                    async with session.get(
                        feed_url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (compatible; MINATANN/1.0)",
                            "Accept": "application/rss+xml, application/xml, text/xml",
                        },
                    ) as response:
                        if response.status != 200:
                            raise RuntimeError(f"RSSHub HTTP {response.status}")
                        xml_text = await response.text()
    
                    root = ET.fromstring(xml_text)
                    item = root.find("./channel/item")
                    if item is None:
                        # Atom形式のフィードにも対応
                        ns = {"atom": "http://www.w3.org/2005/Atom"}
                        item = root.find("./atom:entry", ns)
                        if item is None:
                            continue
                        title = item.findtext("atom:title", default="新しい動画", namespaces=ns)
                        link_element = item.find("atom:link", ns)
                        link = link_element.get("href", "") if link_element is not None else ""
                        published = (
                            item.findtext("atom:published", default="", namespaces=ns)
                            or item.findtext("atom:updated", default="", namespaces=ns)
                        )
                    else:
                        title = item.findtext("title", default="新しい動画")
                        link = item.findtext("link", default="") or item.findtext("guid", default="")
                        published = item.findtext("pubDate", default="")
    
                    cover = ""
                    video_media = ""
                    for node in item.iter():
                        tag = str(node.tag).lower()
                        candidate = node.attrib.get("url") or node.attrib.get("href")
                        media_type = str(
                            node.attrib.get("type")
                            or node.attrib.get("medium")
                            or node.attrib.get("medium-type")
                            or ""
                        ).lower()
                        if candidate and candidate.startswith(("http://", "https://")):
                            if "video" in media_type or candidate.lower().split("?")[0].endswith((".mp4", ".webm", ".mov", ".m4v")):
                                video_media = candidate
                            elif not cover and tag.endswith(("thumbnail", "content", "enclosure")):
                                cover = candidate
                    if not cover:
                        description_html = (
                            item.findtext("description", default="")
                            or item.findtext("{http://www.w3.org/2005/Atom}summary", default="")
                        )
                        image_match = re.search(
                            r'<img[^>]+src=["\']([^"\']+)',
                            description_html,
                            re.IGNORECASE,
                        )
                        if image_match:
                            cover = image_match.group(1)
    
                    match = re.search(r"/video/(\d+)", link)
                    if not match:
                        match = re.search(r"(\d{15,})", link)
                    if not match:
                        continue
    
                    video_id = match.group(1)
                    published_ts = None
                    if published:
                        try:
                            published_dt = parsedate_to_datetime(published)
                            if published_dt.tzinfo is None:
                                published_dt = published_dt.replace(tzinfo=timezone.utc)
                            published_ts = published_dt.timestamp()
                        except Exception:
                            try:
                                published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                                published_ts = published_dt.timestamp()
                            except Exception:
                                pass
    
                    logger.info("TikTok投稿取得成功: @%s via %s", username, base_url)
                    return {
                        "id": video_id,
                        "title": str(title or "新しい動画")[:200],
                        "url": f"https://www.tiktok.com/@{username}/video/{video_id}",
                        "cover": cover,
                        "video_media": video_media,
                        "published_at": published_ts,
                    }
                except Exception as error:
                    errors.append(f"{base_url}: {error}")
                    logger.warning("TikTok RSS取得失敗 @%s (%s): %s", username, base_url, error)
    
        raise RuntimeError("全RSS取得先で失敗: " + " | ".join(errors[-5:]))
    
    
    def extract_tiktok_live_cover(data):
        """TikTok LIVEのルーム情報からサムネイルURLを探す。"""
        cover_keys = {
            "cover", "coverurl", "cover_url", "coverimage", "cover_image",
            "roomcover", "room_cover", "coveruri", "cover_uri",
        }
    
        def find_url(value, inside_cover=False):
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = str(key).lower().replace("-", "_")
                    is_cover = inside_cover or normalized in cover_keys
                    if is_cover:
                        found = find_url(child, True)
                        if found:
                            return found
                    elif isinstance(child, (dict, list)):
                        found = find_url(child, False)
                        if found:
                            return found
                    elif inside_cover and isinstance(child, str) and child.startswith(("https://", "http://")):
                        return child
                if inside_cover:
                    for key in ("url_list", "urlList", "url", "uri", "src"):
                        child = data.get(key)
                        if isinstance(child, list):
                            for item in child:
                                if isinstance(item, str) and item.startswith(("https://", "http://")):
                                    return item
                        elif isinstance(child, str) and child.startswith(("https://", "http://")):
                            return child
            elif isinstance(value, list):
                for child in value:
                    found = find_url(child, inside_cover)
                    if found:
                        return found
            elif inside_cover and isinstance(value, str) and value.startswith(("https://", "http://")):
                return value
            return None
    
        return find_url(data)
    
    
    def extract_tiktok_live_avatar(data):
        """LIVEルーム情報から配信者本人のプロフィール画像URLを探す。"""
        avatar_keys = {
            "avatar", "avatarthumb", "avatar_thumb", "avatarmedium", "avatar_medium",
            "avatarlarger", "avatar_larger", "profilepic", "profile_pic",
            "profilepicture", "profile_picture",
        }
    
        def find_avatar(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = str(key).lower().replace("-", "_")
                    if normalized in avatar_keys or normalized.replace("_", "") in avatar_keys:
                        if isinstance(child, str) and child.startswith(("https://", "http://")):
                            return child
                        found = find_avatar(child) if isinstance(child, (dict, list)) else None
                        if found:
                            return found
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        found = find_avatar(child)
                        if found:
                            return found
            elif isinstance(value, list):
                for child in value:
                    found = find_avatar(child)
                    if found:
                        return found
            return None
    
        return find_avatar(data)
    
    
    async def check_tiktok_live(username: str):
        from TikTokLive import TikTokLiveClient
    
        client = TikTokLiveClient(unique_id=username)
        try:
            is_live = await client.is_live()
            avatar = None
            if is_live:
                try:
                    room_info = await client.web.fetch_room_info(unique_id=username)
                    avatar = extract_tiktok_live_avatar(room_info)
                except Exception:
                    logger.exception("TikTok LIVEプロフィール画像取得失敗: @%s", username)
            return bool(is_live), avatar
        finally:
            await client.web.close()
    
    
    async def send_tiktok_post_notice(channel, username: str, video: dict):
        """TikTok新着投稿を通知し、取得可能な場合は動画ファイルも添付する。"""
        embed = discord.Embed(
            title=f"@{discord.utils.escape_markdown(username)} が新しい投稿をしました！",
            color=discord.Color.from_rgb(238, 29, 82),
        )
    
        video_url = video.get("url") or f"https://www.tiktok.com/@{username}"
        video_media = video.get("video_media")
        embed.description = f"[TikTokで開く]({video_url})"
    
        published_at = video.get("published_at")
        if published_at:
            try:
                published_dt = datetime.fromtimestamp(float(published_at), tz=timezone.utc)
                date_text = discord.utils.format_dt(published_dt, style="F")
            except (TypeError, ValueError, OverflowError, OSError):
                date_text = "投稿日を取得できませんでした。"
        else:
            date_text = "投稿日を取得できませんでした。"
    
        embed.add_field(name="投稿日", value=date_text, inline=False)
        embed.set_footer(text="MINATANN TikTok通知")
    
        # RSSから直接動画ファイルを取得できる場合は、URLだけでなく動画自体を添付する。
        # Discordのアップロード上限を超える場合や取得に失敗した場合は、投稿URLを案内する。
        if isinstance(video_media, str) and video_media.startswith(("https://", "http://")):
            try:
                max_bytes = int(getattr(channel.guild, "filesize_limit", 8 * 1024 * 1024))
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        video_media,
                        headers={"User-Agent": "Mozilla/5.0"},
                        allow_redirects=True,
                    ) as response:
                        if response.status != 200:
                            raise RuntimeError(f"動画取得HTTP {response.status}")
                        if response.content_length is not None and response.content_length > max_bytes:
                            raise ValueError("動画がDiscordのアップロード上限を超えています")
                        video_bytes = await response.content.read(max_bytes + 1)
                        if len(video_bytes) > max_bytes:
                            raise ValueError("動画がDiscordのアップロード上限を超えています")
                        if not video_bytes:
                            raise ValueError("動画データが空です")
    
                video_id = str(video.get("id") or "video")
                file = discord.File(io.BytesIO(video_bytes), filename=f"tiktok_{video_id}.mp4")
                await channel.send(embed=embed, file=file)
                return
            except Exception:
                logger.warning("TikTok動画ファイルの添付に失敗。投稿URLで通知します: @%s", username, exc_info=True)
    
        await channel.send(content=video_url, embed=embed)
    
    async def send_tiktok_live_notice(channel, username: str, avatar: str = None):
        embed = discord.Embed(
            title="🔴 TikTok LIVE開始！",
            description=f"**@{discord.utils.escape_markdown(username)}** がLIVEを開始しました！\n\n[LIVEを見る](https://www.tiktok.com/@{username}/live)",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        if avatar and avatar.startswith(("https://", "http://")):
            embed.set_thumbnail(url=avatar)
        embed.set_footer(text="MINATANN TikTok通知")
        await channel.send(embed=embed)
    
    
    @tasks.loop(seconds=TIKTOK_POLL_SECONDS)
    async def tiktok_notification_loop():
        for guild_key, channel_key, username, settings in get_tiktok_subscriptions():
            if not settings.get("enabled", True):
                continue
    
            guild = bot.get_guild(int(guild_key))
            if guild is None:
                continue
            channel = guild.get_channel(int(channel_key))
            if not isinstance(channel, discord.TextChannel):
                continue
    
            # 投稿通知：初回は最新動画IDを記録するだけで、過去動画を通知しない
            if settings.get("post_enabled", True):
                try:
                    latest = await fetch_tiktok_latest_video(username)
                    if latest:
                        previous_id = str(settings.get("latest_video_id") or "")
                        if previous_id and latest["id"] != previous_id:
                            await send_tiktok_post_notice(channel, username, latest)
                        elif not previous_id:
                            # 取得API障害中に登録された新着投稿を拾うため、24時間以内の投稿だけ初回通知
                            published_at = latest.get("published_at")
                            if published_at and (datetime.now(timezone.utc).timestamp() - published_at) <= 86400:
                                await send_tiktok_post_notice(channel, username, latest)
                        settings["latest_video_id"] = latest["id"]
                except Exception:
                    logger.exception("TikTok動画確認失敗: @%s", username)
    
            # LIVE通知：初回確認時は状態を記録し、次回以降のOFF→ONだけ通知
            if settings.get("live_enabled", True):
                try:
                    is_live, live_avatar = await check_tiktok_live(username)
                    previous_live = settings.get("is_live")
                    if previous_live is not None and not previous_live and is_live:
                        await send_tiktok_live_notice(channel, username, live_avatar)
                    settings["is_live"] = bool(is_live)
                except Exception:
                    logger.exception("TikTok LIVE確認失敗: @%s", username)
    
            await save_tiktok_notify_data()
    
    
    @tiktok_notification_loop.before_loop
    async def before_tiktok_notification_loop():
        await bot.wait_until_ready()
    
    
    SEND_TK_CHOICES = [
        app_commands.Choice(name="送信する", value="on"),
        app_commands.Choice(name="送信しない", value="off"),
    ]
    
    tiktok_group = app_commands.Group(name="tk", description="TikTok通知の設定")
    
    
    TK_MEDIA_ACTIONS = [
        app_commands.Choice(name="登録・更新", value="add"),
        app_commands.Choice(name="削除", value="remove"),
    ]
    
    
    @tiktok_group.command(name="media", description="TikTokユーザーの通知を登録・更新・削除")
    @app_commands.describe(
        action="登録するか削除するか",
        username="TikTokのユーザー名、またはプロフィールURL",
        channel="通知設定の対象チャンネル",
        post="動画投稿通知を送信するか（登録時のみ）",
        live="LIVE開始通知を送信するか（登録時のみ）",
    )
    @app_commands.choices(action=TK_MEDIA_ACTIONS, post=SEND_TK_CHOICES, live=SEND_TK_CHOICES)
    async def tiktok_media_command(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        username: str,
        channel: discord.TextChannel,
        post: app_commands.Choice[str] = None,
        live: app_commands.Choice[str] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
    
        normalized = normalize_tiktok_username(username)
        if normalized is None:
            await interaction.response.send_message(
                "TikTokのユーザー名またはプロフィールURLを正しく入力してね。",
                ephemeral=True,
            )
            return
    
        guild_key = str(guild.id)
        channel_key = str(channel.id)
        channels = tiktok_notify_data.get(guild_key, {})
        users = channels.get(channel_key, {})
    
        if action.value == "remove":
            old_settings = users.pop(normalized, None)
            if old_settings is None:
                await interaction.response.send_message(
                    f"このチャンネルには **@{normalized}** は登録されていないよ。",
                    ephemeral=True,
                )
                return
    
            if not await save_tiktok_notify_data():
                users[normalized] = old_settings
                await interaction.response.send_message(
                    "❌ 削除内容をNeonに保存できなかったため、登録を元に戻したよ。",
                    ephemeral=True,
                )
                return
    
            await interaction.response.send_message(
                f"✅ **@{normalized}** を {channel.mention} のTikTok通知設定から削除したよ。",
                ephemeral=True,
            )
            return
    
        if post is None or live is None:
            await interaction.response.send_message(
                "登録・更新するときは動画投稿通知とLIVE開始通知の設定も選んでね。",
                ephemeral=True,
            )
            return
    
        bot_member = guild.me
        if bot_member is None:
            await interaction.response.send_message("Botのメンバー情報を取得できなかったよ。", ephemeral=True)
            return
    
        permissions = channel.permissions_for(bot_member)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            await interaction.response.send_message(
                "Botに「チャンネルを見る」「メッセージを送信」「埋め込みリンク」の権限が必要だよ。",
                ephemeral=True,
            )
            return
    
        channels = tiktok_notify_data.setdefault(guild_key, {})
        users = channels.setdefault(channel_key, {})
        old_settings = users.get(normalized)
        users[normalized] = {
            "post_enabled": post.value == "on",
            "live_enabled": live.value == "on",
            "enabled": True,
            "latest_video_id": (old_settings or {}).get("latest_video_id"),
            "is_live": (old_settings or {}).get("is_live"),
        }
    
        if not await save_tiktok_notify_data():
            if old_settings is None:
                users.pop(normalized, None)
            else:
                users[normalized] = old_settings
            await interaction.response.send_message("❌ TikTok通知設定をNeonに保存できなかったよ。", ephemeral=True)
            return
    
        await interaction.response.send_message(
            f"✅ TikTok通知を設定したよ！\n"
            f"ユーザー：**@{normalized}**\n"
            f"送信先：{channel.mention}\n"
            f"動画投稿：**{'ON' if post.value == 'on' else 'OFF'}**\n"
            f"LIVE開始：**{'ON' if live.value == 'on' else 'OFF'}**\n\n"
            "設定したサーバーの指定チャンネルだけに通知するよ。",
            ephemeral=True,
        )
    
    
    bot.tree.add_command(tiktok_group)
    
    
    @bot.listen("on_ready")
    async def start_tiktok_notification_loop():
        # 全設定をNeonから復元してから各機能を有効化する
        tiktok_restored = await restore_tiktok_notify_data()
        settings_restored = await restore_all_json_settings() if tiktok_restored else False
    
        if tiktok_restored and settings_restored:
            await restore_au_timeout_tasks()
            if not temporary_nickname_expiry_loop.is_running():
                temporary_nickname_expiry_loop.start()
            await exchange_views_ready()
            if not getattr(bot, "_role_panel_views_registered", False):
                await restore_role_panel_views()
                bot._role_panel_views_registered = True
            await restore_active_poll_views()
            # TikTok旧JSONも、Neon復元成功後にだけ削除する
            for legacy_path in ("tiktok_notify.json", "data/tiktok_notify.json"):
                try:
                    Path(legacy_path).unlink(missing_ok=True)
                except Exception:
                    logger.exception("TikTok旧JSONファイル削除失敗: %s", legacy_path)
            if not tiktok_notification_loop.is_running():
                tiktok_notification_loop.start()
        else:
            logger.error("Neonへの全設定移行・復元が完了していないためTikTok通知ループを開始しません")
    
    
    
    # =========================================================
    # Blackjack card emoji registration (54 images / 2 guilds)
    # =========================================================
    BJ_EMOJI_GUILD_A = 1573260159403294793
    BJ_EMOJI_GUILD_B = 1573260415474073660
    BJ_CARD_FIRST_FILE = 625
    BJ_CARD_LAST_FILE = 678
    
    def make_bj_emoji_name(file_number: int) -> str:
        # s=spade, c=club, d=diamond, h=heart; ranks 1-13 (A-K).
        suit_data = [
            (625, "s"),
            (638, "c"),
            (651, "d"),
            (664, "h"),
        ]
        for start, suit in suit_data:
            if start <= file_number <= start + 12:
                return f"{suit}{file_number - start + 1}"
        if file_number == 677:
            return "joker"
        if file_number == 678:
            return "back"
        raise ValueError(f"Unknown card image number: {file_number}")
    
    
    BJ_EMOJI_REGISTER_LOCK = asyncio.Lock()
    
    @bot.tree.command(name="bjemoji-register", description="トランプ絵文字54枚を指定の2サーバーに登録")
    async def bjemoji_register(interaction: discord.Interaction):
        if interaction.guild_id not in (BJ_EMOJI_GUILD_A, BJ_EMOJI_GUILD_B):
            await interaction.response.send_message(
                "このコマンドは指定された2つのサーバー内で実行してね。",
                ephemeral=True,
            )
            return
    
        user_permissions = getattr(interaction.user, "guild_permissions", None)
        if not (getattr(user_permissions, "administrator", False)
                or getattr(user_permissions, "manage_guild", False)):
            await interaction.response.send_message(
                "この操作はサーバー管理者だけが実行できるよ。",
                ephemeral=True,
            )
            return
    
        if BJ_EMOJI_REGISTER_LOCK.locked():
            await interaction.response.send_message(
                "別の登録処理が進行中だよ。完了してからもう一度実行してね。",
                ephemeral=True,
            )
            return
    
        await interaction.response.defer(ephemeral=True, thinking=True)
    
        async with BJ_EMOJI_REGISTER_LOCK:
            targets = [
                (BJ_EMOJI_GUILD_A, range(625, 652)),
                (BJ_EMOJI_GUILD_B, range(652, 679)),
            ]
            total_added = 0
            total_skipped = 0
            total_failed = 0
            failures = []
            total_processed = 0
            total_count = 54
    
            try:
                await interaction.edit_original_response(
                    content="🃏 **カード絵文字の登録を開始したよ！**\n"
                            "サーバーごとに27枚ずつ処理するね。\n"
                            "進捗：0 / 54枚"
                )
    
                for guild_index, (guild_id, file_numbers) in enumerate(targets, start=1):
                    guild_label = f"サーバー{guild_index}"
                    guild = bot.get_guild(guild_id)
                    if guild is None:
                        try:
                            guild = await bot.fetch_guild(guild_id)
                        except discord.HTTPException as error:
                            failures.append(f"{guild_label}の取得失敗: {error}")
                            total_failed += len(file_numbers)
                            total_processed += len(file_numbers)
                            continue
    
                    try:
                        existing_emojis = await guild.fetch_emojis()
                    except discord.HTTPException as error:
                        failures.append(f"{guild.name}の絵文字一覧取得失敗: {error}")
                        total_failed += len(file_numbers)
                        total_processed += len(file_numbers)
                        continue
    
                    existing_names = {emoji.name for emoji in existing_emojis}
                    guild_added = 0
                    guild_skipped = 0
    
                    for file_number in file_numbers:
                        emoji_name = make_bj_emoji_name(file_number)
                        image_path = Path("cards") / f"IMG_{file_number:04d}.png"
    
                        if emoji_name in existing_names:
                            total_skipped += 1
                            guild_skipped += 1
                            total_processed += 1
                            continue
    
                        try:
                            image_bytes = image_path.read_bytes()
                        except OSError as error:
                            failures.append(f"{image_path}: 読み込み失敗 ({error})")
                            total_failed += 1
                            total_processed += 1
                            continue
    
                        # PNG signature + IHDR color type (4=gray+alpha, 6=RGBA).
                        # Use hex bytes to avoid escaping mistakes in generated source.
                        png_signature = bytes.fromhex("89504e470d0a1a0a")
                        has_alpha_channel = (
                            len(image_bytes) >= 26
                            and image_bytes[:8] == png_signature
                            and image_bytes[25] in (4, 6)
                        )
                        if not has_alpha_channel:
                            failures.append(
                                f"{image_path}: PNG形式または透明度情報を確認できないため登録を中止"
                            )
                            total_failed += 1
                            total_processed += 1
                            continue
    
                        try:
                            await guild.create_custom_emoji(
                                name=emoji_name,
                                image=image_bytes,
                                reason="MINATANN playing card emoji setup",
                            )
                            existing_names.add(emoji_name)
                            total_added += 1
                            guild_added += 1
                        except discord.HTTPException as error:
                            if error.status == 429:
                                retry_after = getattr(error, "retry_after", None)
                                wait_text = (
                                    f"。再試行まで約{retry_after:.0f}秒"
                                    if retry_after is not None else ""
                                )
                                failures.append(
                                    f"{guild.name}: Discordの429制限で停止{wait_text}"
                                )
                                total_failed += len(file_numbers) - (
                                    total_processed - (27 * (guild_index - 1))
                                )
                                total_processed = 27 * guild_index
                                break
                            failures.append(f"{guild.name}/{emoji_name}: {error}")
                            total_failed += 1
                        total_processed += 1
    
                        if total_processed % 3 == 0 or total_processed == total_count:
                            await interaction.edit_original_response(
                                content=(
                                    "🃏 **カード絵文字を登録中！**\n"
                                    f"現在：{guild.name}\n"
                                    f"進捗：**{total_processed} / 54枚**\n"
                                    f"登録：{total_added}枚 / 既存：{total_skipped}枚"
                                    f" / 失敗：{total_failed}枚"
                                )
                            )
                        await asyncio.sleep(1.5)
    
                    logger.info(
                        "[BJ EMOJI] %s: added=%s skipped=%s processed=%s",
                        guild.name, guild_added, guild_skipped, total_processed
                    )
    
                result = (
                    "🃏 **カード絵文字の処理が終了したよ！**\n"
                    f"登録成功：**{total_added}枚**\n"
                    f"登録済み：**{total_skipped}枚**\n"
                    f"失敗・未処理：**{total_failed}枚**"
                )
                if failures:
                    result += "\n\n**エラー内容**\n" + "\n".join(
                        f"・{item}" for item in failures[:8]
                    )
                else:
                    result += "\n\n2つのサーバーの処理が完了したよ！"
                await interaction.edit_original_response(content=result)
            except Exception:
                logger.exception("[BJ EMOJI] registration command failed")
                try:
                    await interaction.edit_original_response(
                        content=(
                            "登録処理中に予期しないエラーが発生したよ。\n"
                            f"ここまでの登録成功：{total_added}枚。"
                            "もう一度実行すれば登録済みのカードは自動でスキップするよ。"
                        )
                    )
                except Exception:
                    logger.exception("[BJ EMOJI] failed to update interaction response")
    
    
    # ==================================================
    # 投票（最大15項目・Neon保存・永続ボタン）
    # ==================================================
    POLL_FILE = Path("polls.json")
    _poll_locks = {}
    
    
    def parse_poll_duration(value: str):
        match = re.fullmatch(r"\s*([1-9]\d*)([smhd])\s*", str(value).lower())
        if not match:
            return None
        amount = int(match.group(1))
        unit = match.group(2)
        seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        if seconds < 1 or seconds > 30 * 86400:
            return None
        return seconds
    
    
    def poll_counts(poll: dict):
        counts = [0] * len(poll.get("options", []))
        for selected in poll.get("votes", {}).values():
            for index in selected:
                if 0 <= int(index) < len(counts):
                    counts[int(index)] += 1
        return counts
    
    
    def poll_is_expired(poll: dict):
        try:
            expires = datetime.fromisoformat(poll["expires_at"])
            return datetime.now(timezone.utc) >= expires
        except Exception:
            return True
    
    
    def get_poll_lock(poll_id: str):
        if poll_id not in _poll_locks:
            _poll_locks[poll_id] = asyncio.Lock()
        return _poll_locks[poll_id]
    
    
    class PollOptionButton(discord.ui.Button):
        def __init__(self, poll_id: str, option_index: int, disabled=False):
            super().__init__(
                label="選択",
                style=discord.ButtonStyle.primary,
                emoji="☑️",
                custom_id=f"minatann_poll:{poll_id}:{option_index}",
                disabled=disabled,
            )
            self.poll_id = poll_id
            self.option_index = option_index
    
        async def callback(self, interaction: discord.Interaction):
            poll = poll_data.get(self.poll_id)
            if not poll:
                await interaction.response.send_message("この投票は見つからないよ。", ephemeral=True)
                return
            async with get_poll_lock(self.poll_id):
                if poll.get("ended") or poll_is_expired(poll):
                    poll["ended"] = True
                    save_json(POLL_FILE, poll_data)
                    await interaction.response.send_message("この投票は終了しているよ。", ephemeral=True)
                    try:
                        await interaction.message.edit(view=build_poll_view(self.poll_id, disabled=True))
                    except discord.HTTPException:
                        pass
                    return
    
                votes = poll.setdefault("votes", {})
                user_key = str(interaction.user.id)
                selected = list(votes.get(user_key, []))
                index = self.option_index
    
                if poll.get("mode") == "single":
                    selected = [] if selected == [index] else [index]
                else:
                    if index in selected:
                        selected.remove(index)
                    else:
                        selected.append(index)
                    selected.sort()
    
                if selected:
                    votes[user_key] = selected
                else:
                    votes.pop(user_key, None)
    
                save_json(POLL_FILE, poll_data)
                await interaction.response.edit_message(view=build_poll_view(self.poll_id))
                selected_label = "投票を登録したよ！" if selected else "投票を取り消したよ！"
                await interaction.followup.send(selected_label, ephemeral=True)
    
    
    class PollPanelView(discord.ui.LayoutView):
        def __init__(self, poll_id: str, disabled=False):
            super().__init__(timeout=None)
            poll = poll_data.get(poll_id)
            if not poll:
                return
    
            counts = poll_counts(poll)
            total_votes = sum(counts)
    
            mode_label = "1人1票" if poll.get("mode") == "single" else "複数選択"
            if poll.get("ended"):
                footer = "投票は終了しました。"
            else:
                expires = datetime.fromisoformat(poll["expires_at"])
                footer = f"方式：{mode_label}　/　終了：{discord.utils.format_dt(expires, style='R')}"
    
            # 題名を独立させ、各選択肢を個別の枠で表示する。
            self.add_item(
                discord.ui.Container(
                    discord.ui.TextDisplay(f"# {poll.get('title', '投票')}"),
                    discord.ui.TextDisplay("回答を選択"),
                )
            )
    
            for index, option in enumerate(poll.get("options", [])[:15]):
                count = counts[index]
                percent = round(count / total_votes * 100) if total_votes else 0
                # 割合を10段階のバーで左から表示する。
                filled_blocks = min(10, max(0, round(percent / 10)))
                progress_bar = "🟩" * filled_blocks + "⬜" * (10 - filled_blocks)
                line = (
                    f"**{index + 1}. {discord.utils.escape_markdown(option)}**\n"
                    f"**{percent}%**　・　**{count}票**\n"
                    f"{progress_bar}"
                )
                # 100%の項目は枠のアクセントも緑色にする。
                row_color = discord.Color.green() if total_votes > 0 and count == total_votes else None
                self.add_item(
                    discord.ui.Container(
                        discord.ui.Section(
                            discord.ui.TextDisplay(line),
                            accessory=PollOptionButton(
                                poll_id,
                                index,
                                disabled=disabled or poll.get("ended", False),
                            ),
                        ),
                        accent_color=row_color,
                    )
                )
    
            self.add_item(
                discord.ui.Container(
                    discord.ui.TextDisplay(f"-# {footer}")
                )
            )
    
    
    def build_poll_view(poll_id: str, disabled=False):
        return PollPanelView(poll_id, disabled=disabled)
    
    
    async def restore_active_poll_views():
        now = datetime.now(timezone.utc)
        for poll_id, poll in list(poll_data.items()):
            if not isinstance(poll, dict):
                continue
            if poll.get("ended"):
                continue
            try:
                if poll_is_expired(poll):
                    asyncio.create_task(expire_poll_after(poll_id, 0))
                    continue
                bot.add_view(build_poll_view(poll_id))
                remaining = max(1, int((datetime.fromisoformat(poll["expires_at"]) - now).total_seconds()))
                asyncio.create_task(expire_poll_after(poll_id, remaining))
            except Exception:
                logger.exception("投票ビュー復元失敗: %s", poll_id)
        save_json(POLL_FILE, poll_data)
    
    
    async def expire_poll_after(poll_id: str, seconds: int):
        await asyncio.sleep(max(0, seconds))
        poll = poll_data.get(poll_id)
        if not poll or poll.get("ended"):
            return
    
        async with get_poll_lock(poll_id):
            poll = poll_data.get(poll_id)
            if not poll or poll.get("ended"):
                return
    
            poll["ended"] = True
            save_json(POLL_FILE, poll_data)
    
            try:
                channel = bot.get_channel(int(poll.get("channel_id", 0)))
                if channel is None:
                    channel = await bot.fetch_channel(int(poll.get("channel_id", 0)))
    
                # 元の投票パネルを締め切る
                try:
                    message = await channel.fetch_message(int(poll.get("message_id", 0)))
                    await message.edit(view=build_poll_view(poll_id, disabled=True))
                except Exception:
                    logger.exception("投票終了時のパネル更新失敗: %s", poll_id)
    
                # 最多得票の項目を別メッセージで発表（同率1位はすべて掲載）
                if not poll.get("announced"):
                    counts = poll_counts(poll)
                    total_votes = sum(counts)
                    if total_votes:
                        highest = max(counts)
                        winners = [
                            (index, option, counts[index])
                            for index, option in enumerate(poll.get("options", []))
                            if counts[index] == highest
                        ]
                        winner_lines = []
                        for index, option, count in winners:
                            percent = round(count / total_votes * 100)
                            winner_lines.append(
                                f"🏆 **{index + 1}. {discord.utils.escape_markdown(option)}**"
                                f" — **{count}票（{percent}%）**"
                            )
                        result_text = (
                            f"# 🗳️ 投票結果発表\n"
                            f"**{discord.utils.escape_markdown(poll.get('title', '投票'))}**\n\n"
                            + "\n".join(winner_lines)
                            + f"\n\n総投票数：**{total_votes}票**"
                        )
                        if len(winners) > 1:
                            result_text = result_text.replace("投票結果発表", "投票結果発表（同率1位）", 1)
                    else:
                        result_text = (
                            f"# 🗳️ 投票終了\n"
                            f"**{discord.utils.escape_markdown(poll.get('title', '投票'))}**\n"
                            "投票はありませんでした。"
                        )
    
                    await channel.send(result_text)
                    poll["announced"] = True
                    save_json(POLL_FILE, poll_data)
            except Exception:
                logger.exception("投票終了処理に失敗: %s", poll_id)
    
    
    async def publish_poll(interaction: discord.Interaction, title: str, options: list[str], mode: str, duration_seconds: int):
        poll_id = format(interaction.id, "x")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        poll_data[poll_id] = {
            "guild_id": interaction.guild_id,
            "channel_id": interaction.channel_id,
            "message_id": None,
            "title": title,
            "options": options,
            "mode": mode,
            "expires_at": expires_at.isoformat(),
            "votes": {},
            "ended": False,
            "created_by": interaction.user.id,
        }
        try:
            message = await interaction.channel.send(view=build_poll_view(poll_id))
        except Exception:
            poll_data.pop(poll_id, None)
            raise
        poll_data[poll_id]["message_id"] = message.id
        save_json(POLL_FILE, poll_data)
        bot.add_view(build_poll_view(poll_id))
        asyncio.create_task(expire_poll_after(poll_id, duration_seconds))
    
    
    class VoteOptionsModal(discord.ui.Modal):
        def __init__(self, title: str, item_count: int, mode: str, duration_seconds: int, options=None, start_index=0):
            super().__init__(title=f"投票項目入力 {start_index + 1}〜{min(start_index + 5, item_count)}")
            self.poll_title = title
            self.item_count = item_count
            self.mode = mode
            self.duration_seconds = duration_seconds
            self.options = list(options or [])
            self.start_index = start_index
    
            page_count = min(5, item_count - start_index)
            self.inputs = []
            for offset in range(page_count):
                index = start_index + offset
                field = discord.ui.TextInput(
                    label=f"項目{index + 1}",
                    placeholder=f"投票項目{index + 1}を入力",
                    required=True,
                    max_length=80,
                )
                self.inputs.append(field)
                self.add_item(field)
    
        async def on_submit(self, interaction: discord.Interaction):
            values = [field.value.strip() for field in self.inputs]
            if any(not value for value in values):
                await interaction.response.send_message("項目はすべて入力してね。", ephemeral=True)
                return
            self.options.extend(values)
            next_index = self.start_index + len(values)
            if next_index < self.item_count:
                await interaction.response.send_modal(
                    VoteOptionsModal(
                        self.poll_title,
                        self.item_count,
                        self.mode,
                        self.duration_seconds,
                        options=self.options,
                        start_index=next_index,
                    )
                )
                return
    
            try:
                await publish_poll(interaction, self.poll_title, self.options, self.mode, self.duration_seconds)
            except Exception:
                logger.exception("投票パネルの作成に失敗")
                await interaction.response.send_message(
                    "投票パネルを作成できなかったよ。Botの送信権限と設定を確認してね。",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                f"投票を作成したよ！項目数：{len(self.options)} / 方式：{'1人1票' if self.mode == 'single' else '複数選択'}",
                ephemeral=True,
            )
    
    
    @bot.tree.command(name="vote", description="投票パネルを作成する")
    @app_commands.describe(
        title="投票の題名",
        item_count="投票項目数（1〜15）",
        mode="投票方式",
        duration="投票時間（例：30s、10m、2h、1d）",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="1人1票", value="single"),
        app_commands.Choice(name="複数選択", value="multiple"),
    ])
    async def vote_command(
        interaction: discord.Interaction,
        title: app_commands.Range[str, 1, 100],
        item_count: app_commands.Range[int, 1, 15],
        mode: app_commands.Choice[str],
        duration: str,
    ):
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        seconds = parse_poll_duration(duration)
        if seconds is None:
            await interaction.response.send_message(
                "時間は 30s・10m・2h・1d の形式で入力してね。1秒〜30日まで設定できるよ。",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(VoteOptionsModal(title, item_count, mode.value, seconds))
    
    
    
    
    # ==================================================
    # Give Role（!giverole @メンション ロール名）
    # ==================================================
    @bot.command(name="giverole")
    @commands.has_permissions(administrator=True)
    async def giverole_command(
        ctx: commands.Context,
        member: discord.Member,
        *,
        role_name: str,
    ):
        guild = ctx.guild
        if guild is None or member.guild.id != guild.id:
            await ctx.send("サーバー内のメンバーを指定してね。")
            return
    
        matches = [
            role for role in guild.roles
            if role.name.casefold() == role_name.strip().casefold()
        ]
        if not matches:
            await ctx.send(f"「{discord.utils.escape_markdown(role_name)}」というロールが見つからないよ。")
            return
        if len(matches) > 1:
            await ctx.send("同じ名前のロールが複数あるよ。ロール名を一意にしてね。")
            return
    
        role = matches[0]
        if role.is_default():
            await ctx.send("@everyone ロールは付与できないよ。")
            return
        if role.managed:
            await ctx.send("Botなどが管理しているロールは付与できないよ。")
            return
        if role.permissions.administrator:
            await ctx.send("管理者権限を持つロールは安全のため付与できないよ。")
            return
    
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            await ctx.send("Botに「ロールの管理」権限を付けてね。")
            return
        if role >= bot_member.top_role:
            await ctx.send("そのロールよりBotの最高ロールを上にしてね。")
            return
        if role in member.roles:
            await ctx.send(f"{member.mention} はすでに {role.mention} を持っているよ。")
            return
    
        try:
            await member.add_roles(
                role,
                reason=f"!giverole by {ctx.author} ({ctx.author.id})",
            )
        except discord.Forbidden:
            await ctx.send("付与できなかったよ。Botの権限とロールの位置を確認してね。")
            return
        except discord.HTTPException:
            logger.exception(
                "!giverole failed: guild=%s member=%s role=%s",
                guild.id, member.id, role.id,
            )
            await ctx.send("Discord側のエラーでロールを付与できなかったよ。")
            return
    
        await ctx.send(
            f"✅ **ロール付与完了！**\n"
            f"対象：{member.mention}\n"
            f"ロール：**{discord.utils.escape_markdown(role.name)}**\n"
            f"実行者：{ctx.author.mention}",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    
    
    # ==================================================
    # Prefix Role Give（!role give ロール名）
    # ==================================================
    @bot.group(name="role", invoke_without_command=True)
    async def prefix_role_group(ctx: commands.Context):
        await ctx.send("使い方：`!role give ロール名`")
    
    
    @prefix_role_group.command(name="give")
    async def prefix_role_give_command(ctx: commands.Context, *, role_name: str):
        """管理者が自分自身に指定ロールを付与する。"""
        guild = ctx.guild
        if guild is None:
            await ctx.send("サーバー内で使ってね。")
            return
    
        matches = [
            role for role in guild.roles
            if role.name.casefold() == role_name.strip().casefold()
        ]
        if not matches:
            await ctx.send(f"「{discord.utils.escape_markdown(role_name)}」というロールが見つからないよ。")
            return
        if len(matches) > 1:
            await ctx.send("同じ名前のロールが複数あるよ。ロール名を一意にしてね。")
            return
    
        role = matches[0]
        if role.is_default():
            await ctx.send("@everyone ロールは付与できないよ。")
            return
        if role.managed:
            await ctx.send("Botなどが管理しているロールは付与できないよ。")
            return
        if role.permissions.administrator:
            await ctx.send("管理者権限を持つロールは安全のため付与できないよ。")
            return
    
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            await ctx.send("Botに「ロールの管理」権限を付けてね。")
            return
        if role >= bot_member.top_role:
            await ctx.send("そのロールよりBotの最高ロールを上にしてね。")
            return
    
        member = ctx.author
        if member.id != guild.owner_id and role >= member.top_role:
            await ctx.send("自分の最高ロール以上のロールは付与できないよ。")
            return
        if role in member.roles:
            await ctx.send(f"{member.mention} はすでに {role.mention} を持っているよ。")
            return
    
        try:
            await member.add_roles(role, reason=f"!role give by {member} ({member.id})")
        except discord.Forbidden:
            await ctx.send("付与できなかったよ。Botの権限とロールの位置を確認してね。")
            return
        except discord.HTTPException:
            logger.exception("!role give failed: guild=%s member=%s role=%s", guild.id, member.id, role.id)
            await ctx.send("Discord側のエラーでロールを付与できなかったよ。")
            return
    
        await ctx.send(f"✅ {member.mention} に {role.mention} を付与したよ！")
    
    
    # ==================================================
    # Fake Kick Log（実際のキックを行わないテストログ）
    # ==================================================
    @bot.tree.command(name="fakekick", description="キックログを作成する")
    @app_commands.describe(
        member="ログに表示するメンバー",
        reason="ログに表示する理由",
    )
    async def fakekick_command(
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "なし",
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
    
        log_channel = get_log_channel(guild.id)
        if log_channel is None:
            await interaction.response.send_message(
                "入退出ログの送信先が設定されていないよ。先にログチャンネルを設定してね。",
                ephemeral=True,
            )
            return
    
        safe_reason = discord.utils.escape_mentions(reason.strip() or "なし")
        embed = discord.Embed(
            title="メンバーがキックされました",
            description=f"**{discord.utils.escape_markdown(member.display_name)}** がサーバーからキックされました。",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="対象メンバー", value=f"{discord.utils.escape_markdown(str(member))}\nID：\`{member.id}\`", inline=False)
        embed.add_field(name="実行者", value=discord.utils.escape_markdown(str(interaction.user)), inline=True)
        embed.add_field(name="理由", value=safe_reason[:1024], inline=False)
        embed.set_footer(text=f"{guild.name} • Minatann便利bot")
    
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                "ログを送れなかったよ。Botにログチャンネルの閲覧・埋め込みリンク送信権限を付けてね。",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception("Fake kick logの送信に失敗: guild=%s", guild.id)
            await interaction.response.send_message("キックログの送信に失敗したよ。", ephemeral=True)
            return
    
        await interaction.response.send_message(
            f"✅ {log_channel.mention} にキックログを送信したよ。",
            ephemeral=True,
        )
    
    
    # ==================================================
    # Clear Logs（指定チャンネルのBotログを削除）
    # ==================================================
    class ClearLogsConfirmView(discord.ui.View):
        def __init__(self, channel: discord.TextChannel, requester_id: int, amount: int):
            super().__init__(timeout=120)
            self.channel = channel
            self.requester_id = requester_id
            self.amount = amount
            self.finished = False
    
        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.requester_id:
                await interaction.response.send_message(
                    "この確認ボタンを操作できるのは実行者だけだよ。",
                    ephemeral=True,
                )
                return False
            if not (
                interaction.user.id == interaction.guild.owner_id
                or interaction.user.guild_permissions.administrator
            ):
                await interaction.response.send_message("管理者のみ操作できるよ。", ephemeral=True)
                return False
            return True
    
        @discord.ui.button(label="ログを削除する", style=discord.ButtonStyle.danger, emoji="🗑️")
        async def confirm_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.finished:
                await interaction.response.send_message("この操作は既に終了しているよ。", ephemeral=True)
                return
            self.finished = True
            self.stop()
            await interaction.response.defer(ephemeral=True, thinking=True)
    
            try:
                deleted = await self.channel.purge(
                    limit=self.amount,
                    check=lambda message: True,
                    bulk=True,
                    reason=f"Clear logs requested by {interaction.user} ({interaction.user.id})",
                )
            except discord.Forbidden:
                await interaction.edit_original_response(
                    content="削除できなかったよ。Botに「メッセージの管理」と「メッセージ履歴を読む」権限を付けてね。",
                    view=None,
                )
                return
            except discord.HTTPException:
                logger.exception("Clear logs failed: guild=%s channel=%s", self.channel.guild.id, self.channel.id)
                await interaction.edit_original_response(
                    content="ログの削除中にDiscord側のエラーが発生したよ。",
                    view=None,
                )
                return
    
            await interaction.edit_original_response(
                content=f"✅ {self.channel.mention} のメッセージを **{len(deleted):,}件** 削除したよ。",
                view=None,
            )
    
        @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
        async def cancel_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.finished = True
            self.stop()
            await interaction.response.edit_message(
                content="ログの削除をキャンセルしたよ。",
                view=None,
            )
    
    
    @bot.tree.command(name="clearlogs", description="指定したチャンネルの最新メッセージを指定件数削除")
    @app_commands.describe(
        channel="ログを削除するチャンネル",
        amount="削除するメッセージ数（最新のものから）",
    )
    @app_commands.rename(amount="件数")
    async def clearlogs_command(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        amount: app_commands.Range[int, 1, 100000],
    ):
        if interaction.guild is None or channel.guild.id != interaction.guild.id:
            await interaction.response.send_message("同じサーバー内のチャンネルを選んでね。", ephemeral=True)
            return
        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message("サーバーオーナーまたは管理者のみ使えるよ。", ephemeral=True)
            return
    
        await interaction.response.send_message(
            f"🗑️ {channel.mention} の最新 **{amount:,}件** のメッセージを、人・Botを問わず削除するよ。\n"
            "ピン留めも対象で、削除したメッセージは元に戻せないよ。実行していい？",
            view=ClearLogsConfirmView(channel, interaction.user.id, amount),
            ephemeral=True,
        )
    
    
    # ==================================================
    # SPAM / Opt-in Announcement System（Neon保存）
    # ==================================================
    SPAM_FILE = "spam_settings.json"
    spam_settings = load_json(SPAM_FILE, {})
    spam_send_cooldowns = {}
    
    
    def get_spam_settings(guild_id: int):
        return spam_settings.setdefault(str(guild_id), {
            "enabled": False, "channel_id": None, "role_ids": [],
            "role_logic": "or", "message": "お知らせがあります！", "subscribers": [],
            "interval_seconds": 3600, "next_send_at": 0,
        })
    
    
    def save_spam_settings():
        return save_json(SPAM_FILE, spam_settings)
    
    
    def spam_embed(guild: discord.Guild):
        data = get_spam_settings(guild.id)
        channel = guild.get_channel(int(data["channel_id"])) if data.get("channel_id") else None
        roles = [guild.get_role(int(x)) for x in data.get("role_ids", [])]
        roles = [r for r in roles if r is not None]
        count = len(set(int(x) for x in data.get("subscribers", [])))
        logic = "OR（どれか1つ）" if data.get("role_logic") == "or" else "AND（すべて）"
        embed = discord.Embed(
            title="📢 SPAM・通知設定",
            description=(
                "通知対象と送信内容を管理します。\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🔔 **通知機能**\n"
                f"状態：**{'ON' if data.get('enabled') else 'OFF'}**\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📍 **対象チャンネル**\n"
                f"設定：{channel.mention if isinstance(channel, discord.TextChannel) else '未設定'}\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🎭 **対象ロール**\n"
                f"ロール：{', '.join(r.mention for r in roles) if roles else '未設定'}\n"
                f"判定：**{logic}**\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "👥 **通知登録者**\n"
                f"登録数：**{count}人**（本人が /spam join で登録）\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "💬 **通知メッセージ**\n"
                f"{discord.utils.escape_mentions(data.get('message', ''))[:500] or '未設定'}\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🛡️ **送信制限**\n"
                "1回最大100人・送信後10分間は再送信不可"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Minatann • SPAM SYSTEM")
        return embed
    
    
    class SpamMessageModal(discord.ui.Modal, title="通知メッセージ設定"):
        message = discord.ui.TextInput(
            label="通知メッセージ", placeholder="最大1,000文字",
            style=discord.TextStyle.paragraph, max_length=1000, required=True,
        )
    
        def __init__(self, guild_id: int, requester_id: int):
            super().__init__()
            self.guild_id = guild_id
            self.requester_id = requester_id
            self.message.default = get_spam_settings(guild_id).get("message", "")
    
        async def on_submit(self, interaction: discord.Interaction):
            if interaction.user.id != self.requester_id:
                await interaction.response.send_message("この設定画面を開いた人だけ操作できるよ。", ephemeral=True)
                return
            get_spam_settings(self.guild_id)["message"] = self.message.value.strip()
            if not save_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await interaction.response.send_message("通知メッセージを保存したよ。", ephemeral=True)
    
    
    class SpamIntervalModal(discord.ui.Modal, title="自動送信間隔の設定"):
        seconds = discord.ui.TextInput(
            label="送信間隔（秒）",
            placeholder="60〜86400（例：300）",
            min_length=2, max_length=5, required=True,
        )
    
        def __init__(self, guild_id: int, requester_id: int):
            super().__init__()
            self.guild_id = guild_id
            self.requester_id = requester_id
            self.seconds.default = str(get_spam_settings(guild_id).get("interval_seconds", 3600))
    
        async def on_submit(self, interaction: discord.Interaction):
            if interaction.user.id != self.requester_id:
                await interaction.response.send_message("この設定画面を開いた人だけ操作できるよ。", ephemeral=True)
                return
            if interaction.guild is None or not (
                interaction.user.id == interaction.guild.owner_id
                or interaction.user.guild_permissions.administrator
            ):
                await interaction.response.send_message("サーバー管理者のみ設定できるよ。", ephemeral=True)
                return
            try:
                seconds = int(str(self.seconds.value).strip())
            except ValueError:
                await interaction.response.send_message("秒数は数字で入力してね。", ephemeral=True)
                return
            if not 60 <= seconds <= 86400:
                await interaction.response.send_message("60〜86400秒の範囲で設定してね。", ephemeral=True)
                return
            data = get_spam_settings(self.guild_id)
            data["interval_seconds"] = seconds
            data["next_send_at"] = datetime.now(timezone.utc).timestamp() + seconds
            if not save_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await interaction.response.send_message(
                f"自動送信間隔を **{seconds}秒** に設定したよ。",
                ephemeral=True,
            )
    
    
    class SpamSetupView(discord.ui.View):
        def __init__(self, guild: discord.Guild, requester_id: int):
            super().__init__(timeout=600)
            self.guild = guild
            self.requester_id = requester_id
            self.channel_select = discord.ui.ChannelSelect(
                channel_types=[discord.ChannelType.text], placeholder="通知先チャンネルを選択",
                min_values=1, max_values=1, row=0,
            )
            self.channel_select.callback = self.select_channel
            self.add_item(self.channel_select)
            self.role_select = discord.ui.RoleSelect(
                placeholder="対象ロールを複数選択（最大25個）",
                min_values=0, max_values=25, row=1,
            )
            self.role_select.callback = self.select_roles
            self.add_item(self.role_select)
    
        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.requester_id:
                await interaction.response.send_message("この設定画面を開いた人だけ操作できるよ。", ephemeral=True)
                return False
            if interaction.guild is None or not (
                interaction.user.id == interaction.guild.owner_id
                or interaction.user.guild_permissions.administrator
            ):
                await interaction.response.send_message("サーバー管理者のみ操作できるよ。", ephemeral=True)
                return False
            return True
    
        async def refresh(self, interaction: discord.Interaction):
            await interaction.response.edit_message(embed=spam_embed(self.guild), view=self)
    
        async def select_channel(self, interaction: discord.Interaction):
            channel = self.channel_select.values[0]
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild.id:
                await interaction.response.send_message("同じサーバーのテキストチャンネルを選んでね。", ephemeral=True)
                return
            get_spam_settings(self.guild.id)["channel_id"] = channel.id
            if not save_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await self.refresh(interaction)
    
        async def select_roles(self, interaction: discord.Interaction):
            get_spam_settings(self.guild.id)["role_ids"] = [
                role.id for role in self.role_select.values if not role.is_default()
            ]
            if not save_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await self.refresh(interaction)
    
        @discord.ui.button(label="通知 ON / OFF", style=discord.ButtonStyle.primary, emoji="🔔", row=2)
        async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
            data = get_spam_settings(self.guild.id)
            data["enabled"] = not data.get("enabled", False)
            if not save_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await self.refresh(interaction)
    
        @discord.ui.button(label="OR / AND 切替", style=discord.ButtonStyle.secondary, emoji="🎭", row=2)
        async def toggle_logic(self, interaction: discord.Interaction, button: discord.ui.Button):
            data = get_spam_settings(self.guild.id)
            data["role_logic"] = "and" if data.get("role_logic", "or") == "or" else "or"
            if not save_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await self.refresh(interaction)
    
        @discord.ui.button(label="メッセージ設定", style=discord.ButtonStyle.primary, emoji="💬", row=3)
        async def edit_message(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(SpamMessageModal(self.guild.id, self.requester_id))
    
        @discord.ui.button(label="設定リセット", style=discord.ButtonStyle.danger, emoji="🗑️", row=3)
        async def reset_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
            spam_settings[str(self.guild.id)] = {
                "enabled": False, "channel_id": None, "role_ids": [],
                "role_logic": "or", "message": "お知らせがあります！", "subscribers": [],
            }
            if not save_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await self.refresh(interaction)
    
    
    class SpamSendConfirmView(discord.ui.View):
        def __init__(self, channel_id: int, requester_id: int, target_ids: list[int], content: str):
            super().__init__(timeout=120)
            self.channel_id = channel_id
            self.requester_id = requester_id
            self.target_ids = target_ids
            self.content = content
            self.finished = False
    
        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.requester_id:
                await interaction.response.send_message("この確認ボタンを操作できるのは実行者だけだよ。", ephemeral=True)
                return False
            return True
    
        @discord.ui.button(label="通知を送信", style=discord.ButtonStyle.success, emoji="📢")
        async def confirm_send(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.finished:
                await interaction.response.send_message("この通知は処理済みだよ。", ephemeral=True)
                return
            self.finished = True
            self.stop()
            await interaction.response.defer(ephemeral=True, thinking=True)
            guild = interaction.guild
            channel = guild.get_channel(self.channel_id) if guild else None
            if not isinstance(channel, discord.TextChannel):
                await interaction.edit_original_response(content="通知先チャンネルが見つからないよ。", view=None)
                return
            members = [guild.get_member(uid) for uid in self.target_ids]
            members = [m for m in members if m is not None and not m.bot]
            if not members:
                await interaction.edit_original_response(content="通知対象者が見つからなかったよ。", view=None)
                return
            try:
                for start in range(0, len(members), 20):
                    batch = members[start:start + 20]
                    mentions = " ".join(member.mention for member in batch)
                    await channel.send(
                        f"{self.content}\n\n{mentions}",
                        allowed_mentions=discord.AllowedMentions(
                            users=batch, roles=False, everyone=False, replied_user=False
                        ),
                    )
                    await asyncio.sleep(1)
            except discord.Forbidden:
                await interaction.edit_original_response(
                    content="送信できなかったよ。Botのチャンネル閲覧・メッセージ送信権限を確認してね。", view=None
                )
                return
            except discord.HTTPException:
                logger.exception("SPAM notification send failed: guild=%s channel=%s", guild.id, channel.id)
                await interaction.edit_original_response(content="Discord側のエラーで送信が中断されたよ。", view=None)
                return
            spam_send_cooldowns[guild.id] = asyncio.get_running_loop().time()
            await interaction.edit_original_response(
                content=f"{channel.mention} に **{len(members)}人** への通知を送信したよ。", view=None
            )
    
        @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
        async def cancel_send(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.finished = True
            self.stop()
            await interaction.response.edit_message(content="通知をキャンセルしたよ。", view=None)
    
    
    
    class SpamPanelButton(discord.ui.Button):
        def __init__(self, panel, label, style, action, emoji=None):
            super().__init__(label=label, style=style, emoji=emoji)
            self.panel = panel
            self.action = action
    
        async def callback(self, interaction: discord.Interaction):
            await self.panel.handle_button(interaction, self.action)
    
    
    class SpamPanelView(discord.ui.LayoutView):
        def __init__(self, guild: discord.Guild):
            super().__init__(timeout=600)
            self.guild = guild
            data = get_spam_settings(guild.id)
            channel = guild.get_channel(int(data["channel_id"])) if data.get("channel_id") else None
            roles = [guild.get_role(int(x)) for x in data.get("role_ids", [])]
            roles = [role for role in roles if role is not None]
            subscriber_count = len(set(int(x) for x in data.get("subscribers", [])))
            enabled = "ON" if data.get("enabled") else "OFF"
            logic = "OR（どれか1つ）" if data.get("role_logic", "or") == "or" else "AND（すべて）"
            message = discord.utils.escape_mentions(data.get("message", "お知らせがあります！"))[:500] or "未設定"
            interval_seconds = max(60, min(86400, int(data.get("interval_seconds", 3600))))
    
            self.channel_select = discord.ui.ChannelSelect(
                channel_types=[discord.ChannelType.text],
                placeholder="【管理者】通知先チャンネルを選択",
                min_values=1, max_values=1,
            )
            self.channel_select.callback = self.select_channel
            self.role_select = discord.ui.RoleSelect(
                placeholder="【管理者】対象ロールを複数選択",
                min_values=0, max_values=25,
            )
            self.role_select.callback = self.select_roles
    
            container = discord.ui.Container(
                discord.ui.TextDisplay(
                    "# 📢 SPAM・通知設定\n"
                    "通知対象・送信先・メッセージをまとめて管理します。"
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 🔔 通知機能\n"
                    f"状態：**{enabled}**"
                ),
                discord.ui.ActionRow(
                    SpamPanelButton(self, "通知 ON / OFF", discord.ButtonStyle.primary, "toggle_enabled", "🔔"),
                    SpamPanelButton(self, "OR / AND 切替", discord.ButtonStyle.secondary, "toggle_logic", "🎭"),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 📍 対象チャンネル\n"
                    f"設定：{channel.mention if isinstance(channel, discord.TextChannel) else '未設定'}"
                ),
                discord.ui.ActionRow(self.channel_select),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 🎭 対象ロール\n"
                    f"ロール：{', '.join(role.mention for role in roles) if roles else '未設定'}\n"
                    f"判定：**{logic}**"
                ),
                discord.ui.ActionRow(self.role_select),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 👥 通知登録者\n"
                    f"登録数：**{subscriber_count}人**"
                ),
                discord.ui.ActionRow(
                    SpamPanelButton(self, "通知に登録", discord.ButtonStyle.success, "join", "🔔"),
                    SpamPanelButton(self, "登録解除", discord.ButtonStyle.secondary, "leave", "🔕"),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 💬 通知メッセージ\n"
                    f"{message}"
                ),
                discord.ui.ActionRow(
                    SpamPanelButton(self, "メッセージ編集", discord.ButtonStyle.primary, "edit_message", "✏️"),
                    SpamPanelButton(self, "通知を送信", discord.ButtonStyle.success, "send_notice", "📢"),
                    SpamPanelButton(self, "設定リセット", discord.ButtonStyle.danger, "reset_settings", "🗑️"),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### ⏱️ 自動送信間隔\n"
                    f"設定：**{interval_seconds}秒ごと**（60〜86400秒）"
                ),
                discord.ui.ActionRow(
                    SpamPanelButton(self, "送信間隔を設定", discord.ButtonStyle.secondary, "set_interval", "⏱️"),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 🛡️ 送信制限\n"
                    "1回最大100人・送信後10分間は再送信不可"
                ),
                accent_color=discord.Color.blurple(),
            )
            self.add_item(container)
    
        async def admin_only(self, interaction: discord.Interaction) -> bool:
            if interaction.guild is None or not (
                interaction.user.id == interaction.guild.owner_id
                or interaction.user.guild_permissions.administrator
            ):
                await interaction.response.send_message("この操作はサーバー管理者のみ使えるよ。", ephemeral=True)
                return False
            return True
    
        async def refresh(self, interaction: discord.Interaction):
            await interaction.response.edit_message(view=SpamPanelView(self.guild))
    
        async def select_channel(self, interaction: discord.Interaction):
            if not await self.admin_only(interaction):
                return
    
            selected_values = (interaction.data or {}).get("values", [])
            if not selected_values:
                logger.warning("SPAM channel select returned no values: guild=%s user=%s", self.guild.id, interaction.user.id)
                await interaction.response.send_message("チャンネル選択を取得できなかったよ。もう一度選んでね。", ephemeral=True)
                return
    
            try:
                channel_id = int(selected_values[0])
            except (TypeError, ValueError):
                logger.warning("SPAM channel select invalid value: guild=%s values=%r", self.guild.id, selected_values)
                await interaction.response.send_message("チャンネル情報を読み取れなかったよ。もう一度選んでね。", ephemeral=True)
                return
    
            channel = self.guild.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    channel = None
    
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild.id:
                logger.warning("SPAM channel select rejected: guild=%s channel_id=%s channel=%r", self.guild.id, channel_id, channel)
                await interaction.response.send_message("同じサーバーのテキストチャンネルを選んでね。", ephemeral=True)
                return
    
            data = get_spam_settings(self.guild.id)
            data["channel_id"] = channel.id
            if not save_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
    
            logger.info("SPAM channel selected: guild=%s channel=%s", self.guild.id, channel.id)
            await self.refresh(interaction)
    
        async def select_roles(self, interaction: discord.Interaction):
            if not await self.admin_only(interaction):
                return
            get_spam_settings(self.guild.id)["role_ids"] = [
                role.id for role in self.role_select.values if not role.is_default()
            ]
            if not save_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await self.refresh(interaction)
    
        async def handle_button(self, interaction: discord.Interaction, action: str):
            if action in {"toggle_enabled", "toggle_logic", "edit_message", "set_interval", "send_notice", "reset_settings"}:
                if not await self.admin_only(interaction):
                    return
    
            data = get_spam_settings(self.guild.id)
    
            if action == "join":
                subscribers = set(int(x) for x in data.get("subscribers", []))
                if interaction.user.id in subscribers:
                    await interaction.response.send_message("すでに通知登録済みだよ。", ephemeral=True)
                    return
                subscribers.add(interaction.user.id)
                data["subscribers"] = sorted(subscribers)
                if not save_spam_settings():
                    await interaction.response.send_message("登録を保存できなかったよ。", ephemeral=True)
                    return
                await interaction.response.send_message("通知対象に登録したよ！", ephemeral=True)
                return
    
            if action == "leave":
                subscribers = set(int(x) for x in data.get("subscribers", []))
                subscribers.discard(interaction.user.id)
                data["subscribers"] = sorted(subscribers)
                if not save_spam_settings():
                    await interaction.response.send_message("登録解除を保存できなかったよ。", ephemeral=True)
                    return
                await interaction.response.send_message("通知対象から解除したよ。", ephemeral=True)
                return
    
            if action == "toggle_enabled":
                if not data.get("enabled", False):
                    try:
                        selected_channel_id = int(data.get("channel_id") or 0)
                    except (TypeError, ValueError):
                        selected_channel_id = 0
                    channel = (
                        self.guild.get_channel(selected_channel_id)
                        or self.guild.get_channel_or_thread(selected_channel_id)
                        or bot.get_channel(selected_channel_id)
                    )
                    if channel is None and selected_channel_id:
                        try:
                            channel = await bot.fetch_channel(selected_channel_id)
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            channel = None
                    if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild.id:
                        await interaction.response.send_message(
                            "対象チャンネルが保存されていないか、見つからないよ。チャンネル選択欄でもう一度選び直してね。",
                            ephemeral=True,
                        )
                        return
                    if not data.get("role_ids"):
                        await interaction.response.send_message("先に対象ロールを1つ以上選択してね。", ephemeral=True)
                        return
                    data["next_send_at"] = datetime.now(timezone.utc).timestamp() + max(
                        60, min(86400, int(data.get("interval_seconds", 3600)))
                    )
                    data["enabled"] = True
                else:
                    data["enabled"] = False
                if not save_spam_settings():
                    await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                    return
                await self.refresh(interaction)
                return
    
            if action == "toggle_logic":
                data["role_logic"] = "and" if data.get("role_logic", "or") == "or" else "or"
                if not save_spam_settings():
                    await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                    return
                await self.refresh(interaction)
                return
    
            if action == "edit_message":
                await interaction.response.send_modal(SpamMessageModal(self.guild.id, interaction.user.id))
                return
    
            if action == "set_interval":
                await interaction.response.send_modal(SpamIntervalModal(self.guild.id, interaction.user.id))
                return
    
            if action == "reset_settings":
                spam_settings[str(self.guild.id)] = {
                    "enabled": False, "channel_id": None, "role_ids": [],
                    "role_logic": "or", "message": "お知らせがあります！", "subscribers": [],
                    "interval_seconds": 3600, "next_send_at": 0,
                }
                if not save_spam_settings():
                    await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                    return
                await self.refresh(interaction)
                return
    
            if action == "send_notice":
                if not data.get("enabled"):
                    await interaction.response.send_message("通知機能がOFFだよ。先にONにしてね。", ephemeral=True)
                    return
                channel = self.guild.get_channel(int(data.get("channel_id") or 0))
                if not isinstance(channel, discord.TextChannel):
                    await interaction.response.send_message("通知先チャンネルを選択してね。", ephemeral=True)
                    return
                role_ids = {int(x) for x in data.get("role_ids", [])}
                if not role_ids:
                    await interaction.response.send_message("対象ロールを1つ以上選択してね。", ephemeral=True)
                    return
                now = asyncio.get_running_loop().time()
                last_sent = spam_send_cooldowns.get(self.guild.id, 0)
                if now - last_sent < 600:
                    await interaction.response.send_message(
                        f"連続送信防止のため、あと **{int(600 - (now - last_sent))}秒** 待ってね。",
                        ephemeral=True,
                    )
                    return
                subscribers = {int(x) for x in data.get("subscribers", [])}
                logic = data.get("role_logic", "or")
                targets = []
                for member in self.guild.members:
                    if member.bot or member.id not in subscribers:
                        continue
                    member_roles = {role.id for role in member.roles}
                    matched = role_ids.issubset(member_roles) if logic == "and" else bool(role_ids & member_roles)
                    if matched:
                        targets.append(member)
                targets = targets[:100]
                if not targets:
                    await interaction.response.send_message("条件に一致する通知登録者がいないよ。", ephemeral=True)
                    return
                content = discord.utils.escape_mentions(data.get("message", "お知らせがあります！"))
                await interaction.response.send_message(
                    f"📢 **通知を送信するよ**\n送信先：{channel.mention}\n"
                    f"対象人数：**{len(targets)}人**（最大100人）\n"
                    "通知登録済みで、選択ロール条件に一致する人だけが対象だよ。\n送信していい？",
                    view=SpamSendConfirmView(channel.id, interaction.user.id, [m.id for m in targets], content),
                    ephemeral=True,
                )
                return
    
    
    @tasks.loop(seconds=5)
    async def spam_announcement_loop():
        now = datetime.now(timezone.utc).timestamp()
        for guild in list(bot.guilds):
            data = get_spam_settings(guild.id)
            if not data.get("enabled"):
                continue
            try:
                interval = max(60, min(86400, int(data.get("interval_seconds", 3600))))
                next_send_at = float(data.get("next_send_at", 0) or 0)
            except (TypeError, ValueError):
                logger.warning("SPAM interval config invalid: guild=%s", guild.id)
                continue
            if next_send_at <= 0:
                data["next_send_at"] = now + interval
                save_spam_settings()
                continue
            if now < next_send_at:
                continue
    
            channel = guild.get_channel(int(data.get("channel_id") or 0))
            role_ids = {int(x) for x in data.get("role_ids", [])}
            subscribers = {int(x) for x in data.get("subscribers", [])}
            if not isinstance(channel, discord.TextChannel) or not role_ids:
                data["enabled"] = False
                save_spam_settings()
                continue
    
            logic = data.get("role_logic", "or")
            targets = []
            for member in guild.members:
                if member.bot or member.id not in subscribers:
                    continue
                member_roles = {role.id for role in member.roles}
                matched = role_ids.issubset(member_roles) if logic == "and" else bool(role_ids & member_roles)
                if matched:
                    targets.append(member)
            targets = targets[:100]
            if not targets:
                data["next_send_at"] = now + interval
                save_spam_settings()
                continue
    
            content = discord.utils.escape_mentions(data.get("message", "お知らせがあります！")).strip()
            if not content:
                content = "お知らせがあります！"
            mentions = " ".join(member.mention for member in targets)
            try:
                await channel.send(
                    f"{content}\n\n{mentions}",
                    allowed_mentions=discord.AllowedMentions(
                        users=targets, roles=False, everyone=False, replied_user=False
                    ),
                )
                data["next_send_at"] = datetime.now(timezone.utc).timestamp() + interval
                save_spam_settings()
            except discord.Forbidden:
                logger.warning("SPAM auto-send forbidden: guild=%s channel=%s", guild.id, channel.id)
                data["enabled"] = False
                save_spam_settings()
            except discord.HTTPException:
                logger.exception("SPAM auto-send failed: guild=%s channel=%s", guild.id, channel.id)
    
    
    @bot.tree.command(name="spam", description="通知設定・登録・解除・送信を1つのパネルで管理")
    async def spam_command(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        await interaction.response.send_message(
            view=SpamPanelView(interaction.guild),
            ephemeral=True,
        )
    
    
    
    
    # ==================================================
    # アンチ連投（Components V2 / Neon保存）
    # ==================================================
    ANTI_SPAM_DEFAULTS = {
        "enabled": False,
        "timeout_enabled": False,
        "timeout_minutes": 10,
        "burst_count": 5,
        "burst_seconds": 5,
        "duplicate_count": 3,
        "duplicate_seconds": 10,
    }
    
    
    def get_anti_spam_settings(guild_id: int):
        data = anti_spam_settings.setdefault(str(guild_id), {})
        for key, value in ANTI_SPAM_DEFAULTS.items():
            data.setdefault(key, value)
        try:
            data["timeout_minutes"] = max(1, min(40320, int(data.get("timeout_minutes", 10))))
            data["burst_count"] = max(2, min(20, int(data.get("burst_count", 5))))
            data["burst_seconds"] = max(1, min(30, int(data.get("burst_seconds", 5))))
            data["duplicate_count"] = max(2, min(10, int(data.get("duplicate_count", 3))))
            data["duplicate_seconds"] = max(1, min(60, int(data.get("duplicate_seconds", 10))))
        except (TypeError, ValueError):
            data.update(ANTI_SPAM_DEFAULTS)
        return data
    
    
    def save_anti_spam_settings():
        return save_json(ANTI_SPAM_FILE, anti_spam_settings)
    
    
    async def process_anti_spam_message(message: discord.Message) -> bool:
        guild = message.guild
        if guild is None or message.webhook_id is not None or not isinstance(message.author, discord.Member):
            return False
    
        data = get_anti_spam_settings(guild.id)
        if not data.get("enabled", False):
            return False
    
        member = message.author
        if member.bot or member.id == guild.owner_id or member.guild_permissions.administrator:
            return False
    
        now = asyncio.get_running_loop().time()
        key = (guild.id, member.id)
        history = anti_spam_histories.setdefault(key, [])
        history[:] = [
            (sent_at, old_message, content)
            for sent_at, old_message, content in history
            if now - sent_at <= max(data["burst_seconds"], data["duplicate_seconds"])
        ]
    
        content = " ".join((message.content or "").casefold().split())
        history.append((now, message, content))
    
        burst = [item for item in history if now - item[0] <= data["burst_seconds"]]
        duplicate = (
            [item for item in history if content and item[2] == content
             and now - item[0] <= data["duplicate_seconds"]]
        )
        triggered = (
            len(burst) >= data["burst_count"]
            or len(duplicate) >= data["duplicate_count"]
        )
        if not triggered:
            return False
    
        # 同じ連投で何度も処罰しないよう、検知時点で履歴をクリアする
        anti_spam_histories.pop(key, None)
        deleted = 0
        for _, old_message, _ in history:
            try:
                await old_message.delete()
                deleted += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
    
        timeout_text = ""
        if data.get("timeout_enabled", False):
            bot_member = guild.me
            minutes = data["timeout_minutes"]
            if (
                bot_member is not None
                and bot_member.guild_permissions.moderate_members
                and member.top_role < bot_member.top_role
            ):
                try:
                    await member.timeout(
                        discord.utils.utcnow() + timedelta(minutes=minutes),
                        reason="アンチ連投：短時間の大量送信または同一内容の連投",
                    )
                    timeout_text = f" / タイムアウト：{minutes}分"
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception("アンチ連投のタイムアウトに失敗: guild=%s user=%s", guild.id, member.id)
                    timeout_text = " / タイムアウト失敗（Bot権限・ロール順位を確認）"
            else:
                timeout_text = " / タイムアウト不可（Bot権限・ロール順位を確認）"
    
        try:
            await message.channel.send(
                f"🛡️ {member.mention} の連投を検知したよ。"
                f"メッセージ削除：{deleted}件{timeout_text}",
                delete_after=8,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.exception("アンチ連投の検知通知に失敗")
        logger.info(
            "アンチ連投検知: guild=%s user=%s deleted=%s timeout=%s",
            guild.id, member.id, deleted, bool(data.get("timeout_enabled")),
        )
        return True
    
    
    class AntiSpamPanelButton(discord.ui.Button):
        def __init__(self, panel, label, style, action, emoji=None):
            super().__init__(label=label, style=style, emoji=emoji)
            self.panel = panel
            self.action = action
    
        async def callback(self, interaction: discord.Interaction):
            await self.panel.handle_button(interaction, self.action)
    
    
    class AntiSpamTimeoutModal(discord.ui.Modal, title="タイムアウト時間の設定"):
        minutes = discord.ui.TextInput(
            label="タイムアウト時間（分）",
            placeholder="例：10（1〜40320分）",
            min_length=1,
            max_length=5,
            required=True,
        )
    
        def __init__(self, guild_id: int):
            super().__init__(timeout=180)
            self.guild_id = guild_id
    
        async def on_submit(self, interaction: discord.Interaction):
            if interaction.guild is None or interaction.guild.id != self.guild_id:
                await interaction.response.send_message("サーバー情報を確認できないよ。", ephemeral=True)
                return
            if not (
                interaction.user.id == interaction.guild.owner_id
                or interaction.user.guild_permissions.administrator
            ):
                await interaction.response.send_message("サーバー管理者だけ変更できるよ。", ephemeral=True)
                return
            try:
                value = int(str(self.minutes.value).strip())
            except ValueError:
                await interaction.response.send_message("1〜40320の数字を入力してね。", ephemeral=True)
                return
            if not 1 <= value <= 40320:
                await interaction.response.send_message("1〜40320分の範囲で入力してね。", ephemeral=True)
                return
            get_anti_spam_settings(self.guild_id)["timeout_minutes"] = value
            if not save_anti_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await interaction.response.edit_message(view=AntiSpamPanelView(interaction.guild))
    
    
    class AntiSpamThresholdModal(discord.ui.Modal, title="アンチ連投の検知条件"):
        def __init__(self, guild_id: int):
            super().__init__(timeout=180)
            self.guild_id = guild_id
            data = get_anti_spam_settings(guild_id)
            self.burst_count = discord.ui.TextInput(
                label="短時間の連投回数（2〜20回）",
                placeholder="例：5",
                default=str(data["burst_count"]),
                min_length=1,
                max_length=2,
                required=True,
            )
            self.burst_seconds = discord.ui.TextInput(
                label="短時間の判定秒数（1〜30秒）",
                placeholder="例：5",
                default=str(data["burst_seconds"]),
                min_length=1,
                max_length=2,
                required=True,
            )
            self.duplicate_count = discord.ui.TextInput(
                label="同一内容の連投回数（2〜10回）",
                placeholder="例：3",
                default=str(data["duplicate_count"]),
                min_length=1,
                max_length=2,
                required=True,
            )
            self.duplicate_seconds = discord.ui.TextInput(
                label="同一内容の判定秒数（1〜60秒）",
                placeholder="例：10",
                default=str(data["duplicate_seconds"]),
                min_length=1,
                max_length=2,
                required=True,
            )
            for item in (self.burst_count, self.burst_seconds, self.duplicate_count, self.duplicate_seconds):
                self.add_item(item)
    
        async def on_submit(self, interaction: discord.Interaction):
            if interaction.guild is None or interaction.guild.id != self.guild_id:
                await interaction.response.send_message("サーバー情報を確認できないよ。", ephemeral=True)
                return
            if not (
                interaction.user.id == interaction.guild.owner_id
                or interaction.user.guild_permissions.administrator
            ):
                await interaction.response.send_message("サーバー管理者だけ変更できるよ。", ephemeral=True)
                return
            try:
                values = {
                    "burst_count": int(str(self.burst_count.value).strip()),
                    "burst_seconds": int(str(self.burst_seconds.value).strip()),
                    "duplicate_count": int(str(self.duplicate_count.value).strip()),
                    "duplicate_seconds": int(str(self.duplicate_seconds.value).strip()),
                }
            except ValueError:
                await interaction.response.send_message("すべて半角数字で入力してね。", ephemeral=True)
                return
            limits = {
                "burst_count": (2, 20),
                "burst_seconds": (1, 30),
                "duplicate_count": (2, 10),
                "duplicate_seconds": (1, 60),
            }
            for key, (minimum, maximum) in limits.items():
                if not minimum <= values[key] <= maximum:
                    await interaction.response.send_message(
                        f"{key} の値が範囲外だよ。設定可能な範囲を確認してね。",
                        ephemeral=True,
                    )
                    return
            get_anti_spam_settings(self.guild_id).update(values)
            if not save_anti_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await interaction.response.edit_message(view=AntiSpamPanelView(interaction.guild))
    
    
    class AntiSpamPanelView(discord.ui.LayoutView):
        def __init__(self, guild: discord.Guild):
            super().__init__(timeout=600)
            self.guild = guild
            data = get_anti_spam_settings(guild.id)
            status = "ON" if data["enabled"] else "OFF"
            timeout_status = "ON" if data["timeout_enabled"] else "OFF"
            timeout_minutes = data["timeout_minutes"]
    
            container = discord.ui.Container(
                discord.ui.TextDisplay(
                    "# 🛡️ アンチ連投設定\n"
                    "短時間の大量送信・同一メッセージの連投を検知します。"
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 🚨 検知機能\n"
                    f"状態：**{status}**\n"
                    f"短時間の連投：**{data['burst_count']}回 / {data['burst_seconds']}秒**\n"
                    f"同一内容の連投：**{data['duplicate_count']}回 / {data['duplicate_seconds']}秒**"
                ),
                discord.ui.ActionRow(
                    AntiSpamPanelButton(
                        self, "回数・秒数を変更", discord.ButtonStyle.secondary,
                        "set_thresholds", "⚙️"
                    ),
                ),
                discord.ui.ActionRow(
                    AntiSpamPanelButton(
                        self, "アンチ連投 ON / OFF", discord.ButtonStyle.primary,
                        "toggle_enabled", "🛡️"
                    ),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### ⏱️ 自動タイムアウト\n"
                    f"状態：**{timeout_status}**\n"
                    f"時間：**{timeout_minutes}分**\n"
                    "OFFでも連投検知とメッセージ削除は動作します。"
                ),
                discord.ui.ActionRow(
                    AntiSpamPanelButton(
                        self, "タイムアウト ON / OFF", discord.ButtonStyle.secondary,
                        "toggle_timeout", "⏱️"
                    ),
                    AntiSpamPanelButton(
                        self, "時間を変更", discord.ButtonStyle.secondary,
                        "set_timeout", "⚙️"
                    ),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "### 🧹 自動対処\n"
                    "検知した連投メッセージを削除します。\n"
                    "タイムアウトがONの場合は、設定時間のタイムアウトも実行します。"
                ),
                accent_color=discord.Color.blurple(),
            )
            self.add_item(container)
    
        async def handle_button(self, interaction: discord.Interaction, action: str):
            guild = interaction.guild
            if guild is None or guild.id != self.guild.id:
                await interaction.response.send_message("サーバー内で操作してね。", ephemeral=True)
                return
            if not (
                interaction.user.id == guild.owner_id
                or interaction.user.guild_permissions.administrator
            ):
                await interaction.response.send_message("サーバー管理者だけ操作できるよ。", ephemeral=True)
                return
    
            data = get_anti_spam_settings(guild.id)
            if action == "set_timeout":
                await interaction.response.send_modal(AntiSpamTimeoutModal(guild.id))
                return
            if action == "set_thresholds":
                await interaction.response.send_modal(AntiSpamThresholdModal(guild.id))
                return
            if action == "toggle_enabled":
                data["enabled"] = not data["enabled"]
            elif action == "toggle_timeout":
                data["timeout_enabled"] = not data["timeout_enabled"]
    
            if not save_anti_spam_settings():
                await interaction.response.send_message("Neonへの保存に失敗したよ。", ephemeral=True)
                return
            await interaction.response.edit_message(view=AntiSpamPanelView(guild))
    
    
    @bot.tree.command(name="antispam", description="アンチ連投の検知・タイムアウト設定")
    @app_commands.guild_only()
    async def anti_spam_command(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってね。", ephemeral=True)
            return
        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message("サーバー管理者だけ使えるよ。", ephemeral=True)
            return
        await interaction.response.send_message(
            view=AntiSpamPanelView(interaction.guild),
            ephemeral=True,
        )
    
    
    
    return True
