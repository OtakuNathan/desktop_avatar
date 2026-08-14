#!/usr/bin/env python3
"""Desktop Avatar Sidecar — mother's desktop-pet chat bridge.

WebSocket server (mother's client) <-> Pal channel endpoint socket.

Wire format: JSON text frames with a ``type`` field for channel multiplexing:

  client -> sidecar:
    {"type": "chat_message", "text": "..."}   # mother sends a message
    {"type": "ping"}                          # keepalive

  sidecar -> client:
    {"type": "chat_message", "text": "...", "sender": "avatar"}
    {"type": "avatar_state", "state": "standby"}
    {"type": "pong"}

States mirror the OLED emotion set so the client can reuse the same animation
mapping: standby / sleeping / thinking / working plus expressive reactions.

State policy is self-contained: the sidecar infers avatar state from the
message flow (thinking while a reply is pending, working while the channel
socket streams a reply, standby when idle, sleeping after an idle timeout).
A later revision may subscribe to Pal turn events for richer states.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import mimetypes
import os
import signal
import sqlite3
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import unquote, urlsplit

import websockets
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from pal.foundation.sidecar import pack_sidecar_message, read_sidecar_message

SOCKET_PROTOCOL_TYPE: str = "user_message"
MAX_FRAME_BYTES: int = 16 * 1024 * 1024

IDLE_TO_SLEEPING_SECONDS: float = 3600.0  # 1h without any traffic -> sleeping
SLEEPING_WAKE_TIMEOUT: float = 3600.0
THINKING_PROBE_SECONDS: float = 0.1
EXPRESSIVE_STATE_SECONDS: float = 1.1
HISTORY_PAGE_ROUNDS: int = 10
INGRESS_DELIVERY_ATTEMPTS: int = 3
INGRESS_RETRY_DELAYS: tuple[float, ...] = (0.25, 0.5)

VALID_STATES = [
    "standby", "sleeping", "thinking", "working",
    "happy", "sad", "angry", "shock", "wink", "curious",
    "awkward", "smirk", "cheeky",
    "excited", "shy", "proud", "confused", "love", "panic", "bored",
    "greeting", "celebrate",
    "snacking", "drinking", "stretching",
]

# Persistent states alternate while the avatar is actively busy.
PERSISTENT_STATES = ("thinking", "working")
IDLE_STATES = frozenset({"standby", "sleeping"})
EXPRESSIVE_STATES = frozenset({
    "happy", "sad", "angry", "shock", "wink", "curious",
    "awkward", "smirk", "cheeky",
    "excited", "shy", "proud", "confused", "love", "panic", "bored",
    "greeting", "celebrate",
    "snacking", "drinking", "stretching",
})
STATE_ALIASES = {
    "sleepy": "sleeping", "crying": "sad", "error": "shock",
    "embarrassed": "awkward", "smug": "smirk", "playful": "cheeky",
    "surprised": "shock", "wave": "greeting",
    "snack": "snacking", "drink": "drinking", "stretch": "stretching",
}


def _default_client_root() -> Path:
    """Find the bundled browser client in source and installed layouts."""
    configured = os.environ.get("PAL_DESKTOP_AVATAR_CLIENT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    module_dir = Path(__file__).resolve().parent
    installed = module_dir / "client"
    return installed if installed.is_dir() else module_dir.parent / "client"


CLIENT_ROOT = _default_client_root()


def _http_response(status: int, reason: str, body: bytes, content_type: str) -> Response:
    import hashlib

    headers = {
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Cache-Control": "no-cache",
        "ETag": '"' + hashlib.sha1(body).hexdigest() + '"',
        "X-Content-Type-Options": "nosniff",
    }
    return Response(status, reason, Headers(headers), body)


def serve_client_asset(_connection: object, request: Request) -> Response | None:
    """Serve the self-contained client; WebSocket upgrades continue normally."""
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None

    relative = unquote(urlsplit(request.path).path).lstrip("/") or "index.html"
    candidate = (CLIENT_ROOT / relative).resolve()
    try:
        candidate.relative_to(CLIENT_ROOT.resolve())
    except ValueError:
        return _http_response(404, "Not Found", b"Not Found\n", "text/plain; charset=utf-8")
    if not candidate.is_file():
        return _http_response(404, "Not Found", b"Not Found\n", "text/plain; charset=utf-8")

    body = candidate.read_bytes()
    content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
        content_type += "; charset=utf-8"
    return _http_response(200, "OK", body, content_type)


def normalize_state(state: object) -> str:
    value = str(state or "").strip().lower()
    return STATE_ALIASES.get(value, value)


@dataclass
class SidecarConfig:
    runtime_root: Path
    data_root: Path
    bridge_socket_path: Path      # Pal endpoint socket (message delivery)
    manager_socket_path: Path     # Pal -> sidecar RPC socket (health/shutdown)
    bind_host: str = "0.0.0.0"
    bind_port: int = 8765
    idle_to_sleeping_seconds: float = IDLE_TO_SLEEPING_SECONDS


@dataclass(frozen=True)
class PendingIngress:
    """One browser action waiting for bounded delivery to Pal."""

    kind: str
    request_id: str
    origin: Any = field(compare=False)
    text: str = ""
    interaction_id: str = ""
    button_token: str = ""


# --------------------------------------------------------------------------- #
# State machine (thread-safe, mirroring the OLED sidecar policy)              #
# --------------------------------------------------------------------------- #

class AvatarStateQueue:
    """Latest-state delivery queue; expressive pushes discard stale motion."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._queue: deque[dict[str, Any]] = deque()
        self._last_push_time: float = 0.0

    def push(self, state: str, *, preempt: bool = False) -> None:
        with self._lock:
            # This queue transports display transitions, not history. A newer
            # state always supersedes a transition the client has not seen yet.
            if preempt or state in IDLE_STATES or self._queue:
                self._queue.clear()
            self._queue.append({"state": state, "at": time.time()})
            self._last_push_time = time.time()

    def pop(self) -> dict[str, Any] | None:
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    def idle_since(self) -> float:
        with self._lock:
            return time.time() - self._last_push_time if self._last_push_time else 0.0

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()


