"""Desktop renderer contribution; the independent emotion plugin owns the tool."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pal.core.module_registry import MODULE_TIER_DETACHABLE, ModuleHandle
from pal.emotion import EmotionReceiver


EMOTIONS = ('happy', 'sad', 'angry', 'crying', 'curious', 'awkward', 'smirk', 'cheeky', 'excited', 'shy', 'proud', 'confused', 'love', 'panic', 'bored', 'gloomy', 'greeting', 'celebrate', 'laugh', 'clap', 'agree', 'complain', 'snacking', 'drinking', 'stretching', 'shock', 'sleepy', 'thinking', 'wink', 'error', 'standby', 'working')
ALIASES = {"sleeping": "sleepy"}
SUPPORTED_EMOTIONS = frozenset(EMOTIONS) | frozenset(ALIASES)


@dataclass
class DesktopAvatarEmotionProvider:
    channel_runtime: Any

    def _available_endpoints(self) -> list[Any]:
        return [endpoint for endpoint in self.channel_runtime.list_endpoints()
                if str(endpoint.endpoint.channel_kind) == "desktop_avatar"
                and endpoint.attached and endpoint.enabled]

    @staticmethod
    def _display(endpoint: Any, emotion: str) -> None:
        state = ALIASES.get(emotion, emotion)
        display = getattr(endpoint, "show_emotion", None)
        if callable(display):
            result = display(state)
            if result is False or isinstance(result, dict) and result.get("accepted") is False:
                raise RuntimeError("Desktop avatar rejected the emotion")
            return
        rpc_client = getattr(endpoint, "_rpc_client", None)
        if not callable(rpc_client):
            raise RuntimeError("Desktop avatar emotion transport unavailable")
        result = rpc_client().request_sync("push_state", {"state": state})
        if not bool(result.get("accepted")):
            raise RuntimeError("Desktop avatar rejected the emotion")

    def receivers(self) -> list[EmotionReceiver]:
        return [EmotionReceiver(
            "desktop_avatar:" + str(endpoint.endpoint.endpoint_id), SUPPORTED_EMOTIONS,
            lambda emotion, target=endpoint: self._display(target, emotion))
            for endpoint in self._available_endpoints()]


def register_with_core(context, *, plugin_dir: Path, scope) -> ModuleHandle:
    _ = plugin_dir
    channel_runtime = context.require_port("channel:channel")
    registry = context.require_port("emotion:emotion")
    provider = DesktopAvatarEmotionProvider(channel_runtime)
    handle = ModuleHandle(module_id="desktop_avatar_emotion", tier=MODULE_TIER_DETACHABLE,
                          detachable=True, ports={"renderer": provider})
    context.register_module(handle)
    registry.register(scope, "desktop_avatar", SUPPORTED_EMOTIONS, provider.receivers)
    return handle
