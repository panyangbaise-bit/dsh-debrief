"""debrief kernel CLI — single-line JSON envelope on stdout, UTF-8.

Every command prints exactly one JSON envelope:
    {"ok":true,"schemaVersion":1,"data":{...}}
    {"ok":false,"schemaVersion":1,"error":{"code":"DEBRIEF_XXX","message":"..."}}
Failures exit non-zero (2 = usage, 1 = runtime).
"""

import argparse
import logging
import sys
from typing import Optional

from debrief.errors import (
    KernelError,
    UsageError,
    fail_and_exit,
    ok,
    print_envelope,
    read_stdin_json,
)

logging.basicConfig(
    # CLI runs are single-shot subprocesses: keep stderr quiet so the plugin's
    # error path (which folds stderr into messages) stays readable. The worker
    # command raises this back to INFO for operational logs.
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)

RANGES = (30, 90, 200, 365)


def _int_arg(value: Optional[str], default: int, minimum: int = 0) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        raise UsageError(f"expected an integer, got '{value}'") from None
    return max(minimum, parsed)


def _range_arg(value: Optional[str]) -> int:
    if value is None:
        return 90
    try:
        parsed = int(value)
    except ValueError:
        raise UsageError(f"--range must be one of {RANGES}") from None
    if parsed not in RANGES:
        raise UsageError(f"--range must be one of {RANGES}; got {parsed}")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="debrief", description="portfolio-agent data kernel CLI")
    parser.add_argument("--db", help="SQLite database path (default: DATABASE_URL / portfolio.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true", help="JSON envelope output (always on)")

    p = sub.add_parser("holdings", help="read current holdings or write (v2)")
    p.add_argument("--status", choices=["open"], default=None)
    add_json(p)
    hold = p.add_subparsers(dest="holdings_command", required=False)
    for action, help_text in (
        ("add", "add a holding (payload on stdin)"),
        ("update", "update a holding (payload on stdin)"),
        ("remove", "remove a holding (payload on stdin)"),
    ):
        ph = hold.add_parser(action, help=help_text)
        add_json(ph)

    p = sub.add_parser("transactions", help="list executed trades, newest first")
    p.add_argument("--ticker", default=None)
    p.add_argument("--limit", default=None)
    p.add_argument("--offset", default=None)
    add_json(p)

    p = sub.add_parser("watchlist", help="read the watchlist or write (v2)")
    p.add_argument("--ticker", default=None)
    add_json(p)
    watch = p.add_subparsers(dest="watchlist_command", required=False)
    for action, help_text in (
        ("add", "add a watchlist item (payload on stdin)"),
        ("update", "update a watchlist item (payload on stdin)"),
        ("remove", "remove a watchlist item (payload on stdin)"),
    ):
        pw = watch.add_parser(action, help=help_text)
        add_json(pw)

    p = sub.add_parser("instruments", help="search investable instruments")
    instr = p.add_subparsers(dest="instruments_command", required=True)
    ps = instr.add_parser("search")
    ps.add_argument("--market", required=True)
    ps.add_argument("--query", required=True)
    add_json(ps)

    p = sub.add_parser("report", help="read/create analysis reports")
    rep = p.add_subparsers(dest="report_command", required=False)
    pl = rep.add_parser("latest")
    pl.add_argument("--market", default=None)
    add_json(pl)
    pi = rep.add_parser("create", help="create a report (payload on stdin)")
    add_json(pi)
    p.add_argument("--id", default=None, help="report id (alternative to 'latest')")
    add_json(p)

    p = sub.add_parser("memory", help="search/compact/add investment memory")
    mem = p.add_subparsers(dest="memory_command", required=True)
    ms = mem.add_parser("search")
    ms.add_argument("--query", required=True)
    add_json(ms)
    mc = mem.add_parser("compact-candidates", help="uncompacted docs past the window")
    add_json(mc)
    mw = mem.add_parser("compact-write", help="write a long-term memory (payload on stdin)")
    add_json(mw)
    ma = mem.add_parser("add", help="append an evidence snapshot (payload on stdin)")
    add_json(ma)

    p = sub.add_parser("analysis", help="prepare an after-market input package")
    an = p.add_subparsers(dest="analysis_command", required=True)
    ap = an.add_parser("prepare")
    ap.add_argument("--market", required=True)
    add_json(ap)

    p = sub.add_parser("job", help="job ledger operations")
    jb = p.add_subparsers(dest="job_command", required=True)
    jl = jb.add_parser("list")
    jl.add_argument("--limit", default=None)
    add_json(jl)
    js = jb.add_parser("start")
    js.add_argument("--kind", required=True)
    add_json(js)
    jst = jb.add_parser("status")
    jst.add_argument("--id", required=True)
    add_json(jst)
    jf = jb.add_parser("finish")
    jf.add_argument("--id", required=True)
    jf.add_argument("--status", required=True)
    jf.add_argument("--error-code", default=None)
    add_json(jf)

    p = sub.add_parser("dashboard", help="dashboard aggregate")
    p.add_argument("--range", default=None)
    add_json(p)

    p = sub.add_parser("migrate", help="apply pending migrations (idempotent)")
    add_json(p)

    p = sub.add_parser("worker", help="APScheduler data-collection worker (no LLM)")
    p.add_argument("--dry-run", action="store_true", help="print the schedule and exit")
    add_json(p)
    return parser


