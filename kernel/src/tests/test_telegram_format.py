"""Markdown → Telegram HTML conversion used by review/news digest pushes.

The review digests carry clickable source links (``[华尔街见闻](https://…)``)
and internal memory citations (``[[cite:doc:<id>]]``). Telegram HTML has no
hover titles and no way to jump to a memory document, so the converter must:

* keep anchors intact even though news URLs commonly contain underscores
  (the italic rule used to rewrite ``abc_def`` into ``abc<i>def</i>`` and
  silently break ``<a href>``);
* leave ``<code>`` / ``<pre>`` content untouched;
* render ``[[cite:doc:<id>]]`` as a readable label instead of a dead token.
"""

from config import config
from notifier.telegram import _escape_unsafe_html, _md_to_telegram_html


def convert(markdown: str) -> str:
    return _escape_unsafe_html(_md_to_telegram_html(markdown))


def test_markdown_link_with_underscores_stays_clickable():
    html = convert("来源：[华尔街见闻](https://wallstreetcn.com/articles/abc_def_123)")
    assert (
        '<a href="https://wallstreetcn.com/articles/abc_def_123">华尔街见闻</a>' in html
    )


def test_markdown_link_query_string_is_escaped_but_clickable():
    html = convert("看 [来源](https://example.com/?a=1&b=2)")
    assert '<a href="https://example.com/?a=1&amp;b=2">来源</a>' in html


def test_bare_url_with_underscores_is_linked_not_italicised():
    html = convert("见 https://example.com/a_b_c 详情")
    assert '<a href="https://example.com/a_b_c">https://example.com/a_b_c</a>' in html
    assert "<i>" not in html


def test_trailing_punctuation_stays_outside_the_link():
    html = convert("见 https://example.com/a_b_c。后续")
    assert '<a href="https://example.com/a_b_c">https://example.com/a_b_c</a>。后续' in html


def test_bold_headings_and_bullets_render_for_the_review_digest():
    html = convert("**关键变化**\n- 要点一\n- 要点二")
    assert "<b>关键变化</b>" in html
    assert "• 要点一" in html
    assert "• 要点二" in html


def test_memory_cite_tokens_become_readable_labels():
    html = convert("纪律核对：遵守 [[cite:doc:2620]]")
    assert "记忆#2620" in html
    assert "[[cite" not in html


def test_code_spans_and_blocks_are_left_alone():
    html = convert("参数 `a_b_c` 不变\n```\nhttps://example.com/a_b\n```")
    assert "<code>a_b_c</code>" in html
    assert "<i>" not in html
    assert "<a href" not in html


def test_unsafe_scheme_stays_plain_text():
    html = convert("[点我](javascript:alert(1))")
    assert "<a href" not in html


def test_report_push_is_off_by_default():
    """The scheduled skills push the digest; the kernel raw push is opt-in."""
    assert config.TELEGRAM_REPORT_PUSH is False
