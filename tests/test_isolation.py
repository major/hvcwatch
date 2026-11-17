"""Tests for the autouse isolation guards defined in conftest.py."""

import importlib
from pathlib import Path

import httpx2
import pytest
import requests

from hvcwatch import utils

SETTINGS_MODULES = ["main", "email_monitor", "db", "notification", "utils"]
TICKER_URL = utils.MASSIVE_TICKER_URL.format(ticker="AAPL")


@pytest.mark.parametrize("module_name", SETTINGS_MODULES)
def test_settings_fixture_is_bound_in_every_module(settings, module_name):
    """⚙️ Each module that imports settings by name sees the fixture value."""
    module = importlib.import_module(f"hvcwatch.{module_name}")

    assert module.settings is settings


@pytest.mark.parametrize("module_name", SETTINGS_MODULES)
def test_override_settings_rebinds_every_module(override_settings, module_name):
    """🔁 override_settings changes the value seen by all five modules."""
    # Act
    changed = override_settings(imap_port=1143)

    # Assert
    module = importlib.import_module(f"hvcwatch.{module_name}")
    assert module.settings is changed
    assert module.settings.imap_port == 1143


def test_override_settings_keeps_the_other_fields(settings, override_settings):
    """🔁 Fields that are not overridden keep their baseline values."""
    changed = override_settings(imap_port=1143)

    assert changed.fastmail_user == settings.fastmail_user


def test_db_path_is_inside_tmp_path(settings, tmp_path):
    """🗄️ The default test database lives in tmp_path, never in the real home."""
    assert settings.hvcwatch_db_path is not None
    assert Path(settings.hvcwatch_db_path).is_relative_to(tmp_path)


def test_home_is_inside_tmp_path(tmp_path):
    """🏠 HOME points into tmp_path, so Path.home() cannot reach the real home."""
    assert Path.home().is_relative_to(tmp_path)


def test_unregistered_requests_call_raises():
    """🚫 A requests call with no registered response never reaches the network."""
    with pytest.raises(requests.ConnectionError, match="Connection refused"):
        requests.get("https://example.invalid/unregistered", timeout=1)


# 🧪 This test expects the call to fail, so it may stay unexpected.
@pytest.mark.httpx2_mock(assert_all_requests_were_expected=False)
def test_unregistered_httpx2_call_raises():
    """🚫 An httpx2 call with no registered reply never reaches the network."""
    with pytest.raises(httpx2.TimeoutException, match="No response can be found"):
        httpx2.get("https://example.invalid/unregistered", timeout=1)


def test_responses_works_with_pinned_requests(http_mock):
    """🔌 Smoke test: responses can serve a registered URL through requests."""
    # Arrange
    http_mock.get("https://example.invalid/ok", json={"ok": True})

    # Act
    response = requests.get("https://example.invalid/ok", timeout=1)

    # Assert
    assert response.json() == {"ok": True}


def test_httpx2_mock_works_with_pinned_httpx2(httpx2_mock):
    """🔌 Smoke test: httpx2_mock can serve a registered URL through httpx2."""
    # Arrange
    httpx2_mock.add_response(url="https://example.invalid/ok", json={"ok": True})

    # Act
    response = httpx2.get("https://example.invalid/ok", timeout=1)

    # Assert
    assert response.json() == {"ok": True}


@pytest.mark.parametrize("run", [1, 2])
def test_ticker_overview_cache_is_cleared_between_tests(
    httpx2_mock, override_settings, run
):
    """🧹 Each test starts with an empty lookup cache, so each makes one HTTP call."""
    # Arrange
    override_settings(massive_api_key="test-key")
    httpx2_mock.add_response(url=TICKER_URL, json={"results": {"name": "Apple Inc."}})

    # Act
    name = utils.get_company_name("AAPL")

    # Assert
    assert name == "Apple Inc."
    assert len(httpx2_mock.get_requests()) == 1
