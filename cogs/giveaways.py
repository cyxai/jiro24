"""
cogs/giveaways.py — Giveaway system
07Dipper / Jiro • NixAI • by Blueey

Supabase table required:
  giveaways (
    id          BIGSERIAL PRIMARY KEY,
    guild_id    TEXT,
    channel_id  TEXT,
    message_id  TEXT,
    host_id     TEXT,
    prize       TEXT,
    winners     INT  DEFAULT 1,
    ends_at     TIMESTAMPTZ,
    ended       BOOLEAN DEFAULT false,
    created_at  TIMESTAMPTZ DEFAULT now()
  )

Commands
  !gstart <duration> <winners> <prize>
      e.g.  !gstart 1h 1 Nitro Classic
            !gstart 30m 3 Discord Server Boost
  !gend <message_id>     Force-end a giveaway early.
  !greroll <message_id>  Reroll a winner for an ended giveaway.
  !glist                 List active giveaways in this server.
"""

import asyncio
import random
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import icon
from utils.embeds import embed

GIVEAWAY_EMOJI = "🎉"


def _parse_duration(s: str) -> int | None:
    """Parse strings like '30m', '2h', '1d' into seconds. Returns None on failure."""
    match = re.fullmatch(r"(\d+)([smhd])", s.lower())
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    return val * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _fmt_delta(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    d, r    = divmod(seconds, 86400)
    h, r    = divmod(r, 3600)
    m, s    = divmod(r, 60)
    parts   = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)


