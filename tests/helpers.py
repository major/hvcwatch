"""Shared test constants and plain helpers that tests import by name.

Fixtures live in tests/conftest.py. This module holds only values and helper
functions that a test calls directly.
"""

import json
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import responses

WEBHOOK_URL = (
    "https://discord.com/api/webhooks/test"  # 🔗 Matches the shared `settings`
)
SECOND_URL = "https://discord.com/api/webhooks/second"  # 🔗 A second, extra webhook
NYC = ZoneInfo("America/New_York")  # 🗽 The market clock that stamps the bars


class ScriptExhausted(Exception):
    """
    🛑 Raised by the fake IMAP mailbox when the test's script has run out.

    A monitor loop never ends on its own, so the fake raises this instead of
    returning empty results forever. Tests catch it with `pytest.raises`.
    """


def daily_bar(day: date, close: float, volume: float) -> dict[str, Any]:
    """📊 One Massive daily bar for `day`, stamped at midnight New York time."""
    session_start = datetime.combine(day, time.min, tzinfo=NYC)
    return {"c": close, "v": volume, "t": int(session_start.timestamp() * 1000)}


def posts_to(http_mock: responses.RequestsMock, url: str) -> list[dict[str, Any]]:
    """📬 JSON bodies of every POST sent to `url`, in order."""
    bodies: list[dict[str, Any]] = []
    for call in http_mock.calls:
        request = call.request
        if request.method != "POST" or (request.url or "").split("?")[0] != url:
            continue
        assert isinstance(request.body, bytes)  # 📦 requests encodes json= as bytes
        bodies.append(json.loads(request.body))
    return bodies


def only_embed(payload: dict[str, Any]) -> dict[str, Any]:
    """🪟 The single embed in a webhook payload."""
    assert len(payload["embeds"]) == 1
    return payload["embeds"][0]
