"""
cogs/afk_report.py — AFK + cross-server reports with Jiro AI triage
07Dipper / Jiro • NixAI • by Blueey

Flow when a report arrives
  1. Report embed posted in the owner's report channel instantly.
  2. Reporter gets an immediate "received" confirmation.
  3. Background task: Jiro posts 8-10 visible "thinking" messages in the
     report channel (staff/owner only) with realistic delays.
  4. Jiro sends ONE final response directly to the reporter's DMs.
     The reporter never sees the thoughts.

Commands
  !afk [reason]     Mark yourself AFK. Auto-clears on next message.
  !afklist          List all currently AFK members in this server.
  !report <msg>     Submit a report. Jiro will triage it and DM you back.
  !userreports      (Owner only) Browse / clear stored reports.
"""

import asyncio
import json
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import icon
from utils.embeds import embed

# ── Config ────────────────────────────────────────────────────────────────────
REPORT_CHANNEL_ID = 1477791888734949476

_THINK_SYSTEM = """\
You are Jiro, a friendly and professional Discord bot built by NixAI.
A user just submitted a report or support request. Work through it carefully.

Return ONLY valid JSON — no markdown fences, no extra text — in exactly this shape:
{
  "thoughts": [
    "step 1 (1-2 sentences of internal reasoning)",
    "step 2",
    ... exactly 10 steps total
  ],
  "response": "The final warm, professional customer-service reply you will DM directly to the user. 2-4 sentences. Acknowledge their issue, assure them the developer has been notified, and set a realistic expectation."
}

The thoughts are internal notes shown only to the developer in the report channel.
The response is what the user will receive in their DMs — make it human and reassuring."""


