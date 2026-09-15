from pathlib import Path
from urllib.parse import urlsplit

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request
from server.sidecar import serve_client_asset


@pytest.mark.parametrize('origin,allowed',[
    ('http://100.101.102.103:8765',True),
    ('https://avatar.example.ts.net',True),
    ('https://unrelated.example',False),('null',False),
    ('http://100.101.102.103:8765@evil.example',False),
    (None,True),
])
def test_browser_origin_must_match_the_avatar_server(origin,allowed):
    host='avatar.example.ts.net' if origin=='https://avatar.example.ts.net' else '100.101.102.103:8765'
    headers=Headers({'Upgrade':'websocket','Host':host})
    if origin is not None:headers['Origin']=origin
    response=serve_client_asset(None,Request('/',headers))
    assert (response is None)==allowed
    if not allowed:assert response.status_code==403


def test_approval_buttons_are_single_click_expire_and_resolve():
    api=pytest.importorskip('playwright.sync_api')
    root=Path(__file__).resolve().parents[1]/'client'
    with api.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Playwright Chromium is not installed')
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        try:
            page=browser.new_page(reduced_motion='reduce')
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            def serve(route):
                path=root/(urlsplit(route.request.url).path.lstrip('/') or 'index.html')
                route.fulfill(path=str(path)) if path.is_file() else route.fulfill(status=404,body='')
            page.route('http://avatar.test/**',serve)
            page.add_init_script('''
                window.WebSocket=class {
                    static OPEN=1;static CONNECTING=0;
                    constructor(){this.readyState=1;this.sent=[];window.testSocket=this;}
                    send(text){this.sent.push(JSON.parse(text));}
                    receive(frame){this.onmessage({data:JSON.stringify(frame)});}
                };
            ''')
            page.goto('http://avatar.test/')
            page.wait_for_function('Boolean(window.testSocket?.onmessage)')
            page.locator('#pal-raster-canvas').dblclick()
            def card(identifier,expires):
                return {'type':'chat_interaction','event':'open','interaction':{
                    'interaction_id':identifier,'interaction_kind':'approval_request',
                    'text':'apt install <script>unsafe()</script>','expires_at':expires,
                    'buttons':[[{'label':'Approve once','token':'b0'},{'label':'Reject','token':'b1'}]]}}
            receive=lambda frame:page.evaluate('(f)=>testSocket.receive(f)',frame)
            receive(card('approve','2099-01-01T00:00:00Z'))
            assert '<script>unsafe()</script>' in page.locator('.approval').inner_text()
            assert page.locator('.approval script').count()==0
            page.get_by_role('button',name='Approve once',exact=True).click()
            assert page.get_by_role('button',name='Approve once',exact=True).is_disabled()
            sent=page.evaluate('testSocket.sent.at(-1)')
            assert sent=={'type':'interaction_result','interaction_id':'approve','button_token':'b0'}
            receive({'type':'chat_interaction','event':'resolve','interaction':{
                'interaction_id':'approve','interaction_kind':'approval_request','text':'Approved once. Execution pending.'}})
            assert page.locator('.approval button').count()==0
            receive(card('expired','2000-01-01T00:00:00Z'))
            assert page.locator('.approval button').count()==0
            assert 'expired' in page.locator('.approval').last.inner_text()
            receive({'type':'delivery_failed','error':'offline'})
            assert page.locator('.approval button').count()==0
            assert not errors
        finally:browser.close()
