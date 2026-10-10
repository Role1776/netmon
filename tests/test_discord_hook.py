import json

import pytest

import discord_hook
from notifier import ChatAction

HOOK = "https://discord.test/api/webhooks/1/abc"

REPORT_HTML = """<b>Report</b>
Client: <b>MyISP</b>
<pre>
Download: 140 Mbps
Upload:   20 Mbps
</pre>
Avg <code>140 Mbps</code> today"""
REPORT_MD = """**Report**
Client: **MyISP**
```
Download: 140 Mbps
Upload:   20 Mbps
```
Avg `140 Mbps` today"""


@pytest.fixture
def bot():
    return discord_hook.Bot.init(HOOK, 5)


def sent_description(bot, http, html):
    bot.send_message(html)
    return http.calls[-1][1]["json"]["embeds"][0]["description"]


@pytest.mark.parametrize("url", ["", "  "])
def test_init_rejects_blank_url(url):
    with pytest.raises(ValueError):
        discord_hook.Bot.init(url, 5)


@pytest.mark.parametrize("html,md", [
    ("<b>x</b>", "**x**"),
    ("<code>x</code>", "`x`"),
    ("<pre>x</pre>", "```x```"),
    ("<b>a</b> and <b>b</b>", "**a** and **b**"),
    ("<b>multi\nline</b>", "**multi\nline**"),
    ("<pre>l1\nl2</pre>", "```l1\nl2```"),
    ("<i>x</i> <u>y</u>", "x y"),
    ("<a href=\"http://x\">link</a>", "link"),
    ("  padded \n", "padded"),
    ("plain text", "plain text"),
    ("", ""),
    (REPORT_HTML, REPORT_MD),
])
def test_html_to_discord_md(html, md, bot, http):
    assert sent_description(bot, http, html) == md


def test_html_entities_are_decoded(bot, http):
    assert sent_description(bot, http, "<b>a &lt; b &amp; c</b>") == "**a < b & c**"


def test_escaped_tag_text_stays_literal(bot, http):
    assert sent_description(bot, http, "&lt;b&gt;x&lt;/b&gt;") == "<b>x</b>"


@pytest.mark.parametrize("html,md", [
    ("say &quot;hi&quot;", 'say "hi"'),
    ("a &gt; b", "a > b"),
    ("<code>a &lt; b</code>", "`a < b`"),
])
def test_html_entities_are_decoded_in_context(html, md, bot, http):
    assert sent_description(bot, http, html) == md


def test_send_message_posts_converted_embed(bot, http):
    http.status, http.text = 204, ""
    assert bot.send_message(REPORT_HTML) == ""
    assert http.calls == [(HOOK, {"json": {"embeds": [{"description": REPORT_MD}]}, "timeout": 5})]


@pytest.mark.parametrize("status", [200, 204])
def test_send_message_success_statuses(bot, http, status):
    http.status = status
    bot.send_message("x")


@pytest.mark.parametrize("status", [400, 404, 429])
def test_send_message_error_status_raises(bot, http, status):
    http.status = status
    with pytest.raises(RuntimeError):
        bot.send_message("x")


def test_send_message_limit_boundary_is_not_truncated(bot, http):
    bot.send_message("a" * 4096)
    assert http.calls[0][1]["json"]["embeds"][0]["description"] == "a" * 4096


def test_send_message_over_limit_is_truncated_with_ellipsis(bot, http):
    bot.send_message("a" * 4097)
    assert http.calls[0][1]["json"]["embeds"][0]["description"] == "a" * 4095 + "…"


def test_send_message_limit_applies_after_conversion(bot, http):
    bot.send_message("<b>" + "x" * 4090 + "</b>")
    assert http.calls[0][1]["json"]["embeds"][0]["description"] == "**" + "x" * 4090 + "**"


def test_send_photo_attaches_graph_inside_embed(bot, http):
    http.status, http.text = 200, "sent"
    assert bot.send_photo(b"PNG", REPORT_HTML) == "sent"
    [(url, kwargs)] = http.calls
    assert url == HOOK
    assert json.loads(kwargs["data"]["payload_json"]) == {
        "embeds": [{"description": REPORT_MD, "image": {"url": "attachment://graph.png"}}]}
    assert kwargs["files"] == {"files[0]": ("graph.png", b"PNG", "image/png")}
    assert kwargs["timeout"] == 5


def test_send_photo_caption_over_limit_is_truncated(bot, http):
    bot.send_photo(b"PNG", "a" * 5000)
    desc = json.loads(http.calls[0][1]["data"]["payload_json"])["embeds"][0]["description"]
    assert desc == "a" * 4095 + "…"


@pytest.mark.parametrize("status", [200, 204])
def test_send_photo_success_statuses(bot, http, status):
    http.status = status
    bot.send_photo(b"PNG", "c")


def test_send_photo_error_status_raises(bot, http):
    http.status = 400
    with pytest.raises(RuntimeError):
        bot.send_photo(b"PNG", "c")


def test_send_chat_action_is_a_noop(bot, http):
    assert bot.send_chat_action(ChatAction.TYPING) == ""
    assert http.calls == []
