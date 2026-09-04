from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from pal.core.module_registry import MODULE_TIER_DETACHABLE, ModuleHandle
from pal.execution.tool_facade import StrictToolModel, ToolGuidance
from pal.execution.tool_semantics import DIRECT_EXTERNAL_WRITE
from pal.shared import (
    OPERATION_NAMESPACE,
    IntrospectionCall,
    IntrospectionResult,
    RuntimeStatus,
    capability_action,
    capability_node,
)
from pal.shared.result_rendering import render_titled_structured_for_llm


class DesktopAvatarEmotionInput(StrictToolModel):
    emotion: Literal[
        "happy",
        "sad",
        "angry",
        "crying",
        "curious",
        "awkward",
        "smirk",
        "cheeky",
        "excited",
        "shy",
        "proud",
        "confused",
        "love",
        "panic",
        "bored",
        "greeting",
        "celebrate",
        "laugh",
        "clap",
        "agree",
        "complain",
        "dance",
        "snacking",
        "drinking",
        "stretching",
        "shock",
        "sleepy",
        "thinking",
        "wink",
        "error",
        "standby",
        "working",
    ] = Field(description="Semantic emotion or activity state to show on the desktop avatar.")
    duration: float = Field(
        default=1.1,
        ge=0.4,
        le=5.0,
        description="Seconds before an expressive animation resumes the current activity state.",
    )


class DesktopAvatarEmotionOutput(StrictToolModel):
    emotion: str
    endpoint_ids: list[str]
    failures: list[dict[str, str]] = Field(default_factory=list)


@capability_node(
    namespace=OPERATION_NAMESPACE,
    scope="module",
    kind="module",
    source="community:desktop_avatar_emotion",
    target_kind="module",
)
@dataclass
class DesktopAvatarEmotionProvider:
    channel_runtime: Any
    main_context: Any
    module_id: str = "desktop_avatar_emotion"

    def _available_endpoints(self) -> list[Any]:
        return [
            endpoint
            for endpoint in self.channel_runtime.list_endpoints()
            if str(endpoint.endpoint.channel_kind) == "desktop_avatar"
            and endpoint.attached
            and endpoint.enabled
        ]

    def _turn_endpoint_id(self, call: IntrospectionCall) -> str:
        turn_id = str(call.meta.get("turn_id") or "").strip()
        if not turn_id:
            return ""
        try:
            core = self.main_context.require_port("core:core")
            continuation = core.state.active_turns.get(turn_id)
            binding = continuation.delivery_binding
            endpoint = binding.endpoint
        except (AttributeError, KeyError, TypeError):
            return ""
        if str(endpoint.channel_kind) != "desktop_avatar":
            return ""
        return str(endpoint.endpoint_id)

    @staticmethod
    def _display(endpoint: Any, emotion: str, duration: float) -> None:
        display = getattr(endpoint, "show_emotion", None)
        if callable(display):
            display(emotion, duration=duration)
            return

        # Compatibility with an already-mounted provider generation created
        # before show_emotion() became a public endpoint method. The paired
        # channel has always owned this RPC client and sidecar method, so the
        # independently hot-loaded tool can work without rescanning channels.
        rpc_client = getattr(endpoint, "_rpc_client", None)
        if not callable(rpc_client):
            raise RuntimeError("endpoint lacks desktop avatar emotion transport")
        result = rpc_client().request_sync(
            "push_state",
            {"state": emotion, "duration": duration},
        )
        if not bool(result.get("accepted")):
            raise RuntimeError(f"desktop avatar rejected emotion: {emotion}")

    @capability_action(
        namespace=OPERATION_NAMESPACE,
        scope="module",
        action_name="show_emotion",
        aliases=("show_emotion",),
        InputModel=DesktopAvatarEmotionInput,
        OutputModel=DesktopAvatarEmotionOutput,
        guidance=ToolGuidance(
            purpose="Show one semantic emotion or activity animation on attached desktop avatars.",
            use_when="A brief expressive reaction naturally supports the conversation shown in the desktop avatar channel.",
            do_not_use_when="The animation would be repetitive, unrelated, or presented as proof of an internal feeling or runtime fact. Routine thinking and working states are automatic.",
            failure_next_steps="Inspect the desktop avatar channel endpoint and retry only after its sidecar is healthy.",
        ),
        execution=DIRECT_EXTERNAL_WRITE,
        examples=(
            {"emotion": "happy", "duration": 1.1},
            {"emotion": "awkward", "duration": 1.4},
            {"emotion": "smirk", "duration": 1.2},
            {"emotion": "cheeky", "duration": 1.5},
            {"emotion": "dance", "duration": 2.0},
        ),
        metadata={"omit_family_in_canonical": True},
    )
    def show_emotion(self, call: IntrospectionCall) -> IntrospectionResult:
        emotion = str(call.args.get("emotion") or "").strip().lower()
        duration = float(call.args.get("duration", 1.1))
        available = self._available_endpoints()
        turn_endpoint_id = self._turn_endpoint_id(call)
        if turn_endpoint_id:
            targets = [
                endpoint
                for endpoint in available
                if str(endpoint.endpoint.endpoint_id) == turn_endpoint_id
            ]
        elif len(available) == 1:
            targets = available
        elif len(available) > 1:
            payload = {
                "emotion": emotion,
                "endpoint_ids": [],
                "failures": [{
                    "endpoint_id": "",
                    "reason": "multiple desktop avatar endpoints are available outside a desktop avatar turn",
                }],
            }
            return IntrospectionResult(
                status=RuntimeStatus.INVALID,
                text="desktop avatar endpoint is ambiguous",
                structured=payload,
                llm_text=render_titled_structured_for_llm(
                    "Desktop avatar emotion target is ambiguous",
                    payload,
                ),
            )
        else:
            targets = []

        displayed: list[str] = []
        failures: list[dict[str, str]] = []

        for endpoint in targets:
            endpoint_id = str(endpoint.endpoint.endpoint_id)
            try:
                self._display(endpoint, emotion, duration)
            except Exception as exc:
                failures.append({
                    "endpoint_id": endpoint_id,
                    "reason": f"{exc.__class__.__name__}: {exc}",
                })
            else:
                displayed.append(endpoint_id)

        payload = {
            "emotion": emotion,
            "endpoint_ids": displayed,
            "failures": failures,
        }
        if displayed:
            return IntrospectionResult(
                status=RuntimeStatus.OK,
                text=f"desktop avatar emotion displayed: {emotion}",
                structured=payload,
                llm_text=render_titled_structured_for_llm(
                    "Desktop avatar emotion displayed",
                    payload,
                ),
            )
        return IntrospectionResult(
            status=RuntimeStatus.ERROR,
            text="no desktop avatar displayed the emotion",
            structured=payload,
            llm_text=render_titled_structured_for_llm(
                "Desktop avatar emotion was not displayed",
                payload,
            ),
        )


def register_with_core(context, *, plugin_dir: Path) -> ModuleHandle:
    _ = plugin_dir
    channel_runtime = context.port_registry.get("channel:channel")
    if channel_runtime is None:
        raise RuntimeError("desktop avatar emotion plugin requires the channel module")
    provider = DesktopAvatarEmotionProvider(
        channel_runtime=channel_runtime,
        main_context=context,
    )
    handle = ModuleHandle(
        module_id="desktop_avatar_emotion",
        tier=MODULE_TIER_DETACHABLE,
        detachable=True,
        introspection_provider=provider,
    )
    context.register_module(handle)
    return handle
