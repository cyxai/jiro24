"""
cogs/reminders.py — Persistent reminder system
07Dipper / Jiro • NixAI • by Blueey

Supabase table required:
  reminders (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT,
    channel_id  TEXT,
    message     TEXT,
    remind_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT now()
  )

Commands
  !remind <duration> <message>    Set a reminder.
      e.g.  !remind 2h check the oven
            !remind 30m daily standup
  !reminders                      List your pending reminders.
  !delreminder <id>               Cancel a reminder by its ID.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import icon
from utils.embeds import embed


def _parse_duration(s: str) -> int | None:
    match = re.fullmatch(r"(\d+)([smhd])", s.lower())
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    return val * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _fmt_delta(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)


class Reminders(commands.Cog):
    """Set, list, and cancel personal reminders."""

    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self._tasks: dict[int, asyncio.Task] = {}  # reminder_id → task

    async def cog_load(self):
        """Resume pending reminders after restart."""
        try:
            now  = datetime.now(timezone.utc).isoformat()
            rows = await self.bot.db._get("reminders", {
                "remind_at": f"gt.{now}",
                "order":     "remind_at.asc",
                "limit":     "200",
            })
            for row in rows:
                await self._schedule(row)
        except Exception as e:
            print(f"[Reminders] Resume failed: {e}")

    async def _schedule(self, row: dict):
        remind_at = datetime.fromisoformat(row["remind_at"])
        if remind_at.tzinfo is None:
            remind_at = remind_at.replace(tzinfo=timezone.utc)
        delay = max((remind_at - datetime.now(timezone.utc)).total_seconds(), 0)
        rid   = int(row["id"])
        task  = asyncio.create_task(
            self._fire(delay, row), name=f"reminder_{rid}",
        )
        self._tasks[rid] = task

    async def _fire(self, delay: float, row: dict):
        await asyncio.sleep(delay)
        channel = self.bot.get_channel(int(row["channel_id"]))
        user_id = int(row["user_id"])

        rem_embed = embed(
            f"{icon('time')} Reminder!",
            row["message"],
            color="info",
        )
        sent = False
        if channel:
            try:
                user = await self.bot.fetch_user(user_id)
                await channel.send(content=user.mention, embed=rem_embed)
                sent = True
            except discord.HTTPException:
                pass
        if not sent:
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(embed=rem_embed)
            except discord.HTTPException:
                pass

        # Clean up DB
        try:
            await self.bot.db._delete("reminders", {"id": str(row["id"])})
        except Exception:
            pass
        self._tasks.pop(int(row["id"]), None)

    # ── !remind ───────────────────────────────────────────────────────────────

    @commands.command(name="remind", aliases=["reminder"])
    async def remind_prefix(self, ctx: commands.Context, duration: str, *, message: str):
        """Set a reminder.  !remind <duration> <message>"""
        secs = _parse_duration(duration)
        if secs is None or secs < 10:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Duration",
                "Use formats like `30s`, `10m`, `2h`, `1d`. Minimum 10 seconds.",
                color="error",
            ))
        await self._create_reminder(ctx.author, ctx.channel, message, secs, send=ctx.send)

    @app_commands.command(name="remind", description="Set a personal reminder")
    @app_commands.describe(duration="How long until the reminder (e.g. 30m, 2h)", message="What to remind you about")
    async def remind_slash(self, interaction: discord.Interaction, duration: str, message: str):
        secs = _parse_duration(duration)
        if secs is None or secs < 10:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Invalid Duration",
                "Use formats like `30s`, `10m`, `2h`, `1d`. Minimum 10 seconds.",
                color="error",
            ), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self._create_reminder(interaction.user, interaction.channel, message, secs,
                                    send=interaction.followup.send)

    async def _create_reminder(self, user, channel, message, secs, *, send):
        remind_at = datetime.now(timezone.utc) + timedelta(seconds=secs)
        ends_ts   = int(remind_at.timestamp())
        try:
            rows = await self.bot.db._post("reminders", {
                "user_id":    str(user.id),
                "channel_id": str(channel.id),
                "message":    message[:500],
                "remind_at":  remind_at.isoformat(),
            })
            row = rows[0] if rows else None
        except Exception as e:
            return await send(embed=embed(
                f"{icon('error')} Failed", f"Could not save reminder: {e}", color="error",
            ))

        if row:
            await self._schedule(row)

        await send(embed=embed(
            f"{icon('ok')} Reminder Set",
            f"I'll remind you <t:{ends_ts}:R>.\n> *{message[:200]}*",
            color="success",
        ))

    # ── !reminders ────────────────────────────────────────────────────────────

    @commands.command(name="reminders")
    async def reminders_prefix(self, ctx: commands.Context):
        """List your pending reminders."""
        await self._list_reminders(ctx.author, send=ctx.send)

    @app_commands.command(name="reminders", description="List your pending reminders")
    async def reminders_slash(self, interaction: discord.Interaction):
        await self._list_reminders(
            interaction.user,
            send=lambda **kw: interaction.response.send_message(**kw, ephemeral=True),
        )

    async def _list_reminders(self, user, *, send):
        try:
            rows = await self.bot.db._get("reminders", {
                "user_id": f"eq.{user.id}",
                "order":   "remind_at.asc",
                "limit":   "10",
            })
        except Exception:
            rows = []
        if not rows:
            return await send(embed=embed(
                f"{icon('time')} Your Reminders", "You have no pending reminders.", color="info",
            ))
        lines = []
        for row in rows:
            remind_at = datetime.fromisoformat(row["remind_at"])
            if remind_at.tzinfo is None:
                remind_at = remind_at.replace(tzinfo=timezone.utc)
            remaining = (remind_at - datetime.now(timezone.utc)).total_seconds()
            short_msg = row["message"][:60] + ("..." if len(row["message"]) > 60 else "")
            lines.append(f"`ID {row['id']}` — {_fmt_delta(remaining)} — *{short_msg}*")
        await send(embed=embed(
            f"{icon('time')} Your Reminders ({len(rows)})", "\n".join(lines), color="info",
        ))

    # ── !delreminder ──────────────────────────────────────────────────────────

    @commands.command(name="delreminder", aliases=["cancelreminder"])
    async def delreminder_prefix(self, ctx: commands.Context, reminder_id: int):
        """Cancel a reminder.  !delreminder <id>"""
        try:
            rows = await self.bot.db._get("reminders", {
                "id":      f"eq.{reminder_id}",
                "user_id": f"eq.{ctx.author.id}",
            })
        except Exception:
            rows = []
        if not rows:
            return await ctx.send(embed=embed(
                f"{icon('error')} Not Found",
                f"No reminder with ID `{reminder_id}` found for you.", color="error",
            ))
        task = self._tasks.pop(reminder_id, None)
        if task:
            task.cancel()
        try:
            await self.bot.db._delete("reminders", {"id": str(reminder_id)})
        except Exception:
            pass
        await ctx.send(embed=embed(
            f"{icon('ok')} Reminder Cancelled",
            f"Reminder `{reminder_id}` has been deleted.", color="success",
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))
