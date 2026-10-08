from __future__ import annotations

import sqlite3

from lib.paths import DB


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    return con
