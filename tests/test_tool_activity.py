import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from pal.channel.contracts import EndpointConfig, ResponseHandle
from server.runtime import DesktopAvatarEndpoint
from server.sidecar import AvatarWebSocketServer
from server.tool_activity import ToolActivityProjection
from install import channel_files


def test_projection_lifecycle_late_events_and_bounded_reconnect():
    state = ToolActivityProjection()
    assert state.apply({'action':'call','turn_id':'old','call_id':'late'}) is None
    state.apply({'action':'begin','turn_id':'a'})
    for i in range(105):
        state.apply({'action':'call','turn_id':'a','call_id':str(i),'status':'running'})
    assert len(state.calls) == 100 and state.omitted == 5
    state.apply({'action':'call','turn_id':'a','call_id':'104','status':'succeeded'})
    assert state.frames()[-1]['payload']['status'] == 'succeeded'
    state.apply({'action':'begin','turn_id':'b'})
    assert state.apply({'action':'end','turn_id':'a'}) is None
    assert state.turn_id == 'b'
    state.apply({'action':'end','turn_id':'b'})
    assert state.frames() == []
    assert state.apply({'action':'call','turn_id':'b','call_id':'late'}) is None


def test_endpoint_optional_frames_drop_when_full_and_install_contains_module(tmp_path):
    endpoint = DesktopAvatarEndpoint(endpoint=EndpointConfig('desktop','desktop_avatar','desktop.sock'),socket_path=Path('desktop.sock'))
    queue = asyncio.Queue(maxsize=100)
    endpoint.sessions['s'] = SimpleNamespace(outbound=queue,closed=False,ready_notified=True,inflight_payload=None,delivery_ack_waiters={})
    handle = ResponseHandle(endpoint_id='desktop',reply_target={'session_id':'s','request_id':'request'})
    payload={'action':'begin','turn_id':'a'}
    endpoint.send_status(handle,'tool_activity',payload)
    assert queue.get_nowait() == {'type':'tool_activity','request_id':'request','payload':payload}
    for _ in range(100): queue.put_nowait({})
    endpoint.send_status(handle,'tool_activity',payload)
    assert queue.qsize() == 100
    _, files = channel_files(tmp_path)
    assert any(f.relative_destination=='tool_activity.py' for f in files)


def test_sidecar_activity_is_transient_and_never_uses_history():
    async def run():
        server=object.__new__(AvatarWebSocketServer)
        server._tool_activity=ToolActivityProjection()
        frames=[]
        class Client:
            async def send(self,frame): frames.append(json.loads(frame))
        server._clients={Client()}
        # No history object: this path must not touch SQLite or chat assembly.
        reply={'type':'tool_activity','payload':{'action':'begin','turn_id':'a'}}
        assert server._is_transient_reply(reply)
        await server._project_pal_reply(reply)
        assert frames[-1]['type']=='tool_activity'
        assert frames[-1]['payload']['action']=='begin'
        await server._project_pal_reply({'type':'tool_activity','payload':{'action':'end','turn_id':'a'}})
        assert server._tool_activity.frames()==[]
    asyncio.run(run())


def test_real_channel_router_to_provider_and_sidecar():
    from pal.channel.runtime import ChannelRuntime
    from pal.channel.tool_activity import ToolActivityRouter
    async def run():
        channel=ChannelRuntime()
        endpoint=DesktopAvatarEndpoint(endpoint=EndpointConfig('desktop','desktop_avatar','desktop.sock'),socket_path=Path('desktop.sock'))
        queue=asyncio.Queue()
        endpoint.sessions['s']=SimpleNamespace(outbound=queue,closed=False,ready_notified=True,inflight_payload=None,delivery_ack_waiters={})
        channel.register_endpoint(endpoint)
        router=ToolActivityRouter(channel)
        router('turn.start',{'turn_id':'a','endpoint_id':'desktop','reply_target':{'session_id':'s','request_id':'r'}})
        channel.flush_endpoint_status('desktop')
        begin=queue.get_nowait()
        sink=router.open_sink('a')
        sink({'action':'call','turn_id':'a','call_id':'1','tool':'read_file','arguments':'{}','status':'running'})
        channel.flush_endpoint_status('desktop')
        call=queue.get_nowait()
        server=object.__new__(AvatarWebSocketServer)
        server._tool_activity=ToolActivityProjection()
        server._clients=set()
        await server._project_pal_reply(begin)
        await server._project_pal_reply(call)
        assert server._tool_activity.calls['1']['tool']=='read_file'
        router('turn.end',{'turn_id':'a'})
        channel.flush_endpoint_status('desktop')
        await server._project_pal_reply(queue.get_nowait())
        assert server._tool_activity.frames()==[]
    asyncio.run(run())


def test_end_bypasses_optional_activity_limit():
    endpoint = DesktopAvatarEndpoint(endpoint=EndpointConfig('desktop','desktop_avatar','desktop.sock'),socket_path=Path('desktop.sock'))
    queue = asyncio.Queue(maxsize=256)
    endpoint.sessions['s'] = SimpleNamespace(outbound=queue, closed=False)
    for _ in range(100):
        queue.put_nowait({'type': 'text_delta'})
    handle = ResponseHandle(endpoint_id='desktop', reply_target={'session_id':'s','request_id':'r'})
    endpoint.send_status(handle, 'tool_activity', {'action':'call','turn_id':'a'})
    assert queue.qsize() == 100
    endpoint.send_status(handle, 'tool_activity', {'action':'end','turn_id':'a'})
    assert queue.qsize() == 101
    for _ in range(100):
        queue.get_nowait()
    assert queue.get_nowait()['payload']['action'] == 'end'
