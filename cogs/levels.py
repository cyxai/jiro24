"""
cogs/levels.py — XP & leveling system
07Dipper / Jiro • NixAI • by Blueey

Supabase table required:
  user_levels (
    guild_id  TEXT,
    user_id   TEXT,
    xp        INT  DEFAULT 0,
    level     INT  DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
  )

Commands
  !rank [@user]         Show XP card for yourself or another member.
  !leaderboard          Top 10 XP members in this server.
  !setxp @user <xp>     (Admin) Manually set a user's XP.
  !resetxp @user        (Admin) Reset a user's XP and level to zero.
"""

import math
import asyncio
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import icon
from utils.embeds import embed

# XP awarded per message (random range handled in on_message)
XP_MIN      = 15
XP_MAX      = 25
# Cooldown in seconds between XP grants per user per guild
XP_COOLDOWN = 60


def _xp_for_level(level: int) -> int:
    """Total XP required to reach `level` from 0."""
    return int(5 * (level ** 2) + 50 * level + 100)


def _level_from_xp(xp: int) -> int:
    """Derive the level for a given XP total."""
    level = 0
    while xp >= _xp_for_level(level):
        xp -= _xp_for_level(level)
        level += 1
    return level


def _xp_progress(total_xp: int) -> tuple[int, int, int]:
    """Return (current_level, xp_into_level, xp_needed_for_next)."""
    level = 0
    remaining = total_xp
    while remaining >= _xp_for_level(level):
        remaining -= _xp_for_level(level)
        level += 1
    return level, remaining, _xp_for_level(level)


def _bar(current: int, total: int, length: int = 20) -> str:
    filled = round(length * current / max(total, 1))
    return "█" * filled + "░" * (length - filled)


