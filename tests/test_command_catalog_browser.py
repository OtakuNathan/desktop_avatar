from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest


def test_real_command_menu_uses_shared_catalog_and_waits_for_user_send():
    api = pytest.importorskip("playwright.sync_api")
    root = Path(__file__).resolve().parents[1] / "client"
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with api.sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).exists():
                pytest.skip("Playwright Chromium is not installed")
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page()
                page.add_init_script('''window.sent=[];window.sockets=[];
                    window.WebSocket=class {static OPEN=1;static CONNECTING=0;
                        constructor(){this.readyState=1;window.sockets.push(this);setTimeout(()=>this.onopen?.({}),0)}
                        send(data){window.sent.push(JSON.parse(data))}close(){this.readyState=3}
                    };
                    window.catalog=commands=>{for(const s of window.sockets)s.onmessage?.({data:JSON.stringify({type:'command_catalog',commands})})};''')
                page.goto(f"http://127.0.0.1:{server.server_port}/?skin=pal2d")
                page.locator("#chat-panel").evaluate("node=>node.classList.remove('hidden')")
                page.wait_for_function("window.sockets.some(s=>s.onmessage)")
                page.evaluate("catalog([{command:'android_pair',description:'<img src=x> 配对手机'}])")
                menu = page.locator("#chat-command")
                assert menu.locator("option").count() == 2
                assert menu.locator("img").count() == 0
                menu.select_option("android_pair")
                assert page.locator("#chat-input").input_value() == "/android_pair "
                assert not page.evaluate("sent.some(frame=>frame.type==='chat_message')")
                page.locator("#chat-send").click()
                assert page.evaluate("sent.filter(frame=>frame.type==='chat_message').at(-1).text") == "/android_pair"
                page.evaluate("catalog([])")
                assert menu.is_disabled()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
