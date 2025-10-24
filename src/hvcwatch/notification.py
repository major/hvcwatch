import logging
from typing import Protocol

import sentry_sdk
import structlog
from discord_webhook import DiscordEmbed, DiscordWebhook
from mastodon import Mastodon

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


class MastodonNotifier:
    """
    🐘 Mastodon notification provider.

    Implements the NotificationProvider protocol to send ticker alerts
    to Mastodon as text statuses with hashtags and market data.
    """

    def __init__(self, server_url: str, access_token: str) -> None:
        """
        Initialize Mastodon notifier with server credentials.

        Args:
            server_url: Mastodon instance URL (e.g., "https://mastodon.social")
            access_token: User access token for posting statuses
        """
        self.server_url = server_url
        self.access_token = access_token
        self.mastodon = Mastodon(
            access_token=access_token,
            api_base_url=server_url,
        )

    def build_status(self, ticker_data: TickerData) -> str:
        """
        🎨 Build formatted status text for Mastodon.

        Creates a concise status with company info, price, volume metrics,
        and relevant hashtags. Handles character limits gracefully.

        Args:
            ticker_data: Enriched ticker data

        Returns:
            Formatted status text (max ~450 chars to be safe)
        """
        volume = format_number(ticker_data.volume)
        volume_sma = format_number(ticker_data.volume_sma)

        # Build volume line
        if ticker_data.volume_sma is not None:
            volume_ratio = ticker_data.volume / ticker_data.volume_sma
            volume_line = (
                f"📊 Volume: {volume} (avg: {volume_sma}, {volume_ratio:.2f}x)"
            )
        else:
            volume_line = f"📊 Volume: {volume}"

        # Build the status components
        title = f"🔔 {ticker_data.name} (${ticker_data.ticker})"
        price_line = f"💰 Price: ${ticker_data.price:.2f}"

        # Build hashtags - keep them concise
        hashtags = f"#stocks #{ticker_data.ticker} #trading"

        # Combine all parts
        status_parts = [
            title,
            price_line,
            volume_line,
            "",  # Empty line before hashtags
            hashtags,
        ]

        status = "\n".join(status_parts)

        # Mastodon default limit is 500 chars, be conservative
        if len(status) > 450:
            # Truncate description if needed
            logger.warning(
                "Status exceeds recommended length, truncating",
                ticker=ticker_data.ticker,
                length=len(status),
            )
            status = status[:450] + "..."

        return status

    def send(self, ticker_data: TickerData) -> None:
        """
        📤 Send notification to Mastodon as a status.

        Args:
            ticker_data: Enriched ticker data to send

        Raises:
            Exception: Logs errors from Mastodon API but doesn't raise
        """
        logger.info("Sending to Mastodon", ticker=ticker_data.ticker)
        sentry_sdk.add_breadcrumb(
            category="notification",
            message="Sending Mastodon notification",
            level="info",
            data={
                "ticker": ticker_data.ticker,
                "platform": "Mastodon",
            },
        )

        try:
            status_text = self.build_status(ticker_data)

            # Post the status (toot)
            response = self.mastodon.status_post(
                status=status_text,
                visibility="public",  # Make it public by default
            )

            logger.info(
                "Mastodon status posted",
                ticker=ticker_data.ticker,
                status_id=response.get("id"),
                url=response.get("url"),
            )

        except Exception as e:
            logger.error(
                "Failed to post Mastodon status",
                ticker=ticker_data.ticker,
                error=str(e),
            )
            raise


def notify_all_platforms(ticker: str) -> None:
    """
    🎼 Orchestrate notifications across all enabled platforms.

    This function fetches ticker data once and sends it to all configured
    notification providers. Currently supports Discord, with more platforms
    coming in future phases (Mastodon, Slack, etc.).

    Platforms are only used if their credentials are configured. Missing
    credentials for a platform results in that platform being skipped
    gracefully without affecting other platforms.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")

    Raises:
        Exception: Logs errors but doesn't raise, allowing other platforms to continue
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

    # Send to Discord if configured
    if settings.discord_webhook_url:
        try:
            discord_notifier = DiscordNotifier()
            discord_notifier.send(ticker_data)
            logger.info(
                "Notification sent successfully", ticker=ticker, platform="Discord"
            )
            notifications_sent += 1
        except Exception as e:
            logger.error(
                "Failed to send notification",
                ticker=ticker,
                platform="Discord",
                error=str(e),
            )
    else:
        logger.debug("Discord webhook not configured, skipping", ticker=ticker)

    # Send to Mastodon if configured
    if settings.mastodon_server_url and settings.mastodon_access_token:
        try:
            mastodon_notifier = MastodonNotifier(
                server_url=settings.mastodon_server_url,
                access_token=settings.mastodon_access_token,
            )
            mastodon_notifier.send(ticker_data)
            logger.info(
                "Notification sent successfully", ticker=ticker, platform="Mastodon"
            )
            notifications_sent += 1
        except Exception as e:
            logger.error(
                "Failed to send notification",
                ticker=ticker,
                platform="Mastodon",
                error=str(e),
            )
    else:
        logger.debug("Mastodon credentials not configured, skipping", ticker=ticker)

    # Warn if no notifications were sent at all
    if notifications_sent == 0:
        logger.warning(
            "No notifications sent - no platforms configured",
            ticker=ticker,
        )
