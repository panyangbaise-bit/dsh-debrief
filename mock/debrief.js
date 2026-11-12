#!/usr/bin/env node
/**
 * Mock debrief kernel CLI for local development, demos, and e2e fixtures.
 * Implements the same JSON envelope and schemas the real Python kernel
 * provides; the DSH plugin treats this file exactly like the kernel.
 *
 *   debrief holdings --json
 *   debrief instruments search --market cn --query maotai --json
 *   echo '{"market":"us",...}' | debrief report create --json
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const ok = (data) => JSON.stringify({ ok: true, schemaVersion: 1, data })
const fail = (code, message) => JSON.stringify({ ok: false, schemaVersion: 1, error: { code, message } })

const argv = process.argv.slice(2)
const command = argv[0] ?? ''
const flags = {}
for (let i = 1; i < argv.length; i++) {
  const a = argv[i]
  if (a.startsWith('--')) {
    const key = a.slice(2)
    const next = argv[i + 1]
    if (next !== undefined && !next.startsWith('--')) {
      flags[key] = next
      i++
    } else flags[key] = true
  }
}

const SEED_HOLDINGS = [
  {
    market: 'CN',
    symbol: '600519',
    name: '贵州茅台',
    quantity: 200,
    cost: 1450.0,
    price: 1412.0,
    marketValue: 282400,
    pnlPct: -2.62,
    weight: 21,
  },
  {
    market: 'HK',
    symbol: '00700',
    name: '腾讯控股',
    quantity: 300,
    cost: 385.0,
    price: 412.8,
    marketValue: 123840,
    pnlPct: 7.22,
    weight: 14,
  },
  {
    market: 'US',
    symbol: 'AAPL',
    name: '苹果',
    quantity: 100,
    cost: 180.2,
    price: 189.5,
    marketValue: 18950,
    pnlPct: 5.16,
    weight: 12,
  },
  {
    market: 'CN',
    symbol: '300750',
    name: '宁德时代',
    quantity: 400,
    cost: 245.0,
    price: 238.6,
    marketValue: 95440,
    pnlPct: -2.61,
    weight: 11,
  },
  {
    market: 'US',
    symbol: 'NVDA',
    name: '英伟达',
    quantity: 80,
    cost: 95.4,
    price: 118.2,
    marketValue: 9456,
    pnlPct: 23.9,
    weight: 9,
  },
  {
    market: 'CC',
    symbol: 'BTC',
    name: '比特币',
    quantity: 0.5,
    cost: 62000,
    price: 67450,
    marketValue: 33725,
    pnlPct: 8.79,
    weight: 8,
  },
]

const SEED_WATCHLIST = [
  {
    market: 'US',
    symbol: 'NVDA',
    name: '英伟达',
    price: 118.2,
    changePct: 1.8,
    targetPrice: 105.0,
    distancePct: 12.6,
    alert: true,
  },
  {
    market: 'HK',
    symbol: '00700',
    name: '腾讯控股',
    price: 412.8,
    changePct: 0.6,
    targetPrice: 380.0,
    distancePct: 8.6,
    alert: true,
  },
  {
    market: 'CC',
    symbol: 'BTC',
    name: '比特币',
    price: 67450,
    changePct: 2.1,
    targetPrice: 60000,
    distancePct: 12.4,
    alert: false,
  },
  {
    market: 'CN',
    symbol: '600519',
    name: '贵州茅台',
    price: 1412.0,
    changePct: -1.2,
    targetPrice: 1350.0,
    distancePct: 4.6,
    alert: true,
  },
  {
    market: 'US',
    symbol: 'AAPL',
    name: '苹果',
    price: 189.5,
    changePct: 0.4,
    targetPrice: 170.0,
    distancePct: 11.5,
    alert: false,
  },
]

const INSTRUMENTS = {
  US: [
    { market: 'US', symbol: 'AAPL', name: '苹果', currency: 'USD', assetClass: 'stock', held: true },
    { market: 'US', symbol: 'NVDA', name: '英伟达', currency: 'USD', assetClass: 'stock', held: true },
    { market: 'US', symbol: 'MSFT', name: '微软', currency: 'USD', assetClass: 'stock' },
    { market: 'US', symbol: 'TSLA', name: '特斯拉', currency: 'USD', assetClass: 'stock' },
    { market: 'US', symbol: 'GOOGL', name: '谷歌-A', currency: 'USD', assetClass: 'stock' },
    { market: 'US', symbol: 'AMZN', name: '亚马逊', currency: 'USD', assetClass: 'stock' },
    { market: 'US', symbol: 'META', name: 'Meta 平台', currency: 'USD', assetClass: 'stock' },
    { market: 'US', symbol: 'SPY', name: '标普500 ETF', currency: 'USD', assetClass: 'etf' },
    { market: 'US', symbol: 'QQQ', name: '纳指100 ETF', currency: 'USD', assetClass: 'etf' },
  ],
  CN: [
    {
      market: 'CN',
      symbol: '600519',
      name: '贵州茅台',
      currency: 'CNY',
      assetClass: 'stock',
      pinyin: 'maotai gzmt',
      held: true,
    },
    {
      market: 'CN',
      symbol: '300750',
      name: '宁德时代',
      currency: 'CNY',
      assetClass: 'stock',
      pinyin: 'ndsd',
      held: true,
    },
    { market: 'CN', symbol: '601318', name: '中国平安', currency: 'CNY', assetClass: 'stock', pinyin: 'zgpa' },
    { market: 'CN', symbol: '000858', name: '五粮液', currency: 'CNY', assetClass: 'stock', pinyin: 'wly' },
    { market: 'CN', symbol: '688981', name: '中芯国际', currency: 'CNY', assetClass: 'stock', pinyin: 'zxgj' },
    { market: 'CN', symbol: '510300', name: '沪深300ETF', currency: 'CNY', assetClass: 'etf', pinyin: 'hs300' },
  ],
  HK: [
    {
      market: 'HK',
      symbol: '00700',
      name: '腾讯控股',
      currency: 'HKD',
      assetClass: 'stock',
      pinyin: 'txkg',
      held: true,
    },
    { market: 'HK', symbol: '09988', name: '阿里巴巴-W', currency: 'HKD', assetClass: 'stock', pinyin: 'albb' },
    { market: 'HK', symbol: '03690', name: '美团-W', currency: 'HKD', assetClass: 'stock', pinyin: 'mt' },
    { market: 'HK', symbol: '01810', name: '小米集团-W', currency: 'HKD', assetClass: 'stock', pinyin: 'xmjt' },
    { market: 'HK', symbol: '00941', name: '中国移动', currency: 'HKD', assetClass: 'stock', pinyin: 'zgyd' },
    { market: 'HK', symbol: '02800', name: '盈富基金', currency: 'HKD', assetClass: 'etf', pinyin: 'yfjj' },
  ],
  CC: [
    { market: 'CC', symbol: 'BTC', name: 'Bitcoin 比特币', currency: 'USD', assetClass: 'crypto', held: true },
    { market: 'CC', symbol: 'ETH', name: 'Ethereum 以太坊', currency: 'USD', assetClass: 'crypto' },
    { market: 'CC', symbol: 'SOL', name: 'Solana', currency: 'USD', assetClass: 'crypto' },
    { market: 'CC', symbol: 'BNB', name: 'BNB', currency: 'USD', assetClass: 'crypto' },
    { market: 'CC', symbol: 'XRP', name: 'XRP 瑞波', currency: 'USD', assetClass: 'crypto' },
    { market: 'CC', symbol: 'DOGE', name: 'Dogecoin 狗狗币', currency: 'USD', assetClass: 'crypto' },
    { market: 'CC', symbol: 'ADA', name: 'Cardano', currency: 'USD', assetClass: 'crypto' },
  ],
}

const TRANSACTIONS = [
  {
    time: '2026-11-08 09:32',
    side: 'buy',
    market: 'US',
    symbol: 'AAPL',
    name: '苹果',
    quantity: 50,
    price: 182.4,
    amount: 9120,
    status: 'filled',
  },
  {
    time: '2026-11-05 13:47',
    side: 'sell',
    market: 'HK',
    symbol: '00700',
    name: '腾讯控股',
    quantity: 100,
    price: 405.2,
    amount: 40520,
    status: 'filled',
  },
  {
    time: '2026-11-01 10:15',
    side: 'buy',
    market: 'US',
    symbol: 'NVDA',
    name: '英伟达',
    quantity: 30,
    price: 98.6,
    amount: 2958,
    status: 'filled',
  },
  {
    time: '2026-10-28 14:02',
    side: 'buy',
    market: 'CN',
    symbol: '600519',
    name: '贵州茅台',
    quantity: 50,
    price: 1468.0,
    amount: 73400,
    status: 'filled',
  },
]

const JOBS = [
  { id: 'debrief-job-2043', kind: '盘后分析 · 美股', at: '2026-11-09 18:00', status: 'succeeded', durationSec: 42 },
  { id: 'debrief-job-2042', kind: '盘后分析 · A股', at: '2026-11-09 15:30', status: 'succeeded', durationSec: 38 },
  { id: 'debrief-job-2044', kind: '盘前新闻扫描', at: '2026-11-10 08:30', status: 'running', durationSec: null },
  { id: 'debrief-job-2040', kind: '周复盘', at: '2026-11-07 09:00', status: 'succeeded', durationSec: 96 },
  {
    id: 'debrief-job-2039',
    kind: '月度复盘',
    at: '2026-11-05 09:00',
    status: 'failed',
    durationSec: 300,
    errorCode: 'E_TIMEOUT',
  },
]

const NEWS = [
  { title: '半导体设备链订单超预期，板块放量上行', at: '2026-11-11 14:20', source: '财联社', market: 'CN' },
  { title: '美联储官员释放鸽派信号，美债收益率回落', at: '2026-11-11 10:05', source: '路透', market: 'US' },
  { title: '恒指科技股午后拉升，南向资金净流入扩大', at: '2026-11-11 13:40', source: '东方财富', market: 'HK' },
  { title: 'BTC 现货 ETF 单日净流入创月内新高', at: '2026-11-11 09:15', source: 'CoinDesk', market: 'CC' },
]

const REPORT = {
  id: 'rpt-2026-11-09-us',
  market: 'US',
  title: '盘后分析',
  generatedAt: '2026-11-09 18:00',
  summary:
    '三大指数收涨，纳指 +1.2% 领跑。科技权重股财报后动量延续，半导体设备链放量；中概震荡分化，电商板块承压。组合内 NVDA 贡献主要超额收益，AAPL 温和跟涨，无触发调仓信号。',
  fullText:
    '风险提示：本周关注 CPI 数据与零售销售；NVDA 短期涨幅已计入乐观预期，若跌破 112 观察位需评估止盈节奏。下一交易日无财报冲击组合持仓，无需主动操作。',
  metrics: [
    { label: '波动率', value: '18.6%' },
    { label: '换手率', value: '1.9%' },
    { label: '关注度', value: '+12%' },
    { label: '风险等级', value: '中' },
  ],
  chart: { title: '60 日走势', unit: '', points: walk(60, 100, 112.4, 1.2) },
}

function walk(n, start, end, vol) {
  const pts = []
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1)
    const base = start + (end - start) * t
    const noise =
      (Math.sin(i * 1.7) * 0.6 + Math.sin(i * 0.53 + 1.3) * 0.5 + Math.sin(i * 0.23) * 0.4) *
      vol *
      Math.sin(Math.PI * t)
    pts.push(Math.round((base + noise) * 100) / 100)
  }
  pts[n - 1] = end
  pts[0] = start
  return pts
}

function memoryItems(_query) {
  return [
    {
      layer: 'long',
      topic: '建仓理由 · AAPL',
      instruments: ['AAPL'],
      confidence: 'high',
      timeRange: '2026-03 ~ 2026-05',
      summary:
        '建仓基于生态护城河与服务收入占比提升；加仓条件为毛利率 >45% 且 PE <30。当时判断 AI 端侧换机周期将在 2 年内兑现，仓位上限设为组合的 15%。',
      evidence: [
        {
          docId: 12,
          date: '2026-03-18',
          label: '建仓决策',
          quote:
            '……服务收入连续四个季度超预期，iOS 用户换机率处于五年低位，等待端侧 AI 催化。计划首批建仓 50 股，回撤 10% 以内不加仓。',
        },
        {
          docId: 34,
          date: '2026-05-06',
          label: '加仓复盘',
          quote: '毛利率 46.2%、PE 28.4，触发加仓条件，按计划加仓至 100 股。剩余预算留给回调机会，不追高。',
        },
      ],
    },
    {
      layer: 'short',
      topic: '昨日盘面观察 · 600519',
      instruments: ['600519'],
      confidence: 'medium',
      timeRange: '2026-11-08',
      summary: '白酒板块放量回调 1.8%，判断为情绪面而非基本面变化；未触发止损线，维持仓位观察。',
      evidence: [
        {
          docId: 2503,
          date: '2026-11-08',
          label: '盘后笔记',
          quote: '北向资金净流出但两融余额稳定，渠道动销数据正常。若连续三日跌破 1,380 再评估止损。',
        },
      ],
    },
  ]
}

function dashboard(range) {
  const RANGES = {
    30: { eqStart: 1190000, eqEnd: 1234567, eqVol: 0.9, rtStart: 1.2, rtEnd: 1.24, rtVol: 0.5 },
    90: { eqStart: 1000000, eqEnd: 1234567, eqVol: 2.4, rtStart: 0, rtEnd: 8.42, rtVol: 1.6 },
    200: { eqStart: 940000, eqEnd: 1234567, eqVol: 4.5, rtStart: 0, rtEnd: 18.2, rtVol: 2.4 },
    365: { eqStart: 820000, eqEnd: 1234567, eqVol: 7, rtStart: 0, rtEnd: 52.6, rtVol: 3.4 },
  }
  const r = RANGES[range] ?? RANGES[90]
  return {
    kpis: {
      totalAssets: 1234567,
      currency: 'CNY',
      dayPnl: 15120,
      dayPnlPct: 1.24,
      totalPnl: 95860,
      totalPnlPct: 8.42,
      annualPct: 12.6,
    },
    series: {
      range: Number(range),
      equity: walk(Number(range), r.eqStart, r.eqEnd, ((r.eqEnd - r.eqStart) * r.eqVol) / 100),
      returns: walk(Number(range), r.rtStart, r.rtEnd, r.rtVol),
    },
    composition: [
      { name: '贵州茅台', value: 21 },
      { name: '腾讯控股', value: 14 },
      { name: '苹果', value: 12 },
      { name: '宁德时代', value: 11 },
      { name: '英伟达', value: 9 },
      { name: '比特币', value: 8 },
      { name: '其他', value: 25 },
    ],
    holdings: HOLDINGS,
    watchlist: WATCHLIST,
  }
}

// ---- write-side state (file-backed so state survives across processes,
// ---- mirroring the kernel's idempotent ledgers) -----------------------------

const STATE_FILE =
  process.env.DEBRIEF_MOCK_STATE ?? fileURLToPath(new URL('./.debrief-mock-state.json', import.meta.url))

function loadState() {
  try {
    return JSON.parse(readFileSync(STATE_FILE, 'utf8'))
  } catch {
    return { reports: [], compactions: [], memories: [], memoryDocSeq: 3000, compactSeq: 1, reportSeq: 1, jobs: {} }
  }
}

function saveState(state) {
  try {
    writeFileSync(STATE_FILE, JSON.stringify(state, null, 0))
  } catch {
    /* best effort; the in-memory copy stays authoritative for this process */
  }
}

