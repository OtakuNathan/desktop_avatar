from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import server.sidecar as sidecar_module
from server.sidecar import (
    AvatarStateQueue,
    AvatarWebSocketServer,
    ChatHistoryStore,
    SidecarConfig,
    StateMachine,
    serve,
)


class _Channel:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.attempts: list[tuple[str, str]] = []

    async def send_user_message(self, text: str, request_id: str) -> None:
        self.attempts.append((text, request_id))
        self.sent.append((text, request_id))


class _FailingChannel(_Channel):
    async def send_user_message(self, text: str, request_id: str) -> None:
        self.attempts.append((text, request_id))
        raise ConnectionError("offline")


class _FlakyChannel(_Channel):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    async def send_user_message(self, text: str, request_id: str) -> None:
        self.attempts.append((text, request_id))
        if len(self.attempts) <= self.failures:
            raise ConnectionError("temporarily offline")
        self.sent.append((text, request_id))


class _ReplyChannel(_Channel):
    def __init__(self, replies: list[dict[str, object]]) -> None:
        super().__init__()
        self.replies = deque(replies)
        self.acknowledged: list[str] = []
        self._empty = asyncio.Event()

    async def read_reply(self) -> dict[str, object]:
        if self.replies:
            return self.replies.popleft()
        await self._empty.wait()
        raise AssertionError("unreachable")

    async def acknowledge_reply(self, reply: dict[str, object]) -> None:
        self.acknowledged.append(str(reply.get("_pal_delivery_id") or ""))


class _StateMachine:
    current_state = "standby"

    def on_client_message(self) -> None:
        pass

    def on_reply_delta(self) -> None:
        pass

    def on_reply_done(self) -> None:
        pass


class _WebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, frame: str) -> None:
        self.sent.append(frame)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _IncomingWebSocket(_WebSocket):
    def __init__(self, incoming: list[dict[str, object]]) -> None:
        super().__init__()
        self.incoming = deque(incoming)

    async def __anext__(self):
        if not self.incoming:
            raise StopAsyncIteration
        return json.dumps(self.incoming.popleft())


