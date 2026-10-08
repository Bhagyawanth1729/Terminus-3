"""Independent Python reference for the depot transfer ledger contract.

Used only by the verifier to compute expected reports. Not shipped in the
agent environment.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from pathlib import Path

MAX_QTY = 999_999_999
MAX_VALUE = 999_999_999_999_999_999
REPORTS = (
    "closing-stock.dat",
    "open-transit.dat",
    "exceptions.dat",
    "summary.dat",
)


def _trim(text: str) -> str:
    return text.rstrip(" ")


def _is_blank(text: str) -> bool:
    return _trim(text) == ""


def _digits(text: str) -> bool:
    return len(text) > 0 and all("0" <= c <= "9" for c in text)


def _valid_date(text: str) -> bool:
    if not _digits(text) or len(text) != 8:
        return False
    year = int(text[0:4])
    month = int(text[4:6])
    day = int(text[6:8])
    if year == 0 or month < 1 or month > 12 or day < 1:
        return False
    return day <= monthrange(year, month)[1]


@dataclass
class Part:
    part: str
    cond: str
    cents: int
    active: str


@dataclass
class Stock:
    depot: str
    part: str
    cond: str
    qty: int


@dataclass
class Event:
    raw: str
    input_order: int
    event_id: str
    date: str
    seq_text: str
    seq: int
    seq_valid: bool
    etype: str
    ref: str
    transfer: str
    source: str
    dest: str
    part: str
    cond: str
    qty_text: str
    qty: int
    qty_valid: bool
    date_valid: bool
    accepted: bool = False
    rejected: str = ""
    voided: bool = False
    original: int = 0
    outstanding: int = 0
    active_received: int = 0
    dispatch_index: int = -1


@dataclass
class BatchResult:
    exit_code: int
    closing: str = ""
    transit: str = ""
    exceptions: str = ""
    summary: str = ""
    reports_present: bool = False


@dataclass
class LedgerState:
    parts: list[Part] = field(default_factory=list)
    stocks: list[Stock] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    exceptions: list[tuple[str, str]] = field(default_factory=list)
    input_count: int = 0
    accepted_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0
    fatal: bool = False


def _read_lines(path: Path) -> list[str]:
    data = path.read_bytes()
    text = data.decode("ascii")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return [line.rstrip("\r") for line in lines]


def _load_parts(path: Path, state: LedgerState) -> None:
    try:
        lines = _read_lines(path)
    except OSError:
        state.fatal = True
        return
    seen: set[tuple[str, str]] = set()
    for line in lines:
        if len(line) != 21:
            state.fatal = True
            return
        part_id = line[0:10]
        cond = line[10:11]
        cents_text = line[11:20]
        active = line[20:21]
        if _is_blank(part_id) or not _digits(cents_text) or active not in ("Y", "N"):
            state.fatal = True
            return
        key = (part_id, cond)
        if key in seen:
            state.fatal = True
            return
        seen.add(key)
        state.parts.append(Part(part_id, cond, int(cents_text), active))


def _load_stock(path: Path, state: LedgerState) -> None:
    try:
        lines = _read_lines(path)
    except OSError:
        state.fatal = True
        return
    seen: set[tuple[str, str, str]] = set()
    for line in lines:
        if len(line) != 26:
            state.fatal = True
            return
        depot = line[0:6]
        part_id = line[6:16]
        cond = line[16:17]
        qty_text = line[17:26]
        if _is_blank(depot) or not _digits(qty_text):
            state.fatal = True
            return
        part_idx = next(
            (i for i, p in enumerate(state.parts) if p.part == part_id and p.cond == cond),
            -1,
        )
        if part_idx < 0 or state.parts[part_idx].active != "Y":
            state.fatal = True
            return
        key = (depot, part_id, cond)
        if key in seen:
            state.fatal = True
            return
        seen.add(key)
        state.stocks.append(Stock(depot, part_id, cond, int(qty_text)))


def _load_events(path: Path, state: LedgerState) -> None:
    try:
        lines = _read_lines(path)
    except OSError:
        state.fatal = True
        return
    for order, line in enumerate(lines, start=1):
        if len(line) != 81:
            state.fatal = True
            return
        seq_text = line[20:24]
        qty_text = line[72:81]
        seq_valid = _digits(seq_text)
        qty_valid = _digits(qty_text)
        date = line[12:20]
        state.events.append(
            Event(
                raw=line,
                input_order=order,
                event_id=line[0:12],
                date=date,
                seq_text=seq_text,
                seq=int(seq_text) if seq_valid else 0,
                seq_valid=seq_valid,
                etype=line[24:25],
                ref=line[25:37],
                transfer=line[37:49],
                source=line[49:55],
                dest=line[55:61],
                part=line[61:71],
                cond=line[71:72],
                qty_text=qty_text,
                qty=int(qty_text) if qty_valid else 0,
                qty_valid=qty_valid,
                date_valid=_valid_date(date),
            )
        )
    state.input_count = len(state.events)


def _sort_events(state: LedgerState) -> None:
    # Stable bubble sort: date, then sequence, then event id. Equal keys keep input order.
    events = state.events
    n = len(events)
    if n < 2:
        return
    for i in range(n - 1):
        swapped = False
        for j in range(n - i - 1):
            left, right = events[j], events[j + 1]
            need = False
            if left.date > right.date:
                need = True
            elif left.date == right.date:
                if left.seq > right.seq:
                    need = True
                elif left.seq == right.seq and left.event_id > right.event_id:
                    need = True
            if need:
                events[j], events[j + 1] = events[j + 1], events[j]
                swapped = True
        if not swapped:
            break


def _find_part(state: LedgerState, ev: Event) -> int:
    for i, p in enumerate(state.parts):
        if p.part == ev.part and p.cond == ev.cond:
            return i
    return -1


def _find_stocks(state: LedgerState, ev: Event) -> tuple[int, int]:
    src = dst = -1
    for i, s in enumerate(state.stocks):
        if s.depot == ev.source and s.part == ev.part and s.cond == ev.cond:
            src = i
        if s.depot == ev.dest and s.part == ev.part and s.cond == ev.cond:
            dst = i
    return src, dst


def _find_accepted_ref(state: LedgerState, idx: int) -> int:
    ref = state.events[idx].ref
    for i in range(idx):
        ev = state.events[i]
        if ev.event_id == ref and ev.accepted:
            return i
    return -1


def _reject(state: LedgerState, idx: int, reason: str) -> None:
    ev = state.events[idx]
    if ev.rejected == "D":
        return
    ev.rejected = "Y"
    state.rejected_count += 1
    state.exceptions.append((_trim(ev.event_id), reason))


def _check_duplicate(state: LedgerState, idx: int) -> str | None:
    ev = state.events[idx]
    if _is_blank(ev.event_id):
        return "BAD_TRANSFER"
    owner = -1
    for i in range(idx):
        if state.events[i].event_id == ev.event_id:
            owner = i
            break
    if owner < 0:
        return None
    if state.events[owner].raw == ev.raw:
        state.duplicate_count += 1
        ev.rejected = "D"
        return None
    return "DUPLICATE_CONFLICT"


def _validate_common(ev: Event) -> str | None:
    if not ev.date_valid:
        return "BAD_DATE"
    if not ev.seq_valid:
        return "BAD_SEQUENCE"
    if ev.etype not in ("D", "R", "V"):
        return "BAD_TYPE"
    return None


def _process_dispatch(state: LedgerState, idx: int) -> str | None:
    ev = state.events[idx]
    if not _is_blank(ev.ref) or ev.transfer != ev.event_id:
        return "BAD_TRANSFER"
    if _is_blank(ev.source) or _is_blank(ev.dest) or ev.source == ev.dest:
        return "BAD_ROUTE"
    part_idx = _find_part(state, ev)
    src_idx, dst_idx = _find_stocks(state, ev)
    if part_idx < 0 or src_idx < 0 or dst_idx < 0:
        return "UNKNOWN_STOCK"
    if state.parts[part_idx].active != "Y":
        return "INACTIVE_PART"
    if not ev.qty_valid or ev.qty == 0:
        return "BAD_QUANTITY"
    if state.stocks[src_idx].qty < ev.qty:
        return "INSUFFICIENT_STOCK"
    state.stocks[src_idx].qty -= ev.qty
    ev.original = ev.qty
    ev.outstanding = ev.qty
    ev.active_received = 0
    ev.accepted = True
    state.accepted_count += 1
    return None


def _process_receipt(state: LedgerState, idx: int) -> str | None:
    ev = state.events[idx]
    if _is_blank(ev.ref) or ev.transfer != ev.ref:
        return "BAD_TRANSFER"
    ref_idx = _find_accepted_ref(state, idx)
    if ref_idx < 0:
        return "BAD_REFERENCE"
    ref = state.events[ref_idx]
    if ref.etype != "D" or ref.voided:
        return "BAD_REFERENCE"
    if (
        ev.source != ref.source
        or ev.dest != ref.dest
        or ev.part != ref.part
        or ev.cond != ref.cond
    ):
        return "BAD_ROUTE"
    if not ev.qty_valid or ev.qty == 0:
        return "BAD_QUANTITY"
    if ev.qty > ref.outstanding:
        return "EXCESS_RECEIPT"
    _, dst_idx = _find_stocks(state, ev)
    if dst_idx < 0:
        return "UNKNOWN_STOCK"
    product = state.stocks[dst_idx].qty + ev.qty
    if product > MAX_QTY:
        return "OVERFLOW"
    ref.outstanding -= ev.qty
    ref.active_received += ev.qty
    state.stocks[dst_idx].qty += ev.qty
    ev.dispatch_index = ref_idx
    ev.accepted = True
    state.accepted_count += 1
    return None


def _void_receipt(state: LedgerState, idx: int, ref_idx: int, dispatch_idx: int) -> str | None:
    ev = state.events[idx]
    ref = state.events[ref_idx]
    _, dst_idx = _find_stocks(state, ev)
    if dst_idx < 0:
        return "UNKNOWN_STOCK"
    if state.stocks[dst_idx].qty < ref.qty:
        return "INSUFFICIENT_STOCK"
    state.stocks[dst_idx].qty -= ref.qty
    state.events[dispatch_idx].outstanding += ref.qty
    state.events[dispatch_idx].active_received -= ref.qty
    ref.voided = True
    ev.accepted = True
    ev.dispatch_index = dispatch_idx
    state.accepted_count += 1
    return None


def _void_dispatch(state: LedgerState, idx: int, ref_idx: int) -> str | None:
    ev = state.events[idx]
    ref = state.events[ref_idx]
    if ref.active_received > 0:
        return "RECEIPTS_ACTIVE"
    src_idx, _ = _find_stocks(state, ev)
    if src_idx < 0:
        return "UNKNOWN_STOCK"
    product = state.stocks[src_idx].qty + ref.original
    if product > MAX_QTY:
        return "OVERFLOW"
    state.stocks[src_idx].qty += ref.original
    ref.outstanding = 0
    ref.voided = True
    ev.accepted = True
    ev.dispatch_index = ref_idx
    state.accepted_count += 1
    return None


def _process_void(state: LedgerState, idx: int) -> str | None:
    ev = state.events[idx]
    if _is_blank(ev.ref) or _is_blank(ev.transfer):
        return "BAD_TRANSFER"
    ref_idx = _find_accepted_ref(state, idx)
    if ref_idx < 0:
        return "BAD_REFERENCE"
    ref = state.events[ref_idx]
    if ref.etype not in ("D", "R"):
        return "BAD_REFERENCE"
    if ref.etype == "R":
        dispatch_idx = ref.dispatch_index
    else:
        dispatch_idx = ref_idx
    if ev.transfer != state.events[dispatch_idx].event_id:
        return "BAD_TRANSFER"
    if (
        ev.source != ref.source
        or ev.dest != ref.dest
        or ev.part != ref.part
        or ev.cond != ref.cond
        or ev.qty != ref.qty
    ):
        return "BAD_ROUTE"
    if not ev.qty_valid or ev.qty == 0:
        return "BAD_QUANTITY"
    if ref.voided:
        return "ALREADY_VOID"
    if ref.etype == "R":
        return _void_receipt(state, idx, ref_idx, dispatch_idx)
    return _void_dispatch(state, idx, ref_idx)


def _process_events(state: LedgerState) -> None:
    for idx, ev in enumerate(state.events):
        reason = _check_duplicate(state, idx)
        if reason is None and ev.rejected != "D":
            reason = _validate_common(ev)
        if reason is None and ev.rejected != "D":
            if ev.etype == "D":
                reason = _process_dispatch(state, idx)
            elif ev.etype == "R":
                reason = _process_receipt(state, idx)
            elif ev.etype == "V":
                reason = _process_void(state, idx)
        if reason is not None:
            _reject(state, idx, reason)


def _format_qty9(value: int) -> str:
    return f"{value:09d}"


def _write_closing(state: LedgerState) -> str:
    rows = sorted(state.stocks, key=lambda s: (s.depot, s.part, s.cond))
    lines = [f"{s.depot}{s.part}{s.cond}{_format_qty9(s.qty)}" for s in rows]
    return "\n".join(lines) + ("\n" if lines else "")


def _write_transit(state: LedgerState) -> str:
    open_rows = [
        ev
        for ev in state.events
        if ev.etype == "D"
        and ev.accepted
        and not ev.voided
        and ev.outstanding > 0
        and ev.rejected != "W"
    ]
    open_rows.sort(key=lambda e: e.event_id)
    lines = []
    for ev in open_rows:
        lines.append(
            f"{ev.event_id}{ev.source}{ev.dest}{ev.part}{ev.cond}"
            f"{_format_qty9(ev.original)}{_format_qty9(ev.outstanding)}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _write_exceptions(state: LedgerState) -> str:
    lines = [f"{eid}|{reason}" for eid, reason in state.exceptions]
    return "\n".join(lines) + ("\n" if lines else "")


def _write_summary(state: LedgerState) -> str | None:
    total_closing = 0
    onhand_value = 0
    for s in state.stocks:
        total_closing += s.qty
        if total_closing > MAX_VALUE:
            return None
        part = next(p for p in state.parts if p.part == s.part and p.cond == s.cond)
        product = s.qty * part.cents
        if product > MAX_VALUE:
            return None
        onhand_value += product
        if onhand_value > MAX_VALUE:
            return None

    total_transit = 0
    transit_value = 0
    for ev in state.events:
        if (
            ev.etype == "D"
            and ev.accepted
            and not ev.voided
            and ev.outstanding > 0
        ):
            total_transit += ev.outstanding
            if total_transit > MAX_VALUE:
                return None
            part = next(p for p in state.parts if p.part == ev.part and p.cond == ev.cond)
            product = ev.outstanding * part.cents
            if product > MAX_VALUE:
                return None
            transit_value += product
            if transit_value > MAX_VALUE:
                return None

    lines = [
        f"INPUT_COUNT={state.input_count}",
        f"ACCEPTED_COUNT={state.accepted_count}",
        f"DUPLICATE_COUNT={state.duplicate_count}",
        f"REJECTED_COUNT={state.rejected_count}",
        f"TOTAL_CLOSING_QTY={total_closing}",
        f"OPEN_TRANSIT_QTY={total_transit}",
        f"ONHAND_VALUE_CENTS={onhand_value}",
        f"TRANSIT_VALUE_CENTS={transit_value}",
    ]
    return "\n".join(lines) + "\n"


def run_ledger(parts_path: Path, stock_path: Path, events_path: Path) -> BatchResult:
    """Run one batch and return exit code plus report bodies (or empty on fatal)."""
    state = LedgerState()
    _load_parts(parts_path, state)
    if state.fatal:
        return BatchResult(exit_code=2)
    _load_stock(stock_path, state)
    if state.fatal:
        return BatchResult(exit_code=2)
    _load_events(events_path, state)
    if state.fatal:
        return BatchResult(exit_code=2)
    _sort_events(state)
    _process_events(state)
    summary = _write_summary(state)
    if summary is None:
        return BatchResult(exit_code=2)
    return BatchResult(
        exit_code=0,
        closing=_write_closing(state),
        transit=_write_transit(state),
        exceptions=_write_exceptions(state),
        summary=summary,
        reports_present=True,
    )
