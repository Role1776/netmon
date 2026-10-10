import pytest

import tg
from notifier import ChatAction

URL = "https://api.telegram.org/bottok"


@pytest.fixture
def bot():
    return tg.Bot.init("tok", "42", 5)


@pytest.mark.parametrize("token,chat", [("", "42"), ("  ", "42"), ("tok", ""), ("tok", " ")])
def test_init_rejects_blank_credentials(token, chat):
    with pytest.raises(ValueError):
        tg.Bot.init(token, chat, 5)


def test_send_message_posts_to_bot_api(bot, http):
    http.text = '{"ok":true}'
    assert bot.send_message("<b>hi</b>") == '{"ok":true}'
    assert http.calls == [(f"{URL}/sendMessage", {
        "data": {"chat_id": "42", "text": "<b>hi</b>", "parse_mode": "HTML"}, "timeout": 5})]


def test_send_message_custom_parse_mode(bot, http):
    bot.send_message("x", parse_mode="MarkdownV2")
    assert http.calls[0][1]["data"]["parse_mode"] == "MarkdownV2"


def test_send_message_error_status_raises(bot, http):
    http.status = 400
    with pytest.raises(RuntimeError):
        bot.send_message("x")


def test_send_message_limit_boundary_is_not_truncated(bot, http):
    bot.send_message("a" * 4096)
    assert http.calls[0][1]["data"]["text"] == "a" * 4096


def test_send_message_over_limit_is_truncated_with_ellipsis(bot, http):
    bot.send_message("a" * 4097)
    assert http.calls[0][1]["data"]["text"] == "a" * 4095 + "…"


def test_send_message_truncation_drops_whitespace_before_ellipsis(bot, http):
    bot.send_message("a" * 4090 + " " * 10 + "b" * 50)
    assert http.calls[0][1]["data"]["text"] == "a" * 4090 + "…"


def test_send_photo_posts_png_with_caption(bot, http):
    http.text = "sent"
    assert bot.send_photo(b"PNG", "cap") == "sent"
    assert http.calls == [(f"{URL}/sendPhoto", {
        "data": {"chat_id": "42", "caption": "cap", "parse_mode": "HTML"},
        "files": {"photo": ("graph.png", b"PNG", "image/png")}, "timeout": 5})]


def test_send_photo_default_caption_is_empty(bot, http):
    bot.send_photo(b"PNG")
    assert http.calls[0][1]["data"]["caption"] == ""


def test_send_photo_error_status_raises(bot, http):
    http.status = 500
    with pytest.raises(RuntimeError):
        bot.send_photo(b"PNG", "cap")


def test_caption_limit_boundary_is_not_truncated(bot, http):
    bot.send_photo(b"PNG", "a" * 1024)
    assert http.calls[0][1]["data"]["caption"] == "a" * 1024


def test_caption_over_limit_is_truncated_with_ellipsis(bot, http):
    bot.send_photo(b"PNG", "a" * 1025)
    assert http.calls[0][1]["data"]["caption"] == "a" * 1023 + "…"


def test_caption_truncation_counts_characters_not_bytes(bot, http):
    bot.send_photo(b"PNG", "я" * 1025)
    assert http.calls[0][1]["data"]["caption"] == "я" * 1023 + "…"


def test_send_chat_action_posts_action(bot, http):
    bot.send_chat_action(ChatAction.UPLOAD_PHOTO)
    assert http.calls == [(f"{URL}/sendChatAction", {
        "data": {"chat_id": "42", "action": "upload_photo"}, "timeout": 5})]


def test_send_chat_action_defaults_to_typing(bot, http):
    bot.send_chat_action()
    assert http.calls[0][1]["data"]["action"] == "typing"


def test_send_chat_action_error_status_raises(bot, http):
    http.status = 403
    with pytest.raises(RuntimeError):
        bot.send_chat_action()


@pytest.mark.parametrize("send,field,limit", [("send_message", "text", 4096), ("send_photo", "caption", 1024)])
def test_truncated_html_stays_well_formed(bot, http, send, field, limit):
    args = ("<b>" + "x" * (limit + 10) + "</b>",)
    getattr(bot, send)(*((b"PNG",) + args if send == "send_photo" else args))
    sent = http.calls[0][1]["data"][field]
    assert sent.count("<b>") == sent.count("</b>")


CASES = [("send_message", "text", 4096), ("send_photo", "caption", 1024)]


def _send(bot, send, text):
    getattr(bot, send)(*((b"PNG", text) if send == "send_photo" else (text,)))


@pytest.mark.parametrize("send,field,limit", CASES)
def test_truncated_html_is_plain_text_without_tags(bot, http, send, field, limit):
    _send(bot, send, "<b>" + "x" * (limit + 10) + "</b>")
    data = http.calls[0][1]["data"]
    assert data[field] == "x" * (limit - 1) + "…"
    assert "parse_mode" not in data


@pytest.mark.parametrize("send,field,limit", CASES)
def test_truncated_text_decodes_entities(bot, http, send, field, limit):
    _send(bot, send, "<i>a &amp; b &lt;c&gt;</i>" + "x" * limit)
    sent = http.calls[0][1]["data"][field]
    assert sent.startswith("a & b <c>x")
    assert len(sent) == limit


@pytest.mark.parametrize("send,field,limit", CASES)
def test_html_at_limit_is_sent_unchanged_with_parse_mode(bot, http, send, field, limit):
    text = "<b>" + "x" * (limit - 7) + "</b>"
    assert len(text) == limit
    _send(bot, send, text)
    data = http.calls[0][1]["data"]
    assert data[field] == text
    assert data["parse_mode"] == "HTML"
