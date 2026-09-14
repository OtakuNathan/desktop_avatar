from pathlib import Path
from urllib.parse import urlsplit

import pytest


def test_review_items_field_edit_and_failed_delivery_preserve_text():
    api = pytest.importorskip("playwright.sync_api")
    root = Path(__file__).resolve().parents[1] / "client"
    with api.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is not installed")
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page(reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            def serve(route):
                path = root / (urlsplit(route.request.url).path.lstrip("/") or "index.html")
                route.fulfill(path=str(path)) if path.is_file() else route.fulfill(status=404, body="")
            page.route("http://avatar.test/**", serve)
            page.add_init_script("""
                window.WebSocket = class {
                    static OPEN=1; static CONNECTING=0;
                    constructor(){this.readyState=1;this.sent=[];window.testSocket=this;}
                    send(text){this.sent.push(JSON.parse(text));}
                    receive(frame){this.onmessage({data:JSON.stringify(frame)});}
                };
            """)
            page.goto("http://avatar.test/")
            page.wait_for_function("Boolean(window.testSocket?.onmessage)")
            page.locator("#pal-raster-canvas").dblclick()
            receive = lambda frame: page.evaluate("(f)=>testSocket.receive(f)", frame)
            receive({"type": "chat_interaction", "event": "open", "interaction": {
                "interaction_id": "mr_test", "revision": "1", "text": "Review each candidate",
                "items": [{"title": "c1", "state": "pending", "text": "def f():\n    return 1\n",
                           "buttons": [[{"label": "修正", "token": "r1b1"}]]}], "buttons": []}})
            assert "    return 1" in page.locator(".interaction-item-text").text_content()
            page.get_by_role("button", name="修正", exact=True).click()
            assert page.evaluate("testSocket.sent.at(-1).button_token") == "r1b1"
            receive({"type": "chat_interaction", "event": "update", "interaction": {
                "interaction_id": "mr_test", "revision": "2", "text": "Edit",
                "inputs": [{"input_id": "value", "label": "正文", "value": "old\n", "multiline": True,
                            "submit": {"label": "保存修改", "token": "r2b1"}}], "buttons": []}})
            editor = page.get_by_label("正文")
            assert editor.input_value() == "old\n"
            value = "def fixed():\n    return '<script>safe</script>'\n"
            editor.fill(value)
            page.get_by_role("button", name="保存修改").click()
            assert page.evaluate("testSocket.sent.at(-1).input_values.value") == value
            receive({"type": "delivery_failed", "error": "offline"})
            assert editor.input_value() == value
            assert page.get_by_role("button", name="保存修改").is_enabled()
            # Reconnection replays the unchanged server draft; keep the unsent edit.
            receive({"type": "chat_interaction", "event": "open", "interaction": {
                "interaction_id": "mr_test", "revision": "2", "text": "Edit",
                "inputs": [{"input_id": "value", "label": "正文", "value": "old\n", "multiline": True,
                            "submit": {"label": "保存修改", "token": "r2b1"}}], "buttons": []}})
            assert page.get_by_label("正文").input_value() == value
            receive({"type": "chat_interaction", "event": "resolve", "interaction": {
                "interaction_id": "mr_test", "text": "Completed"}})
            assert page.locator(".interaction button").count() == 0
            assert not errors
        finally:
            browser.close()