class StateMachine:
    """Base activity state plus preemptive user/Pal expressive actions."""

    def __init__(self, queue: AvatarStateQueue, idle_timeout: float) -> None:
        self._queue = queue
        self._idle_timeout = idle_timeout
        self._base_state = "standby"
        self._display_state = "standby"
        self._override_state: str | None = None
        self._override_until = 0.0
        self._last_activity = time.monotonic()

    @property
    def current_state(self) -> str:
        return self._display_state

    def _set_base_state(self, state: str) -> None:
        normalized = normalize_state(state)
        if normalized not in (*PERSISTENT_STATES, *IDLE_STATES):
            return
        changed = normalized != self._base_state or normalized != self._display_state
        self._base_state = normalized
        self._last_activity = time.monotonic()
        if self._override_state is None and changed:
            self._display_state = normalized
            self._queue.push(normalized, preempt=normalized in IDLE_STATES)

    def on_client_message(self) -> None:
        """Mother sent a message: wake up and think."""
        self._override_state = None
        self._override_until = 0.0
        self._queue.clear()
        self._set_base_state("thinking")

    def on_reply_delta(self) -> None:
        """Pal is streaming a reply: working."""
        self._set_base_state("working")

    def on_reply_done(self) -> None:
        """Reply finished: back to standby."""
        self._set_base_state("standby")

    def on_external_state(self, state: str, *, duration: float = EXPRESSIVE_STATE_SECONDS) -> bool:
        """Apply a Pal/user state signal; expressive states preempt then resume."""
        normalized = normalize_state(state)
        if normalized not in VALID_STATES:
            return False
        if normalized in EXPRESSIVE_STATES:
            bounded_duration = min(5.0, max(0.4, float(duration or EXPRESSIVE_STATE_SECONDS)))
            self._override_state = normalized
            self._override_until = time.monotonic() + bounded_duration
            self._display_state = normalized
            self._last_activity = time.monotonic()
            self._queue.push(normalized, preempt=True)
            return True
        self._set_base_state(normalized)
        return True

    def tick(self) -> str | None:
        """Return next state to broadcast, or None when nothing changed."""
        now = time.monotonic()
        if self._override_state is not None:
            if now < self._override_until:
                return None
            self._override_state = None
            self._override_until = 0.0
            self._display_state = self._base_state
            self._queue.push(self._base_state, preempt=True)
            return self._base_state
        if self._base_state == "standby" and now - self._last_activity >= self._idle_timeout:
            self._set_base_state("sleeping")
            return "sleeping"
        return None


# --------------------------------------------------------------------------- #
# Manager RPC: health / shutdown / push_state                                  #
# --------------------------------------------------------------------------- #

class ManagerRpcServer:
    """Unix-socket RPC endpoint for Pal-side supervision and state pushes."""

    def __init__(
        self,
        *,
        manager_socket_path: Path,
        health_fn,
        shutdown_fn,
        state_callback,
        ready_event: asyncio.Event,
    ) -> None:
        self._manager_socket_path = manager_socket_path
        self._health = health_fn
        self._shutdown = shutdown_fn
        self._state_callback = state_callback
        self._ready = ready_event

    async def serve(self) -> None:
        # The manager socket is created by the parent (Pal) via SidecarEndpoint;
        # the sidecar only awaits readiness. If the socket does not exist yet,
        # wait for it (parent binds before spawning in practice).
        loop = asyncio.get_running_loop()

        async def handle(reader, writer):
            try:
                while True:
                    payload = await read_sidecar_message(reader)
                    method = str(payload.get("method") or payload.get("type") or "")
                    params = dict(payload.get("params") or {})
                    request_id = str(payload.get("id") or "")

                    def response(result: dict[str, Any], *, ok: bool = True) -> bytes:
                        if request_id:
                            frame: dict[str, Any] = {
                                "type": "response",
                                "id": request_id,
                                "ok": ok,
                            }
                            if ok:
                                frame["result"] = result
                            else:
                                frame["error"] = result
                            return pack_sidecar_message(frame)
                        return pack_sidecar_message({"ok": ok, **result})

                    if method == "health":
                        writer.write(response(self._health()))
                        await writer.drain()
                    elif method == "shutdown":
                        writer.write(response({}))
                        await writer.drain()
                        self._ready.clear()
                        for task in asyncio.all_tasks():
                            if task is not asyncio.current_task():
                                task.cancel()
                        break
                    elif method == "push_state":
                        state = str(params.get("state") or payload.get("state") or "")
                        duration = params.get("duration", payload.get("duration", EXPRESSIVE_STATE_SECONDS))
                        accepted = await self._state_callback(state, duration)
                        result = {"state": normalize_state(state), "accepted": accepted}
                        writer.write(response(result, ok=accepted))
                        await writer.drain()
                    else:
                        writer.write(response(
                            {"kind": "unknown_method", "message": f"unknown method: {method}"},
                            ok=False,
                        ))
                        await writer.drain()
            except (ConnectionError, EOFError, asyncio.IncompleteReadError):
                pass
            finally:
                with contextlib.suppress(Exception):
                    writer.close()

        self._ready.set()
        server = await asyncio.start_unix_server(handle, path=self._manager_path)
        async with server:
            await server.serve_forever()

    @property
    def _manager_path(self) -> Path:
        return self._manager_socket_path


