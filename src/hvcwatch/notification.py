import logging

import structlog
from discord_webhook import DiscordEmbed, DiscordWebhook

from hvcwatch.config import settings
from hvcwatch.utils import format_number, get_ticker_details, get_ticker_stats

logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()


class DiscordNotifier:
    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        self.ticker_details = self.get_ticker_details()
        self.ticker_stats = self.get_ticker_volume()

    def get_ticker_details(self) -> dict:
        return get_ticker_details(self.ticker)

    def get_ticker_volume(self) -> dict:
        return get_ticker_stats(self.ticker)

    def build_description(self) -> str:
        volume = format_number(self.ticker_stats["volume"])
        volume_sma = format_number(self.ticker_stats["volume_sma"])
        volume_ratio = self.ticker_stats["volume"] / self.ticker_stats["volume_sma"]

        desc = [
            "Current price: ${:.2f}".format(self.ticker_stats["close"]),
            f"Volume vs avg: {volume} / {volume_sma} **{volume_ratio:.2f}x**",
        ]
        return "\n".join(desc)

    def notify_discord(self) -> None:
        """Send a notification to Discord via webhook."""
        logger.info("Sending to Discord", ticker=self.ticker)
        webhook = DiscordWebhook(
            url=settings.discord_webhook_url,
            rate_limit_retry=True,
        )

        embed = DiscordEmbed(
            title=f"{self.ticker_details['name']} ({self.ticker})",
            description=self.build_description(),
            color="03b2f8",
        )
        embed.set_thumbnail(url=self.ticker_details["logo_url"])
        embed.set_footer(text="HVC Watch · Major's Bots")
        embed.set_image(url=settings.transparent_png)
        embed.set_timestamp()
        webhook.add_embed(embed)
        response = webhook.execute()
        logger.info(f"Discord response: {response.status_code}")
