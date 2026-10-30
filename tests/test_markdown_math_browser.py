"""Exercise chat markdown + KaTeX math rendering; skip when local Chromium is absent."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "client/vendor/katex/katex.min.js",
    "client/vendor/marked.min.js",
    "client/vendor/purify.min.js",
    "client/js/markdown-math.js",
)


def _prepare(page):
    page.set_content('<div id="out"></div>')
    for relative in SCRIPTS:
        page.add_script_tag(path=str(ROOT / relative))
    page.evaluate("window.chatMarkdown = createChatMarkdown(window.marked, window.DOMPurify, window.katex)")


def _render(page, source):
    return page.evaluate(
        "(source) => {"
        " const html = window.chatMarkdown.render(source);"
        " document.getElementById('out').innerHTML = html;"
        " return html;"
        "}",
        source,
    )


def test_markdown_math_pipeline():
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is not installed")
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            _prepare(page)

            # \( ... \) inline delimiters render and leave no placeholder
            html = _render(page, r"\( end' = end - t_{\max} + t_i \)")
            assert "⟦KTX" not in html
            assert page.locator("#out .katex").count() == 1

            # $$ ... $$ and \[ ... \] render as display math
            _render(page, "$$ g(j) = \\sum_{l=1}^{j} s_l \\le g(j-1) + t $$")
            assert page.locator("#out .katex-display").count() == 1
            _render(page, r"\[ \sum_{i \in S} t_i \le \max_{i \in S} d_i \]")
            assert page.locator("#out .katex-display").count() == 1

            # single-dollar inline math
            _render(page, "$a_i \\cdot (2^i - 2^{n-i-1})$ 之余")
            assert page.locator("#out .katex").count() == 1

            # surrounding markdown still works next to math
            _render(page, "_强调_ 后面跟 $x^2$")
            assert page.locator("#out em").count() == 1
            assert page.locator("#out .katex").count() == 1

            # money is not math: "$5 和 $10"
            _render(page, "价格在 $5 和 $10 之间")
            assert page.locator("#out .katex").count() == 0
            assert "$5" in page.locator("#out").inner_text()

            # escaped dollar stays text
            _render(page, "\\$5 不渲染")
            assert page.locator("#out .katex").count() == 0
            assert "$5" in page.locator("#out").inner_text()

            # math inside fenced code stays literal
            _render(page, "```\n$$x^2$$ and $y_1$\n```")
            assert page.locator("#out .katex").count() == 0
            assert "$$x^2$$" in page.locator("#out pre").inner_text()

            # inline code spans win over math
            _render(page, "`$x^2$` 是行内代码")
            assert page.locator("#out .katex").count() == 0
            assert page.locator("#out code").inner_text() == "$x^2$"

            # broken LaTeX degrades to a visible error, never a crash
            html = _render(page, "$\\badcmd{$")
            assert "⟦KTX" not in html
            assert page.locator("#out .katex-error").count() >= 1

            # DOMPurify keeps the (safe) img tag as before, strips handlers and scripts
            _render(page, "<img src=x onerror=alert(1)><script>alert(2)</script> **bold**")
            assert page.locator("#out img").count() == 1
            assert page.locator("#out img").get_attribute("onerror") is None
            assert page.locator("#out script").count() == 0
            assert page.locator("#out strong").count() == 1
        finally:
            browser.close()
