"""
guild_cache_events.py — Jiro Discord Bot

Cog that keeps the `user_guilds` Supabase table in sync.
This is what powers the dashboard guild picker.

Add to your bot in bot.py:
    await bot.load_extension("cogs.guild_cache_events")

Permission bits checked:
    ADMINISTRATOR  = 0x8  (8)
    MANAGE_GUILD   = 0x20 (32)
"""

import discord
from discord.ext import commands


MANAGE_PERM = discord.Permissions(manage_guild=True)


def _has_manage(member: discord.Member) -> bool:
    """True if the member has ADMINISTRATOR or MANAGE_GUILD."""
    p = member.guild_permissions
    return p.administrator or p.manage_guild


def _icon_hash(guild: discord.Guild) -> str | None:
    return str(guild.icon) if guild.icon else None


class GuildCacheEvents(commands.Cog):
    """Keeps user_guilds table in sync for the dashboard guild picker."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Bot joins a new guild ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """
        When Jiro joins a guild, cache every member who has manage permissions.
        discord.py lazy-loads member lists, so we request them explicitly.
        """
        try:
            # chunk=True fetches all members (requires GUILD_MEMBERS intent)
            await guild.chunk(cache=True)
        except Exception:
            pass  # Best-effort; work with whatever is cached

        upserted = 0
        for member in guild.members:
            if member.bot:
                continue
            if _has_manage(member):
                try:
                    await self.bot.db.upsert_user_guild(
                        user_id=member.id,
                        guild_id=guild.id,
                        guild_name=guild.name,
                        guild_icon=_icon_hash(guild),
                        permissions=member.guild_permissions.value,
                    )
                    upserted += 1
                except Exception as e:
                    print(f"[GuildCache] upsert failed {member.id}/{guild.id}: {e}")

        print(f"[GuildCache] on_guild_join {guild.name}: cached {upserted} managers")

    # ── Bot is removed from a guild ───────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """
        When Jiro leaves / is kicked, mark all user rows as bot_absent.
        This hides the guild from every user's dashboard immediately.
        """
        try:
            await self.bot.db.mark_guild_bot_absent(guild.id)
            print(f"[GuildCache] on_guild_remove {guild.name}: marked bot_present=false")
        except Exception as e:
            print(f"[GuildCache] mark_guild_bot_absent failed {guild.id}: {e}")

    # ── Guild is renamed or icon changes ─────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        """Keep guild_name and guild_icon fresh when they change."""
        if before.name == after.name and before.icon == after.icon:
            return
        # Re-upsert all cached rows for this guild with the new name/icon.
        # We do this by patching every user_guilds row for the guild directly.
        try:
            await self.bot.db._patch(
                "user_guilds",
                {"guild_id": str(after.id)},
                {"guild_name": after.name, "guild_icon": _icon_hash(after)},
            )
        except Exception as e:
            print(f"[GuildCache] on_guild_update patch failed {after.id}: {e}")

    # ── Member's roles change → permissions may change ───────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        If a member's permissions changed:
        - Gained manage perms → upsert row
        - Lost manage perms  → remove row
        """
        before_perms = before.guild_permissions.value
        after_perms  = after.guild_permissions.value

        if before_perms == after_perms:
            return  # Nothing changed — skip DB call

        if after.bot:
            return

        had_manage  = _has_manage(before)
        has_manage  = _has_manage(after)

        if has_manage and not had_manage:
            # Member just got manage access — add to cache
            try:
                await self.bot.db.upsert_user_guild(
                    user_id=after.id,
                    guild_id=after.guild.id,
                    guild_name=after.guild.name,
                    guild_icon=_icon_hash(after.guild),
                    permissions=after_perms,
                )
                print(f"[GuildCache] {after} gained manage in {after.guild.name} — upserted")
            except Exception as e:
                print(f"[GuildCache] upsert failed on_member_update: {e}")

        elif had_manage and not has_manage:
            # Member lost manage access — remove from cache
            try:
                await self.bot.db.remove_user_guild(after.id, after.guild.id)
                print(f"[GuildCache] {after} lost manage in {after.guild.name} — removed")
            except Exception as e:
                print(f"[GuildCache] remove failed on_member_update: {e}")

        else:
            # Permissions changed but manage status didn't — just update the value
            if has_manage:
                try:
                    await self.bot.db.upsert_user_guild(
                        user_id=after.id,
                        guild_id=after.guild.id,
                        guild_name=after.guild.name,
                        guild_icon=_icon_hash(after.guild),
                        permissions=after_perms,
                    )
                except Exception as e:
                    print(f"[GuildCache] upsert (perm refresh) failed: {e}")

    # ── Member joins — rare but they could already have perms ─────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Catch edge case where someone joins with manage perms via role pre-assignment."""
        if member.bot:
            return
        if _has_manage(member):
            try:
                await self.bot.db.upsert_user_guild(
                    user_id=member.id,
                    guild_id=member.guild.id,
                    guild_name=member.guild.name,
                    guild_icon=_icon_hash(member.guild),
                    permissions=member.guild_permissions.value,
                )
            except Exception as e:
                print(f"[GuildCache] on_member_join upsert failed: {e}")

    # ── Member leaves ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Clean up when a managing member leaves."""
        if member.bot:
            return
        if _has_manage(member):
            try:
                await self.bot.db.remove_user_guild(member.id, member.guild.id)
            except Exception as e:
                print(f"[GuildCache] on_member_remove remove failed: {e}")


# ── Backfill command (run once after deploying) ───────────────────────────────

    @commands.command(name="cacheguilds", hidden=True)
    @commands.is_owner()
    async def cache_guilds(self, ctx: commands.Context):
        """
        One-time backfill: walks every guild the bot is in and caches
        all members with manage permissions. Run once after deploying
        the user_guilds table.

        Usage: !cacheguilds
        """
        msg = await ctx.send("⏳ Backfilling user_guilds cache...")
        total_guilds  = 0
        total_members = 0

        for guild in self.bot.guilds:
            try:
                await guild.chunk(cache=True)
            except Exception:
                pass

            for member in guild.members:
                if member.bot:
                    continue
                if _has_manage(member):
                    try:
                        await self.bot.db.upsert_user_guild(
                            user_id=member.id,
                            guild_id=guild.id,
                            guild_name=guild.name,
                            guild_icon=_icon_hash(guild),
                            permissions=member.guild_permissions.value,
                        )
                        total_members += 1
                    except Exception as e:
                        print(f"[GuildCache] backfill error {member.id}/{guild.id}: {e}")

            total_guilds += 1

        await msg.edit(content=f"✅ Done — {total_guilds} guilds, {total_members} manager rows cached.")


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildCacheEvents(bot))
