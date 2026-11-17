import logging
import random
import time
from typing import Protocol

import requests
from discord_webhook import DiscordEmbed, DiscordWebhook

from hvcwatch import config
from hvcwatch.types import Timeframe
from hvcwatch.utils import get_company_name, get_ticker_type

logger = logging.getLogger(__name__)

# 🔁 Discord delivery retry policy
MAX_ATTEMPTS = 4
BASE_DELAY_SECONDS = 1.0
BACKOFF_FACTOR = 2
MAX_WAIT_SECONDS = 30.0
JITTER_FRACTION = 0.1
DISCORD_TIMEOUT_SECONDS = 10

# 🎨 Embed color per timeframe, as hex strings for discord_webhook
TIMEFRAME_COLORS = {
    "daily": "03b2f8",  # 🔵
    "weekly": "9b59b6",  # 🟣
    "monthly": "f39c12",  # 🟠
}


class DiscordDeliveryError(Exception):
    """❌ Discord did not accept a webhook message, even after retries."""


def _with_jitter(delay: float) -> float:
    """
    🎲 Add a small random extra wait, so many bots do not retry in lockstep.

    Args:
        delay: The base wait in seconds.

    Returns:
        The wait plus up to 10% random jitter.
    """
    return delay + random.uniform(0, JITTER_FRACTION * delay)


def _backoff_seconds(attempt: int) -> float:
    """
    📈 Exponential backoff after a failed attempt, capped at 30 seconds.

    Args:
        attempt: The attempt that just failed, counting from 1.

    Returns:
        The base wait before the next attempt (1, 2, 4, ... seconds).
    """
    return min(BASE_DELAY_SECONDS * BACKOFF_FACTOR ** (attempt - 1), MAX_WAIT_SECONDS)


def _retry_after_seconds(response: requests.Response) -> float:
    """
    ⏳ Read how long Discord asked us to wait after a 429 reply.

    Checks the JSON body's `retry_after` first, then the `Retry-After` header.
    The result is capped at 30 seconds, and bad values count as 0.

    Args:
        response: The 429 reply from Discord.

    Returns:
        Seconds to wait, from 0 up to 30.
    """
    try:
        raw = response.json().get("retry_after")
    except ValueError, AttributeError:  # 🧩 Body is not a JSON object
        raw = None
    if raw is None:
        raw = response.headers.get("Retry-After", 0)
    try:
        return min(max(float(raw), 0.0), MAX_WAIT_SECONDS)
    except TypeError, ValueError:  # 🧩 Non-numeric value, so do not wait
        return 0.0


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

        Raises:
            DiscordDeliveryError: Discord rejected the message, or every attempt failed.
        """
        logger.info("Sending to Discord ticker=%s timeframe=%s", ticker, timeframe)
        # 🧩 rate_limit_retry=False: the retry loop in _deliver owns 429 handling
        webhook = DiscordWebhook(
            url=self.webhook_url,
            rate_limit_retry=False,
            timeout=DISCORD_TIMEOUT_SECONDS,
        )

        # Look up company name and ticker type (both optional, never block the alert)
        company_name = get_company_name(ticker)
        ticker_type = get_ticker_type(ticker)

        # Add 🔥 emoji for monthly alerts
        emoji = " 🔥" if timeframe == "monthly" else ""
        # 🧩 The title already shows the ticker when there is no name, so bold it only with a name
        description_parts = []
        if company_name:
            description_parts.append(f"**{ticker}**")
        if ticker_type:
            description_parts.append(ticker_type)
        description_parts.append(f"{timeframe.capitalize()}{emoji}")
        description = " · ".join(description_parts)

        embed = DiscordEmbed(
            title=company_name or ticker,
            description=description,
            color=TIMEFRAME_COLORS[timeframe],
        )
        logo_url = f"https://static.stocktitan.net/company-logo/{ticker.lower()}.webp"
        embed.set_thumbnail(url=logo_url)
        embed.set_footer(text="HVC Watch · Major's Bots")
        embed.set_timestamp()
        webhook.add_embed(embed)
        self._deliver(webhook)

    def _deliver(self, webhook: DiscordWebhook) -> None:
        """
        🔁 POST the webhook, retrying 429, 5xx, and network errors with backoff.

        Uses `api_post_request` instead of `execute`, because `execute` runs
        json.loads on every reply and so fails on Discord's empty 204 body.

        Args:
            webhook: The configured webhook with its embed already added.

        Raises:
            DiscordDeliveryError: A reply other than 4xx-except-429 is not
                retried, or the last of MAX_ATTEMPTS attempts still failed.
        """
        for attempt in range(1, MAX_ATTEMPTS + 1):
            retry_after = 0.0
            try:
                response = webhook.api_post_request()
            except (requests.ConnectionError, requests.Timeout) as error:
                reason = f"network error: {error}"
            else:
                if response.status_code in (200, 204):
                    logger.info("Discord response status_code=%s", response.status_code)
                    return
                status = response.status_code
                reason = f"HTTP {status}: {response.text[:200]}"
                if (
                    status != 429 and status < 500
                ):  # 🚫 Other 4xx: retrying will not help
                    raise DiscordDeliveryError(reason)
                if status == 429:
                    retry_after = _retry_after_seconds(response)

            if attempt == MAX_ATTEMPTS:
                raise DiscordDeliveryError(
                    f"gave up after {attempt} attempts: {reason}"
                )
            # ⏳ Wait the longer of the backoff and Discord's retry_after, capped
            delay = max(_backoff_seconds(attempt), retry_after)
            logger.warning(
                "Discord attempt %s/%s failed, retrying reason=%s",
                attempt,
                MAX_ATTEMPTS,
                reason,
            )
            time.sleep(min(_with_jitter(delay), MAX_WAIT_SECONDS))


def notify_all_platforms(ticker: str, timeframe: Timeframe = "daily") -> int:
    """
    🎼 Orchestrate notifications to Discord webhooks.

    Sends ticker alerts to all configured Discord webhook URLs. A failure on
    one URL is logged, and the others still get the alert.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        timeframe: Alert timeframe ("daily", "weekly", or "monthly")

    Returns:
        The number of webhooks that accepted the alert. 0 if none are
        configured or all of them failed.
    """
    logger.info("Sending notifications ticker=%s timeframe=%s", ticker, timeframe)

    # Track how many webhooks accepted the alert
    notifications_sent = 0

    discord_webhook_urls = config.get_settings().get_discord_webhook_urls()
    if not discord_webhook_urls:
        logger.warning("No Discord webhooks configured, nothing sent ticker=%s", ticker)
        return 0

    for webhook_url in discord_webhook_urls:
        try:
            discord_notifier = DiscordNotifier(webhook_url=webhook_url)
            discord_notifier.send(ticker, timeframe)
            logger.info(
                "Notification sent successfully ticker=%s timeframe=%s platform=%s webhook_url=%s",
                ticker,
                timeframe,
                "Discord",
                webhook_url[:50] + "...",  # Truncate for logging
            )
            notifications_sent += 1
        except Exception as e:
            logger.error(
                "Failed to send notification ticker=%s platform=%s webhook_url=%s error=%s",
                ticker,
                "Discord",
                webhook_url[:50] + "...",  # Truncate for logging
                str(e),
            )

    # Warn when every configured webhook failed
    if notifications_sent == 0:
        logger.warning(
            "No Discord notification delivered - all %s webhook(s) failed ticker=%s",
            len(discord_webhook_urls),
            ticker,
        )
    return notifications_sent
