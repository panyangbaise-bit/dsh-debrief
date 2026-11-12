/**
 * dsh-debrief — Client half (single self-contained file, no imports).
 *
 * Registers keyed `tool.call.toolview` entries for every debrief tool, the
 * Dashboard page in the `main` slot plus its `sidebar.panellist` navigation
 * entry. All visible copy routes through the Client locale service
 * (dsh-client-locale) with a zh fallback; all styling uses host theme tokens.
 *
 * The browser entry must stay a single file because the Web Host serves only
 * the exported `./client` URL — internal imports would 404. React comes from
 * the browser module table via `require('react')`; no React package import.
 */
// ---------------------------------------------------------------------------
// Locale dictionaries (namespace `dsh-debrief`). zh is the fallback; en is
// kept key-complete against zh by the test suite.
// ---------------------------------------------------------------------------
const zh = {
    'mkt.us': '美股',
    'mkt.cn': 'A股',
    'mkt.hk': '港股',
    'mkt.cc': '加密',
    'common.retryHint': '可让 Agent 重试，卡片不自行重试',
    'common.readFailed': '读取失败',
    'common.prepFailed': '准备失败',
    'common.expand': '展开全文',
    'common.collapse': '收起',
    'col.symbol': '代码',
    'col.name': '名称',
    'col.quantity': '数量',
    'col.cost': '成本',
    'col.price': '现价',
    'col.marketValue': '市值',
    'col.pnlPct': '盈亏%',
    'col.weight': '权重',
    'col.time': '时间',
    'col.side': '方向',
    'col.amount': '金额',
    'col.status': '状态',
    'col.changePct': '涨跌%',
    'col.targetPrice': '关注价',
    'col.distancePct': '距关注价',
    'col.alert': '提醒',
    'holdings.title': '持仓总览',
    'holdings.count': '{count} 持仓 · {asOf}',
    'holdings.totalValue': '总市值',
    'holdings.dayPnl': '今日盈亏',
    'holdings.totalPnl': '总盈亏',
    'transactions.title': '成交明细',
    'transactions.count': '共 {total} 笔',
    'transactions.empty': '无匹配成交记录',
    'transactions.buy': '买入',
    'transactions.sell': '卖出',
    'transactions.filled': '已成交',
    'watchlist.title': '监察表',
    'watchlist.count': '{count} 自选',
    'watchlist.alertOn': '提醒中',
    'watchlist.alertOff': '无',
    'watchlist.hint': '添加自选：直接对 Agent 说「添加自选 XX，关注价 YY」（v2 走确认流；现在可先用 debrief_instruments 查代码）',
    'report.title': '盘后分析',
    'memory.title': '记忆检索',
    'memory.hits': '命中 {count} 条 · 长期优先',
    'memory.layerLong': '长期',
    'memory.layerShort': '短期',
    'memory.confidence': '置信度 {level}',
    'memory.confidence.high': '高',
    'memory.confidence.medium': '中',
    'memory.confidence.low': '低',
    'memory.evidence': '证据',
    'memory.empty': '无相关记忆',
    'analyze.title': '盘后分析任务',
    'analyze.prepared': '输入包就绪',
    'analyze.quotes': '行情快照（{count}）',
    'analyze.news': '新闻（{count}）',
    'analyze.memory': '记忆候选（{count}）',
    'analyze.guidance': '请基于输入包输出结构化盘后结论（Agent 完成，内核不生成）。',
    'jobs.title': '运行记录',
    'jobs.count': '{count} 条',
    'jobs.succeeded': '成功',
    'jobs.failed': '失败',
    'jobs.running': '运行中',
    'jobs.hint': '任务由 DSH Schedule（new_once 专属会话）触发，状态写回内核 job_runs 台账。',
    'dashboard.title': '总览仪表盘',
    'dashboard.range': '近 {range} 天',
    'dashboard.totalAssets': '总资产',
    'dashboard.dayPnl': '今日收益',
    'dashboard.totalPnl': '总收益',
    'dashboard.annualPct': '年化收益',
    'dashboard.equity': '资产变化',
    'dashboard.returns': '收益',
    'dashboard.composition': '持仓成分',
    'dashboard.holdings': '持仓',
    'dashboard.positions': '{count} 持仓',
    'dashboard.hint': '添加持仓/自选：对 Agent 说「添加持仓/自选 + 标的 + 数量/关注价」，v2 走确认流。',
    'news.title': '新闻速览',
    'news.count': '{count} 条 · {fetchedAt}',
    'news.empty': '暂无新闻条目',
    'write.reportCreated': '报告已写回',
    'write.compacted': '记忆压缩已写回',
    'write.added': '记忆已沉淀',
    'write.audited': '已入内核 user_actions 审计',
    'write.id': 'ID',
    'write.version': '版本',
    'write.docId': '文档',
    'write.status': '状态',
    'chart.daysAgo': '{count} 天前',
    'chart.latest': '最新',
    'chart.donutAria': '组合成分环形图',
    'page.panel': '复盘仪表盘',
    'page.loading': '加载中…',
    'page.loadFailed': '仪表盘加载失败',
    'page.empty': '内核暂无数据',
    'page.retry': '重试',
    'page.range30': '近 30 天',
    'page.range90': '近 90 天',
    'page.range200': '近 200 天',
    'page.range365': '近一年',
    'page.addHolding': '+ 添加持仓',
    'page.addWatch': '+ 添加自选',
    'page.addComing': '添加持仓 / 自选将在 v2 提供（走 DSH 确认流）',
    'page.refreshed': '更新于 {time}',
    'page.kpiTotalAssets': '总资产',
    'page.kpiDayPnl': '今日收益',
    'page.kpiTotalPnl': '总收益',
    'page.kpiAnnual': '年化收益',
    'error.DEBRIEF_TIMEOUT': '内核调用超时',
    'error.DEBRIEF_CLI_NOT_FOUND': '找不到内核 CLI（检查 cliPath 配置）',
    'error.DEBRIEF_CLI_NOT_EXECUTABLE': '内核 CLI 不可执行',
    'error.DEBRIEF_EXEC': '内核执行失败',
    'error.DEBRIEF_PARSE': '内核返回了非法 JSON',
    'error.DEBRIEF_BAD_PAYLOAD': '内核返回了未知负载',
    'error.DEBRIEF_ABORTED': '调用已取消',
    'error.DEBRIEF_ARGS': '参数错误',
    'error.DEBRIEF_OUTPUT_TOO_LARGE': '内核输出过大',
    'error.DEBRIEF_NETWORK': '网络请求失败',
    'error.DEBRIEF_USAGE': '内核命令不存在',
    'error.DEBRIEF_NOT_FOUND': '记录不存在',
    'error.DEBRIEF_ERROR': '内核错误',
    'error.TOOL_ERROR': '工具执行失败',
};
const en = {
    'mkt.us': 'US stocks',
    'mkt.cn': 'A-shares',
    'mkt.hk': 'HK stocks',
    'mkt.cc': 'Crypto',
    'common.retryHint': 'Ask the Agent to retry; the card does not retry on its own.',
    'common.readFailed': 'Read failed',
    'common.prepFailed': 'Prepare failed',
    'common.expand': 'Expand full text',
    'common.collapse': 'Collapse',
    'col.symbol': 'Symbol',
    'col.name': 'Name',
    'col.quantity': 'Qty',
    'col.cost': 'Cost',
    'col.price': 'Price',
    'col.marketValue': 'Value',
    'col.pnlPct': 'P&L%',
    'col.weight': 'Weight',
    'col.time': 'Time',
    'col.side': 'Side',
    'col.amount': 'Amount',
    'col.status': 'Status',
    'col.changePct': 'Chg%',
    'col.targetPrice': 'Target',
    'col.distancePct': 'Distance',
    'col.alert': 'Alert',
    'holdings.title': 'Holdings',
    'holdings.count': '{count} positions · {asOf}',
    'holdings.totalValue': 'Total value',
    'holdings.dayPnl': 'Day P&L',
    'holdings.totalPnl': 'Total P&L',
    'transactions.title': 'Trades',
    'transactions.count': '{total} trades',
    'transactions.empty': 'No matching trades',
    'transactions.buy': 'Buy',
    'transactions.sell': 'Sell',
    'transactions.filled': 'Filled',
    'watchlist.title': 'Watchlist',
    'watchlist.count': '{count} watched',
    'watchlist.alertOn': 'Alerting',
    'watchlist.alertOff': 'Off',
    'watchlist.hint': 'Add to watchlist: tell the Agent "add XX to watchlist with target YY" (v2 confirmation flow; look up codes with debrief_instruments first).',
    'report.title': 'After-market report',
    'memory.title': 'Memory',
    'memory.hits': '{count} hits · long-term first',
    'memory.layerLong': 'Long-term',
    'memory.layerShort': 'Short-term',
    'memory.confidence': 'Confidence {level}',
    'memory.confidence.high': 'High',
    'memory.confidence.medium': 'Medium',
    'memory.confidence.low': 'Low',
    'memory.evidence': 'Evidence',
    'memory.empty': 'No matching memory',
    'analyze.title': 'Analysis job',
    'analyze.prepared': 'Input package ready',
    'analyze.quotes': 'Quotes ({count})',
    'analyze.news': 'News ({count})',
    'analyze.memory': 'Memory candidates ({count})',
    'analyze.guidance': 'Synthesize the structured after-market conclusion from the package (the Agent completes it; the kernel generates nothing).',
    'jobs.title': 'Job ledger',
    'jobs.count': '{count} entries',
    'jobs.succeeded': 'Succeeded',
    'jobs.failed': 'Failed',
    'jobs.running': 'Running',
    'jobs.hint': 'Tasks are triggered by DSH Schedule (new_once dedicated sessions); status is written back to the kernel job_runs ledger.',
    'dashboard.title': 'Dashboard',
    'dashboard.range': 'Last {range} days',
    'dashboard.totalAssets': 'Total assets',
    'dashboard.dayPnl': 'Day return',
    'dashboard.totalPnl': 'Total return',
    'dashboard.annualPct': 'Annualized',
    'dashboard.equity': 'Equity',
    'dashboard.returns': 'Returns',
    'dashboard.composition': 'Composition',
    'dashboard.holdings': 'Holdings',
    'dashboard.positions': '{count} positions',
    'dashboard.hint': 'Add a holding or watchlist entry: tell the Agent "add … + instrument + quantity/target" (v2 confirmation flow).',
    'news.title': 'News',
    'news.count': '{count} items · {fetchedAt}',
    'news.empty': 'No news items',
    'write.reportCreated': 'Report written',
    'write.compacted': 'Memory compacted',
    'write.added': 'Memory added',
    'write.audited': 'Recorded in the kernel user_actions audit',
    'write.id': 'ID',
    'write.version': 'Version',
    'write.docId': 'Document',
    'write.status': 'Status',
    'chart.daysAgo': '{count} days ago',
    'chart.latest': 'Latest',
    'chart.donutAria': 'Portfolio composition donut',
    'page.panel': 'Debrief dashboard',
    'page.loading': 'Loading…',
    'page.loadFailed': 'Dashboard load failed',
    'page.empty': 'No data from the kernel',
    'page.retry': 'Retry',
    'page.range30': '30 days',
    'page.range90': '90 days',
    'page.range200': '200 days',
    'page.range365': '1 year',
    'page.addHolding': '+ Add holding',
    'page.addWatch': '+ Add watch',
    'page.addComing': 'Adding holdings / watchlist arrives in v2 (DSH confirmation flow)',
    'page.refreshed': 'Updated {time}',
    'page.kpiTotalAssets': 'Total assets',
    'page.kpiDayPnl': 'Day return',
    'page.kpiTotalPnl': 'Total return',
    'page.kpiAnnual': 'Annualized',
    'error.DEBRIEF_TIMEOUT': 'Kernel call timed out',
    'error.DEBRIEF_CLI_NOT_FOUND': 'Kernel CLI not found (check cliPath)',
    'error.DEBRIEF_CLI_NOT_EXECUTABLE': 'Kernel CLI is not executable',
    'error.DEBRIEF_EXEC': 'Kernel execution failed',
    'error.DEBRIEF_PARSE': 'Kernel returned invalid JSON',
    'error.DEBRIEF_BAD_PAYLOAD': 'Kernel returned an unexpected payload',
    'error.DEBRIEF_ABORTED': 'Call cancelled',
    'error.DEBRIEF_ARGS': 'Invalid arguments',
    'error.DEBRIEF_OUTPUT_TOO_LARGE': 'Kernel output too large',
    'error.DEBRIEF_NETWORK': 'Network request failed',
    'error.DEBRIEF_USAGE': 'Unknown kernel command',
    'error.DEBRIEF_NOT_FOUND': 'Record not found',
    'error.DEBRIEF_ERROR': 'Kernel error',
    'error.TOOL_ERROR': 'Tool execution failed',
};
function interpolate(template, params) {
    if (!params)
        return template;
    return template.replace(/\{(\w+)\}/g, (match, name) => {
        const value = params[name];
        return value === undefined ? match : String(value);
    });
}
function dictT(dict) {
    return (key, params) => interpolate(dict[key] ?? key, params);
}
/** Prefer the injected locale `t`; fall back to the zh dictionary. */
function pickT(injected) {
    if (typeof injected === 'function')
        return injected;
    return dictT(zh);
}
const s = () => ({ type: 'string' });
const num = () => ({ type: 'number' });
const int = () => ({ type: 'integer' });
const arr = (items) => ({ type: 'array', items });
const obj = (properties, required = []) => ({
    type: 'object',
    properties,
    required,
});
const opt = (shape) => ({ ...shape, optional: true });
function validate(shape, value, path = '$') {
    if ((value === undefined || value === null) && shape.optional)
        return { ok: true, value: undefined };
    if (value === undefined || value === null)
        return { ok: false, path, reason: 'required value is missing' };
    switch (shape.type) {
        case 'string':
            return typeof value === 'string'
                ? { ok: true, value }
                : { ok: false, path, reason: `expected string, got ${typeof value}` };
        case 'number':
            return typeof value === 'number' && Number.isFinite(value)
                ? { ok: true, value }
                : { ok: false, path, reason: `expected finite number, got ${typeof value}` };
        case 'integer':
            return typeof value === 'number' && Number.isInteger(value)
                ? { ok: true, value }
                : { ok: false, path, reason: `expected integer, got ${typeof value}` };
        case 'boolean':
            return typeof value === 'boolean'
                ? { ok: true, value }
                : { ok: false, path, reason: `expected boolean, got ${typeof value}` };
        case 'array': {
            if (!Array.isArray(value))
                return { ok: false, path, reason: `expected array, got ${typeof value}` };
            const items = [];
            for (let index = 0; index < value.length; index += 1) {
                const result = validate(shape.items, value[index], `${path}[${index}]`);
                if (!result.ok)
                    return result;
                items.push(result.value);
            }
            return { ok: true, value: items };
        }
        case 'object': {
            if (typeof value !== 'object' || Array.isArray(value)) {
                return { ok: false, path, reason: `expected object, got ${Array.isArray(value) ? 'array' : typeof value}` };
            }
            const record = value;
            // Render-model gate: validate the declared fields but NEVER drop undeclared
            // keys — an incomplete schema must not erase kernel payload fields (a
            // whitelist here once blanked every dashboard table cell). The Host copy
            // of this validator stays strict because write payloads are exact.
            const out = { ...record };
            for (const [key, member] of Object.entries(shape.properties)) {
                const result = validate(member, record[key], `${path}.${key}`);
                if (!result.ok)
                    return result;
                if (result.value !== undefined)
                    out[key] = result.value;
            }
            return { ok: true, value: out };
        }
    }
}
/** Parse a settled tool call block into args + canonical envelope. */
function envelopeOf(block) {
    let args = {};
    if (!block || block.kind === undefined) {
        return { args, data: null, error: { code: 'PENDING', message: '' } };
    }
    try {
        args = JSON.parse(block.call?.argsRaw ?? '{}');
    }
    catch {
        args = {};
    }
    if (block.isError) {
        return {
            args,
            data: null,
            error: { code: block.error?.code ?? 'TOOL_ERROR', message: block.error?.message ?? 'tool failed' },
        };
    }
    const text = (block.content ?? [])
        .filter((c) => c.type === 'text')
        .map((c) => c.text ?? '')
        .join('\n');
    try {
        const env = JSON.parse(text);
        if (env && typeof env === 'object') {
            if (env.ok === true)
                return { args, data: env.data ?? null, error: null };
            const error = env.error;
            return {
                args,
                data: null,
                error: { code: error?.code ?? 'DEBRIEF_ERROR', message: error?.message ?? 'kernel error' },
            };
        }
        return {
            args,
            data: null,
            error: { code: 'DEBRIEF_BAD_PAYLOAD', message: 'kernel returned an unexpected payload' },
        };
    }
    catch {
        return { args, data: null, error: { code: 'DEBRIEF_PARSE', message: 'invalid tool result' } };
    }
}
/** Loose render-model gate: unknown schema versions or malformed payloads degrade, never crash. */
/** Shared row shapes: complete field sets matching the kernel/mock payloads. */
const POSITION_ROW = {
    market: opt(s()),
    symbol: opt(s()),
    name: opt(s()),
    quantity: opt(num()),
    cost: opt(num()),
    price: opt(num()),
    marketValue: opt(num()),
    pnlPct: opt(num()),
    weight: opt(num()),
};
const WATCH_ROW = {
    market: opt(s()),
    symbol: opt(s()),
    name: opt(s()),
    price: opt(num()),
    changePct: opt(num()),
    targetPrice: opt(num()),
    distancePct: opt(num()),
    alert: opt({ type: 'boolean' }),
};
function renderModel(kind, data) {
    if (!data || typeof data !== 'object')
        return { ok: false, reason: 'tool result is not an object' };
    const record = data;
    switch (kind) {
        case 'debrief_holdings': {
            const result = validate(obj({
                asOf: opt(s()),
                currency: opt(s()),
                totalMarketValue: opt(num()),
                dayPnl: opt(num()),
                dayPnlPct: opt(num()),
                totalPnl: opt(num()),
                totalPnlPct: opt(num()),
                positions: opt(arr(obj(POSITION_ROW))),
            }), data);
            return result.ok
                ? { ok: true, model: result.value }
                : { ok: false, reason: `${result.path} ${result.reason}` };
        }
        case 'debrief_dashboard': {
            const result = validate(obj({
                kpis: opt(obj({
                    totalAssets: opt(num()),
                    currency: opt(s()),
                    dayPnl: opt(num()),
                    dayPnlPct: opt(num()),
                    totalPnl: opt(num()),
                    totalPnlPct: opt(num()),
                    annualPct: opt(num()),
                })),
                series: opt(obj({ range: opt(int()), equity: opt(arr(num())), returns: opt(arr(num())) })),
                composition: opt(arr(obj({ name: opt(s()), value: opt(num()) }))),
                holdings: opt(arr(obj(POSITION_ROW))),
                watchlist: opt(arr(obj(WATCH_ROW))),
            }), data);
            return result.ok
                ? { ok: true, model: result.value }
                : { ok: false, reason: `${result.path} ${result.reason}` };
        }
        default:
            // Unknown or write-result kinds pass through unchanged (lossless).
            return { ok: true, model: record };
    }
}
const NS = 'dsh-debrief';
const PANEL_ID = 'debrief-dashboard';
const DASHBOARD_API = '/api/debrief/dashboard';
const RANGES = ['30', '90', '200', '365'];
function clientFactory(requireFn) {
    const React = requireFn('react');
    const h = React.createElement;
    const CSS = `
.dbr-card{--dbr-up:light-dark(#d5433b,#e5534b);--dbr-down:light-dark(#0f9d58,#2ea870);--dbr-radius:var(--dsw-radius-lg,10px);--dbr-radius-sm:var(--dsw-radius-sm,6px);
  background:var(--dsw-alias-bg-layer-1);border:.5px solid var(--dsw-alias-border-l1);border-radius:var(--dbr-radius);overflow:hidden;margin:2px 0;min-width:0}
.dbr-head{display:flex;align-items:center;gap:8px;padding:8px 12px;cursor:pointer;user-select:none}
.dbr-head:hover{background:var(--dsw-alias-bg-layer-2)}
.dbr-icon{flex:0 0 24px;width:24px;height:24px;border-radius:6px;background:color-mix(in srgb,var(--dsw-alias-brand-primary) 14%,transparent);color:var(--dsw-alias-brand-primary);display:flex;align-items:center;justify-content:center}
.dbr-title{font-weight:600;font-size:13px;color:var(--dsw-alias-label-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dbr-tool{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px;color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-layer-2);border-radius:5px;padding:1px 6px;flex:0 0 auto}
.dbr-meta{margin-left:auto;font-size:11.5px;color:var(--dsw-alias-label-secondary);white-space:nowrap;display:flex;align-items:center;gap:6px}
.dbr-chev{color:var(--dsw-alias-label-secondary);transition:transform .16s ease;flex:0 0 auto}
.dbr-card.closed .dbr-chev{transform:rotate(-90deg)}
.dbr-body{border-top:.5px solid var(--dsw-alias-border-l1);padding:10px 12px 12px;min-width:0}
.dbr-card.closed .dbr-body{display:none}
.dbr-up{color:var(--dbr-up)} .dbr-down{color:var(--dbr-down)}
.dbr-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(108px,1fr));gap:8px;margin-bottom:10px}
.dbr-stat{background:var(--dsw-alias-bg-layer-2);border:.5px solid var(--dsw-alias-border-l1);border-radius:var(--dbr-radius-sm);padding:7px 10px;min-width:0}
.dbr-k{font-size:11px;color:var(--dsw-alias-label-secondary)}
.dbr-v{font-size:14.5px;font-weight:650;color:var(--dsw-alias-label-primary);font-variant-numeric:tabular-nums;margin-top:1px}
.dbr-d{font-size:11.5px;font-weight:600;margin-left:5px;font-variant-numeric:tabular-nums}
.dbr-table{width:100%;border-collapse:collapse;font-size:12px;min-width:0}
.dbr-wrap{overflow-x:auto;border:.5px solid var(--dsw-alias-border-l1);border-radius:var(--dbr-radius-sm)}
.dbr-table th,.dbr-table td{padding:6px 8px;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.dbr-table th:first-child,.dbr-table td:first-child{text-align:left}
.dbr-table th{color:var(--dsw-alias-label-secondary);font-weight:500;font-size:11px;border-bottom:.5px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-2)}
.dbr-table td{border-top:.5px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-primary)}
.dbr-table tbody tr:first-child td{border-top:0}
.dbr-table tbody tr:hover td{background:var(--dsw-alias-bg-layer-2)}
.dbr-sub{display:block;font-size:10.5px;color:var(--dsw-alias-label-secondary)}
.dbr-wbar{display:inline-block;width:42px;height:4px;border-radius:2px;background:var(--dsw-alias-bg-layer-2);vertical-align:middle;margin-left:6px;overflow:hidden}
.dbr-wbar i{display:block;height:100%;background:var(--dsw-alias-brand-primary);border-radius:2px}
.dbr-b{display:inline-block;font-size:11px;font-weight:500;padding:1px 7px;border-radius:999px}
.dbr-b.buy{background:color-mix(in srgb,var(--dbr-up) 14%,transparent);color:var(--dbr-up)}
.dbr-b.sell{background:color-mix(in srgb,var(--dbr-down) 14%,transparent);color:var(--dbr-down)}
.dbr-b.neutral{background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary)}
.dbr-b.ok{background:color-mix(in srgb,var(--dsw-alias-state-success-primary) 14%,transparent);color:var(--dsw-alias-state-success-primary)}
.dbr-b.warn{background:color-mix(in srgb,var(--dsw-alias-state-warn-primary) 14%,transparent);color:var(--dsw-alias-state-warn-primary)}
.dbr-b.danger{background:color-mix(in srgb,var(--dsw-alias-state-error-primary) 14%,transparent);color:var(--dsw-alias-state-error-primary)}
.dbr-b.market{background:color-mix(in srgb,var(--dsw-alias-brand-primary) 14%,transparent);color:var(--dsw-alias-brand-primary)}
.dbr-chart{margin:8px 0 2px}
.dbr-chart svg{width:100%;height:auto;display:block}
.dbr-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:6px;margin-top:4px}
.dbr-metric{background:var(--dsw-alias-bg-layer-2);border:.5px solid var(--dsw-alias-border-l1);border-radius:var(--dbr-radius-sm);padding:6px 9px;font-size:11px;color:var(--dsw-alias-label-secondary)}
.dbr-metric b{display:block;color:var(--dsw-alias-label-primary);font-size:12.5px;margin-top:1px;font-variant-numeric:tabular-nums}
.dbr-text{font-size:12.5px;color:var(--dsw-alias-label-secondary);line-height:1.6;margin:0}
.dbr-more{color:var(--dsw-alias-brand-primary);font-size:12px;background:none;border:0;padding:2px 0;cursor:pointer}
.dbr-more:hover{text-decoration:underline}
.dbr-hint{font-size:11.5px;color:var(--dsw-alias-label-secondary);margin-top:8px}
.dbr-err{display:flex;gap:8px;align-items:flex-start;background:color-mix(in srgb,var(--dsw-alias-state-error-primary) 10%,transparent);border:.5px solid color-mix(in srgb,var(--dsw-alias-state-error-primary) 30%,transparent);border-radius:var(--dbr-radius-sm);padding:8px 10px;font-size:12.5px;color:var(--dsw-alias-label-primary)}
.dbr-code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--dsw-alias-state-error-primary);font-weight:600}
.dbr-sec{margin-top:10px;padding-top:10px;border-top:.5px solid var(--dsw-alias-border-l1)}
.dbr-sec-title{font-size:12px;font-weight:600;color:var(--dsw-alias-label-primary);margin-bottom:6px}
.dbr-evid{border:.5px solid var(--dsw-alias-border-l1);border-radius:var(--dbr-radius-sm);margin-top:6px;overflow:hidden}
.dbr-evid-head{display:flex;align-items:center;gap:7px;padding:6px 10px;cursor:pointer;font-size:12px;color:var(--dsw-alias-label-secondary)}
.dbr-evid-head:hover{background:var(--dsw-alias-bg-layer-2)}
.dbr-evid-quote{display:none;border-top:.5px dashed var(--dsw-alias-border-l2,var(--dsw-alias-border-l1));background:var(--dsw-alias-bg-layer-2);padding:7px 10px;font-size:12px;color:var(--dsw-alias-label-secondary)}
.dbr-evid.open .dbr-evid-quote{display:block}
.dbr-cite{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--dsw-alias-brand-primary);font-size:11.5px}
.dbr-job{display:flex;align-items:center;gap:9px;padding:7px 10px;background:var(--dsw-alias-bg-layer-2);border:.5px solid var(--dsw-alias-border-l1);border-radius:var(--dbr-radius-sm)}
.dbr-dot{width:8px;height:8px;border-radius:50%;flex:0 0 8px}
.dbr-dot.ok{background:var(--dsw-alias-state-success-primary)}
.dbr-dot.danger{background:var(--dsw-alias-state-error-primary)}
.dbr-dot.run{background:var(--dsw-alias-state-warn-primary);animation:dbr-pulse 1.4s ease-in-out infinite}
@keyframes dbr-pulse{50%{opacity:.35}}
.dbr-tl{position:relative;padding-left:18px}
.dbr-tl::before{content:"";position:absolute;left:3px;top:8px;bottom:8px;width:1px;background:var(--dsw-alias-border-l2,var(--dsw-alias-border-l1))}
.dbr-tl-item{position:relative;display:flex;gap:10px;align-items:baseline;padding:4px 0 4px 4px}
.dbr-tl-item .dbr-dot{position:absolute;left:-18px;top:10px}
.dbr-tl-title{font-size:12.5px;font-weight:500;color:var(--dsw-alias-label-primary)}
.dbr-tl-sub{font-size:11.5px;color:var(--dsw-alias-label-secondary)}
.dbr-tl-time{margin-left:auto;font-size:11.5px;color:var(--dsw-alias-label-secondary);font-variant-numeric:tabular-nums}
.dbr-donut{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.dbr-donut svg{width:150px;flex:0 0 150px}
.dbr-legend{flex:1;min-width:150px;display:flex;flex-direction:column;gap:5px;font-size:12px;color:var(--dsw-alias-label-primary)}
.dbr-legend li{display:flex;align-items:center;gap:7px;list-style:none;margin:0;padding:0}
.dbr-swatch{width:8px;height:8px;border-radius:2px;flex:0 0 8px}
.dbr-legend .pct{margin-left:auto;color:var(--dsw-alias-label-secondary);font-variant-numeric:tabular-nums}
.dbr-summary-line{font-size:12.5px;color:var(--dsw-alias-label-primary);margin-bottom:6px}
.dbr-page{height:100%;overflow-y:auto;box-sizing:border-box;overscroll-behavior:contain;padding:18px 20px 32px;max-width:1180px;margin:0 auto;min-width:0;color:var(--dsw-alias-label-primary)}
.dbr-page-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.dbr-page-title{font-size:16px;font-weight:650;margin-right:auto}
.dbr-chips{display:flex;gap:6px;flex-wrap:wrap}
.dbr-chip{font-size:12px;padding:4px 12px;border-radius:999px;border:.5px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-secondary);cursor:pointer}
.dbr-chip.active{background:var(--dsw-alias-brand-primary);border-color:var(--dsw-alias-brand-primary);color:var(--dsw-alias-bg-layer-1)}
.dbr-page-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.dbr-page-grid .wide{grid-column:1/-1}
.dbr-panel{background:var(--dsw-alias-bg-layer-1);border:.5px solid var(--dsw-alias-border-l1);border-radius:var(--dbr-radius);padding:12px 14px;min-width:0}
.dbr-panel-title{display:flex;align-items:center;font-size:12.5px;font-weight:600;margin-bottom:8px;gap:8px}
.dbr-panel-title .dbr-more{font-weight:400;margin-left:auto}
.dbr-skeleton{height:96px;border-radius:var(--dbr-radius-sm);background:linear-gradient(90deg,var(--dsw-alias-bg-layer-2) 25%,var(--dsw-alias-bg-layer-1) 50%,var(--dsw-alias-bg-layer-2) 75%);background-size:200% 100%;animation:dbr-shimmer 1.4s infinite}
@keyframes dbr-shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
.dbr-page-err{display:flex;flex-direction:column;gap:8px;align-items:flex-start}
@media (max-width:768px){.dbr-page-grid{grid-template-columns:1fr}.dbr-page{padding:12px}}
`;
    // ---- helpers --------------------------------------------------------------
    function fmt(n, digits = 2) {
        if (n === null || n === undefined)
            return '—';
        const value = Number(n);
        if (!Number.isFinite(value))
            return '—';
        return value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }
    function pct(n) {
        if (n === null || n === undefined)
            return '—';
        const value = Number(n);
        if (!Number.isFinite(value))
            return '—';
        return (value > 0 ? '+' : '') + value.toFixed(2) + '%';
    }
    function money(n) {
        return '¥' + Math.round(Number(n) || 0).toLocaleString('zh-CN');
    }
    function updown(v) {
        const value = Number(v);
        if (!Number.isFinite(value))
            return '';
        return value > 0 ? 'dbr-up' : value < 0 ? 'dbr-down' : '';
    }
    function marketName(t, market) {
        const key = String(market ?? '').toUpperCase();
        return t(`mkt.${key.toLowerCase()}`) === `mkt.${key.toLowerCase()}`
            ? String(market ?? '')
            : t(`mkt.${key.toLowerCase()}`);
    }
    function errorExplanation(t, code) {
        const explained = t(`error.${code}`);
        return explained === `error.${code}` ? '' : explained;
    }
    function Icon(props) {
        return h('svg', {
            width: 13,
            height: 13,
            viewBox: '0 0 16 16',
            fill: 'none',
            stroke: 'currentColor',
            strokeWidth: 1.5,
            strokeLinecap: 'round',
            strokeLinejoin: 'round',
            'aria-hidden': true,
        }, ...props.d.map((p) => h('path', { d: p })));
    }
    const ICONS = {
        holdings: h(Icon, { d: ['M2 14h12', 'M4.5 14V9.5M8 14V5.5M11.5 14V8'] }),
        transactions: h(Icon, { d: ['M3.5 5.5h9', 'M9.5 2.5 12.5 5 9.5 7.5', 'M12.5 10.5h-9', 'M6.5 8.5 3.5 11l3 3'] }),
        watchlist: h(Icon, {
            d: ['M1.8 8s2.6-4.4 6.2-4.4S14.2 8 14.2 8s-2.6 4.4-6.2 4.4S1.8 8 1.8 8z', 'M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4z'],
        }),
        report: h(Icon, { d: ['M5 2h6l3 3v9H5z', 'M8 2v3h3', 'M6.5 9.5h5M6.5 12h5'] }),
        memory: h(Icon, { d: ['M5 2.5h6v11l-3-2-3 2z'] }),
        analyze: h(Icon, { d: ['M8 14a6 6 0 1 0 0-12 6 6 0 0 0 0 12z', 'M8 5v3.2l2.2 1.4'] }),
        jobs: h(Icon, { d: ['M3.5 4.5h9M3.5 8h9M3.5 11.5h9'] }),
        dashboard: h(Icon, { d: ['M2 14h12', 'M4.5 14V9.5M8 14V5.5M11.5 14V8'] }),
        news: h(Icon, { d: ['M3 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H3z', 'M5 7h6M5 10h4', 'M13 8h1M13 11h1'] }),
        write: h(Icon, { d: ['M3 11.5 12.5 2l2.5 2.5L5.5 14H3z', 'M11 4l2 2'] }),
    };
    function Card(props) {
        const [open, setOpen] = React.useState(props.defaultOpen !== false);
        return h('section', { className: 'dbr-card' + (open ? '' : ' closed') }, h('div', {
            className: 'dbr-head',
            role: 'button',
            tabIndex: 0,
            'aria-expanded': open,
            onClick: () => setOpen(!open),
            onKeyDown: (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setOpen(!open);
                }
            },
        }, h('span', { className: 'dbr-icon' }, props.icon), h('span', { className: 'dbr-title' }, props.title), h('span', { className: 'dbr-tool' }, props.tool), h('span', { className: 'dbr-meta' }, props.meta, h('svg', {
            className: 'dbr-chev',
            width: 12,
            height: 12,
            viewBox: '0 0 16 16',
            fill: 'none',
            stroke: 'currentColor',
            strokeWidth: 1.8,
            strokeLinecap: 'round',
            strokeLinejoin: 'round',
        }, h('path', { d: 'm6 3 5 5-5 5' })))), open ? h('div', { className: 'dbr-body' }, props.children) : null);
    }
    function ErrorBody(props) {
        const explanation = errorExplanation(props.t, props.error.code);
        return h('div', { className: 'dbr-err' }, h('span', { className: 'dbr-code' }, props.error.code), h('span', null, explanation !== '' ? explanation : props.error.message), h('span', { className: 'dbr-hint', style: { marginTop: 0 } }, `（${props.t('common.retryHint')}）`));
    }
    function Stat(props) {
        return h('div', { className: 'dbr-stat' }, h('div', { className: 'dbr-k' }, props.k), h('div', { className: 'dbr-v' }, props.v, props.d !== undefined ? h('span', { className: 'dbr-d ' + (props.cls ?? '') }, props.d) : null));
    }
    function useInView() {
        const ref = React.useRef(null);
        const [inView, setInView] = React.useState(false);
        React.useEffect(() => {
            const node = ref.current;
            if (!node || typeof IntersectionObserver === 'undefined') {
                setInView(true);
                return;
            }
            const observer = new IntersectionObserver((entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        setInView(true);
                        observer.disconnect();
                    }
                }
            }, { rootMargin: '160px' });
            observer.observe(node);
            return () => observer.disconnect();
        }, []);
        return [ref, inView];
    }
    function areaSvg(props) {
        const { points } = props;
        const color = props.color ?? 'var(--dsw-alias-brand-primary)';
        const fmtLabel = props.fmtLabel ?? ((v) => String(v));
        if (points.length < 2)
            return null;
        const minV = Math.min(...points, 0);
        const maxV = Math.max(...points, 0);
        const pad = (maxV - minV) * 0.12 || 1;
        const min = minV - pad;
        const max = maxV + pad;
        const W = 640;
        const H = 180;
        const pl = 12;
        const pr = 12;
        const pt = 16;
        const pb = 24;
        const x = (i) => pl + ((W - pl - pr) * i) / (points.length - 1);
        const y = (v) => pt + (H - pt - pb) * (1 - (v - min) / (max - min));
        const d = points.map((v, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1)).join(' ');
        const area = `${d} L${x(points.length - 1).toFixed(1)} ${H - pb} L${x(0).toFixed(1)} ${H - pb} Z`;
        const zero = min <= 0 && max >= 0
            ? h('line', {
                x1: pl,
                y1: y(0).toFixed(1),
                x2: W - pr,
                y2: y(0).toFixed(1),
                stroke: 'var(--dsw-alias-border-l2,var(--dsw-alias-border-l1))',
                strokeDasharray: '4 4',
            })
            : null;
        const last = points[points.length - 1] ?? 0;
        const lx = x(points.length - 1);
        const ly = y(last);
        return h('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img' }, h('defs', null, h('linearGradient', { id: 'dbr-g', x1: 0, y1: 0, x2: 0, y2: 1 }, h('stop', { offset: 0, style: { stopColor: color, stopOpacity: 0.16 } }), h('stop', { offset: 1, style: { stopColor: color, stopOpacity: 0 } }))), zero, h('line', {
            x1: pl,
            y1: y(max).toFixed(1),
            x2: W - pr,
            y2: y(max).toFixed(1),
            stroke: 'var(--dsw-alias-border-l1)',
            strokeDasharray: '3 4',
        }), h('line', {
            x1: pl,
            y1: y(min).toFixed(1),
            x2: W - pr,
            y2: y(min).toFixed(1),
            stroke: 'var(--dsw-alias-border-l1)',
            strokeDasharray: '3 4',
        }), h('path', { d: area, fill: 'url(#dbr-g)' }), h('path', { d, fill: 'none', stroke: color, strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }), h('circle', { cx: lx.toFixed(1), cy: ly.toFixed(1), r: 6.5, fill: color, opacity: 0.14 }), h('circle', {
            cx: lx.toFixed(1),
            cy: ly.toFixed(1),
            r: 3,
            fill: color,
            stroke: 'var(--dsw-alias-bg-layer-1)',
            strokeWidth: 1.4,
        }), h('text', {
            x: lx.toFixed(1),
            y: (ly - 8).toFixed(1),
            textAnchor: 'end',
            fontSize: 11,
            fontWeight: 600,
            fill: color,
            className: props.endClass,
        }, fmtLabel(last)), h('text', { x: pl, y: H - 6, fontSize: 10, fill: 'var(--dsw-alias-label-secondary)' }, props.t('chart.daysAgo', { count: points.length })), h('text', { x: W - pr, y: H - 6, textAnchor: 'end', fontSize: 10, fill: 'var(--dsw-alias-label-secondary)' }, props.t('chart.latest')));
    }
    const CHART_PALETTE = ['#2f6feb', '#7c3aed', '#0f9d58', '#d97706', '#0891b2', '#e11d48', '#8a939d'];
    function donutSvg(composition, centerTitle, centerSub, ariaLabel) {
        const R = 74;
        const C = 2 * Math.PI * R;
        let acc = 0;
        const segs = composition.map((d, index) => {
            const frac = Number(d.value ?? 0) / 100;
            const seg = { ...d, frac, off: acc, color: CHART_PALETTE[index % CHART_PALETTE.length] ?? CHART_PALETTE[0] };
            acc += frac;
            return seg;
        });
        return h('svg', { viewBox: '0 0 200 200', role: 'img', 'aria-label': ariaLabel }, segs.map((s) => h('circle', {
            cx: 100,
            cy: 100,
            r: R,
            fill: 'none',
            stroke: s.color,
            strokeWidth: 24,
            strokeDasharray: `${(s.frac * C).toFixed(2)} ${C.toFixed(2)}`,
            strokeDashoffset: (-s.off * C).toFixed(2),
            transform: 'rotate(-90 100 100)',
        })), h('text', { x: 100, y: 96, textAnchor: 'middle', fontSize: 13, fontWeight: 650, fill: 'var(--dsw-alias-label-primary)' }, centerTitle), h('text', { x: 100, y: 113, textAnchor: 'middle', fontSize: 10.5, fill: 'var(--dsw-alias-label-secondary)' }, centerSub));
    }
    function donutLegend(composition) {
        return h('ul', { className: 'dbr-legend' }, composition.map((d, index) => h('li', { key: String(d.name ?? index) }, h('span', { className: 'dbr-swatch', style: { background: CHART_PALETTE[index % CHART_PALETTE.length] } }), String(d.name ?? ''), h('span', { className: 'pct' }, `${Number(d.value ?? 0)}%`))));
    }
    function toArray(value) {
        return Array.isArray(value) ? value : [];
    }
    // ---- Cards ----------------------------------------------------------------
    function HoldingsCard(props) {
        const t = pickT(props.t);
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, { icon: ICONS.holdings, title: t('holdings.title'), tool: 'debrief_holdings', meta: t('common.readFailed') }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.holdings, title: t('holdings.title'), tool: 'debrief_holdings', meta: '…' }, null);
        const record = data;
        const positions = toArray(record.positions);
        return h(Card, {
            icon: ICONS.holdings,
            title: t('holdings.title'),
            tool: 'debrief_holdings',
            meta: t('holdings.count', { count: positions.length, asOf: String(record.asOf ?? '') }),
        }, h('div', { className: 'dbr-stats' }, h(Stat, { k: t('holdings.totalValue'), v: money(record.totalMarketValue) }), h(Stat, {
            k: t('holdings.dayPnl'),
            v: money(record.dayPnl),
            d: pct(record.dayPnlPct),
            cls: updown(record.dayPnlPct),
        }), h(Stat, {
            k: t('holdings.totalPnl'),
            v: money(record.totalPnl),
            d: pct(record.totalPnlPct),
            cls: updown(record.totalPnlPct),
        })), h('div', { className: 'dbr-wrap' }, h('table', { className: 'dbr-table' }, h('thead', null, h('tr', null, h('th', null, t('col.symbol')), h('th', null, t('col.name')), h('th', null, t('col.quantity')), h('th', null, t('col.cost')), h('th', null, t('col.price')), h('th', null, t('col.marketValue')), h('th', null, t('col.pnlPct')), h('th', null, t('col.weight')))), h('tbody', null, positions.map((p) => h('tr', { key: String(p.symbol ?? '') }, h('td', null, String(p.symbol ?? ''), h('span', { className: 'dbr-sub' }, marketName(t, p.market))), h('td', null, String(p.name ?? '')), h('td', null, fmt(p.quantity, 4)), h('td', null, fmt(p.cost)), h('td', null, fmt(p.price)), h('td', null, fmt(p.marketValue, 0)), h('td', { className: updown(p.pnlPct) }, pct(p.pnlPct)), h('td', null, `${Number(p.weight ?? 0)}%`, h('span', { className: 'dbr-wbar' }, h('i', { style: { width: `${Math.min(100, Number(p.weight ?? 0) * 4)}%` } })))))))));
    }
    function TxCard(props) {
        const t = pickT(props.t);
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, {
                icon: ICONS.transactions,
                title: t('transactions.title'),
                tool: 'debrief_transactions',
                meta: t('common.readFailed'),
            }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.transactions, title: t('transactions.title'), tool: 'debrief_transactions', meta: '…' }, null);
        const record = data;
        const items = toArray(record.items);
        return h(Card, {
            icon: ICONS.transactions,
            title: t('transactions.title'),
            tool: 'debrief_transactions',
            meta: t('transactions.count', { total: record.total ?? items.length }),
        }, h('div', { className: 'dbr-wrap' }, h('table', { className: 'dbr-table' }, h('thead', null, h('tr', null, h('th', null, t('col.time')), h('th', null, t('col.side')), h('th', null, t('col.symbol')), h('th', null, t('col.name')), h('th', null, t('col.quantity')), h('th', null, t('col.price')), h('th', null, t('col.amount')), h('th', null, t('col.status')))), h('tbody', null, items.map((row) => h('tr', { key: `${String(row.time ?? '')}${String(row.symbol ?? '')}` }, h('td', null, String(row.time ?? '')), h('td', null, h('span', { className: 'dbr-b ' + (row.side === 'buy' ? 'buy' : 'sell') }, row.side === 'buy' ? t('transactions.buy') : t('transactions.sell'))), h('td', null, String(row.symbol ?? ''), h('span', { className: 'dbr-sub' }, marketName(t, row.market))), h('td', null, String(row.name ?? '')), h('td', null, fmt(row.quantity, 4)), h('td', null, fmt(row.price)), h('td', null, fmt(row.amount, 0)), h('td', null, h('span', { className: 'dbr-b neutral' }, row.status === 'filled' ? t('transactions.filled') : String(row.status ?? '')))))))), items.length === 0 ? h('div', { className: 'dbr-hint' }, t('transactions.empty')) : null);
    }
    function WatchlistCard(props) {
        const t = pickT(props.t);
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, { icon: ICONS.watchlist, title: t('watchlist.title'), tool: 'debrief_watchlist', meta: t('common.readFailed') }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.watchlist, title: t('watchlist.title'), tool: 'debrief_watchlist', meta: '…' }, null);
        const record = data;
        const items = toArray(record.items);
        return h(Card, {
            icon: ICONS.watchlist,
            title: t('watchlist.title'),
            tool: 'debrief_watchlist',
            meta: t('watchlist.count', { count: record.count ?? items.length }),
        }, h('div', { className: 'dbr-wrap' }, h('table', { className: 'dbr-table' }, h('thead', null, h('tr', null, h('th', null, t('col.symbol')), h('th', null, t('col.name')), h('th', null, t('col.price')), h('th', null, t('col.changePct')), h('th', null, t('col.targetPrice')), h('th', null, t('col.distancePct')), h('th', null, t('col.alert')))), h('tbody', null, items.map((w) => h('tr', { key: String(w.symbol ?? '') }, h('td', null, String(w.symbol ?? ''), h('span', { className: 'dbr-sub' }, marketName(t, w.market))), h('td', null, String(w.name ?? '')), h('td', null, fmt(w.price)), h('td', { className: updown(w.changePct) }, pct(w.changePct)), h('td', null, fmt(w.targetPrice)), h('td', { className: updown(w.distancePct) }, pct(w.distancePct)), h('td', null, h('span', { className: 'dbr-b ' + (w.alert ? 'warn' : 'neutral') }, w.alert ? t('watchlist.alertOn') : t('watchlist.alertOff')))))))), h('div', { className: 'dbr-hint' }, t('watchlist.hint')));
    }
    function ReportCard(props) {
        const t = pickT(props.t);
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, { icon: ICONS.report, title: t('report.title'), tool: 'debrief_report', meta: t('common.readFailed') }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.report, title: t('report.title'), tool: 'debrief_report', meta: '…' }, null);
        const record = data;
        const [more, setMore] = React.useState(false);
        const chart = (record.chart ?? {});
        const points = toArray(chart.points)
            .map((point) => Number(point))
            .filter((point) => Number.isFinite(point));
        return h(Card, {
            icon: ICONS.report,
            title: String(record.title ?? t('report.title')),
            tool: 'debrief_report',
            meta: `${String(record.generatedAt ?? '')} · ${marketName(t, record.market)}`,
        }, h('p', { className: 'dbr-text' }, String(record.summary ?? '')), more ? h('p', { className: 'dbr-text' }, String(record.fullText ?? '')) : null, record.fullText
            ? h('button', { className: 'dbr-more', onClick: () => setMore(!more) }, more ? t('common.collapse') : t('common.expand'))
            : null, points.length > 1 ? h('div', { className: 'dbr-chart' }, areaSvg({ points, t })) : null, toArray(record.metrics).length > 0
            ? h('div', { className: 'dbr-metrics' }, toArray(record.metrics).map((m) => h('div', { className: 'dbr-metric', key: String(m.label ?? '') }, String(m.label ?? ''), h('b', null, String(m.value ?? '')))))
            : null);
    }
    function MemoryCard(props) {
        const t = pickT(props.t);
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, { icon: ICONS.memory, title: t('memory.title'), tool: 'debrief_memory', meta: t('common.readFailed') }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.memory, title: t('memory.title'), tool: 'debrief_memory', meta: '…' }, null);
        const record = data;
        const items = toArray(record.items);
        const [open, setOpen] = React.useState(() => new Set());
        const confidenceLabel = (level) => {
            const key = `memory.confidence.${String(level ?? '')}`;
            const label = t(key);
            return label === key ? String(level ?? '') : label;
        };
        return h(Card, {
            icon: ICONS.memory,
            title: t('memory.title'),
            tool: 'debrief_memory',
            meta: t('memory.hits', { count: items.length }),
        }, items.map((m, index) => h('div', { key: `${String(m.topic ?? '')}${index}`, className: index ? 'dbr-sec' : '' }, h('div', { style: { display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' } }, h('span', { className: 'dbr-b neutral' }, m.layer === 'long' ? t('memory.layerLong') : t('memory.layerShort')), h('span', { style: { fontWeight: 600, fontSize: 12.5, color: 'var(--dsw-alias-label-primary)' } }, String(m.topic ?? '')), m.confidence
            ? h('span', {
                className: 'dbr-b ' + (m.confidence === 'high' ? 'ok' : m.confidence === 'medium' ? 'warn' : 'neutral'),
            }, t('memory.confidence', { level: confidenceLabel(m.confidence) }))
            : null, h('span', { style: { marginLeft: 'auto', fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } }, String(m.timeRange ?? ''))), h('p', { className: 'dbr-text', style: { marginTop: 5 } }, String(m.summary ?? '')), toArray(m.evidence).map((ev) => {
            const key = `${String(m.topic ?? '')}-${String(ev.docId ?? '')}`;
            const isOpen = open.has(key);
            return h('div', { key, className: 'dbr-evid' + (isOpen ? ' open' : '') }, h('div', {
                className: 'dbr-evid-head',
                onClick: () => setOpen((previous) => {
                    const next = new Set(previous);
                    if (next.has(key))
                        next.delete(key);
                    else
                        next.add(key);
                    return next;
                }),
            }, h('span', null, t('memory.evidence')), h('span', { className: 'dbr-cite' }, `[[cite:doc:${String(ev.docId ?? '')}]]`), h('span', { style: { marginLeft: 'auto', fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } }, `${String(ev.date ?? '')} ${String(ev.label ?? '')}`)), h('div', { className: 'dbr-evid-quote' }, String(ev.quote ?? '')));
        }))), items.length === 0 ? h('div', { className: 'dbr-hint' }, t('memory.empty')) : null);
    }
    function AnalyzeCard(props) {
        const t = pickT(props.t);
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, { icon: ICONS.analyze, title: t('analyze.title'), tool: 'debrief_analyze', meta: t('common.prepFailed') }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.analyze, title: t('analyze.title'), tool: 'debrief_analyze', meta: '…' }, null);
        const record = data;
        const inputs = (record.inputs ?? {});
        return h(Card, { icon: ICONS.analyze, title: t('analyze.title'), tool: 'debrief_analyze', meta: marketName(t, record.market) }, h('div', { className: 'dbr-job' }, h('span', { className: 'dbr-dot ok' }), h('span', {
            style: {
                fontFamily: 'ui-monospace, Menlo, monospace',
                fontSize: 11.5,
                color: 'var(--dsw-alias-label-secondary)',
            },
        }, String(record.jobId ?? '')), h('span', { className: 'dbr-b ok' }, t('analyze.prepared')), h('span', { style: { marginLeft: 'auto', fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } }, String(record.preparedAt ?? ''))), h('div', { className: 'dbr-sec' }, h('div', { className: 'dbr-sec-title' }, t('analyze.quotes', { count: toArray(inputs.quotes).length })), toArray(inputs.quotes).map((q) => h('div', {
            key: String(q.symbol ?? ''),
            style: {
                display: 'flex',
                gap: 8,
                fontSize: 12,
                color: 'var(--dsw-alias-label-primary)',
                padding: '2px 0',
            },
        }, h('span', { style: { fontWeight: 600 } }, String(q.symbol ?? '')), h('span', null, String(q.name ?? '')), h('span', { style: { marginLeft: 'auto', fontVariantNumeric: 'tabular-nums' } }, fmt(q.price)), h('span', {
            className: updown(q.changePct),
            style: { minWidth: 52, textAlign: 'right', fontVariantNumeric: 'tabular-nums' },
        }, pct(q.changePct))))), h('div', { className: 'dbr-sec' }, h('div', { className: 'dbr-sec-title' }, t('analyze.news', { count: toArray(inputs.news).length })), toArray(inputs.news).map((n) => h('div', {
            key: String(n.title ?? ''),
            style: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)', padding: '2px 0' },
        }, String(n.title ?? ''), h('span', { style: { fontSize: 10.5, marginLeft: 6 } }, String(n.source ?? ''))))), h('div', { className: 'dbr-sec' }, h('div', { className: 'dbr-sec-title' }, t('analyze.memory', { count: toArray(inputs.memoryCandidates).length })), toArray(inputs.memoryCandidates).map((m) => h('div', {
            key: String(m.topic ?? ''),
            style: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)', padding: '2px 0' },
        }, h('span', { style: { fontWeight: 600, color: 'var(--dsw-alias-label-primary)' } }, String(m.topic ?? '')), ' · ', String(m.summary ?? '')))), record.guidance ? h('div', { className: 'dbr-hint' }, t('analyze.guidance')) : null);
    }
    function JobsCard(props) {
        const t = pickT(props.t);
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, { icon: ICONS.jobs, title: t('jobs.title'), tool: 'debrief_jobs', meta: t('common.readFailed') }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.jobs, title: t('jobs.title'), tool: 'debrief_jobs', meta: '…' }, null);
        const record = data;
        const items = toArray(record.items);
        const dot = (status) => (status === 'succeeded' ? 'ok' : status === 'failed' ? 'danger' : 'run');
        const label = (status) => status === 'succeeded'
            ? t('jobs.succeeded')
            : status === 'failed'
                ? t('jobs.failed')
                : status === 'running'
                    ? t('jobs.running')
                    : String(status ?? '');
        return h(Card, {
            icon: ICONS.jobs,
            title: t('jobs.title'),
            tool: 'debrief_jobs',
            meta: t('jobs.count', { count: items.length }),
        }, h('div', { className: 'dbr-tl' }, items.map((j) => h('div', { className: 'dbr-tl-item', key: String(j.id ?? '') }, h('span', { className: 'dbr-dot ' + dot(j.status) }), h('span', { className: 'dbr-tl-title' }, String(j.kind ?? '')), h('span', { className: 'dbr-tl-sub' }, j.status === 'failed'
            ? String(j.errorCode ?? '')
            : j.status === 'running'
                ? t('jobs.running')
                : `${String(j.durationSec ?? '')}s`), h('span', { className: 'dbr-tl-time' }, String(j.at ?? '')), h('span', { className: 'dbr-tl-sub' }, label(j.status))))), h('div', { className: 'dbr-hint' }, t('jobs.hint')));
    }
    function NewsCard(props) {
        const t = pickT(props.t);
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, { icon: ICONS.news, title: t('news.title'), tool: 'debrief_news', meta: t('common.readFailed') }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.news, title: t('news.title'), tool: 'debrief_news', meta: '…' }, null);
        const record = data;
        const items = toArray(record.items);
        return h(Card, {
            icon: ICONS.news,
            title: t('news.title'),
            tool: 'debrief_news',
            meta: t('news.count', { count: items.length, fetchedAt: String(record.fetchedAt ?? '') }),
        }, h('div', { className: 'dbr-tl' }, items.map((n, index) => h('div', { className: 'dbr-tl-item', key: `${String(n.title ?? '')}${index}` }, h('span', { className: 'dbr-dot ok' }), h('span', { className: 'dbr-tl-title' }, String(n.title ?? '')), h('span', { className: 'dbr-tl-time' }, String(n.at ?? '')), h('span', { className: 'dbr-tl-sub' }, `${marketName(t, n.market)} · ${String(n.source ?? '')}`)))), items.length === 0 ? h('div', { className: 'dbr-hint' }, t('news.empty')) : null);
    }
    function WriteResultCard(props) {
        const t = pickT(props.t);
        const title = props.kind === 'report'
            ? t('write.reportCreated')
            : props.kind === 'compact'
                ? t('write.compacted')
                : t('write.added');
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, { icon: ICONS.write, title, tool: props.tool, meta: t('common.readFailed') }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.write, title, tool: props.tool, meta: '…' }, null);
        const record = data;
        return h(Card, { icon: ICONS.write, title, tool: props.tool, meta: t('write.audited') }, h('div', { className: 'dbr-job' }, h('span', { className: 'dbr-dot ok' }), h('span', { style: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)' } }, t('write.id')), h('span', {
            style: {
                fontFamily: 'ui-monospace, Menlo, monospace',
                fontSize: 12,
                color: 'var(--dsw-alias-label-primary)',
            },
        }, String(record.id ?? record.docId ?? '')), record.version !== undefined
            ? h('span', { style: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)' } }, `${t('write.version')} ${String(record.version)}`)
            : null, record.status !== undefined
            ? h('span', { className: 'dbr-b ok', style: { marginLeft: 'auto' } }, String(record.status))
            : null));
    }
    function DashboardCard(props) {
        const t = pickT(props.t);
        const { data, error } = envelopeOf(props.block);
        if (error)
            return h(Card, { icon: ICONS.dashboard, title: t('dashboard.title'), tool: 'debrief_dashboard', meta: t('common.readFailed') }, h(ErrorBody, { error, t }));
        if (!data)
            return h(Card, { icon: ICONS.dashboard, title: t('dashboard.title'), tool: 'debrief_dashboard', meta: '…' }, null);
        const record = data;
        const kpis = (record.kpis ?? {});
        const series = (record.series ?? {});
        const equity = toArray(series.equity)
            .map((point) => Number(point))
            .filter((point) => Number.isFinite(point));
        const returns = toArray(series.returns)
            .map((point) => Number(point))
            .filter((point) => Number.isFinite(point));
        const composition = toArray(record.composition);
        const holdings = toArray(record.holdings);
        const watchlist = toArray(record.watchlist);
        return h(Card, {
            icon: ICONS.dashboard,
            title: t('dashboard.title'),
            tool: 'debrief_dashboard',
            meta: t('dashboard.range', { range: String(series.range ?? '—') }),
        }, h('div', { className: 'dbr-stats' }, h(Stat, { k: t('dashboard.totalAssets'), v: money(kpis.totalAssets) }), h(Stat, {
            k: t('dashboard.dayPnl'),
            v: money(kpis.dayPnl),
            d: pct(kpis.dayPnlPct),
            cls: updown(kpis.dayPnlPct),
        }), h(Stat, {
            k: t('dashboard.totalPnl'),
            v: money(kpis.totalPnl),
            d: pct(kpis.totalPnlPct),
            cls: updown(kpis.totalPnlPct),
        }), h(Stat, { k: t('dashboard.annualPct'), v: pct(kpis.annualPct) })), h('div', { className: 'dbr-sec-title' }, t('dashboard.equity')), equity.length > 1
            ? h('div', { className: 'dbr-chart' }, areaSvg({ points: equity, fmtLabel: (v) => money(v), t }))
            : null, h('div', { className: 'dbr-sec-title', style: { marginTop: 10 } }, t('dashboard.returns')), returns.length > 1
            ? h('div', { className: 'dbr-chart' }, areaSvg({
                points: returns,
                color: '#7c3aed',
                fmtLabel: (v) => `${v.toFixed(1)}%`,
                endClass: (returns[returns.length - 1] ?? 0) >= 0 ? 'dbr-up' : 'dbr-down',
                t,
            }))
            : null, composition.length > 0
            ? h('div', { className: 'dbr-sec' }, h('div', { className: 'dbr-sec-title' }, t('dashboard.composition')), h('div', { className: 'dbr-donut' }, donutSvg(composition, t('dashboard.positions', { count: holdings.length }), '100%', t('chart.donutAria')), donutLegend(composition)))
            : null, holdings.length > 0
            ? h('div', { className: 'dbr-sec' }, h('div', { className: 'dbr-sec-title' }, t('dashboard.holdings')), h('div', { className: 'dbr-wrap' }, h('table', { className: 'dbr-table' }, h('thead', null, h('tr', null, h('th', null, t('col.symbol')), h('th', null, t('col.name')), h('th', null, t('col.price')), h('th', null, t('col.marketValue')), h('th', null, t('col.pnlPct')), h('th', null, t('col.weight')))), h('tbody', null, holdings.map((p) => h('tr', { key: String(p.symbol ?? '') }, h('td', null, String(p.symbol ?? '')), h('td', null, String(p.name ?? '')), h('td', null, fmt(p.price)), h('td', null, fmt(p.marketValue, 0)), h('td', { className: updown(p.pnlPct) }, pct(p.pnlPct)), h('td', null, `${Number(p.weight ?? 0)}%`)))))))
            : null, watchlist.length > 0
            ? h('div', { className: 'dbr-sec' }, h('div', { className: 'dbr-sec-title' }, t('watchlist.title')), h('div', { className: 'dbr-wrap' }, h('table', { className: 'dbr-table' }, h('thead', null, h('tr', null, h('th', null, t('col.symbol')), h('th', null, t('col.name')), h('th', null, t('col.price')), h('th', null, t('col.targetPrice')), h('th', null, t('col.alert')))), h('tbody', null, watchlist.map((w) => h('tr', { key: String(w.symbol ?? '') }, h('td', null, String(w.symbol ?? '')), h('td', null, String(w.name ?? '')), h('td', null, fmt(w.price)), h('td', null, fmt(w.targetPrice)), h('td', null, h('span', { className: 'dbr-b ' + (w.alert ? 'warn' : 'neutral') }, w.alert ? t('watchlist.alertOn') : t('watchlist.alertOff')))))))))
            : null, h('div', { className: 'dbr-hint' }, t('dashboard.hint')));
    }
    function rangeLabel(t, range) {
        const key = `page.range${range}`;
        const label = t(key);
        return label === key ? `${range}D` : label;
    }
    function LazyChart(props) {
        const [ref, inView] = useInView();
        return h('div', { ref, className: 'dbr-chart' }, inView
            ? areaSvg({ points: props.points, color: props.color, fmtLabel: props.fmtLabel, t: props.t })
            : h('div', { className: 'dbr-skeleton' }));
    }
    function DashboardPage(props) {
        const t = pickT(props.t);
        const [range, setRange] = React.useState('90');
        const [state, setState] = React.useState({ status: 'loading', data: null, error: null });
        const [attempt, setAttempt] = React.useState(0);
        React.useEffect(() => {
            let cancelled = false;
            const controller = new AbortController();
            setState({ status: 'loading', data: null, error: null });
            fetch(`${DASHBOARD_API}?range=${range}`, { signal: controller.signal })
                .then(async (response) => {
                const body = (await response.json());
                if (cancelled)
                    return;
                if (body.ok === true)
                    setState({ status: 'ready', data: (body.data ?? null), error: null });
                else {
                    const error = (body.error ?? { code: 'DEBRIEF_ERROR', message: 'kernel error' });
                    setState({ status: 'error', data: null, error });
                }
            })
                .catch((error) => {
                if (cancelled)
                    return;
                if (error instanceof DOMException && error.name === 'AbortError')
                    return;
                setState({ status: 'error', data: null, error: { code: 'DEBRIEF_NETWORK', message: String(error) } });
            });
            return () => {
                cancelled = true;
                controller.abort();
            };
        }, [range, attempt]);
        const model = state.data
            ? renderModel('debrief_dashboard', state.data)
            : { ok: false, reason: 'no data' };
        const record = model.ok ? model.model : null;
        const kpis = (record?.kpis ?? {});
        const series = (record?.series ?? {});
        const equity = toArray(series.equity)
            .map((point) => Number(point))
            .filter((point) => Number.isFinite(point));
        const returns = toArray(series.returns)
            .map((point) => Number(point))
            .filter((point) => Number.isFinite(point));
        const composition = toArray(record?.composition);
        const holdings = toArray(record?.holdings);
        const watchlist = toArray(record?.watchlist);
        return h('div', { className: 'dbr-page' }, h('div', { className: 'dbr-page-head' }, h('div', { className: 'dbr-page-title' }, t('page.panel')), h('div', { className: 'dbr-chips', role: 'group', 'aria-label': t('dashboard.range', { range: '' }) }, RANGES.map((value) => h('button', {
            type: 'button',
            key: value,
            className: 'dbr-chip' + (value === range ? ' active' : ''),
            'aria-pressed': value === range,
            onClick: () => setRange(value),
        }, rangeLabel(t, value))))), state.status === 'loading'
            ? h('div', { className: 'dbr-page-grid' }, h('div', { className: 'dbr-panel wide' }, h('div', { className: 'dbr-skeleton' })))
            : state.status === 'error'
                ? h('div', { className: 'dbr-panel' }, h('div', { className: 'dbr-page-err' }, h('div', { className: 'dbr-err' }, h('span', { className: 'dbr-code' }, state.error?.code ?? 'DEBRIEF_ERROR'), h('span', null, state.error?.message ?? '')), h('button', { type: 'button', className: 'dbr-more', onClick: () => setAttempt((previous) => previous + 1) }, t('page.retry'))))
                : record === null
                    ? h('div', { className: 'dbr-panel' }, h('div', { className: 'dbr-hint' }, t('page.empty')))
                    : h('div', { className: 'dbr-page-grid' }, h('div', {
                        className: 'wide dbr-stats',
                        style: { marginBottom: 0, gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))' },
                    }, h(Stat, { k: t('page.kpiTotalAssets'), v: money(kpis.totalAssets) }), h(Stat, {
                        k: t('page.kpiDayPnl'),
                        v: money(kpis.dayPnl),
                        d: pct(kpis.dayPnlPct),
                        cls: updown(kpis.dayPnlPct),
                    }), h(Stat, {
                        k: t('page.kpiTotalPnl'),
                        v: money(kpis.totalPnl),
                        d: pct(kpis.totalPnlPct),
                        cls: updown(kpis.totalPnlPct),
                    }), h(Stat, { k: t('page.kpiAnnual'), v: pct(kpis.annualPct) })), h('div', { className: 'dbr-panel wide' }, h('div', { className: 'dbr-panel-title' }, t('dashboard.equity'), h('span', { className: 'dbr-hint', style: { margin: '0 0 0 auto' } }, t('page.refreshed', { time: new Date().toLocaleTimeString('zh-CN') }))), equity.length > 1
                        ? h(LazyChart, {
                            t,
                            title: t('dashboard.equity'),
                            points: equity,
                            fmtLabel: (v) => money(v),
                        })
                        : null), h('div', { className: 'dbr-panel wide' }, h('div', { className: 'dbr-panel-title' }, t('dashboard.returns')), returns.length > 1
                        ? h(LazyChart, {
                            t,
                            title: t('dashboard.returns'),
                            points: returns,
                            color: '#7c3aed',
                            fmtLabel: (v) => `${v.toFixed(1)}%`,
                        })
                        : null), composition.length > 0
                        ? h('div', { className: 'dbr-panel' }, h('div', { className: 'dbr-panel-title' }, t('dashboard.composition')), h('div', { className: 'dbr-donut' }, donutSvg(composition, t('dashboard.positions', { count: holdings.length }), '100%', t('chart.donutAria')), donutLegend(composition)))
                        : null, h('div', { className: 'dbr-panel' }, h('div', { className: 'dbr-panel-title' }, t('dashboard.holdings'), h('button', { type: 'button', className: 'dbr-more', title: t('page.addComing'), onClick: () => { } }, t('page.addHolding'))), holdings.length > 0
                        ? h('div', { className: 'dbr-wrap' }, h('table', { className: 'dbr-table' }, h('thead', null, h('tr', null, h('th', null, t('col.symbol')), h('th', null, t('col.name')), h('th', null, t('col.quantity')), h('th', null, t('col.cost')), h('th', null, t('col.price')), h('th', null, t('col.marketValue')), h('th', null, t('col.pnlPct')), h('th', null, t('col.weight')))), h('tbody', null, holdings.map((p) => h('tr', { key: String(p.symbol ?? '') }, h('td', null, String(p.symbol ?? ''), h('span', { className: 'dbr-sub' }, marketName(t, p.market))), h('td', null, String(p.name ?? '')), h('td', null, fmt(p.quantity, 4)), h('td', null, fmt(p.cost)), h('td', null, fmt(p.price)), h('td', null, fmt(p.marketValue, 0)), h('td', { className: updown(p.pnlPct) }, pct(p.pnlPct)), h('td', null, `${Number(p.weight ?? 0)}%`))))))
                        : h('div', { className: 'dbr-hint' }, t('page.empty'))), h('div', { className: 'dbr-panel wide' }, h('div', { className: 'dbr-panel-title' }, t('watchlist.title'), h('button', { type: 'button', className: 'dbr-more', title: t('page.addComing'), onClick: () => { } }, t('page.addWatch'))), watchlist.length > 0
                        ? h('div', { className: 'dbr-wrap' }, h('table', { className: 'dbr-table' }, h('thead', null, h('tr', null, h('th', null, t('col.symbol')), h('th', null, t('col.name')), h('th', null, t('col.price')), h('th', null, t('col.changePct')), h('th', null, t('col.targetPrice')), h('th', null, t('col.distancePct')), h('th', null, t('col.alert')))), h('tbody', null, watchlist.map((w) => h('tr', { key: String(w.symbol ?? '') }, h('td', null, String(w.symbol ?? ''), h('span', { className: 'dbr-sub' }, marketName(t, w.market))), h('td', null, String(w.name ?? '')), h('td', null, fmt(w.price)), h('td', { className: updown(w.changePct) }, pct(w.changePct)), h('td', null, fmt(w.targetPrice)), h('td', { className: updown(w.distancePct) }, pct(w.distancePct)), h('td', null, h('span', { className: 'dbr-b ' + (w.alert ? 'warn' : 'neutral') }, w.alert ? t('watchlist.alertOn') : t('watchlist.alertOff'))))))))
                        : h('div', { className: 'dbr-hint' }, t('page.empty'))), h('div', { className: 'dbr-panel wide' }, h('div', { className: 'dbr-hint' }, t('page.addComing')))));
    }
    function PanelGlyph(props) {
        return h('svg', {
            width: props.size ?? 18,
            height: props.size ?? 18,
            viewBox: '0 0 16 16',
            fill: 'none',
            stroke: 'currentColor',
            strokeWidth: 1.5,
            strokeLinecap: 'round',
            strokeLinejoin: 'round',
            'aria-hidden': true,
        }, h('path', { d: 'M2 14h12' }), h('path', { d: 'M4.5 14V9.5M8 14V5.5M11.5 14V8' }));
    }
    const VIEWS = {
        debrief_holdings: HoldingsCard,
        debrief_transactions: TxCard,
        debrief_watchlist: WatchlistCard,
        debrief_report: ReportCard,
        debrief_memory: MemoryCard,
        debrief_analyze: AnalyzeCard,
        debrief_jobs: JobsCard,
        debrief_dashboard: DashboardCard,
        debrief_news: NewsCard,
        debrief_report_create: (props) => h(WriteResultCard, { ...props, tool: 'debrief_report_create', kind: 'report' }),
        debrief_memory_compact_write: (props) => h(WriteResultCard, { ...props, tool: 'debrief_memory_compact_write', kind: 'compact' }),
        debrief_memory_add: (props) => h(WriteResultCard, { ...props, tool: 'debrief_memory_add', kind: 'add' }),
    };
    function apply(ctx) {
        const disposeStyle = ctx.effect(() => {
            if (typeof document === 'undefined')
                return () => { };
            const tag = document.createElement('style');
            tag.dataset.plugin = NS;
            tag.dataset.pluginCss = NS;
            tag.textContent = CSS;
            document.head.appendChild(tag);
            return () => tag.remove();
        }, `${NS}: styles`);
        ctx.effect(() => ctx.locale.register(NS, { zh: { ...zh }, en: { ...en } }), `${NS}: dictionaries`);
        const boundT = ctx.locale.bind ? ctx.locale.bind(NS) : undefined;
        const fallbackT = dictT(zh);
        const at = (key) => (boundT ? boundT(key) : fallbackT(key));
        const disposeViews = ctx.slots.inject('tool.call.toolview', function* () {
            for (const [key, View] of Object.entries(VIEWS)) {
                yield ctx.slots.register({ name: 'tool.call.toolview', key, locale: NS }, View);
            }
        });
        const disposePage = ctx.slots.inject('main', function* () {
            yield ctx.slots.register({ name: 'main', key: PANEL_ID, locale: NS, inject: () => ({}) }, DashboardPage);
        });
        const disposeNav = ctx.slots.inject('sidebar.panellist', function* () {
            yield ctx.slots.register({ name: 'sidebar.panellist', id: PANEL_ID, order: 20, locale: NS, label: () => at('page.panel') }, PanelGlyph);
        });
        return () => {
            disposeViews();
            disposePage();
            disposeNav();
            if (typeof disposeStyle === 'function')
                disposeStyle();
        };
    }
    return { inject: ['slots', 'locale'], apply };
}
if (typeof window !== 'undefined' && window.__ModuleLoader__) {
    window.__ModuleLoader__.load({ id: 'dsh-debrief', factory: clientFactory });
}
