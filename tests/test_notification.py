import pytest
from unittest.mock import Mock, patch, MagicMock

from hvcwatch.notification import DiscordNotifier


@pytest.fixture
def mock_settings():
    """Mock settings with Discord webhook URL and transparent PNG."""
    with patch("hvcwatch.notification.settings") as mock_settings:
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.transparent_png = "https://example.com/transparent.png"
        yield mock_settings


@pytest.fixture
def mock_ticker_details():
    """Mock ticker details."""
    return {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "logo_url": "https://static.stocktitan.net/company-logo/aapl.webp",
        "description": "Technology company",
        "type": "CS",
    }


@pytest.fixture
def mock_ticker_stats():
    """Mock ticker stats."""
    return {
        "close": 150.25,
        "volume": 2500000,
        "volume_sma": 2000000.0,
        "volume_ratio": 1.25,
    }


@pytest.fixture
def mock_get_ticker_functions(mock_ticker_details, mock_ticker_stats):
    """Mock both get_ticker_details and get_ticker_stats functions."""
    with (
        patch("hvcwatch.notification.get_ticker_details") as mock_details,
        patch("hvcwatch.notification.get_ticker_stats") as mock_stats,
    ):
        mock_details.return_value = mock_ticker_details
        mock_stats.return_value = mock_ticker_stats
        yield mock_details, mock_stats


@pytest.fixture
def discord_notifier(mock_get_ticker_functions):
    """Create a DiscordNotifier instance with mocked dependencies."""
    return DiscordNotifier("AAPL")


@pytest.fixture
def mock_discord_webhook():
    """Mock DiscordWebhook and DiscordEmbed."""
    with (
        patch("hvcwatch.notification.DiscordWebhook") as mock_webhook_class,
        patch("hvcwatch.notification.DiscordEmbed") as mock_embed_class,
    ):
        mock_webhook = Mock()
        mock_embed = Mock()
        mock_webhook_class.return_value = mock_webhook
        mock_embed_class.return_value = mock_embed

        # Mock the webhook response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_webhook.execute.return_value = mock_response

        yield mock_webhook_class, mock_embed_class, mock_webhook, mock_embed


class TestDiscordNotifierInit:
    """Test DiscordNotifier initialization."""

    @pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "TSLA", "GOOGL"])
    def test_init_with_different_tickers(self, ticker, mock_get_ticker_functions):
        """Test initialization with different ticker symbols."""
        mock_details, mock_stats = mock_get_ticker_functions

        notifier = DiscordNotifier(ticker)

        assert notifier.ticker == ticker
        mock_details.assert_called_once_with(ticker)
        mock_stats.assert_called_once_with(ticker)
        assert notifier.ticker_details == mock_details.return_value
        assert notifier.ticker_stats == mock_stats.return_value


class TestDiscordNotifierGetMethods:
    """Test DiscordNotifier getter methods."""

    def test_get_ticker_details(self, discord_notifier, mock_get_ticker_functions):
        """Test get_ticker_details method."""
        mock_details, _ = mock_get_ticker_functions

        result = discord_notifier.get_ticker_details()

        assert result == mock_details.return_value
        mock_details.assert_called_with("AAPL")

    def test_get_ticker_volume(self, discord_notifier, mock_get_ticker_functions):
        """Test get_ticker_volume method."""
        _, mock_stats = mock_get_ticker_functions

        result = discord_notifier.get_ticker_volume()

        assert result == mock_stats.return_value
        mock_stats.assert_called_with("AAPL")


class TestDiscordNotifierBuildDescription:
    """Test DiscordNotifier build_description method."""

    @pytest.mark.parametrize(
        "ticker_stats,expected_parts",
        [
            (
                {"close": 150.25, "volume": 2500000, "volume_sma": 2000000.0},
                ["Current price: $150.25", "Volume vs avg: 2M / 2M **1.25x**"],
            ),
            (
                {"close": 99.99, "volume": 1000000, "volume_sma": 800000.0},
                ["Current price: $99.99", "Volume vs avg: 1M / 800K **1.25x**"],
            ),
            (
                {"close": 1000.00, "volume": 500000, "volume_sma": 1000000.0},
                ["Current price: $1000.00", "Volume vs avg: 500K / 1M **0.50x**"],
            ),
        ],
    )
    def test_build_description_various_values(
        self, ticker_stats, expected_parts, mock_get_ticker_functions
    ):
        """Test build_description with various ticker stats values."""
        mock_details, mock_stats = mock_get_ticker_functions

        # Update the mock to return the test ticker_stats
        ticker_stats["volume_ratio"] = (
            ticker_stats["volume"] / ticker_stats["volume_sma"]
        )
        mock_stats.return_value = ticker_stats

        notifier = DiscordNotifier("TEST")
        result = notifier.build_description()

        # Check that both expected parts are in the result
        for part in expected_parts:
            assert part in result

        # Check that the result is properly formatted with newlines
        lines = result.split("\n")
        assert len(lines) == 2


