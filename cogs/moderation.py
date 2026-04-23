import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta
from typing import Union
import datetime
import re
import asyncio
from utils.embeds import mod_embed, embed
from utils.config import icon


# ── Shared guard for slash commands used outside a guild ──────────────────────
async def _guild_only(interaction: discord.Interaction) -> bool:
    """Returns True if we're in a guild, otherwise sends an error and returns False."""
    if interaction.guild is None:
        await interaction.response.send_message(
            embed=embed(
                "⚠️ Server Only",
                "This command can only be used inside a server.",
                color="error"),
            ephemeral=True)
        return False
    return True


def parse_duration(raw: str) -> tuple[int, str]:
    raw   = raw.strip().lower()
    match = re.fullmatch(r"(\d+)(s|sec|secs|m|min|mins|h|hr|hrs|d|day|days)?", raw)
    if not match:
        raise ValueError(f"Cannot parse duration: {raw!r}")

    amount = int(match.group(1))
    unit   = match.group(2) or "m"

    if unit in ("s", "sec", "secs"):
        seconds = amount;  label = f"{amount} second{'s' if amount != 1 else ''}"
    elif unit in ("m", "min", "mins"):
        seconds = amount * 60;    label = f"{amount} minute{'s' if amount != 1 else ''}"
    elif unit in ("h", "hr", "hrs"):
        seconds = amount * 3600;  label = f"{amount} hour{'s' if amount != 1 else ''}"
    elif unit in ("d", "day", "days"):
        seconds = amount * 86400; label = f"{amount} day{'s' if amount != 1 else ''}"
    else:
        raise ValueError(f"Unknown unit: {unit!r}")

    if seconds > 28 * 86400:
        raise ValueError("Duration cannot exceed 28 days.")
    if seconds < 1:
        raise ValueError("Duration must be at least 1 second.")
    return seconds, label


