from __future__ import annotations

import contextlib
from typing import Any

import aiohttp
import lavalink
from lavalink import NodeNotFound
from red_commons.logging import getLogger
from redbot.core import commands
from redbot.cogs.audio.audio_dataclasses import Query
from redbot.cogs.audio.errors import TrackEnqueueError

from .parser import SunoSong, is_supported_suno_url, parse_suno_html

log = getLogger("red.Reece.SunoCog")


class SunoCog(commands.Cog):
    """Queue Suno share links into Red Audio."""

    def __init__(self, bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._patched_play_command = None
        self._original_play_callback = None
        self._patched_play_callback = None

    async def cog_load(self) -> None:
        await self._ensure_session()
        self._patch_audio_play_command()

    def cog_unload(self) -> None:
        self._unpatch_audio_play_command()
        if self._session and not self._session.closed:
            self.bot.loop.create_task(self._session.close())

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        if ctx.command and ctx.command.qualified_name == "play":
            self._patch_audio_play_command()

    @commands.guild_only()
    @commands.command(name="suno", aliases=["sunoplay"])
    async def suno(self, ctx: commands.Context, *, url: str) -> None:
        """Resolve a Suno share link and queue it in Audio."""
        audio = self.bot.get_cog("Audio")
        if audio is None:
            await ctx.send(f"Load Audio first with `{ctx.clean_prefix}load audio`.")
            return

        url = url.strip().strip("<>")
        if not is_supported_suno_url(url):
            await audio.send_embed_msg(
                ctx,
                title="Unsupported URL",
                description="Please provide a Suno song/share link from `suno.com` or `suno.ai`.",
            )
            return
        await self._handle_suno_play(audio, ctx, url)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session

        timeout = aiohttp.ClientTimeout(total=15)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
        }
        self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def _prepare_player(
        self, audio: Any, ctx: commands.Context, can_skip: bool
    ) -> lavalink.Player | None:
        if not audio._player_check(ctx):
            if audio.lavalink_connection_aborted:
                description = None
                if await self.bot.is_owner(ctx.author):
                    description = "Please check your console or logs for details."
                await audio.send_embed_msg(
                    ctx,
                    title="Connection to Lavalink node has failed",
                    description=description,
                )
                return None

            try:
                if (
                    not audio.can_join_and_speak(ctx.author.voice.channel)
                    or not ctx.author.voice.channel.permissions_for(ctx.me).move_members
                    and audio.is_vc_full(ctx.author.voice.channel)
                ):
                    await audio.send_embed_msg(
                        ctx,
                        title="Unable To Play Tracks",
                        description="I don't have permission to connect and speak in your channel.",
                    )
                    return None

                await lavalink.connect(
                    ctx.author.voice.channel,
                    self_deaf=await audio.config.guild_from_id(ctx.guild.id).auto_deafen(),
                )
            except AttributeError:
                await audio.send_embed_msg(
                    ctx,
                    title="Unable To Play Tracks",
                    description="Connect to a voice channel first.",
                )
                return None
            except NodeNotFound:
                await audio.send_embed_msg(
                    ctx,
                    title="Unable To Play Tracks",
                    description="Connection to the Lavalink node has not yet been established.",
                )
                return None

        player = lavalink.get_player(ctx.guild.id)
        player.store("notify_channel", ctx.channel.id)
        await audio._eq_check(ctx, player)
        await audio.set_player_settings(ctx)

        if (not ctx.author.voice or ctx.author.voice.channel != player.channel) and not can_skip:
            await audio.send_embed_msg(
                ctx,
                title="Unable To Play Tracks",
                description="You must be in the voice channel to use this command.",
            )
            return None

        return player

    async def _handle_suno_play(self, audio: Any, ctx: commands.Context, url: str) -> None:
        original_query = Query.process_input(url, audio.local_folder_current_path)
        if not await audio.is_query_allowed(
            audio.config, ctx, f"{original_query}", query_obj=original_query
        ):
            await audio.send_embed_msg(
                ctx,
                title="Unable To Play Tracks",
                description="That track is not allowed.",
            )
            return

        async with ctx.typing():
            try:
                song = await self._resolve_suno_song(url)
            except aiohttp.ClientResponseError as exc:
                await audio.send_embed_msg(
                    ctx,
                    title="Unable To Reach Suno",
                    description=f"Suno returned HTTP {exc.status} while resolving that link.",
                )
                return
            except aiohttp.ClientError:
                log.exception("Network failure while resolving Suno URL %s", url)
                await audio.send_embed_msg(
                    ctx,
                    title="Unable To Reach Suno",
                    description="I couldn't fetch that Suno page right now. Please try again in a moment.",
                )
                return
            except ValueError as exc:
                await audio.send_embed_msg(
                    ctx,
                    title="Unable To Parse Suno Link",
                    description=str(exc),
                )
                return

            guild_data = await audio.config.guild(ctx.guild).all()
            can_skip = await audio._can_instaskip(ctx, ctx.author)

            if guild_data["dj_enabled"] and not can_skip:
                await audio.send_embed_msg(
                    ctx,
                    title="Unable To Play Tracks",
                    description="You need the DJ role to queue tracks.",
                )
                return

            player = await self._prepare_player(audio, ctx, can_skip)
            if player is None:
                return

            if len(player.queue) >= 10000:
                await audio.send_embed_msg(
                    ctx,
                    title="Unable To Play Tracks",
                    description="Queue size limit reached.",
                )
                return

            if not await audio.maybe_charge_requester(ctx, guild_data["jukebox_price"]):
                return

            query = Query.process_input(song.audio_url, audio.local_folder_current_path)
            try:
                result, _called_api = await audio.api_interface.fetch_track(ctx, player, query)
            except TrackEnqueueError:
                await audio.send_embed_msg(
                    ctx,
                    title="Unable To Get Track",
                    description=(
                        "I'm unable to get a track from the Lavalink node right now. "
                        "Please try again in a few minutes."
                    ),
                )
                return

            if not result or not result.tracks:
                description = "Lavalink could not load the resolved Suno audio URL."
                if await audio.config.use_external_lavalink():
                    description += (
                        " If you use an external Lavalink node, make sure its HTTP source is enabled."
                    )
                if getattr(result, "exception_message", None):
                    description = f"{description}\n\n{result.exception_message[:1000]}"
                await audio.send_embed_msg(
                    ctx,
                    title="Unable To Play Tracks",
                    description=description,
                )
                return

            track = result.tracks[0]
            self._decorate_track(track, song)
            await audio._enqueue_tracks(ctx, [track])

    async def _resolve_suno_song(self, url: str) -> SunoSong:
        session = await self._ensure_session()
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            html = await response.text()
            return parse_suno_html(html, str(response.url))

    def _patch_audio_play_command(self) -> bool:
        audio = self.bot.get_cog("Audio")
        play_command = self.bot.get_command("play")
        if audio is None or play_command is None or getattr(play_command, "cog", None) is not audio:
            return False

        if (
            self._patched_play_command is play_command
            and play_command.callback is self._patched_play_callback
        ):
            return True

        self._unpatch_audio_play_command()
        original_callback = play_command.callback

        async def patched_play(audio_cog: Any, ctx: commands.Context, *, query: str) -> None:
            stripped_query = query.strip().strip("<>")
            if is_supported_suno_url(stripped_query):
                return await self._handle_suno_play(audio_cog, ctx, stripped_query)
            return await original_callback(audio_cog, ctx, query=query)

        patched_play.__doc__ = getattr(original_callback, "__doc__", None)
        patched_play.__name__ = getattr(original_callback, "__name__", "command_play")
        patched_play.__qualname__ = getattr(original_callback, "__qualname__", patched_play.__name__)

        play_command.callback = patched_play
        self._patched_play_command = play_command
        self._original_play_callback = original_callback
        self._patched_play_callback = patched_play
        log.debug("Patched Audio play command for Suno link support.")
        return True

    def _unpatch_audio_play_command(self) -> None:
        if (
            self._patched_play_command is not None
            and self._original_play_callback is not None
            and self._patched_play_command.callback is self._patched_play_callback
        ):
            self._patched_play_command.callback = self._original_play_callback
            log.debug("Restored original Audio play command callback.")

        self._patched_play_command = None
        self._original_play_callback = None
        self._patched_play_callback = None

    @staticmethod
    def _decorate_track(track: Any, song: SunoSong) -> None:
        with contextlib.suppress(Exception):
            track.title = song.title
        with contextlib.suppress(Exception):
            track.author = song.artist
        if song.image_url:
            with contextlib.suppress(Exception):
                track.artwork_url = song.image_url

        extras = getattr(track, "extras", None)
        if extras is not None:
            with contextlib.suppress(Exception):
                extras.update(
                    {
                        "suno_audio_url": song.audio_url,
                        "suno_image_url": song.image_url,
                        "suno_song_id": song.song_id,
                        "suno_url": song.canonical_url,
                    }
                )
