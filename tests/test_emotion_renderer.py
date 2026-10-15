from pathlib import Path
from types import SimpleNamespace
import importlib

import pytest


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "plugin"))
    return importlib.import_module("desktop_avatar_emotion_introspection")


def endpoint(name, events, *, enabled=True, attached=True, kind="desktop_avatar", failure=False):
    def show_emotion(state):
        events.append((name, state))
        return {"accepted": not failure}
    return SimpleNamespace(endpoint=SimpleNamespace(endpoint_id=name, channel_kind=kind),
                           enabled=enabled, attached=attached, show_emotion=show_emotion)


def test_all_enabled_attached_desktops_receive_once_with_runtime_owned_duration(renderer):
    events = []
    endpoints = [endpoint("one", events), endpoint("two", events),
                 endpoint("disabled", events, enabled=False), endpoint("offline", events, attached=False),
                 endpoint("other", events, kind="telegram")]
    provider = renderer.DesktopAvatarEmotionProvider(SimpleNamespace(list_endpoints=lambda: endpoints))
    receivers = provider.receivers()
    assert len(receivers) == 2
    for receiver in receivers:
        assert "sleeping" in receiver.emotions
        receiver.send("sleeping")
    assert events == [("one", "sleepy"), ("two", "sleepy")]


def test_fallback_rpc_omits_duration_and_rejections_fail(renderer):
    calls = []
    target = SimpleNamespace(_rpc_client=lambda: SimpleNamespace(request_sync=lambda method, args: calls.append((method, args)) or {"accepted": True}))
    renderer.DesktopAvatarEmotionProvider._display(target, "happy")
    assert calls == [("push_state", {"state": "happy"})]
    with pytest.raises(RuntimeError, match="rejected"):
        renderer.DesktopAvatarEmotionProvider._display(endpoint("broken", [], failure=True), "happy")
