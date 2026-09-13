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
        assert session.outbound.get_nowait() == {"type": "runtime_state", "payload": {"sleeping": True}}
    new = SimpleNamespace(session_id="new", ready_notified=False, closed=False, outbound=asyncio.Queue())
    endpoint.sessions[new.session_id] = new
    endpoint._mark_session_ready(new)
    assert new.outbound.get_nowait()["payload"] == {"sleeping": True}
    endpoint.on_runtime_state({"sleeping": False})
    assert new.outbound.get_nowait()["payload"] == {"sleeping": False}


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
