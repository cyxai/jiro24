import discord
from discord.ext import commands
from discord import app_commands
from utils.embeds import embed
from utils.config import icon
import random
import asyncio
import re

EIGHT_BALL_RESPONSES = [
    f"{icon('ok')} It is certain.",
    f"{icon('ok')} It is decidedly so.",
    f"{icon('ok')} Without a doubt.",
    f"{icon('ok')} Yes, definitely.",
    f"{icon('ok')} You may rely on it.",
    f"{icon('ok')} As I see it, yes.",
    f"{icon('ok')} Most likely.",
    f"{icon('ok')} Outlook good.",
    f"{icon('ok')} Yes.",
    f"{icon('ok')} Signs point to yes.",
    f"{icon('warn')} Reply hazy, try again.",
    f"{icon('warn')} Ask again later.",
    f"{icon('warn')} Better not tell you now.",
    f"{icon('warn')} Cannot predict now.",
    f"{icon('warn')} Concentrate and ask again.",
    f"{icon('error')} Don't count on it.",
    f"{icon('error')} My reply is no.",
    f"{icon('error')} My sources say no.",
    f"{icon('error')} Outlook not so good.",
    f"{icon('error')} Very doubtful.",
]

JOKES = [
    ("Why don't scientists trust atoms?", "Because they make up everything!"),
    ("Why did the scarecrow win an award?", "Because he was outstanding in his field!"),
    ("I'm reading a book about anti-gravity.", "It's impossible to put down!"),
    ("Did you hear about the mathematician who's afraid of negative numbers?", "He'll stop at nothing to avoid them."),
    ("Why do programmers prefer dark mode?", "Because light attracts bugs!"),
    ("How many programmers does it take to change a light bulb?", "None — that's a hardware problem."),
    ("Why was the JavaScript developer sad?", "Because he didn't Node how to Express himself."),
    ("What do you call a fish without eyes?", "A fsh."),
    ("Why can't you give Elsa a balloon?", "Because she'll let it go."),
    ("I told my wife she was drawing her eyebrows too high.", "She looked surprised."),
    ("Why did the bicycle fall over?", "Because it was two-tired!"),
    ("What do you call cheese that isn't yours?", "Nacho cheese!"),
    ("I used to hate facial hair.", "But then it grew on me."),
    ("Why can't you hear a pterodactyl go to the bathroom?", "Because the P is silent."),
    ("I'm on a seafood diet.", "I see food and I eat it."),
    ("What do you call a factory that makes okay products?", "A satisfactory."),
    ("I only know 25 letters of the alphabet.", "I don't know why."),
    ("What do you call a sleeping dinosaur?", "A dino-snore!"),
]

TRIVIA = [
    {"q": "What is the capital of France?",           "a": "Paris",            "wrong": ["London", "Berlin", "Madrid"]},
    {"q": "How many sides does a hexagon have?",      "a": "6",                "wrong": ["5", "7", "8"]},
    {"q": "What planet is known as the Red Planet?",  "a": "Mars",             "wrong": ["Venus", "Jupiter", "Saturn"]},
    {"q": "Who wrote 'Romeo and Juliet'?",            "a": "Shakespeare",      "wrong": ["Dickens", "Hemingway", "Austen"]},
    {"q": "What is the chemical symbol for gold?",    "a": "Au",               "wrong": ["Go", "Gd", "Ag"]},
    {"q": "What year did World War II end?",          "a": "1945",             "wrong": ["1939", "1941", "1944"]},
    {"q": "What is the largest ocean on Earth?",      "a": "Pacific Ocean",    "wrong": ["Atlantic Ocean", "Indian Ocean", "Arctic Ocean"]},
    {"q": "How many bones are in the adult human body?", "a": "206",           "wrong": ["185", "212", "220"]},
    {"q": "What is the fastest land animal?",         "a": "Cheetah",          "wrong": ["Lion", "Greyhound", "Horse"]},
    {"q": "What language has the most native speakers?", "a": "Mandarin Chinese", "wrong": ["Spanish", "English", "Hindi"]},
    {"q": "How many continents are there on Earth?",  "a": "7",                "wrong": ["5", "6", "8"]},
    {"q": "What is the square root of 144?",          "a": "12",               "wrong": ["10", "14", "16"]},
]

