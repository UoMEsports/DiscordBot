# -*- coding: utf-8 -*-

'''
SocietyBot
Christian Moulsdale and Tom Mewett, 2017
'''

import asyncio
import aiohttp
import discord
import json
import smtplib

from configparser import ConfigParser
from datetime import datetime, timedelta
from functools import wraps
from os import listdir, system
from sys import argv

from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from overwatch_api.core import AsyncOWAPI
from overwatch_api.constants import *

from urllib.request import urlopen
from urllib.error import URLError

def log(message):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    print('[{0}]: {1}'.format(ts, message))

# this is a zero width seperator
zero_seperator = '​'

# incorrect usage exception
class UsageException(Exception):
    pass

# initialise the configuration file
config = ConfigParser()

# check if valid arguments have been given
if len(argv) == 2:
    if argv[1].endswith('.cfg') and argv[1] in listdir():
        config.read(argv[1])
    else:
        log('Invalid config file {}'.format(argv[1]))
        exit()
else:
    log('Please specify a config file, correct usage is python3 bot.py config.cfg')
    exit()

# read in from the configuration file
role_name = config.get('names', 'role')
society_name = config.get('names', 'society')
bot_name = config.get('names', 'bot')

# email shit
filename = '{}.csv'.format(bot_name)
fromaddr = config.get('email', 'fromaddr')
password = config.get('email', 'password')
toaddr = config.get('email', 'toaddr')

# twitch shit
twitch_name = config.get('twitch', 'name')
twitch_client_id = config.get('twitch', 'client_id')

