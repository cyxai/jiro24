"""
cogs/logs.py — Comprehensive event logging for Jiro
Logs to Discord channel AND Supabase for dashboard visibility.

Covers:
  • Message deletes (individual + purge batches)
  • Message edits
  • Member joins / leaves
  • Member bans / unbans / kicks / timeouts
  • Nickname changes
  • Role changes
  • AutoMod actions
  • Bot actions (purge, giveaway, welcome, level-up, etc.)
  • Anti-raid events
  • Giveaway actions
  • Moderation commands

Excludes: AI cog commands (intentionally not logged to dashboard)
"""

import asyncio
import uuid
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import embed
from utils.config import icon


# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE HELPER — write to any log table safely
# ─────────────────────────────────────────────────────────────────────────────

async def _sb_insert(bot, table: str, data: dict):
    """Fire-and-forget Supabase insert. Silently swallows errors."""
    try:
        bot.supabase.table(table).insert(data).execute()
    except Exception as e:
        # Never let a logging failure crash anything
        print(f"[LOGS] Supabase insert failed ({table}): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# LOGS COG
# ─────────────────────────────────────────────────────────────────────────────

class Logs(commands.Cog):
    """Audit log management and comprehensive event logging."""

    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────────────────
    # INTERNAL: send embed to configured log channel
    # ─────────────────────────────────────────────────────────

    async def send_to_log(self, guild: discord.Guild, embed_obj: discord.Embed):
        config = await self.bot.db.get_config(guild.id)
        ch_id = config.get("log_channel_id")
        if ch_id:
            ch = guild.get_channel(int(ch_id))
            if ch:
                try:
                    await ch.send(embed=embed_obj)
                except discord.HTTPException:
                    pass

    # ─────────────────────────────────────────────────────────
    # SLASH / PREFIX COMMANDS
    # ─────────────────────────────────────────────────────────

    @commands.command(name="setlogchannel")
    @commands.has_permissions(administrator=True)
    async def set_log_channel_prefix(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await self.bot.db.set_config(ctx.guild.id, "log_channel_id", channel.id)
        await ctx.send(embed=embed(f"{icon('ok')} Log channel set to {channel.mention}", color="success"))

    @app_commands.command(name="setlogchannel", description="Set the mod-log channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_log_channel_slash(self, interaction: discord.Interaction,
                                    channel: discord.TextChannel = None):
        channel = channel or interaction.channel
        await self.bot.db.set_config(interaction.guild.id, "log_channel_id", channel.id)
        await interaction.response.send_message(
            embed=embed(f"{icon('ok')} Log channel set to {channel.mention}", color="success"))

    @commands.command(name="modlogs")
    @commands.has_permissions(manage_messages=True)
    async def modlogs_prefix(self, ctx, limit: int = 10):
        logs = await self.bot.db.get_logs(ctx.guild.id, limit=limit)
        if not logs:
            return await ctx.send(embed=embed("No mod logs found.", color="info"))
        e = embed(f"{icon('log')} Recent Mod Logs (last {len(logs)})", color="log")
        for log in logs:
            mod    = ctx.guild.get_member(int(log["mod_id"]))
            target = ctx.guild.get_member(int(log["target_id"]))
            e.add_field(
                name=f"[{log['created_at'][:10]}] {log['action']}",
                value=(f"**Mod:** {mod.mention if mod else log['mod_id']} "
                       f"→ **Target:** {target.mention if target else log['target_id']}\n"
                       f"**Reason:** {log['reason']}"),
                inline=False,
            )
        await ctx.send(embed=e)

    @app_commands.command(name="modlogs", description="View recent mod actions")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def modlogs_slash(self, interaction: discord.Interaction, limit: int = 10):
        logs = await self.bot.db.get_logs(interaction.guild.id, limit=limit)
        if not logs:
            return await interaction.response.send_message(embed=embed("No mod logs found.", color="info"))
        e = embed(f"{icon('log')} Recent Mod Logs (last {len(logs)})", color="log")
        for log in logs:
            e.add_field(
                name=f"[{log['created_at'][:10]}] {log['action']}",
                value=f"Mod: `{log['mod_id']}` → Target: `{log['target_id']}`\nReason: {log['reason']}",
                inline=False,
            )
        await interaction.response.send_message(embed=e)

    @commands.command(name="clearlogs")
    @commands.has_permissions(administrator=True)
    async def clearlogs_prefix(self, ctx):
        await self.bot.db.clear_logs(ctx.guild.id)
        await ctx.send(embed=embed(f"{icon('ok')} All mod logs cleared for this server.", color="success"))

    @app_commands.command(name="clearlogs", description="Clear all mod logs for this server (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def clearlogs_slash(self, interaction: discord.Interaction):
        await self.bot.db.clear_logs(interaction.guild.id)
        await interaction.response.send_message(
            embed=embed(f"{icon('ok')} All mod logs cleared for this server.", color="success"))

    # ─────────────────────────────────────────────────────────
    # EVENT: Message Deleted (single)
    # ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Discord embed log
        e = embed(f"{icon('log_msg_del')} Message Deleted", color="warn")
        e.add_field(name="Author",  value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
        e.add_field(name="Channel", value=message.channel.mention,                             inline=True)
        e.add_field(name="Content", value=message.content[:1000] or "*[no text content]*",     inline=False)
        if message.attachments:
            e.add_field(name="Attachments",
                        value="\n".join(a.filename for a in message.attachments), inline=False)
        e.set_footer(text=f"Message ID: {message.id}")
        await self.send_to_log(message.guild, e)

        # Supabase log
        await _sb_insert(self.bot, "message_logs", {
            "guild_id":     str(message.guild.id),
            "channel_id":   str(message.channel.id),
            "channel_name": message.channel.name,
            "author_id":    str(message.author.id),
            "author_name":  str(message.author),
            "message_id":   str(message.id),
            "content":      message.content[:4000] or "",
            "event_type":   "deleted",
        })

    # ─────────────────────────────────────────────────────────
    # EVENT: Bulk Message Delete (purge)
    # ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages or not messages[0].guild:
            return

        guild   = messages[0].guild
        channel = messages[0].channel
        batch   = str(uuid.uuid4())
        count   = len(messages)

        # Try to get executor from audit log
        executor_id   = None
        executor_name = None
        try:
            await asyncio.sleep(0.5)  # give Discord time to write the audit log
            async for entry in guild.audit_logs(action=discord.AuditLogAction.message_bulk_delete, limit=3):
                if abs((entry.created_at.replace(tzinfo=timezone.utc) -
                        datetime.now(timezone.utc)).total_seconds()) < 10:
                    executor_id   = str(entry.user.id)
                    executor_name = str(entry.user)
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Discord embed log
        e = embed(f"{icon('purge')} Bulk Delete / Purge", color="warn")
        e.add_field(name="Channel",   value=channel.mention, inline=True)
        e.add_field(name="Messages",  value=str(count),      inline=True)
        if executor_id:
            e.add_field(name="Executor", value=f"<@{executor_id}>", inline=True)
        content_preview = "\n".join(
            f"**{m.author}:** {m.content[:80]}" for m in messages[:10] if not m.author.bot
        )
        if content_preview:
            e.add_field(name="Preview (first 10)", value=content_preview[:1024], inline=False)
        await self.send_to_log(guild, e)

        # Supabase log — one row per message
        rows = []
        for m in messages:
            if m.author.bot:
                continue
            rows.append({
                "guild_id":      str(guild.id),
                "channel_id":    str(channel.id),
                "channel_name":  channel.name,
                "author_id":     str(m.author.id),
                "author_name":   str(m.author),
                "message_id":    str(m.id),
                "content":       m.content[:4000] or "",
                "event_type":    "purged",
                "purge_batch":   batch,
                "purge_count":   count,
                "executor_id":   executor_id,
                "executor_name": executor_name,
            })

        for row in rows:
            await _sb_insert(self.bot, "message_logs", row)

        # Also log as a bot_action
        await _sb_insert(self.bot, "bot_actions", {
            "guild_id":     str(guild.id),
            "channel_id":   str(channel.id),
            "channel_name": channel.name,
            "action":       "purge",
            "actor_id":     executor_id,
            "actor_name":   executor_name,
            "details":      {"count": count, "batch": batch},
        })

    # ─────────────────────────────────────────────────────────
    # EVENT: Message Edited
    # ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return

        e = embed(f"{icon('log_msg_edit')} Message Edited", color="info")
        e.add_field(name="Author",  value=f"{before.author.mention} (`{before.author.id}`)", inline=True)
        e.add_field(name="Channel", value=before.channel.mention,                            inline=True)
        e.add_field(name="Before",  value=before.content[:500] or "*empty*", inline=False)
        e.add_field(name="After",   value=after.content[:500]  or "*empty*", inline=False)
        e.set_footer(text=f"Message ID: {before.id}")
        await self.send_to_log(before.guild, e)

        await _sb_insert(self.bot, "message_logs", {
            "guild_id":       str(before.guild.id),
            "channel_id":     str(before.channel.id),
            "channel_name":   before.channel.name,
            "author_id":      str(before.author.id),
            "author_name":    str(before.author),
            "message_id":     str(before.id),
            "content":        after.content[:4000],
            "before_content": before.content[:4000],
            "event_type":     "edited",
        })

    # ─────────────────────────────────────────────────────────
    # EVENT: Member Join
    # ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        account_age = (datetime.now(timezone.utc) - member.created_at.replace(tzinfo=timezone.utc)).days

        e = embed(f"{icon('log_join')} Member Joined", color="success")
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="User",            value=f"{member.mention} (`{member.id}`)", inline=True)
        e.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
        e.add_field(name="Account Age",     value=f"{account_age} days", inline=True)
        e.add_field(name="Member #",        value=str(member.guild.member_count), inline=True)
        if account_age < 7:
            e.add_field(name="⚠️ New Account", value="Account is less than 7 days old!", inline=False)
        await self.send_to_log(member.guild, e)

        await _sb_insert(self.bot, "member_events", {
            "guild_id":        str(member.guild.id),
            "user_id":         str(member.id),
            "user_name":       str(member),
            "user_avatar":     str(member.display_avatar.url),
            "event_type":      "join",
            "account_age_days": account_age,
            "member_count":    member.guild.member_count,
        })

    # ─────────────────────────────────────────────────────────
    # EVENT: Member Leave
    # ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Check if this was a kick or ban via audit log
        event_type    = "leave"
        executor_id   = None
        executor_name = None
        reason        = None

        try:
            await asyncio.sleep(0.5)
            async for entry in member.guild.audit_logs(limit=3):
                if entry.target.id == member.id and \
                   abs((entry.created_at.replace(tzinfo=timezone.utc) -
                        datetime.now(timezone.utc)).total_seconds()) < 5:
                    if entry.action == discord.AuditLogAction.kick:
                        event_type  = "kick"
                        reason      = str(entry.reason) if entry.reason else None
                        executor_id   = str(entry.user.id)
                        executor_name = str(entry.user)
                    elif entry.action == discord.AuditLogAction.ban:
                        event_type  = "ban"
                        reason      = str(entry.reason) if entry.reason else None
                        executor_id   = str(entry.user.id)
                        executor_name = str(entry.user)
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass

        color_key = "error" if event_type in ("kick", "ban") else "warn"
        label     = {"leave": "Member Left", "kick": "Member Kicked", "ban": "Member Banned"}[event_type]

        e = embed(f"{icon('log_leave')} {label}", color=color_key)
        e.add_field(name="User",  value=f"{member} (`{member.id}`)", inline=True)
        e.add_field(name="Roles", value=", ".join(r.name for r in member.roles[1:]) or "None", inline=False)
        if executor_id:
            e.add_field(name="Executor", value=f"<@{executor_id}>", inline=True)
        if reason:
            e.add_field(name="Reason", value=reason, inline=False)
        await self.send_to_log(member.guild, e)

        await _sb_insert(self.bot, "member_events", {
            "guild_id":     str(member.guild.id),
            "user_id":      str(member.id),
            "user_name":    str(member),
            "user_avatar":  str(member.display_avatar.url),
            "event_type":   event_type,
            "executor_id":  executor_id,
            "executor_name": executor_name,
            "reason":       reason,
            "member_count": member.guild.member_count,
        })

    # ─────────────────────────────────────────────────────────
    # EVENT: Member Ban (explicit)
    # ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        # on_member_remove will also fire — log here for the supabase ban row
        # Discord already gets the log from on_member_remove, so just store in Supabase
        pass  # Handled in on_member_remove above

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        executor_id   = None
        executor_name = None
        reason        = None

        try:
            await asyncio.sleep(0.5)
            async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=3):
                if entry.target.id == user.id:
                    executor_id   = str(entry.user.id)
                    executor_name = str(entry.user)
                    reason        = str(entry.reason) if entry.reason else None
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass

        e = embed(f"{icon('unban')} Member Unbanned", color="success")
        e.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        if executor_id:
            e.add_field(name="Unbanned By", value=f"<@{executor_id}>", inline=True)
        if reason:
            e.add_field(name="Reason", value=reason, inline=False)
        await self.send_to_log(guild, e)

        await _sb_insert(self.bot, "member_events", {
            "guild_id":     str(guild.id),
            "user_id":      str(user.id),
            "user_name":    str(user),
            "event_type":   "unban",
            "executor_id":  executor_id,
            "executor_name": executor_name,
            "reason":       reason,
        })

    # ─────────────────────────────────────────────────────────
    # EVENT: Nickname & Role Changes
    # ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not before.guild:
            return

        # Nickname change
        if before.nick != after.nick:
            e = embed(f"{icon('log_nick')} Nickname Changed", color="info")
            e.add_field(name="User",   value=f"{after.mention} (`{after.id}`)", inline=True)
            e.add_field(name="Before", value=before.nick or before.name, inline=True)
            e.add_field(name="After",  value=after.nick  or after.name,  inline=True)
            await self.send_to_log(before.guild, e)

            await _sb_insert(self.bot, "role_events", {
                "guild_id":   str(before.guild.id),
                "user_id":    str(after.id),
                "user_name":  str(after),
                "event_type": "nick_change",
                "nick_before": before.nick or before.name,
                "nick_after":  after.nick  or after.name,
            })

        # Role changes
        added_roles   = [r for r in after.roles  if r not in before.roles]
        removed_roles = [r for r in before.roles if r not in after.roles]

        if added_roles or removed_roles:
            e = embed(f"{icon('log_roles')} Roles Updated", color="info")
            e.add_field(name="User", value=f"{after.mention} (`{after.id}`)", inline=False)
            if added_roles:
                e.add_field(name="Roles Added",
                            value=" ".join(r.mention for r in added_roles), inline=False)
            if removed_roles:
                e.add_field(name="Roles Removed",
                            value=" ".join(r.mention for r in removed_roles), inline=False)
            await self.send_to_log(before.guild, e)

            await _sb_insert(self.bot, "role_events", {
                "guild_id":      str(before.guild.id),
                "user_id":       str(after.id),
                "user_name":     str(after),
                "event_type":    "role_add" if added_roles else "role_remove",
                "roles_added":   [r.name for r in added_roles],
                "roles_removed": [r.name for r in removed_roles],
            })

    # ─────────────────────────────────────────────────────────
    # EVENT: Voice State Changes
    # ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState,
                                    after: discord.VoiceState):
        if member.bot:
            return

        if before.channel is None and after.channel is not None:
            action = "voice_join"
            desc   = f"joined **{after.channel.name}**"
        elif before.channel is not None and after.channel is None:
            action = "voice_leave"
            desc   = f"left **{before.channel.name}**"
        elif before.channel != after.channel:
            action = "voice_move"
            desc   = f"moved from **{before.channel.name}** → **{after.channel.name}**"
        else:
            return  # mute/deafen changes — skip

        await _sb_insert(self.bot, "bot_actions", {
            "guild_id":   str(member.guild.id),
            "channel_id": str(after.channel.id if after.channel else before.channel.id),
            "action":     action,
            "actor_id":   str(member.id),
            "actor_name": str(member),
            "details":    {"description": desc},
        })

    # ─────────────────────────────────────────────────────────
    # EXTERNAL HOOKS — called by other cogs
    # ─────────────────────────────────────────────────────────

    async def log_automod(self, guild: discord.Guild, channel: discord.TextChannel,
                           user: discord.Member, trigger_type: str,
                           content: str, action_taken: str):
        """Called by AutoMod cog after taking action."""
        await _sb_insert(self.bot, "automod_events", {
            "guild_id":     str(guild.id),
            "channel_id":   str(channel.id),
            "channel_name": channel.name,
            "user_id":      str(user.id),
            "user_name":    str(user),
            "trigger_type": trigger_type,
            "content":      content[:2000],
            "action_taken": action_taken,
        })

    async def log_bot_action(self, guild: discord.Guild, action: str,
                              actor: discord.Member = None,
                              target: discord.Member = None,
                              channel: discord.TextChannel = None,
                              details: dict = None):
        """Generic bot action logger. Called by any cog except AI."""
        await _sb_insert(self.bot, "bot_actions", {
            "guild_id":     str(guild.id),
            "channel_id":   str(channel.id) if channel else None,
            "channel_name": channel.name    if channel else None,
            "action":       action,
            "actor_id":     str(actor.id)   if actor else None,
            "actor_name":   str(actor)      if actor else None,
            "target_id":    str(target.id)  if target else None,
            "target_name":  str(target)     if target else None,
            "details":      details or {},
        })

    async def log_antiraid(self, guild: discord.Guild, event_type: str,
                            affected_users: list = None, details: dict = None):
        """Called by AntiRaid cog."""
        e = embed(f"🚨 Anti-Raid: {event_type.replace('_', ' ').title()}", color="error")
        if affected_users:
            e.add_field(name="Affected Users", value=str(len(affected_users)), inline=True)
        if details:
            for k, v in details.items():
                e.add_field(name=k.replace("_", " ").title(), value=str(v), inline=True)
        await self.send_to_log(guild, e)

        await _sb_insert(self.bot, "antiraid_events", {
            "guild_id":       str(guild.id),
            "event_type":     event_type,
            "affected_users": [str(u) for u in (affected_users or [])],
            "details":        details or {},
        })


async def setup(bot):
    await bot.add_cog(Logs(bot))