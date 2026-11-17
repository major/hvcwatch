"""Tests for the `main` entry point, run against a scripted fake IMAP mailbox."""

import pytest

from hvcwatch.main import main
from tests.helpers import ScriptExhausted

# 📜 Every test here configures logging, so the hvcwatch logger is cleaned up after each
pytestmark = pytest.mark.usefixtures("hvcwatch_logger")


@pytest.fixture
def mailbox(override_settings, fake_mailbox):
    """📭 A fake mailbox on a non-default host and folder. Its script ends at the first poll."""
    override_settings(imap_host="imap.example.com", imap_folder="Alerts")
    return fake_mailbox()


def test_main_connects_with_the_configured_host_login_and_folder(settings, mailbox):
    """🔌 main passes the configured host, user, password, and folder to IMAP."""
    # Act
    with pytest.raises(ScriptExhausted):
        main()

    # Assert
    assert mailbox.host == "imap.example.com"
    assert mailbox.login_args == (settings.fastmail_user, settings.fastmail_pass, None)
    assert mailbox.folder.selected == ("Alerts", True)  # 🔒 Opened read-only


def test_main_configures_logging_before_it_logs(mailbox, hvcwatch_logger, capsys):
    """📜 main sets up one stderr handler, then logs its startup line to it."""
    # Act
    with pytest.raises(ScriptExhausted):
        main()

    # Assert
    assert len(hvcwatch_logger.handlers) == 1
    assert "Starting HVC Watch email monitor" in capsys.readouterr().err
