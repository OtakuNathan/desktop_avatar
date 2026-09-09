# 妹妹的桌面小家（desktop_avatar）

妈妈的桌面上住着一个会动、会睡、会聊天的妹妹（Live2D 小埋），也可以切换成 Pal 的
WebGL 全身机器人。双击角色弹出聊天框，消息通过 WebSocket 进 Pal，回复流式显示，状态会驱动表情和动作。

```
妈妈的电脑                              Pal 主机
┌──────────────────────────┐   WS   ┌──────────────────────────────┐
│ 客户端（ChromeOS 浏览器）    │ :8765  │ desktop_avatar channel provider │
│ ├─ Live2D 小埋 / WebGL Pal │◄─────►│ ├─ runtime.py  端点+sidecar管理 │
│ ├─ 双击弹聊天框（微信式）    │        │ ├─ sidecar.py  WS服务端+状态机  │
│ ├─ 页面+模型均由 Pal 提供    │        │ │   ↕ provider-private socket   │
│ └─ WS 收发消息/状态         │        │ └─ Pal channel → 妹妹(petra)   │
└──────────────────────────┘        └──────────────────────────────┘
```

## 工具工作区

由桌宠发起的 Pal 本体 turn 会在 checklist 下显示工具调用工作区：工具名、
默认折叠的参数、成功／失败／取消状态，以及 `edit_file` / `write_file` 的结构化 diff。
原生 shell 尚在运行时显示 Background 和 session ID；不会把返回 session 当成进程完成。
`call_tool` 显示实际目标工具一次。shell 文件变更不做快照推断。

工作区只保存在 sidecar 内存，网页重连可恢复当前 turn，turn 结束即清空；不写入聊天历史。
最多保留最近 100 次调用，参数预览 8 KiB、diff 64 KiB，超出会标记省略。
明确的密码、token、cookie、验证码等参数字段在显示副本中脱敏；普通文本和 diff 不做秘密扫描。
向上滚动查看时不会被新调用强制拉回底部。该功能适用于 Live2D、Pal 3D 和 SVG 皮肤。

需要配套支持 `tool_activity` 的 Pal 版本，更新 Pal 后重启本体；重新安装／挂载此 channel
并刷新网页以加载新客户端。不支持此回显的旧 Pal 仍可正常聊天，但不会显示工作区。

## 目录结构

```
desktop_avatar/
├── package.py                 # 可复现打包 + 内容校验 + SHA-256
├── install.py                 # 可分别安装 channel / emotion / 两者
├── server/                    # 服务端：Pal channel provider
│   ├── provider.toml          # provider 清单
│   ├── runtime.py             # provider 声明 + endpoint + sidecar 管理
│   └── sidecar.py             # WS 服务端 + 消息桥 + 自治状态机
├── plugin/                    # 配套 show_emotion 工具（不依赖 OLED）
│   ├── plugin.toml
│   ├── runtime.py
│   └── desktop_avatar_emotion_introspection.py
└── client/                    # 客户端（妈妈电脑）
    ├── index.html             # 桌面小家页面
    ├── css/style.css
    ├── js/config.js           # ★ WS 地址配置
    ├── js/main.js             # WS + 聊天 + 状态渲染
    ├── js/pal-webgl-avatar.js # Pal GLB 全身模型、骨骼动作与状态映射
    ├── js/live2d-motion-control.js # 稳定的原生 motion 适配层
    └── assets/model/
        ├── umaru/             # 小埋 Live2D 模型（Cubism2）
        └── pal/               # Pal GLB 模型与美术参考
```

浏览器默认仍加载妹妹皮肤。使用同一 sidecar 打开 `/?skin=pal` 可选择 Pal 的深色主题；
该皮肤用离线 Three.js/WebGL 渲染全身机器人，兼容原有九动作模型和新版具名动作模型，并在新回复开始时播放一次
轻量合成 beep。它不依赖 Cubism、CDN、语音或外部模型服务。beep 使用 Web Audio，不包含音频素材，
首次用户交互前遵守浏览器自动播放限制。

也可以通过 `/?skin=pal2d` 使用无需 GLB 的轻量 SVG 机器人；`/?skin=pal3d` 是 3D 皮肤的别名。
动作映射、thinking/sleeping 定格和表情说明见 [形象文档](client/assets/model/pal/README.md)。

