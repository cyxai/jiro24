"""
cogs/antiraid.py — Anti-raid mode + mention spam protection
07Dipper / Jiro • NixAI • by Blueey

Features
  • Anti-raid: auto-triggers when X joins happen within Y seconds,
    kicks/bans new accounts, locks all channels, and alerts the log channel.
    Manually toggled with !raid on/off.

  • Mention spam: mutes any user who pings more than N members in a single
    message (configurable per-guild in guild_configs).

Guild config keys used
  raid_mode           bool   — whether raid mode is currently active
  raid_join_threshold int    — joins in the window to trigger (default 8)
  raid_window_secs    int    — window in seconds (default 10)
  raid_action         str    — "kick" | "ban" (default "kick")
  mention_limit       int    — max mentions per message before mute (default 5)
  mention_mute_mins   int    — mute duration in minutes (default 10)
  log_channel         str    — channel ID for alerts

Commands  (all require Administrator)
  !raid on          Enable raid mode manually.
  !raid off         Disable raid mode and unlock channels.
  !raid status      Show current settings.
  !raidconfig ...   Adjust thresholds.
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import icon
from utils.embeds import embed

# Defaults
DEFAULT_THRESHOLD   = 8     # joins
DEFAULT_WINDOW      = 10    # seconds
DEFAULT_ACTION      = "kick"
DEFAULT_MENTION_CAP = 5
DEFAULT_MUTE_MINS   = 10


class AntiRaid(commands.Cog):
    """Anti-raid lockdown and mention-spam protection."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # { guild_id: deque of join datetimes }
        self._join_log: dict[int, deque] = {}
        # { guild_id: set of locked channel_ids }
        self._locked: dict[int, set] = {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _cfg(self, guild_id: int) -> dict:
        try:
            return await self.bot.db.get_config(guild_id)
        except Exception:
            return {}

    async def _log(self, guild: discord.Guild, e: discord.Embed):
        cfg        = await self._cfg(guild.id)
        log_ch_id  = cfg.get("log_channel")
        if not log_ch_id:
            return
        ch = guild.get_channel(int(log_ch_id))
        if ch:
            try:
                await ch.send(embed=e)
            except discord.HTTPException:
                pass

    async def _set_raid_mode(self, guild: discord.Guild, active: bool):
        await self.bot.db.set_config(guild.id, "raid_mode", active)

    # ══════════════════════════════════════════════════════════════════════════
    # Anti-raid join listener
    # ══════════════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        cfg   = await self._cfg(guild.id)

        # If already in raid mode — act immediately on every new join
        if self.bot.db._bool(cfg.get("raid_mode")):
            await self._raid_action(guild, member, cfg)
            return

        # Track joins in rolling window
        threshold = int(cfg.get("raid_join_threshold") or DEFAULT_THRESHOLD)
        window    = int(cfg.get("raid_window_secs")    or DEFAULT_WINDOW)
        now       = datetime.now(timezone.utc)
        q         = self._join_log.setdefault(guild.id, deque())
        q.append(now)
        # Prune old entries
        cutoff = now - timedelta(seconds=window)
        while q and q[0] < cutoff:
            q.popleft()

        if len(q) >= threshold:
            await self._trigger_raid(guild, cfg)

    async def _trigger_raid(self, guild: discord.Guild, cfg: dict):
        """Automatically activate raid mode and lock all text channels."""
        await self._set_raid_mode(guild, True)
        self._join_log.pop(guild.id, None)

        locked = self._locked.setdefault(guild.id, set())
        everyone = guild.default_role

        for ch in guild.text_channels:
            overwrite = ch.overwrites_for(everyone)
            if overwrite.send_messages is False:
                continue  # already locked
            try:
                await ch.set_permissions(everyone, send_messages=False,
                                         reason="[Jiro] Raid mode auto-triggered")
                locked.add(ch.id)
            except discord.Forbidden:
                pass

        alert = embed(
            f"🚨 {icon('warn')} RAID MODE ACTIVATED",
            f"Suspicious join spike detected. All channels locked.\n"
            f"Use `!raid off` to disable and unlock when safe.",
            color="error",
        )
        await self._log(guild, alert)

    async def _raid_action(self, guild: discord.Guild, member: discord.Member, cfg: dict):
        action = (cfg.get("raid_action") or DEFAULT_ACTION).lower()
        try:
            if action == "ban":
                await guild.ban(member, reason="[Jiro] Raid mode — auto-ban", delete_message_days=1)
            else:
                await guild.kick(member, reason="[Jiro] Raid mode — auto-kick")
        except discord.Forbidden:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # Mention spam listener
    # ══════════════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return  # don't act on mods

        # Count unique real member mentions (exclude bots)
        mentions = {m for m in message.mentions if not m.bot and m != message.author}
        if not mentions:
            return

        cfg   = await self._cfg(message.guild.id)
        limit = int(cfg.get("mention_limit") or DEFAULT_MENTION_CAP)
        if len(mentions) < limit:
            return

        # Mute via timeout
        mute_mins = int(cfg.get("mention_mute_mins") or DEFAULT_MUTE_MINS)
        until     = datetime.now(timezone.utc) + timedelta(minutes=mute_mins)
        try:
            await message.author.timeout(until, reason=f"[Jiro] Mention spam ({len(mentions)} pings)")
            await message.delete()
        except discord.Forbidden:
            pass

        warn_embed = embed(
            f"{icon('mute')} Mention Spam",
            f"{message.author.mention} was muted for **{mute_mins}m** for mass-pinging "
            f"**{len(mentions)}** members.",
            color="mod",
        )
        try:
            await message.channel.send(embed=warn_embed, delete_after=10)
        except discord.HTTPException:
            pass
        await self._log(message.guild, warn_embed)

    # ══════════════════════════════════════════════════════════════════════════
    # !raid commands
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="raid", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def raid_group(self, ctx: commands.Context):
        """Raid mode controls.  !raid on | off | status"""
        await ctx.send(embed=embed(
            f"{icon('warn')} Raid Commands",
            "`!raid on` — activate raid mode\n"
            "`!raid off` — deactivate and unlock channels\n"
            "`!raid status` — current settings",
            color="info",
        ))

    @raid_group.command(name="on")
    @commands.has_permissions(administrator=True)
    async def raid_on(self, ctx: commands.Context):
        """Manually activate raid mode."""
        cfg = await self._cfg(ctx.guild.id)
        await self._trigger_raid(ctx.guild, cfg)
        await ctx.send(embed=embed(
            f"🚨 Raid Mode ON",
            "All channels locked. New joins will be kicked/banned until disabled.",
            color="error",
        ))

    @raid_group.command(name="off")
    @commands.has_permissions(administrator=True)
    async def raid_off(self, ctx: commands.Context):
        """Deactivate raid mode and restore channel permissions."""
        await self._set_raid_mode(ctx.guild, False)
        locked = self._locked.pop(ctx.guild.id, set())
        everyone = ctx.guild.default_role
        restored = 0
        for ch_id in locked:
            ch = ctx.guild.get_channel(ch_id)
            if ch:
                try:
                    await ch.set_permissions(everyone, send_messages=None,
                                             reason="[Jiro] Raid mode disabled")
                    restored += 1
                except discord.Forbidden:
                    pass
        await ctx.send(embed=embed(
            f"{icon('ok')} Raid Mode OFF",
            f"Raid mode disabled. {restored} channel(s) unlocked.",
            color="success",
        ))

    @raid_group.command(name="status")
    @commands.has_permissions(administrator=True)
    async def raid_status(self, ctx: commands.Context):
        """Show current anti-raid settings."""
        cfg       = await self._cfg(ctx.guild.id)
        active    = self.bot.db._bool(cfg.get("raid_mode"))
        threshold = cfg.get("raid_join_threshold", DEFAULT_THRESHOLD)
        window    = cfg.get("raid_window_secs",    DEFAULT_WINDOW)
        action    = cfg.get("raid_action",         DEFAULT_ACTION)
        m_limit   = cfg.get("mention_limit",       DEFAULT_MENTION_CAP)
        m_mute    = cfg.get("mention_mute_mins",   DEFAULT_MUTE_MINS)

        e = embed(
            f"{icon('warn')} Anti-Raid Status",
            f"Raid mode is currently **{'🔴 ACTIVE' if active else '🟢 OFF'}**.",
            color="error" if active else "info",
        )
        e.add_field(name="Join Threshold", value=f"{threshold} joins / {window}s", inline=True)
        e.add_field(name="Action",         value=action.capitalize(),              inline=True)
        e.add_field(name="Mention Limit",  value=f"{m_limit} pings → {m_mute}m mute", inline=True)
        await ctx.send(embed=e)

    # ── !raidconfig ───────────────────────────────────────────────────────────

    @commands.command(name="raidconfig")
    @commands.has_permissions(administrator=True)
    async def raidconfig(self, ctx: commands.Context, key: str, value: str):
        """
        Adjust anti-raid settings.
        Keys: threshold, window, action, mention_limit, mention_mute_mins
        Example: !raidconfig threshold 10
        """
        key_map = {
            "threshold":         "raid_join_threshold",
            "window":            "raid_window_secs",
            "action":            "raid_action",
            "mention_limit":     "mention_limit",
            "mention_mute_mins": "mention_mute_mins",
        }
        cfg_key = key_map.get(key.lower())
        if not cfg_key:
            return await ctx.send(embed=embed(
                f"{icon('error')} Unknown Key",
                f"Valid keys: {', '.join(key_map)}", color="error",
            ))
        # Validate action
        if cfg_key == "raid_action" and value.lower() not in ("kick", "ban"):
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Action", "Use `kick` or `ban`.", color="error",
            ))
        # Coerce numerics
        stored = value if cfg_key == "raid_action" else int(value)
        await self.bot.db.set_config(ctx.guild.id, cfg_key, stored)
        await ctx.send(embed=embed(
            f"{icon('ok')} Config Updated",
            f"`{key}` set to `{value}`.", color="success",
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiRaid(bot))
