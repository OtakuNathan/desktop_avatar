"""Exercise the default renderer through real page and WebSocket events."""
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest


def test_petra_skin_and_switch_keep_shared_actions():
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
                errors, sockets, requests = [], [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append(request.url))
                page.route_web_socket('**', lambda socket: sockets.append(socket))
                url = f'http://127.0.0.1:{server.server_port}/?skin=petra&preview=1'
                page.goto(url)
                page.wait_for_function('window.PalRasterAvatar?.motionReady()')
                assert page.locator('#pal-raster-widget').get_attribute('data-skin') == 'petra'
                assert any('/petra-raster/soft-body.png' in request for request in requests)
                assert any('/petra-raster/standing-character.png' in request for request in requests)
                assert not any('/pal-raster/arm-texture.png' in request for request in requests)
                assert any('/petra-raster/gesture-hands.png' in request for request in requests)
                # Facial landmarks must remain inside the new screen, in body coordinates.
                landmarks = page.evaluate("""() => {
                    const base = document.querySelector('.base').getScreenCTM().inverse();
                    const face = document.querySelector('#face-layout').getScreenCTM();
                    return [[236,279],[356,279],[296,318]].map(([x,y]) => {
                        const p = new DOMPoint(x,y).matrixTransform(base.multiply(face));
                        return [p.x,p.y];
                    });
                }""")
                assert all(300 < x < 720 and 490 < y < 735 for x, y in landmarks)
                assert page.locator('#chat-input').get_attribute('placeholder').startswith('和 Petra')
                sockets[-1].send(json.dumps({'type': 'avatar_state', 'state': 'greeting'}))
                page.wait_for_function('document.querySelector("#pal-raster-widget").dataset.avatarState === "greeting"')
                page.wait_for_function('document.querySelector("#wave-hand").getAttribute("opacity") === "1"')
                sockets[-1].send(json.dumps({'type': 'avatar_state', 'state': 'drinking'}))
                page.wait_for_function('document.querySelector("#pal-raster-widget").dataset.avatarState === "drinking"')
                page.wait_for_timeout(2100)
                # The rigid hand/prop sprite must deliver its straw to the mouth.
                distance = page.evaluate("""() => {
                    const tip = new DOMPoint(1068,133).matrixTransform(document.querySelector('#cyber-cola').getScreenCTM());
                    const mouth = new DOMPoint(296,318).matrixTransform(document.querySelector('#face-layout').getScreenCTM());
                    return Math.hypot(tip.x-mouth.x,tip.y-mouth.y);
                }""")
                assert distance < 2
                assert page.locator('#rest-hand').get_attribute('opacity') == '0'
                page.locator('#skin-switch').click()
                page.wait_for_function('document.documentElement.dataset.avatarSkin === "pal"')
                page.wait_for_function('window.PalRasterAvatar?.motionReady()')
                assert page.locator('#pal-raster-widget').get_attribute('data-skin') == 'pal'
                assert 'preview=1' in page.url
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()


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
                assert page.locator('.question-eye').count() == 2
                page.screenshot(path=str(tmp_path / 'raster-question.png'))
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
                state('panic')
                page.wait_for_function('Number(document.querySelector(".eye-overlay").dataset.headScale) > 1.16')
                assert page.locator('.spiral-eye').count() == 2
                assert float(page.locator('.eye-overlay').get_attribute('data-head-scale')) > 1.15
                page.screenshot(path=str(tmp_path / 'raster-big-head.png'))
                state('working')
                assert float(page.locator('.eye-overlay').get_attribute('data-head-scale')) == 1
                page.emulate_media(reduced_motion='reduce')
                page.wait_for_function(
                    "document.querySelector('#pal-raster-widget').classList.contains('paused')"
                )
                state('panic')
                assert float(page.locator('.eye-overlay').get_attribute('data-head-scale')) == 1.2
                page.wait_for_timeout(2800)
                assert {'type': 'avatar_action_finished', 'state': 'panic'} in sent
                # Independent expressions survive the WebSocket/main/renderer pipeline.
                page.emulate_media(reduced_motion='no-preference')
                page.wait_for_function(
                    "!document.querySelector('#pal-raster-widget').classList.contains('paused')"
                )
                for name, selector in [('error', '.crash-eye'), ('shy', '.blush'),
                                       ('awkward', '.cookie-eye'), ('crying', '.tear'),
                                       ('bored', '#scratch-hand'), ('gloomy', '.gloom'), ('celebrate', '.firework'), ('agree', '#ok-hand')]:
                    state(name)
                    page.wait_for_timeout(400)
                    assert page.locator(selector).count() > 0
                    if name == 'agree':
                        page.wait_for_timeout(1400)
                        assert page.locator('#ok-hand').get_attribute('opacity') == '1'
                    page.screenshot(path=str(tmp_path / f'raster-{name}.png'))
                    state('working')
                for name in ('error', 'crying'):
                    state(name)
                    page.wait_for_function('document.querySelector(".eye-overlay").dataset.state === "working"')
                    completion = {'type': 'avatar_action_finished', 'state': name}
                    for _ in range(50):
                        if completion in sent:
                            break
                        page.wait_for_timeout(100)
                    assert completion in sent
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
