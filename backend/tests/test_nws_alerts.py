"""NWS timestamps reach the SQL boundary as aware datetimes, without a live DB."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.ingest import nws_alerts


@pytest.mark.parametrize("value, expected", [
    ("2026-10-10T18:58:00-05:00",
     datetime(2026, 10, 10, 18, 58, tzinfo=timezone(timedelta(hours=-5)))),
    ("2026-10-10T23:58:00Z", datetime(2026, 10, 10, 23, 58, tzinfo=timezone.utc)),
    ("2026-10-10T23:58:00.123456+00:00",
     datetime(2026, 10, 10, 23, 58, microsecond=123456, tzinfo=timezone.utc)),
])
def test_parse_offset_and_utc_timestamps(value, expected):
    parsed = nws_alerts._parse_timestamp(value)
    assert parsed == expected
    assert parsed.utcoffset() is not None


@pytest.mark.parametrize("value", [None, "", "  ", "invalid", "2026-99-10T00:00:00Z",
                                    "2026-10-10", "2026-10-10T18:58:00", 123, {}])
def test_missing_invalid_or_timezone_missing_timestamps(value):
    assert nws_alerts._parse_timestamp(value) is None


@pytest.mark.asyncio
async def test_ingest_passes_aware_datetimes_and_nulls_to_asyncpg(monkeypatch):
    polygon = {"type": "Polygon", "coordinates": [[[-95, 29], [-95, 30],
                                                       [-94, 30], [-95, 29]]]}
    timestamp_pairs = [
        {"effective": "2026-10-10T18:58:00-05:00", "expires": "2026-10-11T00:00:00Z"},
        {"effective": "bad", "expires": "bad", "ends": "2026-10-11T01:00:00+00:00"},
        {},
        {"effective": None, "expires": None, "ends": "also bad"},
    ]
    features = [{"geometry": polygon, "properties": {
        "id": f"alert-{i}", "event": "Flood Warning", **timestamps,
    }} for i, timestamps in enumerate(timestamp_pairs)]
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"features": features}))
    monkeypatch.setattr(nws_alerts.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=transport, **kwargs))
    monkeypatch.setattr(nws_alerts, "get_settings", lambda: SimpleNamespace(state_list=["TX"]))
    conn = SimpleNamespace(execute=AsyncMock(return_value="INSERT 0 1"))

    assert await nws_alerts.ingest(conn) == 4
    calls = conn.execute.call_args_list
    for call in calls:
        assert call.args[0] == nws_alerts._UPSERT
        for timestamp in call.args[6:8]:  # SQL parameters $6 and $7
            assert timestamp is None or (
                isinstance(timestamp, datetime) and timestamp.utcoffset() is not None
            )
    assert calls[0].args[6].utcoffset() == timedelta(hours=-5)
    assert calls[0].args[7] == datetime(2026, 10, 11, tzinfo=timezone.utc)
    assert calls[1].args[6] is None
    assert calls[1].args[7] == datetime(2026, 10, 11, 1, tzinfo=timezone.utc)
    assert calls[2].args[6:8] == (None, None)
    assert calls[3].args[6:8] == (None, None)
