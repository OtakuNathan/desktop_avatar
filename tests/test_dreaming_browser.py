"""Exercise runtime sleep through the actual browser frame handler and clicks."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest


def test_resident_sleep_blocks_local_taps_until_wake():
    api = pytest.importorskip("playwright.sync_api")
    root = Path(__file__).resolve().parents[1] / "client"
    with api.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is not installed")
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            def serve(route):
                path = urlsplit(route.request.url).path.lstrip("/") or "index.html"
                if path == "js/config.js":
                    route.fulfill(content_type="text/javascript", body='window.AVATAR_CONFIG = {renderer:"svg"};')
                elif (root / path).is_file():
                    route.fulfill(path=str(root / path))
                else:
                    route.fulfill(status=404, body="")
            page.route("http://avatar.test/**", serve)
            page.add_init_script('''
                window.WebSocket = class {
                  static OPEN = 1; static CONNECTING = 0;
                  constructor() { this.readyState = 1; this.sent = []; window.testSocket = this; }
                  send(text) { this.sent.push(JSON.parse(text)); }
                  receive(frame) { this.onmessage({data:JSON.stringify(frame)}); }
                };
            ''')
            page.goto("http://avatar.test/")
            canvas = page.locator("#pal-svg-canvas")
            canvas.wait_for()
            widget = page.locator("#pal-svg-widget")
            page.wait_for_function("document.querySelector('#pal-svg-widget')?.dataset.avatarState === 'standby'")
            page.evaluate("testSocket.receive({type:'runtime_state', payload:{sleeping:true}})")
            assert widget.get_attribute("data-avatar-state") == "sleeping"
            canvas.click()
            page.wait_for_timeout(350)
            assert widget.get_attribute("data-avatar-state") == "sleeping"
            assert page.evaluate("testSocket.sent.filter(f=>f.type==='avatar_action').length") == 0
            page.evaluate("testSocket.receive({type:'avatar_state', state:'working'})")
            assert widget.get_attribute("data-avatar-state") == "sleeping"
            page.evaluate("testSocket.receive({type:'runtime_state', payload:{sleeping:false}})")
            assert widget.get_attribute("data-avatar-state") == "standby"
            canvas.click()
            page.wait_for_timeout(350)
            assert page.evaluate("testSocket.sent.filter(f=>f.type==='avatar_action').length") == 1
        finally:
            browser.close()
