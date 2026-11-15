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


def _date_arg(value: Optional[str]):
    """Parse an ISO-8601 date/datetime for --since / --until.

    A naive value is interpreted in the kernel's APP_TIMEZONE (Asia/Shanghai),
    matching how users phrase windows; the result is naive UTC to line up with
    the DB, which stores UTC as naive datetimes.
    """
    if value is None:
        return None
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    from zoneinfo import ZoneInfo

    from config import config as _config

    text = value.strip()
    if not text:
        return None
    try:
        parsed = _dt.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise UsageError(f"--since/--until expects ISO-8601, got '{value}'") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(_config.APP_TIMEZONE))
    parsed = parsed.astimezone(_tz.utc).replace(tzinfo=None)
    return parsed


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


def _refresh_flag(args: argparse.Namespace) -> Optional[bool]:
    """--refresh → True (wins), --no-refresh → False, neither → None (auto)."""
    if getattr(args, "refresh", False):
        return True
    if getattr(args, "no_refresh", False):
        return False
    return None


def _add_refresh_flags(p):
    p.add_argument("--refresh", action="store_true", help="force a live price refresh")
    p.add_argument("--no-refresh", action="store_true", help="skip any live price refresh")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="debrief", description="portfolio-agent data kernel CLI")
    parser.add_argument("--db", help="SQLite database path (default: DATABASE_URL / portfolio.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true", help="JSON envelope output (always on)")

    p = sub.add_parser("holdings", help="read current holdings or write (v2)")
    p.add_argument("--status", choices=["open"], default=None)
    _add_refresh_flags(p)
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
    p.add_argument("--since", default=None, help="ISO-8601 start (inclusive)")
    p.add_argument("--until", default=None, help="ISO-8601 end (exclusive)")
    add_json(p)

    p = sub.add_parser("watchlist", help="read the watchlist or write (v2)")
    p.add_argument("--ticker", default=None)
    _add_refresh_flags(p)
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
    prl = rep.add_parser("list", help="list reports in a window (newest first)")
    prl.add_argument("--market", default=None)
    prl.add_argument("--since", default=None)
    prl.add_argument("--until", default=None)
    prl.add_argument("--limit", default=None)
    add_json(prl)
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
    ml = mem.add_parser("list", help="list long-term memories (active by default)")
    ml.add_argument("--all", action="store_true", dest="memory_all", help="include retired topics")
    ml.add_argument("--limit", default=None)
    add_json(ml)
    mu = mem.add_parser("update", help="edit/restore a long-term memory (payload on stdin)")
    add_json(mu)
    mr = mem.add_parser("remove", help="delete a long-term memory (payload on stdin)")
    add_json(mr)

    p = sub.add_parser("analysis", help="prepare an after-market input package")
    an = p.add_subparsers(dest="analysis_command", required=True)
    ap = an.add_parser("prepare")
    ap.add_argument("--market", required=True)
    _add_refresh_flags(ap)
    add_json(ap)

    p = sub.add_parser("job", help="job ledger operations")
    jb = p.add_subparsers(dest="job_command", required=True)
    jl = jb.add_parser("list")
    jl.add_argument("--limit", default=None)
    jl.add_argument("--since", default=None, help="ISO-8601 start (inclusive)")
    jl.add_argument("--until", default=None, help="ISO-8601 end (exclusive)")
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
    _add_refresh_flags(p)
    add_json(p)

    p = sub.add_parser("news", help="read the collected news feed")
    nw = p.add_subparsers(dest="news_command", required=True)
    nl = nw.add_parser("latest", help="latest persisted news")
    nl.add_argument("--limit", default=None)
    nl.add_argument("--no-refresh", action="store_true", help="skip the upstream fetch")
    nl.add_argument("--notify", action="store_true", help="push a digest to Telegram when new items arrived")
    add_json(nl)

    p = sub.add_parser("fx", help="fetch FX cross rates (open.er-api.com)")
    p.add_argument("--base", default="CNY")
    add_json(p)

    p = sub.add_parser("notify", help="Telegram notification test/status")
    nt = p.add_subparsers(dest="notify_command", required=True)
    nt_test = nt.add_parser("test", help="send a test push")
    add_json(nt_test)
    nt_status = nt.add_parser("status", help="report configuration state (masked)")
    add_json(nt_status)

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
    if command == "memory" and args.memory_command in ("compact-write", "add", "update", "remove"):
        from debrief import commands as c

        payload = read_stdin_json()
        session, _ = open_session(resolve_db(args))
        try:
            if args.memory_command == "compact-write":
                return c.cmd_memory_compact_write(session, payload)
            if args.memory_command == "add":
                return c.cmd_memory_add(session, payload)
            if args.memory_command == "update":
                return c.cmd_memory_update(session, payload)
            return c.cmd_memory_remove(session, payload)
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

    # Stateless commands need no database session at all.
    if command == "fx":
        from debrief import commands as c

        return c.cmd_fx(args.base)
    if command == "notify":
        from debrief import commands as c

        if args.notify_command == "test":
            return c.cmd_notify_test()
        if args.notify_command == "status":
            return c.cmd_notify_status()
        raise UsageError(f"unknown notify subcommand: {args.notify_command}")

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
            return c.cmd_holdings(session, args.status, refresh=_refresh_flag(args))
        if command == "transactions":
            return c.cmd_transactions(
                session,
                args.ticker,
                _int_arg(args.limit, 20),
                _int_arg(args.offset, 0),
                since=_date_arg(getattr(args, "since", None)),
                until=_date_arg(getattr(args, "until", None)),
            )
        if command == "watchlist":
            return c.cmd_watchlist(session, args.ticker, refresh=_refresh_flag(args))
        if command == "instruments":
            if args.instruments_command != "search":
                raise UsageError(f"unknown instruments subcommand: {args.instruments_command}")
            return c.cmd_instruments(session, args.market, args.query)
        if command == "report":
            if args.report_command == "latest":
                return c.cmd_report_latest(session, args.market)
            if args.report_command == "list":
                return c.cmd_report_list(
                    session,
                    args.market,
                    since=_date_arg(getattr(args, "since", None)),
                    until=_date_arg(getattr(args, "until", None)),
                    limit=_int_arg(args.limit, 50),
                )
            if args.report_command is None and args.id:
                return c.cmd_report_by_id(session, args.id)
            raise UsageError(f"unknown report subcommand: {args.report_command}")
        if command == "memory":
            if args.memory_command == "search":
                return c.cmd_memory_search(session, args.query)
            if args.memory_command == "list":
                return c.cmd_memory_list(
                    session,
                    include_retired=bool(getattr(args, "memory_all", False)),
                    limit=_int_arg(args.limit, 100),
                )
            if args.memory_command == "compact-candidates":
                return c.cmd_memory_compact_candidates(session)
            raise UsageError(f"unknown memory subcommand: {args.memory_command}")
        if command == "analysis":
            if args.analysis_command != "prepare":
                raise UsageError(f"unknown analysis subcommand: {args.analysis_command}")
            return c.cmd_analysis_prepare(session, args.market, refresh=_refresh_flag(args))
        if command == "news":
            if args.news_command != "latest":
                raise UsageError(f"unknown news subcommand: {args.news_command}")
            return c.cmd_news_latest(
                session,
                _int_arg(args.limit, 20),
                refresh=not args.no_refresh,
                notify=args.notify,
            )
        if command == "job":
            if args.job_command == "list":
                return c.cmd_job_list(
                    session,
                    _int_arg(args.limit, 50),
                    since=_date_arg(getattr(args, "since", None)),
                    until=_date_arg(getattr(args, "until", None)),
                )
            if args.job_command == "start":
                return c.cmd_job_start(session, args.kind)
            if args.job_command == "status":
                return c.cmd_job_status(session, _int_arg(args.id, 0))
            if args.job_command == "finish":
                return c.cmd_job_finish(session, _int_arg(args.id, 0), args.status, args.error_code)
            raise UsageError(f"unknown job subcommand: {args.job_command}")
        if command == "dashboard":
            return c.cmd_dashboard(
                session, _range_arg(args.range), refresh=_refresh_flag(args)
            )
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
