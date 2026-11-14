#!/usr/bin/env bash
# Build the pure-Python kernel wheel.
#
# The wheel carries the whole data kernel — CLI, DB, adapters, scheduler and
# notifier — because `debrief worker` runs from the same install. Third-party
# collector packages (yfinance/akshare/pycoingecko/apscheduler/…) are NOT
# vendored; install them with: pip install 'portfolio-agent-kernel[collectors]'.
#
# Usage:
#   scripts/build_cli_wheel.sh [version]
# Output:
#   artifacts/portfolio_agent_kernel-<version>-py3-none-any.whl
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-0.3.0}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

for pkg in debrief db common domain memory adapters scheduler notifier; do
  rsync -a --exclude '__pycache__' --exclude '*.pyc' "$ROOT/$pkg" "$STAGE/"
done
cp "$ROOT/config.py" "$ROOT/runtime.py" "$STAGE/"

cat > "$STAGE/pyproject.toml" <<PYPROJECT
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "portfolio-agent-kernel"
version = "$VERSION"
description = "debrief data kernel: SQLite ledger, JSON CLI, collection worker (no agent, no LLM)"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0.0",
    "requests>=2.31.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
collectors = [
    "yfinance>=0.2.40",
    "akshare>=1.14.0",
    "pycoingecko>=3.1.0",
    "apscheduler>=3.10.0",
    "python-telegram-bot>=20.0",
    "pyyaml>=6.0",
    "tomlkit>=0.13,<1",
]

[project.scripts]
debrief = "debrief.cli:main"

[tool.setuptools]
py-modules = ["config", "runtime"]

[tool.setuptools.packages.find]
include = ["debrief*", "db*", "common*", "domain*", "memory*", "adapters*", "scheduler*", "notifier*"]
PYPROJECT

mkdir -p "$ROOT/artifacts"
PYTHON="${PYTHON:-$ROOT/.venv-debrief/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON=python3
fi

if ! "$PYTHON" -c "import build" 2>/dev/null; then
  echo "python 'build' module missing — install once: uv pip install -p $PYTHON build 'setuptools>=68' wheel" >&2
  exit 1
fi
if ! "$PYTHON" -c "import setuptools" 2>/dev/null; then
  echo "setuptools missing — install once: uv pip install -p $PYTHON 'setuptools>=68' wheel" >&2
  exit 1
fi

(
  cd "$STAGE"
  "$PYTHON" -m build --wheel --no-isolation --outdir "$ROOT/artifacts" >/dev/null
)

echo "built: $ROOT/artifacts/portfolio_agent_kernel-${VERSION}-py3-none-any.whl"
