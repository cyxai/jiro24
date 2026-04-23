import discord
from discord.ext import commands
from discord import app_commands
from collections import defaultdict, deque
from datetime import datetime, timedelta
import re
from utils.embeds import embed
from utils.config import icon

INVITE_RE = re.compile(r"(discord\.gg|discord\.com/invite)/[a-zA-Z0-9]+", re.IGNORECASE)
URL_RE    = re.compile(r"https?://\S+", re.IGNORECASE)


class AutoMod(commands.Cog):
    """Automatic moderation: spam, links, bad words."""

    def __init__(self, bot):
        self.bot = bot
        self.message_cache: dict[int, dict[int, deque]] = defaultdict(lambda: defaultdict(deque))

    def is_immune(self, member: discord.Member) -> bool:
        if member.bot:
            return True
        return member.guild_permissions.manage_messages

    async def punish(self, message: discord.Message, reason: str):
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            until = discord.utils.utcnow() + timedelta(minutes=60)
            await message.author.timeout(until, reason=reason)
        except discord.Forbidden:
            pass
        try:
            await message.channel.send(
                embed=embed(f"{icon('automod')} {message.author.mention} — {reason}", color="error"),
                delete_after=15,
            )
        except discord.HTTPException:
            pass
        await self.bot.db.add_log(
            message.guild.id, f"AutoMod: {reason}",
            self.bot.user.id, message.author.id, reason,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or self.is_immune(message.author):
            return

        config = await self.bot.db.get_config(message.guild.id)
        db = self.bot.db

        if not db._bool(config.get("automod_enabled"), default=True):
            return

        content  = message.content
        guild_id = message.guild.id
        user_id  = message.author.id

        spam_limit  = db._int(config.get("spam_limit"),  default=5)
        spam_window = db._int(config.get("spam_window"), default=5)

        user_cache = self.message_cache[guild_id][user_id]
        now = datetime.utcnow()
        user_cache.append(now)
        while user_cache and (now - user_cache[0]).total_seconds() > spam_window:
            user_cache.popleft()

        if len(user_cache) > spam_limit:
            user_cache.clear()
            await self.punish(message, "Spamming messages")
            return

        if db._bool(config.get("block_invites"), default=True):
            if INVITE_RE.search(content):
                await self.punish(message, "Posting Discord invite links")
                return

        if db._bool(config.get("block_links"), default=False):
            if URL_RE.search(content):
                await self.punish(message, "Posting external links")
                return

        bad_words = await self.bot.db.get_bad_words(guild_id)
        lower = content.lower()
        for word in bad_words:
            if word in lower:
                await self.punish(message, "Using prohibited language")
                return

    # ── Config commands ────────────────────────────────────────
    @commands.group(name="automod", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def automod_group(self, ctx: commands.Context):
        """Show current auto-mod settings."""
        config = await self.bot.db.get_config(ctx.guild.id)
        db = self.bot.db
        e = embed(f"{icon('automod')} Auto-Mod Settings", color="info")
        e.add_field(name="Enabled",       value=icon("ok") if db._bool(config.get("automod_enabled"), True) else icon("error"), inline=True)
        e.add_field(name="Block Invites", value=icon("ok") if db._bool(config.get("block_invites"),   True) else icon("error"), inline=True)
        e.add_field(name="Block Links",   value=icon("ok") if db._bool(config.get("block_links"),     False) else icon("error"), inline=True)
        e.add_field(name="Spam Limit",
                    value=f"{db._int(config.get('spam_limit'), 5)} msgs / {db._int(config.get('spam_window'), 5)}s",
                    inline=True)
        bad_words = await self.bot.db.get_bad_words(ctx.guild.id)
        e.add_field(name="Bad Words", value=str(len(bad_words)), inline=True)
        await ctx.send(embed=e)

    @automod_group.command(name="toggle")
    @commands.has_permissions(administrator=True)
    async def automod_toggle(self, ctx: commands.Context):
        config  = await self.bot.db.get_config(ctx.guild.id)
        current = self.bot.db._bool(config.get("automod_enabled"), True)
        await self.bot.db.set_config(ctx.guild.id, "automod_enabled", not current)
        status = f"{icon('ok')} Enabled" if not current else f"{icon('error')} Disabled"
        await ctx.send(embed=embed(f"Auto-Mod {status}", color="success"))

    @automod_group.command(name="addbadword")
    @commands.has_permissions(administrator=True)
    async def add_bad_word(self, ctx: commands.Context, *, word: str):
        await self.bot.db.add_bad_word(ctx.guild.id, word.lower())
        await ctx.send(embed=embed(f"{icon('ok')} Added `{word}` to the bad word list.", color="success"))

    @automod_group.command(name="removebadword")
    @commands.has_permissions(administrator=True)
    async def remove_bad_word(self, ctx: commands.Context, *, word: str):
        await self.bot.db.remove_bad_word(ctx.guild.id, word.lower())
        await ctx.send(embed=embed(f"{icon('ok')} Removed `{word}` from the bad word list.", color="success"))

    @automod_group.command(name="listbadwords")
    @commands.has_permissions(administrator=True)
    async def list_bad_words(self, ctx: commands.Context):
        words = await self.bot.db.get_bad_words(ctx.guild.id)
        if not words:
            return await ctx.send(embed=embed("No bad words configured.", color="info"))
        await ctx.send(embed=embed(f"{icon('badword')} Bad Word List",
                                   ", ".join(f"`{w}`" for w in words), color="warn"))

    @automod_group.command(name="invites")
    @commands.has_permissions(administrator=True)
    async def toggle_invites(self, ctx: commands.Context):
        config  = await self.bot.db.get_config(ctx.guild.id)
        current = self.bot.db._bool(config.get("block_invites"), True)
        await self.bot.db.set_config(ctx.guild.id, "block_invites", not current)
        status = f"{icon('lock')} Blocking" if not current else f"{icon('unlock')} Allowing"
        await ctx.send(embed=embed(f"{status} Discord invite links", color="info"))

    @automod_group.command(name="links")
    @commands.has_permissions(administrator=True)
    async def toggle_links(self, ctx: commands.Context):
        config  = await self.bot.db.get_config(ctx.guild.id)
        current = self.bot.db._bool(config.get("block_links"), False)
        await self.bot.db.set_config(ctx.guild.id, "block_links", not current)
        status = f"{icon('lock')} Blocking" if not current else f"{icon('unlock')} Allowing"
        await ctx.send(embed=embed(f"{status} external links", color="info"))

    @automod_group.command(name="spamconfig")
    @commands.has_permissions(administrator=True)
    async def spam_config(self, ctx: commands.Context, limit: int, window: int):
        """Set spam thresholds. ?automod spamconfig <msg_limit> <seconds>"""
        if limit < 2 or limit > 50:
            return await ctx.send(embed=embed(f"{icon('error')} Limit must be between 2 and 50.", color="error"))
        if window < 1 or window > 60:
            return await ctx.send(embed=embed(f"{icon('error')} Window must be between 1 and 60 seconds.", color="error"))
        config = await self.bot.db.get_config(ctx.guild.id)
        config["spam_limit"]  = limit
        config["spam_window"] = window
        await self.bot.db.set_full_config(ctx.guild.id, config)
        await ctx.send(embed=embed(f"{icon('ok')} Spam detection: {limit} messages per {window}s.", color="success"))


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