def dispatch(args: argparse.Namespace) -> dict:
    from debrief.context import open_engine, open_session

    command = args.command

    # Write commands read their JSON payload from stdin and need no session.
    if command == "memory" and args.memory_command in ("compact-write", "add"):
        from debrief import commands as c

        payload = read_stdin_json()
        session, _ = open_session(resolve_db(args))
        try:
            if args.memory_command == "compact-write":
                return c.cmd_memory_compact_write(session, payload)
            return c.cmd_memory_add(session, payload)
        finally:
            session.close()
    if command == "report" and args.report_command == "create":
        from debrief import commands as c

        payload = read_stdin_json()
        session, _ = open_session(resolve_db(args))
        try:
            return c.cmd_report_create(session, payload)
        finally:
            session.close()

    # v2 white-list writes (holdings / watchlist) read stdin JSON.
    if command == "holdings" and getattr(args, "holdings_command", None) in ("add", "update", "remove"):
        from debrief import commands as c

        payload = read_stdin_json()
        session, _ = open_session(resolve_db(args))
        try:
            handler = getattr(c, f"cmd_holdings_{args.holdings_command}")
            return handler(session, payload)
        finally:
            session.close()
    if command == "watchlist" and getattr(args, "watchlist_command", None) in ("add", "update", "remove"):
        from debrief import commands as c

        payload = read_stdin_json()
        session, _ = open_session(resolve_db(args))
        try:
            handler = getattr(c, f"cmd_watchlist_{args.watchlist_command}")
            return handler(session, payload)
        finally:
            session.close()

    if command == "migrate":
        from debrief import commands as c

        engine = open_engine(resolve_db(args), migrate=False)
        return c.cmd_migrate(engine)

    if command == "worker":
        # Long-running worker keeps INFO operational logs on stderr.
        logging.getLogger().setLevel(logging.INFO)
        try:
            from debrief.worker import run_worker
        except ModuleNotFoundError as exc:
            raise KernelError(
                "DEBRIEF_MISSING_COLLECTORS",
                "worker needs the collectors extra: "
                "pip install 'portfolio-agent-kernel[collectors]' "
                f"(missing module: {exc.name})",
            ) from None
        return run_worker(args.dry_run, resolve_db(args))

    from debrief import commands as c

    session, _ = open_session(resolve_db(args))
    try:
        if command == "holdings":
            return c.cmd_holdings(session, args.status)
        if command == "transactions":
            return c.cmd_transactions(
                session, args.ticker, _int_arg(args.limit, 20), _int_arg(args.offset, 0)
            )
        if command == "watchlist":
            return c.cmd_watchlist(session, args.ticker)
        if command == "instruments":
            if args.instruments_command != "search":
                raise UsageError(f"unknown instruments subcommand: {args.instruments_command}")
            return c.cmd_instruments(session, args.market, args.query)
        if command == "report":
            if args.report_command == "latest":
                return c.cmd_report_latest(session, args.market)
            if args.report_command is None and args.id:
                return c.cmd_report_by_id(session, args.id)
            raise UsageError(f"unknown report subcommand: {args.report_command}")
        if command == "memory":
            if args.memory_command == "search":
                return c.cmd_memory_search(session, args.query)
            if args.memory_command == "compact-candidates":
                return c.cmd_memory_compact_candidates(session)
            raise UsageError(f"unknown memory subcommand: {args.memory_command}")
        if command == "analysis":
            if args.analysis_command != "prepare":
                raise UsageError(f"unknown analysis subcommand: {args.analysis_command}")
            return c.cmd_analysis_prepare(session, args.market)
        if command == "job":
            if args.job_command == "list":
                return c.cmd_job_list(session, _int_arg(args.limit, 50))
            if args.job_command == "start":
                return c.cmd_job_start(session, args.kind)
            if args.job_command == "status":
                return c.cmd_job_status(session, _int_arg(args.id, 0))
            if args.job_command == "finish":
                return c.cmd_job_finish(session, _int_arg(args.id, 0), args.status, args.error_code)
            raise UsageError(f"unknown job subcommand: {args.job_command}")
        if command == "dashboard":
            return c.cmd_dashboard(session, _range_arg(args.range))
        raise UsageError(f"unknown command: {command}")
    finally:
        session.close()


def resolve_db(args: argparse.Namespace):
    from debrief.context import resolve_db_path

    return resolve_db_path(getattr(args, "db", None))


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits 2 on usage errors
        print_envelope(
            {
                "ok": False,
                "schemaVersion": 1,
                "error": {"code": "DEBRIEF_USAGE", "message": "invalid command line"},
            }
        )
        return exc.code if isinstance(exc.code, int) else 2

    try:
        payload = dispatch(args)
        print_envelope(ok(payload))
        return 0
    except KernelError as err:
        fail_and_exit(err)
    except Exception as exc:  # never leak tracebacks into stdout
        logging.getLogger("debrief.cli").exception("unexpected failure")
        print_envelope(
            {
                "ok": False,
                "schemaVersion": 1,
                "error": {"code": "DEBRIEF_INTERNAL", "message": f"{type(exc).__name__}: {exc}"},
            }
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
