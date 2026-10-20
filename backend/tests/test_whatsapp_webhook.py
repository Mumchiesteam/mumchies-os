"""WhatsApp signature verification tests (no Meta credentials required)."""
import hashlib
import hmac

from app.api.routes.whatsapp import verify_meta_signature


def test_valid_signature():
    secret = "example-test-secret"
    body = b'{"object":"whatsapp_business_account"}'
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_meta_signature(body, signature, secret)


def test_modified_payload_rejected():
    secret = "example-test-secret"
    body = b'{"object":"whatsapp_business_account"}'
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert not verify_meta_signature(body + b" ", signature, secret)


def test_missing_signature_rejected():
    assert not verify_meta_signature(b"{}", None, "secret")


def test_missing_secret_rejected():
    assert not verify_meta_signature(b"{}", "sha256=anything", None)
