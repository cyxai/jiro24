import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta
from utils.embeds import embed, mod_embed
from utils.config import icon


class Warnings(commands.Cog):
    """Warning system with dashboard-configurable auto-escalation."""

    def __init__(self, bot):
        self.bot = bot

    async def escalate(self, guild: discord.Guild, member: discord.Member, warn_count: int) -> str | None:
        thresholds = await self.bot.db.get_warn_thresholds(guild.id)
        mute_at  = thresholds["mute_at"]
        kick_at  = thresholds["kick_at"]
        ban_at   = thresholds["ban_at"]
        mute_hrs = thresholds["mute_hours"]
        reason   = f"Auto-escalation: {warn_count} warning(s)"

        if warn_count == mute_at:
            until = discord.utils.utcnow() + timedelta(hours=mute_hrs)
            try:
                await member.timeout(until, reason=reason)
                dur = f"{int(mute_hrs)}h" if mute_hrs >= 1 else f"{int(mute_hrs * 60)}m"
                return f"{icon('mute')} Auto-muted for {dur} ({mute_at} warnings)"
            except discord.Forbidden:
                return f"{icon('warn')} Could not auto-mute (missing permissions)"

        elif warn_count == kick_at:
            try:
                await member.kick(reason=reason)
                return f"{icon('kick')} Auto-kicked ({kick_at} warnings)"
            except discord.Forbidden:
                return f"{icon('warn')} Could not auto-kick (missing permissions)"

        elif warn_count >= ban_at:
            try:
                await member.ban(reason=reason)
                return f"{icon('ban')} Auto-banned ({ban_at}+ warnings)"
            except discord.Forbidden:
                return f"{icon('warn')} Could not auto-ban (missing permissions)"

        return None

    # ── Warn ──────────────────────────────────────────────────
    @commands.command(name="warn")
    @commands.has_permissions(manage_messages=True)
    async def warn_prefix(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await self.bot.db.add_warning(ctx.guild.id, member.id, ctx.author.id, reason)
        warnings = await self.bot.db.get_warnings(ctx.guild.id, member.id)
        count = len(warnings)
        e = mod_embed("Warning Issued", member, ctx.author, reason,
                      extra_fields={"Total Warnings": str(count)}, color="warn")
        await ctx.send(embed=e)
        escalation = await self.escalate(ctx.guild, member, count)
        if escalation:
            await ctx.send(embed=embed(escalation, color="error"))
        await self.bot.db.add_log(ctx.guild.id, f"Warn ({count} total)", ctx.author.id, member.id, reason)

    @app_commands.command(name="warn", description="Issue a warning to a member")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn_slash(self, interaction: discord.Interaction,
                         member: discord.Member, reason: str = "No reason provided"):
        await self.bot.db.add_warning(interaction.guild.id, member.id, interaction.user.id, reason)
        warnings = await self.bot.db.get_warnings(interaction.guild.id, member.id)
        count = len(warnings)
        e = mod_embed("Warning Issued", member, interaction.user, reason,
                      extra_fields={"Total Warnings": str(count)}, color="warn")
        await interaction.response.send_message(embed=e)
        escalation = await self.escalate(interaction.guild, member, count)
        if escalation:
            await interaction.followup.send(embed=embed(escalation, color="error"))

    # ── Warnings list ─────────────────────────────────────────
    @commands.command(name="warnings")
    @commands.has_permissions(manage_messages=True)
    async def warnings_prefix(self, ctx, member: discord.Member):
        warnings = await self.bot.db.get_warnings(ctx.guild.id, member.id)
        if not warnings:
            return await ctx.send(embed=embed(f"{icon('ok')} {member.display_name} has no warnings.", color="success"))
        thresholds = await self.bot.db.get_warn_thresholds(ctx.guild.id)
        e = embed(f"{icon('warnings')} Warnings for {member.display_name}", color="warn")
        e.set_footer(text=f"Thresholds — Mute: {thresholds['mute_at']} | Kick: {thresholds['kick_at']} | Ban: {thresholds['ban_at']}")
        for i, w in enumerate(warnings[:10], 1):
            e.add_field(
                name=f"#{i} — ID: `{w['id']}`",
                value=f"**Reason:** {w['reason']}\n**Date:** {w['created_at'][:10]}",
                inline=False,
            )
        await ctx.send(embed=e)

    @app_commands.command(name="warnings", description="View warnings for a member")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warnings_slash(self, interaction: discord.Interaction, member: discord.Member):
        warnings = await self.bot.db.get_warnings(interaction.guild.id, member.id)
        if not warnings:
            return await interaction.response.send_message(
                embed=embed(f"{icon('ok')} {member.display_name} has no warnings.", color="success"))
        e = embed(f"{icon('warnings')} Warnings for {member.display_name}", color="warn")
        for i, w in enumerate(warnings[:10], 1):
            e.add_field(
                name=f"#{i} — ID: `{w['id']}`",
                value=f"**Reason:** {w['reason']}\n**Date:** {w['created_at'][:10]}",
                inline=False,
            )
        await interaction.response.send_message(embed=e)

    # ── Clear warnings ────────────────────────────────────────
    @commands.command(name="clearwarnings", aliases=["clearwarn"])
    @commands.has_permissions(administrator=True)
    async def clearwarnings_prefix(self, ctx, member: discord.Member):
        await self.bot.db.clear_warnings(ctx.guild.id, member.id)
        await ctx.send(embed=embed(f"{icon('ok')} Cleared all warnings for {member.mention}", color="success"))

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member")
    @app_commands.checks.has_permissions(administrator=True)
    async def clearwarnings_slash(self, interaction: discord.Interaction, member: discord.Member):
        await self.bot.db.clear_warnings(interaction.guild.id, member.id)
        await interaction.response.send_message(
            embed=embed(f"{icon('ok')} Cleared all warnings for {member.mention}", color="success"))

    # ── Remove single warning ──────────────────────────────────
    @commands.command(name="delwarning")
    @commands.has_permissions(administrator=True)
    async def delwarning_prefix(self, ctx, warning_id: int):
        await self.bot.db.remove_warning(warning_id)
        await ctx.send(embed=embed(f"{icon('ok')} Removed warning `#{warning_id}`", color="success"))

    # ── Configure thresholds ───────────────────────────────────
    @commands.command(name="warnconfig")
    @commands.has_permissions(administrator=True)
    async def warnconfig(self, ctx, mute_at: int, kick_at: int, ban_at: int, mute_hours: float = 1.0):
        """Set warning escalation thresholds.
        Usage: ?warnconfig <mute_at> <kick_at> <ban_at> [mute_hours]"""
        if not (1 <= mute_at < kick_at < ban_at <= 50):
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid thresholds. Must be: mute_at < kick_at < ban_at, all between 1-50.",
                color="error"))
        config = await self.bot.db.get_config(ctx.guild.id)
        config["warn_mute_at"]    = mute_at
        config["warn_kick_at"]    = kick_at
        config["warn_ban_at"]     = ban_at
        config["warn_mute_hours"] = mute_hours
        await self.bot.db.set_full_config(ctx.guild.id, config)
        e = embed(f"{icon('ok')} Warning Thresholds Updated", color="success")
        e.add_field(name="Auto-Mute at", value=f"{mute_at} warnings ({mute_hours}h)", inline=True)
        e.add_field(name="Auto-Kick at", value=f"{kick_at} warnings",                 inline=True)
        e.add_field(name="Auto-Ban at",  value=f"{ban_at} warnings",                  inline=True)
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(Warnings(bot))
