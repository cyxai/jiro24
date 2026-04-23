import discord
from discord.ext import commands
from utils.embeds import embed
from utils.config import icon
from datetime import datetime, timezone


class SharedModerationView(discord.ui.View):
    """
    Persistent button view for a shared moderation embed.
    Looks up the record by message_id so buttons survive bot restarts.
    """

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _get_record_for(self, interaction: discord.Interaction):
        return await self.bot.db.get_shared_mod_by_message(str(interaction.message.id))

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary,
                       custom_id="sharedmod:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            record = await self._get_record_for(interaction)
        except Exception:
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Database error. Try again.", color="error"), ephemeral=True)
        if not record:
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Moderation record not found.", color="error"), ephemeral=True)
        if record["status"] == "claimed":
            return await interaction.followup.send(
                embed=embed(f"{icon('warn')} Already claimed by <@{record['claimed_by']}>.", color="warn"), ephemeral=True)
        if record["status"] == "donated":
            return await interaction.followup.send(
                embed=embed(f"{icon('warn')} This moderation has already been donated.", color="warn"), ephemeral=True)

        mod_id = record["id"]
        try:
            await self.bot.db.claim_shared_mod(mod_id, interaction.user.id)
            await self.bot.db.update_modtrack(interaction.guild.id, interaction.user.id, "claimed")
        except Exception:
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Failed to save claim. Try again.", color="error"), ephemeral=True)

        await interaction.followup.send(
            embed=embed(f"{icon('claim')} Claimed!",
                        f"{interaction.user.mention} claimed moderation **#{mod_id}**.", color="success"))
        await _refresh_embed(interaction.message, mod_id, self.bot)

    @discord.ui.button(label="Donate", style=discord.ButtonStyle.success,
                       custom_id="sharedmod:donate")
    async def donate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DonateModal(str(interaction.message.id), self.bot))

    @discord.ui.button(label="Leave Open", style=discord.ButtonStyle.secondary,
                       custom_id="sharedmod:leave")
    async def leave_open(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            record = await self._get_record_for(interaction)
        except Exception:
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Database error. Try again.", color="error"), ephemeral=True)
        if not record:
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Moderation record not found.", color="error"), ephemeral=True)
        await interaction.followup.send(
            embed=embed(f"{icon('open')} Left open.",
                        f"Moderation **#{record['id']}** stays open for others to claim.", color="info"),
            ephemeral=True)


class DonateModal(discord.ui.Modal, title="Donate Moderation"):
    recipient = discord.ui.TextInput(
        label="Recipient User ID",
        placeholder="Enter a Discord user ID...",
        max_length=20,
    )

    def __init__(self, message_id: str, bot):
        super().__init__()
        self.message_id = message_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            record = await self.bot.db.get_shared_mod_by_message(self.message_id)
        except Exception:
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Database error. Try again.", color="error"), ephemeral=True)
        if not record:
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Moderation record not found.", color="error"), ephemeral=True)
        if str(interaction.user.id) != str(record["mod_id"]):
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Only the original moderator can donate this.", color="error"), ephemeral=True)
        if record["status"] == "donated":
            return await interaction.followup.send(
                embed=embed(f"{icon('warn')} Already donated.", color="warn"), ephemeral=True)

        try:
            recipient_id = int(self.recipient.value.strip())
            recipient    = await interaction.guild.fetch_member(recipient_id)
        except (ValueError, discord.NotFound):
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Invalid user ID or user not in server.", color="error"), ephemeral=True)
        if recipient.id == interaction.user.id:
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} You can't donate to yourself.", color="error"), ephemeral=True)

        mod_id = record["id"]
        try:
            await self.bot.db.donate_shared_mod(mod_id, interaction.user.id, recipient.id)
            await self.bot.db.update_modtrack(interaction.guild.id, interaction.user.id, "donated")
            await self.bot.db.update_modtrack(interaction.guild.id, recipient.id, "received_donation")
        except Exception:
            return await interaction.followup.send(
                embed=embed(f"{icon('error')} Failed to save donation. Try again.", color="error"), ephemeral=True)

        await interaction.followup.send(
            embed=embed(f"{icon('donate')} Donated!",
                        f"Moderation **#{mod_id}** donated to {recipient.mention}.", color="success"))

        if record.get("channel_id") and record.get("message_id"):
            try:
                ch = interaction.guild.get_channel(int(record["channel_id"]))
                if ch:
                    msg = await ch.fetch_message(int(record["message_id"]))
                    await _refresh_embed(msg, mod_id, self.bot)
            except discord.HTTPException:
                pass


def build_shared_mod_embed(record: dict) -> discord.Embed:
    status = record.get("status", "open")
    status_map = {
        "open":    f"{icon('open')} Open for claim",
        "claimed": f"{icon('claim')} Claimed by <@{record.get('claimed_by', '?')}>",
        "donated": f"{icon('donate')} Donated to <@{record.get('donated_to', '?')}>",
    }
    color_hex = {"open": 0x57F287, "claimed": 0x5865F2, "donated": 0xEB459E}.get(status, 0x5865F2)

    e = discord.Embed(
        title=f"{icon('sharedmod')} Shared Moderation #{record['id']} — {record['action'].upper()}",
        color=color_hex,
        timestamp=datetime.now(timezone.utc),
    )
    e.add_field(name=f"{icon('target')} User",      value=f"<@{record['target_id']}> (`{record['target_id']}`)", inline=True)
    e.add_field(name=f"{icon('mod')} Moderator",    value=f"<@{record['mod_id']}>",                              inline=True)
    e.add_field(name=f"{icon('reason')} Reason",    value=record.get("reason") or "No reason",                  inline=False)
    if record.get("duration"):
        e.add_field(name=f"{icon('duration')} Duration", value=record["duration"], inline=True)
    e.add_field(name=f"{icon('stats')} Status", value=status_map.get(status, status), inline=True)

    def _ts(iso):
        try:
            return f"<t:{int(datetime.fromisoformat(iso).timestamp())}:R>"
        except Exception:
            return iso

    if record.get("claimed_at"):
        e.add_field(name="Claimed At", value=_ts(record["claimed_at"]), inline=True)
    if record.get("donated_at"):
        e.add_field(name="Donated At", value=_ts(record["donated_at"]), inline=True)

    e.set_footer(text="Shared Moderation System • Jiro")
    return e


