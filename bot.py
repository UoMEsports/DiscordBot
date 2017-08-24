'''
EsportsBot
Christian Moulsdale, 2017
'''

import discord
import asyncio

from configparser import ConfigParser
from functools import wraps
from os import system
from profanity import profanity

# this is a zero width seperator
zero_seperator = '​'

# incorrect usage exception
class UsageException(Exception):
    pass

# the esbot class
class esbot(discord.Client):
    # initialise the bot
    def __init__(self, command_prefix = '!'):
        super().__init__()
        self.command_prefix = command_prefix
        self.config = ConfigParser()
        self.config.read('esbot.cfg')
        self.token = self.config.get('esbot', 'token')

    # run the bot
    def run(self):
        super().run(self.token)

    # respond to a message and then delete the message and response after a given lifetime with a default of 30s
    async def temp_respond(self, message, str_response, lifetime=30):
        response = await self.send_message(message.channel, str_response)
        await asyncio.sleep(lifetime)
        await self.delete_messages([message, response])

    # respond to a message and then delete the response after a given lifetime with a default of 30s
    async def temp_say(self, channel, str_response, lifetime=30):
        response = await self.send_message(channel, str_response)
        await asyncio.sleep(lifetime)
        await self.delete_message(response)
        
    # output to terminal if the bot successfully logs in
    async def on_ready(self):
        # output information about the bot's login
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

        # get the list of commands and committee-only-commands
        self.commands = []
        self.non_committee_commands = []
        for att in dir(self):
            attr = getattr(self, att, None)
            if hasattr(attr, 'is_command'):
                self.commands.append(att)
                if not attr.is_committee_only:
                    self.non_committee_commands.append(att)

        # read server variable ids from the config file and intialise them as global variables
        self.server = discord.utils.get(self.servers, id=self.config.get('esbot', 'server_id'))
        self.member_role = discord.utils.get(self.server.roles, id=self.config.get('esbot', 'member_id'))
        self.guest_role = discord.utils.get(self.server.roles, id=self.config.get('esbot', 'guest_id'))
        self.committee_role = discord.utils.get(self.server.roles, id=self.config.get('esbot', 'committee_id'))
        self.no_merci_emoji = discord.utils.get(self.server.emojis, name='nomerci')
        self.team_scrub_emoji = discord.utils.get(self.server.emojis, name='teamscrub')
        
        # set the current game to 'Orisa because she's the best hero'
        await self.change_presence(game = discord.Game(type=0, name = 'Orisa because she\'s the best hero'))

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
                message = kwargs['message']
                member = kwargs['member']

                # if committe only, check if the user has the committee role
                if committee_only:
                    if self.committee_role in member.roles:
                        try:
                            return await func(self, *args, **kwargs)
                        except UsageException:
                            return await self.temp_respond(message, 'Correct usage is `{}{} {}`. This command is committee only.'.format(self.command_prefix, func.__name__, usage))
                    else:
                        return await self.temp_respond(message, 'You need to be a committee member to use this command.')
                try:
                    return await func(self, *args, **kwargs)
                except UsageException:
                    return await self.temp_respond(message, 'Correct usage is `{}{} {}`'.format(self.command_prefix, func.__name__, usage))
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
                # process the responses in parallel because we do some async sleeping
                coros = []

                coros.append(self.meme_response(message, message_content_lower))
                if message_content_lower.startswith(self.command_prefix):
                    coros.append(self.process_commands(message, message_content))
                if profanity.contains_profanity(message_content):
                    coros.append(self.christian_server(message, message_content))

                await asyncio.wait(coros)
        
    # check if message is a PM - terms and conditions
    async def accept_terms(self, member, message_content_lower):
        if message_content_lower.startswith('yes'):
            # user is a member
            await self.send_message(member, 'Member role has been added')
            return await self.add_roles(member, self.member_role)
        elif message_content_lower.startswith('no'):
            # user is a guest
            await self.send_message(member, 'Guest role has been added')
            return await self.add_roles(member, self.guest_role)
        
    # check for a command
    async def process_commands(self, message, message_content):
        command, *args = message_content.split()
        command = command.replace(self.command_prefix, '', 1).lower()
        if command in self.commands:
            kwargs = dict()
            kwargs['message'] = message
            kwargs['author'] = message.author
            kwargs['member'] = self.server.get_member(message.author.id)
            
            cmd = getattr(self, command, None)
            await cmd(*args, **kwargs)
        else:
            await self.temp_respond(message, 'Command `{0}{1}` not found. Use `{0}help` to get the list of commands.'.format(self.command_prefix, command))

    # process the meme responses
    async def meme_response(self, message, message_content_lower):
        if 'merci' in message_content_lower:
            await self.add_reaction(message, self.no_merci_emoji)
        if 'scrub' in message_content_lower:
            await self.add_reaction(message, self.team_scrub_emoji)
        if 'behave' in message_content_lower:
            await self.temp_say(message.channel, 'No, you.')

    # this is a christian server
    async def christian_server(self, message, message_content):
        response = await self.send_file(message.channel, fp = 'christianserverorisa.png', content = profanity.censor(message.content))
        await asyncio.sleep(30)
        await self.delete_message(response)

    # send the terms and conditions prompts to a member
    async def send_terms(self, member):
        await self.send_message(member, 'Are you a member of the University of Manchester Esports Society? (`yes` or `no`) You can be in this server without being a member as a guest.')

    # when a member joins, send them a PM asking if they accept the terms and conditions
    async def on_member_join(self, member):
        await self.send_message(member, 'Welcome to the University of Manchester Esports Society discord server!')
        await self.send_terms(member)

    # BOT COMMANDS
    
    # list the bot commands
    @command(usage='[command(s)]')
    async def help(self, *args, **kwargs):
        member = kwargs['member']
        message = kwargs['message']
        # check if a command has been given to list the usage
        if len(args) == 0:
            response = '**EsportsBot commands**\n```!'
            if self.committee_role in member.roles:
                response += ', !'.join(self.commands)
            else:
                response += ', !'.join(self.non_committee_commands)
            response += '```'
            await self.temp_respond(message, response)
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
            await self.temp_respond(message, '\n'.join(responses))

    # restart the bot
    @command(committee_only=True)
    async def restart(self, *args, **kwargs):
        message = kwargs['message']
        author = kwargs['author']
        await self.send_message(author, 'Restarting.')
        await self.delete_message(message)
        print('Restarting the bot.')
        print('------')
        system('python3 bot.py')
        exit()

    # add game role
    @command(usage='game(s) | list')
    async def addrole(self, *args, **kwargs):
        member = kwargs['member']
        message = kwargs['message']
        if len(args) != 0:
            games = dict()
            for role in self.server.roles:
                if role.name.startswith(zero_seperator):
                    games[role.name.replace(zero_seperator, '').lower()] = role
            if args[0].lower() == 'list':
                response = 'The possible game roles are: '
                items = []
                for game in games:
                    items.append('`{}`'.format(games[game].name))
                response += ', '.join(items)
                await self.temp_respond(message, response)
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
                await self.temp_respond(message, '\n'.join(responses))
        else:
            raise UsageException

    # remove game role
    @command(usage='game(s) | list | all')
    async def removerole(self, *args, **kwargs):
        member = kwargs['member']
        message = kwargs['message']
        if len(args) != 0:
            games = dict()
            for role in self.server.roles:
                if role.name.startswith(zero_seperator):
                    games[role.name.replace(zero_seperator, '').lower()] = role
            if args[0].lower() == 'list':
                response = 'Your current game roles are: '
                items = []
                for game in games:
                    role = games[game]
                    if role in member.roles:
                        items.append('`{}`'.format(role.name))
                if len(items) == 0:
                    await self.temp_respond(message, 'You currently have no game roles. Add them using the `{}addrole` command.'.format(self.command_prefix))
                else:
                    response += ', '.join(items)
                    await self.temp_respond(message, response)
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
                    await self.temp_respond(message, '\n'.join(responses))
                else:
                    await self.temp_respond(message, 'You currently have no game roles. Add them using the `{}addrole` command.'.format(self.command_prefix))
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
                await self.temp_respond(message, '\n'.join(responses))
        else:
            raise UsageException

    # create new game role
    @command(usage='game', committee_only=True)
    async def createrole(self, *args, **kwargs):
        message = kwargs['message']
        if len(args) == 1:
            games = dict()
            for role in self.server.roles:
                if role.name.startswith(zero_seperator):
                    games[role.name.replace(zero_seperator, '').lower()] = role
            if args[0].lower() not in games:
                await self.create_role(self.server, name='{}{}'.format(zero_seperator, args[0]), mentionable=True, permissions=self.server.default_role.permissions)
                await self.temp_respond(message, 'Created `{}` game role'.format(args[0]))
            else:
                await self.temp_respond(message, '`{}` game role already exists'.format(games[args[0].lower()].name))
        else:
            raise UsageException

    # change Orisa's presence (game played)
    @command(usage='presence', committee_only=True)
    async def changepresence(self, *args, **kwargs):
        message = kwargs['message']
        if len(args) != 0:
            presence = ' '.join(args)
            await self.change_presence(game=discord.Game(type=0, name=presence))
            await self.temp_respond(message, 'Changed presence to `{}`.'.format(presence))
        else:
            raise UsageException
        
# start the bot
bot = esbot()
bot.run()
