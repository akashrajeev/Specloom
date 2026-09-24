from backend.tools.adapters import _compact_feed

ATOM = b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Query</title>
  <entry>
    <id>http://arxiv.org/abs/2609.00001v1</id>
    <title>Agents That
      Plan</title>
    <published>2026-09-20T10:00:00Z</published>
    <link href="https://arxiv.org/abs/2609.00001v1" rel="alternate" type="text/html"/>
    <link href="https://arxiv.org/pdf/2609.00001v1" rel="related" type="application/pdf"/>
    <summary>We study planning in tool-using agents.</summary>
  </entry>
</feed>"""

RSS = b"""<rss version="2.0"><channel><title>Blog</title>
<item><title>Post one</title><link>https://example.com/1</link><pubDate>Mon, 21 Sep 2026</pubDate><description>First post.</description></item>
</channel></rss>"""


def test_atom_feed_becomes_compact_entries():
    text = _compact_feed(ATOM)
    assert text is not None
    assert "1. Agents That Plan" in text
    assert "https://arxiv.org/abs/2609.00001v1 (2026-09-20)" in text
    assert "pdf" not in text
    assert "We study planning" in text


def test_rss_feed_becomes_compact_entries():
    text = _compact_feed(RSS)
    assert text is not None and "1. Post one" in text and "https://example.com/1" in text


def test_non_feed_is_left_alone():
    assert _compact_feed(b"<html><body>hello</body></html>") is None
    assert _compact_feed(b'{"a": 1}') is None