Pal 的 GLB 不进入 provider 仓库或发布包。安装器校验动作后把模型写入 runtime-local、内容寻址的
`<runtime-root>/data/desktop_avatar/skins/pal/<sha256>.glb`，sidecar 通过动态 manifest 暴露带哈希的
URL，浏览器以 `immutable` 缓存一年。模型不变时只下载一次；更新模型会生成新 URL，并清理旧缓存。

## 服务端安装（Pal 主机）

先核验下载包，再解压并运行安装器：

```bash
sha256sum -c pal-desktop-avatar-0.1.13.tar.gz.sha256
tar -xzf pal-desktop-avatar-0.1.13.tar.gz
cd pal-desktop-avatar-0.1.13
python install.py --dry-run --runtime-root ~/.pal --pal-model /path/to/pal.glb
python install.py --runtime-root ~/.pal --pal-model /path/to/pal.glb
```

两个模块也可以独立安装：

```bash
python install.py --runtime-root /path/to/runtime --component all
python install.py --runtime-root /path/to/runtime --component channel --pal-model /path/to/pal.glb
python install.py --runtime-root /path/to/runtime --component emotion
```

更新已有安装时显式加 `--force`。安装器只复制文件，不会操作正在运行的 Pal；随后通过 Pal 的
`channel_provider_rescan` / endpoint attach 与 `plugin_rescan` / `plugin_attach` 生命周期能力热加载。
安装采用逐文件原子替换，保留安装目录中不属于发布包的文件；成功后会生成
`.desktop-avatar-install.json`，记录版本、安装文件和 SHA-256，并立即核验安装结果。
已知由旧版本安装、但已经退役的入口文件会在 `--force` 更新时一并清理。

## 构建发布包

在项目根目录运行：

```bash
python package.py
```

脚本读取 `VERSION` 并检查 channel/plugin manifest 版本一致性，然后在 `dist/` 生成：

```text
pal-desktop-avatar-<version>.tar.gz
pal-desktop-avatar-<version>.tar.gz.sha256
```

归档只接受明确的运行源码、客户端资源和许可证目录，会排除 `dist/`、`__pycache__`、字节码、
运行时数据、外置 Pal GLB 以及仅供开发参考的 Pal 美术图。文件顺序、权限、所有者和时间戳会
规范化，因此相同源码可得到相同 SHA-256。

手动安装等价于：

```bash
# 1. 把 provider 装进 Pal 运行时（将 <runtime-root> 替换为实际 runtime root）
mkdir -p <runtime-root>/channel/providers/desktop_avatar
cp server/{provider.toml,runtime.py,sidecar.py} <runtime-root>/channel/providers/desktop_avatar/
cp -a client <runtime-root>/channel/providers/desktop_avatar/client

# 安装配套的独立 show_emotion 插件
mkdir -p <runtime-root>/plugins/community/desktop_avatar_emotion
cp plugin/{plugin.toml,runtime.py,desktop_avatar_emotion_introspection.py} \
  <runtime-root>/plugins/community/desktop_avatar_emotion/

# 2. 重启 Pal，或分别热加载 channel provider 与 plugin
# 3. 注册 endpoint（Pal 内执行）：
#    desktop_avatar / channel_kind=desktop_avatar / binding_key=<任意唯一键>
#    binding_metadata: bind_host=0.0.0.0, bind_port=8765

# 4. attach 后验证：
#    provider 健康检查应显示 healthy=true, listener_bound=true
```

> 端口默认 8765，可通过 binding_metadata 的 `bind_port` 覆盖。

## 客户端运行（ChromeOS）

无需在 ChromeOS 安装或运行任何程序，也不依赖外网 CDN。用 Chrome 打开：

```text
http://<家里Pal的IP>:8765/
```

页面、Live2D 库、模型和 WebSocket 都通过同一个局域网端口提供。交互方式：

- **双击小埋** → 弹聊天框
- **单击小埋** → 小互动（随机动作）
- 输入文字回车/点发送 → 妹妹回复流式显示
- 双方消息气泡直接渲染 Markdown（流式回复会持续重绘并做 HTML 清理）
- 打开聊天框时只渲染最近 10 轮；向上滚到顶部会按时间继续加载更早的 10 轮
- **清屏**只清当前页面，刷新或重连后记录仍会回来；**清空记录**会永久清空桌宠自己的 SQLite 历史
- 状态徽标：思考中/工作中/睡觉中/开心…

