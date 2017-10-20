'''
SocietyBot
Christian Moulsdale and Tom Mewett, 2017
'''

import asyncio
import aiohttp
import discord
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
        print('Invalid config file {}'.format(argv[1]))
        exit()
else:
    print('Please specify a config file, correct usage is python3 bot.py config.cfg')
    exit()

# read in from the configuration file
role_name = config.get('names', 'role')
society_name = config.get('names', 'society')
bot_name = config.get('names', 'bot')

'''
# read in the members from the csv file
def read_members():
    members = dict()
    with open('{}.csv'.format(bot_name), 'r') as f:
        f.readline()
        for line in f:
            id, data = line.strip().split(',', 1)
            members[id] = data.split(',')
    return members
'''

# email shit
fromaddr = config.get('email', 'fromaddr')
password = config.get('email', 'password')
toaddr = config.get('email', 'toaddr')

# backup the members file
async def backup_members():
    while True:
        msg = MIMEMultipart()
         
        msg['From'] = fromaddr
        msg['To'] = toaddr
        msg['Subject'] = 'Backup of EsportsBot.csv {}'.format(datetime.now().strftime('%Y-%m-%d %H:%M'))
         
        filename = '{}.csv'.format(bot_name)
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

        # wait 1 day
        await asyncio.sleep(86400)

