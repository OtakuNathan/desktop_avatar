from __future__ import annotations

from pal.plugins.contracts import PluginBuildContext

from desktop_avatar_emotion_introspection import register_with_core


def build_plugin(context: PluginBuildContext):
    plugin_dir = context.plugin_dir
    if plugin_dir is None:
        raise ValueError("plugin_dir is required")

    class DesktopAvatarEmotionBundle:
        plugin_id = "desktop_avatar_emotion"
        version = "0.1.13"

        # raii.v1: the plugin host requires start(scope) and rejects a bundle
        # that exposes register_with_core as its own surface. This mirrors the
        # oled_status / st7789_face / eye entrypoints.
        def start(self, scope):
            return register_with_core(scope.context, plugin_dir=plugin_dir)

    return DesktopAvatarEmotionBundle()