const persisted = loadState()
const createdReports = persisted.reports ?? []
const compactedMemories = persisted.compactions ?? []
const addedMemories = persisted.memories ?? []
let memoryDocSeq = persisted.memoryDocSeq ?? 3000
let compactSeq = persisted.compactSeq ?? 1
let reportSeq = persisted.reportSeq ?? 1
const runningJobs = new Map(Object.entries(persisted.jobs ?? {}))
const HOLDINGS = (persisted.holdings ?? SEED_HOLDINGS).map((row, index) => ({
  id: row.id ?? `hld-${index + 1}`,
  ...row,
}))
const WATCHLIST = (persisted.watchlist ?? SEED_WATCHLIST).map((row, index) => ({
  id: row.id ?? `wl-${index + 1}`,
  ...row,
}))

function persistState() {
  saveState({
    reports: createdReports,
    compactions: compactedMemories,
    memories: addedMemories,
    memoryDocSeq,
    compactSeq,
    reportSeq,
    jobs: Object.fromEntries(runningJobs),
    holdings: HOLDINGS,
    watchlist: WATCHLIST,
  })
}

function findRow(list, payload) {
  if (typeof payload.id === 'string' && payload.id !== '') return list.find((row) => row.id === payload.id)
  if (typeof payload.market === 'string' && typeof payload.symbol === 'string') {
    return list.find(
      (row) =>
        row.market.toUpperCase() === payload.market.toUpperCase() &&
        row.symbol.toUpperCase() === payload.symbol.toUpperCase(),
    )
  }
  return undefined
}

