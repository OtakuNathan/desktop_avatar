"""Runtime-root-only channel provider for the Desktop Avatar bridge.

Responsibility: own the desktop-avatar WebSocket sidecar subprocess and the
provider-private Unix channel used to exchange messages with the local Pal
runtime. Mother's desktop-pet client connects over WebSocket (JSON frames with
a ``type`` field), and the sidecar bridges those frames to the provider-private
channel socket so ordinary channel routing (including replies back to this
endpoint) works without touching the TTY ``pal.sock``.

This provider is loaded as a runtime-root provider via ``provider.toml`` +
``build_channel_provider`` and discovered by the channel provider manager
(installation into ``<runtime_root>/channel/providers/desktop_avatar/``).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pal.channel.channel_endpoint_queue_base import ChannelEndpointQueueBase
from pal.channel.contracts import (
    ChannelDeliveryError,
    ChannelMessage,
    ChannelMessageReceipt,
    ChannelStreamUpdate,
    EndpointConfig,
)
from pal.channel.endpoints import SocketChannelEndpoint
from pal.channel.models import ChannelEndpointModel
from pal.channel.provider_manager import (
    ChannelProvider,
    ChannelProviderContext,
    commit_channel_endpoint_attach,
    commit_channel_endpoint_detach,
)
from pal.foundation.sidecar import (
    SidecarEndpoint,
    SidecarRpcClient,
    SidecarRpcError,
    cleanup_sidecar_endpoint,
    python_subprocess_env,
)
from pal.shared import ChannelStreamUpdateKind, IntrospectionResult, RuntimeStatus
from pal.shared.result_rendering import render_titled_structured_for_llm

logger = logging.getLogger(__name__)

PROVIDER_ID = "desktop_avatar"
ENDPOINT_TYPE = "desktop_avatar"
SIDECAR_NAME = "desktop_avatar"

# Environment variable used to hand the serialized ``SidecarConfig`` to the
# child process. The child reconstructs the config and runs ``sidecar.serve``.
_CONFIG_ENV = "PAL_DESKTOP_AVATAR_CONFIG"

# Default WebSocket listen port (fixed for the mother's client; override via
# binding metadata ``bind_port``).
DEFAULT_BIND_PORT = 8765
DEFAULT_BIND_HOST = "0.0.0.0"
DESKTOP_AVATAR_STATES = frozenset({
    "standby", "sleeping", "sleepy", "thinking", "working",
    "happy", "sad", "angry", "crying", "curious", "shock", "wink", "error",
    "awkward", "smirk", "cheeky",
    "excited", "shy", "proud", "confused", "love", "panic", "bored",
    "greeting", "celebrate", "embarrassed", "smug", "playful", "surprised", "wave",
    "snacking", "drinking", "stretching", "snack", "drink", "stretch",
})

# Bootstrap executed inside the sidecar subprocess. The provider directory is
# placed on PYTHONPATH; the sidecar module declares ``serve(SidecarConfig)``.
_SIDECAR_BOOTSTRAP = (
    "import asyncio, json, os, pathlib\n"
    "from pal.foundation.service_logging import configure_process_logging\n"
    "configure_process_logging(component='pal.channel.providers.desktop_avatar.sidecar')\n"
    "from sidecar import serve, SidecarConfig\n"
    "payload = json.loads(os.environ['PAL_DESKTOP_AVATAR_CONFIG'])\n"
    "payload['runtime_root'] = pathlib.Path(payload['runtime_root'])\n"
    "payload['data_root'] = pathlib.Path(payload['data_root'])\n"
    "payload['bridge_socket_path'] = pathlib.Path(payload['bridge_socket_path'])\n"
    "payload['manager_socket_path'] = pathlib.Path(payload['manager_socket_path'])\n"
    "asyncio.run(serve(SidecarConfig(**payload)))\n"
)

# Directory containing this module. Resolved at import time so subprocess spawns
# work both for in-repo use and after the provider is copied into a runtime root.
PROVIDER_DIR = Path(__file__).resolve().parent


@dataclass
class DesktopAvatarEndpoint(SocketChannelEndpoint):
    """A real channel endpoint backed by a provider-private Unix socket.

    The inherited framed-session plumbing is shared with the ordinary socket
    endpoint, but the path and endpoint identity are independent, so mother's
    messages and their replies are routed without touching ``pal.sock``.
    """

    runtime_root: Any = None
    data_root: Path | None = None
    binding_metadata: dict[str, Any] = field(default_factory=dict)
    # Lifecycle tunables (overridable per-instance, e.g. in tests).
    startup_probe_seconds: float = 5.0
    shutdown_rpc_seconds: float = 3.0
    shutdown_wait_seconds: float = 2.0
    rpc_timeout_seconds: float = 3.0
    _process: Any = field(default=None, init=False, repr=False)
    _startup_error: str = field(default="", init=False, repr=False)
    _sidecar_command_override: tuple[str, ...] | None = field(default=None, init=False, repr=False)

    async def start_async(self) -> None:
        """Bind the private channel socket, then spawn and supervise the sidecar."""
        if (
            self._process is not None
            and self._process.poll() is None
            and self.server is not None
        ):
            return
        if not self.runtime_root or not self.socket_path:
            self._startup_error = "desktop_avatar endpoint missing runtime_root or bridge_socket_path"
            return
        self._startup_error = ""
        if self._process is not None and self._process.poll() is None:
            _force_terminate(self._process)
        self._process = None
        try:
            await super().start_async()
            process = self._spawn_sidecar()
        except Exception as exc:  # pragma: no cover - defensive spawn guard
            self._startup_error = f"sidecar spawn failed: {exc.__class__.__name__}: {exc}"
            self._process = None
            logger.exception("desktop_avatar sidecar failed to spawn")
            with contextlib.suppress(Exception):
                await super().stop_async()
            return
        self._process = process
        await self._await_sidecar_ready(process)
        if self._startup_error:
            if process.poll() is None:
                _force_terminate(process)
            self._process = None
            with contextlib.suppress(Exception):
                await cleanup_sidecar_endpoint(self._manager_endpoint())
            with contextlib.suppress(Exception):
                await super().stop_async()

    async def stop_async(self) -> None:
        """Cleanly stop the sidecar and release both provider-owned sockets."""
        process = self._process
        if process is not None:
            loop = asyncio.get_running_loop()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    self._rpc_client().request("shutdown"),
                    timeout=self.shutdown_rpc_seconds,
                )
            exited = await self._await_exit(process, loop, self.shutdown_wait_seconds)
            if not exited:
                _force_terminate(process)
        self._process = None
        with contextlib.suppress(Exception):
            await cleanup_sidecar_endpoint(self._manager_endpoint())
        await super().stop_async()

    def send_status(self, response_handle: Any, kind: str, payload: dict[str, Any]) -> None:
        """Project Pal turn hooks into the avatar's persistent activity state."""

        state = {
            "typing_start": "thinking",
            "working_stop": "standby",
        }.get(str(kind or ""))
        if state:
            with contextlib.suppress(Exception):
                self.show_emotion(state, request_timeout_seconds=0.35)
        super().send_status(response_handle, kind, payload)

    def send_channel_message(self, response_handle: Any, message: ChannelMessage) -> None:
        if message.tag != "checklist":
            super().send_channel_message(response_handle, message)
            return
        self._send_tagged_message(response_handle, message)

    def send_stream_update(self, response_handle: Any, update: ChannelStreamUpdate) -> None:
        if update.kind == ChannelStreamUpdateKind.MESSAGE:
            message = update.message or ChannelMessage(text=update.text)
            if message.tag == "checklist":
                self._send_tagged_message(response_handle, message)
                return
        super().send_stream_update(response_handle, update)

    def _send_tagged_message(self, response_handle: Any, message: ChannelMessage) -> None:
        session = self._require_session(response_handle)
        session.outbound.put_nowait(
            {
                "type": "tagged_message",
                "request_id": str(response_handle.reply_target.get("request_id") or ""),
                "tag": str(message.tag or ""),
                "text": message.text,
                "payload": dict(message.payload),
            }
        )

    def show_emotion(
        self,
        emotion: str,
        *,
        duration: float = 1.1,
        request_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Push one semantic state directly to this endpoint's avatar sidecar."""
        state = str(emotion or "").strip().lower()
        if state not in DESKTOP_AVATAR_STATES:
            raise ValueError(f"unsupported desktop avatar emotion: {state}")
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError("desktop avatar sidecar is not running")
        result = self._rpc_client(
            request_timeout_seconds=request_timeout_seconds,
        ).request_sync(
            "push_state",
            {"state": state, "duration": float(duration)},
        )
        if not bool(result.get("accepted")):
            raise RuntimeError(f"desktop avatar rejected emotion: {state}")
        return dict(result)

    def inspect_health(self) -> dict[str, Any]:
        """Report sidecar process and connection health."""
        process = self._process
        process_running = process is not None and process.poll() is None
        health: dict[str, Any] = {
            "endpoint_id": self.endpoint.endpoint_id,
            "process_running": process_running,
            "channel_socket_bound": self.server is not None,
            "channel_socket_path": str(self.socket_path or ""),
            "listener_bound": False,
            "connected_clients": 0,
            "bind_host": _clean_str(self.binding_metadata.get("bind_host")) or DEFAULT_BIND_HOST,
            "bind_port": _as_int(self.binding_metadata.get("bind_port"), DEFAULT_BIND_PORT),
            "last_error": self._startup_error,
            "healthy": False,
        }
        if not process_running:
            if not health["last_error"] and process is not None:
                health["last_error"] = _exit_reason(process)
            return health
        try:
            result = self._rpc_client().request_sync("health")
        except Exception as exc:
            health["last_error"] = f"health probe failed: {exc.__class__.__name__}"
            return health
        health["listener_bound"] = bool(result.get("listener_bound"))
        health["connected_clients"] = int(result.get("connected_peers") or 0)
        health["last_error"] = str(result.get("last_error") or "")
        health["healthy"] = bool(health["listener_bound"] and health["channel_socket_bound"])
        return health

    # -- private sidecar supervision ----------------------------------------

    def _manager_endpoint(self) -> SidecarEndpoint:
        data_root = (
            Path(self.data_root)
            if self.data_root is not None
            else Path(str(self.socket_path)).parent
        )
        return SidecarEndpoint(
            runtime_root=Path(str(self.runtime_root)),
            name=SIDECAR_NAME,
            runtime_dir_override=data_root,
        )

    def _rpc_client(self, *, request_timeout_seconds: float | None = None) -> SidecarRpcClient:
        return SidecarRpcClient(
            endpoint=self._manager_endpoint(),
            request_timeout_seconds=(
                self.rpc_timeout_seconds
                if request_timeout_seconds is None
                else request_timeout_seconds
            ),
        )

    def _sidecar_command(self) -> list[str]:
        if self._sidecar_command_override:
            return list(self._sidecar_command_override)
        return [sys.executable, "-c", _SIDECAR_BOOTSTRAP]

    def _sidecar_config_payload(self) -> dict[str, Any]:
        metadata = dict(self.binding_metadata or {})
        data_root = (
            Path(self.data_root)
            if self.data_root is not None
            else Path(str(self.socket_path)).parent
        )
        return {
            "runtime_root": str(Path(str(self.runtime_root))),
            "data_root": str(data_root),
            "bridge_socket_path": str(Path(str(self.socket_path))),
            "manager_socket_path": str(self._manager_endpoint().socket_path),
            "bind_host": _clean_str(metadata.get("bind_host")) or DEFAULT_BIND_HOST,
            "bind_port": _as_int(metadata.get("bind_port"), DEFAULT_BIND_PORT),
            "idle_to_sleeping_seconds": _as_float(metadata.get("idle_to_sleeping_seconds"), 3600.0),
        }

    def _spawn_sidecar(self) -> subprocess.Popen[bytes]:
        env = python_subprocess_env()
        existing_path = [
            entry for entry in str(env.get("PYTHONPATH") or "").split(os.pathsep) if entry
        ]
        provider_dir = str(PROVIDER_DIR)
        if provider_dir not in existing_path:
            env["PYTHONPATH"] = os.pathsep.join([provider_dir, *existing_path])
        env[_CONFIG_ENV] = json.dumps(self._sidecar_config_payload())
        runtime_dir = self._manager_endpoint().runtime_dir
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return subprocess.Popen(
            self._sidecar_command(),
            env=env,
            cwd=provider_dir,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    async def _await_sidecar_ready(self, process: subprocess.Popen[bytes]) -> None:
        socket_path = self._manager_endpoint().socket_path
        deadline = time.monotonic() + self.startup_probe_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._startup_error = _exit_reason(process)
                return
            if socket_path.exists():
                return
            await asyncio.sleep(0.1)

    async def _await_exit(
        self,
        process: subprocess.Popen[bytes],
        loop: asyncio.AbstractEventLoop,
        timeout: float,
    ) -> bool:
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, process.wait),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            return process.poll() is not None


class DesktopAvatarProvider:
    """Custom ChannelProvider owning the desktop-avatar sidecar lifecycle."""

    provider_id: str = PROVIDER_ID
    endpoint_types: tuple[str, ...] = (ENDPOINT_TYPE,)
    reload_modules: tuple[str, ...] = ("runtime", "sidecar")

    def create_endpoint(
        self,
        record: ChannelEndpointModel,
        context: ChannelProviderContext,
    ) -> ChannelEndpointQueueBase | None:
        if str(record.channel_kind or "").strip() != ENDPOINT_TYPE:
            return None
        runtime_root = Path(str(context.runtime_root))
        data_root = context.endpoint_data_root(str(record.endpoint_id))
        endpoint = DesktopAvatarEndpoint(
            endpoint=EndpointConfig(
                endpoint_id=str(record.endpoint_id),
                channel_kind=str(record.channel_kind),
                binding_key=str(record.binding_key),
                send_policy=dict(record.send_policy_blob or {}),
            ),
            socket_path=data_root / "channel.sock",
        )
        endpoint.runtime_root = runtime_root
        endpoint.data_root = data_root
        endpoint.binding_metadata = dict(record.binding_metadata or {})
        endpoint.enabled = bool(record.enabled)
        endpoint.attached = record.detached_at is None
        endpoint.paired = True
        return endpoint

    def attach_endpoint(self, endpoint_id: str, context: ChannelProviderContext) -> IntrospectionResult:
        record = context.repository.get(endpoint_id)
        if record is None:
            return _not_found(endpoint_id)
        endpoint = self.create_endpoint(record, context)
        if endpoint is None:
            return _provider_missing(endpoint_id, str(record.channel_kind))
        _preserve_state(context.runtime.get_endpoint(endpoint_id), endpoint)
        endpoint.attached = True
        record = commit_channel_endpoint_attach(endpoint_id, endpoint, context)
        return _ok(
            "Desktop avatar endpoint attached",
            {
                "endpoint_id": endpoint_id,
                "endpoint_type": record.channel_kind,
                "provider_id": self.provider_id,
                "reload_modules": list(self.reload_modules),
                "attached": True,
                "enabled": bool(endpoint.enabled),
                "bind_host": _clean_str(endpoint.binding_metadata.get("bind_host")) or DEFAULT_BIND_HOST,
                "bind_port": _as_int(endpoint.binding_metadata.get("bind_port"), DEFAULT_BIND_PORT),
            },
        )

    def detach_endpoint(self, endpoint_id: str, context: ChannelProviderContext) -> IntrospectionResult:
        endpoint = context.runtime.get_endpoint(endpoint_id)
        record = context.repository.get(endpoint_id)
        if record is None and endpoint is None:
            return _not_found(endpoint_id)
        record, endpoint, removed = commit_channel_endpoint_detach(endpoint_id, context)
        endpoint_type = _endpoint_type_of(record, endpoint)
        return _ok(
            "Desktop avatar endpoint detached",
            {
                "endpoint_id": endpoint_id,
                "endpoint_type": endpoint_type,
                "provider_id": self.provider_id,
                "attached": False,
                "removed_runtime_endpoint": bool(removed),
            },
        )

    def restart_endpoint(self, endpoint_id: str, context: ChannelProviderContext) -> IntrospectionResult:
        record = context.repository.get(endpoint_id)
        if record is None:
            return _not_found(endpoint_id)
        _drop_module_cache(self.reload_modules)
        endpoint = self.create_endpoint(record, context)
        if endpoint is None:
            return _provider_missing(endpoint_id, str(record.channel_kind))
        _preserve_state(context.runtime.get_endpoint(endpoint_id), endpoint)
        context.runtime.replace_endpoint(endpoint)
        return _ok(
            "Desktop avatar endpoint restarted",
            {
                "endpoint_id": endpoint_id,
                "endpoint_type": record.channel_kind,
                "provider_id": self.provider_id,
                "reload_modules": list(self.reload_modules),
                "attached": bool(endpoint.attached),
                "enabled": bool(endpoint.enabled),
            },
        )

    def inspect_endpoint(self, endpoint_id: str, context: ChannelProviderContext) -> IntrospectionResult:
        record = context.repository.get(endpoint_id)
        endpoint = context.runtime.get_endpoint(endpoint_id)
        if record is None and endpoint is None:
            return _not_found(endpoint_id)
        payload = _snapshot(endpoint_id, record, endpoint)
        payload["provider_id"] = self.provider_id
        return _ok("Desktop avatar endpoint snapshot", payload)

    def inspect_health(self, endpoint_id: str, context: ChannelProviderContext) -> IntrospectionResult:
        record = context.repository.get(endpoint_id)
        endpoint = context.runtime.get_endpoint(endpoint_id)
        if record is None and endpoint is None:
            return _not_found(endpoint_id)
        if endpoint is None:
            payload = {
                "endpoint_id": endpoint_id,
                "provider_id": self.provider_id,
                "attached": record.detached_at is None if record is not None else False,
                "enabled": bool(record.enabled) if record is not None else False,
                "healthy": False,
                "reason": "runtime_endpoint_missing",
            }
            return _ok("Desktop avatar health", payload)
        payload = _sanitize(dict(endpoint.inspect_health()))
        payload.setdefault("endpoint_id", endpoint_id)
        payload.setdefault("provider_id", self.provider_id)
        payload.setdefault("attached", bool(endpoint.attached))
        payload.setdefault("enabled", bool(endpoint.enabled))
        return _ok("Desktop avatar health", payload)


def build_channel_provider(context: Any) -> ChannelProvider:
    """Runtime-root provider entrypoint consumed by ChannelEndpointProviderManager."""
    _ = context
    return DesktopAvatarProvider()


# -- private provider helpers -------------------------------------------------


def _ok(text: str, payload: dict[str, Any]) -> IntrospectionResult:
    return IntrospectionResult(
        status=RuntimeStatus.OK,
        text=text,
        structured=payload,
        llm_text=render_titled_structured_for_llm(text, payload),
    )


def _not_found(endpoint_id: str) -> IntrospectionResult:
    return IntrospectionResult(
        status=RuntimeStatus.NOT_FOUND,
        text="channel endpoint not found",
        structured={"endpoint_id": endpoint_id},
        llm_text="channel endpoint not found",
    )


def _provider_missing(endpoint_id: str, endpoint_type: str) -> IntrospectionResult:
    return IntrospectionResult(
        status=RuntimeStatus.NOT_FOUND,
        text="channel provider not found",
        structured={
            "endpoint_id": endpoint_id,
            "endpoint_type": endpoint_type,
            "channel_kind": endpoint_type,
        },
        llm_text="channel provider not found",
    )


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    for key in ("token", "secret", "bot_token", "password"):
        sanitized.pop(key, None)
    return sanitized


def _preserve_state(
    old_endpoint: ChannelEndpointQueueBase | None,
    new_endpoint: ChannelEndpointQueueBase,
) -> None:
    if old_endpoint is None or old_endpoint is new_endpoint:
        return
    if getattr(old_endpoint, "paired", False):
        new_endpoint.paired = True
    pairing_metadata = dict(getattr(old_endpoint, "pairing_metadata", {}) or {})
    if pairing_metadata and hasattr(new_endpoint, "pairing_metadata"):
        new_endpoint.pairing_metadata.update(pairing_metadata)


def _drop_module_cache(prefixes: tuple[str, ...]) -> None:
    clean = tuple(dict.fromkeys(str(prefix).strip() for prefix in prefixes if str(prefix).strip()))
    if not clean:
        return
    importlib.invalidate_caches()
    for module_name in list(sys.modules):
        if any(module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in clean):
            sys.modules.pop(module_name, None)


def _snapshot(
    endpoint_id: str,
    record: ChannelEndpointModel | None,
    endpoint: ChannelEndpointQueueBase | None,
) -> dict[str, Any]:
    endpoint_type = _endpoint_type_of(record, endpoint)
    binding_key = (
        record.binding_key
        if record is not None
        else endpoint.endpoint.binding_key
        if endpoint is not None
        else ""
    )
    enabled = (
        bool(record.enabled)
        if record is not None
        else bool(endpoint.enabled)
        if endpoint is not None
        else False
    )
    attached = (
        bool(endpoint.attached)
        if endpoint is not None
        else record.detached_at is None
        if record is not None
        else False
    )
    return {
        "endpoint_id": endpoint_id,
        "endpoint_type": endpoint_type,
        "channel_kind": endpoint_type,
        "binding_key": binding_key,
        "enabled": enabled,
        "attached": attached,
        "paired": bool(getattr(endpoint, "paired", False)) if endpoint is not None else False,
        "runtime_endpoint_present": endpoint is not None,
    }


def _endpoint_type_of(
    record: ChannelEndpointModel | None,
    endpoint: ChannelEndpointQueueBase | None,
) -> str:
    if record is not None:
        return str(record.channel_kind)
    if endpoint is not None:
        return endpoint.endpoint.channel_kind
    return ENDPOINT_TYPE


def _exit_reason(process: subprocess.Popen[bytes]) -> str:
    code = process.returncode
    return f"sidecar process exited with code {code}"


def _force_terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        process_group = os.getpgid(process.pid)
    except (OSError, ProcessLookupError):
        process_group = 0
    owns_group = bool(process_group) and process_group == process.pid
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if process.poll() is not None:
            break
        with contextlib.suppress(ProcessLookupError, OSError):
            if owns_group:
                os.killpg(process_group, sig)
            elif sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            continue
        break


def _clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "PROVIDER_ID",
    "ENDPOINT_TYPE",
    "DesktopAvatarEndpoint",
    "DesktopAvatarProvider",
    "build_channel_provider",
]
