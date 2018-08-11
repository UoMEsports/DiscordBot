# -*- coding: utf-8 -*-

import asyncio

from aiohttp import ClientSession
from configparser import ConfigParser
from csv import reader, writer
from datetime import datetime, timedelta
from discord import Client, Embed, File, Game, Streaming
from discord.abc import GuildChannel
from discord.utils import find
from functools import wraps
from io import BytesIO

# STUFF

# zero width joiner
zwj = '\u200d'

# incorrect usage error
class UsageError(Exception):
    def __init__(self, value=None):
        self.value = value

# command failed error
class CommandError(Exception):
    def __init__(self, value):
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
        self.config.read('config.cfg')

        loop = asyncio.get_event_loop()

        self.ready = asyncio.Event(loop=loop)        

        try:
            loop.run_until_complete(super().start(self.config.get('general', 'token')))
        except KeyboardInterrupt:
            loop.run_until_complete(super().logout())
        finally:
            loop.close()

    # UTILITIES

    # replace a command prefix token with the command prefix
    def rcpfx(self, text):
        return text.replace('%CPFX%', self.command_prefix)
        
    # process the command in a channel
    async def process_commands(self, message, member, content):
        channel = message.channel

        if channel in [self.bot_channel, self.admin_channel]:
            command, *args = content.split()
            command = command.replace(self.command_prefix, '', 1).lower()

            if command in self.commands and (channel == self.admin_channel or not self.commands[command]['admin_only']):
                return await self.commands[command]['cmd'](*args, member=member, channel=channel)
            else:
                return await channel.send(embed=self.response_embed('Command "{0}{1}" not found. Use "{0}help" to get the list of commands.'.format(self.command_prefix, command), False))
        else:
            if isinstance(channel, GuildChannel):
                await message.delete()
            return await self.bot_channel.send(member.mention, embed=self.response_embed('Use commands here.', False))

    # WRAPPERS

    # event wrapper
    def event():
        def wrapper(func):
            func.bot_event = True
            
            @wraps(func)
            async def sub_wrapper(self, *args, **kwargs):
                try:
                    return await func(self, *args, **kwargs)
                except asyncio.CancelledError:
                    # ignore these - spam when bot restarts
                    return
                except Exception as ex:
                    err = 'Unhandled {} in event {}: {}'.format(ex.__class__.__name__,
                                                                func.__name__,
                                                                ex)
                    log(err)
                    return self.admin_channel.send(err)
                    
            return sub_wrapper
        return wrapper

    # command wrapper
    def command(description, usage='', admin_only=False, category='General'):
        def wrapper(func):
            func.bot_command = True
            func.description = description
            func.usage = usage
            func.admin_only = admin_only
            func.category = category
            
            @wraps(func)
            async def sub_wrapper(self, *args, **kwargs):
                try:
                    response = await func(self, *args, **kwargs)
                    success = True
                except UsageError as ex:
                    response = 'Correct usage is "{}{} {}"{}'.format(self.command_prefix,
                                                                     func.__name__,
                                                                     self.rcpfx(usage),
                                                                     '\n{}'.format(ex.value) if ex.value else '')
                    success = False
                except CommandError as ex:
                    response = ex.value
                    success = False
                except asyncio.CancelledError:
                    # ignore these - spam when bot restarts
                    return
                except Exception as ex:
                    # unhandled exception
                    err = 'Unhandled {} in command {}{} by {}: {}'.format(ex.__class__.__name__,
                                                                          self.command_prefix,
                                                                          func.__name__,
                                                                          kwargs['member'],
                                                                          ex)
                    log(err)
                    await self.admin_channel.send(err)
                    response = 'Sorry, that command failed.'
                    success = False

                if response:
                    if isinstance(response, Embed):
                        return await kwargs['channel'].send(embed=response)
                    else:
                        return await kwargs['channel'].send(embed=self.response_embed(response, success))
                    
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
                except asyncio.CancelledError:
                    # ignore these - spam when bot restarts
                    return
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
                      description=self.rcpfx('{}\nUsage: {}{} {}'.format(cmd.description, self.command_prefix, cmd.__name__, cmd.usage)),
                      color=self.admin_role.colour if cmd.admin_only else self.member_role.colour)
        embed.set_author(name='Esports Bot')
        if cmd.admin_only:
            embed.set_footer(text='Admin-only command.')

        return embed
    
    # response embed
    def response_embed(self, response, success):
        return Embed(description=response,
                     color=0x00ff00 if success else 0xff0000)

    # EVENTS
        
    # output to terminal if the bot successfully logs in
    @event()
    async def on_ready(self):        
        # output information about the bot's login
        log('Logged in as {0}, {0.id}'.format(self.user))

        # command prefix
        self.command_prefix = self.config.get('general', 'command_prefix')

        # bot name
        self.name = self.config.get('general', 'name')

        # read guild variable ids from the config file and intialise them as global variables
        self.guild = self.get_guild(int(self.config.get('general', 'guild')))

        # channels
        self.bot_channel = self.guild.get_channel(int(self.config.get('channels', 'bot')))
        self.admin_channel = self.guild.get_channel(int(self.config.get('channels', 'admin')))

        # roles
        self.admin_role = find(lambda role: role.id == int(self.config.get('roles', 'admin')), self.guild.roles)
        self.member_role = find(lambda role: role.id == int(self.config.get('roles', 'member')), self.guild.roles)
        self.guest_role = find(lambda role: role.id == int(self.config.get('roles', 'guest')), self.guild.roles)

        # produce the list of commands
        self.commands = {}
        for att in dir(self):
            attr = getattr(self, att, None)
            if hasattr(attr, 'bot_command'):
                self.commands[att] = {'cmd': attr, 'admin_only': attr.admin_only, 'embed': self.cmd_embed(attr)}
                
        # change the nickname of the bot to its name
        await self.guild.me.edit(nick=self.name)

        # maintain the bots presence
        asyncio.ensure_future(self.maintain_presence())

        # generate the help embeds
        self.help_embed = Embed(title='Commands',
                                color=self.member_role.colour)
        for category in ['General', 'Games', 'Roles']:
            self.help_embed.add_field(name=category,
                                      value='\n'.join(['{}{}'.format(self.command_prefix, command) for command in self.commands if not self.commands[command]['admin_only'] and self.commands[command]['cmd'].category == category]),)
        self.help_embed.set_footer(text='Type "{}help command" to get its usage.'.format(self.command_prefix))
        self.admin_embed = Embed(title='Admin Commands',
                                 color=self.admin_role.colour)
        for category in ['General', 'Games', 'Roles']:
            self.admin_embed.add_field(name=category,
                                       value='\n'.join(['{}{}'.format(self.command_prefix, command) for command in self.commands if self.commands[command]['cmd'].category == category]))
        self.admin_embed.set_footer(text='Type "{}help command" to get its usage.'.format(self.command_prefix))
        
        # generate the game roles
        self.games = []
        with open('games.txt', 'r') as f:
            for line in f:
                try:
                    id = int(line.strip())

                    role = find(lambda role: role.id == id, self.guild.roles)

                    # check if role exists
                    if role:
                        self.games.append(role)
                    else:
                        # role doesn't exist
                        log('Couldn\'t find role with ID {}'.format(id))
                except Exception as ex:
                    log('Unhandled {} while reading in role ID {}: {}'.format(ex.__class__.__name__,
                                                                              line.strip(),
                                                                              ex))

        with open('games.txt', 'w') as f:
            for role in self.games:
                f.write('{}\n'.format(role.id))
        
        # ready to go!
        log('------')
        self.ready.set()
        
    # check the contents of the message
    @event()
    async def on_message(self, message):
        # wait until the bot is ready
        await self.ready.wait()

        # process responses if message isn't from user:
        if message.author != self.user:
            # get the message content in a managable format
            content = message.content.strip()

            # get the member who sent the message
            member = self.guild.get_member(message.author.id)
            
            # check whether a command has been given
            if member and content.startswith(self.command_prefix):
                return await self.process_commands(message, member, content)

    # check if a deleted role was a game role
    @event()
    async def on_guild_role_delete(self, role):
        if role in self.games:
            self.games.remove(role)

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
    async def help(self, *args, **kwargs):
        if len(args) == 0:
            # give the correct version of the help text
            if kwargs['channel'] == self.admin_channel:
                return self.admin_embed
            else:
                return self.help_embed
        elif len(args) == 1:
            # find the command
            command = args[0].lower().replace(self.command_prefix, '')
            if command in self.commands and (not self.commands[command]['admin_only'] or kwargs['channel'] == self.admin_channel):
                return self.commands[command]['embed']
            else:
                raise CommandError('Command {}{} not found.'.format(self.command_prefix, command))
        else:
            raise UsageError

    # GAME ROLE COMMANDS

    # add game role
    @command(description='Add a game role.', usage='game', category='Games')
    async def addgame(self, *args, **kwargs):
        if len(args) == 0:
            raise UsageError
        else:
            game = ' '.join(args)

            role = find(lambda role: role.name.lower() == game.lower(), self.games)

            if role:
                # role exists
                if role in kwargs['member'].roles:
                    # member already has the role
                    raise CommandError('You already have "{}" role.'.format(role.name))
                else:
                    # member doesn't have role
                    await kwargs['member'].add_roles(*[role])
                    return 'Added "{}" role.'.format(role.name)
            else:
                # role doesn't exist
                raise CommandError('Didn\'t recognise "{}" role.'.format(game))

    # remove game role
    @command(description='Remove a game role.', usage='games', category='Games')
    async def removegame(self, *args, **kwargs):
        if len(args) == 0:
            raise UsageError
        else:
            game = ' '.join(args)

            role = find(lambda role: role.name.lower() == game.lower(), self.games)

            if role:
                # role exists
                if role in kwargs['member'].roles:
                    # member already has the role
                    await kwargs['member'].remove_roles(*[role])
                    return 'Removed "{}" role.'.format(role.name)
                else:
                    # member doesn't have role
                    raise CommandError('You don\'t have "{}" role.'.format(role.name))
            else:
                # role doesn't exist
                raise CommandError('Didn\'t recognise "{}" role.'.format(game))

    # list the game roles
    @command(description='List the game roles.', category='Games')
    async def listgames(self, *args, **kwargs):
        # get the list of roles
        games = [role.name for role in self.games]

        return 'The game roles are:\n{}'.format(', '.join(games))

    # create a new game role
    @command(description='Create a new game role.', usage='game', admin_only=True, category='Games')
    async def creategame(self, *args, **kwargs):
        if len(args) == 0:
            raise UsageError
        else:
            game = ' '.join(args)
            
            # check if role already exists
            role = find(lambda role: role.name.lower() == game.lower(), self.games)

            if role:
                # role already exists
                raise CommandError('"{}" game already exists.'.format(self.games[args[0].lower()].name))
            else:
                # role doesn't exist
                role = await self.guild.create_role(name=game)
                self.games.append(role)
                with open('games.txt', 'a') as f:
                    f.write('{}\n'.format(role.id))
                return 'Created "{}" game.'.format(game)

    # make yourself a member
    @command(description='Give yourself the member role.', category='Roles')
    async def member(self, *args, **kwargs):
        if self.member_role in kwargs['member'].roles:
            raise CommandError('You already have the member role.')
        else:
            await edit_roles(kwargs['member'], add=[self.member_role], remove=[self.guest_role])
            return 'Adding member role.'

    # make yourself a guest
    @command(description='Give yourself the guest role.', category='Roles')
    async def guest(self, *args, **kwargs):
        if self.guest_role in kwargs['member'].roles:
            raise CommandError('You already have the guest role.')
        else:
            await edit_roles(kwargs['member'], add=[self.guest_role], remove=[self.member_role])
            return 'Adding guest role.'
    
    # restart the bot
    @command(description='Restart the bot.', admin_only=True)
    async def restart(self, *args, **kwargs):
        await kwargs['channel'].send(embed=self.response_embed('Restarting.', True))
        log('Restarting the bot.')
        log('------')
        await self.logout()
        
# start the bot
Bot()
