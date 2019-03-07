from random import choice, randint
import discord
import asyncio
import unidecode

import datetime
import aiohttp
import re
import itertools
from io import BytesIO
from redbot.core import commands
from redbot.core import checks, bank, Config
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import pagify, box
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu
from redbot.core.utils.predicates import MessagePredicate

from discord.ext.commands.converter import IDConverter
from discord.ext.commands.converter import _get_from_guilds
from discord.ext.commands.errors import BadArgument
from typing import Union, Optional


_ = Translator("ServerStats", __file__)


class FuzzyMember(IDConverter):
    """
    This will accept user ID's, mentions, and perform a fuzzy search for
    members within the guild and return a list of member objects
    matching partial names

    Guidance code on how to do this from:
    https://github.com/Rapptz/discord.py/blob/rewrite/discord/ext/commands/converter.py#L85
    https://github.com/Cog-Creators/Red-DiscordBot/blob/V3/develop/redbot/cogs/mod/mod.py#L24

    """

    async def convert(self, ctx, argument):
        bot = ctx.bot
        match = self._get_id_match(argument) or re.match(r"<@!?([0-9]+)>$", argument)
        guild = ctx.guild
        result = []
        if match is None:
            # Not a mention
            if guild:
                for m in guild.members:
                    if argument.lower() in unidecode.unidecode(m.display_name.lower()):
                        # display_name so we can get the nick of the user first
                        # without being NoneType and then check username if that matches
                        # what we're expecting
                        result.append(m)
                        continue
                    if argument.lower() in unidecode.unidecode(m.name.lower()):
                        result.append(m)
                        continue
        else:
            user_id = int(match.group(1))
            if guild:
                result.append(guild.get_member(user_id))
            else:
                result.append(_get_from_guilds(bot, "get_member", user_id))

        if result is None:
            raise BadArgument('Member "{}" not found'.format(argument))

        return result


class GuildConverter(IDConverter):
    """
    This is a guild converter for fuzzy guild names which is used throughout
    this cog to search for guilds by part of their name and will also
    accept guild ID's

    Guidance code on how to do this from:
    https://github.com/Rapptz/discord.py/blob/rewrite/discord/ext/commands/converter.py#L85
    https://github.com/Cog-Creators/Red-DiscordBot/blob/V3/develop/redbot/cogs/mod/mod.py#L24

    """

    async def convert(self, ctx, argument):
        bot = ctx.bot
        match = self._get_id_match(argument)
        result = None
        if ctx.author.id != ctx.bot.owner_id:
            # Don't need to be snooping other guilds unless we're
            # the bot owner
            raise BadArgument(_("That option is only available for the bot owner."))
        if match is None:
            # Not a mention
            for g in bot.guilds:
                if argument.lower() in g.name.lower():
                    # display_name so we can get the nick of the user first
                    # without being NoneType and then check username if that matches
                    # what we're expecting
                    result = g
        else:
            guild_id = int(match.group(1))
            result = bot.get_guild(guild_id)

        if result is None:
            raise BadArgument('Guild "{}" not found'.format(argument))

        return result


