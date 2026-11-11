#!/usr/bin/env bash
# dsh-debrief 一键演示：用仓库自带 mock 内核跑通全部命令形态。
# One-command demo against the bundled mock kernel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOCK="$ROOT/mock/debrief.js"

section() {
  printf '\n\033[1;34m== %s ==\033[0m\n' "$1"
}

run() {
  printf '\033[2m$ debrief %s --json\033[0m\n' "$*"
  node "$MOCK" "$@" --json
  printf '\n'
}

section '只读 Read: holdings / transactions / watchlist'
run holdings
run transactions --ticker AAPL --limit 2
run watchlist

section '只读 Read: instruments / report / memory / analysis / jobs'
run instruments search --market cn --query maotai
run report latest --market us
run memory search --query 建仓理由
run analysis prepare --market us
run job list

section '只读 Read: dashboard / news'
run dashboard --range 90
run news latest --limit 3

section '白名单写 Write: report create (stdin JSON)'
printf '{"market":"us","title":"盘后分析 · demo","summary":"一句话总结","jobId":"debrief-job-2048"}' |
  node "$MOCK" report create --json
printf '\n'

section '白名单写 Write: memory compact-write (stdin JSON)'
printf '{"topic":"position-aapl-rationale","instruments":["AAPL"],"summary":"结论","evidenceRefs":[{"docId":12,"quote":"原文"}],"timeRange":{"from":"2026-03-01","to":"2026-05-31"},"confidence":"high"}' |
  node "$MOCK" memory compact-write --json
printf '\n'

section '白名单写 Write: memory add (stdin JSON)'
printf '{"sourceType":"decision","content":"建仓理由：……","instruments":["AAPL"],"occurredAt":"2026-11-10T08:00:00Z"}' |
  node "$MOCK" memory add --json
printf '\n'

section 'job 状态机 Job lifecycle: start -> status -> finish'
JOB_ID="$(printf '{"kind":"盘后分析 · 美股"}' | node "$MOCK" job start --json | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>console.log(JSON.parse(s).data.id))')"
echo "jobId = $JOB_ID"
node "$MOCK" job status --id "$JOB_ID" --json
printf '{"id":"%s","status":"succeeded","durationSec":42}' "$JOB_ID" | node "$MOCK" job finish --json
printf '\n'

section '记忆压缩候选 Memory compaction candidates'
run memory compact-candidates

printf '\n\033[1;32mDemo complete. 把插件 cliPath 指向 %s 即可在 DSH 中体验。\033[0m\n' "$MOCK"