页面采用自适应双区布局：聊天面板随窗口占满左侧可用空间，角色在右侧独立舞台中显示，
两者之间和窗口四周仅保留少量间距且不会重叠。温馨室内背景随页面一起本地提供。
> 打包 Tauri（可选）：`cargo tauri dev` 需要 Rust 工具链；透明窗口配置见
> Tauri 文档（`decorations: false` + `transparent: true`）。

## WS 帧协议（JSON 文本帧，type 字段复用通道）

| type | 方向 | 载荷 |
|---|---|---|
| `chat_message` | 双向 | 客户端只提交文字；sidecar 广播带 `sender/event/message_id` 的权威展示事件 |
| `chat_history` | 服务端→客户端 | 最近/更早的 10 轮记录、未完成气泡、时间游标与 `has_more` |
| `load_chat_history` | 客户端→服务端 | `{type, before:{created_at_us,id}}`，滚到顶部自动发送 |
| `clear_chat_history` | 客户端→服务端 | 永久清空本桌宠端点的历史记录 |
| `chat_history_cleared` | 服务端→客户端 | 清空成功；所有已连接客户端同步清屏 |
| `chat_interaction` | 服务端→客户端 | slash command 的面板文字与按钮 |
| `tagged_message` | 服务端→客户端 | 带语义标签的普通消息；`checklist` 在角色上方原位展示 |
| `interaction_result` | 客户端→服务端 | `{type, interaction_id, button_token}` |
| `avatar_state` | 服务端→客户端 | `{type, state}` standby/sleeping/thinking/working/happy/… |
| `ping` / `pong` | 双向 | 保活 |

状态集合兼容 OLED 表情（standby/sleeping/thinking/working/happy/sad/angry/shock/wink/curious），
并额外提供桌宠专属的 `awkward`（尴尬）、`smirk`（坏笑）、`cheeky`（耍贱），
以及 `excited`、`shy`、`proud`、`confused`、`love`、`panic`、`bored`、
`greeting`、`celebrate` 等有辨识度的动作语义，
客户端将这些语义映射为呼吸、思考摇摆、工作点头、开心跳跃、震惊弹起等轻量动作；
也兼容 OLED 的 `sleepy`/`crying`/`error` 别名，但不依赖 OLED sidecar。单击桌宠会随机触发
一次好奇、眨眼或开心互动，随后回到服务端给出的状态。

`standby` 时客户端会每隔一段随机时间轮播无聊、偷吃薯片、喝可乐、伸懒腰等本地 idle 动作。
这些动作会调用模型自带 motion（默认静音）；turn 开始、流式回复、工具执行或显式 `show_emotion`
状态到达时会立即停止 idle motion，由新状态抢占。

## 联调测试（开发机 localhost）

1. Pal 上启动 provider（endpoint attach 后 sidecar 自动起）
2. 浏览器打开 `http://localhost:8765/`
3. 双击小埋 → 发消息 → 观察妹妹回复 + 状态徽标变化

## 设计要点

- **信道**：channel provider（同 websocket_bridge 模式），provider-private socket，
  不碰 TTY `pal.sock`；回复经 channel 路由自动回到本端点
- **全双工信道**：浏览器 ingress 只提交消息，不等待回复；sidecar 用独立 reader pump 按 request_id
  投影交错输出，因此 active turn 中仍可发送普通插话、`/status` 或 `/interrupt`
- **展示投影**：浏览器只是 renderer；sidecar 的 SQLite 保存用户消息、流式未完成气泡和 tagged
  展示快照，浏览器或 provider 重连后可直接重建当前画面
- **状态机**：sidecar 自治（消息流推断：thinking → working → standby；1h 无消息 → sleeping），
  未来可订阅 turn 事件推送更精细状态
- **通道复用**：WS 帧 type 字段区分消息/状态/保活（老爹钦定）
- **独立历史**：每个 endpoint 在自己的 data root 保存 `chat_history.sqlite3`；普通对话从首个流式片段起按轮更新，
  slash command 面板和按钮回执不写入聊天记录
- **妈妈友好**：零安装（浏览器）、双击即聊、大字体大按钮

## 分发说明

第三方浏览器依赖的许可证已经随包保留，详见 `THIRD_PARTY_NOTICES.md`。当前小埋 Live2D
模型在工作区中没有附带授权信息；公开分发前应替换为有明确再分发许可的模型。
