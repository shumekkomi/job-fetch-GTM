"""Tests for retry behaviour in the shared HTTP helper."""
from unittest.mock import MagicMock, patch

import pytest

from jobfetcher import http
from jobfetcher.models import FetchError


def _resp(status, headers=None):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    return r


def test_429_is_retried_then_succeeds():
    with patch.object(http.requests, "get", side_effect=[_resp(429, {"Retry-After": "5"}), _resp(200)]), \
         patch.object(http.time, "sleep") as sleep:
        assert http.get("https://example.com").status_code == 200
    sleep.assert_called_once_with(5)


def test_429_wait_is_capped():
    with patch.object(http.requests, "get", side_effect=[_resp(429, {"Retry-After": "3600"}), _resp(200)]), \
         patch.object(http.time, "sleep") as sleep:
        http.get("https://example.com")
    sleep.assert_called_once_with(http.MAX_RATE_LIMIT_WAIT)


def test_429_without_header_backs_off():
    with patch.object(http.requests, "get", side_effect=[_resp(429), _resp(200)]), \
         patch.object(http.time, "sleep") as sleep:
        http.get("https://example.com")
    sleep.assert_called_once_with(http.RATE_LIMIT_BACKOFF)


def test_429_every_time_fails_after_attempts():
    with patch.object(http.requests, "get", return_value=_resp(429)), patch.object(http.time, "sleep"):
        with pytest.raises(FetchError, match="429"):
            http.get("https://example.com")


def test_404_is_not_retried():
    with patch.object(http.requests, "get", return_value=_resp(404)) as g, patch.object(http.time, "sleep"):
        with pytest.raises(FetchError):
            http.get("https://example.com")
    assert g.call_count == 1
