from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from pal.channel.contracts import ChannelMessage, ChannelStreamUpdate, EndpointConfig, ResponseHandle
from pal.shared import ChannelStreamUpdateKind

from server.runtime import DesktopAvatarEndpoint
from server.sidecar import AvatarWebSocketServer


class _Outbound:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def put_nowait(self, item: dict) -> None:
        self.items.append(item)

    def empty(self) -> bool:
        return not self.items


class _WebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, frame: str) -> None:
        self.sent.append(frame)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _message(action: str = "upsert") -> ChannelMessage:
    active = action != "clear"
    return ChannelMessage(
        text="Checklist progress 0/1\n⬜ inspect" if active else "Checklist cleared.",
        tag="checklist",
        payload={
            "action": action,
            "active": active,
            "plan": [{"step": "inspect", "status": "pending"}] if active else [],
            "done": 0,
            "total": 1 if active else 0,
        },
    )


def test_endpoint_projects_checklist_stream_message_to_a_dedicated_frame() -> None:
    endpoint = DesktopAvatarEndpoint(
        endpoint=EndpointConfig("desktop", "desktop_avatar", "desktop.sock"),
        socket_path=Path("desktop.sock"),
    )
    outbound = _Outbound()
    endpoint.sessions["session-1"] = SimpleNamespace(outbound=outbound, closed=False)
    handle = ResponseHandle(
        endpoint_id="desktop",
        reply_target={"session_id": "session-1", "request_id": "request-1"},
    )

    endpoint.send_stream_update(
        handle,
        ChannelStreamUpdate(kind=ChannelStreamUpdateKind.MESSAGE, message=_message()),
    )

    assert outbound.items == [
        {
            "type": "tagged_message",
            "request_id": "request-1",
            "tag": "checklist",
            "text": "Checklist progress 0/1\n⬜ inspect",
            "payload": dict(_message().payload),
        }
    ]


def test_endpoint_routes_active_delivery_through_the_newest_open_sidecar_session() -> None:
    endpoint = DesktopAvatarEndpoint(
        endpoint=EndpointConfig("desktop", "desktop_avatar", "desktop.sock"),
        socket_path=Path("desktop.sock"),
    )
    endpoint.sessions["old"] = SimpleNamespace(session_id="old", closed=False)
    endpoint.sessions["closed"] = SimpleNamespace(session_id="closed", closed=True)
    endpoint.sessions["replacement"] = SimpleNamespace(session_id="replacement", closed=False)

    assert endpoint.derive_default_reply_target() == {
        "session_id": "replacement",
        "request_id": "",
        "control_scope_key": "socket:desktop:replacement",
    }


def test_endpoint_rejects_active_delivery_without_an_open_sidecar_session() -> None:
    endpoint = DesktopAvatarEndpoint(
        endpoint=EndpointConfig("desktop", "desktop_avatar", "desktop.sock"),
        socket_path=Path("desktop.sock"),
    )
    endpoint.sessions["closed"] = SimpleNamespace(session_id="closed", closed=True)

    assert endpoint.derive_default_reply_target() == {}


def test_endpoint_replacement_is_not_ready_before_sidecar_handshake() -> None:
    endpoint = DesktopAvatarEndpoint(
        endpoint=EndpointConfig("desktop", "desktop_avatar", "desktop.sock"),
        socket_path=Path("desktop.sock"),
    )
    endpoint.sessions["starting"] = SimpleNamespace(
        session_id="starting",
        closed=False,
        ready_notified=False,
        inflight_payload=None,
        outbound=_Outbound(),
        delivery_ack_waiters={},
    )

    assert not endpoint.replacement_delivery_ready()

    endpoint.sessions["starting"].ready_notified = True
    assert endpoint.replacement_delivery_ready()


def test_sidecar_retains_active_checklist_and_broadcasts_clear() -> None:
    async def scenario() -> None:
        server = object.__new__(AvatarWebSocketServer)
        client = _WebSocket()
        server._clients = {client}
        server._tagged_messages = {}
        server._history = SimpleNamespace(store_tagged_message=lambda _tag, _frame: None)

        await server.broadcast_tagged_message(
            tag="checklist",
            text=_message().text,
            payload=dict(_message().payload),
        )
        assert "checklist" in server._tagged_messages
        assert json.loads(client.sent[-1])["type"] == "tagged_message"

        await server.broadcast_tagged_message(
            tag="checklist",
            text=_message("clear").text,
            payload=dict(_message("clear").payload),
        )
        assert "checklist" not in server._tagged_messages
        assert json.loads(client.sent[-1])["payload"]["action"] == "clear"

    asyncio.run(scenario())
