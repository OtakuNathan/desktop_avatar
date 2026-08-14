from __future__ import annotations

from pathlib import Path

from desktop_avatar_emotion_introspection import register_with_core


def build_plugin(*, plugin_dir: Path):
    class DesktopAvatarEmotionBundle:
        plugin_id = "desktop_avatar_emotion"
        version = "0.1.4"

        def register_with_core(self, context):
            return register_with_core(context, plugin_dir=plugin_dir)

    return DesktopAvatarEmotionBundle()
