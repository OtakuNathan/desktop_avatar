/* ============================================================
 * 聊天消息渲染 — markdown + LaTeX 数学公式
 * 管线：marked（带数学 tokenizer 扩展）→ DOMPurify → 占位符替换为 KaTeX HTML。
 * 数学 HTML 在 sanitize 之后注入：占位符是纯文本，可安全通过
 * DOMPurify；KaTeX 输出的行内样式与 MathML 不会被安全配置剥掉。
 * ============================================================ */
(function (global) {
  "use strict";

  const PLACEHOLDER_RE = /⟦KTX(\d+)⟧/g;

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (ch) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
  }

  function createChatMarkdown(marked, domPurify, katex) {
    if (global.__chatMarkdownInstance) return global.__chatMarkdownInstance;

    const tokens = [];
    const hasKatex = Boolean(katex && typeof katex.renderToString === "function");

    function placeholder(token) {
      const index = tokens.length;
      tokens.push(token);
      return "⟦KTX" + index + "⟧";
    }

    function renderMath(token) {
      if (!hasKatex) return "<code>" + escapeHtml(token.raw) + "</code>";
      try {
        return katex.renderToString(token.latex, {
          displayMode: token.display,
          throwOnError: false,
          strict: false,
          trust: false,
        });
      } catch (_error) {
        return "<code>" + escapeHtml(token.raw) + "</code>";
      }
    }

    if (marked && typeof marked.use === "function") {
      marked.use({
        extensions: [
          {
            // 块级：$$...$$ 与 \[...\]
            name: "chatMathBlock",
            level: "block",
            start(src) {
              const dollar = src.indexOf("$$");
              const bracket = src.indexOf("\\[");
              if (dollar < 0 && bracket < 0) return undefined;
              if (dollar < 0) return bracket;
              if (bracket < 0) return dollar;
              return Math.min(dollar, bracket);
            },
            tokenizer(src) {
              const match = /^\$\$([\s\S]+?)\$\$(?:\n+|$)/.exec(src) ||
                /^\\\[([\s\S]+?)\\\](?:\n+|$)/.exec(src);
              if (!match) return false;
              return { type: "chatMathBlock", raw: match[0], latex: match[1].trim(), display: true };
            },
            renderer(token) { return placeholder(token); },
          },
          {
            // 行内：\(...\) 与 $...$（$ 后不能是空白，$ 前不能是空白、后不能是数字，
            // 避免「$5 和 $10」这类金额被误判）
            name: "chatMathInline",
            level: "inline",
            start(src) {
              const index = src.search(/(?<!\\)\$|\\\(/);
              return index < 0 ? undefined : index;
            },
            tokenizer(src) {
              const match = /^\\\(([\s\S]+?)\\\)/.exec(src) ||
                /^\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)/.exec(src);
              if (!match) return false;
              return { type: "chatMathInline", raw: match[0], latex: match[1], display: false };
            },
            renderer(token) { return placeholder(token); },
          },
        ],
      });
    }

    const instance = {
      render(source) {
        if (!marked || !domPurify) return null;
        tokens.length = 0;
        let rendered;
        try {
          rendered = marked.parse(String(source || ""), { async: false, breaks: true, gfm: true });
        } catch (_error) {
          return null;
        }
        const sanitized = domPurify.sanitize(rendered, {
          USE_PROFILES: { html: true },
          FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "iframe", "object", "embed", "svg", "math"],
          FORBID_ATTR: ["style"],
        });
        return sanitized.replace(PLACEHOLDER_RE, (match, index) => {
          const token = tokens[Number(index)];
          return token ? renderMath(token) : match;
        });
      },
    };

    global.__chatMarkdownInstance = instance;
    return instance;
  }

  global.createChatMarkdown = createChatMarkdown;
})(window);
