"""Presentation may shed observations, never reliable messages or latest state."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pal.channel.contracts import ChannelDeliveryError, ChannelMessage, EndpointConfig, ResponseHandle
from server.runtime import DesktopAvatarEndpoint


def make_endpoint():
    endpoint = DesktopAvatarEndpoint(endpoint=EndpointConfig("desktop", "desktop_avatar", "unused.sock"), socket_path=Path("unused.sock"))
    session = SimpleNamespace(session_id="session", ready_notified=True, closed=False, outbound=asyncio.Queue(maxsize=1))
    endpoint.sessions[session.session_id] = session
    return endpoint, session


def test_full_snapshot_coalesces_and_recovers_without_another_state_change():
    endpoint, session = make_endpoint()
    session.outbound.put_nowait({"type": "text_delta", "text": "keep"})
    endpoint.on_runtime_state({"sleeping": True})
    endpoint.on_runtime_state({"sleeping": False, "failures": [{"failure_id": "latest"}]})
    endpoint.on_runtime_state({"sleeping": False, "failures": [{"failure_id": "latest"}]})
    assert session.outbound.qsize() == 1
    assert session.outbound.get_nowait()["text"] == "keep"
    session.outbound.task_done()
    endpoint._on_session_writable(session)
    assert session.outbound.get_nowait() == {"type": "runtime_state", "payload": {"sleeping": False, "failures": [{"failure_id": "latest"}], "safe_modes": []}}
    session.outbound.task_done()
    endpoint._on_session_writable(session)
    assert session.outbound.empty()


def test_ready_snapshot_survives_full_replay_queue():
    endpoint, session = make_endpoint()
    session.ready_notified = False
    endpoint._unacknowledged_frames.append({"type": "text_delta", "text": "replay"})
    endpoint._mark_session_ready(session)
    assert session.ready_notified
    assert session.outbound.get_nowait()["text"] == "replay"
    session.outbound.task_done()
    endpoint._on_session_writable(session)
    assert session.outbound.get_nowait()["type"] == "runtime_state"


def test_blocked_session_does_not_prevent_other_session_snapshot():
    endpoint, blocked = make_endpoint()
    blocked.outbound.put_nowait({"type": "text_delta"})
    healthy = SimpleNamespace(session_id="healthy", ready_notified=True, closed=False, outbound=asyncio.Queue(maxsize=1))
    endpoint.sessions[healthy.session_id] = healthy
    endpoint.on_runtime_state({"sleeping": True})
    assert healthy.outbound.get_nowait()["payload"]["sleeping"] is True
    assert blocked.outbound.get_nowait()["type"] == "text_delta"


def test_core_event_respects_actual_capacity_below_soft_limit():
    endpoint, session = make_endpoint()
    session.outbound.put_nowait({"type": "text_delta", "text": "keep"})
    endpoint.on_core_event("turn.start", {})
    assert session.outbound.get_nowait()["text"] == "keep"


def test_tagged_message_uses_classified_backpressure_and_retries():
    endpoint, session = make_endpoint()
    handle = ResponseHandle(endpoint_id="desktop", reply_target={"session_id": "session", "request_id": "request"})
    message = ChannelMessage(text="checklist", tag="checklist", payload={"done": 1})
    session.outbound.put_nowait({"type": "occupied"})
    with pytest.raises(ChannelDeliveryError) as failure:
        endpoint.send_channel_message(handle, message)
    assert failure.value.reason == "transport_backpressure"
    assert not failure.value.permanent
    endpoint.queue_reply(message, response_handle=handle)
    endpoint.flush_outbox()
    assert len(endpoint.outbox) == 1
    session.outbound.get_nowait()
    session.outbound.task_done()
    endpoint.flush_outbox()
    assert not endpoint.outbox
    assert session.outbound.get_nowait()["tag"] == "checklist"


def test_writer_progress_flushes_pending_snapshot_without_polling():
    async def run():
        endpoint, session = make_endpoint()
        session.delivery_ack_enabled = False
        session.delivery_ack_waiters = {}
        session.inflight_payload = None
        session.outbound_recovered = False
        writes = []
        session.writer = SimpleNamespace(write=writes.append, drain=AsyncMock())
        session.outbound.put_nowait({"type": "text_delta", "text": "keep"})
        endpoint.on_runtime_state({"sleeping": True})
        task = asyncio.create_task(endpoint._writer_loop(session))
        try:
            await asyncio.wait_for(session.outbound.join(), 1)
            assert len(writes) == 2
            assert b"runtime_state" in writes[-1]
        finally:
            task.cancel()
            await task
    asyncio.run(run())
