import os
import json
import random
from pathlib import Path
import discord
from discord.ext import commands

# メッセージの内容を読み取る権限を有効化
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)

# 通貨データの保存先
BALANCE_FILE = Path("balances.json")
STARTING_BALANCE = 1000

SLOT_EMOJIS = ["🍒", "🍋", "🔔", "⭐", "7️⃣"]

# 3つ同じ絵柄がそろったときの配当倍率
PAYOUTS = {
    "🍒": 2,
    "🍋": 3,
    "🔔": 5,
    "⭐": 10,
    "7️⃣": 50,
}


def load_balances():
    if not BALANCE_FILE.exists():
        return {}
    try:
        data = json.loads(BALANCE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


balances = load_balances()


def save_balances():
    BALANCE_FILE.write_text(
        json.dumps(balances, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_balance(user_id):
    key = str(user_id)
    if key not in balances:
        balances[key] = STARTING_BALANCE
        save_balances()
    return int(balances[key])


@bot.command(name="balance")
async def balance(ctx):
    money = get_balance(ctx.author.id)
    await ctx.send(
        f"💰 {ctx.author.mention} の所持金：**{money:,} コイン**"
    )


@bot.command(name="slot")
async def slot(ctx, bet: int = None):
    if bet is None or bet <= 0:
        await ctx.send("使い方：`.slot 100`")
        return

    money = get_balance(ctx.author.id)

    if bet > money:
        await ctx.send(
            f"❌ 所持金不足！現在は **{money:,} コイン** だよ。"
        )
        return

    # 賭け金を先に引く
    balances[str(ctx.author.id)] = money - bet

    result = [random.choice(SLOT_EMOJIS) for _ in range(3)]
    payout = 0

    if result[0] == result[1] == result[2]:
        payout = bet * PAYOUTS[result[0]]

    balances[str(ctx.author.id)] += payout
    save_balances()

    reels = " | ".join(result)

    if payout > 0:
        await ctx.send(
            f"🎰 **SLOT** 🎰\n\n"
            f"【 {reels} 】\n"
            f"🎉 当たり！ **{payout:,} コイン** 獲得！\n"
            f"💰 残高：**{balances[str(ctx.author.id)]:,} コイン**"
        )
    else:
        await ctx.send(
            f"🎰 **SLOT** 🎰\n\n"
            f"【 {reels} 】\n"
            f"❌ ハズレ！ **{bet:,} コイン** 消費！\n"
            f"💰 残高：**{balances[str(ctx.author.id)]:,} コイン**"
        )


@bot.command(name="Payment")
async def payment(ctx):
    # ownerロールを確認
    if not isinstance(ctx.author, discord.Member):
        return

    if not any(
        role.name.lower() == "owner"
        for role in ctx.author.roles
    ):
        await ctx.send("❌ このコマンドは owner ロール限定だよ。")
        return

    await ctx.send(
        "👑 **コイン付与**\n"
        "付与する相手をメンションしてね！（60秒以内）"
    )

    def check(message):
        return (
            message.author.id == ctx.author.id
            and message.channel.id == ctx.channel.id
        )

    try:
        target_msg = await bot.wait_for(
            "message", check=check, timeout=60
        )

        target = None
        if target_msg.mentions:
            target = target_msg.mentions[0]
        else:
            try:
                target_id = int(target_msg.content.strip())
                target = ctx.guild.get_member(target_id)
            except ValueError:
                pass

        if target is None or target.bot:
            await ctx.send("❌ 有効なユーザーを指定してね。")
            return

        await ctx.send(
            f"💰 {target.mention} に何コイン付与する？数字で入力してね。"
        )

        amount_msg = await bot.wait_for(
            "message", check=check, timeout=60
        )

    try:
            amount = int(amount_msg.content.strip())
    except ValueError:
        await ctx.send("❌ 数字で入力してね。")
        return

    if amount <= 0 or amount > 1_000_000_000:
        await ctx.send("❌ 1〜1,000,000,000 の範囲で入力してね。")
        return

    current = get_balance(target.id)
    balances[str(target.id)] = current + amount
    save_balances()

    await ctx.send(
        f"✅ **コイン付与完了！**\n"
        f"対象：{target.mention}\n"
        f"付与額：**{amount:,} コイン**\n"
        f"現在の残高：**{balances[str(target.id)]:,} コイン**"
    )

    except TimeoutError:
        await ctx.send("⌛ 時間切れ！もう一度 `.Payment` を実行してね。")

# ボットの起動
bot.run(os.getenv("DISCORD_TOKEN"))
