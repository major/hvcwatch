from unittest.mock import patch

import hvcwatch.main


@patch("hvcwatch.main.sentry_sdk")
@patch("hvcwatch.main.logger")
@patch("hvcwatch.main.connect_imap")
@patch("hvcwatch.main.settings")
def test_main_calls_connect_imap_and_logs(
    mock_settings, mock_connect_imap, mock_logger, mock_sentry
):
    # Setup mock settings
    mock_settings.imap_host = "imap.example.com"
    mock_settings.fastmail_user = "user"
    mock_settings.fastmail_pass = "pass"
    mock_settings.imap_folder = "INBOX"
    mock_settings.sentry_dsn = None  # No Sentry in test

    hvcwatch.main.main()

    mock_logger.info.assert_called_once_with(
        "Starting HVC Watch email monitor", version="commit=unknown, branch=unknown"
    )
    mock_connect_imap.assert_called_once_with(
        "imap.example.com",
        "user",
        "pass",
        "INBOX",
    )
    # Sentry should not be initialized when DSN is None
    mock_sentry.init.assert_not_called()


@patch("hvcwatch.main.sentry_sdk")
@patch("hvcwatch.main.logger")
@patch("hvcwatch.main.connect_imap")
@patch("hvcwatch.main.settings")
def test_main_initializes_sentry_when_dsn_provided(
    mock_settings, mock_connect_imap, mock_logger, mock_sentry
):
    # Setup mock settings with Sentry DSN
    mock_settings.imap_host = "imap.example.com"
    mock_settings.fastmail_user = "user"
    mock_settings.fastmail_pass = "pass"
    mock_settings.imap_folder = "INBOX"
    mock_settings.sentry_dsn = "https://example@sentry.io/123"
    mock_settings.sentry_environment = "test"
    mock_settings.sentry_traces_sample_rate = 1.0

    hvcwatch.main.main()

    # Sentry should be initialized
    mock_sentry.init.assert_called_once_with(
        dsn="https://example@sentry.io/123",
        environment="test",
        traces_sample_rate=1.0,
        integrations=[],
        attach_stacktrace=True,
    )
    # Should log Sentry initialization
    assert any(
        call[0][0] == "Sentry initialized" for call in mock_logger.info.call_args_list
    )