# --------------------------------------------------------------------------- #
# Pal channel socket client: deliver mother messages, stream replies           #
# --------------------------------------------------------------------------- #

class PalChannelClient:
    """Framed client for the provider-private Pal channel socket."""

    def __init__(self, socket_path: Path) -> None:
        self._path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        for attempt in range(20):
            try:
                self._reader, self._writer = await asyncio.open_unix_connection(str(self._path))
                return
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                await asyncio.sleep(0.5)
        raise ConnectionError(f"cannot connect to Pal channel socket {self._path}")

    async def send_user_message(self, text: str, request_id: str) -> None:
        payload = {
            "type": SOCKET_PROTOCOL_TYPE,
            "request_id": request_id,
            "text": str(text),
        }
        data = pack_sidecar_message(payload)
        async with self._write_lock:
            if self._writer is None:
                raise ConnectionError("Pal channel socket not connected")
            self._writer.write(data)
            await self._writer.drain()

    async def send_interaction_result(
        self,
        interaction_id: str,
        button_token: str,
        request_id: str,
    ) -> None:
        payload = {
            "type": "interaction_result",
            "request_id": request_id,
            "interaction_id": str(interaction_id),
            "button_token": str(button_token),
        }
        data = pack_sidecar_message(payload)
        async with self._write_lock:
            if self._writer is None:
                raise ConnectionError("Pal channel socket not connected")
            self._writer.write(data)
            await self._writer.drain()

    async def read_reply(self) -> dict[str, Any]:
        if self._reader is None:
            raise ConnectionError("Pal channel socket not connected")
        return await read_sidecar_message(self._reader)

    async def close(self) -> None:
        if self._writer is not None:
            with contextlib.suppress(Exception):
                self._writer.close()
                await self._writer.wait_closed()


# --------------------------------------------------------------------------- #
# Durable chat history                                                        #
# --------------------------------------------------------------------------- #

