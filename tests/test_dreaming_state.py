import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pal.channel.contracts import EndpointConfig
from server.runtime import DesktopAvatarEndpoint
from server.sidecar import AvatarStateQueue, AvatarWebSocketServer, StateMachine


def test_dreaming_sleep_survives_messages_emotions_and_idle_timeout():
    sm = StateMachine(AvatarStateQueue(), idle_timeout=1)
    sm.on_external_state("happy")
    sm.on_runtime_state({"sleeping": True})
    assert sm.current_state == "sleeping"
    sm.on_client_message()
    sm.on_reply_delta()
    sm.on_reply_done()
    assert not sm.on_external_state("thinking")
    assert not sm.on_external_state("happy")
    with patch("server.sidecar.time.monotonic", return_value=10**12):
        assert sm.tick() is None
    assert sm.current_state == "sleeping"
    sm.on_runtime_state({"sleeping": "false"})
    assert sm.current_state == "sleeping"
    sm.on_runtime_state({"sleeping": False})
    assert sm.current_state == "standby"
    sm.on_client_message()
    assert sm.current_state == "thinking"


def test_idle_sleep_still_wakes_on_message():
    sm = StateMachine(AvatarStateQueue(), idle_timeout=1)
    sm.on_external_state("sleeping")
    sm.on_client_message()
    assert sm.current_state == "shock"


def test_endpoint_broadcasts_and_replays_latest_state_on_reconnect():
    endpoint = DesktopAvatarEndpoint(
        endpoint=EndpointConfig("desktop", "desktop_avatar", "desktop.sock"),
        socket_path=Path("desktop.sock"),
    )
    sessions = [SimpleNamespace(session_id=str(i), ready_notified=True, closed=False,
                               outbound=asyncio.Queue()) for i in range(2)]
    endpoint.sessions.update({s.session_id: s for s in sessions})
    endpoint.on_runtime_state({"sleeping": True})
    for session in sessions:
        assert session.outbound.get_nowait() == {"type": "runtime_state", "payload": {"sleeping": True, "failures": [], "safe_modes": []}}
    new = SimpleNamespace(session_id="new", ready_notified=False, closed=False, outbound=asyncio.Queue())
    endpoint.sessions[new.session_id] = new
    endpoint._mark_session_ready(new)
    assert new.outbound.get_nowait()["payload"] == {"sleeping": True, "failures": [], "safe_modes": []}
    endpoint.on_runtime_state({"sleeping": False})
    assert new.outbound.get_nowait()["payload"] == {"sleeping": False, "failures": [], "safe_modes": []}


def test_sleep_frame_projects_without_chat_or_history():
    async def run():
        server = object.__new__(AvatarWebSocketServer)
        server._sm = StateMachine(AvatarStateQueue(), idle_timeout=1)
        server.broadcast_frame = AsyncMock()
        frame = {"type": "runtime_state", "payload": {"sleeping": True}}
        assert server._is_transient_reply(frame)
        await server._project_pal_reply(frame)
        assert server._sm.current_state == "sleeping"
        await server._project_pal_reply({"type": "runtime_state", "payload": {"sleeping": False}})
        assert server._sm.current_state == "standby"
    asyncio.run(run())


def test_core_notifications_broadcast_without_route_and_failure_snapshot_replays():
    async def run():
        endpoint = DesktopAvatarEndpoint(
            endpoint=EndpointConfig("desktop", "desktop_avatar", "desktop.sock"),
            socket_path=Path("desktop.sock"),
        )
        session = SimpleNamespace(session_id="one", ready_notified=True, closed=False, outbound=asyncio.Queue())
        endpoint.sessions["one"] = session
        event = {"subsystem": "channel", "component": "endpoint-one", "failure_id": "one"}
        endpoint.on_core_event("failure.started", event)
        frame = session.outbound.get_nowait()
        server = object.__new__(AvatarWebSocketServer)
        server._sm = StateMachine(AvatarStateQueue(), idle_timeout=1)
        server.broadcast_frame = AsyncMock()
        assert server._is_transient_reply(frame)
        await server._project_pal_reply(frame)
        server.broadcast_frame.assert_awaited_with(frame)
        snapshot = {"sleeping": False, "failures": [event], "safe_modes": []}
        endpoint.on_runtime_state(snapshot)
        await server._project_pal_reply(session.outbound.get_nowait())
        assert server._sm.runtime_state == snapshot
        replacement = SimpleNamespace(session_id="two", ready_notified=False, closed=False, outbound=asyncio.Queue())
        endpoint.sessions["two"] = replacement
        endpoint._mark_session_ready(replacement)
        assert replacement.outbound.get_nowait() == {"type": "runtime_state", "payload": snapshot}
    asyncio.run(run())


def test_system_frames_skip_ack_and_replay_while_chat_remains_reliable():
    async def run():
        endpoint = DesktopAvatarEndpoint(
            endpoint=EndpointConfig("desktop", "desktop_avatar", "desktop.sock"),
            socket_path=Path("desktop.sock"),
        )
        writes = []
        session = SimpleNamespace(
            session_id="writer", outbound=asyncio.Queue(), delivery_ack_enabled=True, delivery_ack_waiters={},
            closed=False, inflight_payload=None, outbound_recovered=False,
            writer=SimpleNamespace(write=writes.append, drain=AsyncMock()),
        )
        session.outbound.put_nowait({"type": "core_event", "topic": "turn.tool_call_failed", "payload": {}})
        session.outbound.put_nowait({"type": "text_delta", "text": "keep this"})
        writer = asyncio.create_task(endpoint._writer_loop(session))
        for _ in range(100):
            if session.delivery_ack_waiters:
                break
            await asyncio.sleep(0)
        assert len(writes) == 2
        assert b"_pal_delivery_id" not in writes[0]
        assert b"_pal_delivery_id" in writes[1]
        assert len(session.delivery_ack_waiters) == 1
        writer.cancel()
        await writer
        session.outbound.put_nowait({"type": "runtime_state", "payload": {"sleeping": True}})
        session.outbound.put_nowait({"type": "core_event", "topic": "failure.started", "payload": {}})
        endpoint._recover_session_outbound(session)
        assert [frame["type"] for frame in endpoint._unacknowledged_frames] == ["text_delta"]
        assert endpoint.accept_transport_backlog(({"type": "core_event"},)) == 1
        assert len(endpoint._unacknowledged_frames) == 1
    asyncio.run(run())