class AfkReport(commands.Cog):
    """AFK tracking, cross-server reports, and Jiro AI triage."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # { user_id: {"message": str|None, "since": datetime} }
        self._afk: dict[int, dict] = {}

    # ══════════════════════════════════════════════════════════════════════════
    # AFK
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="afk")
    async def afk_prefix(self, ctx: commands.Context, *, message: str = None):
        """Mark yourself AFK.  !afk [reason]"""
        await self._set_afk(ctx.author, message, send=ctx.send)

    @app_commands.command(name="afk", description="Mark yourself as AFK with an optional reason")
    @app_commands.describe(message="Why you're going AFK (optional)")
    async def afk_slash(self, interaction: discord.Interaction, message: str = None):
        await self._set_afk(
            interaction.user, message,
            send=lambda **kw: interaction.response.send_message(**kw),
        )

    @commands.command(name="afklist")
    async def afklist_prefix(self, ctx: commands.Context):
        """Show all currently AFK members in this server."""
        await self._show_afklist(ctx.guild, send=ctx.send)

    @app_commands.command(name="afklist", description="Show all currently AFK members in this server")
    async def afklist_slash(self, interaction: discord.Interaction):
        await self._show_afklist(
            interaction.guild,
            send=lambda **kw: interaction.response.send_message(**kw),
        )

    async def _set_afk(self, user, message, *, send):
        self._afk[user.id] = {"message": message, "since": datetime.now(timezone.utc)}
        reason = f"*{message}*" if message else "No reason given."
        await send(embed=embed(
            f"{icon('afk')} You're now AFK",
            f"{user.mention} is now AFK.\n**Reason:** {reason}",
            color="info",
        ))

    async def _show_afklist(self, guild: discord.Guild | None, *, send):
        if not guild:
            return await send(embed=embed(f"{icon('error')} Server only", color="error"))
        lines = []
        for uid, data in self._afk.items():
            member = guild.get_member(uid)
            if not member:
                continue
            elapsed = datetime.now(timezone.utc) - data["since"]
            mins    = int(elapsed.total_seconds() // 60)
            t       = f"{mins}m ago" if mins else "just now"
            reason  = data["message"] or "No reason"
            lines.append(f"**{member.display_name}** — {t} | *{reason}*")
        if not lines:
            return await send(embed=embed(
                f"{icon('afk')} AFK List", "Nobody is currently AFK in this server.", color="info",
            ))
        await send(embed=embed(
            f"{icon('afk')} AFK Members ({len(lines)})", "\n".join(lines), color="info",
        ))

    # ══════════════════════════════════════════════════════════════════════════
    # Report
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="report")
    async def report_prefix(self, ctx: commands.Context, *, message: str = None):
        """Submit a report. Jiro will triage it and DM you back.  !report <message>"""
        if not message:
            return await ctx.send(embed=embed(
                f"{icon('error')} Missing Message",
                "Please include a message.\n**Usage:** `!report <your message>`",
                color="error",
            ))
        await self._send_report(
            reporter=ctx.author, guild=ctx.guild,
            channel=ctx.channel, message=message,
            send=ctx.send,
        )

    @app_commands.command(name="report", description="Submit a report or feedback — Jiro will DM you back")
    @app_commands.describe(message="Describe your issue or report")
    async def report_slash(self, interaction: discord.Interaction, message: str):
        await self._send_report(
            reporter=interaction.user, guild=interaction.guild,
            channel=interaction.channel, message=message,
            send=lambda **kw: interaction.response.send_message(**kw),
        )

    async def _send_report(self, *, reporter, guild, channel, message, send):
        # Resolve destination channel
        dest = self.bot.get_channel(REPORT_CHANNEL_ID)
        if dest is None:
            try:
                dest = await self.bot.fetch_channel(REPORT_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden):
                pass

        if dest is None:
            return await send(embed=embed(
                f"{icon('error')} Report Failed",
                "Couldn't reach the report channel. Please contact the bot owner directly.",
                color="error",
            ))

        # Build and post the report embed
        guild_name = guild.name if guild else "DM / Unknown"
        guild_id   = str(guild.id) if guild else "N/A"
        ch_name    = f"#{channel.name}" if hasattr(channel, "name") else "Unknown"
        ch_id      = str(channel.id) if channel else "N/A"
        ts         = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        report_embed = embed(f"{icon('report')} New Report", f"> {message[:1800]}", color="warn")
        report_embed.add_field(
            name=f"{icon('user')} Reporter",
            value=f"{reporter.mention}\n`{reporter}` (ID: `{reporter.id}`)", inline=True)
        report_embed.add_field(
            name=f"{icon('server')} Server",
            value=f"**{guild_name}**\nID: `{guild_id}`", inline=True)
        report_embed.add_field(
            name=f"{icon('info')} Channel",
            value=f"{ch_name}\nID: `{ch_id}`", inline=True)
        report_embed.add_field(name=f"{icon('time')} Timestamp", value=ts, inline=False)
        report_embed.set_thumbnail(url=reporter.display_avatar.url)

        try:
            await dest.send(embed=report_embed)
        except discord.Forbidden:
            return await send(embed=embed(
                f"{icon('error')} Report Failed",
                "The bot lacks permission to post in the report channel.",
                color="error",
            ))

        # Confirm to reporter right away — don't make them wait
        await send(embed=embed(
            f"{icon('ok')} Report Received",
            "Your report has been received! Jiro is looking into it and will DM you shortly.",
            color="success",
        ))

        # Fire off the thinking sequence as a background task
        asyncio.create_task(
            self._jiro_think(dest, reporter, message),
            name=f"jiro_think_{reporter.id}",
        )

    # ── Jiro triage background task ───────────────────────────────────────────
    async def _jiro_think(
        self,
        dest: discord.TextChannel,
        reporter: discord.User | discord.Member,
        report_message: str,
    ):
        """
        Visible to staff/owner in the report channel only:
          • 10 sequential "thinking" plain-text messages with realistic delays.
          • A final clean embed labeled [Jiro's Response].

        Visible to the reporter only:
          • A single DM with the final response. They never see the thoughts.
        """
        await asyncio.sleep(2)  # Let the report embed settle

        # ── Call Groq ─────────────────────────────────────────────────────
        raw = await self.bot.ask_groq(
            f"Report submitted by a user:\n\n{report_message}",
            system=_THINK_SYSTEM,
            model="llama-3.3-70b-versatile",
        )

        # ── Parse JSON response ───────────────────────────────────────────
        thoughts: list[str] = []
        final_response      = ""
        try:
            clean         = re.sub(r"```(?:json)?|```", "", raw).strip()
            data          = json.loads(clean)
            thoughts      = data.get("thoughts") or []
            final_response = data.get("response", "").strip()
        except Exception:
            pass

        # Fallback if parsing fails or Groq returns garbage
        if not thoughts:
            thoughts = [
                "Hmm, let me read this report carefully...",
                "Okay, the user is reporting an issue with the bot.",
                "I need to understand what exactly went wrong here.",
                "Let me think about what could cause this behaviour...",
                "This could be a bug, a config issue, or a missing feature.",
                "I should make sure the developer sees this as soon as possible.",
                "The issue seems clear enough to act on.",
                "I want my response to be reassuring without over-promising.",
                "The developer will be able to investigate once they see this.",
                "Alright, I have everything I need to respond properly.",
            ]
        if not final_response:
            final_response = (
                "Hey there! I've received your report and it's been forwarded directly to the developer. "
                "They'll look into it as soon as possible. "
                "Thank you for taking the time to let us know — your feedback genuinely helps make the bot better!"
            )

        # ── Post thinking steps in the report channel ─────────────────────
        # Each step looks like Jiro is typing out loud.
        # Delays are randomised slightly to feel natural.
        think_delays = [1.8, 1.5, 2.0, 1.6, 1.9, 1.4, 2.1, 1.7, 1.5, 1.8]
        for i, thought in enumerate(thoughts[:10]):
            try:
                await dest.send(f"💭 {thought}")
            except discord.HTTPException:
                pass
            delay = think_delays[i] if i < len(think_delays) else 1.8
            await asyncio.sleep(delay)

        # ── Post final labeled response in report channel (for staff record) ─
        response_embed = embed(
            f"{icon('ok')} Jiro's Response  —  sent to reporter's DM",
            final_response,
            color="success",
        )
        response_embed.set_footer(text=f"Sent to {reporter} ({reporter.id})")
        try:
            await dest.send(embed=response_embed)
        except discord.HTTPException:
            pass

        # ── DM the reporter — this is the ONLY thing they receive ────────
        dm_embed = embed(
            f"{icon('report')} Update on your report",
            final_response,
            color="info",
        )
        dm_embed.set_footer(text="Jiro • NixAI — reply here if you have more details")
        try:
            await reporter.send(embed=dm_embed)
        except discord.Forbidden:
            # User has DMs closed — post a gentle notice in the report channel
            try:
                await dest.send(
                    f"⚠️ Couldn't DM {reporter.mention} (`{reporter.id}`) — their DMs are closed."
                )
            except discord.HTTPException:
                pass

    # ══════════════════════════════════════════════════════════════════════════
    # User Reports (owner utility)
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="userreports")
    @commands.is_owner()
    async def userreports_prefix(self, ctx: commands.Context, *, query: str = None):
        """
        Owner only — jump to the report channel and optionally search messages.
        !userreports              → link to the channel
        !userreports <keyword>    → search last 100 messages for that keyword
        !userreports clear        → delete the last 50 non-pinned messages
        """
        dest = self.bot.get_channel(REPORT_CHANNEL_ID)
        if dest is None:
            try:
                dest = await self.bot.fetch_channel(REPORT_CHANNEL_ID)
            except Exception:
                dest = None
        if dest is None:
            return await ctx.send(embed=embed(
                f"{icon('error')} Channel Not Found",
                f"Could not resolve report channel `{REPORT_CHANNEL_ID}`.",
                color="error",
            ))

        # ── Clear ─────────────────────────────────────────────────────────
        if query and query.lower() == "clear":
            deleted = 0
            async for msg in dest.history(limit=50):
                if not msg.pinned:
                    try:
                        await msg.delete()
                        deleted += 1
                        await asyncio.sleep(0.4)
                    except discord.HTTPException:
                        pass
            return await ctx.send(embed=embed(
                f"{icon('ok')} Cleared",
                f"Deleted **{deleted}** messages from the report channel.",
                color="success",
            ))

        # ── Search ────────────────────────────────────────────────────────
        if query:
            kw      = query.lower()
            matches = []
            async for msg in dest.history(limit=100):
                # Search inside embed descriptions/fields too
                text = msg.content
                for em in msg.embeds:
                    text += f" {em.description or ''} "
                    for f in em.fields:
                        text += f" {f.value} "
                if kw in text.lower():
                    ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                    matches.append(f"`{ts}` — [Jump]({msg.jump_url})")
                if len(matches) >= 10:
                    break
            if not matches:
                return await ctx.send(embed=embed(
                    f"{icon('info')} No Results",
                    f"No reports matched `{query}` in the last 100 messages.",
                    color="info",
                ))
            return await ctx.send(embed=embed(
                f"{icon('report')} Search: `{query}`",
                "\n".join(matches),
                color="info",
            ))

        # ── Default: link to channel ──────────────────────────────────────
        await ctx.send(embed=embed(
            f"{icon('report')} Report Channel",
            f"View all reports here: {dest.mention}\n\n"
            f"**Subcommands:**\n"
            f"`!userreports <keyword>` — search\n"
            f"`!userreports clear` — delete last 50 messages",
            color="info",
        ))

    # ══════════════════════════════════════════════════════════════════════════
    # on_message — AFK intercept
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    async def _safe_reply(message: discord.Message, **kwargs):
        """Reply with fallback to channel.send on 400 (stale message reference)."""
        try:
            await message.reply(**kwargs)
        except discord.HTTPException as exc:
            if exc.status == 400:
                try:
                    await message.channel.send(**kwargs)
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # 1. Author is AFK and just spoke — lift their status
        if message.author.id in self._afk:
            data    = self._afk.pop(message.author.id)
            elapsed = datetime.now(timezone.utc) - data["since"]
            mins    = int(elapsed.total_seconds() // 60)
            t       = f"{mins} minute{'s' if mins != 1 else ''}" if mins else "less than a minute"
            await self._safe_reply(message, embed=embed(
                f"{icon('afk')} Welcome back!",
                f"Your AFK status has been removed. You were away for **{t}**.",
                color="success",
            ))
            return

        # 2. Someone pinged an AFK user — notify the sender
        if not message.mentions:
            return
        notices = []
        for member in message.mentions:
            if member.id not in self._afk:
                continue
            data    = self._afk[member.id]
            reason  = data["message"] or "No reason given."
            elapsed = datetime.now(timezone.utc) - data["since"]
            mins    = int(elapsed.total_seconds() // 60)
            t       = f"{mins} minute{'s' if mins != 1 else ''} ago" if mins else "just now"
            notices.append(f"**{member.display_name}** is AFK ({t}) — *{reason}*")
        if notices:
            await self._safe_reply(message, embed=embed(
                f"{icon('afk')} AFK Notice", "\n".join(notices), color="warn",
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(AfkReport(bot))
