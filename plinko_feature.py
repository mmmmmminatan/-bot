import asyncio
import random

import discord
from discord.ext import commands


ROWS = 8
MULTIPLIERS = [10, 5, 2, 1, 0.5, 1, 2, 5, 10]
ACTIVE_USERS = set()


def render_board(path, current_row):
    lines = ["\`\`\`"]
    for row in range(ROWS + 1):
        cells = []
        for col in range(row + 1):
            if row == current_row and row < len(path) and col == path[row]:
                cells.append("●")
            else:
                cells.append("·")
        lines.append((" " * (ROWS - row)) + "   ".join(cells))
    lines.append("\`\`\`")
    return "\n".join(lines)


def render_final_board(slot):
    lines = ["\`\`\`"]
    for row in range(ROWS + 1):
        cells = ["●" if row == ROWS and col == slot else "·" for col in range(row + 1)]
        lines.append((" " * (ROWS - row)) + "   ".join(cells))
    lines.append("\`\`\`")
    labels = []
    for index, multiplier in enumerate(MULTIPLIERS):
        mark = "▼" if index == slot else " "
        labels.append(f"{mark}{multiplier:g}x")
    return "\n".join(lines) + "\n" + "  ".join(labels)


def setup_plinko(bot, get_balance, set_balance, money, money_change):
    @bot.command(name="plinko", aliases=["プリンコ"])
    async def plinko_command(ctx, bet_text: str = None):
        if ctx.guild is None:
            await ctx.reply("サーバー内で使ってね。", mention_author=False)
            return

        if bet_text is None:
            await ctx.reply("使い方：\`.plinko 賭け金\`\n例：\`.plinko 100\` または \`.plinko all\`", mention_author=False)
            return

        user_id = str(ctx.author.id)
        if user_id in ACTIVE_USERS:
            await ctx.reply("今のPlinkoが終わるまで待ってね！", mention_author=False)
            return

        if bet_text.casefold() == "all":
            bet = int(get_balance(user_id))
        else:
            try:
                bet = int(bet_text.replace(",", "").replace("$", ""))
            except ValueError:
                await ctx.reply("賭け金は数字か \`all\` で入力してね。", mention_author=False)
                return

        balance = int(get_balance(user_id))
        if bet <= 0:
            await ctx.reply("賭け金は1以上にしてね。", mention_author=False)
            return
        if bet > balance:
            await ctx.reply(f"残高が足りないよ。現在の残高：{money(balance)}", mention_author=False)
            return

        ACTIVE_USERS.add(user_id)
        deducted = False
        try:
            set_balance(user_id, balance - bet)
            deducted = True
            path = [0]
            embed = discord.Embed(
                title="🔵 PLINKO",
                description=f"**{ctx.author.display_name}**\n賭け金：{money(bet)}\n\nボールを落としているよ！\n{render_board(path, 0)}",
                color=discord.Color.blurple(),
            )
            message = await ctx.send(embed=embed)

            position = 0
            for row in range(1, ROWS + 1):
                position += random.choice((0, 1))
                path.append(position)
                embed.description = (
                    f"**{ctx.author.display_name}**\n賭け金：{money(bet)}\n\n"
                    f"ボール落下中… ({row}/{ROWS})\n{render_board(path, row)}"
                )
                await message.edit(embed=embed)
                await asyncio.sleep(0.45)

            multiplier = MULTIPLIERS[position]
            payout = int(round(bet * multiplier))
            net = payout - bet
            set_balance(user_id, balance - bet + payout)
            deducted = False

            embed.title = "🎯 PLINKO 結果"
            embed.color = discord.Color.green() if net >= 0 else discord.Color.red()
            embed.description = (
                f"**{ctx.author.mention}**\n"
                f"賭け金：{money(bet)}\n"
                f"倍率：**{multiplier:g}x**\n"
                f"払い戻し：**{money(payout)}**\n"
                f"利益：**{money_change(net)}**\n"
                f"残高：**{money(get_balance(user_id))}**\n\n"
                f"{render_final_board(position)}"
            )
            await message.edit(embed=embed)
        except Exception:
            if deducted:
                set_balance(user_id, int(get_balance(user_id)) + bet)
            raise
        finally:
            ACTIVE_USERS.discard(user_id)
