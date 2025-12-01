import logging
from typing import Protocol

import sentry_sdk
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
    for notification platforms.

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

    def __init__(self, webhook_url: str) -> None:
        """
        Initialize Discord notifier with webhook URL.

        Args:
            webhook_url: Discord webhook URL for sending notifications
        """
        self.webhook_url = webhook_url

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
        sentry_sdk.add_breadcrumb(
            category="notification",
            message="Sending Discord notification",
            level="info",
            data={
                "ticker": ticker_data.ticker,
                "platform": "Discord",
            },
        )

        webhook = DiscordWebhook(
            url=self.webhook_url,
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
    🎼 Orchestrate notifications to Discord webhooks.

    This function fetches ticker data once and sends it to all configured
    Discord webhook URLs.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
    """
    logger.info("Fetching ticker data for notifications", ticker=ticker)
    sentry_sdk.add_breadcrumb(
        category="notification",
        message="Starting notification process",
        level="info",
        data={"ticker": ticker},
    )

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
        sentry_sdk.add_breadcrumb(
            category="notification",
            message="Ticker data fetched successfully",
            level="info",
            data={
                "ticker": ticker,
                "company": ticker_data.name,
                "price": ticker_data.price,
            },
        )

    except Exception as e:
        logger.error("Failed to fetch ticker data", ticker=ticker, error=str(e))
        sentry_sdk.capture_exception(e)
        return

    # Track if at least one notification was sent
    notifications_sent = 0

    # Send to Discord webhook(s) if configured
    discord_webhook_urls = settings.get_discord_webhook_urls()
    if discord_webhook_urls:
        for webhook_url in discord_webhook_urls:
            try:
                discord_notifier = DiscordNotifier(webhook_url=webhook_url)
                discord_notifier.send(ticker_data)
                logger.info(
                    "Notification sent successfully",
                    ticker=ticker,
                    platform="Discord",
                    webhook_url=webhook_url[:50] + "...",  # Truncate for logging
                )
                notifications_sent += 1
            except Exception as e:
                logger.error(
                    "Failed to send notification",
                    ticker=ticker,
                    platform="Discord",
                    webhook_url=webhook_url[:50] + "...",  # Truncate for logging
                    error=str(e),
                )
    else:
        logger.debug("Discord webhook not configured, skipping", ticker=ticker)

    # Warn if no notifications were sent at all
    if notifications_sent == 0:
        logger.warning(
            "No notifications sent - no Discord webhooks configured",
            ticker=ticker,
        )
