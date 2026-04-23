"""
cogs/guild_sync.py
──────────────────
Populates the `user_guilds` Supabase table so the dashboard can
show servers. Syncs on:
  • Bot ready (all guilds, all members)
  • Member joins / leaves a guild
  • Bot joins / leaves a guild
  • /syncroles slash command (manual trigger, admin only)

Requires in .env:
  SUPABASE_URL           — your project URL
  SUPABASE_SERVICE_KEY   — service role key (bypasses RLS for writes)
  (falls back to SUPABASE_KEY if SERVICE_KEY isn't set)
"""

import os
import discord
from discord.ext import commands
from discord import app_commands
from supabase import create_client, Client
import logging

log = logging.getLogger(__name__)


class GuildSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Use service role key so writes bypass RLS — anon key will be rejected
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("GuildSync: SUPABASE_URL / SUPABASE_SERVICE_KEY not set in .env")
        self.supabase: Client = create_client(url, key)

    # ──────────────────────────────────────────────
    #  HELPERS
    # ──────────────────────────────────────────────

    def _build_row(self, member: discord.Member) -> dict:
        """Build a single user_guilds row from a Member object."""
        guild = member.guild
        return {
            "user_id":    str(member.id),
            "guild_id":   str(guild.id),
            "guild_name": guild.name,
            "guild_icon": str(guild.icon) if guild.icon else None,
            # Store raw integer as string — edge function does BigInt(permissions)
            "permissions": str(member.guild_permissions.value),
            "bot_present": True,
        }

    async def _upsert(self, rows: list[dict]):
        """Upsert a batch of rows into user_guilds."""
        if not rows:
            return
        try:
            # supabase-py v2 .execute() is synchronous — run in executor to avoid blocking
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.supabase.table("user_guilds")
                    .upsert(rows, on_conflict="user_id,guild_id")
                    .execute()
            )
        except Exception as e:
            log.error("user_guilds upsert failed: %s", e)

    async def _mark_bot_gone(self, guild_id: int):
        """When the bot leaves a guild, flip bot_present = false."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.supabase.table("user_guilds")
                    .update({"bot_present": False})
                    .eq("guild_id", str(guild_id))
                    .execute()
            )
        except Exception as e:
            log.error("mark_bot_gone failed for guild %s: %s", guild_id, e)

    async def _remove_member(self, user_id: int, guild_id: int):
        """Remove a specific member row when they leave."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.supabase.table("user_guilds")
                    .delete()
                    .eq("user_id", str(user_id))
                    .eq("guild_id", str(guild_id))
                    .execute()
            )
        except Exception as e:
            log.error("remove_member failed: %s", e)

    # ──────────────────────────────────────────────
    #  FULL SYNC (called on ready + slash command)
    # ──────────────────────────────────────────────

    async def _full_sync(self) -> int:
        """Sync every member of every guild the bot is in. Returns row count."""
        rows = []
        for guild in self.bot.guilds:
            # Fetch full member list (requires members intent)
            try:
                await guild.chunk()
            except Exception:
                pass  # chunking may fail in some configurations — that's ok

            for member in guild.members:
                if member.bot:
                    continue  # skip bots
                rows.append(self._build_row(member))

            # Batch upsert per guild to avoid huge payloads
            if len(rows) >= 200:
                await self._upsert(rows)
                rows = []

        if rows:
            await self._upsert(rows)

        return sum(len(g.members) for g in self.bot.guilds)

    # ──────────────────────────────────────────────
    #  EVENTS
    # ──────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("GuildSync: starting full sync across %d guilds…", len(self.bot.guilds))
        count = await self._full_sync()
        log.info("GuildSync: synced ~%d member rows.", count)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        await self._upsert([self._build_row(member)])

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        await self._remove_member(member.id, member.guild.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Re-sync when roles change (permissions may have changed)."""
        if after.bot:
            return
        if before.roles != after.roles:
            await self._upsert([self._build_row(after)])

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        log.info("GuildSync: bot joined %s — syncing members…", guild.name)
        try:
            await guild.chunk()
        except Exception:
            pass
        rows = [self._build_row(m) for m in guild.members if not m.bot]
        await self._upsert(rows)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        log.info("GuildSync: bot left %s — marking bot_present=false", guild.name)
        await self._mark_bot_gone(guild.id)

    # ──────────────────────────────────────────────
    #  SLASH COMMAND  —  /syncroles
    # ──────────────────────────────────────────────

    @app_commands.command(name="syncroles", description="[Admin] Force-sync all server members to the dashboard.")
    @app_commands.checks.has_permissions(administrator=True)
    async def syncroles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        count = await self._full_sync()
        await interaction.followup.send(
            f"✅ Synced **~{count}** member rows to the dashboard.",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildSync(bot))