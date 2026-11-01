import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from pal.channel.contracts import EndpointConfig
from server.runtime import DesktopAvatarEndpoint
from server.sidecar import AvatarWebSocketServer


def test_shared_commands_reach_sidecar_without_becoming_history():
    async def run():
        endpoint = DesktopAvatarEndpoint(endpoint=EndpointConfig("desktop", "desktop_avatar", "fixture"), socket_path=Path("fixture"))
        queue = asyncio.Queue(maxsize=1)
        session = SimpleNamespace(outbound=queue, closed=False, ready_notified=True)
        endpoint.sessions["client"] = session
        queue.put_nowait({"type": "existing"})
        catalog = [{"command": "android_pair", "description": "配对手机"}]
        endpoint.apply_control_catalog({"commands": catalog})
        assert session.avatar_commands_pending
        queue.get_nowait()
        endpoint._flush_command_catalog(session)
        frame = queue.get_nowait()
        assert frame == {"type": "command_catalog", "commands": catalog}
        assert endpoint.is_ephemeral_frame(frame)
        server = object.__new__(AvatarWebSocketServer)
        frames = []
        class Client:
            async def send(self, value): frames.append(json.loads(value))
        server._clients = {Client()}
        assert server._is_transient_reply(frame)
        await server._project_pal_reply(frame)
        assert server._control_commands == catalog and frames == [frame]
        endpoint.apply_control_catalog({"commands": []})
        await server._project_pal_reply(queue.get_nowait())
        assert server._control_commands == []
    asyncio.run(run())