# backup the members file
async def backup_members():
    while True:
        msg = MIMEMultipart()

        msg['From'] = fromaddr
        msg['To'] = toaddr
        msg['Subject'] = 'Backup of {} {}'.format(filename, datetime.now().strftime('%Y-%m-%d %H:%M'))

        attachment = open(filename, 'rb')

        part = MIMEBase('application', 'octet-stream')
        part.set_payload((attachment).read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename={}'.format(filename))
        msg.attach(part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(fromaddr, password)
        text = msg.as_string()
        server.sendmail(fromaddr, toaddr, text)
        server.quit()

        # delete junk
        del msg, attachment, part, text

        # wait 1 day
        await asyncio.sleep(86400)

# the societybot class
class Societybot(discord.Client):
    # initialise the bot
    def __init__(self):
        super().__init__()
        self.command_prefix = config.get('general', 'command_prefix')

        # run the bot
        super().run(config.get('general', 'token'))

    # SAFE COROUTINES

    # safely send a message
    async def safe_send_message(self, destination, content):
        try:
            return await super().send_message(destination, content)
        except Exception as ex:
            log(ex)

    # safely send a file
    async def safe_send_file(self, destination, fp, content=None):
        try:
            return await super().send_file(destination, fp, content)
        except Exception as ex:
            log(ex)

    # safely delete a message
    async def safe_delete_message(self, message):
        try:
            await super().delete_message(message)
        except Exception as ex:
            log(ex)

    # safely add a reaction
    async def safe_add_reaction(self, message, emoji):
        try:
            await super().add_reaction(message, emoji)
        except Exception as ex:
            log(ex)

    # EVENTS
        
    # output to terminal if the bot successfully logs in
    async def on_ready(self):
        # output information about the bot's login
        log('Logged in as {0} ({1})'.format(self.user, self.user.id))
        log('START INIT')
        
        # get the list of commands and committee-only-commands
        log('Producing the command lists')
        self.commands = []
        self.committee_commands = []
        for att in dir(self):
            attr = getattr(self, att, None)
            if hasattr(attr, 'is_command'):
                if attr.is_committee_only:
                    self.committee_commands.append(att)
                else:
                    self.commands.append(att)

        # read server variable ids from the config file and intialise them as global variables
        log('Initialising server variables')
        self.server = discord.utils.get(self.servers, id=config.get('general', 'server_id'))
        
        self.member_role = discord.utils.get(self.server.roles, id=config.get('roles', 'member_id'))
        self.guest_role = discord.utils.get(self.server.roles, id=config.get('roles', 'guest_id'))
        self.committee_role = discord.utils.get(self.server.roles, id=config.get('roles', 'committee_id'))
        self.first_strike_role = discord.utils.get(self.server.roles, id=config.get('roles', 'first_strike_id'))
        self.second_strike_role = discord.utils.get(self.server.roles, id=config.get('roles', 'second_strike_id'))
        self.third_strike_role = discord.utils.get(self.server.roles, id=config.get('roles', 'third_strike_id'))
        self.strike_roles = [self.first_strike_role, self.second_strike_role, self.third_strike_role]
        
        self.command_channel = discord.utils.get(self.server.channels, id=config.get('channels', 'command_id'))
        self.moderation_channel = discord.utils.get(self.server.channels, id=config.get('channels', 'moderation_id'))

        # starting the twitch integration
        log('Starting twitch integration')
        asyncio.ensure_future(self.check_stream())

        # change the nickname of the bot to its name
        log('Changing nickname to {}'.format(bot_name))
        await self.change_nickname(self.server.get_member(self.user.id), bot_name)

        # initialise the members dictionary and read from the file
        log('Reading members in from file')
        self.members = dict()
        if filename in listdir():
            with open(filename, mode='r', encoding='utf-8') as f:
                f.readline()
                for line in f:
                    id, data = line.strip().split(',', 1)
                    self.members[id] = data.split(',')
        else:
            # make an empty file if it doesn't exist
            log('Member file doesn\'t exist, making one now')
            self.write_members()

        # check for consistency with the current list of members
        log('Checking consistency with current members')
        members = self.server.members
        for member in members:
            id = member.id
            if id not in self.members:
                if self.member_role in member.roles:
                    self.members[member.id] = [str(member), 'member', '0', '', '', '', '', '']
                elif self.guest_role in member.roles:
                    self.members[member.id] = [str(member), 'guest', '0', '', '', '', '', '']
                else:
                    self.members[member.id] = [str(member), '', '0', '', '', '', '', '']
            else:
                self.members[id][0] = str(member)

            # send prompts to all members who don't currently have the member role
            if self.member_role not in member.roles and self.guest_role not in member.roles and member != self.user:
                await self.send_terms(member)

        # writing to the file
        log('Writing to the members file')
        self.write_members()

        # process the unbans
        asyncio.ensure_future(self.process_unbans())

        # backup the members file
        log('Backing up the current members file')
        asyncio.ensure_future(backup_members())

        # ready to go!
        log('Ready to go!')
        log('------')

    # check the contents of the message
    async def on_message(self, message):
        # wait until the bot is ready
        await self.wait_until_ready()

        # process responses if message isn't from user:
        if message.author != self.user:
            # get the message content in a managable format
            message_content = message.content.strip()
            message_content_lower = message_content.lower()
            
            if message.channel.is_private:
                member = self.server.get_member(message.author.id)
                if self.member_role not in member.roles and self.guest_role not in member.roles:
                    await self.accept_terms(member, message_content_lower)
            else:
                if message_content.startswith(self.command_prefix):
                    await self.process_commands(message, message_content)

    # when a member updates their profile:
    async def on_member_update(self, before, after):
        # wait until the bot is ready
        await self.wait_until_ready()
        
        if str(after) != str(before):
            self.members[after.id][0] = str(after)
        elif after.roles != before.roles:
            id = after.id
            old = self.members[id][1]
            if self.member_role in after.roles:
                self.members[id][1] = 'member'
            elif self.guest_role in after.roles:
                self.members[id][1] = 'guest'
            else:
                self.members[id][1] = ''
                
            if self.members[id][1] == old:
                # no changes
                return
        else:
            # no changes
            return

        # save the changes
        self.write_members()

    # when a member joins, send them a PM asking if they accept the terms and conditions
    async def on_member_join(self, member):
        # wait until the bot is ready
        await self.wait_until_ready()
        
        log('Member join: {}({})'.format(str(member), member.id))
        id = member.id
        await self.safe_send_message(member, 'Welcome to the {} discord server!'.format(society_name))
        if id in self.members:
            roles = []
            role = self.members[id][1]
            if role == 'member':
                roles.append(self.member_role)
            elif role == 'guest':
                roles.append(self.guest_role)
            else:
                await self.send_terms(member)
            strikes = self.members[id][2]
            if strikes == '1':
                roles.append(self.first_strike_role)
            elif strikes == '2':
                roles.append(self.second_strike_role)
            elif strikes == '3':
                roles.append(self.third_strike_role)
                await self.safe_send_message(member, 'You are now on your third strike. 1 more strike and you will be permanently banned from the server. Please follow the rules.')
            await self.add_roles(member, *roles)
        else:
            self.members[id] = [str(member), '', '0', '', '', '', '', '']
            await self.send_terms(member)
            self.write_members()

    # UTILITY

    # confirm a command
    async def confirm(self, member, prompt):
        def check(msg):
            return msg.content.lower() in ['yes', 'no']
        
        sent = await self.safe_send_message(member, 'Confirm: `{}` (`yes` or `no`)'.format(prompt))
        response = await self.wait_for_message(author=member, channel=sent.channel, check=check)
        if response.content.lower() == 'yes':
            return True
        else:
            return False

    # add and remove roles
    async def add_remove_roles(self, member, add, remove):
        roles = member.roles
        
        for role in remove:
            if role in roles:
                roles.remove(role)
                
        for role in add:
            if role not in roles:
                roles.append(role)
                
        await self.replace_roles(member, *roles)

    # write the members to the csv file
    def write_members(self):
        with open(filename, mode='w', encoding='utf-8') as f:
            f.write('User ID,Username,Role,Number of strikes,Reason 1,Reason 2,Reason 3,Reason 4,Unban date\n')
            for id in self.members:
                f.write('{},{}\n'.format(id, ','.join(self.members[id])))
                
    # esborts command wrapper
    def command(usage='', committee_only=False):
        def wrapper(func):
            func.is_command = True
            func.is_committee_only = committee_only
            func.usage = usage
            
            @wraps(func)
            async def sub_wrapper(self, *args, **kwargs):
                channel = kwargs['channel']
                member = kwargs['member']
                log('{}{} in #{} by {}'.format(self.command_prefix, func.__name__, channel, member))
                try:
                    return await func(self, *args, **kwargs)
                except UsageException:
                    return await self.safe_send_message(channel, 'Correct usage is `{}{} {}`'.format(self.command_prefix, func.__name__, usage))
            return sub_wrapper
        return wrapper

    # change the currently playing game if the society twitch account is streaming
    async def check_stream(self):
        while True:
            url = 'https://api.twitch.tv/kraken/streams/{}?client_id={}'.format(twitch_name, twitch_client_id)
            try:
                info = json.loads(urlopen(url, timeout = 15).read().decode('utf-8'))
                if info['stream'] == None:
                    # nothing is streaming
                    await self.change_presence(game=discord.Game(type=0, name='type {}help for the list of commands'.format(self.command_prefix)))
                else:
                    # give the stream name
                    await self.change_presence(game=discord.Game(type=1, name=info['stream']['channel']['status'], url='https://twitch.tv/uomesports'))
            except:
                await self.change_presence(game=discord.Game(type=0, name='type {}help for the list of commands'.format(self.command_prefix)))
            await asyncio.sleep(60)
        
    # check if message is a PM - terms and conditions
    async def accept_terms(self, member, message_content_lower):
        if message_content_lower.startswith('yes'):
            # user is a member
            log('{} is now a member'.format(str(member)))
            await self.safe_send_message(member, 'Member role has been added')
            self.members[member.id][1] = 'member'
            await self.add_roles(member, self.member_role)
        elif message_content_lower.startswith('no'):
            # user is a guest
            log('{} is now a guest'.format(str(member)))
            await self.safe_send_message(member, 'Guest role has been added')
            self.members[member.id][1] = 'guest'
            await self.add_roles(member, self.guest_role)
        else:
            # invalid response receieved
            return

        # write to the file
        self.write_members()
        
    # check for a command
    async def process_commands(self, message, message_content):
        command, *args = message_content.split()
        command = command.replace(self.command_prefix, '', 1).lower()
        channel = message.channel
        member = self.server.get_member(message.author.id)
        
        if channel is self.command_channel and command in self.commands or channel is self.moderation_channel and command in (self.commands + self.committee_commands):
            kwargs = dict()
            kwargs['member'] = member
            kwargs['message'] = message
            kwargs['channel'] = channel
            
            cmd = getattr(self, command, None)
            await cmd(*args, **kwargs)
        elif channel not in [self.command_channel, self.moderation_channel]:
            await self.safe_delete_message(message)
            if command in self.committee_commands and self.committee_role in member.roles:
                await self.safe_send_message(self.moderation_channel, '{} use committee commands here.'.format(member.mention))
            else:
                await self.safe_send_message(self.command_channel, '{} use commands here.'.format(member.mention))
        else:
            await self.safe_send_message(channel, 'Command `{0}{1}` not found. Use `{0}help` to get the list of commands'.format(self.command_prefix, command))
            if command in self.committee_commands and self.committee_role in member.roles:
                await self.safe_send_message(self.moderation_channel, '{} use committee commands here.'.format(member.mention))

    # send the terms and conditions prompts to a member
    async def send_terms(self, member):
        await self.safe_send_message(member, 'Are you a member of the {}? (`yes` or `no`) You can be in this server without being a member as a guest.'.format(society_name))

    # process the unbans
    async def process_unbans(self):
        while True:
            log('Processing the unbans')
            for id in self.members:
                if self.members[id][7] not in ['', 'never']:
                    date = datetime.strptime(self.members[id][7], '%Y-%m-%d %H:%M')
                    if datetime.now() > date:
                        self.members[id][7] = ''
                        await self.unban(self.server, discord.User(id=id))
                        await self.safe_send_message(self.moderation_channel, '{} has been unbanned'.format(self.members[id][0]))
            self.write_members()
            
            # wait 1 hour
            await asyncio.sleep(3600)

    # BOT COMMANDS
 
    # list the bot commands
    @command(usage='[command(s)]')
    async def help(self, *args, **kwargs):
        channel = kwargs['channel']
        member = kwargs['member']
        # check if a command has been given to list the usage
        if len(args) == 0:
            response = '**{} commands**\n```\n!{}'.format(bot_name, ', !'.join(self.commands))
            if channel is self.moderation_channel:
                response += '\n```\n**Committee-only commands**\n```\n!{}'.format(', !'.join(self.committee_commands))
            response += '\n```\nType `!help command` to get the usage of a command.'
            await self.safe_send_message(channel, response)
        else:
            responses = []
            for arg in args:
                if channel is self.command_channel and arg.lower() in self.commands or channel is self.moderation_channel and arg.lower() in (self.commands + self.committee_commands):
                    cmd = getattr(self, arg.lower())
                    responses.append('Usage is `{}{} {}`.'.format(self.command_prefix, cmd.__name__, cmd.usage))
                else:
                    responses.append('Command `{}{}` not found.'.format(self.command_prefix, arg))
            await self.safe_send_message(channel, '\n'.join(responses))

    # restart the bot
    @command(committee_only=True)
    async def restart(self, *args, **kwargs):
        channel = kwargs['channel']
        await self.safe_send_message(channel, 'Restarting.')
        log('Restarting the bot.')
        log('------')
        system('python3 {}'.format(' '.join(argv)))
        exit()

    # add game role
    @command(usage='{}(s) | list'.format(role_name))
    async def addrole(self, *args, **kwargs):
        channel = kwargs['channel']
        member = kwargs['member']
        if len(args) != 0:
            games = dict()
            for role in self.server.roles:
                if role.name.startswith(zero_seperator):
                    games[role.name.replace(zero_seperator, '').lower()] = role
            if args[0].lower() == 'list':
                response = 'The possible {} roles are: '.format(role_name)
                items = []
                for game in games:
                    items.append('`{}`'.format(games[game].name))
                response += ', '.join(items)
                await self.safe_send_message(channel, response)
            else:
                responses = []
                roles = []
                for arg in args:
                    game = arg.lower()
                    if game in games:
                        role = games[game]
                        if role in member.roles:
                            responses.append('You already have `{}` role'.format(role.name))
                        else:
                            roles.append(games[game])
                            responses.append('Added `{}` role'.format(role.name))
                    else:
                        responses.append('Didn\'t recognise `{}` role '.format(arg))
                await self.add_roles(member, *roles)
                await self.safe_send_message(channel, '\n'.join(responses))
        else:
            raise UsageException

    # remove game role
    @command(usage='{}(s) | list | all'.format(role_name))
    async def removerole(self, *args, **kwargs):
        channel = kwargs['channel']
        member = kwargs['member']
        if len(args) != 0:
            games = dict()
            for role in self.server.roles:
                if role.name.startswith(zero_seperator):
                    games[role.name.replace(zero_seperator, '').lower()] = role
            if args[0].lower() == 'list':
                response = 'Your current {} roles are: '.format(role_name)
                items = []
                for game in games:
                    role = games[game]
                    if role in member.roles:
                        items.append('`{}`'.format(role.name))
                if len(items) == 0:
                    await self.safe_send_message(channel, 'You currently have no {} roles. Add them using the `{}addrole` command.'.format(role_name, self.command_prefix))
                else:
                    response += ', '.join(items)
                    await self.safe_send_message(channel, response)
            elif args[0].lower() == 'all':
                responses = []
                roles = []
                for game in games:
                    role = games[game]
                    if role in member.roles:
                        roles.append(role)
                        responses.append('Removed `{}` role'.format(role.name))
                if len(responses) != 0:
                    await self.remove_roles(member, *roles)
                    await self.safe_send_message(channel, '\n'.join(responses))
                else:
                    await self.safe_send_message(channel, 'You currently have no {} roles. Add them using the `{}addrole` command.'.format(role_nameself.command_prefix))
            else:
                responses = []
                roles = []
                for arg in args:
                    game = arg.lower()
                    if game in games:
                        role = games[game]
                        if role in member.roles:
                            roles.append(role)
                            responses.append('Removed `{}` role'.format(role.name))
                        else:
                            responses.append('You don\'t have `{}` role'.format(role.name))
                    else:
                        responses.append('Didn\'t recognise `{}` role'.format(game))
                await self.remove_roles(member, *roles)
                await self.safe_send_message(channel, '\n'.join(responses))
        else:
            raise UsageException

    # list the members of a game role
    @command(usage=role_name)
    async def listrole(self, *args, **kwargs):
        channel = kwargs['channel']
        if len(args) == 1:
            games = dict()
            for role in self.server.roles:
                if role.name.startswith(zero_seperator):
                    games[role.name.replace(zero_seperator, '').lower()] = role
            game = args[0].lower()
            all = []
            online = []
            if game in games:
                role = games[game]
                members = self.server.members
                for member in members:
                    if role in member.roles:
                        all.append(str(member))
                        if str(member.status) in ['online', 'idle']:
                            online.append(str(member))
                if len(all) != 0:
                    response = 'List of {} members with `{}` role:\n```\n{}\n```\n'.format(len(all), role.name, ', '.join(sorted(all, key=str.lower)))
                    if len(online) != 0:
                        response += 'List of {} online members with `{}` role:\n```\n{}\n```'.format(len(online), role.name, ', '.join(sorted(online, key=str.lower)))
                    else:
                        response += 'There are currently no online members with `{}` role'.format(role.name)
                    await self.safe_send_message(channel, response)
                else:
                    await self.safe_send_message(channel, 'There are currently no members with `{0}` role. Add it using `{1}addrole {0}`'.format(role.name, self.command_prefix))
            else:
                await self.safe_send_message(channel, 'Didn\'t recognise `{}` role.'.format(game))
        else:
            raise UsageException

    # create new game role
    @command(usage=role_name, committee_only=True)
    async def createrole(self, *args, **kwargs):
        channel = kwargs['channel']
        if len(args) == 1:
            games = dict()
            for role in self.server.roles:
                if role.name.startswith(zero_seperator):
                    games[role.name.replace(zero_seperator, '').lower()] = role
            if args[0].lower() not in games:
                await self.create_role(self.server, name='{}{}'.format(zero_seperator, args[0]), mentionable=True, permissions=self.server.default_role.permissions)
                await self.safe_send_message(channel, 'Created `{}` {} role'.format(args[0], role_name))
            else:
                await self.safe_send_message(channel, '`{}` {} role already exists'.format(games[args[0].lower()].name, role_name))
        else:
            raise UsageException

    # change Orisa's presence (game played)
    @command(usage='presence', committee_only=True)
    async def changepresence(self, *args, **kwargs):
        channel = kwargs['channel']
        if len(args) != 0:
            presence = ' '.join(args)
            await self.change_presence(game=discord.Game(type=0, name=presence))
            await self.safe_send_message(channel, 'Changed presence to `{}`.'.format(presence))
        else:
            raise UsageException

    # get bnet stats for a user
    @command(usage='battletag')
    async def stats(self, *args, **kwargs):
        channel = kwargs['channel']
        if len(args) != 0:
            client = AsyncOWAPI()
            try:
                data = await client.get_profile(args[0])
            except asyncio.TimeoutError:
                return await self.safe_send_message(channel, 'Timed out, :slight_frown:')
            if data != {}:
                try:
                    SR = data['eu']['stats']['competitive']['overall_stats']['comprank']
                    tier = data['eu']['stats']['competitive']['overall_stats']['tier']
                    if SR == None:
                        await self.safe_send_message(channel, '{} hasn\'t played comp this season'.format(args[0]))
                    else:
                        await self.safe_send_message(channel, '`{}: {}({})`'.format(args[0], tier, SR))
                except KeyError:
                    return await self.safe_send_message(channel, '{} has never played on EU, :slight_frown:'.format(args[0]))
            else:
                await self.safe_send_message(channel, 'Unable to find profile `{}`.'.format(args[0]))
        else:
            raise UsageException

    # strike commands

    # give a user a strike
    @command(usage='@user reason', committee_only=True)
    async def strike(self, *args, **kwargs):
        message = kwargs['message']
        if message.mentions != None and len(args) >= 2:
            reason = ' '.join(args[1:])
            for member in message.mentions:
                id = member.id
                if self.members[id][2] == '0':
                    self.members[id][2] = '1'
                    self.members[id][3] = reason
                    await self.safe_send_message(member, 'You have been given a first strike for `{}`. Please follow the rules.'.format(reason))
                    await self.safe_send_message(self.moderation_channel, '{} has been given a first strike for `{}`.'.format(str(member), reason))
                    await self.add_remove_roles(member, [self.first_strike_role], self.strike_roles)
                elif self.members[id][2] == '1':
                    self.members[id][2] = '2'
                    self.members[id][4] = reason
                    await self.safe_send_message(member, 'You have been given a second strike for `{}`. 1 more strike and you will be given a 7-day ban from the server. Please follow the rules.'.format(reason))
                    await self.safe_send_message(self.moderation_channel, '{} has been given a second strike for `{}`.'.format(str(member), reason))
                    await self.add_remove_roles(member, [self.second_strike_role], self.strike_roles)
                elif self.members[id][2] == '2':
                    if await self.confirm(message.author, 'Give 7-day ban to {}'.format(str(member))):
                        self.members[id][2] = '3'
                        self.members[id][5] = reason
                        unban_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M')
                        self.members[id][7] = unban_date
                        await self.safe_send_message(member, 'You have been given a 7 day ban for `{}`. Your ban will expire at `{}`'.format(reason, unban_date))
                        await self.safe_send_message(self.moderation_channel, '{} has been given a 7 day ban for `{}`.'.format(str(member), reason))
                        await self.ban(member)
                else:
                    if await self.confirm(message.author, 'Permanently ban {}'.format(str(member))):
                        self.members[id][2] = '4'
                        self.members[id][6] = reason
                        self.members[id][7] = 'never'
                        await self.safe_send_message(member, 'You have been permanently banned for `{}`.'.format(reason))
                        await self.safe_send_message(self.moderation_channel, '{} has been permanently banned for `{}`.'.format(str(member), reason))
                        await self.ban(member)
                        
            self.write_members()
        else:
            raise UsageException

    # remove a users strikes
    @command(usage='@user', committee_only=True)
    async def destrike(self, *args, **kwargs):
        message = kwargs['message']
        if message.mentions != None:
            for member in message.mentions:
                id = member.id
                if self.members[id][2] == '0':
                    await self.safe_send_message(self.moderation_channel, '{} has no strikes.'.format(str(member)))
                elif self.members[id][2] == '1':
                    self.members[id][2] = '0'
                    self.members[id][3] = ''
                    await self.remove_roles(member, *self.strike_roles)
                    await self.safe_send_message(self.moderation_channel, '{}\'s first strike has been removed.'.format(str(member)))
                elif self.members[id][2] == '2':
                    self.members[id][2] = '1'
                    self.members[id][4] = ''
                    await self.add_remove_roles(member, [self.first_strike_role], self.strike_roles)
                    await self.safe_send_message(self.moderation_channel, '{}\'s second strike has been removed.'.format(str(member)))
                else:
                    self.members[id][2] = '2'
                    self.members[id][5] = ''
                    await self.add_remove_roles(member, [self.second_strike_role], self.strike_roles)
                    await self.safe_send_message(self.moderation_channel, '{}\'s third strike has been removed.'.format(str(member)))
            self.write_members()
        else:
            raise UsageException

    # view your own strikes
    @command()
    async def strikes(self, *args, **kwargs):
        channel = kwargs['channel']
        member = kwargs['member']
        id = member.id
        strikes = []
        for i in range(4):
            if self.members[id][i+3] != '':
                strikes.append('Strike {}: `{}`'.format(i+1, self.members[id][i+3]))
        if len(strikes) == 0:
            await self.safe_send_message(member, 'You currently have no strikes.')
        else:
            await self.safe_send_message(member, 'You have the following {} strikes:\n{}'.format(len(strikes), '\n'.join(strikes)))
        await self.safe_send_message(channel, 'PM\'d.')

    # change your role
    @command(usage='member | guest')
    async def changerole(self, *args, **kwargs):
        channel = kwargs['channel']
        member = kwargs['member']
        if len(args) == 1:
            role = args[0].lower()
            if role == 'member':
                if self.member_role in member.roles:
                    return await self.safe_send_message(channel, 'You already have the `member` role')
                else:
                    await self.add_remove_roles(member, [self.member_role], [self.guest_role])
                    await self.safe_send_message(channel, 'You now have the `member` role')
            elif role == 'guest':
                if self.guest_role in member.roles:
                    return await self.safe_send_message(channel, 'You already have the `guest` role')
                else:
                    await self.add_remove_roles(member, [self.guest_role], [self.member_role])
                    await self.safe_send_message(channel, 'You now have the `guest` role')
            else:
                return await self.safe_send_message(channel, 'Didn\'t recognise `{}` role'.format(args[0]))

            # update the members file
            self.write_members()
        else:
            raise UsageException
        
# start the bot
Societybot()
