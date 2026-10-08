from __future__ import annotations

import argparse
import sys

from lib import commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hrctl")
    sub = parser.add_subparsers(dest="cmd")
    t = sub.add_parser("transfer")
    t.add_argument("--employee", required=True)
    t.add_argument("--effective", required=True)
    t.add_argument("--cost-center", required=True)
    t.add_argument("--flsa", required=True, choices=["exempt", "non_exempt"])
    t.add_argument("--leave-plan", required=True)
    p = sub.add_parser("punch")
    p.add_argument("--employee", required=True)
    p.add_argument("--at", required=True)
    p.add_argument("--direction", required=True, choices=["in", "out"])
    lv = sub.add_parser("leave")
    lv.add_argument("--employee", required=True)
    lv.add_argument("--start", required=True)
    lv.add_argument("--end", required=True)
    lv.add_argument("--hours", required=True)
    lv.add_argument("--status", required=True, choices=["approved", "pending", "denied"])
    c = sub.add_parser("close-payroll")
    c.add_argument("--period", required=True)
    sub.add_parser("dump")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.cmd:
        print("usage: hrctl transfer|punch|leave|close-payroll|dump", file=sys.stderr)
        return 2
    payload = vars(args)
    if args.cmd == "transfer":
        return commands.cmd_transfer(payload)
    if args.cmd == "punch":
        return commands.cmd_punch(payload)
    if args.cmd == "leave":
        return commands.cmd_leave(payload)
    if args.cmd == "close-payroll":
        return commands.cmd_close(payload)
    if args.cmd == "dump":
        return commands.cmd_dump(payload)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