POLL_NUMBERS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
POLL_EMOJIS  = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

DICE_RE = re.compile(r"^(\d+)d(\d+)$", re.IGNORECASE)


class Fun(commands.Cog):
    """Fun and utility commands."""

    def __init__(self, bot):
        self.bot = bot

    # ── Joke ──────────────────────────────────────────────────
    @commands.command(name="joke")
    async def joke_prefix(self, ctx):
        """Get a random joke."""
        setup, punchline = random.choice(JOKES)
        e = embed(f"{icon('joke')} Random Joke", color="info")
        e.add_field(name="Setup",     value=setup,     inline=False)
        e.add_field(name="Punchline", value=punchline, inline=False)
        await ctx.send(embed=e)

    @app_commands.command(name="joke", description="Get a random joke")
    async def joke_slash(self, interaction: discord.Interaction):
        setup, punchline = random.choice(JOKES)
        e = embed(f"{icon('joke')} Random Joke", color="info")
        e.add_field(name="Setup",     value=setup,     inline=False)
        e.add_field(name="Punchline", value=punchline, inline=False)
        await interaction.response.send_message(embed=e)

    # ── Poll ──────────────────────────────────────────────────
    @commands.command(name="poll")
    @commands.has_permissions(manage_messages=True)
    async def poll_prefix(self, ctx, question: str, *options):
        """Create a reaction poll.
        Usage: ?poll "question" option1 option2 [option3 ...]"""
        if len(options) < 2:
            return await ctx.send(embed=embed(
                f"{icon('error')} Missing Options",
                'Provide at least 2 options.\n**Usage:** `?poll "question" opt1 opt2 ...`',
                color="error"))
        if len(options) > 10:
            return await ctx.send(embed=embed(
                f"{icon('error')} Too Many Options",
                "Maximum 10 options per poll.", color="error"))

        description = "\n".join(f"{POLL_EMOJIS[i]} {opt}" for i, opt in enumerate(options))
        e = embed(f"{icon('poll')} {question}", description, color="mod")
        e.set_footer(text=f"Poll by {ctx.author.display_name} • React to vote!")
        msg = await ctx.send(embed=e)
        for i in range(len(options)):
            try:
                await msg.add_reaction(POLL_EMOJIS[i])
            except discord.HTTPException:
                break   # Stop reacting if we hit a rate limit

    @app_commands.command(name="poll", description="Create a reaction poll (up to 4 options)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def poll_slash(self, interaction: discord.Interaction,
                         question: str, option1: str, option2: str,
                         option3: str = None, option4: str = None):
        options = [o for o in [option1, option2, option3, option4] if o]
        description = "\n".join(f"{POLL_EMOJIS[i]} {opt}" for i, opt in enumerate(options))
        e = embed(f"{icon('poll')} {question}", description, color="mod")
        e.set_footer(text=f"Poll by {interaction.user.display_name} • React to vote!")
        await interaction.response.send_message(embed=e)
        msg = await interaction.original_response()
        for i in range(len(options)):
            try:
                await msg.add_reaction(POLL_EMOJIS[i])
            except discord.HTTPException:
                break

    # ── 8-ball ────────────────────────────────────────────────
    @commands.command(name="8ball")
    async def eightball_prefix(self, ctx, *, question: str):
        """Ask the magic 8-ball a question."""
        answer = random.choice(EIGHT_BALL_RESPONSES)
        e = embed(f"{icon('8ball')} Magic 8-Ball", color="info")
        e.add_field(name="Question", value=question, inline=False)
        e.add_field(name="Answer",   value=answer,   inline=False)
        await ctx.send(embed=e)

    @app_commands.command(name="8ball", description="Ask the magic 8-ball a question")
    async def eightball_slash(self, interaction: discord.Interaction, question: str):
        answer = random.choice(EIGHT_BALL_RESPONSES)
        e = embed(f"{icon('8ball')} Magic 8-Ball", color="info")
        e.add_field(name="Question", value=question, inline=False)
        e.add_field(name="Answer",   value=answer,   inline=False)
        await interaction.response.send_message(embed=e)

    # ── Coin flip ─────────────────────────────────────────────
    @commands.command(name="coinflip", aliases=["flip", "coin"])
    async def coinflip_prefix(self, ctx):
        """Flip a coin."""
        result = random.choice([f"{icon('flip')} Heads!", f"{icon('flip')} Tails!"])
        await ctx.send(embed=embed(result, color="info"))

    @app_commands.command(name="coinflip", description="Flip a coin")
    async def coinflip_slash(self, interaction: discord.Interaction):
        result = random.choice([f"{icon('flip')} Heads!", f"{icon('flip')} Tails!"])
        await interaction.response.send_message(embed=embed(result, color="info"))

    # ── RNG ───────────────────────────────────────────────────
    @commands.command(name="rng")
    async def rng_prefix(self, ctx, min_val: int = 1, max_val: int = 100):
        """Random number. ?rng [min] [max]"""
        if min_val >= max_val:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Range",
                "Min must be less than max.\n**Usage:** `?rng [min] [max]`", color="error"))
        result = random.randint(min_val, max_val)
        await ctx.send(embed=embed(
            f"{icon('rng')} Random Number",
            f"**{result}**  (range: {min_val}–{max_val})", color="info"))

    @app_commands.command(name="rng", description="Generate a random number")
    async def rng_slash(self, interaction: discord.Interaction,
                        min_val: int = 1, max_val: int = 100):
        if min_val >= max_val:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Invalid Range",
                "Min must be less than max.", color="error"), ephemeral=True)
        result = random.randint(min_val, max_val)
        await interaction.response.send_message(embed=embed(
            f"{icon('rng')} Random Number",
            f"**{result}**  (range: {min_val}–{max_val})", color="info"))

    # ── Roll (dice) ───────────────────────────────────────────
    @commands.command(name="roll")
    async def roll_prefix(self, ctx, dice: str = "1d6"):
        """Roll dice. ?roll [XdY]  — e.g. 2d6, 1d20"""
        m = DICE_RE.match(dice)
        if not m:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Dice Format",
                "Use `XdY` format (e.g. `2d6`, `1d20`).\n**Usage:** `?roll [XdY]`",
                color="error"))
        count, sides = int(m.group(1)), int(m.group(2))
        if count < 1 or count > 50:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Dice Count",
                "Dice count must be between 1 and 50.", color="error"))
        if sides < 2 or sides > 1000:
            return await ctx.send(embed=embed(
                f"{icon('error')} Invalid Dice Sides",
                "Sides must be between 2 and 1000.", color="error"))
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        roll_str = " + ".join(str(r) for r in rolls) if count > 1 else str(rolls[0])
        e = embed(f"{icon('rng')} Dice Roll — {dice}", color="info")
        e.add_field(name="Rolls",  value=roll_str, inline=False)
        if count > 1:
            e.add_field(name="Total", value=str(total), inline=True)
            e.add_field(name="Avg",   value=f"{total/count:.1f}", inline=True)
        await ctx.send(embed=e)

    @app_commands.command(name="roll", description="Roll dice (e.g. 2d6, 1d20)")
    async def roll_slash(self, interaction: discord.Interaction, dice: str = "1d6"):
        m = DICE_RE.match(dice)
        if not m:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Invalid Dice Format",
                "Use `XdY` format (e.g. `2d6`, `1d20`).", color="error"), ephemeral=True)
        count, sides = int(m.group(1)), int(m.group(2))
        if count < 1 or count > 50:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Invalid Dice Count",
                "Count must be 1–50.", color="error"), ephemeral=True)
        if sides < 2 or sides > 1000:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Invalid Dice Sides",
                "Sides must be 2–1000.", color="error"), ephemeral=True)
        rolls  = [random.randint(1, sides) for _ in range(count)]
        total  = sum(rolls)
        roll_str = " + ".join(str(r) for r in rolls) if count > 1 else str(rolls[0])
        e = embed(f"{icon('rng')} Dice Roll — {dice}", color="info")
        e.add_field(name="Rolls", value=roll_str, inline=False)
        if count > 1:
            e.add_field(name="Total", value=str(total), inline=True)
            e.add_field(name="Avg",   value=f"{total/count:.1f}", inline=True)
        await interaction.response.send_message(embed=e)

    # ── Mock ──────────────────────────────────────────────────
    @commands.command(name="mock")
    async def mock_prefix(self, ctx, *, text: str):
        """AlTeRnAtInG cApS mOcKiNg TeXt. ?mock <text>"""
        mocked = "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(text))
        await ctx.send(embed=embed(f"{icon('reverse')} Mocked", mocked[:1000], color="warn"))

    @app_commands.command(name="mock", description="Convert text to aLtErNaTiNg CaPs")
    async def mock_slash(self, interaction: discord.Interaction, text: str):
        mocked = "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(text))
        await interaction.response.send_message(
            embed=embed(f"{icon('reverse')} Mocked", mocked[:1000], color="warn"))

    # ── Server info ────────────────────────────────────────────
    @commands.command(name="serverinfo")
    async def serverinfo_prefix(self, ctx):
        """Show server info."""
        g = ctx.guild
        e = embed(f"{icon('server')} {g.name}", color="info")
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name=f"{icon('owner')} Owner",      value=g.owner.mention if g.owner else "Unknown", inline=True)
        e.add_field(name=f"{icon('id')} ID",             value=str(g.id),                                 inline=True)
        e.add_field(name=f"{icon('members')} Members",  value=str(g.member_count),                       inline=True)
        e.add_field(name=f"{icon('channels')} Channels",value=str(len(g.channels)),                      inline=True)
        e.add_field(name=f"{icon('roles')} Roles",      value=str(len(g.roles)),                         inline=True)
        e.add_field(name=f"{icon('boosts')} Boosts",    value=str(g.premium_subscription_count),         inline=True)
        e.add_field(name=f"{icon('created')} Created",  value=g.created_at.strftime("%Y-%m-%d"),         inline=True)
        e.add_field(name="Verification",                 value=str(g.verification_level).title(),         inline=True)
        await ctx.send(embed=e)

    @app_commands.command(name="serverinfo", description="Show server information")
    async def serverinfo_slash(self, interaction: discord.Interaction):
        g = interaction.guild
        e = embed(f"{icon('server')} {g.name}", color="info")
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name=f"{icon('owner')} Owner",      value=g.owner.mention if g.owner else "Unknown", inline=True)
        e.add_field(name=f"{icon('id')} ID",             value=str(g.id),                                 inline=True)
        e.add_field(name=f"{icon('members')} Members",  value=str(g.member_count),                       inline=True)
        e.add_field(name=f"{icon('channels')} Channels",value=str(len(g.channels)),                      inline=True)
        e.add_field(name=f"{icon('roles')} Roles",      value=str(len(g.roles)),                         inline=True)
        e.add_field(name=f"{icon('boosts')} Boosts",    value=str(g.premium_subscription_count),         inline=True)
        e.add_field(name=f"{icon('created')} Created",  value=g.created_at.strftime("%Y-%m-%d"),         inline=True)
        e.add_field(name="Verification",                 value=str(g.verification_level).title(),         inline=True)
        await interaction.response.send_message(embed=e)

    # ── User info ─────────────────────────────────────────────
    @commands.command(name="userinfo", aliases=["whois"])
    async def userinfo_prefix(self, ctx, member: discord.Member = None):
        """Display user info. ?userinfo [@user]"""
        member   = member or ctx.author
        top_role = member.top_role or ctx.guild.default_role
        roles    = [r.mention for r in member.roles if r.name != "@everyone"]
        e = embed(f"{icon('user')} {member.display_name}", color="info")
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name=f"{icon('id')} Username",        value=str(member),                                                         inline=True)
        e.add_field(name=f"{icon('id')} ID",              value=str(member.id),                                                      inline=True)
        e.add_field(name=f"{icon('bot')} Bot",            value="Yes" if member.bot else "No",                                       inline=True)
        e.add_field(name=f"{icon('joined')} Joined",      value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "Unknown", inline=True)
        e.add_field(name=f"{icon('created')} Registered", value=member.created_at.strftime("%Y-%m-%d"),                             inline=True)
        e.add_field(name=f"{icon('top_role')} Top Role",  value=top_role.mention,                                                   inline=True)
        if roles:
            e.add_field(
                name=f"{icon('roles')} Roles ({len(roles)})",
                value=" ".join(roles[:10]) + (" ..." if len(roles) > 10 else ""),
                inline=False,
            )
        await ctx.send(embed=e)

    @app_commands.command(name="userinfo", description="Display user information")
    async def userinfo_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        member   = member or interaction.user
        top_role = member.top_role or interaction.guild.default_role
        roles    = [r.mention for r in member.roles if r.name != "@everyone"]
        e = embed(f"{icon('user')} {member.display_name}", color="info")
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name=f"{icon('id')} Username",        value=str(member),                                                         inline=True)
        e.add_field(name=f"{icon('id')} ID",              value=str(member.id),                                                      inline=True)
        e.add_field(name=f"{icon('bot')} Bot",            value="Yes" if member.bot else "No",                                       inline=True)
        e.add_field(name=f"{icon('joined')} Joined",      value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "Unknown", inline=True)
        e.add_field(name=f"{icon('created')} Registered", value=member.created_at.strftime("%Y-%m-%d"),                             inline=True)
        e.add_field(name=f"{icon('top_role')} Top Role",  value=top_role.mention,                                                   inline=True)
        if roles:
            e.add_field(
                name=f"{icon('roles')} Roles ({len(roles)})",
                value=" ".join(roles[:10]) + (" ..." if len(roles) > 10 else ""),
                inline=False,
            )
        await interaction.response.send_message(embed=e)

    # ── Avatar ────────────────────────────────────────────────
    @commands.command(name="avatar", aliases=["av", "pfp"])
    async def avatar_prefix(self, ctx, member: discord.Member = None):
        """Get a user's avatar. ?avatar [@user]"""
        member = member or ctx.author
        e = embed(f"{icon('avatar')} {member.display_name}'s Avatar", color="info")
        e.set_image(url=member.display_avatar.url)
        e.description = f"[Open in browser]({member.display_avatar.url})"
        await ctx.send(embed=e)

    @app_commands.command(name="avatar", description="Get a user's avatar")
    async def avatar_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        e = embed(f"{icon('avatar')} {member.display_name}'s Avatar", color="info")
        e.set_image(url=member.display_avatar.url)
        e.description = f"[Open in browser]({member.display_avatar.url})"
        await interaction.response.send_message(embed=e)

    # ── Choose ────────────────────────────────────────────────
    @commands.command(name="choose")
    async def choose_prefix(self, ctx, *options):
        """Pick a random choice. ?choose option1 option2 ..."""
        if len(options) < 2:
            return await ctx.send(embed=embed(
                f"{icon('error')} Not Enough Options",
                "Give at least 2 options.\n**Usage:** `?choose opt1 opt2 opt3`",
                color="error"))
        choice = random.choice(options)
        await ctx.send(embed=embed(f"{icon('choose')} I choose: **{choice}**",
                                   f"Options: {', '.join(options)}", color="info"))

    @app_commands.command(name="choose", description="Pick randomly between options (separate with commas)")
    async def choose_slash(self, interaction: discord.Interaction, options: str):
        choices = [o.strip() for o in options.split(",") if o.strip()]
        if len(choices) < 2:
            return await interaction.response.send_message(embed=embed(
                f"{icon('error')} Not Enough Options",
                "Provide at least 2 comma-separated options.", color="error"), ephemeral=True)
        choice = random.choice(choices)
        await interaction.response.send_message(
            embed=embed(f"{icon('choose')} I choose: **{choice}**",
                        f"Options: {', '.join(choices)}", color="info"))

    # ── Ship ──────────────────────────────────────────────────
    @commands.command(name="ship")
    async def ship_prefix(self, ctx, member1: discord.Member, member2: discord.Member = None):
        """Calculate ship score. ?ship @user1 [@user2]"""
        member2 = member2 or ctx.author
        score = random.randint(0, 100)
        bar_filled = round(score / 10)
        bar = "+" * bar_filled + "-" * (10 - bar_filled)
        e = embed(f"{icon('ship')} {member1.display_name} x {member2.display_name}", color="warn")
        e.description = f"`[{bar}]`\n**{score}% compatible!**"
        e.set_footer(text="A match made in heaven!" if score >= 80 else "There's potential!" if score >= 50 else "Maybe just friends.")
        await ctx.send(embed=e)

    @app_commands.command(name="ship", description="Calculate compatibility between two users")
    async def ship_slash(self, interaction: discord.Interaction,
                         member1: discord.Member, member2: discord.Member = None):
        member2 = member2 or interaction.user
        score = random.randint(0, 100)
        bar_filled = round(score / 10)
        bar = "+" * bar_filled + "-" * (10 - bar_filled)
        e = embed(f"{icon('ship')} {member1.display_name} x {member2.display_name}", color="warn")
        e.description = f"`[{bar}]`\n**{score}% compatible!**"
        e.set_footer(text="A match made in heaven!" if score >= 80 else "There's potential!" if score >= 50 else "Maybe just friends.")
        await interaction.response.send_message(embed=e)

    # ── Reverse ───────────────────────────────────────────────
    @commands.command(name="reverse")
    async def reverse_prefix(self, ctx, *, text: str):
        """Reverse a string. ?reverse <text>"""
        await ctx.send(embed=embed(f"{icon('reverse')} Reversed", text[::-1][:1000], color="info"))

    @app_commands.command(name="reverse", description="Reverse any text")
    async def reverse_slash(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message(
            embed=embed(f"{icon('reverse')} Reversed", text[::-1][:1000], color="info"))

    # ── Trivia ────────────────────────────────────────────────
    @commands.command(name="trivia")
    async def trivia_prefix(self, ctx):
        """Answer a random trivia question. ?trivia"""
        item = random.choice(TRIVIA)
        options = [item["a"]] + item["wrong"]
        random.shuffle(options)
        answer_emoji  = POLL_EMOJIS[:len(options)]
        answer_index  = options.index(item["a"])

        description = "\n".join(f"{answer_emoji[i]} {opt}" for i, opt in enumerate(options))
        e = embed(f"{icon('trivia')} Trivia", color="info")
        e.description = f"**{item['q']}**\n\n{description}"
        e.set_footer(text="You have 20 seconds to react with the correct emoji!")
        msg = await ctx.send(embed=e)
        for emoji in answer_emoji:
            await msg.add_reaction(emoji)

        def check(reaction, user):
            return (user == ctx.author
                    and str(reaction.emoji) in answer_emoji
                    and reaction.message.id == msg.id)

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=20.0, check=check)
            chosen_index = answer_emoji.index(str(reaction.emoji))
            if chosen_index == answer_index:
                await ctx.send(embed=embed(f"{icon('ok')} Correct!", f"The answer was **{item['a']}**!", color="success"))
            else:
                await ctx.send(embed=embed(f"{icon('error')} Wrong!", f"The correct answer was **{item['a']}**.", color="error"))
        except asyncio.TimeoutError:
            await ctx.send(embed=embed(f"{icon('warn')} Time's up!", f"The answer was **{item['a']}**.", color="warn"))


async def setup(bot):
    await bot.add_cog(Fun(bot))