# the esbot class
class Esbot(discord.Client):
    # initialise the bot
    def __init__(self, command_prefix = '!'):
        super().__init__()
        self.command_prefix = command_prefix

        # run the bot
        super().run(config.get('general', 'token'))

    # safely perform various coroutines

    # safely send a message
    async def safe_send_message(self, destination, content):
        try:
            return await super().send_message(destination, content)
        except Exception as ex:
            print(ex)

    # safely send a file
    async def safe_send_file(self, destination, fp, content=None):
        try:
            return await super().send_file(destination, fp, content)
        except Exception as ex:
            print(ex)

    # safely delete a message
    async def safe_delete_message(self, message):
        try:
            await super().delete_message(message)
        except Exception as ex:
            print(ex)

    # safely add a reaction
    async def safe_add_reaction(self, message, emoji):
        try:
            await super().add_reaction(message, emoji)
        except Exception as ex:
            print(ex)
        
    # output to terminal if the bot successfully logs in
    async def on_ready(self):
        # output information about the bot's login
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

        # get the list of commands and committee-only-commands
        self.commands = []
        for att in dir(self):
            attr = getattr(self, att, None)
            if hasattr(attr, 'is_command'):
                self.commands.append(att)

        # read server variable ids from the config file and intialise them as global variables
        self.server = discord.utils.get(self.servers, id=config.get('general', 'server_id'))
        
        self.member_role = discord.utils.get(self.server.roles, id=config.get('roles', 'member_id'))
        self.guest_role = discord.utils.get(self.server.roles, id=config.get('roles', 'guest_id'))
        self.committee_role = discord.utils.get(self.server.roles, id=config.get('roles', 'committee_id'))
        self.first_strike_role = discord.utils.get(self.server.roles, id=config.get('roles', 'first_strike_id'))
        self.second_strike_role = discord.utils.get(self.server.roles, id=config.get('roles', 'second_strike_id'))
        self.third_strike_role = discord.utils.get(self.server.roles, id=config.get('roles', 'third_strike_id'))
        
        self.esbot_channel = discord.utils.get(self.server.channels, id=config.get('channels', 'esbot_id'))
        self.moderation_channel = discord.utils.get(self.server.channels, id=config.get('channels', 'moderation_id'))

        # change the game to 'type !help for the list of commands'
        await self.change_presence(game=discord.Game(type=0, name='type {}help for the list of commands'.format(self.command_prefix)))

        # change the nickname of the bot to its name
        await self.change_nickname(self.server.get_member(self.user.id), bot_name)

        # send prompts to all members who don't currently have the member role
        for member in self.server.members:
            if self.member_role not in member.roles and self.guest_role not in member.roles and member != self.user:
                await self.send_terms(member)

        # initialise the members dictionary
        self.members = dict()
        with open('{}.csv'.format(bot_name), 'r') as f:
            f.readline()
            for line in f:
                id, data = line.strip().split(',', 1)
                self.members[id] = data.split(',')

        # process the unbans
        asyncio.ensure_future(self.process_unbans())

        # backup the members file
        asyncio.ensure_future(backup_members())

        '''
        members = dict()
        for member in self.server.members:
            if self.member_role in member.roles:
                members[member.id] = [member.name, 'member', '0', '', '', '', '', '']
            elif self.guest_role in member.roles:
                members[member.id] = [member.name, 'guest', '0', '', '', '', '', '']
            else:
                members[member.id] = [member.name, '', '0', '', '', '', '', '']
        self.write_members()
        '''

    # write the members to the csv file
    def write_members(self):
        with open('{}.csv'.format(bot_name), 'w') as f:
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
                member = kwargs['member']

                if self.committee_role in member.roles or not committee_only:
                    try:
                        return await func(self, *args, **kwargs)
                    except UsageException:
                        return await self.safe_send_message(self.esbot_channel, 'Correct usage is `{}{} {}`'.format(self.command_prefix, func.__name__, usage))
                else:
                    return await self.safe_send_message(self.esbot_channel, 'You need to be a committee member to use that command.'.format(member.mention))
            return sub_wrapper
            
        return wrapper
    
    #check the contents of the message
    async def on_message(self, message):
        # wait until the bot is ready to process messages
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
        if before.name != after.name:
            self.members[after.id][0] = after.name
            self.write_members()
        
    # check if message is a PM - terms and conditions
    async def accept_terms(self, member, message_content_lower):
        if message_content_lower.startswith('yes'):
            # user is a member
            await self.safe_send_message(member, 'Member role has been added')
            self.members[member.id][2] = 'member'
            await self.add_roles(member, self.member_role)
        elif message_content_lower.startswith('no'):
            # user is a guest
            await self.safe_send_message(member, 'Guest role has been added')
            self.members[member.id][2] = 'guest'
            await self.add_roles(member, self.guest_role)
        self.write_members()
        
    # check for a command
    async def process_commands(self, message, message_content):
        command, *args = message_content.split()
        command = command.replace(self.command_prefix, '', 1).lower()
        member = self.server.get_member(message.author.id)
        channel = message.channel
            
        if channel is self.esbot_channel:
            if command in self.commands:
                kwargs = dict()
                kwargs['member'] = member
                kwargs['message'] = message
                
                cmd = getattr(self, command, None)
                await cmd(*args, **kwargs)
            else:
                await self.safe_send_message(self.esbot_channel, 'Command `{0}{1}` not found. Use `{0}help` to get the list of commands'.format(self.command_prefix, command))
        else:
            await self.safe_delete_message(message)
            await self.safe_send_message(self.esbot_channel, '{} use commands here.'.format(member.mention))

    # send the terms and conditions prompts to a member
    async def send_terms(self, member):
        await self.safe_send_message(member, 'Are you a member of the {}? (`yes` or `no`) You can be in this server without being a member as a guest.'.format(society_name))

    # when a member joins, send them a PM asking if they accept the terms and conditions
    async def on_member_join(self, member):
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
            await self.add_roles(member, *roles)
        else:
            self.members[id] = [member.name, '', '0', '', '', '', '', '']
            await self.send_terms(member)
        self.write_members()

    # process the unbans
    async def process_unbans(self):
        while True:
            for id in self.members:
                if self.members[id][7] not in ['', 'never']:
                    date = datetime.strptime(self.members[id][7], '%Y-%m-%d %H:%M:%S')
                    if datetime.now() > date:
                        self.members[id][7] = ''
                        await self.unban(self.server, discord.User(id=id))
                        await self.send_message(self.moderation_channel, '{} has been unbanned'.format(self.members[0]))
            self.write_members()
            await asyncio.sleep(3600)

    # BOT COMMANDS
 
    # list the bot commands
    @command(usage='[command(s)]')
    async def help(self, *args, **kwargs):
        member = kwargs['member']
        # check if a command has been given to list the usage
        if len(args) == 0:
            response = '**{} commands**\n```\n!'.format(bot_name)
            response += ', !'.join(self.commands)
            response += '\n```\nType `!help command` to get the usage of a command.'
            await self.safe_send_message(self.esbot_channel, response)
        else:
            responses = []
            for arg in args:
                if arg.lower() in self.commands:
                    cmd = getattr(self, arg.lower())
                    if cmd.is_committee_only:
                        if self.committee_role in member.roles:
                            responses.append('Usage is `{}{} {}`.'.format(self.command_prefix, cmd.__name__, cmd.usage))
                        responses.append('This command is committee only')
                    else:
                        responses.append('Usage is `{}{} {}`.'.format(self.command_prefix, cmd.__name__, cmd.usage))

                else:
                    responses.append('Command `{}{}` not found.'.format(self.command_prefix, arg))
            await self.safe_send_message(self.esbot_channel, '\n'.join(responses))

    # restart the bot
    @command(committee_only=True)
    async def restart(self, *args, **kwargs):
        await self.safe_send_message(self.esbot_channel, 'Restarting.')
        print('Restarting the bot.')
        print('------')
        system('python3 {}'.format(' '.join(argv)))
        exit()

    # add game role
    @command(usage='{}(s) | list'.format(role_name))
    async def addrole(self, *args, **kwargs):
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
                await self.safe_send_message(self.esbot_channel, response)
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
                await self.safe_send_message(self.esbot_channel, '\n'.join(responses))
        else:
            raise UsageException

    # remove game role
    @command(usage='{}(s) | list | all'.format(role_name))
    async def removerole(self, *args, **kwargs):
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
                    await self.safe_send_message(self.esbot_channel, 'You currently have no {} roles. Add them using the `{}addrole` command.'.format(role_name, self.command_prefix))
                else:
                    response += ', '.join(items)
                    await self.safe_send_message(self.esbot_channel, response)
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
                    await self.safe_send_message(self.esbot_channel, '\n'.join(responses))
                else:
                    await self.safe_send_message(self.esbot_channel, 'You currently have no {} roles. Add them using the `{}addrole` command.'.format(role_nameself.command_prefix))
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
                await self.safe_send_message(self.esbot_channel, '\n'.join(responses))
        else:
            raise UsageException

    # list the members of a game role
    @command(usage=role_name)
    async def listrole(self, *args, **kwargs):
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
                for member in self.server.members:
                    if role in member.roles:
                        all.append(member.name)
                        if str(member.status) in ['online', 'idle']:
                            online.append(member.name)
                if len(all) != 0:
                    response = 'List of {} members with `{}` role:\n```\n{}\n```\n'.format(len(all), role.name, ', '.join(sorted(all, key=str.lower)))
                    if len(online) != 0:
                        response += 'List of {} online members with `{}` role:\n```\n{}\n```'.format(len(online), role.name, ', '.join(sorted(online, key=str.lower)))
                    else:
                        response += 'There are currently no online members with `{}` role'.format(role.name)
                    await self.safe_send_message(self.esbot_channel, response)
                else:
                    await self.safe_send_message(self.esbot_channel, 'There are currently no members with `{0}` role. Add it using `{1}addrole {0}`'.format(role.name, self.command_prefix))
            else:
                await self.safe_send_message(self.esbot_channel, 'Didn\'t recognise `{}` role.'.format(game))
        else:
            raise UsageException

    # create new game role
    @command(usage=role_name, committee_only=True)
    async def createrole(self, *args, **kwargs):
        if len(args) == 1:
            games = dict()
            for role in self.server.roles:
                if role.name.startswith(zero_seperator):
                    games[role.name.replace(zero_seperator, '').lower()] = role
            if args[0].lower() not in games:
                await self.create_role(self.server, name='{}{}'.format(zero_seperator, args[0]), mentionable=True, permissions=self.server.default_role.permissions)
                await self.safe_send_message(self.esbot_channel, 'Created `{}` {} role'.format(args[0], role_name))
            else:
                await self.safe_send_message(self.esbot_channel, '`{}` {} role already exists'.format(games[args[0].lower()].name, role_name))
        else:
            raise UsageException

    # change Orisa's presence (game played)
    @command(usage='presence', committee_only=True)
    async def changepresence(self, *args, **kwargs):
        if len(args) != 0:
            presence = ' '.join(args)
            await self.change_presence(game=discord.Game(type=0, name=presence))
            await self.safe_send_message(self.esbot_channel, 'Changed presence to `{}`.'.format(presence))
        else:
            raise UsageException

    # get bnet stats for a user
    @command(usage='battletag')
    async def stats(self, *args, **kwargs):
        if len(args) != 0:
            client = AsyncOWAPI()
            try:
                data = await client.get_profile(args[0])
            except asyncio.TimeoutError:
                return await self.safe_send_message(self.esbot_channel, 'Timed out, :slight_frown:')
            if data != {}:
                try:
                    SR = data['eu']['stats']['competitive']['overall_stats']['comprank']
                    tier = data['eu']['stats']['competitive']['overall_stats']['tier']
                    if SR == None:
                        SR = ''
                    await self.safe_send_message(self.esbot_channel, '`{}: {}({})`'.format(args[0], tier.title(), SR))
                except KeyError:
                    return await self.safe_send_message(self.esbot_channel, '{} has never played on EU, :slight_frown:'.format(args[0]))
            else:
                await self.safe_send_message(self.esbot_channel, 'Unable to find profile `{}`.'.format(args[0]))
        else:
            raise UsageException

    # give a user a strike
    @command(usage='user reason', committee_only=True)
    async def strike(self, *args, **kwargs):
        message = kwargs['message']
        if message.mentions != None and len(args) == 2:
            reason = args[1]
            for member in message.mentions:
                id = member.id
                if self.members[id][2] == '0':
                    self.members[id][2] = '1'
                    self.members[id][3] = reason
                    await self.safe_send_message(member, 'You have been given a first strike for `{}`. Please follow the rules.'.format(reason))
                    await self.safe_send_message(self.moderation_channel, '{} has been given a first strike.'.format(member.name))
                    await self.add_roles(member, self.first_strike_role)
                elif self.members[id][2] == '1':
                    self.members[id][2] = '2'
                    self.members[id][4] = reason
                    await self.safe_send_message(member, 'You have been given a second strike for `{}`. Please follow the rules.'.format(reason))
                    await self.safe_send_message(self.moderation_channel, '{} has been given a second strike.'.format(member.name))
                    await self.remove_roles(member, self.first_strike_role)
                    await self.add_roles(member, self.second_strike_role)
                elif self.members[id][2] == '2':
                    self.members[id][2] = '3'
                    self.members[id][5] = reason
                    unban_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
                    self.members[id][7] = unban_date
                    await self.safe_send_message(member, 'You have been given a 7 day ban for `{}`. Your ban will expire at `{}`'.format(reason, unban_date))
                    await self.safe_send_message(self.moderation_channel, '{} has been given a 7-day ban.'.format(member.name))
                    await self.ban(member)
                else:
                    self.members[id][2] = '4'
                    self.members[id][6] = reason
                    self.members[id][7] = 'never'
                    await self.safe_send_message(member, 'You have been permanently banned for `{}`.'.format(reason))
                    await self.safe_send_message(self.moderation_channel, '{} has been permanently banned.'.format(member.name))
                    await self.ban(member)
            self.write_members()
        else:
            raise UsageException

# start the bot
Esbot()
