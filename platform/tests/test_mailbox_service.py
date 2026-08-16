"""Tests for the temp-mail driver.

The parsing tests run against `fixtures/confirm-email.eml` — a real message
captured from the live service, carried across from the TypeScript driver. That
matters: both parsing bugs these tests pin (the quoted-printable split and the
truncating URL bound) are invisible against a synthetic message, because a
hand-written fixture doesn't wrap its own links at awkward places.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from services.mailbox import (
    DEFAULT_TIMEOUT_SECONDS,
    Mail,
    Mailbox,
    MailboxConfig,
    MailboxError,
    MailboxNoMatch,
    MailboxNotFound,
    create_mailbox,
    decode_quoted_printable,
    delete_mailbox,
    extract_reset_password_token,
    extract_urls,
    extract_verify_email_token,
    generate_mailbox_name,
    list_mails,
    wait_for_mail,
)

FIXTURE = Path(__file__).parent / "fixtures" / "confirm-email.eml"
CONFIG = MailboxConfig(base_url="https://mail.invalid/", admin_auth="secret-admin", domain="mail.invalid")


@pytest.fixture
def confirm_email() -> str:
    return FIXTURE.read_text(encoding="utf-8", errors="replace")


class TestConfig:
    def test_strips_trailing_slash(self):
        assert CONFIG.resolved().base_url == "https://mail.invalid"

    @pytest.mark.parametrize("field", ["base_url", "admin_auth", "domain"])
    def test_missing_field_fails_loudly(self, field):
        cfg = MailboxConfig(**{**CONFIG.__dict__, field: ""})
        with pytest.raises(MailboxError, match=field):
            cfg.resolved()

    def test_error_never_echoes_the_secret(self):
        """A MailboxError must be safe to log — it names fields, never values."""
        cfg = MailboxConfig(base_url="", admin_auth="super-secret-admin-auth", domain="d")
        with pytest.raises(MailboxError) as exc:
            cfg.resolved()
        assert "super-secret-admin-auth" not in str(exc.value)


class TestQuotedPrintable:
    def test_soft_line_breaks_removed_before_hex_decoding(self):
        """Order matters: a link split by a soft break must rejoin, not decode
        into two useless halves."""
        text = "https://host.example=\r\n/verify-email/TOKEN=3D1"
        assert decode_quoted_printable(text) == "https://host.example/verify-email/TOKEN=1"

    def test_real_message_yields_an_intact_host(self, confirm_email):
        decoded = decode_quoted_printable(confirm_email)
        assert "icecap.=" not in decoded, "soft break left in place — the host is truncated"


class TestExtractUrls:
    def test_finds_urls_in_the_real_message(self, confirm_email):
        urls = extract_urls(confirm_email)
        assert urls, "no URLs extracted from a message that certainly contains them"
        assert all(u.startswith("http") for u in urls)

    def test_deduplicates_preserving_order(self):
        raw = "see https://a.example/xxxxxxxxxx then https://b.example/yyyyyyyyyy and https://a.example/xxxxxxxxxx"
        assert extract_urls(raw) == ["https://a.example/xxxxxxxxxx", "https://b.example/yyyyyyyyyy"]

    def test_bound_is_well_above_any_real_token(self):
        """The bound was 300 once and silently truncated real tokens: a capped
        greedy quantifier returns a prefix instead of failing."""
        long_url = "https://host.example/verify-email/" + ("A" * 600)
        assert extract_urls(long_url) == [long_url]


class TestVerifyEmailToken:
    def test_reads_the_token_from_the_real_message(self, confirm_email):
        token = extract_verify_email_token(confirm_email)
        assert token
        # The captured message's token is 32 chars. A truncated read yields 24 —
        # plausible, and wrong. That asymmetry is the whole point of the fixture.
        assert len(token) == 32, f"expected a 32-char token, got {len(token)}: {token!r}"
        assert token.isalnum()

    def test_url_decodes_the_token(self):
        raw = "go to https://host.example/verify-email/AA%2FBB now"
        assert extract_verify_email_token(raw) == "AA/BB"

    def test_missing_link_names_what_it_saw(self):
        with pytest.raises(MailboxError, match="URLs seen"):
            extract_verify_email_token("no links here at all")


class TestResetPasswordToken:
    def test_path_form(self):
        raw = "reset: https://host.example/reset-password/TOKEN12345"
        assert extract_reset_password_token(raw) == "TOKEN12345"

    def test_query_parameter_form(self):
        """Not speculative generality: one line turns a backend switching to a
        query parameter from a baffling empty-token failure into a working read."""
        raw = "reset: https://host.example/reset-password?token=TOKEN12345&x=1"
        assert extract_reset_password_token(raw) == "TOKEN12345"

    def test_strips_query_and_fragment_from_the_path_form(self):
        raw = "reset: https://host.example/reset-password/TOKEN12345?lang=en#top"
        assert extract_reset_password_token(raw) == "TOKEN12345"

    def test_survives_a_jwt_length_token(self):
        """Same species as the verification-token truncation, different length.

        The reset token is a JWT and far longer than the 32-char confirmation
        token, so a capped pattern truncates it while still returning something
        that looks like a token. Flagged by the sibling suite, which hit exactly
        this with a capped \\S+ capture.
        """
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            + "a" * 400
            + ".c2lnbmF0dXJlLXBhZGRpbmctdGhhdC1rZWVwcy1nb2luZw"
        )
        raw = f"reset here: https://host.example/reset-password/{jwt}"
        assert extract_reset_password_token(raw) == jwt


class TestFixtureIntegrity:
    def test_captured_message_has_not_drifted(self):
        """Pin the fixture, because it now guards four implementations.

        This file is a copy of portal-client's, which test-hub also copied. Two
        copies of a fixture guarding two copies of a parser can drift apart
        silently, and then both sides stay green while disagreeing. A checksum
        turns that into a failing test.

        It does NOT cover the other failure mode: if the mail service changes its
        MIME encoding, every stale fixture keeps passing while every live parse
        breaks. That gap is real and unaddressed here.
        """
        import hashlib

        # Verified 2026-08-16: byte-identical across all three copies —
        # portal-client/src/test/fixtures/, test-hub/src/drivers/mail/fixtures/,
        # and this one. That shared baseline is what the pin protects.
        digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        assert digest == "cb3fc7c1d62739449d811e7cccf504abf61da4103736a8055ca3f6d133e1cf35", (
            "confirm-email.eml changed. If that was deliberate, re-pin this digest and tell "
            "whoever maintains the sibling copies; if not, the fixture has drifted."
        )


class TestMailboxNames:
    def test_generated_names_are_alphanumeric_and_prefixed(self):
        name = generate_mailbox_name()
        assert name.startswith("e2e")
        assert name.isalnum()

    def test_generated_names_differ(self):
        assert generate_mailbox_name() != generate_mailbox_name()

    def test_punctuated_name_is_rejected_rather_than_mangled(self):
        """The service strips punctuation silently, so the address would differ
        from the request and prefix-based pruning would match nothing."""
        with pytest.raises(MailboxError, match="alphanumeric"):
            create_mailbox(CONFIG, "e2e-1234-ab")


class TestCreateAndDelete:
    def test_create_returns_the_service_address_not_the_requested_name(self):
        with patch("services.mailbox._call") as call:
            call.return_value = {"address": "tmpe2eabc@mail.invalid", "address_id": 7, "jwt": "j"}
            box = create_mailbox(CONFIG, "e2eabc")
        assert box == Mailbox(address="tmpe2eabc@mail.invalid", address_id=7, jwt="j")

    def test_delete_keys_on_the_numeric_id(self):
        with patch("services.mailbox._call") as call:
            delete_mailbox(CONFIG, 42)
        assert "/admin/delete_address/42" in call.call_args.args[1]


class TestListMailsPrivilege:
    def test_jwt_uses_the_scoped_api_surface(self):
        """The polling loop must not need the full-service admin secret."""
        with patch("services.mailbox.httpx.request") as req:
            req.return_value.status_code = 200
            req.return_value.json.return_value = {"results": []}
            list_mails(CONFIG, "a@mail.invalid", jwt="scoped-token")
        url = req.call_args.args[1]
        headers = req.call_args.kwargs["headers"]
        assert "/api/mails" in url
        assert headers["Authorization"] == "Bearer scoped-token"
        assert "x-admin-auth" not in headers

    def test_without_jwt_falls_back_to_admin(self):
        with patch("services.mailbox.httpx.request") as req:
            req.return_value.status_code = 200
            req.return_value.json.return_value = {"results": []}
            list_mails(CONFIG, "a+b@mail.invalid")
        url = req.call_args.args[1]
        headers = req.call_args.kwargs["headers"]
        assert "/admin/mails" in url
        assert "a%2Bb%40mail.invalid" in url, "address must be URL-encoded"
        assert headers["x-admin-auth"] == "secret-admin"


def _mail(**kw) -> Mail:
    base = dict(id=1, message_id="m", source="s", address="a@mail.invalid", raw="body", created_at="now")
    return Mail(**{**base, **kw})


class TestWaitForMail:
    def test_returns_the_first_message_when_no_matcher(self):
        with patch("services.mailbox.list_mails", return_value=[_mail(id=9)]):
            assert wait_for_mail(CONFIG, "a@mail.invalid").id == 9

    def test_applies_the_matcher(self):
        mails = [_mail(id=1, raw="nope"), _mail(id=2, raw="wanted")]
        with patch("services.mailbox.list_mails", return_value=mails):
            got = wait_for_mail(CONFIG, "a@mail.invalid", matching=lambda m: "wanted" in m.raw)
        assert got.id == 2

    def test_mail_arrived_but_nothing_matched_is_its_own_failure(self):
        """'It arrived but said something else' and 'it never arrived' need
        different fixes, so they must not report identically."""
        with patch("services.mailbox.list_mails", return_value=[_mail()]), \
                patch("services.mailbox.time.sleep"):
            with pytest.raises(MailboxNoMatch, match="wrong expectation"):
                wait_for_mail(CONFIG, "a@mail.invalid", matching=lambda m: False,
                              timeout_seconds=0.01, poll_seconds=0)

    def test_nothing_arrived_consults_the_unknown_mailbox(self):
        with patch("services.mailbox.list_mails", return_value=[]), \
                patch("services.mailbox.time.sleep"), \
                patch("services.mailbox.list_unknown_mails",
                      return_value=[{"address": "tmptypo@mail.invalid"}]):
            with pytest.raises(MailboxNotFound, match="tmptypo@mail.invalid"):
                wait_for_mail(CONFIG, "a@mail.invalid", timeout_seconds=0.01, poll_seconds=0)

    def test_nothing_anywhere_says_the_platform_never_sent_it(self):
        with patch("services.mailbox.list_mails", return_value=[]), \
                patch("services.mailbox.time.sleep"), \
                patch("services.mailbox.list_unknown_mails", return_value=[]):
            with pytest.raises(MailboxNotFound, match="never sent it"):
                wait_for_mail(CONFIG, "a@mail.invalid", timeout_seconds=0.01, poll_seconds=0)

    def test_default_timeout_covers_observed_latency(self):
        """Verification mail has been observed at 60-120s; the TypeScript
        default of 60s sits exactly where it flakes."""
        assert DEFAULT_TIMEOUT_SECONDS >= 120

    def test_polls_with_the_jwt(self):
        with patch("services.mailbox.list_mails", return_value=[_mail()]) as lm:
            wait_for_mail(CONFIG, "a@mail.invalid", jwt="scoped")
        assert lm.call_args.kwargs["jwt"] == "scoped"