class ChatHistoryStore:
    """Small SQLite transcript store, paged by complete conversation turns."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=3000")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id TEXT NOT NULL,
                sender TEXT NOT NULL CHECK (sender IN ('user', 'avatar')),
                content TEXT NOT NULL,
                created_at_us INTEGER NOT NULL,
                complete INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_order "
            "ON chat_messages(created_at_us, id)"
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_turn "
            "ON chat_messages(turn_id, created_at_us, id)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS display_projection ("
            "projection_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL"
            ")"
        )
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(chat_messages)").fetchall()
        }
        if "complete" not in columns:
            self._connection.execute(
                "ALTER TABLE chat_messages ADD COLUMN complete INTEGER NOT NULL DEFAULT 1"
            )
        row = self._connection.execute(
            "SELECT COALESCE(MAX(created_at_us), 0) AS latest FROM chat_messages"
        ).fetchone()
        self._last_timestamp_us = int(row["latest"] if row else 0)
        self._connection.commit()

    def append(self, turn_id: str, sender: str, content: str) -> None:
        text = str(content or "").strip()
        if not text:
            return
        timestamp_us = max(time.time_ns() // 1_000, self._last_timestamp_us + 1)
        self._last_timestamp_us = timestamp_us
        self._connection.execute(
            "INSERT INTO chat_messages(turn_id, sender, content, created_at_us) "
            "VALUES (?, ?, ?, ?)",
            (str(turn_id), str(sender), text, timestamp_us),
        )
        self._connection.commit()

    def page(
        self,
        *,
        before_created_at_us: int | None = None,
        before_id: int | None = None,
        limit_rounds: int = HISTORY_PAGE_ROUNDS,
    ) -> dict[str, Any]:
        """Return the preceding N turns in chronological display order."""
        limit = max(1, min(int(limit_rounds), 50))
        params: list[Any] = []
        having = ""
        if before_created_at_us is not None and before_id is not None:
            having = (
                "HAVING MAX(created_at_us) < ? "
                "OR (MAX(created_at_us) = ? AND MAX(id) < ?)"
            )
            params.extend((before_created_at_us, before_created_at_us, before_id))
        params.append(limit + 1)
        turns = self._connection.execute(
            f"""
            SELECT turn_id, MAX(created_at_us) AS turn_at_us, MAX(id) AS turn_last_id
            FROM chat_messages
            GROUP BY turn_id
            {having}
            ORDER BY turn_at_us DESC, turn_last_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        has_more = len(turns) > limit
        selected = turns[:limit]
        if not selected:
            return {"messages": [], "cursor": None, "has_more": False}

        turn_ids = [str(row["turn_id"]) for row in selected]
        placeholders = ",".join("?" for _ in turn_ids)
        rows = self._connection.execute(
            f"""
            SELECT id, turn_id, sender, content, created_at_us, complete
            FROM chat_messages
            WHERE turn_id IN ({placeholders})
            ORDER BY created_at_us ASC, id ASC
            """,
            turn_ids,
        ).fetchall()
        oldest_turn = selected[-1]
        return {
            "messages": [
                {
                    "id": int(row["id"]),
                    "turn_id": str(row["turn_id"]),
                    "sender": str(row["sender"]),
                    "text": str(row["content"]),
                    "created_at_us": int(row["created_at_us"]),
                    "complete": bool(row["complete"]),
                }
                for row in rows
            ],
            "cursor": {
                "created_at_us": int(oldest_turn["turn_at_us"]),
                "id": int(oldest_turn["turn_last_id"]),
            },
            "has_more": has_more,
        }

    def append_avatar_delta(self, turn_id: str, delta: str) -> bool:
        """Update the durable display projection for one active chat reply.

        A matching user row is the authority that this is an ordinary chat
        request. Control and interaction replies remain transient UI output.
        """
        normalized_turn_id = str(turn_id or "")
        text = str(delta or "")
        if not normalized_turn_id or not text:
            return False
        user = self._connection.execute(
            "SELECT 1 FROM chat_messages WHERE turn_id = ? AND sender = 'user' LIMIT 1",
            (normalized_turn_id,),
        ).fetchone()
        if user is None:
            return False
        avatar = self._connection.execute(
            "SELECT id FROM chat_messages "
            "WHERE turn_id = ? AND sender = 'avatar' "
            "ORDER BY created_at_us DESC, id DESC LIMIT 1",
            (normalized_turn_id,),
        ).fetchone()
        if avatar is None:
            timestamp_us = max(time.time_ns() // 1_000, self._last_timestamp_us + 1)
            self._last_timestamp_us = timestamp_us
            self._connection.execute(
                "INSERT INTO chat_messages(turn_id, sender, content, created_at_us, complete) "
                "VALUES (?, 'avatar', ?, ?, 0)",
                (normalized_turn_id, text, timestamp_us),
            )
        else:
            self._connection.execute(
                "UPDATE chat_messages SET content = content || ?, complete = 0 WHERE id = ?",
                (text, int(avatar["id"])),
            )
        self._connection.commit()
        return True

    def complete_avatar(self, turn_id: str) -> None:
        self._connection.execute(
            "UPDATE chat_messages SET complete = 1 "
            "WHERE id = ("
            "SELECT id FROM chat_messages WHERE turn_id = ? AND sender = 'avatar' "
            "ORDER BY created_at_us DESC, id DESC LIMIT 1"
            ")",
            (str(turn_id or ""),),
        )
        self._connection.commit()

    def active_replies(self) -> dict[str, str]:
        rows = self._connection.execute(
            "SELECT turn_id, content FROM chat_messages "
            "WHERE sender = 'avatar' AND complete = 0 "
            "ORDER BY created_at_us ASC, id ASC"
        ).fetchall()
        return {str(row["turn_id"]): str(row["content"]) for row in rows}

    def load_tagged_messages(self) -> dict[str, dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT projection_key, payload_json FROM display_projection "
            "WHERE projection_key LIKE 'tagged:%'"
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            tag = str(row["projection_key"]).removeprefix("tagged:")
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError):
                continue
            if tag and isinstance(payload, dict):
                result[tag] = payload
        return result

    def store_tagged_message(self, tag: str, frame: dict[str, Any] | None) -> None:
        key = f"tagged:{str(tag or '').strip()}"
        if not key.removeprefix("tagged:"):
            return
        if frame is None:
            self._connection.execute(
                "DELETE FROM display_projection WHERE projection_key = ?",
                (key,),
            )
        else:
            self._connection.execute(
                "INSERT INTO display_projection(projection_key, payload_json) VALUES (?, ?) "
                "ON CONFLICT(projection_key) DO UPDATE SET payload_json = excluded.payload_json",
                (key, json.dumps(frame, ensure_ascii=False, separators=(",", ":"))),
            )
        self._connection.commit()

    def load_interactions(self) -> dict[str, dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT projection_key, payload_json FROM display_projection "
            "WHERE projection_key LIKE 'interaction:%'"
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            interaction_id = str(row["projection_key"]).removeprefix("interaction:")
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError):
                continue
            if interaction_id and isinstance(payload, dict):
                result[interaction_id] = payload
        return result

    def store_interaction(self, interaction_id: str, frame: dict[str, Any] | None) -> None:
        normalized_id = str(interaction_id or "").strip()
        if not normalized_id:
            return
        key = f"interaction:{normalized_id}"
        if frame is None:
            self._connection.execute(
                "DELETE FROM display_projection WHERE projection_key = ?",
                (key,),
            )
        else:
            self._connection.execute(
                "INSERT INTO display_projection(projection_key, payload_json) VALUES (?, ?) "
                "ON CONFLICT(projection_key) DO UPDATE SET payload_json = excluded.payload_json",
                (key, json.dumps(frame, ensure_ascii=False, separators=(",", ":"))),
            )
        self._connection.commit()

    def clear(self) -> None:
        self._connection.execute("DELETE FROM chat_messages")
        self._connection.commit()
        self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def delete_turn(self, turn_id: str) -> None:
        self._connection.execute(
            "DELETE FROM chat_messages WHERE turn_id = ?",
            (str(turn_id or ""),),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


# --------------------------------------------------------------------------- #
# WebSocket server: mother's desktop-pet client                               #
# --------------------------------------------------------------------------- #

class AvatarWebSocketServer:
    def __init__(self, *, state_machine: StateMachine, state_queue: AvatarStateQueue,
                 channel: PalChannelClient, history: ChatHistoryStore, loop,
                 ingress_retry_delays: tuple[float, ...] = INGRESS_RETRY_DELAYS) -> None:
        self._sm = state_machine
        self._queue = state_queue
        self._channel = channel
        self._history = history
        self._loop = loop
        self._clients: set[websockets.WebSocketServerProtocol] = set()
        self._connected = 0
        self._history_generation = 0
        self._tagged_messages: dict[str, dict[str, Any]] = history.load_tagged_messages()
        self._interactions: dict[str, dict[str, Any]] = history.load_interactions()
        self._reply_parts: dict[str, list[str]] = {
            request_id: [text]
            for request_id, text in history.active_replies().items()
        }
        self._started_replies: set[str] = set()
        self._segment_break_pending: set[str] = set()
        self._ingress_queue: asyncio.Queue[PendingIngress] = asyncio.Queue()
        self._ingress_retry_delays = tuple(ingress_retry_delays)

    async def broadcast_state(self, state: str) -> None:
        frame = json.dumps({"type": "avatar_state", "state": state}, ensure_ascii=False)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def broadcast_frame(self, payload: dict[str, Any]) -> None:
        frame = json.dumps(payload, ensure_ascii=False)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def broadcast_tagged_message(
        self,
        *,
        tag: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        normalized_tag = str(tag or "").strip()
        if not normalized_tag:
            return
        frame = {
            "type": "tagged_message",
            "tag": normalized_tag,
            "text": str(text or ""),
            "payload": dict(payload or {}),
        }
        if str(frame["payload"].get("action") or "").lower() == "clear":
            self._tagged_messages.pop(normalized_tag, None)
            with contextlib.suppress(sqlite3.Error):
                self._history.store_tagged_message(normalized_tag, None)
        else:
            self._tagged_messages[normalized_tag] = frame
            with contextlib.suppress(sqlite3.Error):
                self._history.store_tagged_message(normalized_tag, frame)
        await self.broadcast_frame(frame)

    async def send_history_page(
        self,
        ws: websockets.WebSocketServerProtocol,
        *,
        mode: str,
        before_created_at_us: int | None = None,
        before_id: int | None = None,
    ) -> None:
        try:
            page = self._history.page(
                before_created_at_us=before_created_at_us,
                before_id=before_id,
            )
        except sqlite3.Error as exc:
            await ws.send(json.dumps({
                "type": "history_error",
                "error": f"Failed to load chat history: {exc}",
            }, ensure_ascii=False))
            return
        await ws.send(json.dumps({
            "type": "chat_history",
            "mode": mode,
            **page,
        }, ensure_ascii=False))

    async def broadcast_chat(
        self,
        text: str,
        *,
        event: str = "delta",
        message_id: str = "",
    ) -> None:
        frame = json.dumps(
            {
                "type": "chat_message",
                "sender": "avatar",
                "event": event,
                "message_id": message_id,
                "text": text,
            },
            ensure_ascii=False,
        )
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def broadcast_user_message(self, text: str, *, message_id: str) -> None:
        await self.broadcast_frame({
            "type": "chat_message",
            "sender": "user",
            "event": "message",
            "message_id": str(message_id or ""),
            "text": str(text or ""),
        })

    async def broadcast_interaction(
        self,
        interaction: dict[str, Any],
        *,
        event: str,
        message_id: str,
    ) -> None:
        frame = {
            "type": "chat_interaction",
            "event": str(event or "update"),
            "message_id": str(message_id or ""),
            "interaction": dict(interaction or {}),
        }
        interaction_id = str(frame["interaction"].get("interaction_id") or "").strip()
        if interaction_id:
            if frame["event"] in {"resolve", "expire"}:
                self._interactions.pop(interaction_id, None)
                with contextlib.suppress(sqlite3.Error):
                    self._history.store_interaction(interaction_id, None)
            else:
                self._interactions[interaction_id] = frame
                with contextlib.suppress(sqlite3.Error):
                    self._history.store_interaction(interaction_id, frame)
        await self.broadcast_frame(frame)

    async def handle(self, ws: websockets.WebSocketServerProtocol) -> None:
        self._clients.add(ws)
        self._connected += 1
        try:
            await ws.send(json.dumps({"type": "avatar_state", "state": self._sm.current_state}))
            await self.send_history_page(ws, mode="replace")
            for tagged in self._tagged_messages.values():
                await ws.send(json.dumps(tagged, ensure_ascii=False))
            for interaction in self._interactions.values():
                await ws.send(json.dumps(interaction, ensure_ascii=False))
            async for raw in ws:
                if not raw:
                    continue
                try:
                    frame = json.loads(str(raw))
                except (ValueError, TypeError):
                    await ws.send(json.dumps({"type": "error", "error": "bad_json"}))
                    continue
                kind = str(frame.get("type") or "")
                if kind == "chat_message":
                    text = str(frame.get("text") or "").strip()
                    if not text:
                        continue
                    self._queue_user_message(text, origin=ws)
                elif kind == "load_chat_history":
                    cursor = frame.get("before")
                    if not isinstance(cursor, dict):
                        await ws.send(json.dumps({"type": "history_error", "error": "Invalid history cursor."}, ensure_ascii=False))
                        continue
                    try:
                        before_created_at_us = int(cursor.get("created_at_us"))
                        before_id = int(cursor.get("id"))
                    except (TypeError, ValueError):
                        await ws.send(json.dumps({"type": "history_error", "error": "Invalid history cursor."}, ensure_ascii=False))
                        continue
                    await self.send_history_page(
                        ws,
                        mode="prepend",
                        before_created_at_us=before_created_at_us,
                        before_id=before_id,
                    )
                elif kind == "clear_chat_history":
                    try:
                        self._history.clear()
                    except sqlite3.Error as exc:
                        await ws.send(json.dumps({
                            "type": "history_error",
                            "error": f"Failed to clear chat history: {exc}",
                        }, ensure_ascii=False))
                        continue
                    self._history_generation += 1
                    self._reply_parts = {
                        request_id: parts
                        for request_id, parts in self._reply_parts.items()
                        if not request_id.startswith("chat_")
                    }
                    self._segment_break_pending = {
                        request_id
                        for request_id in self._segment_break_pending
                        if not request_id.startswith("chat_")
                    }
                    await self.broadcast_frame({"type": "chat_history_cleared"})
                elif kind == "ping":
                    await ws.send(json.dumps({"type": "pong"}))
                elif kind == "avatar_action":
                    state = str(frame.get("state") or "")
                    duration = frame.get("duration", EXPRESSIVE_STATE_SECONDS)
                    if normalize_state(state) not in EXPRESSIVE_STATES:
                        await ws.send(json.dumps({"type": "error", "error": "invalid_avatar_action"}))
                        continue
                    self._sm.on_external_state(state, duration=duration)
                elif kind == "interaction_result":
                    interaction_id = str(frame.get("interaction_id") or "").strip()
                    button_token = str(frame.get("button_token") or "").strip()
                    if not interaction_id or not button_token:
                        await ws.send(json.dumps({"type": "error", "error": "invalid_interaction_result"}))
                        continue
                    self._queue_interaction_result(
                        interaction_id,
                        button_token,
                        origin=ws,
                    )
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            self._connected = max(0, self._connected - 1)

    def _queue_user_message(self, text: str, *, origin: Any) -> str:
        persist_history = not text.lstrip().startswith("/")
        request_kind = "chat" if persist_history else "control"
        request_id = f"{request_kind}_{self._history_generation}_{os.urandom(8).hex()}"
        self._ingress_queue.put_nowait(PendingIngress(
            kind="user_message",
            request_id=request_id,
            origin=origin,
            text=text,
        ))
        return request_id

    def _queue_interaction_result(
        self,
        interaction_id: str,
        button_token: str,
        *,
        origin: Any,
    ) -> str:
        request_id = f"interaction_{self._history_generation}_{os.urandom(8).hex()}"
        self._ingress_queue.put_nowait(PendingIngress(
            kind="interaction_result",
            request_id=request_id,
            origin=origin,
            interaction_id=interaction_id,
            button_token=button_token,
        ))
        return request_id

    async def _send_with_backoff(self, send) -> None:
        last_error: BaseException | None = None
        for attempt in range(INGRESS_DELIVERY_ATTEMPTS):
            try:
                await send()
                return
            except (ConnectionError, OSError) as exc:
                last_error = exc
                if attempt + 1 >= INGRESS_DELIVERY_ATTEMPTS:
                    break
                delay_index = min(attempt, len(self._ingress_retry_delays) - 1)
                delay = self._ingress_retry_delays[delay_index] if self._ingress_retry_delays else 0.0
                if delay > 0:
                    await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error

    async def _dispatch_to_pal(self, text: str, *, request_id: str | None = None) -> str:
        """Deliver one message without waiting for its eventual response.

        Pal owns turn serialization and interjection state.  The sidecar is a
        full-duplex transport: browser ingress remains available while the
        independent reply pump projects whatever Pal emits.
        """
        persist_history = not text.lstrip().startswith("/")
        request_kind = "chat" if persist_history else "control"
        request_id = request_id or f"{request_kind}_{self._history_generation}_{os.urandom(8).hex()}"
        await self._send_with_backoff(
            lambda: self._channel.send_user_message(text, request_id)
        )
        if persist_history:
            with contextlib.suppress(sqlite3.Error):
                self._history.append(request_id, "user", text)
            self._sm.on_client_message()
            await self.broadcast_state("thinking")
        await self.broadcast_user_message(text, message_id=request_id)
        return request_id

    async def _dispatch_interaction_to_pal(
        self,
        interaction_id: str,
        button_token: str,
        *,
        request_id: str | None = None,
    ) -> str:
        """Forward one browser button selection through the owning socket session."""
        request_id = request_id or f"interaction_{self._history_generation}_{os.urandom(8).hex()}"
        await self._send_with_backoff(
            lambda: self._channel.send_interaction_result(
                interaction_id,
                button_token,
                request_id,
            )
        )
        return request_id

    async def ingress_pump(self) -> None:
        """Deliver queued browser actions in order, then discard failed items."""
        while True:
            pending = await self._ingress_queue.get()
            try:
                if pending.kind == "interaction_result":
                    await self._dispatch_interaction_to_pal(
                        pending.interaction_id,
                        pending.button_token,
                        request_id=pending.request_id,
                    )
                else:
                    await self._dispatch_to_pal(
                        pending.text,
                        request_id=pending.request_id,
                    )
            except (ConnectionError, OSError) as exc:
                with contextlib.suppress(Exception):
                    await pending.origin.send(json.dumps({
                        "type": "delivery_failed",
                        "request_id": pending.request_id,
                        "error": f"Message delivery to Pal failed after 3 attempts: {exc}",
                    }, ensure_ascii=False))
            finally:
                self._ingress_queue.task_done()

    async def reply_pump(self) -> None:
        """Continuously project the full-duplex Pal socket onto browser peers."""
        while True:
            reply = await self._channel.read_reply()
            await self._project_pal_reply(reply)

    async def _start_reply(self, request_id: str) -> None:
        if not request_id or request_id in self._started_replies:
            return
        self._started_replies.add(request_id)
        await self.broadcast_chat("", event="start", message_id=request_id)

    def _mark_segment_break(self, request_id: str) -> None:
        if request_id and "".join(self._reply_parts.get(request_id, [])).strip():
            self._segment_break_pending.add(request_id)

    def _apply_segment_break(self, request_id: str, text: str) -> str:
        if request_id not in self._segment_break_pending:
            return text
        self._segment_break_pending.discard(request_id)
        prior = "".join(self._reply_parts.get(request_id, []))
        if not prior.strip() or not text.strip() or prior.endswith("\n\n") or text.startswith("\n\n"):
            return text
        if prior.endswith("\n") or text.startswith("\n"):
            return "\n" + text
        return "\n\n" + text

    async def _project_pal_reply(self, reply: dict[str, Any]) -> None:
        """Project one Pal frame without assuming responses are contiguous."""
        rtype = str(reply.get("type") or "")
        request_id = str(reply.get("request_id") or "")
        if rtype == "text_delta":
            delta = str(reply.get("text") or "")
            if not delta:
                return
            delta = self._apply_segment_break(request_id, delta)
            if request_id.startswith("chat_"):
                self._sm.on_reply_delta()
            await self._start_reply(request_id)
            self._reply_parts.setdefault(request_id, []).append(delta)
            try:
                self._history.append_avatar_delta(request_id, delta)
            except sqlite3.Error:
                pass
            await self.broadcast_chat(delta, event="delta", message_id=request_id)
            return
        if rtype in {
            "interactive_open",
            "interactive_update",
            "interactive_resolve",
            "interactive_expire",
        }:
            interaction = reply.get("interaction")
            if isinstance(interaction, dict):
                await self.broadcast_interaction(
                    interaction,
                    event=rtype.removeprefix("interactive_"),
                    message_id=request_id,
                )
            return
        if rtype == "tagged_message":
            tag = str(reply.get("tag") or "").strip()
            payload = reply.get("payload")
            if tag == "checklist" and isinstance(payload, dict):
                await self.broadcast_tagged_message(
                    tag=tag,
                    text=str(reply.get("text") or ""),
                    payload=payload,
                )
                return
            fallback = str(reply.get("text") or "")
            if fallback:
                await self._start_reply(request_id)
                self._reply_parts.setdefault(request_id, []).append(fallback)
                with contextlib.suppress(sqlite3.Error):
                    self._history.append_avatar_delta(request_id, fallback)
                await self.broadcast_chat(fallback, event="delta", message_id=request_id)
            return
        if rtype in {"tool_call", "op_tool_call"}:
            if request_id.startswith("chat_"):
                self._sm.on_reply_delta()
            self._mark_segment_break(request_id)
            return
        if rtype in {"llm_done", "llm_error", "done", "error"}:
            finish_reason = str(reply.get("finish_reason") or "").lower()
            if rtype in {"llm_done", "done"} and finish_reason in {
                "tool_calls",
                "compact_required",
            }:
                if request_id.startswith("chat_"):
                    self._sm.on_reply_delta()
                self._mark_segment_break(request_id)
                return
            final_text = str(reply.get("final_text") or "")
            existing_text = "".join(self._reply_parts.get(request_id, []))
            if final_text and final_text.startswith(existing_text):
                missing_text = final_text[len(existing_text):]
                if missing_text:
                    await self._start_reply(request_id)
                    self._reply_parts.setdefault(request_id, []).append(missing_text)
                    try:
                        self._history.append_avatar_delta(request_id, missing_text)
                    except sqlite3.Error:
                        pass
                    await self.broadcast_chat(
                        missing_text,
                        event="delta",
                        message_id=request_id,
                    )
            error_text = str(reply.get("error_text") or reply.get("text") or "").strip()
            if rtype in {"llm_error", "error"} and error_text:
                error_text = self._apply_segment_break(request_id, error_text)
                await self._start_reply(request_id)
                self._reply_parts.setdefault(request_id, []).append(error_text)
                try:
                    self._history.append_avatar_delta(request_id, error_text)
                except sqlite3.Error:
                    pass
                await self.broadcast_chat(error_text, event="delta", message_id=request_id)
            self._reply_parts.pop(request_id, None)
            self._segment_break_pending.discard(request_id)
            try:
                self._history.complete_avatar(request_id)
            except sqlite3.Error:
                pass
            chat_reply = request_id.startswith("chat_")
            self._started_replies.discard(request_id)
            if request_id:
                await self.broadcast_chat("", event="done", message_id=request_id)
            other_chat_replies = any(
                active_request_id.startswith("chat_")
                for active_request_id in self._started_replies
            )
            if chat_reply and not other_chat_replies:
                self._sm.on_reply_done()
                await self.broadcast_state("standby")

    async def state_pump(self) -> None:
        """Periodically evaluate the state machine and broadcast changes."""
        while True:
            await asyncio.sleep(THINKING_PROBE_SECONDS)
            self._sm.tick()
            queued = self._queue.pop()
            if queued:
                await self.broadcast_state(str(queued["state"]))


# --------------------------------------------------------------------------- #
# Main entrypoint                                                              #
# --------------------------------------------------------------------------- #

def _force_exit(signum, frame):
    raise SystemExit(0)


async def serve(config: SidecarConfig) -> None:
    signal.signal(signal.SIGTERM, _force_exit)
    signal.signal(signal.SIGINT, _force_exit)

    queue = AvatarStateQueue()
    state_machine = StateMachine(queue, config.idle_to_sleeping_seconds)
    channel = PalChannelClient(config.bridge_socket_path)
    await channel.connect()
    history = ChatHistoryStore(config.data_root / "chat_history.sqlite3")

    loop = asyncio.get_running_loop()

    async def push_external_state(state: str, duration: object = EXPRESSIVE_STATE_SECONDS) -> bool:
        try:
            parsed_duration = float(duration)
        except (TypeError, ValueError):
            parsed_duration = EXPRESSIVE_STATE_SECONDS
        return state_machine.on_external_state(state, duration=parsed_duration)

    manager = ManagerRpcServer(
        manager_socket_path=config.manager_socket_path,
        health_fn=lambda: {"listener_bound": ws_server._connected >= 0, "connected_peers": ws_server._connected, "last_error": ""},
        shutdown_fn=lambda: None,
        state_callback=push_external_state,
        ready_event=asyncio.Event(),
    )

    ws_server = AvatarWebSocketServer(
        state_machine=state_machine,
        state_queue=queue,
        channel=channel,
        history=history,
        loop=loop,
    )

    async with websockets.serve(
        ws_server.handle,
        config.bind_host,
        config.bind_port,
        process_request=serve_client_asset,
    ):
        print(
            f"[desktop_avatar] client + WS listening on {config.bind_host}:{config.bind_port}",
            flush=True,
        )
        tasks = (
            asyncio.create_task(ws_server.state_pump()),
            asyncio.create_task(ws_server.ingress_pump()),
            asyncio.create_task(ws_server.reply_pump()),
            asyncio.create_task(manager.serve()),
        )
        try:
            # A dead reply pump must terminate the sidecar rather than leave a
            # healthy-looking WebSocket listener that can no longer talk to
            # Pal. Provider supervision can then report/recover the failure.
            await asyncio.gather(*tasks)
        except (asyncio.CancelledError, SystemExit):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await channel.close()
            history.close()


if __name__ == "__main__":
    cfg = SidecarConfig(
        runtime_root=Path(os.environ.get("PAL_RUNTIME_ROOT", ".")),
        data_root=Path(os.environ.get("PAL_DATA_ROOT", ".")),
        bridge_socket_path=Path(os.environ.get("PAL_DESKTOP_AVATAR_BRIDGE", "/tmp/desktop_avatar_bridge.sock")),
        manager_socket_path=Path(os.environ.get("PAL_DESKTOP_AVATAR_MANAGER", "/tmp/desktop_avatar_manager.sock")),
        bind_host=os.environ.get("PAL_DESKTOP_AVATAR_HOST", "0.0.0.0"),
        bind_port=int(os.environ.get("PAL_DESKTOP_AVATAR_PORT", "8765")),
    )
    asyncio.run(serve(cfg))
