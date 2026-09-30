from pathlib import Path
import importlib.util

import pytest
from pal.plugins.contracts import PluginBuildContext


def test_emotion_factory_accepts_the_host_build_context(monkeypatch, tmp_path):
    plugin_dir = Path(__file__).parents[1] / "plugin"
    monkeypatch.syspath_prepend(str(plugin_dir))
    spec = importlib.util.spec_from_file_location("emotion_factory_contract", plugin_dir / "runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bundle = module.build_plugin(PluginBuildContext(runtime_root=tmp_path, plugin_dir=plugin_dir))
    assert bundle.plugin_id == "desktop_avatar_emotion"
    with pytest.raises(ValueError, match="plugin_dir"):
        module.build_plugin(PluginBuildContext(runtime_root=tmp_path))