class Levels(commands.Cog):
    """XP and leveling system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # cooldown: { (guild_id, user_id): last_xp_time }
        self._cooldown: dict[tuple, datetime] = {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_xp(self, guild_id: int, user_id: int) -> tuple[int, int]:
        """Return (total_xp, level) for a user."""
        try:
            rows = await self.bot.db._get("user_levels", {
                "guild_id": f"eq.{guild_id}",
                "user_id":  f"eq.{user_id}",
            })
            if rows:
                return int(rows[0].get("xp", 0)), int(rows[0].get("level", 0))
        except Exception:
            pass
        return 0, 0

    async def _add_xp(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int, bool]:
        """
        Add XP to a user. Returns (new_xp, new_level, levelled_up).
        """
        xp, old_level = await self._get_xp(guild_id, user_id)
        xp += amount
        new_level, _, _ = _xp_progress(xp)
        levelled_up = new_level > old_level
        try:
            await self.bot.db._upsert("user_levels", {
                "guild_id": str(guild_id),
                "user_id":  str(user_id),
                "xp":       xp,
                "level":    new_level,
            }, "guild_id,user_id")
        except Exception:
            pass
        return xp, new_level, levelled_up

    # ── on_message XP grant ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        key = (message.guild.id, message.author.id)
        now = datetime.now(timezone.utc)
        last = self._cooldown.get(key)
        if last and (now - last).total_seconds() < XP_COOLDOWN:
            return

        self._cooldown[key] = now
        import random
        amount = random.randint(XP_MIN, XP_MAX)
        xp, level, levelled_up = await self._add_xp(message.guild.id, message.author.id, amount)

        if levelled_up:
            try:
                lvl_embed = embed(
                    f"{icon('level')} Level Up!",
                    f"🎉 {message.author.mention} just reached **Level {level}**!",
                    color="success",
                )
                await message.channel.send(embed=lvl_embed)
            except discord.HTTPException:
                pass

            # Award level roles if configured (guild_config key: "level_roles")
            try:
                config     = await self.bot.db.get_config(message.guild.id)
                level_roles: dict = config.get("level_roles") or {}
                role_id = level_roles.get(str(level))
                if role_id:
                    role = message.guild.get_role(int(role_id))
                    if role:
                        await message.author.add_roles(role, reason=f"Reached level {level}")
            except Exception:
                pass

    # ── !rank ─────────────────────────────────────────────────────────────────

    @commands.command(name="rank")
    async def rank_prefix(self, ctx: commands.Context, member: discord.Member = None):
        """Show your XP card.  !rank [@user]"""
        await self._show_rank(ctx.guild, member or ctx.author, send=ctx.send)

    @app_commands.command(name="rank", description="Show your XP rank card")
    @app_commands.describe(member="Member to check (defaults to you)")
    async def rank_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        await self._show_rank(
            interaction.guild, member or interaction.user,
            send=lambda **kw: interaction.response.send_message(**kw),
        )

    async def _show_rank(self, guild: discord.Guild, member: discord.Member, *, send):
        xp, _ = await self._get_xp(guild.id, member.id)
        level, xp_into, xp_needed = _xp_progress(xp)
        bar = _bar(xp_into, xp_needed)

        # Server rank position
        try:
            rows = await self.bot.db._get("user_levels", {
                "guild_id": f"eq.{guild.id}",
                "order":    "xp.desc",
            })
            ids   = [r["user_id"] for r in rows]
            rank  = ids.index(str(member.id)) + 1 if str(member.id) in ids else "?"
        except Exception:
            rank = "?"

        e = embed(f"{icon('level')} {member.display_name}'s Rank", color="info")
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Level",   value=str(level),          inline=True)
        e.add_field(name="Rank",    value=f"#{rank}",           inline=True)
        e.add_field(name="Total XP", value=f"{xp:,}",          inline=True)
        e.add_field(
            name=f"Progress to Level {level + 1}",
            value=f"`{bar}` {xp_into:,} / {xp_needed:,} XP",
            inline=False,
        )
        await send(embed=e)

    # ── !leaderboard ──────────────────────────────────────────────────────────

    @commands.command(name="leaderboard", aliases=["lb"])
    async def leaderboard_prefix(self, ctx: commands.Context):
        """Show the top 10 XP members.  !leaderboard"""
        await self._show_lb(ctx.guild, send=ctx.send)

    @app_commands.command(name="leaderboard", description="Show the top 10 XP members in this server")
    async def leaderboard_slash(self, interaction: discord.Interaction):
        await self._show_lb(
            interaction.guild,
            send=lambda **kw: interaction.response.send_message(**kw),
        )

    async def _show_lb(self, guild: discord.Guild, *, send):
        try:
            rows = await self.bot.db._get("user_levels", {
                "guild_id": f"eq.{guild.id}",
                "order":    "xp.desc",
                "limit":    "10",
            })
        except Exception:
            rows = []
        if not rows:
            return await send(embed=embed(
                f"{icon('level')} Leaderboard",
                "No XP data yet. Start chatting!", color="info",
            ))

        medals = ["🥇", "🥈", "🥉"]
        lines  = []
        for i, row in enumerate(rows):
            member = guild.get_member(int(row["user_id"]))
            name   = member.display_name if member else f"User {row['user_id']}"
            prefix = medals[i] if i < 3 else f"`{i+1}.`"
            lvl, xp_into, xp_needed = _xp_progress(int(row.get("xp", 0)))
            lines.append(f"{prefix} **{name}** — Level {lvl} ({int(row.get('xp', 0)):,} XP)")

        await send(embed=embed(
            f"{icon('level')} XP Leaderboard — {guild.name}",
            "\n".join(lines), color="mod",
        ))

    # ── Admin: setxp / resetxp ────────────────────────────────────────────────

    @commands.command(name="setxp")
    @commands.has_permissions(administrator=True)
    async def setxp_prefix(self, ctx: commands.Context, member: discord.Member, xp: int):
        """Manually set a member's XP.  !setxp @user <xp>"""
        level, _, _ = _xp_progress(xp)
        try:
            await self.bot.db._upsert("user_levels", {
                "guild_id": str(ctx.guild.id),
                "user_id":  str(member.id),
                "xp":       xp,
                "level":    level,
            }, "guild_id,user_id")
        except Exception as err:
            return await ctx.send(embed=embed(f"{icon('error')} Failed", str(err), color="error"))
        await ctx.send(embed=embed(
            f"{icon('ok')} XP Set",
            f"Set {member.mention}'s XP to **{xp:,}** (Level {level}).",
            color="success",
        ))

    @commands.command(name="resetxp")
    @commands.has_permissions(administrator=True)
    async def resetxp_prefix(self, ctx: commands.Context, member: discord.Member):
        """Reset a member's XP and level to zero.  !resetxp @user"""
        try:
            await self.bot.db._upsert("user_levels", {
                "guild_id": str(ctx.guild.id),
                "user_id":  str(member.id),
                "xp":       0,
                "level":    0,
            }, "guild_id,user_id")
        except Exception as err:
            return await ctx.send(embed=embed(f"{icon('error')} Failed", str(err), color="error"))
        await ctx.send(embed=embed(
            f"{icon('ok')} XP Reset",
            f"{member.mention}'s XP has been reset to **0**.",
            color="success",
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
