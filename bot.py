'''
SocietyBot
Christian Moulsdale and Tom Mewett, 2017
'''

import discord
import asyncio

from configparser import ConfigParser
from functools import wraps
from os import listdir, system
from sys import argv

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
        except:
            pass

    # safely send a file
    async def safe_send_file(self, destination, fp):
        try:
            return await super().send_file(destination, fp)
        except:
            pass

    # safely delete a message
    async def safe_delete_message(self, message):
        try:
            await super().delete_message(message)
        except:
            pass

    # safely add a reaction
    async def safe_add_reaction(self, message, emoji):
        try:
            await super().add_reaction(message, emoji)
        except:
            pass

    # respond to a message and then delete the response after a given lifetime with a default of 30s
    async def temp_say(self, channel, str_response, lifetime=30):
        response = await self.safe_send_message(channel, str_response)
        await asyncio.sleep(lifetime)
        await self.safe_delete_message(response)
        
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
        self.esbot_channel = discord.utils.get(self.server.channels, id=config.get('channels', 'esbot_id'))

        # change the game to 'type !help for the list of commands'
        await self.change_presence(game=discord.Game(type=0, name='type {}help for the list of commands'.format(self.command_prefix)))

        # change the nickname of the bot to its name
        await self.change_nickname(self.server.get_member(self.user.id), bot_name)

        # send prompts to all members who don't currently have the member role
        for member in self.server.members:
            if self.member_role not in member.roles and self.guest_role not in member.roles and member != self.user:
                await self.send_terms(member)

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
                await self.process_commands(message, message_content)
        
    # check if message is a PM - terms and conditions
    async def accept_terms(self, member, message_content_lower):
        if message_content_lower.startswith('yes'):
            # user is a member
            await self.safe_send_message(member, 'Member role has been added')
            return await self.add_roles(member, self.member_role)
        elif message_content_lower.startswith('no'):
            # user is a guest
            await self.safe_send_message(member, 'Guest role has been added')
            return await self.add_roles(member, self.guest_role)
        
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
                
                cmd = getattr(self, command, None)
                await cmd(*args, **kwargs)
            else:
                await self.safe_send_message(self.esbot_channel, 'Command `{0}{1}` not found. Use `{0}help` to get the list of commands'.format(self.command_prefix, command))
        else:
            await self.safe_delete_message(message)
            await self.safe_send_message(self.esbot_channel, '{} use commands here.'.format(member.mention))

    '''
    # process the meme responses
    async def meme_response(self, message, message_content_lower):
        if 'merci' in message_content_lower:
            await self.safe_add_reaction(message, self.no_merci_emoji)
        if 'scrub' in message_content_lower:
            await self.safe_add_reaction(message, self.team_scrub_emoji)
    '''

    # send the terms and conditions prompts to a member
    async def send_terms(self, member):
        await self.safe_send_message(member, 'Are you a member of the {}? (`yes` or `no`) You can be in this server without being a member as a guest.'.format(society_name))

    # when a member joins, send them a PM asking if they accept the terms and conditions
    async def on_member_join(self, member):
        await self.safe_send_message(member, 'Welcome to the {} discord server!'.format(society_name))
        await self.send_terms(member)

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
        
# start the bot
Esbot()
