from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from server.sidecar import AvatarWebSocketServer, ChatHistoryStore


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


def _server(history: ChatHistoryStore, channel: _Channel | None = None) -> AvatarWebSocketServer:
    return AvatarWebSocketServer(
        state_machine=_StateMachine(),
        state_queue=SimpleNamespace(),
        channel=channel or _Channel(),
        history=history,
        loop=asyncio.get_running_loop(),
        ingress_retry_delays=(0.0, 0.0),
    )


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


def test_active_chat_projection_survives_sidecar_restart_and_interleaved_control_reply(tmp_path: Path) -> None:
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
        assert history.active_replies() == {chat_id: "part one"}
        history.close()

        restored_history = ChatHistoryStore(path)
        restored = _server(restored_history)
        assert restored._reply_parts == {chat_id: ["part one"]}
        reconnect = _WebSocket()
        await restored.handle(reconnect)
        history_frame = next(
            json.loads(frame)
            for frame in reconnect.sent
            if json.loads(frame).get("type") == "chat_history"
        )
        active = [item for item in history_frame["messages"] if item["sender"] == "avatar"]
        assert active == [
            {
                "id": active[0]["id"],
                "turn_id": chat_id,
                "sender": "avatar",
                "text": "part one",
                "created_at_us": active[0]["created_at_us"],
                "complete": False,
            }
        ]

        await restored._project_pal_reply({"type": "text_delta", "request_id": chat_id, "text": " and two"})
        await restored._project_pal_reply({"type": "done", "request_id": chat_id})
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
        assert frames[-2]["event"] == "done"
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
