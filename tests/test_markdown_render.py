from __future__ import annotations

from markupsafe import Markup

from app.services.markdown_render import render_design_doc, render_issue_body


def _html(raw: str) -> str:
    rendered = render_issue_body(raw)
    assert rendered is not None
    assert isinstance(rendered, Markup)
    return str(rendered)


def _doc_html(raw: str) -> str:
    rendered = render_design_doc(raw)
    assert rendered is not None
    assert isinstance(rendered, Markup)
    return str(rendered)


def test_blank_body_returns_none() -> None:
    assert render_issue_body("") is None
    assert render_issue_body(None) is None
    assert render_issue_body("   \n\t ") is None


def test_headings_start_at_h3_and_stop_at_h6() -> None:
    html = _html("# 一级\n\n## 二级\n\n### 三级\n\n#### 四级\n\n##### 五级")
    assert "<h3>一级</h3>" in html
    assert "<h3>二级</h3>" in html
    assert "<h4>三级</h4>" in html
    assert "<h5>四级</h5>" in html
    assert "<h6>五级</h6>" in html
    assert "<h1" not in html
    assert "<h2" not in html


def test_common_markdown_subset() -> None:
    html = _html(
        "段落 **粗体** 与 *斜体*，行内 `code`。\n\n"
        "- 第一项\n- 第二项\n\n"
        "1. 有序一\n2. 有序二\n\n"
        "> 引用\n\n"
        "---\n\n"
        "```python\nprint('<x>')\n```\n"
    )
    assert "<p>" in html
    assert "<strong>粗体</strong>" in html
    assert "<em>斜体</em>" in html
    assert "<code>code</code>" in html
    assert "<ul>" in html and "<li>第一项</li>" in html
    assert "<ol>" in html and "<li>有序一</li>" in html
    assert "<blockquote>" in html and "引用" in html
    assert "<hr>" in html
    assert '<pre tabindex="0"><code>print(\'&lt;x&gt;\')\n</code></pre>' in html
    assert "language-python" not in html


def test_tables_render_without_alignment_styles() -> None:
    html = _html("| 名称 | 数量 |\n| :--- | ---: |\n| 苹果 | 2 |")
    assert "<table>" in html
    assert "<thead>" in html and "<th>名称</th>" in html
    assert "<tbody>" in html and "<td>苹果</td>" in html
    assert "style=" not in html


def test_safe_links_are_kept_with_rel() -> None:
    html = _html("[示例](https://example.com/docs) 与 [HTTP](http://example.com)")
    assert 'href="https://example.com/docs"' in html
    assert 'href="http://example.com"' in html
    assert 'rel="noopener noreferrer"' in html


def test_relative_and_unsafe_links_lose_href() -> None:
    html = _html(
        "[相对](/docs) [锚点](#part) [协议相对](//example.com) "
        "[脚本](javascript:alert(1)) [数据](data:text/html,x) "
        "[邮件](mailto:a@example.com)"
    )
    assert "javascript:" not in html
    assert "data:text/html" not in html
    assert "mailto:" not in html
    assert 'href="/docs"' not in html
    assert 'href="#part"' not in html
    assert 'href="//example.com"' not in html
    assert 'href="mailto:a@example.com"' not in html


def test_raw_html_is_sanitized_and_active_content_removed() -> None:
    html = _html(
        "<p>保留段落</p>"
        '<script>alert("script")</script>'
        '<style>body{display:none}</style>'
        '<iframe src="https://evil.example"></iframe>'
        '<svg onload="alert(1)"></svg>'
        "<form><input name=\"x\"><button>提交</button></form>"
        '<img src="x" onerror="alert(1)">'
    )
    assert "<p>保留段落</p>" in html
    for tag in ("script", "style", "iframe", "svg", "form", "input", "button", "img"):
        assert f"<{tag}" not in html


