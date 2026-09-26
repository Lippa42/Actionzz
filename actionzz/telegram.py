"""Client Telegram minimale (Bot API via HTTPS, nessuna libreria extra)."""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 4096


class Telegram:
    """Se token o chat id mancano, stampa i messaggi a console (utile in prova)."""

    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token if token is not None else os.environ.get("TELEGRAM_TOKEN", "")
        self.chat_id = str(chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")).strip()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _call(self, method: str, timeout: float = 30, **kwargs) -> dict | list | None:
        if not self.token:
            return None
        try:
            r = requests.post(API.format(token=self.token, method=method), timeout=timeout, **kwargs)
            payload = r.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("Telegram %s fallito: %s", method, exc)
            return None
        if not payload.get("ok"):
            log.error("Telegram %s: %s", method, payload.get("description"))
            return None
        return payload.get("result")

    def send(self, text: str, chat_id: str | None = None) -> bool:
        chat = chat_id or self.chat_id
        if not (self.token and chat):
            print("----- [Telegram non configurato] -----\n" + text + "\n")
            return False
        ok = True
        for part in split_message(text):
            result = self._call(
                "sendMessage",
                data={"chat_id": chat, "text": part, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
            ok = ok and result is not None
        return ok

    def send_photo(self, png: bytes, caption: str = "", chat_id: str | None = None) -> bool:
        chat = chat_id or self.chat_id
        if not (self.token and chat):
            print(f"----- [Telegram non configurato] grafico ({len(png)} byte): {caption}")
            return False
        result = self._call(
            "sendPhoto",
            data={"chat_id": chat, "caption": caption[:1024], "parse_mode": "HTML"},
            files={"photo": ("grafico.png", png, "image/png")},
        )
        return result is not None

    def get_updates(self, offset: int = 0, timeout: int = 0) -> list[dict]:
        result = self._call(
            "getUpdates",
            timeout=timeout + 15,
            data={"offset": offset, "timeout": timeout, "allowed_updates": '["message"]'},
        )
        return result or []

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        import json

        self._call("setMyCommands", data={"commands": json.dumps([{"command": c, "description": d} for c, d in commands])})


def split_message(text: str, limit: int = MAX_TEXT) -> list[str]:
    """Divide un testo lungo sulle righe, senza spezzare i tag HTML di una riga."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # riga lunghissima: taglio brutale
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts
