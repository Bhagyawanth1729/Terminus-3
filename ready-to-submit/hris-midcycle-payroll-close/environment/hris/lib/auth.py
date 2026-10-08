from __future__ import annotations

import json

from lib.paths import IDP, TOKEN


def expected_token() -> str:
    data = json.loads(IDP.read_text(encoding="utf-8"))
    return f"{data['issuer']}.{data['subject']}.{data['audience']}.v1"


def token_ok() -> bool:
    # Starter: ignore the fake IdP file.
    return TOKEN.is_file()


def require_token() -> None:
    if not token_ok():
        raise SystemExit(3)
