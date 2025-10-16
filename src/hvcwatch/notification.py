import logging
from typing import Protocol

import structlog
from discord_webhook import DiscordEmbed, DiscordWebhook

from hvcwatch.config import settings
from hvcwatch.models import TickerData
from hvcwatch.utils import format_number, get_ticker_details, get_ticker_stats

logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()


class NotificationProvider(Protocol):
    """
    🎭 Protocol for notification providers.

    Any class that implements a `send()` method accepting TickerData
    can be used as a notification provider. This enables duck typing
    and makes it easy to add new notification platforms (Mastodon,
    Slack, Telegram, etc.) without modifying existing code.

    Example:
        class MyNotifier:
            def send(self, ticker_data: TickerData) -> None:
                # Send notification to your platform
                pass
    """

    def send(self, ticker_data: TickerData) -> None:
        """
        📤 Send notification with enriched ticker data.

        Args:
            ticker_data: Enriched ticker data including company info and market stats
        """
        ...


class DiscordNotifier:
    """
    📢 Discord notification provider.

    Implements the NotificationProvider protocol to send ticker alerts
    to Discord using rich embeds with company logos and formatted data.
    """

    def build_description(self, ticker_data: TickerData) -> str:
        """
        🎨 Build formatted description for Discord embed.

        Args:
            ticker_data: Enriched ticker data

        Returns:
            Formatted description string with price and volume info
        """
        volume = format_number(ticker_data.volume)
        volume_sma = format_number(ticker_data.volume_sma)

        # Handle case where volume_sma might be None
        if ticker_data.volume_sma is not None:
            volume_ratio = ticker_data.volume / ticker_data.volume_sma
            volume_line = (
                f"Volume vs avg: {volume} / {volume_sma} **{volume_ratio:.2f}x**"
            )
        else:
            volume_line = f"Volume: {volume} (insufficient data for average)"

        desc = [
            "Current price: ${:.2f}".format(ticker_data.price),
            volume_line,
        ]
        return "\n".join(desc)

    def send(self, ticker_data: TickerData) -> None:
        """
        📤 Send notification to Discord via webhook.

        Args:
            ticker_data: Enriched ticker data to send
        """
        logger.info("Sending to Discord", ticker=ticker_data.ticker)
        webhook = DiscordWebhook(
            url=settings.discord_webhook_url,
            rate_limit_retry=True,
        )

        embed = DiscordEmbed(
            title=f"{ticker_data.name} ({ticker_data.ticker})",
            description=self.build_description(ticker_data),
            color="03b2f8",
        )
        embed.set_thumbnail(url=ticker_data.logo_url)
        embed.set_footer(text="HVC Watch · Major's Bots")
        embed.set_image(url=settings.transparent_png)
        embed.set_timestamp()
        webhook.add_embed(embed)
        response = webhook.execute()
        logger.info("Discord response", status_code=response.status_code)


def notify_all_platforms(ticker: str) -> None:
    """
    🎼 Orchestrate notifications across all enabled platforms.

    This function fetches ticker data once and sends it to all configured
    notification providers. Currently supports Discord, with more platforms
    coming in future phases (Mastodon, Slack, etc.).

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")

    Raises:
        Exception: Logs errors but doesn't raise, allowing other platforms to continue
    """
    logger.info("Fetching ticker data for notifications", ticker=ticker)

    try:
        # Fetch ticker data once for all platforms
        ticker_details = get_ticker_details(ticker)
        ticker_stats = get_ticker_stats(ticker)

        # Combine into TickerData model
        ticker_data = TickerData(
            ticker=ticker_details["ticker"],
            name=ticker_details["name"],
            description=ticker_details["description"],
            type=ticker_details["type"],
            logo_url=ticker_details["logo_url"],
            close=ticker_stats["close"],
            volume=ticker_stats["volume"],
            volume_sma=ticker_stats["volume_sma"],
            volume_ratio=ticker_stats["volume_ratio"],
        )

        logger.info("Ticker data fetched successfully", ticker=ticker)

    except Exception as e:
        logger.error("Failed to fetch ticker data", ticker=ticker, error=str(e))
        return

    # Send to Discord (only platform currently supported)
    # TODO: Add more platforms in future phases based on configuration
    try:
        discord_notifier = DiscordNotifier()
        discord_notifier.send(ticker_data)
        logger.info("Notification sent successfully", ticker=ticker, platform="Discord")
    except Exception as e:
        logger.error(
            "Failed to send notification",
            ticker=ticker,
            platform="Discord",
            error=str(e),
        )
