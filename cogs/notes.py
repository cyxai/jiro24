"""
cogs/notes.py — Private staff notes
07Dipper / Jiro • NixAI • by Blueey

Separate from warnings — notes are internal staff annotations never
shown to the target user.

Supabase table required:
  staff_notes (
    id          BIGSERIAL PRIMARY KEY,
    guild_id    TEXT,
    target_id   TEXT,
    mod_id      TEXT,
    note        TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
  )

Commands  (all require Manage Messages or higher)
  !note add @user <text>      Add a note to a user.
  !note list @user            View all notes for a user.
  !note remove @user <id>     Delete a specific note by ID.
  !note clear @user           Delete all notes for a user.
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import icon
from utils.embeds import embed


class Notes(commands.Cog):
    """Private staff notes attached to members."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _require_mod(self):
        return commands.has_permissions(manage_messages=True)

    # ── note add ──────────────────────────────────────────────────────────────

    @commands.group(name="note", invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def note_group(self, ctx: commands.Context):
        """Note management.  !note add | list | remove | clear"""
        await ctx.send(embed=embed(
            f"{icon('note')} Note Commands",
            "`!note add @user <text>`\n"
            "`!note list @user`\n"
            "`!note remove @user <id>`\n"
            "`!note clear @user`",
            color="info",
        ))

    @note_group.command(name="add")
    @commands.has_permissions(manage_messages=True)
    async def note_add(self, ctx: commands.Context, member: discord.Member, *, note: str):
        """Add a note to a member.  !note add @user <text>"""
        try:
            rows = await self.bot.db._post("staff_notes", {
                "guild_id":  str(ctx.guild.id),
                "target_id": str(member.id),
                "mod_id":    str(ctx.author.id),
                "note":      note[:1000],
            })
            nid = rows[0]["id"] if rows else "?"
        except Exception as e:
            return await ctx.send(embed=embed(f"{icon('error')} Failed", str(e), color="error"))
        await ctx.send(embed=embed(
            f"{icon('note')} Note Added",
            f"Note `#{nid}` added to {member.mention}.\n> *{note[:200]}*",
            color="success",
        ))

    # ── note list ─────────────────────────────────────────────────────────────

    @note_group.command(name="list")
    @commands.has_permissions(manage_messages=True)
    async def note_list(self, ctx: commands.Context, member: discord.Member):
        """View all notes for a member.  !note list @user"""
        try:
            rows = await self.bot.db._get("staff_notes", {
                "guild_id":  f"eq.{ctx.guild.id}",
                "target_id": f"eq.{member.id}",
                "order":     "created_at.asc",
            })
        except Exception:
            rows = []
        if not rows:
            return await ctx.send(embed=embed(
                f"{icon('note')} Notes for {member.display_name}",
                "No notes found.", color="info",
            ))
        lines = []
        for row in rows:
            mod = ctx.guild.get_member(int(row["mod_id"]))
            mod_name = mod.display_name if mod else f"User {row['mod_id']}"
            ts   = row.get("created_at", "")[:10]
            text = row["note"][:120] + ("..." if len(row["note"]) > 120 else "")
            lines.append(f"`#{row['id']}` [{ts}] **{mod_name}:** {text}")
        e = embed(
            f"{icon('note')} Notes for {member.display_name} ({len(rows)})",
            "\n".join(lines),
            color="info",
        )
        e.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=e)

    # ── note remove ───────────────────────────────────────────────────────────

    @note_group.command(name="remove")
    @commands.has_permissions(manage_messages=True)
    async def note_remove(self, ctx: commands.Context, member: discord.Member, note_id: int):
        """Delete a specific note.  !note remove @user <id>"""
        try:
            rows = await self.bot.db._get("staff_notes", {
                "id":        f"eq.{note_id}",
                "guild_id":  f"eq.{ctx.guild.id}",
                "target_id": f"eq.{member.id}",
            })
        except Exception:
            rows = []
        if not rows:
            return await ctx.send(embed=embed(
                f"{icon('error')} Not Found",
                f"Note `#{note_id}` not found for {member.mention}.", color="error",
            ))
        try:
            await self.bot.db._delete("staff_notes", {"id": str(note_id)})
        except Exception as e:
            return await ctx.send(embed=embed(f"{icon('error')} Failed", str(e), color="error"))
        await ctx.send(embed=embed(
            f"{icon('ok')} Note Removed",
            f"Note `#{note_id}` for {member.mention} has been deleted.", color="success",
        ))

    # ── note clear ────────────────────────────────────────────────────────────

    @note_group.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def note_clear(self, ctx: commands.Context, member: discord.Member):
        """Delete ALL notes for a member.  !note clear @user  (Admin only)"""
        try:
            await self.bot.db._delete("staff_notes", {
                "guild_id":  str(ctx.guild.id),
                "target_id": str(member.id),
            })
        except Exception as e:
            return await ctx.send(embed=embed(f"{icon('error')} Failed", str(e), color="error"))
        await ctx.send(embed=embed(
            f"{icon('ok')} Notes Cleared",
            f"All notes for {member.mention} have been deleted.", color="success",
        ))

    # ── Slash: /note ──────────────────────────────────────────────────────────

    note_slash = app_commands.Group(name="note", description="Private staff notes")

    @note_slash.command(name="add", description="Add a private staff note to a member")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(member="Target member", note="Note content")
    async def note_add_slash(self, interaction: discord.Interaction, member: discord.Member, note: str):
        try:
            rows = await self.bot.db._post("staff_notes", {
                "guild_id":  str(interaction.guild.id),
                "target_id": str(member.id),
                "mod_id":    str(interaction.user.id),
                "note":      note[:1000],
            })
            nid = rows[0]["id"] if rows else "?"
        except Exception as e:
            return await interaction.response.send_message(
                embed=embed(f"{icon('error')} Failed", str(e), color="error"), ephemeral=True)
        await interaction.response.send_message(embed=embed(
            f"{icon('note')} Note Added",
            f"Note `#{nid}` added to {member.mention}.",
            color="success",
        ), ephemeral=True)

    @note_slash.command(name="list", description="View all staff notes for a member")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(member="Target member")
    async def note_list_slash(self, interaction: discord.Interaction, member: discord.Member):
        try:
            rows = await self.bot.db._get("staff_notes", {
                "guild_id":  f"eq.{interaction.guild.id}",
                "target_id": f"eq.{member.id}",
                "order":     "created_at.asc",
            })
        except Exception:
            rows = []
        if not rows:
            return await interaction.response.send_message(embed=embed(
                f"{icon('note')} Notes for {member.display_name}", "No notes found.", color="info",
            ), ephemeral=True)
        lines = []
        for row in rows:
            ts   = row.get("created_at", "")[:10]
            text = row["note"][:120] + ("..." if len(row["note"]) > 120 else "")
            lines.append(f"`#{row['id']}` [{ts}] {text}")
        await interaction.response.send_message(embed=embed(
            f"{icon('note')} Notes for {member.display_name} ({len(rows)})",
            "\n".join(lines), color="info",
        ), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Notes(bot))
