from __future__ import annotations

import httpx
import pytest

from src.ingestion.http import FetchError, backoff_delay, fetch_bytes


class Recorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)


def client_for(responses: list[httpx.Response | Exception]) -> tuple[httpx.AsyncClient, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


def test_backoff_grows_and_is_capped() -> None:
    assert [backoff_delay(i, base=1.0, cap=5.0) for i in range(4)] == [1.0, 2.0, 4.0, 5.0]


async def test_success_first_try() -> None:
    client, calls = client_for([httpx.Response(200, content=b"ok")])
    recorder = Recorder()
    async with client:
        assert (
            await fetch_bytes("https://x.invalid/a", client=client, sleep=recorder.sleep) == b"ok"
        )
    assert len(calls) == 1 and recorder.delays == []


async def test_retries_server_error_then_succeeds() -> None:
    client, calls = client_for([httpx.Response(503), httpx.Response(200, content=b"ok")])
    recorder = Recorder()
    async with client:
        body = await fetch_bytes("https://x.invalid/a", client=client, sleep=recorder.sleep)
    assert body == b"ok"
    assert len(calls) == 2 and recorder.delays == [1.0]


async def test_rate_limit_honours_retry_after() -> None:
    client, _ = client_for(
        [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, content=b"ok")]
    )
    recorder = Recorder()
    async with client:
        await fetch_bytes("https://x.invalid/a", client=client, sleep=recorder.sleep)
    assert recorder.delays == [7.0]


async def test_transport_error_is_retried() -> None:
    client, calls = client_for([httpx.ConnectError("down"), httpx.Response(200, content=b"ok")])
    recorder = Recorder()
    async with client:
        assert (
            await fetch_bytes("https://x.invalid/a", client=client, sleep=recorder.sleep) == b"ok"
        )
    assert len(calls) == 2


async def test_gives_up_after_max_retries() -> None:
    client, calls = client_for([httpx.Response(500)])
    recorder = Recorder()
    async with client:
        with pytest.raises(FetchError, match="after 3 attempts"):
            await fetch_bytes(
                "https://x.invalid/a", client=client, max_retries=2, sleep=recorder.sleep
            )
    assert len(calls) == 3 and recorder.delays == [1.0, 2.0]


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_access_denied_is_final(status: int) -> None:
    """An access restriction is never retried or worked around."""
    client, calls = client_for([httpx.Response(status)])
    recorder = Recorder()
    async with client:
        with pytest.raises(FetchError, match="not retryable"):
            await fetch_bytes("https://x.invalid/a", client=client, sleep=recorder.sleep)
    assert len(calls) == 1 and recorder.delays == []
