"""Exercise the default renderer through real page and WebSocket events."""
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest


def test_raster_channel_lifecycle_and_preview(tmp_path):
    api = pytest.importorskip('playwright.sync_api')
    root = Path(__file__).resolve().parents[1] / 'client'
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with api.sync_playwright() as p:
            if not Path(p.chromium.executable_path).exists():
                pytest.skip('Playwright Chromium is not installed')
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            try:
                page = browser.new_page(viewport={'width': 1280, 'height': 850})
                errors, sent, sockets, requests = [], [], [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append(request.url))
                def connect(socket):
                    sockets.append(socket)
                    socket.on_message(lambda message: sent.append(json.loads(message)))
                page.route_web_socket('**', connect)
                url = f'http://127.0.0.1:{server.server_port}'
                page.goto(url)
                page.wait_for_function('window.PalRasterAvatar?.motionReady()')
                assert not any('.glb' in path or 'three.module' in path for path in requests)
                def state(name):
                    sockets[-1].send(json.dumps({'type': 'avatar_state', 'state': name}))
                    page.wait_for_function('(s)=>document.querySelector("#pal-raster-widget").dataset.avatarState === s', arg=name)
                state('sleeping')
                assert page.locator('#particles text').count() == 3
                state('shock')
                page.wait_for_timeout(1400)
                assert {'type': 'avatar_action_finished', 'state': 'shock'} in sent
                state('thinking')
                page.wait_for_timeout(1200)
                page.screenshot(path=str(tmp_path / 'raster-thinking.png'))
                state('confused')
                page.wait_for_timeout(250)
                state('working')
                page.wait_for_timeout(4300)
                assert not any(frame.get('state') == 'confused' for frame in sent)
                assert page.locator('.eye-overlay').get_attribute('data-state') == 'working'
                sockets[-1].send(json.dumps({'type': 'tool_activity', 'payload': {'action': 'begin', 'turn_id': 'test'}}))
                sockets[-1].send(json.dumps({'type': 'tool_activity', 'payload': {'action': 'call', 'turn_id': 'test', 'call_id': 'one', 'tool': 'run_shell', 'arguments': '{"command":"pwd"}', 'status': 'running'}}))
                page.wait_for_function('document.querySelectorAll("#tool-workspace article").length === 1')
                sockets[-1].send(json.dumps({'type': 'tool_activity', 'payload': {'action': 'end', 'turn_id': 'test'}}))
                page.wait_for_function('document.querySelectorAll("#tool-workspace article").length === 0')
                # Double-click still opens the existing chat panel.
                page.locator('#pal-raster-canvas').dblclick()
                assert 'hidden' not in (page.locator('#chat-panel').get_attribute('class') or '')
                # Reconnection state snapshots drive the same renderer.
                sockets[-1].close()
                page.wait_for_timeout(3400)
                assert len(sockets) == 2
                state('sleeping')
                page.emulate_media(reduced_motion='reduce')
                state('panic')
                page.wait_for_timeout(1400)
                assert {'type': 'avatar_action_finished', 'state': 'panic'} in sent
                page.evaluate('PalRasterAvatar.destroy()')
                assert page.locator('#pal-raster-widget').count() == 0
                assert not page.evaluate('PalRasterAvatar.motionReady()')
                page.goto(url + '/previews/pal-blink/index.html')
                page.locator('[data-expression="greeting"]').click()
                assert page.locator('#wave-hand').get_attribute('opacity') == '1'
                assert not errors, errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