class TestDiscordNotifierNotifyDiscord:
    """Test DiscordNotifier notify_discord method."""

    @patch("hvcwatch.notification.logger")
    def test_notify_discord_success(
        self, mock_logger, discord_notifier, mock_settings, mock_discord_webhook
    ):
        """Test successful Discord notification."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        discord_notifier.notify_discord()

        # Verify webhook creation
        mock_webhook_class.assert_called_once_with(
            url=mock_settings.discord_webhook_url, rate_limit_retry=True
        )

        # Verify embed creation and configuration
        mock_embed_class.assert_called_once_with(
            title="Apple Inc. (AAPL)",
            description=discord_notifier.build_description(),
            color="03b2f8",
        )

        # Verify embed methods were called
        mock_embed.set_thumbnail.assert_called_once_with(
            url="https://static.stocktitan.net/company-logo/aapl.webp"
        )
        mock_embed.set_footer.assert_called_once_with(text="HVC Watch · Major's Bots")
        mock_embed.set_image.assert_called_once_with(url=mock_settings.transparent_png)
        mock_embed.set_timestamp.assert_called_once()

        # Verify webhook operations
        mock_webhook.add_embed.assert_called_once_with(mock_embed)
        mock_webhook.execute.assert_called_once()

        # Verify logging
        mock_logger.info.assert_any_call("Sending to Discord", ticker="AAPL")
        mock_logger.info.assert_any_call("Discord response: 200")

    @patch("hvcwatch.notification.logger")
    @pytest.mark.parametrize("status_code", [200, 201, 204, 400, 500])
    def test_notify_discord_various_response_codes(
        self, mock_logger, discord_notifier, mock_settings, status_code
    ):
        """Test Discord notification with various HTTP response codes."""
        with (
            patch("hvcwatch.notification.DiscordWebhook") as mock_webhook_class,
            patch("hvcwatch.notification.DiscordEmbed"),
        ):
            mock_webhook = Mock()
            mock_webhook_class.return_value = mock_webhook

            # Mock response with different status codes
            mock_response = Mock()
            mock_response.status_code = status_code
            mock_webhook.execute.return_value = mock_response

            discord_notifier.notify_discord()

            mock_logger.info.assert_any_call(f"Discord response: {status_code}")

    @patch("hvcwatch.notification.logger")
    def test_notify_discord_with_different_ticker_data(
        self, mock_logger, mock_settings, mock_discord_webhook
    ):
        """Test Discord notification with different ticker data."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        # Test data with different company
        test_ticker_details = {
            "ticker": "TSLA",
            "name": "Tesla, Inc.",
            "logo_url": "https://static.stocktitan.net/company-logo/tsla.webp",
            "description": "Electric vehicle company",
            "type": "CS",
        }

        test_ticker_stats = {
            "close": 250.75,
            "volume": 5000000,
            "volume_sma": 3000000.0,
            "volume_ratio": 1.67,
        }

        with (
            patch("hvcwatch.notification.get_ticker_details") as mock_details,
            patch("hvcwatch.notification.get_ticker_stats") as mock_stats,
        ):
            mock_details.return_value = test_ticker_details
            mock_stats.return_value = test_ticker_stats

            notifier = DiscordNotifier("TSLA")
            notifier.notify_discord()

            # Verify embed was created with correct title
            mock_embed_class.assert_called_once()
            call_args = mock_embed_class.call_args[1]
            assert call_args["title"] == "Tesla, Inc. (TSLA)"

            # Verify thumbnail was set with correct URL
            mock_embed.set_thumbnail.assert_called_once_with(
                url="https://static.stocktitan.net/company-logo/tsla.webp"
            )

            # Verify logging with correct ticker
            mock_logger.info.assert_any_call("Sending to Discord", ticker="TSLA")


class TestDiscordNotifierIntegration:
    """Integration tests for DiscordNotifier."""

    @patch("hvcwatch.notification.logger")
    def test_full_notification_flow(self, mock_logger, mock_settings):
        """Test the complete notification flow from init to Discord send."""
        # Mock all external dependencies
        mock_ticker_details = {
            "ticker": "INTC",
            "name": "Intel Corporation",
            "logo_url": "https://static.stocktitan.net/company-logo/intc.webp",
            "description": "Semiconductor company",
            "type": "CS",
        }

        mock_ticker_stats = {
            "close": 45.67,
            "volume": 12000000,
            "volume_sma": 8000000.0,
            "volume_ratio": 1.5,
        }

        with (
            patch("hvcwatch.notification.get_ticker_details") as mock_details,
            patch("hvcwatch.notification.get_ticker_stats") as mock_stats,
            patch("hvcwatch.notification.DiscordWebhook") as mock_webhook_class,
            patch("hvcwatch.notification.DiscordEmbed") as mock_embed_class,
        ):
            # Setup mocks
            mock_details.return_value = mock_ticker_details
            mock_stats.return_value = mock_ticker_stats

            mock_webhook = Mock()
            mock_embed = Mock()
            mock_webhook_class.return_value = mock_webhook
            mock_embed_class.return_value = mock_embed

            mock_response = Mock()
            mock_response.status_code = 200
            mock_webhook.execute.return_value = mock_response

            # Create notifier and send notification
            notifier = DiscordNotifier("INTC")
            notifier.notify_discord()

            # Verify the complete flow
            assert notifier.ticker == "INTC"
            assert notifier.ticker_details == mock_ticker_details
            assert notifier.ticker_stats == mock_ticker_stats

            # Verify external function calls
            mock_details.assert_called_once_with("INTC")
            mock_stats.assert_called_once_with("INTC")

            # Verify Discord webhook and embed setup
            mock_webhook_class.assert_called_once()
            mock_embed_class.assert_called_once()
            mock_webhook.add_embed.assert_called_once_with(mock_embed)
            mock_webhook.execute.assert_called_once()

            # Verify logging
            assert mock_logger.info.call_count >= 2
