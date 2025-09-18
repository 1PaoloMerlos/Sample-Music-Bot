# Importing libraries and modules
import os
import re
import discord
import yt_dlp
import asyncio
from collections import deque
from discord.ext import commands
from discord import app_commands
from discord.ext import commands #discord help command addition
from dotenv import load_dotenv
import spotipy  # Spotify integration
from spotipy.oauth2 import SpotifyClientCredentials # Spotify function authentication declaration


# Environment variables for tokens and other sensitive data
load_dotenv("dc_env/.env")
TOKEN = os.getenv("DISCORD_TOKEN")

# Spotify credentials - Needed for spotify API to access track info
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET")
))

# Create the structure for queueing songs - Dictionary of queues
SONG_QUEUES = {}
DISCONNECT_TIMERS = {}
DISCONNECT_DELAY = 300 

async def search_ytdlp_async(query, ydl_opts):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _extract(query, ydl_opts))

def _extract(query, ydl_opts):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(query, download=False)
    
def get_source(audio_url, ffmpeg_options):
    return discord.FFmpegOpusAudio(
        audio_url,
        **ffmpeg_options,
        executable="bin\\ffmpeg\\ffmpeg.exe"
    )

# Setup of intents. Intents are permissions the bot has on the server
intents = discord.Intents.default()
intents.message_content = True

# Custom help command
class HelpCommand(commands.DefaultHelpCommand):
    async def send_bot_help(self, mapping):
        help_message = """
        **Ti commands exoumentes:**

        **/play link or name** - play songs from YOUTUBE/SPOTIFY
        Example: `/play Chinese rap`

        **/skip** - Skips the song

        **/pause** - Pauses the song

        **/continue** - Continues playing the paused song

        **/clear** - Clears the song queue

        **/leave** - Leaves the voice channel
        """
        channel = self.context.channel
        await channel.send(help_message)

# Bot setup with custom help command
bot = commands.Bot(command_prefix="!", intents=intents, help_command=HelpCommand())


# Bot ready-up code
@bot.event
async def on_ready():
    await bot.tree.sync()  # Make sure slash commands sync
    print(f"{bot.user} is online and ready!")

async def disconnect_after_delay(guild_id, voice_client, channel):
    await asyncio.sleep(DISCONNECT_DELAY)
    if guild_id in SONG_QUEUES and not SONG_QUEUES[guild_id]:
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()
            await channel.send("**I'm leaving**")
        if guild_id in DISCONNECT_TIMERS:
            del DISCONNECT_TIMERS[guild_id]

@bot.tree.command(name="pause", description="Pause the currently playing song.")
async def pause(interaction: discord.Interaction):
    guild_id_str = str(interaction.guild_id)
    if guild_id_str in DISCONNECT_TIMERS:
        DISCONNECT_TIMERS[guild_id_str].cancel()
        del DISCONNECT_TIMERS[guild_id_str]
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        return await interaction.response.send_message("I'm not in voice chat")
    if not voice_client.is_playing():
        return await interaction.response.send_message("There is nothing playing at the moment")
    voice_client.pause()
    await interaction.response.send_message("Taking a break")

@bot.tree.command(name="continue", description="Continuing song")
async def resume(interaction: discord.Interaction):
    guild_id_str = str(interaction.guild_id)
    if guild_id_str in DISCONNECT_TIMERS:
        DISCONNECT_TIMERS[guild_id_str].cancel()
        del DISCONNECT_TIMERS[guild_id_str]
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        return await interaction.response.send_message("I'm not in a channel")
    if not voice_client.is_paused():
        return await interaction.response.send_message("I'm not paused")
    voice_client.resume()
    await interaction.response.send_message("Playing song")

# Command to clear the queue
@bot.tree.command(name="clear", description="Clear the song queue.")
async def clear_queue(interaction: discord.Interaction):
    guild_id_str = str(interaction.guild_id)
    if guild_id_str in DISCONNECT_TIMERS:
        DISCONNECT_TIMERS[guild_id_str].cancel()
        del DISCONNECT_TIMERS[guild_id_str]
    if guild_id_str in SONG_QUEUES:
        SONG_QUEUES[guild_id_str].clear()
        await interaction.response.send_message("Cleared the queue")
    else:
        await interaction.response.send_message("There is nothing in the queue to clear")

