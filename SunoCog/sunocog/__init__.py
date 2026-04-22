from .sunocog import SunoCog

__red_end_user_data_statement__ = (
    "This cog does not persistently store personal data. "
    "It only fetches publicly accessible Suno song metadata at command time."
)


async def setup(bot):
    await bot.add_cog(SunoCog(bot))