function readStdin() {
  return new Promise((resolve) => {
    let data = ''
    process.stdin.setEncoding('utf8')
    process.stdin.on('data', (chunk) => {
      data += chunk
    })
    process.stdin.on('end', () => {
      if (data.trim() === '') {
        resolve(undefined)
        return
      }
      try {
        resolve(JSON.parse(data))
      } catch {
        resolve(undefined)
      }
    })
  })
}

async function main() {
  const stdinPayload = await readStdin()

  switch (command) {
    case 'holdings': {
      const sub = argv[1]
      if (sub === 'add') {
        if (!stdinPayload || typeof stdinPayload !== 'object') {
          console.log(fail('DEBRIEF_USAGE', 'holdings add requires a JSON payload on stdin'))
          break
        }
        const p = stdinPayload
        if (
          typeof p.market !== 'string' ||
          typeof p.symbol !== 'string' ||
          typeof p.quantity !== 'number' ||
          typeof p.cost !== 'number'
        ) {
          console.log(fail('DEBRIEF_USAGE', 'market, symbol, quantity, cost are required'))
          break
        }
        if (findRow(HOLDINGS, p)) {
          console.log(fail('DEBRIEF_CONFLICT', `holding ${p.market}:${p.symbol} already exists`))
          break
        }
        const row = {
          id: `hld-${Date.now()}`,
          market: p.market.toUpperCase(),
          symbol: p.symbol,
          name: typeof p.name === 'string' && p.name !== '' ? p.name : p.symbol,
          quantity: p.quantity,
          cost: p.cost,
          price: p.cost,
          marketValue: Math.round(p.quantity * p.cost * 100) / 100,
          pnlPct: 0,
          weight: 0,
        }
        HOLDINGS.push(row)
        persistState()
        console.log(
          ok({
            id: row.id,
            market: row.market,
            symbol: row.symbol,
            name: row.name,
            quantity: row.quantity,
            cost: row.cost,
          }),
        )
        break
      }
      if (sub === 'update' || sub === 'remove') {
        if (!stdinPayload || typeof stdinPayload !== 'object') {
          console.log(fail('DEBRIEF_USAGE', `holdings ${sub} requires a JSON payload on stdin`))
          break
        }
        const row = findRow(HOLDINGS, stdinPayload)
        if (!row) {
          console.log(fail('DEBRIEF_NOT_FOUND', 'holding not found (id or market+symbol did not match)'))
          break
        }
        if (sub === 'update') {
          if (typeof stdinPayload.quantity === 'number') {
            row.quantity = stdinPayload.quantity
            row.marketValue = Math.round(row.quantity * row.cost * 100) / 100
          }
          if (typeof stdinPayload.cost === 'number') {
            row.cost = stdinPayload.cost
            row.marketValue = Math.round(row.quantity * row.cost * 100) / 100
          }
          persistState()
          console.log(ok({ id: row.id, status: 'updated' }))
          break
        }
        const index = HOLDINGS.indexOf(row)
        HOLDINGS.splice(index, 1)
        persistState()
        console.log(ok({ id: row.id, status: 'removed' }))
        break
      }
      const positions = flags.status === 'open' ? HOLDINGS : HOLDINGS
      console.log(
        ok({
          asOf: '2026-11-10 09:30',
          currency: 'CNY',
          totalMarketValue: 1234567,
          dayPnl: 15120,
          dayPnlPct: 1.24,
          totalPnl: 95860,
          totalPnlPct: 8.42,
          positions,
        }),
      )
      break
    }
    case 'transactions': {
      let items = TRANSACTIONS
      if (flags.ticker) items = items.filter((t) => t.symbol.toLowerCase() === String(flags.ticker).toLowerCase())
      const limit = Math.min(Number(flags.limit) || 20, 100)
      const offset = Number(flags.offset) || 0
      console.log(ok({ total: 48, limit, offset, items: items.slice(offset, offset + limit) }))
      break
    }
    case 'watchlist': {
      const sub = argv[1]
      if (sub === 'add') {
        if (!stdinPayload || typeof stdinPayload !== 'object') {
          console.log(fail('DEBRIEF_USAGE', 'watchlist add requires a JSON payload on stdin'))
          break
        }
        const p = stdinPayload
        if (typeof p.market !== 'string' || typeof p.symbol !== 'string') {
          console.log(fail('DEBRIEF_USAGE', 'market, symbol are required'))
          break
        }
        if (findRow(WATCHLIST, p)) {
          console.log(fail('DEBRIEF_CONFLICT', `watchlist entry ${p.market}:${p.symbol} already exists`))
          break
        }
        const row = {
          id: `wl-${Date.now()}`,
          market: p.market.toUpperCase(),
          symbol: p.symbol,
          name: typeof p.name === 'string' && p.name !== '' ? p.name : p.symbol,
          price: 0,
          changePct: 0,
          targetPrice: typeof p.targetPrice === 'number' ? p.targetPrice : null,
          distancePct: null,
          alert: typeof p.alert === 'boolean' ? p.alert : false,
        }
        WATCHLIST.push(row)
        persistState()
        console.log(
          ok({
            id: row.id,
            market: row.market,
            symbol: row.symbol,
            name: row.name,
            targetPrice: row.targetPrice,
            alert: row.alert,
          }),
        )
        break
      }
      if (sub === 'update' || sub === 'remove') {
        if (!stdinPayload || typeof stdinPayload !== 'object') {
          console.log(fail('DEBRIEF_USAGE', `watchlist ${sub} requires a JSON payload on stdin`))
          break
        }
        const row = findRow(WATCHLIST, stdinPayload)
        if (!row) {
          console.log(fail('DEBRIEF_NOT_FOUND', 'watchlist entry not found (id or market+symbol did not match)'))
          break
        }
        if (sub === 'update') {
          if (typeof stdinPayload.targetPrice === 'number' || stdinPayload.targetPrice === null)
            row.targetPrice = stdinPayload.targetPrice
          if (typeof stdinPayload.alert === 'boolean') row.alert = stdinPayload.alert
          persistState()
          console.log(ok({ id: row.id, status: 'updated' }))
          break
        }
        const index = WATCHLIST.indexOf(row)
        WATCHLIST.splice(index, 1)
        persistState()
        console.log(ok({ id: row.id, status: 'removed' }))
        break
      }
      console.log(ok({ count: WATCHLIST.length, items: WATCHLIST }))
      break
    }
    case 'instruments': {
      const market = flags.market ?? 'us'
      const query = String(flags.query ?? '')
        .trim()
        .toLowerCase()
      const pool = INSTRUMENTS[market.toUpperCase()] ?? []
      const items = query
        ? pool.filter(
            (it) =>
              it.symbol.toLowerCase().includes(query) ||
              it.name.toLowerCase().includes(query) ||
              (it.pinyin ?? '').toLowerCase().includes(query),
          )
        : pool
      console.log(
        ok({
          query: String(flags.query ?? '').trim(),
          market: market.toLowerCase(),
          source:
            market.toLowerCase() === 'crypto' || market.toLowerCase() === 'cc'
              ? 'CoinGecko /coins/list (daily sync) + local search'
              : 'akshare catalog (daily sync) + eastmoney suggest fallback',
          items,
        }),
      )
      break
    }
    case 'report': {
      if (argv[1] === 'create') {
        if (!stdinPayload || typeof stdinPayload !== 'object') {
          console.log(fail('DEBRIEF_ARGS', 'report create requires a JSON payload on stdin'))
          break
        }
        const p = stdinPayload
        if (typeof p.market !== 'string' || typeof p.title !== 'string' || typeof p.summary !== 'string') {
          console.log(fail('DEBRIEF_ARGS', 'market, title, summary are required'))
          break
        }
        const report = { id: `rpt-${reportSeq++}`, status: 'created', ...p }
        createdReports.push(report)
        persistState()
        console.log(ok({ id: report.id, status: 'created' }))
        break
      }
      console.log(ok(flags.id ? { ...REPORT, id: flags.id } : REPORT))
      break
    }
    case 'memory': {
      const sub = argv[1]
      if (sub === 'compact-write') {
        if (!stdinPayload || typeof stdinPayload !== 'object') {
          console.log(fail('DEBRIEF_ARGS', 'memory compact-write requires a JSON payload on stdin'))
          break
        }
        const p = stdinPayload
        if (
          typeof p.topic !== 'string' ||
          !Array.isArray(p.instruments) ||
          typeof p.summary !== 'string' ||
          !Array.isArray(p.evidenceRefs) ||
          typeof p.timeRange !== 'object'
        ) {
          console.log(fail('DEBRIEF_ARGS', 'payload does not match the compact-write schema'))
          break
        }
        const previous = compactedMemories.filter((m) => m.topic === p.topic)
        const version = previous.length + 1
        const entry = { id: `ltm-${compactSeq++}`, topic: p.topic, version, compressedAt: new Date().toISOString() }
        compactedMemories.push(entry)
        persistState()
        console.log(ok({ id: entry.id, version }))
        break
      }
      if (sub === 'add') {
        if (!stdinPayload || typeof stdinPayload !== 'object') {
          console.log(fail('DEBRIEF_ARGS', 'memory add requires a JSON payload on stdin'))
          break
        }
        const p = stdinPayload
        if (typeof p.sourceType !== 'string' || typeof p.content !== 'string' || !Array.isArray(p.instruments)) {
          console.log(fail('DEBRIEF_ARGS', 'sourceType, content, instruments are required'))
          break
        }
        const docId = memoryDocSeq++
        addedMemories.push({ docId, ...p, occurredAt: p.occurredAt ?? new Date().toISOString() })
        persistState()
        console.log(ok({ docId }))
        break
      }
      if (sub === 'compact-candidates') {
        console.log(
          ok({
            windowDays: 30,
            candidates: [
              {
                docId: 1201,
                topic: '建仓理由 · 600519',
                instruments: ['600519'],
                occurredAt: '2026-09-02',
                sourceType: 'decision',
                content: '茅台渠道动销稳定，PE 回到历史中位，按纪律建仓 100 股；止损条件为连续三日低于成本 8%。',
              },
              {
                docId: 1204,
                topic: '建仓理由 · 600519',
                instruments: ['600519'],
                occurredAt: '2026-09-15',
                sourceType: 'note',
                content: '白酒板块回调 3%，检查止损条件未触发，维持仓位；记录观察位 1,380。',
              },
              {
                docId: 1210,
                topic: '止盈纪律 · NVDA',
                instruments: ['NVDA'],
                occurredAt: '2026-09-20',
                sourceType: 'decision',
                content: 'NVDA 单标的权重逼近 15% 上限，短期涨幅计入乐观预期；设观察位 112，跌破评估止盈。',
              },
              {
                docId: 1218,
                topic: '风险预算 · 组合',
                instruments: [],
                occurredAt: '2026-09-28',
                sourceType: 'report',
                content: '组合波动率 18.6%，风险预算内；无调仓信号。',
              },
            ],
          }),
        )
        break
      }
      console.log(ok({ query: String(flags.query ?? '').trim(), items: memoryItems(String(flags.query ?? '')) }))
      break
    }
    case 'analysis': {
      const market = (flags.market ?? 'us').toUpperCase()
      const label = { US: '美股', CN: 'A股', HK: '港股', CC: '加密' }[market] ?? market
      console.log(
        ok({
          market: market.toLowerCase(),
          preparedAt: '2026-11-10 15:30',
          jobId: 'debrief-job-2048',
          inputs: {
            quotes: [
              { symbol: 'NVDA', name: '英伟达', price: 118.2, changePct: 1.8 },
              { symbol: 'AAPL', name: '苹果', price: 189.5, changePct: 0.4 },
              { symbol: 'MSFT', name: '微软', price: 421.3, changePct: -0.3 },
            ],
            news: [
              { title: '半导体设备链订单超预期，板块放量上行', at: '2026-11-10 14:20', source: '财联社' },
              { title: '美联储官员释放鸽派信号，美债收益率回落', at: '2026-11-10 10:05', source: '路透' },
            ],
            memoryCandidates: [
              { topic: '建仓理由 · AAPL', summary: '生态护城河 + 服务收入占比；加仓条件为毛利率 >45% 且 PE <30。' },
              { topic: '止盈纪律 · NVDA', summary: '单标的权重上限 15%，短期涨幅计入乐观预期后观察 112 位。' },
            ],
          },
          guidance: `基于以上 ${label} 行情、新闻与记忆候选，输出结构化盘后结论：一句话总结 / 关键变化 / 组合影响 / 是否触发操作信号（不写库，只呈现）。`,
        }),
      )
      break
    }
    case 'news': {
      let items = NEWS
      if (flags.market) items = items.filter((n) => n.market === String(flags.market).toUpperCase())
      const limit = Math.min(Number(flags.limit) || 20, 100)
      console.log(ok({ fetchedAt: '2026-11-11 15:00', items: items.slice(0, limit) }))
      break
    }
    case 'job': {
      const sub = argv[1]
      if (sub === 'start') {
        if (!stdinPayload || typeof stdinPayload !== 'object' || typeof stdinPayload.kind !== 'string') {
          console.log(fail('DEBRIEF_ARGS', 'job start requires a JSON payload with kind on stdin'))
          break
        }
        const id = `debrief-job-${2048 + runningJobs.size + 1}`
        runningJobs.set(id, {
          id,
          kind: stdinPayload.kind,
          at: new Date().toISOString().slice(0, 16).replace('T', ' '),
          status: 'running',
        })
        persistState()
        console.log(ok({ id, status: 'running' }))
        break
      }
      if (sub === 'status') {
        const id = String(flags.id ?? '')
        const job = runningJobs.get(id) ?? JOBS.find((j) => j.id === id)
        if (!job) {
          console.log(fail('DEBRIEF_NOT_FOUND', `job ${id} not found`))
          break
        }
        console.log(ok(job))
        break
      }
      if (sub === 'finish') {
        if (!stdinPayload || typeof stdinPayload !== 'object' || typeof stdinPayload.id !== 'string') {
          console.log(fail('DEBRIEF_ARGS', 'job finish requires a JSON payload with id on stdin'))
          break
        }
        const job = runningJobs.get(stdinPayload.id)
        if (!job) {
          console.log(fail('DEBRIEF_NOT_FOUND', `job ${stdinPayload.id} not found`))
          break
        }
        const finished = {
          ...job,
          status: stdinPayload.status === 'failed' ? 'failed' : 'succeeded',
          ...(stdinPayload.errorCode ? { errorCode: stdinPayload.errorCode } : {}),
          durationSec: Number(stdinPayload.durationSec) || 1,
        }
        runningJobs.set(stdinPayload.id, finished)
        persistState()
        console.log(ok(finished))
        break
      }
      console.log(ok({ items: [...runningJobs.values(), ...JOBS] }))
      break
    }
    case 'dashboard':
      console.log(ok(dashboard(flags.range ?? '90')))
      break
    default:
      console.error(`unknown command: ${command}`)
      console.log(fail('DEBRIEF_USAGE', `unknown command ${command}`))
      process.exit(2)
  }
}

main().catch((error) => {
  console.error(error)
  console.log(fail('DEBRIEF_EXEC', error instanceof Error ? error.message : String(error)))
  process.exit(1)
})