#command to disconnect the bot from the voice channel
@bot.tree.command(name="leave", description="Disconnect the bot from the voice channel.")
async def leave(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        return await interaction.response.send_message("I'm not in a voice channel")

    try:
        # First stop any ongoing playback
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        # Then disconnect
        await voice_client.disconnect()
        await interaction.response.send_message("I'm leaving")
        guild_id_str = str(interaction.guild_id)
        if guild_id_str in DISCONNECT_TIMERS:
            del DISCONNECT_TIMERS[guild_id_str]
        if guild_id_str in SONG_QUEUES:
            del SONG_QUEUES[guild_id_str]
    except Exception as e:
        print(f"Error disconnecting: {e}")
        await interaction.response.send_message("I had trouble leaving the channel")

# Check if the input is a YouTube URL
def is_youtube_url(query):
    youtube_patterns = [
        r"https?://(?:www\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]+",
        r"https?://(?:www\.)?youtu\.be/[A-Za-z0-9_-]+"
    ]
    return any(re.match(pattern, query) for pattern in youtube_patterns)

# Check if the input is a Spotify URL
def is_spotify_url(query):
    spotify_pattern = r"https?://open\.spotify\.com/(track|playlist)/[A-Za-z0-9]+" #added |playlist support
    return re.match(spotify_pattern, query)

# Fetch song name from Spotify URL
def get_spotify_track_name(url):
    try:
        track_id = url.split("track/")[1].split("?")[0]
        track_info = sp.track(track_id)
        return f"{track_info['artists'][0]['name']} - {track_info['name']}"
    except Exception as e:
        print(f"Error fetching Spotify track: {e}")
        return None
    
# fetch detail of single track
def get_spotify_track_info(url):
    "Get detailed track info from Spotify URL"
    try:
        track_id = url.split("track/")[1].split("?")[0]
        track = sp.track(track_id)
        return {
            'title': track['name'],
            'artist': track['artists'][0]['name'],
            'is_explicit': track.get('explicit', False)
        }
    except Exception as e:
        print(f"Spotify error: {e}")
        return None
    
#fetch all tracks from a Spotify playlist URL
def get_spotify_playlist_tracks(url):
    playlist_id = url.split("playlist/")[1].split("?")[0]
    results = sp.playlist_items(playlist_id)
    tracks = []
    for item in results['items']:
        track = item['track']
        tracks.append({
            'title': track['name'],
            'artist': track['artists'][0]['name'],
            'spotify_url': track['external_urls']['spotify']
        })
    return tracks

#pull playlist tracks from spotify and add them to the queue while playing 
async def fetch_spotify_playlist_async(interaction, playlist_url, ydl_options):
    guild_id = str(interaction.guild_id)
    if guild_id not in SONG_QUEUES:
        SONG_QUEUES[guild_id] = deque()

    playlist_tracks = get_spotify_playlist_tracks(playlist_url)
    voice_client = interaction.guild.voice_client

    for track in playlist_tracks:
        query = f"{track['artist']} - {track['title']} official audio"
        results = await search_ytdlp_async(f"ytsearch:{query}", ydl_options)
        entries = results.get("entries", [])
        if not entries:
            await interaction.followup.send(f"En ivra tpt me to: {query}")
            continue

        first_track = entries[0]
        audio_url = first_track["url"]
        title = first_track.get("title", "Untitled")

        SONG_QUEUES[guild_id].append((audio_url, title))
        print(f"Added '{title}' to queue")

        # Start playing immediately if nothing is playing
        if not voice_client.is_playing() and not voice_client.is_paused():
            await play_next_song(voice_client, guild_id, interaction.channel)

        await asyncio.sleep(0.5)  # optional small delay




# Play Command
@bot.tree.command(name="play", description="Add something to play from YouTube or Spotify or search based on name !")

@app_commands.describe(song_query="Spotify/YouTube URL or search query")

async def play(interaction: discord.Interaction, song_query: str):
    print(f"[/play] Command received with query: {song_query}")
    await interaction.response.defer()
    print(f"[/play] Interaction deferred.")
    guild_id_str = str(interaction.guild_id)
    if guild_id_str in DISCONNECT_TIMERS:
        print(f"[/play] Cancelling disconnect timer.")
        DISCONNECT_TIMERS[guild_id_str].cancel()
        del DISCONNECT_TIMERS[guild_id_str]
    try:
        print(f"[/play] Checking voice channel.")
        if not interaction.user.voice:
            print(f"[/play] User not in a voice channel.")
            return await interaction.followup.send("You will need to be in a channel to play music")
        print(f"[/play] Handling voice client.")
        voice_client = interaction.guild.voice_client

        if not voice_client:
            print(f"[/play] Connecting to voice channel.")
            voice_client = await interaction.user.voice.channel.connect()
            print(f"[/play] Connected to voice channel.")
        elif voice_client.channel != interaction.user.voice.channel:
            print(f"[/play] Moving to user's voice channel.")
            await voice_client.move_to(interaction.user.voice.channel)
            print(f"[/play] Moved to user's voice channel.")

        # YouTube DL options
        ydl_options = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "default_search": "ytsearch",
            "match_filter": lambda info: not any(
                word in info.get('title', '').lower()
                for word in ['clean', 'censored', 'radio edit']
            ),
        }

        print(f"[/play] Handling input query.")
        if is_spotify_url(song_query):
            if "track/" in song_query:
                track_info = get_spotify_track_info(song_query)
                if not track_info:
                    return await interaction.followup.send("Spotify track error get_spotify_track_info(song_query)")
                query_list = [f"{track_info['artist']} - {track_info['title']} official audio"]

                # Process single track like before
                for query in query_list:
                    print(f"[/play] Spotify search query: {query}")
                    results = await search_ytdlp_async(f"ytsearch:{query}", ydl_options)
                    tracks = results.get("entries", [])
                    if not tracks:
                        print(f"[/play] No tracks found for Spotify query: {query}")
                        await interaction.followup.send(f"I didn't find anything for: {query}")
                        continue
                    first_track = tracks[0]
                    audio_url = first_track["url"]
                    title = first_track.get("title", "Untitled")
                    print(f"[/play] Found track: {title} - URL: {audio_url}")

                    guild_id = str(interaction.guild_id)
                    if guild_id not in SONG_QUEUES:
                        SONG_QUEUES[guild_id] = deque()
                        print(f"[/play] Created new queue for guild {guild_id}.")

                    SONG_QUEUES[guild_id].append((audio_url, title))
                    print(f"[/play] Added '{title}' to the queue.")

            elif "playlist/" in song_query:
                #async playlist fetching
                playlist_tracks = get_spotify_playlist_tracks(song_query)
                if not playlist_tracks:
                    return await interaction.followup.send("Spotify playlist error get_spotify_playlist_tracks(song_query)")
                
                guild_id = str(interaction.guild_id)
                if guild_id not in SONG_QUEUES:
                    SONG_QUEUES[guild_id] = deque()

                for track in playlist_tracks:
                    query = f"{track['artist']} - {track['title']} official audio"
                    print(f"[/play] Spotify playlist search query: {query}")
                    results = await search_ytdlp_async(f"ytsearch:{query}", ydl_options)
                    tracks = results.get("entries", [])
                    if not tracks:
                        await interaction.followup.send(f"I didn't find anything for: {query}")
                        continue

                    first_track = tracks[0]
                    audio_url = first_track["url"]
                    title = first_track.get("title", "Untitled")
                    SONG_QUEUES[guild_id].append((audio_url, title))
                    print(f"[/play] Added '{title}' to the queue from playlist.")

                    #start playing immediately if nothing is playing
                    if not voice_client.is_playing() and not voice_client.is_paused():
                        await play_next_song(voice_client, guild_id, interaction.channel)

                    await asyncio.sleep(0.3)  #small delay to avoid blocking

                await interaction.followup.send("added playlist to queue")
                return  #stop further processing

        elif is_youtube_url(song_query):
            print(f"[/play] Input is a YouTube URL.")
            query = song_query
            ydl_options["default_search"] = None  # Don't prepend ytsearch
        elif song_query.startswith("https://") or song_query.startswith("http://"):
            return await interaction.followup.send("Only Spotify or YouTube links are supported")
        else:
            query = f"ytsearch:{song_query}"
            print(f"[/play] YouTube search query: {query}")

        # Handle single YouTube search or URL
        print(f"[/play] Searching with yt-dlp.")
        results = await search_ytdlp_async(query, ydl_options)
        tracks = results.get("entries", [])
        if not tracks:
            if "entries" in results and not results["entries"]:
                print(f"[/play] No tracks found for URL or search.")
                return await interaction.followup.send("I didn't find anything with the link or search")
            elif 'url' in results:
                tracks = [results]
            else:
                print(f"[/play] No tracks found.")
                return await interaction.followup.send("I didn't find anything")

        first_track = tracks[0]
        audio_url = first_track["url"]
        title = first_track.get("title", "Untitled")
        print(f"[/play] Found track: {title} - URL: {audio_url}")

        guild_id = str(interaction.guild_id)
        if guild_id not in SONG_QUEUES:
            SONG_QUEUES[guild_id] = deque()
            print(f"[/play] Created new queue for guild {guild_id}.")

        SONG_QUEUES[guild_id].append((audio_url, title))
        print(f"[/play] Added '{title}' to the queue.")

        if voice_client.is_playing() or voice_client.is_paused():
            print(f"[/play] Bot is playing music or it's paused. Sending 'added to queue' message.")
            await interaction.followup.send(f"Song:**{title}** Added to queue")
        else:
            print(f"[/play] Bot is not playing. Calling play_next_song.")
            await play_next_song(voice_client, guild_id, interaction.channel)
            await interaction.followup.send(f"**Now playing:** `{title}`")

    except Exception as e:
        print(f"[/play] Error in /play: {e}")
        await interaction.followup.send("Something went wrong while processing your request.")

