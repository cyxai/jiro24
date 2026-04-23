# cogs/roles.py
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from utils.embeds import embed
from utils.config import icon


class Roles(commands.Cog):
    """Role management and self-assignable roles."""

    def __init__(self, bot):
        self.bot = bot

    # ── Add role ──────────────────────────────────────────────
    @commands.command(name="addrole")
    @commands.has_permissions(manage_roles=True)
    async def addrole_prefix(self, ctx, member: discord.Member, *, role: discord.Role):
        """Add a role to a member. ?addrole @user <role>"""
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=embed(
                f"{icon('error')} Can't Assign Role",
                "That role is higher than or equal to my highest role. "
                "Move my role above it in Server Settings.", color="error"))
        await member.add_roles(role)
        await ctx.send(embed=embed(
            f"{icon('role_add')} Added **{role.name}** to {member.mention}", color="success"))

    @app_commands.command(name="addrole", description="Add a role to a member")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def addrole_slash(self, interaction: discord.Interaction,
                            member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Can't Assign Role",
                "That role is above my highest role.", color="error"), ephemeral=True)
        await member.add_roles(role)
        await interaction.response.send_message(embed=embed(
            f"{icon('role_add')} Added **{role.name}** to {member.mention}", color="success"))

    # ── Remove role ───────────────────────────────────────────
    @commands.command(name="removerole")
    @commands.has_permissions(manage_roles=True)
    async def removerole_prefix(self, ctx, member: discord.Member, *, role: discord.Role):
        """Remove a role from a member. ?removerole @user <role>"""
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=embed(
                f"{icon('error')} Can't Remove Role",
                "That role is higher than or equal to my highest role.", color="error"))
        await member.remove_roles(role)
        await ctx.send(embed=embed(
            f"{icon('role_remove')} Removed **{role.name}** from {member.mention}", color="success"))

    @app_commands.command(name="removerole", description="Remove a role from a member")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def removerole_slash(self, interaction: discord.Interaction,
                               member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Can't Remove Role",
                "That role is above my highest role.", color="error"), ephemeral=True)
        await member.remove_roles(role)
        await interaction.response.send_message(embed=embed(
            f"{icon('role_remove')} Removed **{role.name}** from {member.mention}", color="success"))

    # ── Auto-role ─────────────────────────────────────────────
    @commands.command(name="setautorole")
    @commands.has_permissions(administrator=True)
    async def set_autorole(self, ctx, role: discord.Role):
        """Set a role to auto-assign on member join. ?setautorole <role>"""
        await self.bot.db.set_config(ctx.guild.id, "autorole_id", str(role.id))
        await ctx.send(embed=embed(
            f"{icon('ok')} Auto-role set to **{role.name}**",
            "New members will automatically receive this role.", color="success"))

    @commands.command(name="clearautorole")
    @commands.has_permissions(administrator=True)
    async def clear_autorole(self, ctx):
        """Clear the auto-role. ?clearautorole"""
        await self.bot.db.set_config(ctx.guild.id, "autorole_id", None)
        await ctx.send(embed=embed(f"{icon('ok')} Auto-role cleared.", color="success"))

    # ── Role info ─────────────────────────────────────────────
    @commands.command(name="roleinfo")
    async def roleinfo(self, ctx, *, role: discord.Role):
        """View info about a role. ?roleinfo <role>"""
        e = embed(f"{icon('role')} Role: {role.name}", color="info")
        e.colour = role.color
        e.add_field(name="ID",          value=str(role.id),           inline=True)
        e.add_field(name="Color",       value=str(role.color),        inline=True)
        e.add_field(name="Members",     value=str(len(role.members)), inline=True)
        e.add_field(name="Mentionable", value=str(role.mentionable),  inline=True)
        e.add_field(name="Hoisted",     value=str(role.hoist),        inline=True)
        e.add_field(name="Position",    value=str(role.position),     inline=True)
        e.add_field(name="Created",     value=role.created_at.strftime("%Y-%m-%d"), inline=True)
        await ctx.send(embed=e)

    # ── Self-assignable roles ─────────────────────────────────
    @commands.command(name="iam")
    async def iam(self, ctx, *, role: discord.Role):
        """Assign yourself a self-assignable role (or remove it if you have it).
        ?iam <role>"""
        self_roles = await self.bot.db.get_self_roles(ctx.guild.id)
        if str(role.id) not in self_roles:
            return await ctx.send(embed=embed(
                f"{icon('error')} Not Self-Assignable",
                f"**{role.name}** is not on the self-assignable list.\n"
                f"An admin can add it with `?addselfrole {role.name}`.", color="error"))
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(embed=embed(
                f"{icon('ok')} Removed **{role.name}** from you.", color="warn"))
        else:
            await ctx.author.add_roles(role)
            await ctx.send(embed=embed(
                f"{icon('ok')} Gave you **{role.name}**.", color="success"))

    @commands.command(name="iamnot")
    async def iamnot(self, ctx, *, role: discord.Role):
        """Remove a self-assigned role from yourself. ?iamnot <role>"""
        self_roles = await self.bot.db.get_self_roles(ctx.guild.id)
        if str(role.id) not in self_roles:
            return await ctx.send(embed=embed(
                f"{icon('error')} Not Self-Assignable",
                f"**{role.name}** is not on the self-assignable list.", color="error"))
        if role not in ctx.author.roles:
            return await ctx.send(embed=embed(
                f"{icon('warn')} You Don't Have That Role",
                f"You don't currently have **{role.name}**.", color="warn"))
        await ctx.author.remove_roles(role)
        await ctx.send(embed=embed(
            f"{icon('ok')} Removed **{role.name}** from you.", color="success"))

    @app_commands.command(name="iamnot", description="Remove a self-assigned role from yourself")
    async def iamnot_slash(self, interaction: discord.Interaction, role: discord.Role):
        self_roles = await self.bot.db.get_self_roles(interaction.guild.id)
        if str(role.id) not in self_roles:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Not Self-Assignable",
                f"**{role.name}** is not on the self-assignable list.", color="error"), ephemeral=True)
        if role not in interaction.user.roles:
            return await interaction.response.send_message(embed=embed(
                f"{icon('warn')} You Don't Have That Role",
                f"You don't currently have **{role.name}**.", color="warn"), ephemeral=True)
        await interaction.user.remove_roles(role)
        await interaction.response.send_message(embed=embed(
            f"{icon('ok')} Removed **{role.name}** from you.", color="success"))

    @commands.command(name="addselfrole")
    @commands.has_permissions(administrator=True)
    async def add_self_role(self, ctx, role: discord.Role):
        """Make a role self-assignable. ?addselfrole <role>"""
        await self.bot.db.add_self_role(ctx.guild.id, str(role.id))
        await ctx.send(embed=embed(
            f"{icon('ok')} **{role.name}** is now self-assignable.",
            "Members can use `?iam` to give themselves this role.", color="success"))

    @commands.command(name="removeselfrole")
    @commands.has_permissions(administrator=True)
    async def remove_self_role(self, ctx, role: discord.Role):
        """Remove a role from the self-assignable list. ?removeselfrole <role>"""
        config = await self.bot.db.get_config(ctx.guild.id)
        roles  = await self.bot.db.get_self_roles(ctx.guild.id)
        if str(role.id) not in roles:
            return await ctx.send(embed=embed(
                f"{icon('warn')} **{role.name}** is not in the self-assignable list.", color="warn"))
        roles.remove(str(role.id))
        config["self_roles"] = roles
        await self.bot.db.set_full_config(ctx.guild.id, config)
        await ctx.send(embed=embed(
            f"{icon('ok')} **{role.name}** removed from self-assignable list.", color="success"))

    @commands.command(name="listselfroles")
    async def list_self_roles(self, ctx):
        """List all self-assignable roles. ?listselfroles"""
        self_roles = await self.bot.db.get_self_roles(ctx.guild.id)
        if not self_roles:
            return await ctx.send(embed=embed(
                f"{icon('info')} No Self-Assignable Roles",
                "No roles have been made self-assignable yet.\n"
                "An admin can use `?addselfrole <role>` to add one.", color="info"))
        resolved = []
        for rid in self_roles:
            role = ctx.guild.get_role(int(rid))
            resolved.append(role.mention if role else f"`{rid}` (deleted)")
        e = embed(f"{icon('self_role')} Self-Assignable Roles", color="info")
        e.description = "Use `?iam <role>` to assign yourself one of these:\n\n" + "  ".join(resolved)
        await ctx.send(embed=e)

    # ── Mass role ─────────────────────────────────────────────
    @commands.command(name="massrole")
    @commands.has_permissions(administrator=True)
    async def massrole(self, ctx, action: str, *, role: discord.Role):
        """Add or remove a role from every member.
        ?massrole <add|remove> <role>"""
        action = action.lower()
        if action not in ("add", "remove"):
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Action",
                "Action must be `add` or `remove`.\n**Usage:** `?massrole <add|remove> <role>`",
                color="error"))
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=embed(
                f"{icon('error')} Role Too High",
                "That role is above my highest role. I can't assign it.", color="error"))

        members = [m for m in ctx.guild.members if not m.bot]
        progress = await ctx.send(embed=embed(
            f"{icon('progress')} Mass Role — Starting…",
            f"{'Adding' if action == 'add' else 'Removing'} **{role.name}** "
            f"{'to' if action == 'add' else 'from'} {len(members)} members…",
            color="info"))

        done, failed = 0, 0
        for i, member in enumerate(members):
            try:
                if action == "add":
                    await member.add_roles(role, reason=f"Mass role by {ctx.author}")
                else:
                    await member.remove_roles(role, reason=f"Mass role by {ctx.author}")
                done += 1
            except discord.Forbidden:
                failed += 1
            except discord.HTTPException:
                failed += 1

            # Rate-limit friendly: update progress every 10 members
            if (i + 1) % 10 == 0:
                await asyncio.sleep(0.5)
                try:
                    await progress.edit(embed=embed(
                        f"{icon('progress')} Mass Role — {i+1}/{len(members)}",
                        f"Done: {done}  |  Failed: {failed}", color="info"))
                except discord.HTTPException:
                    pass

        verb = "added to" if action == "add" else "removed from"
        result_color = "success" if failed == 0 else "warn"
        await progress.edit(embed=embed(
            f"{icon('ok')} Mass Role Complete",
            f"**{role.name}** {verb} **{done}** member(s)."
            + (f"\n{icon('warn')} Failed: {failed}" if failed else ""),
            color=result_color))


async def setup(bot):
    await bot.add_cog(Roles(bot))
