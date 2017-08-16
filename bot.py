'''
EsportsBot
Christian Moulsdale, 2017
'''

import discord
import asyncio

from functools import wraps
from os import system
from profanity import profanity
from random import choice

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

        # get the list of commands
        self.commands = []
        for att in dir(self):
            attr = getattr(self, att, None)
            if hasattr(attr, 'is_command'):
                self.commands.append(att)
        
        # initialise the server variables as global variables
        self.server = discord.utils.get(self.servers, id = '230727209202089984')
        self.member_role = discord.utils.get(self.server.roles, id = '233644097007517697')
        self.committee_role = discord.utils.get(self.server.roles, id = '233643432843804674')
        self.no_merci_emoji = discord.utils.get(self.server.emojis, name = 'nomerci')
        self.team_scrub_emoji = discord.utils.get(self.server.emojis, name = 'teamscrub')

        # get the list of non-member ids
        self.non_member_ids = []
        with open('nonmemberids.txt', 'r') as f:
            for line in f:
                member = discord.utils.get(self.server.members, id=line.strip())
                if member != None:
                    if self.member_role not in member.roles:
                        self.non_member_ids.append(member.id)
        self.update_non_member_ids()
        
        # set the current game to 'Orisa because she's the best hero'
        await self.change_presence(game = discord.Game(name = 'Orisa because she\'s the best hero'))

        # send prompts to all members who don't currently have the member role
        for member in self.server.members:
            if self.member_role not in member.roles and member != self.user and member.id not in self.non_member_ids:
                await self.send_terms(member)

    def update_non_member_ids(self):
        with open('nonmemberids.txt', 'w') as f:
            for member_id in self.non_member_ids:
                f.write('{}\n'.format(member_id))

    # esborts command wrapper
    def command(usage='', committee_only=False):
        def wrapper(func):
            func.is_command = True
            @wraps(func)
            async def sub_wrapper(self, *args, details=False, **kwargs):
                message = kwargs.get('message')
                # if ran as part of help command, return the usage
                if details:
                    response = 'Usage is `{}{} {}`. '.format(self.command_prefix, func.__name__, usage)
                    if committee_only:
                        response += 'This command is committee only.'
                    return response
                # if committe only, check if the user has the committee role
                if committee_only:
                    member = kwargs.get('member')
                    if self.committee_role in member.roles:
                        try:
                            return await func(self, *args, **kwargs)
                        except UsageException:
                            return await self.temp_respond(message, 'Correct usage is `{}{} {}`'.format(self.command_prefix, func.__name__, usage))
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
        
        # get the message content in a managable format
        message_content = message.content.strip()
        message_content_lower = message_content.lower()

        # process the various responses as tasks to avoid async blocking
        task_process = asyncio.ensure_future(self.process_commands(message, message_content, message_content_lower))
        task_accept = asyncio.ensure_future(self.accept_terms(message, message_content_lower))
        task_meme = asyncio.ensure_future(self.meme_response(message, message_content_lower))
        task_christian = asyncio.ensure_future(self.christian_server(message, message_content))

        # finish the tasks
        await task_process
        await task_accept
        await task_meme
        await task_christian

    # check for a command
    async def process_commands(self, message, message_content, message_content_lower):
        if message_content_lower.startswith(self.command_prefix) and message.author != self.user and not message.channel.is_private:
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
        
    # check if message is a PM - terms and conditions
    async def accept_terms(self, message, message_content_lower):
        if message.channel.is_private and message.author != self.user:
            yes = False
            no = False
            if message_content_lower.startswith('yes'):
                yes = True
            elif message_content_lower.startswith('no'):
                no = True
            # check if they have the member role
            member = discord.utils.get(self.server.members, id=message.author.id)
            if member != None:
                if member.id not in self.non_member_ids:
                    if self.member_role not in member.roles:
                        # check their response if they don't have the member role
                        if yes:
                            # user has accepted the terms and conditions
                            await self.send_message(message.author, 'Member role has been added')
                            await self.add_roles(member, self.member_role)
                        elif no:
                            # user has rejected the terms and conditions
                            await self.send_message(message.author, 'OK, I\'ll stop asking.')
                            self.non_member_ids.append(member.id)
                            with open('nonmemberids.txt', 'a') as f:
                                f.write('{}\n'.format(member.id))
                    elif yes or no:
                        await self.send_message(message.author, 'You\'re already a member, dummy!')

    # process the meme responses
    async def meme_response(self, message, message_content_lower):
        if not message.channel.is_private and message.author != self.user:
            if 'behave' in message_content_lower:
                await self.temp_say(message.channel, 'No, you.')
            if 'merci' in message_content_lower:
                await self.add_reaction(message, self.no_merci_emoji)
            if 'scrub' in message_content_lower:
                await self.add_reaction(message, self.team_scrub_emoji)

    # this is a christian server
    async def christian_server(self, message, message_content):
        if profanity.contains_profanity(message_content) and message.author != self.user:
            response = await self.send_file(message.channel, fp = 'christianserverorisa.png', content = profanity.censor(message.content))
            await asyncio.sleep(30)
            await self.delete_message(response)

    # send the terms and conditions prompts to a member
    async def send_terms(self, member):
        await self.send_message(member, 'Are you a member of the University of Manchester Esports Society? (`yes` or `no`) You can be in this server without being a member.')

    # when a member joins, send them a PM asking if they accept the terms and conditions
    async def on_member_join(self, member):
        await self.send_message(member, 'Welcome to the University of Manchester Esports Society discord server!')
        if member.id not in self.non_member_ids:
            await self.send_terms(member)

    # BOT COMMANDS
    
    # list the bot commands
    @command(usage='[command(s)]')
    async def help(self, *args, **kwargs):
        message = kwargs.get('message')
        # check if a command has been given to list the usage
        if len(args) == 0:
            response = '**EsportsBot commands**\n```!'
            response += ', !'.join(self.commands)
            response += '```'
            await self.temp_respond(message, response)
        else:
            responses = []
            for arg in args:
                if arg.lower() in self.commands:
                    cmd = getattr(self, arg.lower(), None)
                    responses.append(await cmd(*args, **kwargs, details=True))
                else:
                    responses.append('Command `{}{}` not found.'.format(self.command_prefix, arg))
            await self.temp_respond(message, '\n'.join(responses))

    # restart the bot
    @command(committee_only=True)
    async def restart(self, *args, **kwargs):
        message = kwargs.get('message')
        author = kwargs.get('author')
        await self.send_message(author, 'Restarting.')
        await self.delete_message(message)
        print('Restarting the bot.')
        print('------')
        system('python3 bot.py')
        exit()

    # add game role
    @command(usage='game(s) | list')
    async def addrole(self, *args, **kwargs):
        member = kwargs.get('member')
        message = kwargs.get('message')
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
        member = kwargs.get('member')
        message = kwargs.get('message')
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
            
# start the bot
bot = esbot()
bot.run('token')
