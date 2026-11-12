from __future__ import annotations

import smtplib

import pytest

from app.services.app_config import MailConfig
from app.services.mail import (
    MailConfigError,
    MailSendError,
    html_to_text,
    send_mail,
)


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.kwargs = kwargs
        self.calls: list[tuple] = []
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def ehlo(self):
        self.calls.append(("ehlo",))

    def starttls(self, *, context=None):
        self.calls.append(("starttls", context))

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message, from_addr=None, to_addrs=None):
        self.calls.append(("send_message", message, from_addr, to_addrs))


@pytest.fixture(autouse=True)
def _clear_fake_smtp():
    FakeSMTP.instances.clear()


def _mail(**overrides: object) -> MailConfig:
    values: dict[str, object] = {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "security": "starttls",
        "username": "notify",
        "from_address": "notify@example.com",
        "from_name": "GitHub 工作流",
        "default_to": "ops@example.com",
    }
    values.update(overrides)
    return MailConfig(**values)


def _patch(monkeypatch, mail: MailConfig | None = None, password: str = "smtp-secret"):
    monkeypatch.setattr("app.services.mail.read_mail_config", lambda: mail or _mail())
    monkeypatch.setattr("app.services.mail.get_smtp_password", lambda: password)


def _sent_message(smtp: FakeSMTP):
    for call in smtp.calls:
        if call[0] == "send_message":
            return call[1]
    raise AssertionError("send_message was not called")


def test_starttls_login_and_message_content(monkeypatch) -> None:
    _patch(monkeypatch)
    monkeypatch.setattr("app.services.mail.smtplib.SMTP", FakeSMTP)

    send_mail("a@example.com, b@example.com", "主题", "<p>你好</p><script>bad()</script>")

    smtp = FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.example.com", 587, 10)
    assert [call[0] for call in smtp.calls[:4]] == ["ehlo", "starttls", "ehlo", "login"]
    assert smtp.calls[3] == ("login", "notify", "smtp-secret")
    assert smtp.calls[4][0] == "send_message"
    assert smtp.calls[4][2:] == ("notify@example.com", ["a@example.com", "b@example.com"])

    message = _sent_message(smtp)
    assert message["Subject"] == "主题"
    assert message["To"] == "a@example.com, b@example.com"
    assert "GitHub 工作流" in message["From"]
    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "你好" in plain
    assert "<p>你好</p>" in html
    assert "<script>" not in html
    assert "bad()" not in html


def test_ssl_uses_smtp_ssl(monkeypatch) -> None:
    _patch(monkeypatch, _mail(security="ssl", smtp_port=465, username=""))
    monkeypatch.setattr("app.services.mail.smtplib.SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(
        "app.services.mail.smtplib.SMTP",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("plain SMTP used")),
    )

    send_mail(["a@example.com"], "Subject", "<p>Hello</p>")

    smtp = FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 465)
    assert smtp.context is not None
    assert [call[0] for call in smtp.calls] == ["ehlo", "send_message"]


def test_none_security_skips_starttls_and_login(monkeypatch) -> None:
    _patch(monkeypatch, _mail(security="none", username=""))
    monkeypatch.setattr("app.services.mail.smtplib.SMTP", FakeSMTP)

    send_mail("a@example.com", "Subject", "<p>Hello</p>")

    smtp = FakeSMTP.instances[-1]
    assert [call[0] for call in smtp.calls] == ["send_message"]


def test_text_fallback_is_used(monkeypatch) -> None:
    _patch(monkeypatch)
    monkeypatch.setattr("app.services.mail.smtplib.SMTP", FakeSMTP)

    send_mail("a@example.com", "Subject", "<p>Hello</p>", text_fallback="plain fallback")

    message = _sent_message(FakeSMTP.instances[-1])
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "plain fallback"


def test_html_sanitization_removes_dangerous_content(monkeypatch) -> None:
    _patch(monkeypatch)
    monkeypatch.setattr("app.services.mail.smtplib.SMTP", FakeSMTP)
    body = (
        '<p onclick="evil()">ok</p>'
        '<a href="javascript:alert(1)">bad link</a>'
        '<a href="https://example.com">good link</a>'
        "<style>body{display:none}</style>"
        '<iframe src="https://evil.example"></iframe>'
    )

    send_mail("a@example.com", "Subject", body)

    message = _sent_message(FakeSMTP.instances[-1])
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "<p>ok</p>" in html
    assert "onclick" not in html
    assert "javascript:" not in html
    assert "<style" not in html
    assert "<iframe" not in html
    assert 'href="https://example.com"' in html
    assert 'rel="noopener noreferrer"' in html