# Function to handle playing the next song
async def play_next_song(voice_client, guild_id, channel):
    print("Inside play_next_song")
    print(f"play_next_song - voice_client: {voice_client}, connected: {voice_client.is_connected() if voice_client else None}")
    print(f"play_next_song - SONG_QUEUES.get({guild_id}): {SONG_QUEUES.get(guild_id)}")
    try:
        if not voice_client or not voice_client.is_connected():
            print("play_next_song - Voice client not valid or not connected.")
            return

        if not SONG_QUEUES.get(guild_id):
            print("play_next_song - Song queue is empty. Starting disconnect timer.")
            if guild_id in DISCONNECT_TIMERS:
                DISCONNECT_TIMERS[guild_id].cancel()
            DISCONNECT_TIMERS[guild_id] = asyncio.create_task(disconnect_after_delay(guild_id, voice_client, channel))
            return

        audio_url, title = SONG_QUEUES[guild_id].popleft()
        print(f"play_next_song - Playing: {title} - URL: {audio_url}")
        ffmpeg_options = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn -c:a libopus -b:a 96k",
        }
        source = get_source(audio_url, ffmpeg_options)

        def after_play(error):
            print("Inside after_play")
            if error:
                print(f"Playback error in after_play: {error}")
            try:
                asyncio.run_coroutine_threadsafe(
                    play_next_song(voice_client, guild_id, channel),
                    bot.loop
                )
            except Exception as e:
                print(f"Error in after_play calling play_next_song: {e}")

        # Start playback
        voice_client.play(source, after=after_play)
        print(f"play_next_song - Started playing: {title}")
        # REMOVED THE CHANNEL SEND HERE

    except discord.ClientException as e:
        print(f"Discord Client Exception in play_next_song: {e}")
        await channel.send("**Something went wrong - Client Exception**")
    except Exception as e:
        print(f"General Error in play_next_song: {e}")
        await channel.send("**Something went wrong :(**")

