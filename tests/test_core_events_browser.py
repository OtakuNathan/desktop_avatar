"""System notifications drive display only; turns and history stay independent."""
from pathlib import Path
from urllib.parse import urlsplit
import pytest


def test_failure_display_recovery_and_thinking_hand_reset():
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
                path = root / (urlsplit(route.request.url).path.lstrip('/') or 'index.html')
                if path.is_file():
                    route.fulfill(path=str(path))
                else:
                    route.fulfill(status=404, body='')
            page.route('http://avatar.test/**', serve)
            page.add_init_script('''
                window.WebSocket = class {
                  static OPEN=1; static CONNECTING=0;
                  constructor(){ this.readyState=1;this.sent=[];window.testSocket=this; }
                  send(text){this.sent.push(JSON.parse(text));}
                  receive(frame){this.onmessage({data:JSON.stringify(frame)});}
                };
            ''')
            page.goto('http://avatar.test/')
            page.wait_for_function('window.PalRasterAvatar?.motionReady()')
            page.clock.install()
            receive = lambda frame: page.evaluate('(f)=>testSocket.receive(f)', frame)
            state = lambda: page.locator('.eye-overlay').get_attribute('data-state')
            receive({'type':'avatar_state','state':'thinking'})
            receive({'type':'core_event','topic':'turn.tool_call_failed','payload':{'subsystem':'execution','component':'probe'}})
            assert state() == 'panic'
            receive({'type':'avatar_state','state':'standby'})
            assert state() == 'panic', 'turn completion must not erase a just-started reaction'
            page.clock.run_for(2700)
            assert state() == 'standby'
            assert page.locator('#caption').text_content() == ''

            failure = {'failure_id':'one','subsystem':'channel','component':'desktop'}
            snapshot = {'sleeping':False,'failures':[failure],'safe_modes':[failure]}
            receive({'type':'runtime_state','payload':snapshot})
            assert state() == 'error'
            assert page.locator('#caption').text_content() == 'channel'
            receive({'type':'avatar_state','state':'working'})
            receive({'type':'core_event','topic':'turn.tool_call_failed','payload':{}})
            page.clock.run_for(6000)
            assert state() == 'error'
            assert page.locator('#caption').text_content() == 'channel'
            assert not page.evaluate("testSocket.sent.some(f=>f.type==='avatar_action_finished')")
            receive({'type':'runtime_state','payload':{'sleeping':False,'failures':[],'safe_modes':[]}})
            assert state() == 'working'
            assert page.locator('#caption').text_content() == '· · ·'

            # Report-only failures can finish within one frame; still show the error briefly.
            receive({'type':'core_event','topic':'failure.finished','payload':{'subsystem':'llm','status':'failed'}})
            assert state() == 'error'
            assert page.locator('#caption').text_content() == 'llm'
            page.clock.run_for(2700)
            assert state() == 'working'

            # A failure snapshot also works on first connection, with no start event.
            receive({'type':'runtime_state','payload':{**snapshot,'sleeping':True}})
            assert state() == 'error'
            receive({'type':'runtime_state','payload':{'sleeping':True,'failures':[],'safe_modes':[]}})
            assert state() == 'sleeping'
            receive({'type':'runtime_state','payload':{'sleeping':False,'failures':[],'safe_modes':[]}})

            page.emulate_media(reduced_motion='no-preference')
            receive({'type':'avatar_state','state':'thinking'})
            page.clock.run_for(1300)
            assert page.locator('#scratch-hand').get_attribute('opacity') == '1'
            receive({'type':'avatar_state','state':'thinking'})
            page.clock.run_for(3200)
            assert state() == 'thinking'
            assert page.locator('#scratch-hand').get_attribute('opacity') == '0'
            assert page.locator('#rest-hand').get_attribute('opacity') == '1'
            assert page.locator('#elbow-joint').get_attribute('transform') == 'rotate(0 177 483)'
            assert not errors, errors
        finally:
            browser.close()
