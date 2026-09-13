# desktop_avatar 开发与更新

这是独立于 Pal 的桌宠仓库：`server/` 是 channel provider，`client/` 是浏览器界面，`plugin/` 是独立 emotion 插件。维护 Pal 集成时参考同级 `../Pal/AGENTS.md` 和 `../Pal/src/pal/skill/builtin_skills.py` 的维护、channel provider、插件开发手册。

## 安装与热重载

- 确认实际 runtime root，不把 `~/.pal` 当作所有实例的固定位置。
- 更新前比较源码与安装目录，保留运行目录中的独立修改。只改 channel 时用 `python install.py --runtime-root <root> --component channel --force`，不要顺便覆盖 emotion 插件。
- 安装器只复制并校验文件。已有 provider 的代码更新用 `channel_reload_provider(provider_id="desktop_avatar")` 激活；`channel_restart_endpoint` 只重建连接，不替换 provider 代码。新 provider 使用 rescan/attach 路径。
- emotion 插件更新后用 `plugin_attach` 重载其 generation；有 manifest 变更时先 rescan。不要因“插件是 builtin”就默认重启 Pal。
- 热重载会短暂重建连接；检查生命周期返回值、endpoint health 和 HTTP 资源，再提示用户刷新浏览器。不要把安装完成当作热重载完成。
- Pal 正忙时不追加激活消息、不强制中断；记录已安装和待确认的激活状态。

## 工具活动与验证

工具活动是临时执行展示，回合结束必须清空，不保留成聊天历史。排查漏记录时检查 Pal 的事件产生、队列和调用标识，再检查 provider、sidecar projection 与浏览器，避免只改 UI 掩盖传递问题。

工具参数按文本安全渲染，不执行模型输出的 HTML。保持上游脱敏、截断标识、展开状态和 diff 显示；命令字符串应展示真实换行，嵌套对象应可读。

相关测试：`tests/test_tool_activity.py`、`tests/test_tool_workspace_browser.py`、`tests/test_duplex_sidecar.py`、`tests/test_runtime_lifecycle.py`。安装变更运行 `tests/test_installer.py`。浏览器测试依赖 Playwright Chromium，缺失导致 skip 时明确报告。完整本地测试可用 `python -m pytest -q`；发布包可用 `python package.py --dist-dir <directory>` 检查。