@bot.tree.command(name="skip", description="Skips the current playing song")
async def skip(interaction: discord.Interaction):
    guild_id_str = str(interaction.guild_id)
    if guild_id_str in DISCONNECT_TIMERS:
        DISCONNECT_TIMERS[guild_id_str].cancel()
        del DISCONNECT_TIMERS[guild_id_str]
    voice_client = interaction.guild.voice_client

    if not voice_client or not voice_client.is_connected():
        return await interaction.response.send_message("I'm not in a voice channel")

    if not voice_client.is_playing():
        return await interaction.response.send_message("There is nothing playing right now")

    # Check if queue exists and has songs
    if not SONG_QUEUES.get(guild_id_str):
        return await interaction.response.send_message("There is no next song in the queue to skip to")

    # Clean up current player
    if voice_client.is_playing():
        voice_client.stop()

    # Small delay to ensure clean transition
    await asyncio.sleep(0.5)

    # Get next song
    try:
        audio_url, title = SONG_QUEUES[guild_id_str].popleft()
    except IndexError:
        return await interaction.response.send_message("No more songs in the queue to skip to")

    ffmpeg_options = {
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        "options": "-vn -c:a libopus -b:a 96k -loglevel warning",
    }

    try:
        source = get_source(audio_url, ffmpeg_options)

        def after_play(error):
            if error:
                print(f"Error playing {title}: {error}")
            asyncio.run_coroutine_threadsafe(
                play_next_song(voice_client, guild_id_str, interaction.channel),
                bot.loop
            )

        voice_client.play(source, after=after_play)
        await interaction.response.send_message(f"Skipping Current song, Playing next: **{title}**")
    except Exception as e:
        print(f"Error in skip: {e}")
        await interaction.response.send_message("Something went wrong while trying to skip the song.")

# Run the bot
bot.run(TOKEN)
