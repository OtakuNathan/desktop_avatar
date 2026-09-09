"""Exercise the actual DOM renderer; skip only when local Chromium is absent."""
from pathlib import Path
import pytest


def test_work_area_updates_safe_text_scroll_and_turn_lifetime():
    api=pytest.importorskip('playwright.sync_api')
    root=Path(__file__).resolve().parents[1]
    with api.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Playwright Chromium is not installed')
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        try:
            page=browser.new_page()
            page.set_content('''<div id="stage"><section id="panel">
                <span id="tool-workspace-count"></span><div class="tool-workspace-list" style="height:100px;overflow:auto"></div>
                </section></div>''')
            page.add_script_tag(path=str(root/'client/js/tool-workspace.js'))
            page.evaluate("window.work=createToolWorkspace(document.getElementById('panel'),document.getElementById('stage'))")
            def send(payload): page.evaluate('p=>work.handle(p)',payload)
            send({'action':'begin','turn_id':'a'})
            record={'action':'call','turn_id':'a','call_id':'one','tool':'write_file','arguments':'{"content":"<img src=x onerror=alert(1)>"}','status':'running'}
            send(record)
            page.locator('summary').click()
            send({**record,'status':'succeeded','patch':'--- file\n+++ file\n-old\n+new\n'})
            assert page.locator('article').count()==1
            assert page.locator('details').first.get_attribute('open') is not None
            assert page.locator('img').count()==0
            assert page.locator('.diff-add').count()==2
            assert page.locator('.diff-remove').count()==2
            for i in range(15): send({**record,'call_id':str(i)})
            page.locator('.tool-workspace-list').evaluate('(e)=>{e.scrollTop=0;e.dispatchEvent(new Event("scroll"))}')
            send({**record,'call_id':'new'})
            assert page.locator('.tool-workspace-list').evaluate('e=>e.scrollTop')==0
            for i in range(110): send({**record,'call_id':'many'+str(i)})
            assert page.locator('article').count()==100
            assert 'omitted' in page.locator('#tool-workspace-count').inner_text()
            send({'action':'begin','turn_id':'b'})
            send({'action':'end','turn_id':'a'})
            assert 'hidden' not in (page.locator('#panel').get_attribute('class') or '')
            send({'action':'end','turn_id':'b'})
            send({**record,'turn_id':'b'})
            assert page.locator('article').count()==0
            assert 'hidden' in (page.locator('#panel').get_attribute('class') or '')
        finally:
            browser.close()
