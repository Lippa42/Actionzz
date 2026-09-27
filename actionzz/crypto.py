"""Cifratura dei dati personali (portafoglio), compatibile con la dashboard.

Formato: PBKDF2-SHA256 per ricavare la chiave dalla password, AES-256-GCM per
cifrare il JSON. La dashboard usa lo stesso schema con WebCrypto, quindi i
file si leggono e si scrivono da entrambe le parti. Nel repository (pubblico)
finisce solo la busta cifrata.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 310_000


class WrongPassword(Exception):
    pass


def _key(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)


def encrypt_json(obj, password: str, iterations: int = ITERATIONS) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    data = AESGCM(_key(password, salt, iterations)).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": iterations, "salt": b64(salt), "iv": b64(iv), "data": b64(data)}


def decrypt_json(envelope: dict, password: str):
    try:
        salt = base64.b64decode(envelope["salt"])
        iv = base64.b64decode(envelope["iv"])
        data = base64.b64decode(envelope["data"])
        plain = AESGCM(_key(password, salt, int(envelope["iter"]))).decrypt(iv, data, None)
    except Exception as exc:  # tag GCM non valido = password sbagliata o file alterato
        raise WrongPassword("Password errata o file danneggiato") from exc
    return json.loads(plain.decode("utf-8"))