class Moderation(commands.Cog):
    """Core moderation commands."""

    def __init__(self, bot):
        self.bot = bot

    async def log_action(self, guild, action, mod, target, reason):
        await self.bot.db.add_log(guild.id, action, mod.id, target.id, reason)
        config = await self.bot.db.get_config(guild.id)
        log_channel_id = config.get("log_channel_id")
        if log_channel_id:
            ch = guild.get_channel(int(log_channel_id))
            if ch:
                try:
                    await ch.send(embed=mod_embed(action, target, mod, reason))
                except discord.HTTPException:
                    pass

    async def _send_with_shared_buttons(self, ctx_or_interaction, action, target, mod,
                                        reason, extra_fields=None, color="mod"):
        from cogs.shared_moderation import SharedModerationView, build_shared_mod_embed

        guild  = ctx_or_interaction.guild
        config = await self.bot.db.get_config(guild.id)
        shared_channel_id = config.get("shared_mod_channel_id")
        action_embed = mod_embed(action, target, mod, reason,
                                 extra_fields=extra_fields, color=color)

        if shared_channel_id:
            record = await self.bot.db.create_shared_mod(
                guild_id=guild.id, mod_id=mod.id, target_id=target.id,
                action=action, reason=reason,
                duration=extra_fields.get("Duration") if extra_fields else None,
            )
            await self.bot.db.update_modtrack(guild.id, mod.id, "modded")
            mod_id = record["id"]
            view = SharedModerationView(self.bot)

            if isinstance(ctx_or_interaction, commands.Context):
                msg = await ctx_or_interaction.send(embed=action_embed, view=view)
            else:
                await ctx_or_interaction.response.send_message(embed=action_embed, view=view)
                msg = await ctx_or_interaction.original_response()

            await self.bot.db.update_shared_mod_message(mod_id, msg.channel.id, msg.id)
        else:
            if isinstance(ctx_or_interaction, commands.Context):
                await ctx_or_interaction.send(embed=action_embed)
            else:
                await ctx_or_interaction.response.send_message(embed=action_embed)

    # ── Safe Purge ────────────────────────────────────────────
    async def safe_purge(self, channel, limit=None, check=None, progress_msg=None):
        two_weeks_ago = discord.utils.utcnow() - datetime.timedelta(days=13)
        new_messages, old_messages = [], []

        async for msg in channel.history(limit=limit or 500):
            if check and not check(msg):
                continue
            if msg.created_at > two_weeks_ago:
                new_messages.append(msg)
            else:
                old_messages.append(msg)

        deleted = 0
        for i in range(0, len(new_messages), 100):
            chunk = new_messages[i:i + 100]
            try:
                await channel.delete_messages(chunk)
                deleted += len(chunk)
                if progress_msg and deleted % 50 == 0:
                    try:
                        await progress_msg.edit(embed=embed(
                            f"{icon('progress')} Purging… {deleted} deleted so far.", color="info"))
                    except discord.HTTPException:
                        pass
                await asyncio.sleep(1)
            except discord.HTTPException:
                pass

        if old_messages:
            for msg in old_messages:
                try:
                    await msg.delete()
                    deleted += 1
                    await asyncio.sleep(1.2)
                except discord.HTTPException:
                    pass

        return deleted

    # ── Kick ──────────────────────────────────────────────────
    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick_prefix(self, ctx, member: discord.Member, *, reason="No reason provided"):
        """Kick a member. ?kick @user [reason]"""
        await member.kick(reason=reason)
        await self._send_with_shared_buttons(ctx, "Kicked", member, ctx.author, reason, color="error")
        await self.log_action(ctx.guild, "Kicked", ctx.author, member, reason)

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member,
                         reason: str = "No reason provided"):
        if not await _guild_only(interaction):
            return
        await member.kick(reason=reason)
        await self._send_with_shared_buttons(interaction, "Kicked", member, interaction.user, reason, color="error")
        await self.log_action(interaction.guild, "Kicked", interaction.user, member, reason)

    # ── Ban ───────────────────────────────────────────────────
    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban_prefix(self, ctx, member: discord.Member, *, reason="No reason provided"):
        """Ban a member. ?ban @user [reason]"""
        await member.ban(reason=reason)
        await self._send_with_shared_buttons(ctx, "Banned", member, ctx.author, reason, color="error")
        await self.log_action(ctx.guild, "Banned", ctx.author, member, reason)

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member,
                        reason: str = "No reason provided"):
        if not await _guild_only(interaction):
            return
        await member.ban(reason=reason)
        await self._send_with_shared_buttons(interaction, "Banned", member, interaction.user, reason, color="error")
        await self.log_action(interaction.guild, "Banned", interaction.user, member, reason)

    # ── Unban ─────────────────────────────────────────────────
    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban_prefix(self, ctx, user_id: int, *, reason="No reason provided"):
        """Unban a user by ID. ?unban <user_id> [reason]"""
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            return await ctx.send(embed=embed(
                f"{icon('error')} User Not Found",
                f"No user with ID `{user_id}` exists.", color="error"))
        try:
            await ctx.guild.unban(user, reason=reason)
        except discord.NotFound:
            return await ctx.send(embed=embed(
                f"{icon('warn')} Not Banned",
                f"{user} is not currently banned in this server.", color="warn"))
        await ctx.send(embed=embed(f"{icon('ok')} Unbanned **{user}**", color="success"))
        await self.log_action(ctx.guild, "Unbanned", ctx.author, user, reason)

    @app_commands.command(name="unban", description="Unban a user by their ID")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban_slash(self, interaction: discord.Interaction, user_id: str,
                          reason: str = "No reason provided"):
        if not await _guild_only(interaction):
            return
        try:
            uid  = int(user_id)
            user = await self.bot.fetch_user(uid)
        except (ValueError, discord.NotFound):
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} User Not Found",
                f"No user found with ID `{user_id}`.", color="error"), ephemeral=True)
        try:
            await interaction.guild.unban(user, reason=reason)
        except discord.NotFound:
            return await interaction.response.send_message(embed=embed(
                f"{icon('warn')} Not Banned",
                f"{user} is not currently banned in this server.", color="warn"), ephemeral=True)
        await interaction.response.send_message(embed=embed(
            f"{icon('ok')} Unbanned **{user}**", color="success"))

    # ── Soft-ban ──────────────────────────────────────────────
    @commands.command(name="softban")
    @commands.has_permissions(ban_members=True)
    async def softban_prefix(self, ctx, member: discord.Member, *, reason="No reason provided"):
        """Softban: ban then immediately unban to delete message history.
        ?softban @user [reason]"""
        await member.ban(reason=f"Softban: {reason}", delete_message_days=7)
        await ctx.guild.unban(member, reason="Softban — immediate unban")
        await ctx.send(embed=mod_embed("Soft-Banned", member, ctx.author,
                                       f"{reason}\n*(Softban: messages deleted, not permanently banned)*",
                                       color="warn"))
        await self.log_action(ctx.guild, "Soft-Banned", ctx.author, member, reason)

    @app_commands.command(name="softban",
                          description="Softban: ban + instant unban to wipe message history")
    @app_commands.checks.has_permissions(ban_members=True)
    async def softban_slash(self, interaction: discord.Interaction, member: discord.Member,
                            reason: str = "No reason provided"):
        if not await _guild_only(interaction):
            return
        await member.ban(reason=f"Softban: {reason}", delete_message_days=7)
        await interaction.guild.unban(member, reason="Softban — immediate unban")
        await interaction.response.send_message(embed=mod_embed(
            "Soft-Banned", member, interaction.user,
            f"{reason}\n*(Softban: messages deleted, not permanently banned)*", color="warn"))

    # ── Ban info ──────────────────────────────────────────────
    @commands.command(name="baninfo")
    @commands.has_permissions(ban_members=True)
    async def baninfo_prefix(self, ctx, user_id: int):
        """Check if a user is currently banned. ?baninfo <user_id>"""
        try:
            ban_entry = await ctx.guild.fetch_ban(discord.Object(id=user_id))
        except discord.NotFound:
            return await ctx.send(embed=embed(
                f"{icon('ok')} Not Banned",
                f"User ID `{user_id}` is not banned in this server.", color="success"))
        e = embed(f"{icon('ban')} Ban Info — {ban_entry.user}", color="error")
        e.add_field(name="User",   value=f"{ban_entry.user} (`{ban_entry.user.id}`)", inline=True)
        e.add_field(name="Reason", value=ban_entry.reason or "No reason provided",   inline=False)
        e.set_thumbnail(url=ban_entry.user.display_avatar.url)
        await ctx.send(embed=e)

    @app_commands.command(name="baninfo", description="Check if a user is banned (by user ID)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def baninfo_slash(self, interaction: discord.Interaction, user_id: str):
        if not await _guild_only(interaction):
            return
        try:
            uid       = int(user_id)
            ban_entry = await interaction.guild.fetch_ban(discord.Object(id=uid))
        except (ValueError, discord.NotFound):
            return await interaction.response.send_message(embed=embed(
                f"{icon('ok')} Not Banned",
                f"User ID `{user_id}` is not banned in this server.", color="success"))
        e = embed(f"{icon('ban')} Ban Info — {ban_entry.user}", color="error")
        e.add_field(name="User",   value=f"{ban_entry.user} (`{ban_entry.user.id}`)", inline=True)
        e.add_field(name="Reason", value=ban_entry.reason or "No reason provided",   inline=False)
        e.set_thumbnail(url=ban_entry.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

    # ── Mute (Timeout) ────────────────────────────────────────
    @commands.command(name="mute")
    @commands.has_permissions(moderate_members=True)
    async def mute_prefix(self, ctx, member: discord.Member,
                          duration: str = "10m", *, reason="No reason provided"):
        """Timeout a member. ?mute @user [duration] [reason]
        Formats: 30s, 10m, 2h, 1d (max 28 days, default 10m)"""
        try:
            seconds, label = parse_duration(duration)
        except ValueError as e:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Duration",
                f"{e}\n**Usage:** `?mute @user [duration] [reason]`\n"
                "Examples: `30s`, `10m`, `2h`, `1d`", color="error"))
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await member.timeout(until, reason=reason)
        await self._send_with_shared_buttons(ctx, "Muted", member, ctx.author, reason,
                                             extra_fields={"Duration": label}, color="warn")
        await self.log_action(ctx.guild, f"Muted ({label})", ctx.author, member, reason)

    @app_commands.command(name="mute", description="Timeout a member (e.g. 30s, 10m, 2h, 1d)")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute_slash(self, interaction: discord.Interaction, member: discord.Member,
                         duration: str = "10m", reason: str = "No reason provided"):
        if not await _guild_only(interaction):
            return
        try:
            seconds, label = parse_duration(duration)
        except ValueError as e:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Invalid Duration",
                f"{e}\nFormats: `30s`, `10m`, `2h`, `1d`", color="error"), ephemeral=True)
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await member.timeout(until, reason=reason)
        await self._send_with_shared_buttons(interaction, "Muted", member, interaction.user,
                                             reason, extra_fields={"Duration": label}, color="warn")
        await self.log_action(interaction.guild, f"Muted ({label})", interaction.user, member, reason)

    # ── Unmute ────────────────────────────────────────────────
    @commands.command(name="unmute")
    @commands.has_permissions(moderate_members=True)
    async def unmute_prefix(self, ctx, member: discord.Member, *, reason="No reason provided"):
        """Remove a member's timeout. ?unmute @user [reason]"""
        if not member.is_timed_out():
            return await ctx.send(embed=embed(
                f"{icon('warn')} Not Muted",
                f"{member.mention} is not currently muted.", color="warn"))
        await member.timeout(None, reason=reason)
        await ctx.send(embed=mod_embed("Unmuted", member, ctx.author, reason, color="success"))
        await self.log_action(ctx.guild, "Unmuted", ctx.author, member, reason)

    @app_commands.command(name="unmute", description="Remove a timeout from a member")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute_slash(self, interaction: discord.Interaction, member: discord.Member,
                           reason: str = "No reason provided"):
        if not await _guild_only(interaction):
            return
        if not member.is_timed_out():
            return await interaction.response.send_message(embed=embed(
                f"{icon('warn')} Not Muted",
                f"{member.mention} is not currently muted.", color="warn"), ephemeral=True)
        await member.timeout(None, reason=reason)
        await interaction.response.send_message(embed=mod_embed(
            "Unmuted", member, interaction.user, reason, color="success"))

    # ── Purge ─────────────────────────────────────────────────
    @commands.command(name="purge")
    @commands.has_permissions(manage_messages=True)
    async def purge_prefix(self, ctx, target: Union[discord.Member, int, str] = None, amount: int = 100):
        """Bulk delete messages.
        ?purge [amount]         — delete last N messages
        ?purge @user [amount]   — delete messages from a user
        ?purge banned           — delete messages from banned users"""
        await ctx.message.delete()

        # ── banned keyword ──
        if isinstance(target, str) and target.lower() == "banned":
            banned = [entry.user async for entry in ctx.guild.bans(limit=None)]
            if not banned:
                msg = await ctx.send(embed=embed(f"{icon('info')} No banned users found.", color="info"))
                await asyncio.sleep(4)
                return await msg.delete()
            banned_ids = {u.id for u in banned}
            progress = await ctx.send(embed=embed(
                f"{icon('purge')} Purging messages from {len(banned_ids)} banned user(s)…", color="info"))
            deleted = await self.safe_purge(ctx.channel, limit=500,
                                            check=lambda m: m.author.id in banned_ids,
                                            progress_msg=progress)
            await progress.edit(embed=embed(
                f"{icon('ok')} Purged {deleted} messages from {len(banned_ids)} banned user(s).",
                color="success"))
            await asyncio.sleep(4)
            return await progress.delete()

        # ── specific member ──
        if isinstance(target, discord.Member):
            progress = await ctx.send(embed=embed(
                f"{icon('purge')} Purging messages from {target.display_name}…", color="info"))
            deleted = await self.safe_purge(ctx.channel, limit=max(amount, 200),
                                            check=lambda m: m.author.id == target.id,
                                            progress_msg=progress)
            await progress.edit(embed=embed(
                f"{icon('ok')} Purged {deleted} messages from {target.mention}.", color="success"))
            await asyncio.sleep(4)
            return await progress.delete()

        # ── numeric / no target ──
        if isinstance(target, int):
            amount = target
        elif target is not None:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Purge Target",
                "Use `?purge [amount]`, `?purge @user`, or `?purge banned`.", color="error"))

        progress = await ctx.send(embed=embed(
            f"{icon('purge')} Purging {amount} messages…", color="info"))
        deleted = await self.safe_purge(ctx.channel, limit=amount, progress_msg=progress)
        await progress.edit(embed=embed(f"{icon('ok')} Purged {deleted} messages.", color="success"))
        await asyncio.sleep(4)
        await progress.delete()

    @purge_prefix.error
    async def purge_error(self, ctx, error):
        # Union[Member, int, str] handles conversion automatically.
        # This handler now only catches unexpected errors.
        if isinstance(error, (commands.MissingPermissions, commands.BotMissingPermissions)):
            raise error
        # Fallback: try treating the first arg as a plain number
        raw = ctx.message.content.split()
        if len(raw) >= 2 and raw[1].isdigit():
            return await ctx.invoke(self.purge_prefix, target=None, amount=int(raw[1]))
        raise error

    @app_commands.command(name="purge", description="Delete messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_slash(self, interaction: discord.Interaction,
                          amount: int = 10, member: discord.Member = None, banned: bool = False):
        if not await _guild_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if banned:
            banned_users = [entry.user async for entry in interaction.guild.bans(limit=None)]
            banned_ids   = {u.id for u in banned_users}
            deleted = await self.safe_purge(interaction.channel, limit=500,
                                            check=lambda m: m.author.id in banned_ids)
            return await interaction.followup.send(embed=embed(
                f"{icon('ok')} Purged {deleted} messages from {len(banned_ids)} banned user(s).",
                color="success"), ephemeral=True)
        if member:
            deleted = await self.safe_purge(interaction.channel, limit=max(amount, 200),
                                            check=lambda m: m.author.id == member.id)
            return await interaction.followup.send(embed=embed(
                f"{icon('ok')} Purged {deleted} messages from {member.mention}.",
                color="success"), ephemeral=True)
        deleted = await self.safe_purge(interaction.channel, limit=amount)
        await interaction.followup.send(embed=embed(
            f"{icon('ok')} Purged {deleted} messages.", color="success"), ephemeral=True)

    # ── Cleanup ───────────────────────────────────────────────
    @commands.command(name="cleanup")
    @commands.has_permissions(manage_messages=True)
    async def cleanup_prefix(self, ctx, amount: int = 20):
        """Delete bot messages from this channel. ?cleanup [amount]"""
        if amount < 1 or amount > 500:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Amount",
                "Amount must be between 1 and 500.", color="error"))
        deleted = await self.safe_purge(
            ctx.channel, limit=amount,
            check=lambda m: m.author.id == self.bot.user.id)
        msg = await ctx.send(embed=embed(
            f"{icon('ok')} Cleaned up {deleted} bot message(s).", color="success"))
        await asyncio.sleep(5)
        await msg.delete()

    @app_commands.command(name="cleanup", description="Delete bot messages from this channel")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def cleanup_slash(self, interaction: discord.Interaction, amount: int = 20):
        if not await _guild_only(interaction):
            return
        if amount < 1 or amount > 500:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Amount must be 1–500.", color="error"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        deleted = await self.safe_purge(interaction.channel, limit=amount,
                                        check=lambda m: m.author.id == self.bot.user.id)
        await interaction.followup.send(embed=embed(
            f"{icon('ok')} Cleaned up {deleted} bot message(s).", color="success"), ephemeral=True)

    # ── Slowmode ──────────────────────────────────────────────
    @commands.command(name="slowmode")
    @commands.has_permissions(manage_channels=True)
    async def slowmode_prefix(self, ctx, seconds: int = 0):
        """Set channel slowmode. ?slowmode [seconds] (0 to disable)"""
        if seconds < 0 or seconds > 21600:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Slowmode",
                "Seconds must be between 0 and 21600 (6 hours).", color="error"))
        await ctx.channel.edit(slowmode_delay=seconds)
        msg = (f"{icon('slow')} Slowmode set to **{seconds}s**" if seconds > 0
               else f"{icon('unlock')} Slowmode disabled")
        await ctx.send(embed=embed(msg, color="info"))

    @app_commands.command(name="slowmode", description="Set channel slowmode (0 to disable)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode_slash(self, interaction: discord.Interaction, seconds: int = 0):
        if not await _guild_only(interaction):
            return
        if seconds < 0 or seconds > 21600:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Seconds must be 0–21600.", color="error"), ephemeral=True)
        await interaction.channel.edit(slowmode_delay=seconds)
        msg = (f"{icon('slow')} Slowmode set to **{seconds}s**" if seconds > 0
               else f"{icon('unlock')} Slowmode disabled")
        await interaction.response.send_message(embed=embed(msg, color="info"))

    # ── Lock / Unlock ─────────────────────────────────────────
    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    async def lock_prefix(self, ctx, *, reason: str = "No reason provided"):
        """Lock this channel. ?lock [reason]"""
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        e = embed(f"{icon('lock')} Channel Locked", color="error")
        e.add_field(name="Channel",   value=ctx.channel.mention, inline=True)
        e.add_field(name="Moderator", value=ctx.author.mention,  inline=True)
        e.add_field(name="Reason",    value=reason,              inline=False)
        await ctx.send(embed=e)
        await self.bot.db.add_log(ctx.guild.id, "Channel Locked", ctx.author.id, ctx.channel.id, reason)

    @app_commands.command(name="lock", description="Lock this channel so members cannot send messages")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock_slash(self, interaction: discord.Interaction, reason: str = "No reason provided"):
        if not await _guild_only(interaction):
            return
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        e = embed(f"{icon('lock')} Channel Locked", color="error")
        e.add_field(name="Channel",   value=interaction.channel.mention, inline=True)
        e.add_field(name="Moderator", value=interaction.user.mention,    inline=True)
        e.add_field(name="Reason",    value=reason,                      inline=False)
        await interaction.response.send_message(embed=e)

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    async def unlock_prefix(self, ctx):
        """Unlock this channel. ?unlock"""
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        e = embed(f"{icon('unlock')} Channel Unlocked", color="success")
        e.add_field(name="Channel",   value=ctx.channel.mention, inline=True)
        e.add_field(name="Moderator", value=ctx.author.mention,  inline=True)
        await ctx.send(embed=e)

    @app_commands.command(name="unlock", description="Unlock this channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock_slash(self, interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        e = embed(f"{icon('unlock')} Channel Unlocked", color="success")
        e.add_field(name="Channel",   value=interaction.channel.mention, inline=True)
        e.add_field(name="Moderator", value=interaction.user.mention,    inline=True)
        await interaction.response.send_message(embed=e)

    # ── Nickname ──────────────────────────────────────────────
    @commands.command(name="nickname", aliases=["nick"])
    @commands.has_permissions(manage_nicknames=True)
    async def nickname_prefix(self, ctx, member: discord.Member, *, new_nick: str = None):
        """Change or reset a member's nickname. ?nickname @user [new_name]"""
        old_nick = member.display_name
        await member.edit(nick=new_nick)
        if new_nick:
            await ctx.send(embed=embed(
                f"{icon('nick')} Nickname changed",
                f"{old_nick} → **{new_nick}**", color="success"))
        else:
            await ctx.send(embed=embed(
                f"{icon('nick')} Nickname reset for {member.name}", color="success"))

    @app_commands.command(name="nickname", description="Change or reset a member's nickname")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def nickname_slash(self, interaction: discord.Interaction,
                             member: discord.Member, new_nick: str = None):
        if not await _guild_only(interaction):
            return
        old_nick = member.display_name
        await member.edit(nick=new_nick)
        if new_nick:
            await interaction.response.send_message(embed=embed(
                f"{icon('nick')} Nickname changed", f"{old_nick} → **{new_nick}**", color="success"))
        else:
            await interaction.response.send_message(embed=embed(
                f"{icon('nick')} Nickname reset for {member.name}", color="success"))


async def setup(bot):
    await bot.add_cog(Moderation(bot))
