import asyncio
import sys
import time
from types import SimpleNamespace

from server import agent


def test_fetch_does_not_block_websocket_event_loop(monkeypatch, tmp_path):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def iter_bytes(chunk_size):
            assert chunk_size == 1024 * 1024
            yield b'payload'

    def slow_stream(*args, **kwargs):
        time.sleep(0.2)
        return Response()

    monkeypatch.setitem(sys.modules, 'httpx', SimpleNamespace(stream=slow_stream))
    messages = []
    instance = agent.Agent()

    async def fake_send(message):
        messages.append(message)

    monkeypatch.setattr(instance, '_send', fake_send)

    async def scenario():
        started = time.monotonic()
        task = asyncio.create_task(instance._fetch_files(
            'fetch-1', 'marker-1', ['input.glb'], str(tmp_path)
        ))
        await asyncio.sleep(0.03)
        elapsed = time.monotonic() - started
        assert elapsed < 0.12, '同步 HTTP 下载堵塞了 WebSocket 心跳事件循环'
        assert not task.done()
        await task

    asyncio.run(scenario())
    assert (tmp_path / 'input.glb').read_bytes() == b'payload'
    assert messages == [{'type': 'fetch_done', 'fetchId': 'fetch-1', 'ok': True, 'error': None}]


def test_fetch_streams_to_atomic_target(monkeypatch, tmp_path):
    payload = b'x' * (2 * 1024 * 1024 + 7)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def iter_bytes(chunk_size):
            assert chunk_size == 1024 * 1024
            yield payload[:100]
            yield payload[100:]

    monkeypatch.setitem(sys.modules, 'httpx', SimpleNamespace(stream=lambda *a, **k: Response()))
    messages = []
    instance = agent.Agent()

    async def fake_send(message):
        messages.append(message)

    monkeypatch.setattr(instance, '_send', fake_send)
    dest = tmp_path / 'stage'
    asyncio.run(instance._fetch_files(
        'fetch-atomic', 'marker', ['model.glb'], str(dest)
    ))

    assert (dest / 'model.glb').read_bytes() == payload
    assert not list(dest.glob('*.part-*'))
    assert messages == [{'type': 'fetch_done', 'fetchId': 'fetch-atomic',
                         'ok': True, 'error': None}]
