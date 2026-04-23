import discord
from discord.ext import commands
from discord import app_commands
from utils.embeds import embed
from utils.config import icon


class Welcome(commands.Cog):
    """Welcome/leave messages and auto-role on member join."""

    def __init__(self, bot):
        self.bot = bot

    def format_message(self, template: str, member: discord.Member) -> str:
        return (
            template
            .replace("{user}",     member.mention)
            .replace("{username}", member.display_name)
            .replace("{server}",   member.guild.name)
            .replace("{count}",    str(member.guild.member_count))
        )

    # ─────────────────────────────────────────────────────────
    # WELCOME SETUP
    # ─────────────────────────────────────────────────────────

    @commands.command(name="setwelcome")
    @commands.has_permissions(administrator=True)
    async def set_welcome_prefix(self, ctx, channel: discord.TextChannel = None):
        """Set the welcome channel. ?setwelcome [#channel]"""
        channel = channel or ctx.channel
        await self.bot.db.set_config(ctx.guild.id, "welcome_channel_id", str(channel.id))
        await ctx.send(embed=embed(
            f"{icon('welcome')} Welcome channel set to {channel.mention}", color="success"))

    @app_commands.command(name="setwelcome", description="Set the welcome channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_welcome_slash(self, interaction: discord.Interaction,
                                channel: discord.TextChannel = None):
        channel = channel or interaction.channel
        await self.bot.db.set_config(interaction.guild.id, "welcome_channel_id", str(channel.id))
        await interaction.response.send_message(embed=embed(
            f"{icon('welcome')} Welcome channel set to {channel.mention}", color="success"))

    @commands.command(name="setwelcomemsg")
    @commands.has_permissions(administrator=True)
    async def set_welcome_msg_prefix(self, ctx, *, message: str):
        """Set the welcome message. ?setwelcomemsg <message>
        Placeholders: {user}, {username}, {server}, {count}"""
        await self.bot.db.set_config(ctx.guild.id, "welcome_message", message)
        e = embed(f"{icon('ok')} Welcome message updated.", color="success")
        e.add_field(name="Preview", value=self.format_message(message, ctx.author)[:500], inline=False)
        e.set_footer(text="Placeholders: {user}, {username}, {server}, {count}")
        await ctx.send(embed=e)

    @app_commands.command(name="setwelcomemsg",
                          description="Set the welcome message ({user}, {server}, {count})")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_welcome_msg_slash(self, interaction: discord.Interaction, message: str):
        await self.bot.db.set_config(interaction.guild.id, "welcome_message", message)
        e = embed(f"{icon('ok')} Welcome message updated.", color="success")
        e.add_field(name="Preview",
                    value=self.format_message(message, interaction.user)[:500], inline=False)
        e.set_footer(text="Placeholders: {user}, {username}, {server}, {count}")
        await interaction.response.send_message(embed=e)

    @commands.command(name="togglewelcome")
    @commands.has_permissions(administrator=True)
    async def toggle_welcome(self, ctx):
        """Toggle welcome messages on/off. ?togglewelcome"""
        config  = await self.bot.db.get_config(ctx.guild.id)
        current = self.bot.db._bool(config.get("welcome_enabled"), True)
        await self.bot.db.set_config(ctx.guild.id, "welcome_enabled", not current)
        status = f"{icon('ok')} Enabled" if not current else f"{icon('error')} Disabled"
        await ctx.send(embed=embed(f"Welcome messages {status}", color="success"))

    @commands.command(name="testwelcome")
    @commands.has_permissions(administrator=True)
    async def test_welcome_prefix(self, ctx):
        """Fire a test welcome message. ?testwelcome"""
        await self._send_welcome(ctx.author)
        await ctx.send(embed=embed(
            f"{icon('ok')} Test welcome sent!",
            "Check the configured welcome channel.", color="success"), delete_after=8)

    @app_commands.command(name="testwelcome", description="Test the welcome message")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_welcome_slash(self, interaction: discord.Interaction):
        await self._send_welcome(interaction.user)
        await interaction.response.send_message(embed=embed(
            f"{icon('ok')} Test welcome sent!", color="success"), ephemeral=True)

    # ─────────────────────────────────────────────────────────
    # LEAVE / GOODBYE SETUP
    # ─────────────────────────────────────────────────────────

    @commands.command(name="setleave")
    @commands.has_permissions(administrator=True)
    async def set_leave_prefix(self, ctx, channel: discord.TextChannel = None):
        """Set the leave / goodbye channel. ?setleave [#channel]"""
        channel = channel or ctx.channel
        await self.bot.db.set_config(ctx.guild.id, "leave_channel_id", str(channel.id))
        await ctx.send(embed=embed(
            f"{icon('leave')} Leave channel set to {channel.mention}", color="success"))

    @app_commands.command(name="setleave", description="Set the goodbye/leave channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_leave_slash(self, interaction: discord.Interaction,
                              channel: discord.TextChannel = None):
        channel = channel or interaction.channel
        await self.bot.db.set_config(interaction.guild.id, "leave_channel_id", str(channel.id))
        await interaction.response.send_message(embed=embed(
            f"{icon('leave')} Leave channel set to {channel.mention}", color="success"))

    @commands.command(name="setleavemsg")
    @commands.has_permissions(administrator=True)
    async def set_leave_msg_prefix(self, ctx, *, message: str):
        """Set the leave message. ?setleavemsg <message>
        Placeholders: {user}, {username}, {server}"""
        await self.bot.db.set_config(ctx.guild.id, "leave_message", message)
        e = embed(f"{icon('ok')} Leave message updated.", color="success")
        e.add_field(name="Preview",
                    value=self.format_message(message, ctx.author)[:500], inline=False)
        e.set_footer(text="Placeholders: {user}, {username}, {server}")
        await ctx.send(embed=e)

    @app_commands.command(name="setleavemsg",
                          description="Set the leave message ({user}, {username}, {server})")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_leave_msg_slash(self, interaction: discord.Interaction, message: str):
        await self.bot.db.set_config(interaction.guild.id, "leave_message", message)
        e = embed(f"{icon('ok')} Leave message updated.", color="success")
        e.add_field(name="Preview",
                    value=self.format_message(message, interaction.user)[:500], inline=False)
        e.set_footer(text="Placeholders: {user}, {username}, {server}")
        await interaction.response.send_message(embed=e)

    @commands.command(name="toggleleave")
    @commands.has_permissions(administrator=True)
    async def toggle_leave(self, ctx):
        """Toggle leave messages on/off. ?toggleleave"""
        config  = await self.bot.db.get_config(ctx.guild.id)
        current = self.bot.db._bool(config.get("leave_enabled"), True)
        await self.bot.db.set_config(ctx.guild.id, "leave_enabled", not current)
        status = f"{icon('ok')} Enabled" if not current else f"{icon('error')} Disabled"
        await ctx.send(embed=embed(f"Leave messages {status}", color="success"))

    @commands.command(name="testleave")
    @commands.has_permissions(administrator=True)
    async def test_leave_prefix(self, ctx):
        """Fire a test leave message. ?testleave"""
        await self._send_leave(ctx.author)
        await ctx.send(embed=embed(
            f"{icon('ok')} Test leave message sent!", color="success"), delete_after=8)

    # ─────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────

    async def _send_welcome(self, member: discord.Member):
        config = await self.bot.db.get_config(member.guild.id)
        db = self.bot.db

        if not db._bool(config.get("welcome_enabled"), default=True):
            return

        channel_id = config.get("welcome_channel_id")
        if not channel_id:
            return
        try:
            channel = member.guild.get_channel(int(channel_id))
        except (ValueError, TypeError):
            return
        if not channel:
            return

        template = config.get(
            "welcome_message",
            f"{icon('welcome')} Welcome to **{{server}}**, {{user}}! "
            "You are member **#{count}**.",
        )
        message_text = self.format_message(template, member)

        e = embed(f"{icon('welcome')} Welcome to {member.guild.name}!", color="success")
        e.description = message_text
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Account Created",
                    value=member.created_at.strftime("%Y-%m-%d"), inline=True)
        e.add_field(name=f"{icon('count')} Member",
                    value=f"#{member.guild.member_count}", inline=True)
        try:
            await channel.send(embed=e)
        except discord.HTTPException:
            pass

    async def _send_leave(self, member: discord.Member):
        config = await self.bot.db.get_config(member.guild.id)
        db = self.bot.db

        if not db._bool(config.get("leave_enabled"), default=True):
            return

        channel_id = config.get("leave_channel_id")
        if not channel_id:
            return
        try:
            channel = member.guild.get_channel(int(channel_id))
        except (ValueError, TypeError):
            return
        if not channel:
            return

        template = config.get(
            "leave_message",
            f"{icon('leave')} **{{username}}** has left **{{server}}**. Goodbye!",
        )
        message_text = self.format_message(template, member)

        e = embed(f"{icon('leave')} {member.display_name} left.", color="error")
        e.description = message_text
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Joined",
                    value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "Unknown",
                    inline=True)
        try:
            await channel.send(embed=e)
        except discord.HTTPException:
            pass

    # ─────────────────────────────────────────────────────────
    # EVENT LISTENERS
    # ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._send_welcome(member)

        config = await self.bot.db.get_config(member.guild.id)
        autorole_id = config.get("autorole_id")
        if autorole_id:
            try:
                role = member.guild.get_role(int(autorole_id))
                if role:
                    await member.add_roles(role, reason="Auto-role on join")
            except (ValueError, discord.Forbidden):
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._send_leave(member)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
