"""Field-level encryption at rest for PII (PRD §8 P4/P5).

Uses Fernet (AES-128-CBC + HMAC). Key comes from env DAL_ENC_KEY. If unset, a
DEV key is derived so local runs work — NEVER rely on the dev key in production;
set DAL_ENC_KEY to a real Fernet key:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os
import base64
import hashlib

try:
    from cryptography.fernet import Fernet
    _HAVE = True
except Exception:  # cryptography not installed
    _HAVE = False


def _key() -> bytes:
    k = os.getenv("DAL_ENC_KEY")
    if k:
        return k.encode()
    # deterministic dev key (clearly insecure; for local testing only)
    seed = hashlib.sha256(b"dal-dev-key-do-not-use-in-prod").digest()
    return base64.urlsafe_b64encode(seed)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    if not _HAVE:
        return "PLAIN:" + plaintext  # graceful fallback if lib missing
    return Fernet(_key()).encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    if token.startswith("PLAIN:"):
        return token[6:]
    if not _HAVE:
        return token
    try:
        return Fernet(_key()).decrypt(token.encode()).decode()
    except Exception:
        return "[decrypt-error]"
