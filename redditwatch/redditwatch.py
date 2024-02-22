import asyncio
import asyncpraw
from redbot.core import Config, app_commands, commands, checks

class redditwatch(commands.Cog):
    """Cog to watch a specific Reddit post for new comments"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)  # Unique identifier

        # Set default config values
        default_guild = {
            "reddit_post_url": "",
            "discord_channel_id": 0,
            "last_checked_timestamp": 0,
            "client_id": "",
            "client_secret": "",
            "user_agent": ""
        }
        self.config.register_guild(**default_guild)
        

        # Initialize Reddit client
        self.reddit = None
        asyncio.create_task(self.setup_reddit_client())

        # Start watching for new comments
        asyncio.create_task(self.watch_comments())

    async def setup_reddit_client(self):
        await self.bot.wait_until_ready()

        # Get Reddit API credentials from config
        client_id = await self.config.client_id()
        client_secret = await self.config.client_secret()
        user_agent = await self.config.user_agent()

        # Check if credentials are set
        if not client_id or not client_secret or not user_agent:
            print("Reddit API credentials not set. Use the setredditapi command to set them.")
            return

        # Initialize Reddit client
        self.reddit = asyncpraw.Reddit(client_id=client_id,
                                  client_secret=client_secret,
                                  user_agent=user_agent)

        # Close the client session
        await self.reddit.close()

    async def watch_comments(self):
        await self.bot.wait_until_ready()

        # Get the guild ID from the configuration
        guild_id = await self.config.guild_id()

        while not self.bot.is_closed():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                print("Guild not found. Make sure the guild ID is set correctly.")
                return

            reddit_post_url = await self.config.guild(guild).reddit_post_url()
            discord_channel_id = await self.config.guild(guild).discord_channel_id()
            last_checked_timestamp = await self.config.guild(guild).last_checked_timestamp()

            # Initialize a new Reddit client for each iteration to avoid unclosed session errors
            async with asyncpraw.Reddit(client_id=await self.config.client_id(),
                                         client_secret=await self.config.client_secret(),
                                         user_agent=await self.config.user_agent()) as reddit:

                # Get comments from the Reddit post
                post = reddit.submission(url=reddit_post_url)
                post.comments.replace_more(limit=None)
                comments = post.comments.list()

                # Check for new comments
                for comment in comments:
                    if comment.created_utc > last_checked_timestamp:
                        # Log the new comment
                        print(f"New Comment: {comment.body}")

                        # Post comment to Discord
                        channel = self.bot.get_channel(discord_channel_id)
                        await channel.send(f'New Comment: {comment.body}')

                        # Update last_checked_timestamp
                        await self.config.guild(guild).last_checked_timestamp.set(comment.created_utc)

            # Wait for some time before checking again (e.g., 30 seconds)
            await asyncio.sleep(30)

    @commands.group()
    async def redditwatch(self, ctx):
        """redditwatch commands."""
        pass

    @redditwatch.command()
    @checks.is_owner()
    async def setredditapi(self, ctx, client_id: str, client_secret: str, user_agent: str):
        """Set the Reddit API credentials."""
        await self.config.client_id.set(client_id)
        await self.config.client_secret.set(client_secret)
        await self.config.user_agent.set(user_agent)
        await ctx.send("Reddit API credentials set successfully.")

    @redditwatch.command()
    async def setconfig(self, ctx, reddit_post_url: str, discord_channel_id: int):
        """Set the Reddit post URL and Discord channel ID for watching."""
        await self.config.guild(ctx.guild).reddit_post_url.set(reddit_post_url)
        await self.config.guild(ctx.guild).discord_channel_id.set(discord_channel_id)
        await ctx.send("Config set successfully.")

def setup(bot):
    bot.add_cog(redditwatch(bot))