async def _refresh_embed(message: discord.Message, mod_id: int, bot):
    if not message:
        return
    record = await bot.db.get_shared_mod(mod_id)
    if record:
        try:
            await message.edit(embed=build_shared_mod_embed(record))
        except discord.HTTPException:
            pass


class SharedModeration(commands.Cog):
    """Shared moderation system — post, claim, donate moderations."""

    def __init__(self, bot):
        self.bot = bot
        bot.add_view(SharedModerationView(bot))

    @commands.command(name="sharemod", aliases=["sharedmod", "sm"])
    @commands.has_permissions(moderate_members=True)
    async def sharemod(self, ctx, member: discord.Member, action: str,
                       duration: str = None, *, reason: str = "No reason provided"):
        """Post a shared moderation with claim/donate buttons.
        Usage: !sharemod @user mute 10m Spamming in general"""
        config = await self.bot.db.get_config(ctx.guild.id)
        shared_channel_id = config.get("shared_mod_channel_id")
        if not shared_channel_id:
            return await ctx.send(embed=embed(
                f"{icon('error')} No shared mod channel set.",
                "An admin must run `!setsharedchannel #channel` first.", color="error"))

        ch = ctx.guild.get_channel(int(shared_channel_id))
        if not ch:
            return await ctx.send(embed=embed(f"{icon('error')} Shared mod channel not found.", color="error"))

        record = await self.bot.db.create_shared_mod(
            guild_id=ctx.guild.id, mod_id=ctx.author.id, target_id=member.id,
            action=action, reason=reason, duration=duration)
        await self.bot.db.update_modtrack(ctx.guild.id, ctx.author.id, "modded")

        mod_id = record["id"]
        view = SharedModerationView(self.bot)
        msg = await ch.send(embed=build_shared_mod_embed(record), view=view)
        await self.bot.db.update_shared_mod_message(mod_id, ch.id, msg.id)

        await ctx.send(embed=embed(f"{icon('ok')} Shared!",
                                   f"Moderation posted to {ch.mention} as **#{mod_id}**.", color="success"))

    @commands.command(name="modtrack")
    @commands.has_permissions(moderate_members=True)
    async def modtrack(self, ctx, member: discord.Member = None):
        """Show moderation stats for yourself or another mod."""
        target    = member or ctx.author
        stats     = await self.bot.db.get_modtrack(ctx.guild.id, target.id)
        donations = await self.bot.db.get_received_donations(ctx.guild.id, target.id)

        e = discord.Embed(title=f"{icon('track')} Mod Track — {target.display_name}",
                          color=0xEB459E, timestamp=datetime.now(timezone.utc))
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="Moderations Done",   value=str(stats.get("modded",            0)), inline=True)
        e.add_field(name="Claimed",            value=str(stats.get("claimed",           0)), inline=True)
        e.add_field(name="Donated Away",       value=str(stats.get("donated",           0)), inline=True)
        e.add_field(name="Received Donations", value=str(stats.get("received_donation", 0)), inline=True)

        if donations:
            lines = [
                f"• <@{d['from_mod_id']}> → mod **#{d['mod_id']}** ({d['action']})"
                for d in donations[:5]
            ]
            if len(donations) > 5:
                lines.append(f"*…and {len(donations) - 5} more*")
            e.add_field(name="Donations Received From", value="\n".join(lines), inline=False)
        else:
            e.add_field(name="Donations Received From", value="None yet", inline=False)

        e.set_footer(text="Shared Moderation System • Jiro")
        await ctx.send(embed=e)

    @commands.command(name="setsharedchannel")
    @commands.has_permissions(administrator=True)
    async def set_shared_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where shared moderations are posted."""
        await self.bot.db.set_config(ctx.guild.id, "shared_mod_channel_id", channel.id)
        await ctx.send(embed=embed(f"{icon('ok')} Shared mod channel set!",
                                   f"Shared moderations will be posted to {channel.mention}.", color="success"))

    @commands.command(name="sharedlist", aliases=["sml"])
    @commands.has_permissions(moderate_members=True)
    async def sharedlist(self, ctx, status: str = "open"):
        """List shared moderations. Status: open / claimed / donated / all"""
        valid = ("open", "claimed", "donated", "all")
        if status not in valid:
            return await ctx.send(embed=embed(
                f"{icon('error')} Status must be one of: {', '.join(valid)}", color="error"))

        records = await self.bot.db.list_shared_mods(ctx.guild.id, status if status != "all" else None)
        if not records:
            return await ctx.send(embed=embed(f"{icon('open')} No {status} shared moderations.", color="info"))

        status_icons = {"open": icon("open"), "claimed": icon("claim"), "donated": icon("donate")}
        lines = [
            f"{status_icons.get(r['status'], '-')} **#{r['id']}** — `{r['action']}` on <@{r['target_id']}> by <@{r['mod_id']}>"
            for r in records[:15]
        ]
        e = discord.Embed(
            title=f"{icon('sharedmod')} Shared Moderations — {status.capitalize()}",
            description="\n".join(lines),
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )
        if len(records) > 15:
            e.set_footer(text=f"Showing 15 of {len(records)} records.")
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(SharedModeration(bot))