def test_event_style_id_and_class_attributes_are_stripped() -> None:
    html = _html(
        '<p onclick="alert(1)" style="color:red" id="x" class="y">内容</p>'
        '<a href="https://example.com" onclick="alert(1)" style="color:red" '
        'id="z" class="w" title="说明">链接</a>'
    )
    assert "onclick" not in html
    assert "style=" not in html
    assert 'id="' not in html
    assert "class=" not in html
    assert 'title="说明"' in html
    assert 'href="https://example.com"' in html


def test_render_failure_falls_back_without_markup(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("sanitizer unavailable")

    monkeypatch.setattr("app.services.markdown_render.nh3.clean", boom)
    assert render_issue_body("# 标题") is None
    assert render_design_doc("# 标题") is None


def test_design_doc_blank_returns_none() -> None:
    assert render_design_doc("") is None
    assert render_design_doc(None) is None
    assert render_design_doc("   \n\t ") is None


def test_design_doc_keeps_heading_hierarchy() -> None:
    html = _doc_html(
        "# 一级\n\n## 二级\n\n### 三级\n\n#### 四级\n\n##### 五级\n\n###### 六级"
    )
    assert "<h3>一级</h3>" in html
    assert "<h4>二级</h4>" in html
    assert "<h5>三级</h5>" in html
    assert "<h6>四级</h6>" in html
    assert "<h6>五级</h6>" in html
    assert "<h6>六级</h6>" in html
    assert "<h1" not in html
    assert "<h2" not in html


def test_design_doc_common_markdown_subset() -> None:
    html = _doc_html(
        "# 标题\n\n"
        "段落 **粗体** 与 *斜体*，行内 `code`。\n\n"
        "- 第一项\n- 第二项\n\n"
        "> 引用\n\n"
        "---\n\n"
        "```python\nprint('<x>')\n```\n\n"
        "| 名称 | 数量 |\n| :--- | ---: |\n| 苹果 | 2 |"
    )
    assert "<h3>标题</h3>" in html
    assert "<p>" in html
    assert "<strong>粗体</strong>" in html
    assert "<em>斜体</em>" in html
    assert "<code>code</code>" in html
    assert "<ul>" in html and "<li>第一项</li>" in html
    assert "<blockquote>" in html and "引用" in html
    assert "<hr>" in html
    assert '<pre tabindex="0"><code>print(\'&lt;x&gt;\')\n</code></pre>' in html
    assert "language-python" not in html
    assert "<table>" in html
    assert "<thead>" in html and "<th>名称</th>" in html
    assert "<tbody>" in html and "<td>苹果</td>" in html
    assert "style=" not in html


def test_design_doc_links_whitelist() -> None:
    html = _doc_html(
        "[示例](https://example.com/docs) 与 [HTTP](http://example.com) "
        "[相对](/docs) [锚点](#part) [脚本](javascript:alert(1)) "
        "[数据](data:text/html,x) [邮件](mailto:a@example.com)"
    )
    assert 'href="https://example.com/docs"' in html
    assert 'href="http://example.com"' in html
    assert 'rel="noopener noreferrer"' in html
    assert "javascript:" not in html
    assert "data:text/html" not in html
    assert "mailto:" not in html
    assert 'href="/docs"' not in html
    assert 'href="#part"' not in html


def test_design_doc_raw_html_is_sanitized() -> None:
    html = _doc_html(
        "<p>保留段落</p>"
        '<script>alert("script")</script>'
        '<style>body{display:none}</style>'
        '<iframe src="https://evil.example"></iframe>'
        '<svg onload="alert(1)"></svg>'
        '<form><input name="x"><button>提交</button></form>'
        '<img src="x" onerror="alert(1)">'
        '<p onclick="alert(1)" style="color:red" id="x" class="y">内容</p>'
    )
    assert "<p>保留段落</p>" in html
    assert "<p>内容</p>" in html
    for tag in ("script", "style", "iframe", "svg", "form", "input", "button", "img"):
        assert f"<{tag}" not in html
    assert "onclick" not in html
    assert "onerror" not in html
    assert "style=" not in html
    assert 'id="' not in html
    assert "class=" not in html
