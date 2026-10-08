from __future__ import annotations

import os
from pathlib import Path

ROOT = Path("/app/hris")
DB = Path(os.environ.get("HRIS_DB", str(ROOT / "var" / "hris.db")))
OUT = Path(os.environ.get("HRIS_OUT", str(ROOT / "out")))
TOKEN = Path(os.environ.get("HRIS_TOKEN", str(ROOT / "var" / "idp.token")))
IDP = Path(os.environ.get("HRIS_IDP", str(ROOT / "var" / "idp.json")))
INCLUDED_STATUSES = {"active", "leave_of_absence", "seasonal", "contractor"}
