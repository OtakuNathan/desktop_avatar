"""Idle reactions stay local, yield to Pal, and use the real raster renderer."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest


def test_idle_variety_cola_and_preemption():
    api = pytest.importorskip('playwright.sync_api')
    root = Path(__file__).resolve().parents[1] / 'client'
    with api.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Playwright Chromium is not installed')
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            page = browser.new_page(reduced_motion='reduce')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def serve(route):
                path = urlsplit(route.request.url).path.lstrip('/') or 'index.html'
                if path == 'js/config.js':
                    route.fulfill(content_type='text/javascript', body=(root / path).read_text() +
                                  '\nAVATAR_CONFIG.idleActionMinMs=1000; AVATAR_CONFIG.idleActionJitterMs=0;')
                elif (root / path).is_file():
                    route.fulfill(path=str(root / path))
                else:
                    route.fulfill(status=404, body='')

            page.route('http://avatar.test/**', serve)
            page.add_init_script('''
                window.WebSocket = class {
                  static OPEN = 1; static CONNECTING = 0;
                  constructor() { this.readyState=1; this.sent=[]; window.testSocket=this; }
                  send(text) { this.sent.push(JSON.parse(text)); }
                  receive(frame) { this.onmessage({data:JSON.stringify(frame)}); }
                };
            ''')
            page.goto('http://avatar.test/')
            page.wait_for_function('window.PalRasterAvatar?.motionReady()')
            page.clock.install()
            receive = lambda frame: page.evaluate('(f)=>testSocket.receive(f)', frame)
            state = lambda: page.locator('.eye-overlay').get_attribute('data-state')
            receive({'type': 'avatar_state', 'state': 'standby'})
            for random, expected, duration in [(0, 'snacking', 4200), (0, 'drinking', 5600),
                                                (.5, 'bored', 4600), (.99, 'gloomy', 4600)]:
                page.evaluate('(r)=>Math.random=()=>r', random)
                page.clock.run_for(1000)
                assert state() == expected
                if expected == 'drinking':
                    assert page.locator('#cyber-cola').get_attribute('opacity') == '1'
                    assert page.locator('#snack').get_attribute('opacity') == '0'
                page.clock.run_for(duration)
                assert state() == 'standby'
            assert page.evaluate("testSocket.sent.filter(f=>f.type==='avatar_action_finished').length") == 0

            # The same random value cannot repeat the last action.
            page.clock.run_for(1000)
            assert state() != 'gloomy'
            receive({'type': 'avatar_state', 'state': 'working'})
            page.clock.run_for(10000)
            assert state() == 'working'
            assert page.locator('#cyber-cola').get_attribute('opacity') == '0'

            # Tool and reply events also interrupt idle before an avatar-state frame arrives.
            for frame in [
                {'type': 'tool_activity', 'payload': {'action': 'begin', 'turn_id': 'idle-test'}},
                {'type': 'chat_message', 'sender': 'avatar', 'event': 'start', 'message_id': 'idle-test'},
            ]:
                receive({'type': 'avatar_state', 'state': 'standby'})
                page.clock.run_for(1000)
                assert state() != 'standby'
                receive(frame)
                assert state() == 'standby'
                page.clock.run_for(10000)
                assert state() == 'standby'

            receive({'type': 'avatar_state', 'state': 'standby'})
            page.clock.run_for(1000)
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true}); document.dispatchEvent(new Event('visibilitychange'))")
            page.clock.run_for(10000)
            assert state() == 'standby'
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false}); document.dispatchEvent(new Event('visibilitychange'))")
            page.clock.run_for(1000)
            assert state() != 'standby'
            receive({'type': 'runtime_state', 'payload': {'sleeping': True}})
            receive({'type': 'avatar_state', 'state': 'drinking'})
            page.clock.run_for(10000)
            assert state() == 'sleeping'

            # An explicit Pal drink still acknowledges its original state exactly once.
            receive({'type': 'runtime_state', 'payload': {'sleeping': False}})
            receive({'type': 'avatar_state', 'state': 'working'})
            receive({'type': 'avatar_state', 'state': 'drinking'})
            page.clock.run_for(5200)
            assert state() == 'working'
            assert page.evaluate("testSocket.sent.filter(f=>f.type==='avatar_action_finished' && f.state==='drinking').length") == 1

            # One painted hand/can/straw follows the wrist as a rigid attachment.
            # The arm brings the fixed straw tip to the mouth; the prop never slides.
            page.emulate_media(reduced_motion='no-preference')
            receive({'type': 'avatar_state', 'state': 'drinking'})
            page.clock.run_for(800)
            hand = page.locator('#cyber-cola')
            assert hand.evaluate('(el)=>el.parentElement.id') == 'wrist-joint'
            assert hand.locator('image').count() == 1
            assert page.locator('#cola-straw').count() == 0
            assert page.locator('#pinch-hand').get_attribute('opacity') == '0'
            transform = hand.get_attribute('transform')
            def straw_distance():
                return page.evaluate('''() => {
                    const tip = new DOMPoint(1068,133).matrixTransform(document.querySelector('#cyber-cola').getScreenCTM());
                    const mouth = new DOMPoint(296,318).matrixTransform(document.querySelector('.eye-overlay').getScreenCTM());
                    return Math.hypot(tip.x-mouth.x,tip.y-mouth.y);
                }''')
            assert straw_distance() > 15
            page.clock.run_for(1200)
            assert straw_distance() < 2
            assert hand.get_attribute('transform') == transform
            page.clock.run_for(2400)
            assert straw_distance() > 15
            receive({'type': 'avatar_state', 'state': 'thinking'})
            assert hand.get_attribute('opacity') == '0'
            assert state() == 'thinking'
            assert not errors, errors
        finally:
            browser.close()
