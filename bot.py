# -*- coding: utf-8 -*-

import asyncio

from aiohttp import ClientSession
from configparser import ConfigParser
from csv import reader, writer
from datetime import datetime, timedelta
from discord import Client, Embed, File, Game, Streaming
from discord.abc import PrivateChannel
from discord.utils import find
from functools import wraps
from io import BytesIO

# STUFF

# zero width joiner
zwj = '\u200d'

# incorrect usage error
class UsageException(Exception):
    def __init__(self, value=None):
        self.value = value

# UTILITY

def log(message):
    with open('out.log', 'a') as f:
        f.write('[{}]: {}\n'.format(datetime.now().strftime('%Y-%m-%d %H:%M'),
                                    message))

# edit a member's roles
async def edit_roles(member, add=[], remove=[]):
    # get the list of the member's current roles
    roles = member.roles

    # remove the desired roles from the list
    for role in remove:
        if role in roles:
            roles.remove(role)

    # add the desired roles from the list
    for role in add:
        if role not in roles:
            roles.append(role)

    # edit the member's roles
    await member.edit(roles=roles)

# the bot class
class Bot(Client):
    # initialise the bot
    def __init__(self):
        super().__init__()

        # open the config file
        self.config = ConfigParser()
        self.config.read('test.cfg')
        
        # run the bot using the token from the config file
        super().run(self.config.get('general', 'token'))

    # UTILITIES

    # replace a command prefix token with the command prefix
    def rcpfx(self, text):
        return text.replace('%CPFX%', self.command_prefix)
        
    # process the command in a DM
    async def process_commands(self, message, member, content):
        command, *args = content.split()
        command = command.replace(self.command_prefix, '', 1).lower()

        if command in self.commands and (not self.commands[command]['admin_only'] or self.admin_role in member.roles):
            return await self.commands[command]['cmd'](member, *args)
        else:
            return await member.send('Command "{0}{1}" not found. Use "{0}help" to get the list of commands'.format(self.command_prefix, command))

    # WRAPPERS

    # event wrapper
    def event():
        def wrapper(func):
            func.bot_event = True
            
            @wraps(func)
            async def sub_wrapper(self, *args, **kwargs):
                try:
                    return await func(self, *args, **kwargs)
                except Exception as ex:
                    err = 'Unhandled {} in event {}: {}'.format(ex.__class__.__name__,
                                                                func.__name__,
                                                                ex)
                    log(err)
                    return self.admin_channel.send(err)
                    
            return sub_wrapper
        return wrapper

    # command wrapper
    def command(description, usage='', admin_only=False, category='general'):
        def wrapper(func):
            func.bot_command = True
            func.description = description
            func.usage = usage
            func.admin_only = admin_only
            func.category = category
            
            @wraps(func)
            async def sub_wrapper(self, member, *args):
                try:
                    response = await func(self, member, *args)
                except UsageException as ex:
                    response = 'Correct usage is "{}{} {}"{}'.format(self.command_prefix,
                                                                     func.__name__,
                                                                     usage,
                                                                     '\n{}'.format(ex.value) if ex.value else '')
                except Exception as ex:
                    # unhandled exception
                    err = 'Unhandled {} in command {}{} by {}: {}'.format(ex.__class__.__name__,
                                                                          self.command_prefix,
                                                                          func.__name__,
                                                                          member,
                                                                          ex)
                    log(err)
                    await self.admin_channel.send(err)
                    response = 'Sorry, that command failed.'
                
                if response:
                    if isinstance(response, Embed):
                        return await member.send(embed=response)
                    else:
                        return await member.send(response)
                    
            return sub_wrapper
        return wrapper

    # process wrapper
    def process(period=60., retry=True):
        def wrapper(func):
            func.bot_process = True
            
            @wraps(func)
            async def sub_wrapper(self, **kwargs):
                # start the process
                kwargs['state'] = 'setup'
                try:
                    kwargs = await func(self, **kwargs)
                except Exception as ex:
                    err = 'Unhandled {} while starting up process {}: {}'.format(ex.__class__.__name__,
                                                                                 func.__name__,
                                                                                 ex)
                    log(err)
                    return await self.admin_channel.send(err)
                # run the process
                while kwargs['state'] == 'run':
                    try:
                        kwargs = await func(self, **kwargs)
                    except Exception as ex:
                        err = 'Unhandled {} in process {}: {}'.format(ex.__class__.__name__,
                                                                      func.__name__,
                                                                      ex)
                        log(err)
                        await self.admin_channel.send(err)
                        if not retry:
                            kwargs['continue'] = 'end'

                    await asyncio.sleep(period)

                # finish the process
                try:
                    return await func(self, **kwargs)
                except Exception as ex:
                    err = 'Unhandled {} while shutting down process {}: {}'.format(ex.__class__.__name__,
                                                                                   func.__name__,
                                                                                   ex)
                    log(err)
                    return await self.admin_channel.send(err)
                
            return sub_wrapper
        return wrapper

    # EMBEDS

    # command embed
    def cmd_embed(self, cmd):
        embed = Embed(title='{}{}'.format(self.command_prefix, cmd.__name__),
                      description='{}\nUsage: {}{} {}'.format(cmd.description, self.command_prefix, cmd.__name__, cmd.usage),
                      color=0xb72025 if cmd.admin_only else 0x00607d)
        embed.set_author(name='Esports Bot')
        if cmd.admin_only:
            embed.set_footer(text='Admin-only command.')

        return embed

    # EVENTS
        
    # output to terminal if the bot successfully logs in
    @event()
    async def on_ready(self):
        # output information about the bot's login
        log('Logged in as {0}, {0.id}'.format(self.user))
        log('------')

        # command prefix
        self.command_prefix = self.config.get('general', 'command_prefix')

        self.name = self.config.get('general', 'name')

        # produce the list of commands
        log('Producing the command lists')
        self.commands = {}
        for att in dir(self):
            attr = getattr(self, att, None)
            if hasattr(attr, 'bot_command'):
                self.commands[att] = {'cmd': attr, 'admin_only': attr.admin_only, 'embed': self.cmd_embed(attr)}

        # read guild variable ids from the config file and intialise them as global variables
        log('Initialising the guild variables')
        self.guild = self.get_guild(int(self.config.get('general', 'guild')))

        # channels
        self.admin_channel = self.guild.get_channel(int(self.config.get('channels', 'admin')))

        # roles
        self.admin_role = find(lambda role: role.id == self.config.get('roles', 'admin'), self.guild.roles)

        # change the nickname of the bot to its name
        log('Changing nickname to {}'.format(self.name))
        await self.guild.me.edit(nick=self.name)

        # maintain the bots presence
        log('Maintaining the bots presence')
        asyncio.ensure_future(self.maintain_presence())

        # generate the help text
        log('Generating the help text')
        self.help_embed = Embed(color=0x00607d)
        self.help_embed.add_field(name='Commands',
                                  value='\n'.join(['{}{}'.format(self.command_prefix, command) for command in self.commands if not self.commands[command]['admin_only']]))
        self.help_embed.set_footer(text='Type "{}help command" to get its usage.'.format(self.command_prefix))
        self.admin_embed = Embed(color=0xb72025)
        self.admin_embed.add_field(name='Commands',
                                   value='\n'.join(['{}{}'.format(self.command_prefix, command) for command in self.commands if not self.commands[command]['admin_only']]))
        self.admin_embed.add_field(name='Admin-only commands',
                                   value='\n'.join(['{}{}'.format(self.command_prefix, command) for command in self.commands if self.commands[command]['admin_only']]))
        self.admin_embed.set_footer(text='Type "{}help command" to get its usage.'.format(self.command_prefix))
        
        # generate the game roles
        log('Generating the game roles')
        self.games = []
        with open('games.txt', 'r') as f:
            for line in f:
                id = int(line.strip())

                # check if role exists
                if find(lambda role: role.id == id, self.guild.roles):
                    self.games.append(id)
                else:
                    # role doesn't exist
                    log('Couldn\'t find role with ID {}'.format(id))

        with open('games.txt', 'w') as f:
            for id in self.games:
                f.write('{}\n'.format(id))
        
        # ready to go!
        log('Ready to go!')
        log('------')
        
    # check the contents of the message
    @event()
    async def on_message(self, message):
        # wait until the bot is ready
        await self.wait_until_ready()

        # process responses if message isn't from user:
        if message.author != self.user:
            # get the message content in a managable format
            content = message.content.strip()

            # get the member who sent the message
            member = self.guild.get_member(message.author.id)
            
            # check whether a command has been given
            if content.startswith(self.command_prefix):
                # check whether it was given correctly by DM
                if isinstance(message.channel, PrivateChannel):
                    return await self.process_commands(message, member, content)
                else:
                    # delete message if in guild channel and remind user to use DM's
                    await delete_message(message)
                    return await member.send('Use commands here.')

    # PERIODIC COROUTINES
    
    # maintain the bots presence on the server
    @process()
    async def maintain_presence(self, **kwargs):
        if kwargs['state'] == 'setup':
            # read in the stream
            stream = self.config.get('general', 'stream')

            # read in the default presence
            kwargs['presence'] = self.config.get('general', 'presence')
            
            # the URLs
            kwargs['stream_URL'] = 'https://twitch.tv/{}'.format(stream)
            kwargs['API_URL'] = 'https://api.twitch.tv/kraken/streams/{}?client_id=vnhejis97bfke371caeq7u8zn2li3u'.format(stream)

            # set the bot to run
            kwargs['state'] = 'run'
        elif kwargs['state'] == 'run':
            # check if the stram is live
            async with ClientSession() as session:
                async with session.get(kwargs['API_URL']) as resp:
                    info = await resp.json()

            if info['stream'] == None:
                # nothing is streaming - use default presence
                await self.change_presence(activity=Game(kwargs['presence']))
            else:
                # stream is live - use streaming presence
                await self.change_presence(activity=Streaming(name=info['stream']['channel']['status'], details=info['stream']['channel']['game'], url=kwargs['stream_URL']))

        return kwargs

    # COMMANDS

    # GENERAL COMMANDS
    
    # list the bot commands
    @command(description='List the bot commands and their usage.', usage='[command]')
    async def help(self, member, *args):
        if len(args) == 0:
            # give the correct version of the help text
            if self.admin_role in member.roles:
                return self.admin_embed
            else:
                return self.help_embed
        elif len(args) == 1:
            # find the command
            command = args[0].lower().replace(self.command_prefix, '')
            if command in self.commands and (not self.commands[command]['admin_only'] or self.admin_role in member.roles):
                return self.commands[command]['embed']
            else:
                return 'Command {}{} not found.'.format(self.command_prefix, command)
        else:
            raise UsageException

    # GAME ROLE COMMANDS

    # add game role
    @command(description='Add a game role.', usage='game')
    async def addgame(self, member, *args):
        if len(args) == 0:
            raise UsageException
        else:
            game = ' '.join(args)

            role = find(lambda role: role.name.lower() == game.lower(), self.guild.roles)

            if role:
                # role exists
                if role in member.roles:
                    # member already has the role
                    return 'You already have "{}" role.'.format(role.name)
                else:
                    # member doesn't have role
                    await member.add_roles(*[role])
                    return 'Added "{}" role.'.format(role.name)
            else:
                # role doesn't exist
                return 'Didn\'t recognise "{}" role.'.format(game)

    # remove game role
    @command(description='Remove a game role.', usage='games')
    async def removegame(self, member, *args):
        if len(args) == 0:
            raise UsageException
        else:
            game = ' '.join(args)

            role = find(lambda role: role.name.lower() == game.lower() and role.id in self.games, self.guild.roles)

            if role:
                # role exists
                if role in member.roles:
                    # member already has the role
                    await member.remove_roles(*[role])
                    return 'Removed "{}" role.'.format(role.name)
                else:
                    # member doesn't have role
                    return 'You don\'t have "{}" role.'.format(role.name)
            else:
                # role doesn't exist
                return 'Didn\'t recognise "{}" role.'.format(game)

    # list the game roles
    @command(description='List the game roles.')
    async def listgames(self, member, *args):
        # get the list of roles
        games = [role.name for role in self.guild.roles if role.id in self.games]

        return 'The game roles are:\n{}'.format(', '.join(games))

    # create a new game role
    @command(description='Create a new game role.', usage='game', admin_only=True)
    async def creategame(self, member, *args):
        if len(args) == 0:
            raise UsageException
        else:
            game = ' '.join(args)
            
            # check if role already exists
            role = find(lambda role: role.name.lower() == game.lower(), self.guild.roles)

            if role:
                # role already exists
                return '"{}" game already exists.'.format(self.games[args[0].lower()].name)
            else:
                # role doesn't exist
                role = await self.guild.create_role(name=game)
                self.games.append(role.id)
                return 'Created "{}" game.'.format(game)

    @command(description='')
    async def test(self, member, *args):
        await None.send('Test')
        
# start the bot
Bot()