@pytest.mark.parametrize(
    ("mail", "to", "subject", "html_body", "password", "code"),
    [
        (_mail(enabled=False), "a@example.com", "S", "<p>x</p>", "secret", "disabled"),
        (_mail(smtp_host=""), "a@example.com", "S", "<p>x</p>", "secret", "missing_host"),
        (_mail(smtp_port=0), "a@example.com", "S", "<p>x</p>", "secret", "missing_port"),
        (_mail(smtp_port=70000), "a@example.com", "S", "<p>x</p>", "secret", "invalid_port"),
        (_mail(security="tls"), "a@example.com", "S", "<p>x</p>", "secret", "invalid_security"),
        (_mail(from_address=""), "a@example.com", "S", "<p>x</p>", "secret", "missing_from"),
        (_mail(from_address="not-an-address"), "a@example.com", "S", "<p>x</p>", "secret", "invalid_from"),
        (_mail(), "a@example.com", "S", "<p>x</p>", "", "missing_password"),
        (_mail(), "", "S", "<p>x</p>", "secret", "missing_recipient"),
        (_mail(), "a@example.com", "", "<p>x</p>", "secret", "empty_message"),
        (_mail(), "a@example.com", "S", "", "secret", "empty_message"),
        (_mail(), "a@example.com", "bad\r\nBcc: x@example.com", "<p>x</p>", "secret", "invalid_header"),
        (_mail(), "a@example.com\r\nBcc: x@example.com", "S", "<p>x</p>", "secret", "invalid_recipient"),
        (_mail(from_name="Name\nBcc: x@example.com"), "a@example.com", "S", "<p>x</p>", "secret", "invalid_header"),
        (_mail(), "not-an-address", "S", "<p>x</p>", "secret", "invalid_recipient"),
    ],
)
def test_send_mail_config_errors(monkeypatch, mail, to, subject, html_body, password, code) -> None:
    _patch(monkeypatch, mail, password)
    monkeypatch.setattr("app.services.mail.smtplib.SMTP", FakeSMTP)

    with pytest.raises(MailConfigError) as exc_info:
        send_mail(to, subject, html_body)

    assert exc_info.value.code == code
    assert FakeSMTP.instances == []


def test_smtp_exception_is_wrapped_without_password(monkeypatch) -> None:
    _patch(monkeypatch, password="smtp-secret")

    class FailingSMTP(FakeSMTP):
        def send_message(self, message, from_addr=None, to_addrs=None):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr("app.services.mail.smtplib.SMTP", FailingSMTP)

    with pytest.raises(MailSendError) as exc_info:
        send_mail("a@example.com", "Subject", "<p>Hello</p>")

    assert exc_info.value.code == "smtp_error"
    assert "SMTPAuthenticationError" in str(exc_info.value)
    assert "smtp.example.com:587/starttls" in str(exc_info.value)
    assert "smtp-secret" not in str(exc_info.value)


def test_smtp_disconnected_includes_port_hint(monkeypatch) -> None:
    _patch(
        monkeypatch,
        _mail(security="starttls", smtp_port=465, username="u"),
        password="smtp-secret",
    )

    class DroppingSMTP(FakeSMTP):
        def ehlo(self):
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    monkeypatch.setattr("app.services.mail.smtplib.SMTP", DroppingSMTP)

    with pytest.raises(MailSendError) as exc_info:
        send_mail("a@example.com", "Subject", "<p>Hello</p>")

    assert exc_info.value.code == "smtp_error"
    assert "SMTPServerDisconnected" in str(exc_info.value)
    assert "465→SSL" in str(exc_info.value)
    assert "smtp-secret" not in str(exc_info.value)


def test_sanitize_failure_never_sends(monkeypatch) -> None:
    _patch(monkeypatch)
    monkeypatch.setattr("app.services.mail.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr(
        "app.services.mail.sanitize_html",
        lambda _html: (_ for _ in ()).throw(ValueError("bad html")),
    )

    with pytest.raises(MailSendError) as exc_info:
        send_mail("a@example.com", "Subject", "<p>Hello</p>")

    assert exc_info.value.code == "sanitize_error"
    assert FakeSMTP.instances == []


def test_html_to_text_roughly_flattens_blocks() -> None:
    text = html_to_text("<h2>标题</h2><p>第一段</p><p>第二段<br>换行</p>")
    assert "标题" in text
    assert "第一段" in text
    assert "第二段" in text
    assert "换行" in text
    assert "<" not in text
