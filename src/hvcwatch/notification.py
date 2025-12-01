from typing import Literal, Protocol

import sentry_sdk
from discord_webhook import DiscordEmbed, DiscordWebhook

from hvcwatch.config import settings
from hvcwatch.logging import logger

# Type alias for timeframe
Timeframe = Literal["daily", "weekly", "monthly"]


class NotificationProvider(Protocol):
    """
    🎭 Protocol for notification providers.

    Any class that implements a `send()` method accepting ticker and timeframe
    can be used as a notification provider. This enables duck typing
    for notification platforms.
    """

    def send(self, ticker: str, timeframe: Timeframe) -> None:
        """
        📤 Send notification with ticker and timeframe.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL")
            timeframe: Alert timeframe ("daily", "weekly", or "monthly")
        """
        ...


class DiscordNotifier:
    """
    📢 Discord notification provider.

    Implements the NotificationProvider protocol to send ticker alerts
    to Discord using rich embeds.
    """

    def __init__(self, webhook_url: str) -> None:
        """
        Initialize Discord notifier with webhook URL.

        Args:
            webhook_url: Discord webhook URL for sending notifications
        """
        self.webhook_url = webhook_url

    def send(self, ticker: str, timeframe: Timeframe) -> None:
        """
        📤 Send notification to Discord via webhook.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL")
            timeframe: Alert timeframe ("daily", "weekly", or "monthly")
        """
        logger.info(
            "Sending to Discord ticker={ticker} timeframe={timeframe}",
            ticker=ticker,
            timeframe=timeframe,
        )
        sentry_sdk.add_breadcrumb(
            category="notification",
            message="Sending Discord notification",
            level="info",
            data={
                "ticker": ticker,
                "timeframe": timeframe,
                "platform": "Discord",
            },
        )

        webhook = DiscordWebhook(
            url=self.webhook_url,
            rate_limit_retry=True,
        )

        # Add 🔥 emoji for monthly alerts
        emoji = " 🔥" if timeframe == "monthly" else ""
        description = f"**Timeframe:** {timeframe.capitalize()}{emoji}"

        embed = DiscordEmbed(
            title=ticker,
            description=description,
            color="03b2f8",
        )
        embed.set_footer(text="HVC Watch · Major's Bots")
        embed.set_image(url=settings.transparent_png)
        embed.set_timestamp()
        webhook.add_embed(embed)
        response = webhook.execute()
        logger.info(
            "Discord response status_code={status_code}",
            status_code=response.status_code,
        )


def notify_all_platforms(ticker: str, timeframe: Timeframe = "daily") -> None:
    """
    🎼 Orchestrate notifications to Discord webhooks.

    Sends ticker alerts to all configured Discord webhook URLs.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        timeframe: Alert timeframe ("daily", "weekly", or "monthly")
    """
    logger.info(
        "Sending notifications ticker={ticker} timeframe={timeframe}",
        ticker=ticker,
        timeframe=timeframe,
    )
    sentry_sdk.add_breadcrumb(
        category="notification",
        message="Starting notification process",
        level="info",
        data={"ticker": ticker, "timeframe": timeframe},
    )

    # Track if at least one notification was sent
    notifications_sent = 0

    # Send to Discord webhook(s) if configured
    discord_webhook_urls = settings.get_discord_webhook_urls()
    if discord_webhook_urls:
        for webhook_url in discord_webhook_urls:
            try:
                discord_notifier = DiscordNotifier(webhook_url=webhook_url)
                discord_notifier.send(ticker, timeframe)
                logger.info(
                    "Notification sent successfully ticker={ticker} timeframe={timeframe} platform={platform} webhook_url={webhook_url}",
                    ticker=ticker,
                    timeframe=timeframe,
                    platform="Discord",
                    webhook_url=webhook_url[:50] + "...",  # Truncate for logging
                )
                notifications_sent += 1
            except Exception as e:
                logger.error(
                    "Failed to send notification ticker={ticker} platform={platform} webhook_url={webhook_url} error={error}",
                    ticker=ticker,
                    platform="Discord",
                    webhook_url=webhook_url[:50] + "...",  # Truncate for logging
                    error=str(e),
                )
    else:
        logger.debug(
            "Discord webhook not configured, skipping ticker={ticker}", ticker=ticker
        )

    # Warn if no notifications were sent at all
    if notifications_sent == 0:
        logger.warning(
            "No notifications sent - no Discord webhooks configured ticker={ticker}",
            ticker=ticker,
        )
