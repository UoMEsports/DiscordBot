# -*- coding: utf-8 -*-

import asyncio

from aiohttp import ClientSession
from configparser import ConfigParser
from csv import reader, writer
from datetime import datetime, timedelta
from discord import Client, Embed, File, Game, NotFound, Streaming
from discord.utils import find
from functools import wraps
from io import BytesIO
from operator import itemgetter

# ERRORS

# incorrect usage error
class UsageError(Exception):
    pass

# command failed error
class CommandError(Exception):
    pass

# FILE MANAGEMENT

# write the strikes to strikes.csv
def write_strikes(strikes):
    with open('strikes.csv', 'w', newline='', encoding='utf-8') as f:
        swriter = writer(f, delimiter=',', quotechar='\'')

        # write out the header line
        swriter.writerow(['ID', 'Username', 'Reason #1', 'Reason #2', 'Reason #3', 'Unban date'])

        for id in strikes:
            swriter.writerow([id] + strikes[id])

# UTILITY

# log to file and console
def log(message):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M') 
    print('[{0}]: {1}'.format(ts, message))
    with open('out.log', 'a') as f:
        f.write('[{}]: {}\n'.format(ts, message))

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

    # FILE MANAGEMENT

    # read the strikes in from the file
    async def read_strikes(self):
        try:
            with open('strikes.csv', 'r', newline='', encoding='utf-8') as f:
                sreader = reader(f, delimiter=',', quotechar='\'')

                if sreader:
                    # skip the header line
                    next(sreader)
                    
                    strikes = {}
                    for line in sreader:
                        strikes[line[0]] = line[1:]

                    # check if the usernames have changed
                    for sid in strikes:
                        try:
                            user = await self.get_user_info(int(sid))
                            strikes[sid][0] = str(user)
                        except NotFound:
                            # couldn't find user
                            log('Couldn\'t find user with ID {}'.format(sid))
                            strikes.pop(sid)
                else:
                    # strikes file is empty
                    strikes = {}
        except FileNotFoundError:
            # file not found
            log('Strikes file is empty - making one')
            strikes = {}
        finally:
            write_strikes(strikes)
            return strikes

    # write the config file
    def write_config(self):
        with open('config.cfg', 'w') as f:
            self.config.write(f)

    # UTILITIES

    # confirm a command
    async def confirm(self, member, channel, prompt, timeout=60.):
        # check message is from the user
        def check(message):
            return message.author == member and message.channel == channel

        try:
            while True:
                await channel.send(embed=self.response_embed('{} (y/n)'.format(prompt)))
                
                message = await self.wait_for('message', check=check, timeout=timeout)

                response = message.content.strip().lower()

                if response in ['y', 'yes']:
                    return True
                elif response in ['n', 'no']:
                    await channel.send(embed=self.response_embed('Aborted.'))
                    return False
                else:
                    await channel.send(embed=self.response_embed('Didn\'t recognise "{}".'.format(message.content.strip()), False))
        except asyncio.TimeoutError:
            await channel.send(embed=self.response_embed('Timed out after {} seconds.'.format(int(timeout)), False))
            return False

    # replace a command prefix token with the command prefix
    def rcpfx(self, text):
        return text.replace('CPFX', self.command_prefix)
        
    # process the command in a channel
    async def process_commands(self, message, member, content):
        command, *args = content.split()
        command = command.replace(self.command_prefix, '', 1).lower()
        channel = message.channel

        if command in self.commands and (channel == self.admin_channel or not self.commands[command]['admin_only']):
            return await self.commands[command]['cmd'](*args, member=member, channel=channel, roles=message.role_mentions, mentions=message.mentions)
        else:
            return await channel.send(embed=self.response_embed('Command "{0}{1}" not found. Use "{0}help" to get the list of commands.'.format(self.command_prefix, command), False))

    # WRAPPERS

    # event wrapper
    def event(wait_until_ready=True):
        def wrapper(func):
            func.bot_event = True
            
            @wraps(func)
            async def sub_wrapper(self, *args, **kwargs):
                if wait_until_ready:
                    # wait until the bot is ready
                    await self.ready.wait()
                    
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
                    return self.admin_channel.send(embed=self.response_embed(err, False))
                    
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
                                                                     ex)
                    success = False
                except CommandError as ex:
                    response = str(ex)
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
                    print(self.admin_channel)
                    await self.admin_channel.send(embed=self.response_embed(err, False))
                    response = 'Sorry, that command failed.'
                    success = False
                finally:
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
                    
                    # set the bot to run
                    kwargs['state'] = 'run'
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
                    except asyncio.CancelledError:
                        # ignore these - spam when bot restarts
                        return
                    except Exception as ex:
                        err = 'Unhandled {} in process {}: {}'.format(ex.__class__.__name__,
                                                                      func.__name__,
                                                                      ex)
                        log(err)
                        await self.admin_channel.send(err)
                        if not retry:
                            kwargs['continue'] = 'end'
                            break
                    finally:
                        await asyncio.sleep(period)

                # finish the process
                try:
                    return await func(self, **kwargs)
                except asyncio.CancelledError:
                    # ignore these - spam when bot restarts
                    return
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
        embed.set_author(name='Esports Bot',
                         icon_url=self.user.avatar_url)
        if cmd.admin_only:
            embed.set_footer(text='Admin-only command.')

        return embed
    
    # response embed
    def response_embed(self, response, success=True):
        embed = Embed(description=response,
                      color=0x00ff00 if success else 0xff0000)
        embed.set_author(name='UoM Esports Bot',
                         icon_url=self.user.avatar_url)

        return embed

    def stream_embed(self, stream):
        e = Embed(color=0x5D3981, title=stream['channel']['url'])
        
        e.set_author(name='{} is now streaming!'.format(stream['channel']['display_name']), url=stream['channel']['url'], icon_url=self.user.avatar_url)

        e.add_field(name="Now Playing", value=stream['channel']['game'], inline=False)
        e.add_field(name="Stream Title", value=stream['channel']['status'], inline=False)

        e.set_thumbnail(url=stream['channel']['logo'])
        e.set_image(url=stream['preview']['large'])

        e.add_field(name="Followers", value=stream['channel']['followers'], inline=True)
        e.add_field(name="Total Views", value=stream['channel']['views'], inline=True)
        
        return e
        
    # EVENTS
        
    # output to terminal if the bot successfully logs in
    @event(wait_until_ready=False)
    async def on_ready(self):
        # output information about the bot's login
        log('Logged in as {0}, {0.id}'.format(self.user))

        # command prefix
        self.command_prefix = self.config.get('general', 'command_prefix')

        # read guild variable ids from the config file and intialise them as global variables
        self.guild = self.get_guild(int(self.config.get('general', 'guild')))

        # bot name
        await self.guild.me.edit(nick=self.config.get('general', 'name'))

        # channels
        self.bot_channel = self.guild.get_channel(int(self.config.get('channels', 'bot')))
        self.admin_channel = self.guild.get_channel(int(self.config.get('channels', 'admin')))
        self.stream_channel = self.guild.get_channel(int(self.config.get('channels', 'stream')))

        self.streaming = None

        # roles
        self.admin_role = find(lambda role: role.id == int(self.config.get('roles', 'admin')), self.guild.roles)
        self.member_role = find(lambda role: role.id == int(self.config.get('roles', 'member')), self.guild.roles)
        self.guest_role = find(lambda role: role.id == int(self.config.get('roles', 'guest')), self.guild.roles)
        self.first_strike_role = find(lambda role: role.id == int(self.config.get('roles', 'first_strike')), self.guild.roles)
        self.second_strike_role = find(lambda role: role.id == int(self.config.get('roles', 'second_strike')), self.guild.roles)

        with open('roles.txt', 'w') as f:
            for role in self.guild.roles:
                f.write('{0.name} {0.id}\n'.format(role))

        # produce the list of commands
        self.commands = {}
        for att in dir(self):
            attr = getattr(self, att, None)
            if hasattr(attr, 'bot_command'):
                self.commands[att] = {'cmd': attr, 'admin_only': attr.admin_only, 'embed': self.cmd_embed(attr)}

        # maintain the bots presence
        asyncio.ensure_future(self.maintain_presence())

        # check the unbans
        asyncio.ensure_future(self.check_unbans())

        # generate the help embeds
        self.help_embed = Embed(title='Commands',
                                color=self.member_role.colour)
        self.help_embed.set_author(name='UoM Esports Bot',
                                   icon_url=self.user.avatar_url)
        for category in ['General', 'Games', 'Roles']:
            self.help_embed.add_field(name=category,
                                      value='\n'.join(['{}{}'.format(self.command_prefix, command) for command in self.commands if not self.commands[command]['admin_only'] and self.commands[command]['cmd'].category == category]),)
        self.help_embed.set_footer(text='Type "{}help command" to get its usage.'.format(self.command_prefix))
        self.admin_embed = Embed(title='Admin Commands',
                                 color=self.admin_role.colour)
        self.admin_embed.set_author(name='UoM Esports Bot',
                                    icon_url=self.user.avatar_url)
        for category in ['General', 'Games', 'Roles']:
            self.admin_embed.add_field(name=category,
                                       value='\n'.join(['{0}{1}{2}{0}'.format('**' if self.commands[command]['admin_only'] else '', self.command_prefix, command) for command in self.commands if self.commands[command]['cmd'].category == category]))
        self.admin_embed.set_footer(text='Type "{}help command" to get its usage. Admin-only commands have bold formattng.'.format(self.command_prefix))
        
        # generate the game roles
        self.games = []
        for sid in self.config.get('roles', 'games').split():
            try:
                role = find(lambda role: role.id == int(sid), self.guild.roles)

                # check if role exists
                if role:
                    self.games.append(role)
                else:
                    # role doesn't exist
                    log('Couldn\'t find role with ID {}'.format(sid))
            except Exception as ex:
                log('Unhandled {} while reading in role ID {}: {}'.format(ex.__class__.__name__,
                                                                          sid,
                                                                          ex))

        # write out working game roles to the config file
        self.config.set('roles', 'games', ' '.join([str(role.id) for role in self.games]))
        self.write_config()
        
        # ready to go!
        log('------')
        self.ready.set()
        
    # check the contents of the message
    @event()
    async def on_message(self, message):
        # process responses if message isn't from user:
        if message.author != self.user and message.channel in [self.bot_channel, self.admin_channel] and not message.author.bot:
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
                        
    # when a member joins, send them a PM
    @event()
    async def on_member_join(self, member):
        # check if they have strikes
        sid = str(member.id)
        strikes = await self.read_strikes()
        if sid in strikes:
            if strikes[sid][2] == '':
                # user has 1 strike
                await member.send(embed=self.response_embed('You currently have 1 strike. Another strike will result in a 7-day ban. Please follow the rules in the future.', False))
                return await member.add_roles(*[self.first_strike_role])
            else:
                # user has 2 strikes
                await member.send(embed=self.response_embed('You currently have 2 strikes. Another strike will result in a permanent ban. Please follow the rules in the future.', False))
                return await member.add_roles(*[self.second_strike_role])

    # PERIODIC COROUTINES
    
    # maintain the bots presence on the server
    @process()
    async def maintain_presence(self, **kwargs):
        if kwargs['state'] == 'setup':
            # read in the stream
            twitch_channel = self.config.get('general', 'twitch_channel')

            # read in the default presence
            kwargs['presence'] = self.rcpfx(self.config.get('general', 'presence'))
            
            # the URLs
            kwargs['stream_URL'] = 'https://twitch.tv/{}'.format(twitch_channel)
            kwargs['API_URL'] = 'https://api.twitch.tv/kraken/streams/{}?client_id=6r0rm3qhbmjjq4z6vz4hez56tc9m4o'.format(twitch_channel)
        elif kwargs['state'] == 'run':
            # check if the stream is live
            async with ClientSession() as session:
                async with session.get(kwargs['API_URL']) as resp:
                    info = await resp.json(content_type='application/json')

            if info['stream'] == None:
                # nothing is streaming - use default presence

                self.streaming = False

                await self.change_presence(activity=Game(kwargs['presence']))
            else:
                # stream is live - use streaming presence

                if self.streaming is not None and self.streaming == False:
                    await self.stream_channel.send(embed=self.stream_embed(info['stream']))

                self.streaming = True

                await self.change_presence(activity=Streaming(name=info['stream']['channel']['status'], details=info['stream']['channel']['game'], url=kwargs['stream_URL']))

        return kwargs

    # check for unbans
    @process(period=3600.)
    async def check_unbans(self, **kwargs):
        if kwargs['state'] == 'run':
            strikes = await self.read_strikes()

            for sid in strikes:
                if strikes[sid][4] not in ['', 'never'] and datetime.now() > datetime.strptime(strikes[sid][4], '%Y-%m-%d %H:%M'):
                    strikes[sid][4] = ''

                    target_user = await self.get_user_info(int(sid))

                    if target_user in [entry.user for entry in await self.guild.bans()]:
                        # user is banned - unban them
                        await self.guild.unban(target_user)
                        await self.admin_channel.send(embed=self.response_embed('{} has been automatically unbanned after 7 days.'.format(strikes[sid][0])))
                    else:
                        # user is not banned or could not be unbanned
                        await self.admin_channel.send(embed=self.response_embed('{}\'s 7-day ban has expired but they couldn\'t be unbanned.'.format(strikes[sid][0]), False))

            # write to the strikes file
            write_strikes(strikes)

        return kwargs

    # COMMANDS

    # GENERAL
    
    # list the bot commands
    @command(description='List the bot commands and their usage.', usage='[command]')
    async def help(self, *args, **kwargs):
        if len(args) == 0:
            # give the correct version of the help text
            if kwargs['channel'] == self.admin_channel:
                return self.admin_embed
            else:
                return self.help_embed
        else:
            # find the command
            command = args[0].lower().replace(self.command_prefix, '')
            if command in self.commands and (not self.commands[command]['admin_only'] or kwargs['channel'] == self.admin_channel):
                return self.commands[command]['embed']
            else:
                raise CommandError('Command "{}{}" not found.'.format(self.command_prefix, command))

    # restart the bot
    @command(description='Restart the bot.', admin_only=True)
    async def restart(self, *args, **kwargs):
        await kwargs['channel'].send(embed=self.response_embed('Restarting.'))
        log('Restarting the bot')
        log('------')
        await self.logout()

    # test_stream
    @command(description='Generate test stream announcement', admin_only=True)
    async def teststream(self, *args, **kwargs):
        # check if the stream is live
        async with ClientSession() as session:
            async with session.get('https://api.twitch.tv/kraken/streams/failarmy?client_id=6r0rm3qhbmjjq4z6vz4hez56tc9m4o') as resp:
                info = await resp.json(content_type='application/json')

        return self.stream_embed(info['stream'])

    # GAMES

    # list the game roles
    @command(description='List the game roles.', category='Games')
    async def listgames(self, *args, **kwargs):
        # get the list of roles
        games = [role.name for role in self.games]

        embed = Embed(title='The game roles',
                      description='\n'.join(games),
                      color=0x00ff00)
        embed.set_author(name='UoM Esports Bot',
                         icon_url=self.user.avatar_url)

        return embed

    # get count of each role
    @command(description='Get count of each role.', admin_only=True, category='Games')
    async def rolecall(self, *args, **kwargs):

        games = []
        for role in self.games:
            games.append((role.name, len(role.members)))

        games = sorted(games,key=itemgetter(1),reverse=True)

        roles = '\n'.join(['**Member**', '**Guest**'] + [role[0] for role in games])

        counts = ['**' + str(len(self.member_role.members)) + '**', '**' + str(len(self.guest_role.members)) + '**']
        for role in games:
            counts.append(str(role[1]))
        counts = '\n'.join(counts)

        embed = Embed(title='Role call', color=0x00ff00)

        embed.add_field(name='Role', value=roles)
        embed.add_field(name='Count', value=counts)
        
        embed.set_author(name='UoM Esports Bot', icon_url=self.user.avatar_url)

        return embed

    # link game role
    @command(description='Link game role.', usage='<role ping>', admin_only=True, category='Games')
    async def linkgame(self, *args, **kwargs):
        if len(args) == 0:
            raise UsageError
        else:
            for role in kwargs['roles']:
                if role.id in self.games:
                    # role already exists
                    raise CommandError('"{}" role already exists.'.format(role.name))
                else:
                    # role doesn't exist
                    self.games.append(role)
                    self.config.set('roles', 'games', ' '.join([str(role.id) for role in self.games]))
                    self.write_config()
                    return 'Imported "{}" role.'.format(role.name)

    # unlink a game role
    @command(description='Unlink a game role.', usage='<role ping>', admin_only=True, category='Games')
    async def unlinkgame(self, *args, **kwargs):
        if len(args) == 0:
            raise UsageError
        else:
            for role in kwargs['roles']:
                if role in self.games:
                    # role exists
                    self.games.remove(role)
                    self.config.set('roles', 'games', ' '.join([str(role.id) for role in self.games]))
                    self.write_config()
                    return 'Deleted "{}" role.'.format(role.name)
                else:
                    # role doesn't exist
                    raise CommandError('"{}" role doesn\'t exist.'.format(role.name))

    # DISCIPLINE

    # strike a user
    @command(description='Strike a user with a given reason.', usage='<user_ping> <reason>', admin_only=True)
    async def strike(self, *args, **kwargs):
        if len(args) <= 1 or (not kwargs['mentions']):
            raise UsageError('"')
        elif len(kwargs['mentions']) > 1:
            raise UsageError('Ping a single user.')
        else:
            target = kwargs['mentions'][0]
            name = target.name
            reason = ' '.join(args[1:])

            if not self.guild.get_member(target.id):
                raise CommandError('Cannot find member "{}" in this server. '.format(name))

            sid = str(target.id)
            strikes = await self.read_strikes()
            if sid in strikes:
                if strikes[sid][2] == '':
                    # check if you want to give a 7-day ban
                    if await self.confirm(kwargs['member'], kwargs['channel'], 'Give {} a 7-day ban?'.format(name)):
                        strikes[sid][2] = reason
                        # unban_date = (datetime.now() + timedelta(days=7.)).strftime('%Y-%m-%d %H:%M')
                        unban_date = (datetime.now() + timedelta(minutes=1.)).strftime('%Y-%m-%d %H:%M')
                        strikes[sid][4] = unban_date
                        await target.send(embed=self.response_embed('You have been given a 7-day ban (second strike) for "{}". You will be unbanned at {}.'.format(reason, unban_date), False))
                        response = '{} has been given a 7-day ban (second strike) by {} for "{}". They will be unbanned at {}.'.format(name, kwargs['member'], reason, unban_date)
                        await self.guild.ban(target, reason=' '.join(['{}. {}'.format(i+1, strikes[sid][i+1]) for i in range(2)]+[unban_date]))
                else:
                    # check if you want to give a permanent ban
                    if await self.confirm(kwargs['member'], kwargs['channel'], 'Give {} a permanent ban?'.format(name)):
                        strikes[sid][3] = reason
                        strikes[sid][4] = 'never'
                        await target.send(embed=self.response_embed('You have been given a permanent ban (third strike) for "{}".'.format(reason), False))
                        response = '{} has been given a permanent ban (third strike) by {} for "{}".'.format(name, kwargs['member'], reason)
                        await self.guild.ban(target, reason=' '.join(['{}. {}'.format(i+1, strikes[sid][i+1]) for i in range(3)]+['Permanent ban']))
            else:
                strikes[sid] = [target, reason, '', '', '']
                await edit_roles(target, [self.first_strike_role], [self.first_strike_role, self.second_strike_role])
                await target.send(embed=self.response_embed('You have been given a first strike for "{}". One more strike will result in a 7-day ban. Please follow the rules in future.'.format(reason), False))
                response = '{} has been given a first strike by {} for "{}".'.format(name, kwargs['member'], reason)
                
            write_strikes(strikes)
            return response 

    # de-strike a user
    @command(description='De-strike a user.', usage='<user_ping>', admin_only=True)
    async def destrike(self, *args, **kwargs):
        if not kwargs['mentions']:
            raise UsageError('Ping the user you wish to destrike')
        elif len(kwargs['mentions']) > 1:
            raise UsageError('Ping a single user.')
        else:
            target_user = kwargs['mentions'][0]

            sid = str(target_user.id)
            strikes = await self.read_strikes()
            banned = target_user in [entry.user for entry in await self.guild.bans()]

            if sid in strikes:
                target_member = self.guild.get_member(int(sid))

                if strikes[sid][2] == '':
                    # 1 strike

                    # remove them from the strikes file
                    strikes.pop(sid)

                    if target_member:
                        # remove the strike roles
                        await target_member.remove_roles(*[self.first_strike_role, self.second_strike_role])
                        await target_user.send(embed=self.response_embed('Your first strike has been removed.'))
                        
                    response = '{}\'s first strike has been removed by {}.'.format(target_user, kwargs['member'])
                elif strikes[sid][3] == '':
                    # 2 strikes
                    strikes[sid][2] = ''
                    strikes[sid][4] = ''

                    if banned:
                        # target user is banned
                        await self.guild.unban(target_user)
                        response = '{}\'s second strike has been removed by {} and they have been unbanned.'.format(target_user, kwargs['member'])
                    else:
                        # target user is not banned
                        if target_member:
                            # edit the strike roles
                            await edit_roles(target_member, [self.first_strike_role], [self.first_strike_role, self.second_strike_role])
                            await target_user.send(embed=self.response_embed('Your second strike has been removed.'))
                            
                        response = '{}\'s second strike has been removed by {}.'.format(target_user, kwargs['member'])
                else:
                    # 3 strikes
                    strikes[sid][3] = ''
                    strikes[sid][4] = ''

                    if banned:
                        # target user is banned
                        await self.guild.unban(target_user)
                        response = '{}\'s third strike has been removed by {} and they have been unbanned.'.format(target_user, kwargs['member'])
                    else:
                        # target user is not banned
                        if target_member:
                            # edit the strike roles
                            await edit_roles(target_member, [self.second_strike_role], [self.first_strike_role, self.second_strike_role])
                            await target_user.send(embed=self.response_embed('Your third strike has been removed.'))
                            
                        response = '{}\'s third strike has been removed by {}.'.format(target_user, kwargs['member'])

                write_strikes(strikes)
                return response
            else:
                raise CommandError('Cannot find striked user "{}". Check the strikes file'.format(target_user.name))

    @command(description='See current active strike(s).', admin_only=True)
    async def strikes(self, *args, **kwargs):
        strikes = await self.read_strikes()

        strike_string = ''

        for sid in strikes:
            strike_string += '**' + strikes[sid][0] + '**: ' + strikes[sid][1] + '\n'

        embed = Embed(color=0x00ff00)

        embed.add_field(name='Strikes', value=strike_string)
        
        embed.set_author(name='UoM Esports Bot', icon_url=self.user.avatar_url)

        return embed

    @command(description='Get ids of members with strikes. Useful for `!destrike`', admin_only=True)
    async def strikeids(self, *args, **kwargs):
        strikes = await self.read_strikes()

        strike_string = ''

        for sid in strikes:
            strike_string += '**' + strikes[sid][0] + '**: ' + sid + '\n'

        embed = Embed(color=0x00ff00)

        embed.add_field(name='Strike Ids', value=strike_string)
        
        embed.set_author(name='UoM Esports Bot', icon_url=self.user.avatar_url)

        return embed
        

    # view the strikes file
    @command(description='See the strikes file.', admin_only=True)
    async def strikesfile(self, *args, **kwargs):
        await kwargs['member'].send(embed=self.response_embed('The strikes file.'),
                                    file=File(fp='strikes.csv'))

        return 'DM\'d.'

# start the bot
Bot()
