"""Distribution guardrails: CLI stays collector-free, slim wheel is slim."""

import ast
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WHEEL_VERSION = "0.2.2"  # bump on EVERY wheel content change (cache-key rule)
COLLECTOR_MODULES = (
    "yfinance",
    "akshare",
    "pycoingecko",
    "apscheduler",
    "telegram",
    "streamlit",
    "yaml",
    "tomlkit",
)


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = set()
    for node in tree.body:  # module level only — lazy in-function imports allowed
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


@pytest.mark.parametrize(
    "module_file",
    [path.name for path in (REPO_ROOT / "debrief").glob("*.py")],
)
def test_cli_modules_do_not_eagerly_import_collectors(module_file):
    """Every debrief module except worker.py stays collector-free at import."""
    if module_file == "worker.py":
        pytest.skip("worker is the collector entry point; loaded on demand only")
    imported = _top_level_imports(REPO_ROOT / "debrief" / module_file)
    assert not (imported & set(COLLECTOR_MODULES)), (
        f"debrief/{module_file} imports {imported & set(COLLECTOR_MODULES)} at module level"
    )


def test_cli_entry_surface_loads_without_collectors():
    """Fresh interpreter: importing the CLI surface loads no collector package."""
    script = (
        "import sys;"
        "mods=['debrief.cli','debrief.commands','debrief.kernel','debrief.catalog',"
        "'debrief.context','debrief.errors','db.models','db.repository','db.migrate',"
        "'domain.valuation','domain.markets','memory.capture','memory.indexer',"
        "'memory.retrieval','config'];"
        "[__import__(m) for m in mods];"
        "bad=[n for n in %r if n in sys.modules];"
        "print('BAD:',','.join(bad) or 'none');"
        "sys.exit(1 if bad else 0)" % (COLLECTOR_MODULES,)
    )
    env = {
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"collector import leaked: {result.stdout} {result.stderr}"


def test_worker_without_collectors_returns_structured_error(seeded_db, run_cli, monkeypatch):
    """`debrief worker` without apscheduler → DEBRIEF_MISSING_COLLECTORS envelope."""
    monkeypatch.setitem(sys.modules, "apscheduler", None)
    monkeypatch.setitem(sys.modules, "debrief.worker", None)
    code, payload = run_cli(
        ["--db", str(seeded_db), "worker", "--dry-run"]
    )
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "DEBRIEF_MISSING_COLLECTORS"
    assert "collectors" in payload["error"]["message"]


def test_artifacts_has_no_stale_wheel_versions():
    """Same-version overwrite is forbidden: pip/uv caches key on the filename."""
    assert list((REPO_ROOT / "artifacts").glob("portfolio_agent_kernel-*.whl")) == [
        REPO_ROOT / "artifacts" / f"portfolio_agent_kernel-{WHEEL_VERSION}-py3-none-any.whl"
    ]


def test_committed_slim_wheel_contains_only_cli_modules():
    wheels = sorted((REPO_ROOT / "artifacts").glob("portfolio_agent_kernel-*.whl"))
    assert wheels, "no committed slim wheel in artifacts/"
    wheel = wheels[-1]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "debrief/cli.py" in names
        assert "db/models.py" in names
        assert "db/repository.py" in names
        assert "config.py" in names
        top = {name.split("/")[0] for name in names}
        assert top <= {
            "adapters",
            "common",
            "config.py",
            "db",
            "debrief",
            "domain",
            "memory",
            f"portfolio_agent_kernel-{WHEEL_VERSION}.dist-info",
        }
        assert {"debrief", "db", "config.py"} <= top
        # CLI needs the lightweight FX layer; market adapters stay out.
        assert "adapters/fx.py" in names
        assert "adapters/base.py" in names
        assert "adapters/__init__.py" in names
        assert not any(
            name.startswith(("app/", "scheduler/", "notifier/")) for name in names
        )
        adapter_files = [name for name in names if name.startswith("adapters/")]
        assert adapter_files == ["adapters/__init__.py", "adapters/base.py", "adapters/fx.py"]
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode()
        assert f"Version: {WHEEL_VERSION}" in metadata
        # Core requirements are unconditional; collectors only behind the extra.
        assert "Requires-Dist: sqlalchemy>=2.0.0\n" in metadata
        assert "Requires-Dist: requests>=2.31.0\n" in metadata
        assert "Requires-Dist: python-dotenv>=1.0.0\n" in metadata
        assert 'Requires-Dist: akshare>=1.14.0; extra == "collectors"' in metadata
        assert 'Requires-Dist: yfinance>=0.2.40; extra == "collectors"' in metadata
        assert "Requires-Dist: akshare>=1.14.0\n" not in metadata
        entry_points_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        entry_points = archive.read(entry_points_name).decode()
        assert "debrief = debrief.cli:main" in entry_points


def _latest_wheel() -> Path:
    wheels = sorted((REPO_ROOT / "artifacts").glob("portfolio_agent_kernel-*.whl"))
    assert wheels, "no committed slim wheel in artifacts/"
    return wheels[-1]


def test_wheel_install_cli_works_outside_repo(tmp_path):
    """Real install: fresh venv, wheel only, cwd outside the repo, no PYTHONPATH.

    Guards against the cwd-shadows-source failure mode (repo root on
    sys.path masking a module missing from the wheel).
    """
    import shutil

    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not available")
    venv = tmp_path / "venv"
    python = venv / "bin" / "python"
    debrief_bin = venv / "bin" / "debrief"
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    db_path = tmp_path / "isolated.db"

    def run(args, **kwargs):
        return subprocess.run(args, capture_output=True, text=True, timeout=300, **kwargs)

    run([uv, "venv", "-p", "3.11", str(venv)], check=True)
    core = ["sqlalchemy>=2.0.0", "requests>=2.31.0", "python-dotenv>=1.0.0"]
    install = [
        uv,
        "pip",
        "install",
        "-p",
        str(python),
        "--offline",
        str(_latest_wheel()),
        *core,
    ]
    result = run(install)
    if result.returncode != 0:  # cold cache → retry online; fail → skip
        result = run([uv, "pip", "install", "-p", str(python), str(_latest_wheel()), *core])
        if result.returncode != 0:
            pytest.skip(f"cannot provision isolated venv: {result.stderr[-300:]}")

    # Strict isolation: empty PYTHONPATH, cwd outside the repo, no repo root
    # anywhere on sys.path.
    env = {
        "PATH": f"{venv / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "PYTHONPATH": "",
        "PYTHON_DOTENV_DISABLED": "1",
        "DEBRIEF_FX_USD": "7.2",
        "DEBRIEF_FX_HKD": "0.92",
    }
    check = run(
        [str(python), "-c", "import sys, debrief; print('::'.join(sys.path)); " "assert not any('portfolio-agent' in p for p in sys.path)"],
        cwd=workdir,
        env=env,
    )
    assert check.returncode == 0, f"repo leaked into sys.path: {check.stdout} {check.stderr}"
    assert str(REPO_ROOT) not in check.stdout

    # Content assertions on the INSTALLED package — not just a passing --help:
    # the wheel itself must carry the FX layer (import + RECORD listing).
    content_check = run(
        [str(python), "-c",
         "import importlib.metadata as md; "
         "import adapters, adapters.fx, adapters.base; "
         "record = md.distribution('portfolio-agent-kernel').read_text('RECORD'); "
         "assert 'adapters/fx.py' in record, 'adapters/fx.py missing from RECORD'; "
         "assert 'debrief/cli.py' in record; "
         "print('content ok')"],
        cwd=workdir,
        env=env,
    )
    assert content_check.returncode == 0, (
        f"installed wheel content check failed: {content_check.stdout} {content_check.stderr}"
    )

    def cli(*args, stdin=None):
        result = run([str(debrief_bin), "--db", str(db_path), *args], cwd=workdir, env=env, input=stdin)
        assert result.returncode == 0, f"debrief {args} failed: {result.stdout} {result.stderr}"
        payload = json.loads(result.stdout)
        assert payload["ok"] is True, f"envelope not ok for {args}: {payload}"
        return payload["data"]

    cli("migrate", "--json")
    added = cli("holdings", "add", "--json", stdin='{"market":"us","symbol":"NVDA","name":"英伟达","quantity":10,"cost":100}')
    assert added["symbol"] == "NVDA"
    holdings = cli("holdings", "--json")
    assert [p["symbol"] for p in holdings["positions"]] == ["NVDA"]
    dashboard = cli("dashboard", "--json")
    assert dashboard["kpis"]["totalAssets"] == dashboard["series"]["equity"][-1]
    job_list = cli("job", "list", "--json")
    assert job_list["items"] == []
