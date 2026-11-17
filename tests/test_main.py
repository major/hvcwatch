from unittest.mock import patch

import hvcwatch.main


@patch("hvcwatch.main.connect_imap")
@patch("hvcwatch.main.settings")
def test_main_calls_connect_imap(mock_settings, mock_connect_imap):
    # Setup mock settings
    mock_settings.imap_host = "imap.example.com"
    mock_settings.fastmail_user = "user"
    mock_settings.fastmail_pass = "pass"
    mock_settings.imap_folder = "INBOX"

    hvcwatch.main.main()

    mock_connect_imap.assert_called_once_with(
        "imap.example.com",
        "user",
        "pass",
        "INBOX",
    )