class _SlowWebSocket(_WebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def send(self, frame: str) -> None:
        _ = frame
        await asyncio.Event().wait()

    async def close(self, **_kwargs: object) -> None:
        self.closed = True


def _server(history: ChatHistoryStore, channel: _Channel | None = None) -> AvatarWebSocketServer:
    return AvatarWebSocketServer(
        state_machine=_StateMachine(),
        state_queue=SimpleNamespace(),
        channel=channel or _Channel(),
        history=history,
        loop=asyncio.get_running_loop(),
        ingress_retry_delays=(0.0, 0.0),
    )


def test_slow_browser_is_retired_without_blocking_reply_pump(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        history = ChatHistoryStore(tmp_path / "history.sqlite3")
        server = _server(history)
        client = _SlowWebSocket()
        server._clients.add(client)
        monkeypatch.setattr(sidecar_module, "BROWSER_SEND_TIMEOUT_SECONDS", 0.01)

        await server.broadcast_frame({"type": "chat_message", "text": "hello"})
        await asyncio.sleep(0)

        assert client not in server._clients
        assert client.closed is True
        history.close()

    asyncio.run(scenario())


def test_native_action_completion_resumes_the_latest_base_state() -> None:
    queue = AvatarStateQueue()
    state_machine = StateMachine(queue, idle_timeout=3600.0)

    assert state_machine.on_external_state("happy", duration=1.1)
    assert queue.pop()["state"] == "happy"
    state_machine.on_reply_delta()

    assert state_machine.current_state == "happy"
    assert not state_machine.on_external_action_finished("sad")
    assert state_machine.current_state == "happy"
    assert state_machine.on_external_action_finished("happy")
    assert state_machine.current_state == "working"
    assert queue.pop()["state"] == "working"


def test_native_action_has_a_disconnect_failsafe(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(sidecar_module.time, "monotonic", lambda: now[0])
    queue = AvatarStateQueue()
    state_machine = StateMachine(queue, idle_timeout=3600.0)

    assert state_machine.on_external_state("happy", duration=1.1)
    queue.pop()
    now[0] += 31.0

    assert state_machine.tick() == "standby"
    assert state_machine.current_state == "standby"
    assert queue.pop()["state"] == "standby"


def test_sidecar_shutdown_is_event_driven_and_listener_health_is_real(
    tmp_path: Path,
    monkeypatch,
) -> None:
    events: list[str] = []
    health_samples: list[bool] = []
    listeners = []

    class FakeChannel:
        def __init__(self, _socket_path: Path) -> None:
            self.blocked = asyncio.Event()

        async def connect(self) -> None:
            events.append("channel_connected")

        async def close(self) -> None:
            events.append("channel_closed")

        async def read_reply(self):
            await self.blocked.wait()
            raise AssertionError("unreachable")

    class FakeListener:
        def __init__(self) -> None:
            self.serving = False

        async def __aenter__(self):
            self.serving = True
            events.append("listener_entered")
            return self

        async def __aexit__(self, *_exc_info) -> None:
            self.serving = False
            events.append("listener_closed")

        def is_serving(self) -> bool:
            return self.serving

    def fake_websocket_serve(*_args, **kwargs):
        assert kwargs["close_timeout"] == 1.0
        listener = FakeListener()
        listeners.append(listener)
        return listener

    class FakeManager:
        def __init__(self, *, health_fn, shutdown_fn, **_kwargs) -> None:
            self.health_fn = health_fn
            self.shutdown_fn = shutdown_fn

        async def serve(self) -> None:
            listener = listeners[0]
            health_samples.append(bool(self.health_fn()["listener_bound"]))
            listener.serving = False
            health_samples.append(bool(self.health_fn()["listener_bound"]))
            listener.serving = True
            self.shutdown_fn()

    monkeypatch.setattr(sidecar_module, "PalChannelClient", FakeChannel)
    monkeypatch.setattr(sidecar_module, "ManagerRpcServer", FakeManager)
    monkeypatch.setattr(sidecar_module.websockets, "serve", fake_websocket_serve)

    asyncio.run(
        serve(
            SidecarConfig(
                runtime_root=tmp_path,
                data_root=tmp_path,
                bridge_socket_path=tmp_path / "bridge.sock",
                manager_socket_path=tmp_path / "manager.sock",
                bind_host="127.0.0.1",
                bind_port=0,
            )
        )
    )

    assert health_samples == [True, False]
    assert events == [
        "channel_connected",
        "listener_entered",
        "listener_closed",
        "channel_closed",
    ]


def test_ingress_does_not_wait_for_a_reply_before_sending_the_next_message(tmp_path: Path) -> None:
    async def scenario() -> None:
        history = ChatHistoryStore(tmp_path / "history.sqlite3")
        channel = _Channel()
        server = _server(history, channel)
        try:
            request_ids = await asyncio.gather(
                server._dispatch_to_pal("first"),
                server._dispatch_to_pal("/status"),
                server._dispatch_to_pal("second"),
            )
            assert [text for text, _request_id in channel.sent] == ["first", "/status", "second"]
            assert request_ids[0].startswith("chat_")
            assert request_ids[1].startswith("control_")
            assert request_ids[2].startswith("chat_")
            page = history.page()
            assert [item["text"] for item in page["messages"]] == ["first", "second"]
        finally:
            history.close()

    asyncio.run(scenario())


def test_failed_ingress_does_not_leave_a_ghost_history_message(tmp_path: Path) -> None:
    async def scenario() -> None:
        history = ChatHistoryStore(tmp_path / "history.sqlite3")
        server = _server(history, _FailingChannel())
        try:
            try:
                await server._dispatch_to_pal("not delivered")
            except ConnectionError:
                pass
            else:
                raise AssertionError("expected delivery failure")
            assert len(server._channel.attempts) == 3
            assert len({request_id for _text, request_id in server._channel.attempts}) == 1
            assert history.page()["messages"] == []
        finally:
            history.close()

    asyncio.run(scenario())


def test_ingress_retries_with_backoff_and_commits_only_after_delivery(tmp_path: Path) -> None:
    async def scenario() -> None:
        history = ChatHistoryStore(tmp_path / "history.sqlite3")
        channel = _FlakyChannel(failures=2)
        server = _server(history, channel)
        try:
            request_id = await server._dispatch_to_pal("eventually delivered")
            assert channel.sent == [("eventually delivered", request_id)]
            assert channel.attempts == [("eventually delivered", request_id)] * 3
            assert [item["text"] for item in history.page()["messages"]] == [
                "eventually delivered"
            ]
        finally:
            history.close()

    asyncio.run(scenario())


def test_ingress_queue_discards_after_three_failures_and_reports_request_id(tmp_path: Path) -> None:
    async def scenario() -> None:
        history = ChatHistoryStore(tmp_path / "history.sqlite3")
        channel = _FailingChannel()
        server = _server(history, channel)
        origin = _WebSocket()
        request_id = server._queue_user_message("drop me", origin=origin)
        worker = asyncio.create_task(server.ingress_pump())
        try:
            await asyncio.wait_for(server._ingress_queue.join(), timeout=1.0)
            assert len(channel.attempts) == 3
            assert history.page()["messages"] == []
            failure = json.loads(origin.sent[-1])
            assert failure["type"] == "delivery_failed"
            assert failure["request_id"] == request_id
            assert "failed after 3 attempts" in failure["error"]
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            history.close()

    asyncio.run(scenario())


def test_tagged_display_projection_survives_sidecar_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "history.sqlite3"
        history = ChatHistoryStore(path)
        server = _server(history)
        await server.broadcast_tagged_message(
            tag="checklist",
            text="Checklist progress 0/1",
            payload={"action": "upsert", "plan": [{"step": "inspect"}]},
        )
        history.close()

        restored_history = ChatHistoryStore(path)
        restored = _server(restored_history)
        assert restored._tagged_messages["checklist"]["payload"]["action"] == "upsert"
        restored_history.close()

    asyncio.run(scenario())


def test_completed_chat_reconstructs_without_stale_boundary_replay(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        path = tmp_path / "history.sqlite3"
        history = ChatHistoryStore(path)
        history.append("chat_pending", "user", "finish this")
        server = _server(history)
        await server._project_pal_reply({
            "type": "text_delta",
            "request_id": "chat_pending",
            "text": "finished while absent",
        })
        await server._project_pal_reply({
            "type": "done",
            "request_id": "chat_pending",
            "finish_reason": "stop",
        })
        history.close()

        restored_history = ChatHistoryStore(path)
        restored = _server(restored_history)
        reconnect = _WebSocket()
        await restored.handle(reconnect)
        replayed = [json.loads(frame) for frame in reconnect.sent]
        history_frames = [frame for frame in replayed if frame.get("type") == "chat_history"]
        assert len(history_frames) == 1
        messages = history_frames[0]["messages"]
        avatar_messages = [message for message in messages if message["sender"] == "avatar"]
        assert [message["text"] for message in avatar_messages] == [
            "finished while absent"
        ]
        assert avatar_messages[0]["complete"] is True
        assert not any(
            frame.get("type") == "chat_message"
            and frame.get("event") in {"start", "done"}
            for frame in replayed
        )
        restored_history.close()

    asyncio.run(scenario())


def test_pal_delivery_receipts_survive_sidecar_restart(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    history = ChatHistoryStore(path)
    assert not history.has_pal_delivery("delivery-1")
    history.remember_pal_delivery("delivery-1")
    assert history.has_pal_delivery("delivery-1")
    history.close()

    restored = ChatHistoryStore(path)
    assert restored.has_pal_delivery("delivery-1")
    restored.close()


def test_pal_projection_rolls_back_when_receipt_cannot_commit(tmp_path: Path) -> None:
    async def scenario() -> None:
        history = ChatHistoryStore(tmp_path / "history.sqlite3")
        channel = _ReplyChannel([{
            "type": "done",
            "request_id": "control_0_atomic",
            "final_text": "must be atomic",
            "_pal_delivery_id": "delivery-atomic",
        }])
        server = _server(history, channel)

        def fail_receipt(_delivery_id: str) -> None:
            raise sqlite3.OperationalError("receipt unavailable")

        history._remember_pal_delivery = fail_receipt
        worker = asyncio.create_task(server.reply_pump())
        try:
            try:
                await asyncio.wait_for(worker, timeout=1.0)
            except sqlite3.OperationalError as exc:
                assert "receipt unavailable" in str(exc)
            else:
                raise AssertionError("expected receipt failure")
            assert history.active_control_replies() == {}
            assert not history.has_pal_delivery("delivery-atomic")
            assert channel.acknowledged == []
        finally:
            if not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            history.close()

    asyncio.run(scenario())


def test_offline_control_reply_replays_as_one_acknowledged_notification(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        path = tmp_path / "history.sqlite3"
        history = ChatHistoryStore(path)
        channel = _ReplyChannel([
            {
                "type": "text_delta",
                "request_id": "control_0_status",
                "text": "status while absent",
                "_pal_delivery_id": "delivery-control-text",
            },
            {
                "type": "text_delta",
                "request_id": "control_0_status",
                "text": "status while absent",
                "_pal_delivery_id": "delivery-control-text",
            },
            {
                "type": "done",
                "request_id": "control_0_status",
                "finish_reason": "stop",
                "_pal_delivery_id": "delivery-control-done",
            },
        ])
        server = _server(history, channel)
        worker = asyncio.create_task(server.reply_pump())
        try:
            deadline = asyncio.get_running_loop().time() + 1.0
            while len(channel.acknowledged) < 3:
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("Pal replies were not acknowledged")
                await asyncio.sleep(0)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

        assert channel.acknowledged == [
            "delivery-control-text",
            "delivery-control-text",
            "delivery-control-done",
        ]
        pending = history.pending_control_deliveries()
        assert pending == [{
            "request_id": "control_0_status",
            "text": "status while absent",
            "delivery_id": "control:control_0_status",
        }]
        history.close()

        restored_history = ChatHistoryStore(path)
        restored = _server(restored_history)
        browser = _IncomingWebSocket([{
            "type": "browser_delivery_ack",
            "delivery_id": "control:control_0_status",
        }])
        await restored.handle(browser)
        replayed = [json.loads(frame) for frame in browser.sent]
        notifications = [
            frame
            for frame in replayed
            if frame.get("_avatar_delivery_id") == "control:control_0_status"
        ]
        assert len(notifications) == 1
        assert notifications[0]["event"] == "notification"
        assert notifications[0]["text"] == "status while absent"
        assert restored_history.pending_control_deliveries() == []
        restored_history.close()

    asyncio.run(scenario())


def test_unknown_tag_uses_durable_ordinary_text_fallback(tmp_path: Path) -> None:
    async def scenario() -> None:
        history = ChatHistoryStore(tmp_path / "history.sqlite3")
        request_id = "chat_0_future_tag"
        history.append(request_id, "user", "show the future widget")
        server = _server(history)
        try:
            await server._project_pal_reply({
                "type": "tagged_message",
                "request_id": request_id,
                "tag": "future_widget",
                "text": "ordinary fallback",
                "payload": {"future": True},
            })
            await server._project_pal_reply({"type": "done", "request_id": request_id})
            assert [item["text"] for item in history.page()["messages"]] == [
                "show the future widget",
                "ordinary fallback",
            ]
        finally:
            history.close()

    asyncio.run(scenario())


def test_active_interaction_projection_survives_restart_and_resolve_clears_it(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "history.sqlite3"
        interaction = {
            "interaction_id": "ix-1",
            "interaction_kind": "panel",
            "text": "Choose",
            "buttons": [[{"label": "OK", "token": "0"}]],
        }
        history = ChatHistoryStore(path)
        server = _server(history)
        await server.broadcast_interaction(
            interaction,
            event="open",
            message_id="control_0_open",
        )
        history.close()

        restored_history = ChatHistoryStore(path)
        restored = _server(restored_history)
        assert restored._interactions["ix-1"]["event"] == "open"
        await restored.broadcast_interaction(
            interaction,
            event="resolve",
            message_id="control_0_resolve",
        )
        assert restored._interactions == {}
        assert restored_history.load_interactions() == {}
        restored_history.close()

    asyncio.run(scenario())


def test_partial_chat_is_ephemeral_and_terminal_text_recovers_after_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "history.sqlite3"
        history = ChatHistoryStore(path)
        chat_id = "chat_0_request"
        history.append(chat_id, "user", "keep working")
        server = _server(history)
        client = _WebSocket()
        server._clients.add(client)

        await server._project_pal_reply({"type": "text_delta", "request_id": chat_id, "text": "part one"})
        await server._project_pal_reply({"type": "text_delta", "request_id": "control_0_status", "text": "status"})
        await server._project_pal_reply({"type": "done", "request_id": "control_0_status"})
        assert history.active_replies() == {}
        history.close()

        restored_history = ChatHistoryStore(path)
        restored = _server(restored_history)
        assert restored._reply_parts == {}
        reconnect = _WebSocket()
        await restored.handle(reconnect)
        history_frame = next(
            json.loads(frame)
            for frame in reconnect.sent
            if json.loads(frame).get("type") == "chat_history"
        )
        active = [item for item in history_frame["messages"] if item["sender"] == "avatar"]
        assert active == []

        await restored._project_pal_reply({
            "type": "done",
            "request_id": chat_id,
            "final_text": "part one and two",
        })
        assert restored_history.active_replies() == {}
        messages = restored_history.page()["messages"]
        assert [item["text"] for item in messages] == ["keep working", "part one and two"]
        assert messages[-1]["complete"] is True
        restored_history.close()

    asyncio.run(scenario())


def test_terminal_full_text_repairs_a_delta_lost_during_reattach(tmp_path: Path) -> None:
    async def scenario() -> None:
        history = ChatHistoryStore(tmp_path / "history.sqlite3")
        request_id = "chat_0_repair"
        history.append(request_id, "user", "continue")
        history.append_avatar_delta(request_id, "visible prefix")
        server = _server(history)
        client = _WebSocket()
        server._clients.add(client)

        await server._project_pal_reply({
            "type": "llm_done",
            "request_id": request_id,
            "finish_reason": "stop",
            "final_text": "visible prefix and recovered tail",
        })

        assert [item["text"] for item in history.page()["messages"]] == [
            "continue",
            "visible prefix and recovered tail",
        ]
        frames = [json.loads(frame) for frame in client.sent]
        assert any(
            frame.get("event") == "delta" and frame.get("text") == " and recovered tail"
            for frame in frames
        )
        assert frames[-1]["event"] == "done"
        history.close()

    asyncio.run(scenario())


def test_visible_text_rounds_are_paragraph_separated_inside_one_bubble(tmp_path: Path) -> None:
    async def scenario() -> None:
        history = ChatHistoryStore(tmp_path / "history.sqlite3")
        request_id = "chat_0_multistep"
        history.append(request_id, "user", "exercise the checklist")
        server = _server(history)
        client = _WebSocket()
        server._clients.add(client)

        await server._project_pal_reply({
            "type": "text_delta",
            "request_id": request_id,
            "text": "First checklist update.",
        })
        await server._project_pal_reply({
            "type": "op_tool_call",
            "request_id": request_id,
            "op_tool_call": {"name": "checklist_update", "args": {}},
        })
        await server._project_pal_reply({
            "type": "llm_done",
            "request_id": request_id,
            "finish_reason": "tool_calls",
        })
        await server._project_pal_reply({
            "type": "text_delta",
            "request_id": request_id,
            "text": "Second update",
        })
        await server._project_pal_reply({
            "type": "text_delta",
            "request_id": request_id,
            "text": " continues normally.",
        })
        await server._project_pal_reply({
            "type": "llm_done",
            "request_id": request_id,
            "finish_reason": "stop",
        })

        assert [item["text"] for item in history.page()["messages"]] == [
            "exercise the checklist",
            "First checklist update.\n\nSecond update continues normally.",
        ]
        frames = [json.loads(frame) for frame in client.sent]
        deltas = [
            frame["text"]
            for frame in frames
            if frame.get("type") == "chat_message" and frame.get("event") == "delta"
        ]
        assert deltas == [
            "First checklist update.",
            "\n\nSecond update",
            " continues normally.",
        ]
        assert sum(frame.get("event") == "start" for frame in frames) == 1
        assert sum(frame.get("event") == "done" for frame in frames) == 1
        history.close()

    asyncio.run(scenario())


def test_tool_workspace_reconnect_restores_only_current_turn(tmp_path: Path) -> None:
    async def run() -> None:
        history = ChatHistoryStore(tmp_path / 'activity.sqlite3')
        server = _server(history)
        await server._project_pal_reply({'type': 'tool_activity', 'payload': {
            'action': 'begin', 'turn_id': 'active',
        }})
        await server._project_pal_reply({'type': 'tool_activity', 'payload': {
            'action': 'call', 'turn_id': 'active', 'call_id': 'one',
            'tool': 'read_file', 'arguments': '{}', 'status': 'succeeded',
        }})
        ws = _WebSocket()
        await server.handle(ws)
        frames = [json.loads(raw) for raw in ws.sent]
        activity = [f['payload'] for f in frames if f['type'] == 'tool_activity']
        assert [f['action'] for f in activity] == ['begin', 'call']
        assert activity[-1]['call_id'] == 'one'
        await server._project_pal_reply({'type': 'tool_activity', 'payload': {
            'action': 'end', 'turn_id': 'active',
        }})
        ws = _WebSocket()
        await server.handle(ws)
        assert not any(json.loads(raw)['type'] == 'tool_activity' for raw in ws.sent)

    asyncio.run(run())


def test_terminal_reply_closes_tools_when_optional_end_is_missing(tmp_path: Path) -> None:
    async def run() -> None:
        server = _server(ChatHistoryStore(tmp_path / 'tools.sqlite3'))
        client = _WebSocket()
        server._clients.add(client)
        await server._project_pal_reply({'type': 'tool_activity', 'request_id': 'chat_current',
            'payload': {'action': 'begin', 'turn_id': 'current'}})
        await server._project_pal_reply({'type': 'tool_activity', 'request_id': 'chat_current',
            'payload': {'action': 'call', 'turn_id': 'current', 'call_id': 'one'}})
        for request, reason in [('chat_previous', 'stop'), ('chat_current', 'tool_calls'),
                                ('chat_current', 'compact_required')]:
            await server._project_pal_reply({'type': 'llm_done', 'request_id': request, 'finish_reason': reason})
            assert server._tool_activity.turn_id == 'current'
        await server._project_pal_reply({'type': 'llm_done', 'request_id': 'chat_current', 'finish_reason': 'stop'})
        assert server._tool_activity.frames() == []
        assert json.loads(client.sent[-1])['payload']['action'] == 'end'
        await server._project_pal_reply({'type': 'tool_activity', 'request_id': 'chat_current',
            'payload': {'action': 'call', 'turn_id': 'current', 'call_id': 'late'}})
        assert server._tool_activity.frames() == []
    asyncio.run(run())


def test_idle_sleep_auto_wake_and_message_startle(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(sidecar_module.time, 'monotonic', lambda: now[0])
    queue = AvatarStateQueue()
    sm = StateMachine(queue, idle_timeout=10)
    now[0] += 10
    assert sm.tick() == 'sleeping'
    now[0] += sidecar_module.SLEEPING_WAKE_TIMEOUT
    assert sm.tick() == 'standby'
    now[0] += 10
    assert sm.tick() == 'sleeping'
    sm.on_client_message()
    assert sm.current_state == 'shock'
    assert queue.pop()['state'] == 'shock'
    sm.on_reply_delta()
    sm.on_client_message()  # A second message must not erase the wake-up beat.
    assert sm.current_state == 'shock'
    sm.on_reply_done()
    assert sm.on_external_action_finished('shock')
    assert sm.current_state == 'standby'
    assert queue.pop()['state'] == 'standby'
    sm.on_client_message()
    assert sm.current_state == 'thinking'  # Awake messages do not startle.


def test_wakeup_recovers_without_browser_completion(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(sidecar_module.time, 'monotonic', lambda: now[0])
    sm = StateMachine(AvatarStateQueue(), idle_timeout=10)
    now[0] += 10
    sm.tick()
    sm.on_client_message()
    sm.on_reply_delta()
    now[0] += sidecar_module.WAKEUP_FAILSAFE_SECONDS
    assert sm.tick() == 'working'
    assert not sm.on_external_action_finished('shock')


def test_independent_emotions_preserve_identity_and_dance_is_removed():
    queue = AvatarStateQueue()
    machine = StateMachine(queue, idle_timeout=3600)
    for name in ("error", "crying", "shy", "awkward", "bored", "celebrate", "agree"):
        assert sidecar_module.normalize_state(name) == name
        assert machine.on_external_state(name)
        assert machine.current_state == name
        assert machine.on_external_action_finished(name)
        assert machine.current_state == "standby"
    assert sidecar_module.normalize_state("err") == "error"
    assert not machine.on_external_state("dance")