class Giveaways(commands.Cog):
    """Giveaway management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tasks: dict[int, asyncio.Task] = {}  # message_id → task

    async def cog_load(self):
        """Resume any unfinished giveaways after a restart."""
        try:
            rows = await self.bot.db._get("giveaways", {
                "ended":   "eq.false",
                "order":   "ends_at.asc",
                "limit":   "50",
            })
            for row in rows:
                ends_at = datetime.fromisoformat(row["ends_at"])
                if ends_at.tzinfo is None:
                    ends_at = ends_at.replace(tzinfo=timezone.utc)
                delay = max((ends_at - datetime.now(timezone.utc)).total_seconds(), 0)
                msg_id = int(row["message_id"])
                self._tasks[msg_id] = asyncio.create_task(
                    self._end_giveaway_after(delay, row),
                    name=f"gw_{msg_id}",
                )
        except Exception as e:
            print(f"[Giveaways] Resume failed: {e}")

    # ── !gstart ───────────────────────────────────────────────────────────────

    @commands.command(name="gstart")
    @commands.has_permissions(manage_guild=True)
    async def gstart_prefix(self, ctx: commands.Context, duration: str, winners: int, *, prize: str):
        """Start a giveaway.  !gstart <duration> <winners> <prize>"""
        secs = _parse_duration(duration)
        if secs is None or secs < 10:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Duration",
                "Use formats like `30s`, `10m`, `2h`, `1d`. Minimum 10 seconds.",
                color="error",
            ))
        if winners < 1 or winners > 20:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Winners",
                "Winners must be between 1 and 20.", color="error",
            ))
        await self._start_giveaway(ctx.guild, ctx.channel, ctx.author, prize, secs, winners,
                                   send=ctx.send)

    @app_commands.command(name="gstart", description="Start a giveaway")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        duration="Duration e.g. 30m, 2h, 1d",
        winners="Number of winners (1-20)",
        prize="What you're giving away",
    )
    async def gstart_slash(self, interaction: discord.Interaction,
                           duration: str, winners: int, prize: str):
        secs = _parse_duration(duration)
        if secs is None or secs < 10:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Invalid Duration",
                "Use formats like `30s`, `10m`, `2h`, `1d`. Minimum 10 seconds.",
                color="error",
            ), ephemeral=True)
        if winners < 1 or winners > 20:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Invalid Winners",
                "Winners must be between 1 and 20.", color="error",
            ), ephemeral=True)
        await interaction.response.defer()
        await self._start_giveaway(interaction.guild, interaction.channel, interaction.user,
                                   prize, secs, winners,
                                   send=interaction.followup.send)

    async def _start_giveaway(self, guild, channel, host, prize, secs, winners, *, send):
        ends_at  = datetime.now(timezone.utc) + timedelta(seconds=secs)
        ends_ts  = int(ends_at.timestamp())

        gw_embed = embed(
            f"{GIVEAWAY_EMOJI} GIVEAWAY — {prize}",
            f"React with {GIVEAWAY_EMOJI} to enter!\n\n"
            f"**Ends:** <t:{ends_ts}:R>\n"
            f"**Winners:** {winners}\n"
            f"**Hosted by:** {host.mention}",
            color="mod",
        )
        gw_embed.set_footer(text=f"Ends at {ends_at.strftime('%Y-%m-%d %H:%M UTC')}")

        msg = await channel.send(embed=gw_embed)
        await msg.add_reaction(GIVEAWAY_EMOJI)

        # Persist to Supabase
        try:
            await self.bot.db._post("giveaways", {
                "guild_id":   str(guild.id),
                "channel_id": str(channel.id),
                "message_id": str(msg.id),
                "host_id":    str(host.id),
                "prize":      prize,
                "winners":    winners,
                "ends_at":    ends_at.isoformat(),
                "ended":      False,
            })
        except Exception as e:
            print(f"[Giveaways] DB save failed: {e}")

        row = {
            "guild_id": str(guild.id), "channel_id": str(channel.id),
            "message_id": str(msg.id), "prize": prize,
            "winners": winners, "ended": False,
        }
        self._tasks[msg.id] = asyncio.create_task(
            self._end_giveaway_after(secs, row),
            name=f"gw_{msg.id}",
        )

    # ── End logic ─────────────────────────────────────────────────────────────

    async def _end_giveaway_after(self, delay: float, row: dict):
        await asyncio.sleep(delay)
        await self._conclude(row)

    async def _conclude(self, row: dict):
        channel = self.bot.get_channel(int(row["channel_id"]))
        if channel is None:
            return
        try:
            msg = await channel.fetch_message(int(row["message_id"]))
        except (discord.NotFound, discord.Forbidden):
            return

        # Collect entrants
        reaction = discord.utils.get(msg.reactions, emoji=GIVEAWAY_EMOJI)
        entrants = []
        if reaction:
            async for user in reaction.users():
                if not user.bot:
                    entrants.append(user)

        n_winners = int(row.get("winners") or 1)
        if not entrants:
            result_desc = "No one entered. 😔"
            winner_text = "Nobody"
        else:
            picked      = random.sample(entrants, min(n_winners, len(entrants)))
            winner_text = ", ".join(w.mention for w in picked)
            result_desc = f"🎉 Congratulations {winner_text}!\nYou won **{row['prize']}**!"

        # Edit original message
        ended_embed = embed(
            f"🎊 GIVEAWAY ENDED — {row['prize']}",
            result_desc, color="success",
        )
        ended_embed.set_footer(text=f"Message ID: {row['message_id']}")
        try:
            await msg.edit(embed=ended_embed)
        except discord.HTTPException:
            pass

        await channel.send(
            f"🎉 **Giveaway ended!** Winner(s) of **{row['prize']}**: {winner_text}\n"
            f"*(Use `!greroll {row['message_id']}` to reroll)*"
        )

        # Mark ended in DB
        try:
            await self.bot.db._patch("giveaways", {"message_id": row["message_id"]}, {"ended": True})
        except Exception:
            pass

    # ── !gend ─────────────────────────────────────────────────────────────────

    @commands.command(name="gend")
    @commands.has_permissions(manage_guild=True)
    async def gend_prefix(self, ctx: commands.Context, message_id: int):
        """Force-end a giveaway early.  !gend <message_id>"""
        task = self._tasks.pop(message_id, None)
        if task:
            task.cancel()
        try:
            rows = await self.bot.db._get("giveaways", {
                "message_id": f"eq.{message_id}",
                "ended":      "eq.false",
            })
        except Exception:
            rows = []
        if not rows:
            return await ctx.send(embed=embed(
                f"{icon('error')} Not Found",
                f"No active giveaway found with message ID `{message_id}`.",
                color="error",
            ))
        await self._conclude(rows[0])
        await ctx.send(embed=embed(f"{icon('ok')} Giveaway Ended", "Ended early.", color="success"))

    # ── !greroll ──────────────────────────────────────────────────────────────

    @commands.command(name="greroll")
    @commands.has_permissions(manage_guild=True)
    async def greroll_prefix(self, ctx: commands.Context, message_id: int):
        """Reroll a winner for an ended giveaway.  !greroll <message_id>"""
        try:
            msg = await ctx.channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden):
            return await ctx.send(embed=embed(
                f"{icon('error')} Not Found",
                "Couldn't find that message in this channel.", color="error",
            ))
        reaction = discord.utils.get(msg.reactions, emoji=GIVEAWAY_EMOJI)
        entrants = []
        if reaction:
            async for user in reaction.users():
                if not user.bot:
                    entrants.append(user)
        if not entrants:
            return await ctx.send(embed=embed(
                f"{icon('error')} No Entrants", "There are no entrants to reroll from.", color="error",
            ))
        winner = random.choice(entrants)
        await ctx.send(embed=embed(
            f"🎉 Reroll Winner!",
            f"{winner.mention} is the new winner! Congratulations!",
            color="success",
        ))

    # ── !glist ────────────────────────────────────────────────────────────────

    @commands.command(name="glist")
    async def glist_prefix(self, ctx: commands.Context):
        """List active giveaways in this server."""
        try:
            rows = await self.bot.db._get("giveaways", {
                "guild_id": f"eq.{ctx.guild.id}",
                "ended":    "eq.false",
                "order":    "ends_at.asc",
                "limit":    "10",
            })
        except Exception:
            rows = []
        if not rows:
            return await ctx.send(embed=embed(
                f"{icon('info')} No Active Giveaways",
                "There are no active giveaways right now.", color="info",
            ))
        lines = []
        for row in rows:
            ends_at = datetime.fromisoformat(row["ends_at"])
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)
            remaining = (ends_at - datetime.now(timezone.utc)).total_seconds()
            lines.append(
                f"**{row['prize']}** — {_fmt_delta(remaining)} left "
                f"| {row['winners']} winner(s) | ID: `{row['message_id']}`"
            )
        await ctx.send(embed=embed(
            f"{GIVEAWAY_EMOJI} Active Giveaways ({len(rows)})",
            "\n".join(lines), color="mod",
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
