"""An organisation's own mail host (12 Oct 2026).

Innodhara's account is admin@innodhara.com, hosted by Zoho, but every send went
to the server's smtp.gmail.com and failed: Innodhara had never sent an email.
YuviPep's gmail.com account must take exactly the path it always took.
"""
from __future__ import annotations

import pytest

from app.core.crypto import encrypt_secret
from app.services import email_service as es


@pytest.fixture(autouse=True)
def fresh_cache():
    es._mx_cache.clear()
    yield
    es._mx_cache.clear()


def _mx(monkeypatch, table):
    calls = []

    def fake(domain):
        calls.append(domain)
        return table.get(domain, [])
    monkeypatch.setattr(es, "_mx_hosts", fake)
    return calls


def test_a_gmail_account_never_looks_anything_up(monkeypatch):
    calls = _mx(monkeypatch, {})
    assert es._smtp_server_for("sales@gmail.com") is None
    assert es._smtp_server_for("x@googlemail.com") is None
    assert calls == []


def test_a_zoho_hosted_domain_uses_zoho(monkeypatch):
    _mx(monkeypatch, {"innodhara.com": ["mx.zoho.in", "mx2.zoho.in"]})
    assert es._smtp_server_for("admin@innodhara.com") == ("smtp.zoho.in", 587)


def test_google_hosted_and_unknown_domains_keep_the_server_host(monkeypatch):
    _mx(monkeypatch, {"workspace-example.com": ["aspmx.l.google.com"],
                      "odd-example.com": ["mail.odd-example.com"]})
    assert es._smtp_server_for("a@workspace-example.com") is None
    assert es._smtp_server_for("a@odd-example.com") is None
    assert es._smtp_server_for("a@nothing-example.com") is None


def test_the_lookup_is_made_once_per_domain(monkeypatch):
    calls = _mx(monkeypatch, {"innodhara.com": ["mx.zoho.in"]})
    es._smtp_server_for("admin@innodhara.com")
    es._smtp_server_for("sales@innodhara.com")
    assert calls == ["innodhara.com"]


def test_org_credentials_carry_the_host(monkeypatch):
    _mx(monkeypatch, {"innodhara.com": ["mx.zoho.in"]})
    creds = es.resolve_credentials(
        user_email="ajith@innodhara.com", user_app_password_enc=None,
        org_email_integration={"smtp_username": "admin@innodhara.com",
                               "smtp_app_password_enc": encrypt_secret("pw")})
    assert (creds.username, creds.host, creds.port) == (
        "admin@innodhara.com", "smtp.zoho.in", 587)


def test_a_stored_host_wins_over_the_lookup(monkeypatch):
    calls = _mx(monkeypatch, {"innodhara.com": ["mx.zoho.in"]})
    creds = es.resolve_credentials(
        user_email="", user_app_password_enc=None,
        org_email_integration={"smtp_username": "admin@innodhara.com",
                               "smtp_app_password_enc": encrypt_secret("pw"),
                               "smtp_host": "smtp.example.net", "smtp_port": 2525})
    assert (creds.host, creds.port) == ("smtp.example.net", 2525)
    assert calls == []


def test_yuvipep_shaped_credentials_are_unchanged(monkeypatch):
    calls = _mx(monkeypatch, {})
    creds = es.resolve_credentials(
        user_email="rahul@yuvipep.com", user_app_password_enc=None,
        org_email_integration={"smtp_username": "yuvipep.sales@gmail.com",
                               "smtp_app_password_enc": encrypt_secret("pw")})
    assert (creds.host, creds.port) == (None, None)
    assert calls == []


def _payload():
    return es.EmailPayload(sender_name="Ajith Kumar", sender_email="ajith@innodhara.com",
                           to_address="client@example.com", subject="s", body="b")


def test_the_from_is_the_login_only_on_an_own_host():
    payload = _payload()
    msg = es._build_mime(payload)
    es._sender_for_host(msg, payload, es.SmtpCredentials(
        "admin@innodhara.com", "pw", host="smtp.zoho.in", port=587))
    assert msg["From"] == "Ajith Kumar <admin@innodhara.com>"
    assert msg["Reply-To"] == "ajith@innodhara.com"


def test_the_server_host_keeps_the_salespersons_from():
    payload = _payload()
    msg = es._build_mime(payload)
    es._sender_for_host(msg, payload, es.SmtpCredentials("x@gmail.com", "pw"))
    assert msg["From"] == "Ajith Kumar <ajith@innodhara.com>"
    assert msg["Reply-To"] is None


def test_the_send_goes_to_the_accounts_host(monkeypatch):
    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            seen["server"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            seen["login"] = user

        def send_message(self, msg, to_addrs):
            seen["to"] = to_addrs

    monkeypatch.setattr(es.smtplib, "SMTP", FakeSMTP)
    msg = es._build_mime(_payload())
    es._smtp_send_sync(msg, es.SmtpCredentials(
        "admin@innodhara.com", "pw", host="smtp.zoho.in", port=587), ["c@x.com"])
    assert seen["server"] == ("smtp.zoho.in", 587)
    es._smtp_send_sync(msg, es.SmtpCredentials("x@gmail.com", "pw"), ["c@x.com"])
    settings = es.get_settings()
    assert seen["server"] == (settings.smtp_host, settings.smtp_port)