@cog_i18n(_)
class ServerStats(getattr(commands, "Cog", object)):
    """
        Gather useful information about servers the bot is in
        A lot of commands are bot owner only
    """

    def __init__(self, bot):
        self.bot = bot
        default_global = {"join_channel": None}
        self.config = Config.get_conf(self, 54853421465543)
        self.config.register_global(**default_global)

    async def on_guild_join(self, guild):
        """Build and send a message containing serverinfo when the bot joins a new server"""
        channel_id = await self.config.join_channel()
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        em = await self.guild_embed(guild)
        em.title = "{bot} has left {server}".format(bot=channel.guild.me.name, server=guild.name)
        await channel.send(embed=em)

    async def guild_embed(self, guild):
        """
            Builds the guild embed information used throughout the cog
        """

        def check_feature(feature):
            return "\N{WHITE HEAVY CHECK MARK}" if feature in guild.features else "\N{CROSS MARK}"

        total_users = len(guild.members)
        humans = len([a for a in guild.members if a.bot == False])
        bots = len([a for a in guild.members if a.bot])
        text_channels = len([x for x in guild.text_channels])
        voice_channels = len([x for x in guild.voice_channels])
        passed = (datetime.datetime.utcnow() - guild.created_at).days
        created_at = _("Created on : {since}").format(
            since=guild.created_at.strftime("%d %b %Y %H:%M")
        )
        try:
            joined_at = guild.me.joined_at
        except:
            joined_at = datetime.datetime.utcnow()

        bot_joined = joined_at.strftime("%d %b %Y %H:%M:%S")
        since_joined = (datetime.datetime.utcnow() - joined_at).days

        joined_on = _(
            "Joined on : {bot_join}"
        ).format(bot_join=bot_joined)

        em = discord.Embed(description=f"{created_at}\n{joined_on}")
        em.add_field(
            name=_("Members :"),
            value=_(
                "Total users : {total}\nHumans : {hum}\nBots : {bots}"
            ).format(
                total=total_users,
                hum=humans,
                bots=bots,
            ),
        )
        em.add_field(
            name=_("Utility :"),
            value=_(
                "Owner : {owner}\nServer ID : {id}"
            ).format(
                owner=guild.owner,
                id=guild.id,
            ),
        )
        em.title = guild.name
        if guild.icon_url:
            em.set_thumbnail(url=guild.icon_url)
        else:
            em.set_thumbnail(
                url="https://cdn.discordapp.com/attachments/494975386334134273/529843761635786754/Discord-Logo-Black.png"
            )
        return em

    async def on_guild_remove(self, guild):
        """Build and send a message containing serverinfo when the bot leaves a server"""
        channel_id = await self.config.join_channel()
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        em = await self.guild_embed(guild)
        em.title = "{bot} has left {server}".format(bot=channel.guild.me.mention, server=guild.name)
        await channel.send(embed=em)

    async def ask_for_invite(self, ctx):
        """
            Ask the user to provide an invite link
            if reinvite is True
        """
        check = lambda m: m.author == ctx.message.author
        msg_send = _(
            "Please provide a reinvite link/message.\n" "Type `exit` for no invite link/message."
        )
        invite_check = await ctx.send(msg_send)
        try:
            msg = await ctx.bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            await msg.edit(content=_("I Guess not."))
            return None
        if "exit" in msg.content:
            return None
        else:
            return msg.content

    async def get_members_since(self, ctx, days: int, role: discord.Role):
        now = datetime.datetime.utcnow()
        after = now - datetime.timedelta(days=days)
        if role is None:
            member_list = [m for m in ctx.guild.members if m.top_role < ctx.me.top_role]
        else:
            member_list = [m for m in role.members if m.top_role < ctx.me.top_role]
        user_list = []
        for channel in ctx.guild.text_channels:
            if not channel.permissions_for(ctx.me).read_message_history:
                continue
            async for message in channel.history(limit=None, after=after):
                if message.author in member_list:
                    member_list.remove(message.author)
        return member_list

    @commands.command()
    @checks.is_owner()
    @commands.bot_has_permissions(embed_links=True)
    async def setguildjoin(self, ctx, channel: discord.TextChannel = None):
        """
            Set a channel to see new servers the bot is joining
        """
        if channel is None:
            channel = ctx.message.channel
        await self.config.join_channel.set(channel.id)
        msg = _("Posting new servers and left servers in ") + channel.mention
        await ctx.send(msg)

    @commands.command()
    @checks.is_owner()
    async def removeguildjoin(self, ctx):
        """
            Stop bots join/leave server messages
        """
        await self.config.join_channel.set(None)
        await ctx.send(_("No longer posting joined or left servers."))

    async def guild_menu(
        self, ctx, post_list: list, message: discord.Message = None, page=0, timeout: int = 30
    ):
        """menu control logic for this taken from
           https://github.com/Lunar-Dust/Dusty-Cogs/blob/master/menu/menu.py"""

        guild = post_list[page]
        em = await self.guild_embed(guild)

        if not message:
            message = await ctx.send(embed=em)
            await message.add_reaction("⬅")
            await message.add_reaction("❌")
            await message.add_reaction("➡")
            await message.add_reaction("📤")
            await message.add_reaction("📥")
        else:
            # message edits don't return the message object anymore lol
            await message.edit(embed=em)
        check = (
            lambda react, user: user == ctx.message.author
            and react.emoji in ["➡", "⬅", "❌", "\N{OUTBOX TRAY}", "\N{INBOX TRAY}"]
            and react.message.id == message.id
        )
        try:
            react, user = await self.bot.wait_for("reaction_add", check=check, timeout=timeout)
        except asyncio.TimeoutError:
            await message.remove_reaction("⬅", ctx.me)
            await message.remove_reaction("❌", ctx.me)
            await message.remove_reaction("➡", ctx.me)
            await message.remove_reaction("\N{INBOX TRAY}", ctx.me)
            await message.remove_reaction("\N{OUTBOX TRAY}", ctx.me)
            return None
        else:
            if react.emoji == "➡":
                next_page = 0
                if page == len(post_list) - 1:
                    next_page = 0  # Loop around to the first item
                else:
                    next_page = page + 1
                if ctx.channel.permissions_for(ctx.me).manage_messages:
                    await message.remove_reaction("➡", ctx.message.author)
                return await self.guild_menu(
                    ctx, post_list, message=message, page=next_page, timeout=timeout
                )
            elif react.emoji == "⬅":
                next_page = 0
                if page == 0:
                    next_page = len(post_list) - 1  # Loop around to the last item
                else:
                    next_page = page - 1
                if ctx.channel.permissions_for(ctx.me).manage_messages:
                    await message.remove_reaction("⬅", ctx.message.author)
                return await self.guild_menu(
                    ctx, post_list, message=message, page=next_page, timeout=timeout
                )
            elif react.emoji == "\N{OUTBOX TRAY}":
                try:
                    await self.confirm_leave_guild(ctx, guild)
                except:
                    pass
            elif react.emoji == "\N{INBOX TRAY}":
                invite = await self.get_guild_invite(guild)
                if invite:
                    await ctx.send(str(invite))
                else:
                    await ctx.send(
                        _("I cannot find or create an invite for `{guild}`").format(
                            guild=guild.name
                        )
                    )
            else:
                return await message.delete()

    @staticmethod
    async def confirm_leave_guild(ctx, guild):
        await ctx.send(
            _("Are you sure you want to leave {guild}? (reply yes or no)").format(guild=guild.name)
        )
        pred = MessagePredicate.yes_or_no(ctx)
        await ctx.bot.wait_for("message", check=pred)
        if pred.result is True:
            try:
                await ctx.send(_("Leaving {guild}.").format(guild=guild.name))
                await guild.leave()
            except:
                await ctx.send(_("I couldn't leave {guild}.").format(guild=guild.name))
        else:
            await ctx.send(_("Okay, not leaving {guild}.").format(guild=guild.name))

    @staticmethod
    async def get_guild_invite(guild: discord.Guild, max_age: int = 86400):
        """Handles the reinvite logic for getting an invite
        to send the newly unbanned user
        :returns: :class:`Invite`"""
        my_perms: discord.Permissions = guild.me.guild_permissions
        if my_perms.manage_guild or my_perms.administrator:
            if "VANITY_URL" in guild.features:
                # guild has a vanity url so use it as the one to send
                return await guild.vanity_invite()
            invites = await guild.invites()
        else:
            invites = []
        for inv in invites:  # Loop through the invites for the guild
            if not (inv.max_uses or inv.max_age or inv.temporary):
                # Invite is for the guild's default channel,
                # has unlimited uses, doesn't expire, and
                # doesn't grant temporary membership
                # (i.e. they won't be kicked on disconnect)
                return inv
        else:  # No existing invite found that is valid
            channels_and_perms = zip(
                guild.text_channels, map(guild.me.permissions_in, guild.text_channels)
            )
            channel = next(
                (channel for channel, perms in channels_and_perms if perms.create_instant_invite),
                None,
            )
            if channel is None:
                return
            try:
                # Create invite that expires after max_age
                return await channel.create_invite(max_age=max_age)
            except discord.HTTPException:
                return

    @commands.command()
    @checks.is_owner()
    @commands.bot_has_permissions(embed_links=True)
    async def getguild(self, ctx, *, guild: GuildConverter = None):
        """
            Display info about servers the bot is on

            `guild_name` can be either the server ID or partial name
        """
        page = ctx.bot.guilds.index(ctx.guild)
        if guild or await ctx.bot.is_owner(ctx.author):
            page = ctx.bot.guilds.index(guild) if guild else page
            await self.guild_menu(ctx, ctx.bot.guilds, None, page)
        else:
            await ctx.send(embed=await self.guild_embed(ctx.guild))
