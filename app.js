/* ============================================================
 * app.js — US Macro Observer 应用逻辑 (v3 专业分析师版)
 * ============================================================ */

const charts = {};
const COLORS = {
  up: '#e63946', down: '#2a9d8f', neutral: '#6b7280', accent: '#4361ee',
  grid: '#e5e7eb', text: '#6b7280',
  series: ['#4361ee', '#2a9d8f', '#f59e0b', '#e63946', '#7209b7', '#3a86ff', '#e85d75', '#06b6d4']
};
const SECTION_CONFIG = {
  assets:     { title: '大类资产',   subtitle: 'Multi-Asset · 跨资产信号' },
  rates:      { title: '利率',       subtitle: 'Rates · 曲线形态与实际利率拆解' },
  fed:        { title: '美联储',     subtitle: 'Fed · 政策路径与沟通追踪' },
  liquidity:  { title: '流动性',     subtitle: 'Liquidity · 缓冲与价格信号' },
  economy:    { title: '经济数据',   subtitle: 'Economy · 增长/就业/通胀/衰退' },
  credit:     { title: '信用市场',   subtitle: 'Credit · 利差分层与违约周期' },
  volatility: { title: '波动率',     subtitle: 'Volatility · 跨资产波动分化' },
  crypto:     { title: '加密货币',   subtitle: 'Crypto · BTC/ETH/ETF/比率' },
  ai:         { title: 'AI产业链',   subtitle: 'AI Chain · 五层蛋糕价值挖掘' },
  signal:     { title: '矛盾信号',   subtitle: 'Signal · 主导矛盾/领先确认/交叉验证' },
  recession:  { title: '衰退信号',   subtitle: 'Recession · 7项先行指标交叉验证' },
  risk:       { title: '风险总览',   subtitle: 'Risk · 7板块加权聚合风险评分' }
};

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('lastUpdated').textContent = DATA.meta.lastUpdated;
  document.getElementById('dataSourceText').textContent = DATA.meta.dataSource;
  const elAsOf = document.getElementById('dataAsOf');
  if (elAsOf) elAsOf.textContent = DATA.meta.dataAsOf || '—';
  updateMarketStatus();
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => { e.preventDefault(); switchSection(item.dataset.section); });
  });
  // AI 板块内子页面切换 (data-ai-tab)：总览 / 各分层 / 国产替代
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-ai-tab]');
    if (!t) return;
    e.preventDefault();
    const d = DATA.aiChain || { layers: [], bestValuePicks: [], summary: {}, meta: {} };
    _renderAiTab(t.getAttribute('data-ai-tab'), d);
  });
  switchSection('assets');
});

function updateMarketStatus() {
  const now = new Date();
  const etHour = now.getUTCHours() - 5;
  const day = now.getUTCDay();
  const isOpen = day >= 1 && day <= 5 && etHour >= 9 && etHour < 16;
  const badge = document.getElementById('marketStatus');
  if (isOpen) {
    badge.className = 'status-badge';
    badge.querySelector('.status-text').textContent = '市场开盘中';
  } else {
    badge.className = 'status-badge closed';
    badge.querySelector('.status-text').textContent = '市场已收盘';
  }
}

function switchSection(section) {
  document.querySelectorAll('.nav-item').forEach(i => i.classList.toggle('active', i.dataset.section === section));
  const c = SECTION_CONFIG[section];
  document.getElementById('sectionTitle').textContent = c.title;
  document.getElementById('sectionSubtitle').textContent = c.subtitle;
  Object.keys(charts).forEach(k => { if (charts[k]) { charts[k].destroy(); delete charts[k]; } });
  const content = document.getElementById('content');
  content.innerHTML = '';
  const renderers = {
    assets: renderAssets, rates: renderRates, fed: renderFed,
    liquidity: renderLiquidity, economy: renderEconomy,
    credit: renderCredit, volatility: renderVolatility,
    crypto: renderCrypto, recession: renderRecession, risk: renderRisk,
    ai: renderAiChain, signal: renderMacroSignal
  };
  renderers[section](content);
}

/* ================= 通用组件 ================= */

// Regime 横幅
function regimeBanner(r, extraClass) {
  const cls = r.signal === 'risk-off' ? 'risk-off' : r.signal === 'risk-on' ? 'risk-on' : 'mixed';
  const sigLabel = r.signal === 'risk-off' ? '对风险资产利空' : r.signal === 'risk-on' ? '对风险资产利多' : '信号混杂';
  return '<div class="regime-banner ' + cls + ' ' + (extraClass || '') + '">' +
    '<div class="regime-left">' +
      '<div class="regime-label">当前 Regime · ' + sigLabel + '</div>' +
      '<div class="regime-name">' + r.label + '</div>' +
      '<div class="regime-conf">' + r.confidence + '</div>' +
    '</div>' +
    '<div class="regime-right">' + r.description + '</div>' +
  '</div>';
}

// 关键信号列表
function signalList(signals) {
  let html = '<div class="signal-list">';
  signals.forEach(s => {
    const badgeLabel = s.direction === 'bearish' ? '利空' : s.direction === 'bullish' ? '利多' : '中性';
    html += '<div class="signal-item">' +
      '<span class="signal-badge ' + s.direction + '">' + badgeLabel + '</span>' +
      '<div class="signal-body">' +
        '<div class="signal-title">' + s.title + '</div>' +
        '<div class="signal-meaning">' + s.meaning + '</div>' +
      '</div>' +
    '</div>';
  });
  return html + '</div>';
}

// 指标卡 v3：含分位条 + 信号点 + 经济含义 + 四尺度变化
function metricCardsV3(metrics) {
  let html = '<div class="metric-grid">';
  metrics.forEach(m => {
    const changeCls = m.dir || 'neutral';
    const arrow = m.dir === 'up' ? '&#9650;' : m.dir === 'down' ? '&#9660;' : '&#9644;';
    const pct = typeof m.percentile === 'number' ? m.percentile : 50;
    html += '<div class="metric-card-v3">' +
      '<div class="metric-top">' +
        '<div class="metric-label">' + m.label + (m.tag ? ' <span class="metric-tag">' + m.tag + '</span>' : '') + '</div>' +
        (m.signal ? '<span class="metric-signal-dot ' + m.signal + '" title="' + (m.signal === 'bearish' ? '利空风险资产' : m.signal === 'bullish' ? '利多风险资产' : '中性') + '"></span>' : '') +
      '</div>' +
      '<div class="metric-value">' + m.value + '</div>' +
      '<div class="metric-change ' + changeCls + '">' + arrow + ' ' + m.change + ' <span style="color:var(--text-tertiary);font-weight:400">日</span></div>' +
      tfRow(m.changes) +
      '<div class="metric-pct-track">' +
        '<div class="metric-pct-fill" style="width:' + pct + '%"></div>' +
        '<div class="metric-pct-marker" style="left:' + pct + '%"></div>' +
      '</div>' +
      '<div class="metric-pct-labels"><span>1年低分位</span><span>当前 ' + pct + ' 分位</span><span>高分位</span></div>' +
      (m.meaning ? '<div class="metric-meaning">' + m.meaning + '</div>' : '') +
      releaseLine(m) +
      consensusBadge(m) +
    '</div>';
  });
  return html + '</div>';
}

// 经济指标"最新公布 / 下次公布" + 数据源 / 数据获取时间
// (release.latest/next 为按发布频率推算值, estimated=true 标"预计"; source/fetch 为真实信息)
function releaseLine(m) {
  if (!m) return '';
  const parts = [];
  if (m.release) {
    const latest = m.release.latest || '—';
    const nxt = m.release.next || '—';
    const est = m.release.estimated ? ' <span style="color:#b08968">预计</span>' : '';
    parts.push('最新公布 <b style="color:var(--text-secondary,#4b5563);font-weight:600">' + latest + '</b>'
      + ' · 下次公布 <b style="color:var(--text-secondary,#4b5563);font-weight:600">' + nxt + '</b>' + est);
  }
  if (m.source) {
    parts.push('来源 <b style="color:var(--text-secondary,#4b5563);font-weight:600">' + m.source + '</b>');
  }
  const ga = (DATA.economy && DATA.economy.generatedAt) ? DATA.economy.generatedAt : '';
  if (ga) {
    parts.push('获取 <b style="color:var(--text-secondary,#4b5563);font-weight:600">' + ga + '</b>');
  }
  if (!parts.length) return '';
  return '<div style="font-size:11px;color:var(--text-tertiary,#8a93a3);margin-top:7px;padding-top:7px;border-top:1px dashed #ececf1;display:flex;gap:5px;align-items:center;flex-wrap:wrap;line-height:1.6">'
    + '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#9aa3b2;flex:0 0 auto"></span>'
    + parts.join(' · ')
    + '</div>';
}

// 指标卡上的"市场预期 + 结论"徽章（公布值 vs 彭博/路透一致预期）
function consensusBadge(m) {
  if (!m || !m.consensusInfo) return '';
  const ci = m.consensusInfo;
  const vmap = {
    beat:   ['好于预期', '#1d9e75', 'rgba(42,157,143,0.14)'],
    miss:   ['差于预期', '#c0392b', 'rgba(230,57,70,0.14)'],
    inline: ['符合预期', '#6b7280', 'rgba(107,114,128,0.12)'],
  };
  const v = vmap[ci.verdict] || vmap.inline;
  return '<div class="metric-consensus">市场预期 <b>' + ci.consensus + '</b> <span style="color:var(--text-tertiary)">(' + ci.periodLabel + ')</span> · <span class="verdict-badge" style="color:' + v[1] + ';background:' + v[2] + '">' + v[0] + '</span></div>';
}

// 四尺度变化行（日/周/月/半年）
function tfRow(changes) {
  if (!changes) return '';
  const cells = [
    { label: '周', val: changes.w },
    { label: '月', val: changes.m },
    { label: '半年', val: changes.h6 }
  ];
  let html = '<div class="tf-row">';
  cells.forEach(c => {
    const cls = tfClass(c.val);
    html += '<div class="tf-cell"><div class="tf-label">' + c.label + '</div><div class="tf-val ' + cls + '">' + c.val + '</div></div>';
  });
  // 第四格：趋势形状
  html += '<div class="tf-cell"><div class="tf-label">形态</div>' + tfShape(changes) + '</div>';
  return html + '</div>';
}

// 变化值 → 颜色class
function tfClass(val) {
  if (typeof val !== 'string') return 'zero';
  if (val === '—' || val === '0' || val.indexOf('0bp') === 0 || val.indexOf('0%') === 0 || val.indexOf('0pt') === 0) return 'zero';
  if (val.charAt(0) === '+') return 'pos';
  if (val.charAt(0) === '-') return 'neg';
  return 'zero';
}

// 趋势形状：半年→月→周→日 的四点迷你形态图
function tfShape(changes) {
  const nums = [parseTfNum(changes.h6), parseTfNum(changes.m), parseTfNum(changes.w)];
  const maxAbs = Math.max(Math.abs(nums[0]), Math.abs(nums[1]), Math.abs(nums[2]), 0.001);
  let html = '<span class="trend-shape">';
  nums.forEach(v => {
    const h = Math.max(Math.abs(v) / maxAbs * 100, 12);
    const color = v > 0 ? 'var(--up)' : v < 0 ? 'var(--down)' : '#b6bcc9';
    html += '<i style="height:' + h + '%;background:' + color + '"></i>';
  });
  html += '<i class="now" style="height:100%"></i></span>';
  return html;
}

function parseTfNum(val) {
  if (typeof val !== 'string') return 0;
  const n = parseFloat(val.replace(/[^0-9.\-]/g, ''));
  return isNaN(n) ? 0 : n;
}

// 分析师观点框
function analystBox(text) {
  return '<div class="analyst-box">' +
    '<div class="analyst-box-title">分析师观点 Analyst View</div>' +
    '<div class="analyst-box-body">' + text + '</div>' +
  '</div>';
}

// 观察清单
function watchList(items) {
  let html = '<div class="section-h">下一步观察什么 <span class="section-h-sub">触发条件 → 市场含义</span></div><div class="watch-list">';
  items.forEach(w => {
    html += '<div class="watch-item">' +
      '<div class="watch-trigger">' + w.trigger + '</div>' +
      '<div class="watch-implication">' + w.implication + '</div>' +
      '<div class="watch-status">' + w.status + '</div>' +
    '</div>';
  });
  return html + '</div>';
}

// 分区标题
function sectionH(title, sub) {
  return '<div class="section-h">' + title + (sub ? ' <span class="section-h-sub">' + sub + '</span>' : '') + '</div>';
}

function table(headers, rows) {
  let html = '<div class="table-card"><table class="data-table"><thead><tr>';
  headers.forEach(h => { html += '<th>' + h + '</th>'; });
  html += '</tr></thead><tbody>';
  rows.forEach(row => {
    html += '<tr>';
    row.forEach(cell => {
      if (typeof cell === 'object' && cell !== null) {
        const cls = cell.dir === 'up' ? 'pos' : cell.dir === 'down' ? 'neg' : '';
        html += '<td class="' + cls + '">' + cell.text + '</td>';
      } else {
        html += '<td>' + cell + '</td>';
      }
    });
    html += '</tr>';
  });
  return html + '</tbody></table></div>';
}

function chartCard(title, sub, id, h) {
  return '<div class="chart-card"><div class="chart-header"><div><div class="chart-title">' + title + '</div><div class="chart-subtitle">' + sub + '</div></div></div><div class="chart-body ' + (h || '') + '"><canvas id="' + id + '"></canvas></div></div>';
}
function sectionCard(title, sub, inner) {
  return '<div class="chart-card"><div class="chart-header"><div><div class="chart-title">' + title + '</div><div class="chart-subtitle">' + sub + '</div></div></div><div style="padding:4px 4px">' + inner + '</div></div>';
}

// 把 'YYYY-MM-DD' 日期标签格式化为 'YY/MM' 时间轴 (非日期标签原样返回)
function fmtDate(l, idx) {
  // Chart.js v4 category 轴在 maxTicksLimit 自动跳过时常传入数值索引而非标签字符串
  // 此时需通过 this 上下文回查 data.labels 取得真实日期
  var label = l;
  if (typeof label !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(label)) {
    try {
      if (this && this.chart && this.chart.data && this.chart.data.labels) {
        var realIdx = (typeof idx === 'number') ? idx : Math.round(Number(label));
        label = this.chart.data.labels[realIdx] || label;
      }
    } catch(e) {}
  }
  if (typeof label === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(label)) {
    var parts = label.split('-');
    return parts[0].slice(2) + '/' + parts[1];
  }
  // 非ISO日期标签(如 '1月', '26Q2')直接返回回查结果
  return label;
}

function baseOpts(yUnit) {
  const opts = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        display: true, position: 'top',
        labels: { color: COLORS.text, font: { size: 11 }, boxWidth: 12, padding: 12 }
      },
      tooltip: {
        backgroundColor: 'rgba(26,29,41,0.9)', titleColor: '#fff', bodyColor: '#c4c9d4',
        borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1, padding: 10, cornerRadius: 6
      }
    },
    scales: {
      x: {
        grid: { color: COLORS.grid, drawBorder: false },
        ticks: { color: COLORS.text, font: { size: 10 }, maxTicksLimit: 8, callback: fmtDate }
      },
      y: {
        grid: { color: COLORS.grid, drawBorder: false },
        ticks: {
          color: COLORS.text, font: { size: 10 },
          callback: function (v) {
            if (yUnit === '%') return v.toFixed(1) + '%';
            if (yUnit === 'T$') return v.toFixed(2) + 'T';
            return v;
          }
        }
      }
    }
  };
  if (yUnit === '%') {
    opts.plugins.tooltip.callbacks = {
      label: function (ctx) { return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + '%'; }
    };
  }
  return opts;
}

/** 根据数据 min/max 计算更紧的 Y 轴范围，让涨跌更明显
 *  arr: 数据数组
 *  padRatio: 上下边距占 range 的比例
 *  hardMin/hardMax: 可选的硬边界（如利差图保留一点负区间）
 */
function _chartRange(arr, padRatio, hardMin, hardMax) {
  const vals = arr.filter(v => v !== null && v !== undefined && !isNaN(v));
  if (vals.length === 0) return null;
  const min = Math.min.apply(null, vals);
  const max = Math.max.apply(null, vals);
  const range = Math.max(max - min, 0.05); // 至少 5bp/0.05% 的 span，避免单点数据压扁
  const pad = range * padRatio;
  return {
    min: hardMin !== undefined ? Math.min(hardMin, min - pad) : min - pad,
    max: hardMax !== undefined ? Math.max(hardMax, max + pad) : max + pad
  };
}

function sparkline(data, dir) {
  const max = Math.max.apply(null, data), min = Math.min.apply(null, data), range = max - min || 1;
  const color = dir === 'up' ? COLORS.up : dir === 'down' ? COLORS.down : COLORS.neutral;
  let bars = '';
  data.slice(-20).forEach(v => {
    const h = Math.max(((v - min) / range) * 100, 5);
    bars += '<div class="mini-bar" style="height:' + h + '%;background:' + color + ';opacity:0.7;"></div>';
  });
  return '<div class="mini-bars">' + bars + '</div>';
}

function dirTag(direction) {
  const label = direction === 'bearish' ? '利空' : direction === 'bullish' ? '利多' : '中性';
  return '<span class="dir-tag ' + direction + '">' + label + '</span>';
}

/* ================= 多尺度趋势判定 =================
 * 输入四个尺度的数值变化（同单位、带符号）
 * 逻辑：
 *  1. 周与月同向 → 趋势延续；周速率/月速率(折算) > 1.5 → 加速
 *  2. 周与月反向 → 反转预警（短期方向与中期背离）
 *  3. 半年与月反向 → 中期趋势正在切换
 *  4. 全尺度绝对值都小 → 横盘
 */
function computeTrend(ch) {
  const w = ch.w, m = ch.m, h6 = ch.h6;
  const eps = 1e-9;
  const monthlyPace = Math.abs(m);
  const weeklyPace = Math.abs(w) * 4; // 周变化折算成月速率
  const flatThresh = Math.max(Math.abs(h6) * 0.02, 0.05); // 横盘阈值：半年变化的2%

  if (Math.abs(w) < flatThresh && Math.abs(m) < flatThresh) {
    return { cls: 'flat', arrow: '&#9644;', label: '横盘' };
  }
  const sameWM = (w > eps && m > eps) || (w < -eps && m < -eps);
  const sameMH = (m > eps && h6 > eps) || (m < -eps && h6 < -eps);
  const dirUp = w > 0;

  if (!sameWM) {
    // 周月反向 = 反转预警
    return dirUp
      ? { cls: 'reverse-up', arrow: '&#8599;', label: '反转向上' }
      : { cls: 'reverse-dn', arrow: '&#8600;', label: '反转向下' };
  }
  // 周月同向
  const accel = weeklyPace > monthlyPace * 1.5 && monthlyPace > flatThresh;
  if (!sameMH) {
    // 半年与月反向 = 中期趋势切换中
    return dirUp
      ? { cls: 'reverse-up', arrow: '&#8599;', label: '趋势反转中' }
      : { cls: 'reverse-dn', arrow: '&#8600;', label: '趋势反转中' };
  }
  if (dirUp) {
    return accel
      ? { cls: 'accel-up', arrow: '&#8648;', label: '加速上行' }
      : { cls: 'steady-up', arrow: '&#8593;', label: '稳步上行' };
  }
  return accel
    ? { cls: 'accel-dn', arrow: '&#8650;', label: '加速下行' }
    : { cls: 'steady-dn', arrow: '&#8595;', label: '稳步下行' };
}

// 趋势追踪表
function trendTable(trendData) {
  const hasSource = trendData.some(t => t.source);
  let html = '<div class="table-card trend-table"><table class="data-table"><thead><tr>' +
    '<th>指标</th><th>当前值</th><th>日</th><th>周</th><th>月</th><th>半年</th><th>趋势判定</th><th>解读</th>' +
    (hasSource ? '<th>来源</th>' : '') +
    '</tr></thead><tbody>';
  trendData.forEach(t => {
    const trend = computeTrend(t.changes);
    html += '<tr>' +
      '<td style="font-weight:500">' + t.name + '</td>' +
      '<td style="font-variant-numeric:tabular-nums">' + t.current + '</td>' +
      '<td>' + fmtChange(t.changes.d, t.unit) + '</td>' +
      '<td>' + fmtChange(t.changes.w, t.unit) + '</td>' +
      '<td>' + fmtChange(t.changes.m, t.unit) + '</td>' +
      '<td>' + fmtChange(t.changes.h6, t.unit) + '</td>' +
      '<td><span class="trend-badge ' + trend.cls + '"><span class="trend-arrow">' + trend.arrow + '</span>' + trend.label + '</span></td>' +
      '<td style="font-size:11px;color:var(--text-secondary);max-width:280px">' + t.meaning + '</td>' +
      (hasSource ? '<td style="font-size:11px;color:var(--text-tertiary)">' + (t.source || '—') + '</td>' : '') +
    '</tr>';
  });
  return html + '</tbody></table></div>';
}

function fmtChange(v, unit) {
  if (v === null || v === undefined || v !== v) return '<span class="tf-val zero">—</span>';
  if (v === 0) return '<span class="tf-val zero">0</span>';
  const sign = v > 0 ? '+' : '';
  const cls = v > 0 ? 'pos' : 'neg';
  return '<span class="tf-val ' + cls + '">' + sign + v + unit + '</span>';
}

/* ================= 1. 大类资产 ================= */
function renderAssets(c) {
  const d = DATA.assets;
  let html = '';
  // 全局 regime（仅资产页显示全局）
  html += riskScoreBar();
  html += regimeBanner({ label: DATA.globalRegime.name, signal: DATA.globalRegime.signal, confidence: DATA.globalRegime.confidence, description: DATA.globalRegime.description });
  html += regimeBanner(d.regime);
  html += sectionH('关键信号', '按对风险资产的影响方向排序');
  html += signalList(d.keySignals);
  html += metricCardsV3(d.metrics);
  html += '<div class="chart-row two-col">' +
    chartCard('资产走势对比', '近30日累计涨跌(起点=0%)', 'assetsPerf', 'tall') +
    chartCard('跨资产相关性矩阵', '共同交易日日度收益真实相关 · 股债/油股符号变化是regime信号', 'corr', 'tall') +
  '</div>';
  html += chartCard('大类资产热力图', '日涨跌幅 · 红=涨 绿=跌', 'heatmap', 'short');
  html += '<div class="chart-row one-col">' +
    chartCard('美股指数走势（累计涨跌）', d.usIndicesChart.note || '累计涨跌(起点=0%) · 标普500/纳斯达克100/道琼斯/罗素2000/费城半导体', 'usIndices', 'tall') +
    '</div>';
  html += sectionH('多尺度趋势追踪', '日/周/月/半年变化 → 识别趋势确立、加速与反转');
  html += trendTable(d.trendData);
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  html += sectionH('全部资产行情', '');
  html += table(['代码', '名称', '最新价', '日涨跌幅'], d.table.map(r => [r.ticker, r.name, r.price, { text: r.change, dir: r.dir }]));
  c.innerHTML = html;

  const sl = d.chartData.labels.slice(-30), se = d.chartData.series;
  charts.assetsPerf = new Chart(document.getElementById('assetsPerf'), {
    type: 'line',
    data: {
      labels: sl,
      datasets: Object.keys(se).map((n, i) => ({
        label: n,
        data: se[n].slice(-30).map(v => Math.round((v / se[n][0] - 1) * 10000) / 100),
        borderColor: COLORS.series[i], backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3
      }))
    },
    options: baseOpts('%')
  });
  renderCorr(document.getElementById('corr').parentElement, d.correlation);
  renderAssetHeat(document.getElementById('heatmap').parentElement, d.table);
  // 美股五大指数归一化走势
  if (d.usIndicesChart && d.usIndicesChart.series && Object.keys(d.usIndicesChart.series).length > 0) {
    const uid = d.usIndicesChart;
    charts.usIndices = new Chart(document.getElementById('usIndices'), {
      type: 'line',
      data: {
        labels: uid.labels,
        datasets: Object.keys(uid.series).map((n, i) => ({
          label: n, data: uid.series[n],
          borderColor: COLORS.series[i % COLORS.series.length],
          backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3
        }))
      },
      options: baseOpts('%')
    });
  }
}

/* ================= 10. 加密货币 ================= */
function renderCrypto(c) {
  const d = DATA.crypto;
  if (!d) { c.innerHTML = '<div class="loading">加密货币数据加载中...</div>'; return; }
  let html = '';
  html += regimeBanner(d.regime);
  html += sectionH('关键信号', '');
  html += signalList(d.keySignals);
  html += metricCardsV3(d.metrics);
  html += '<div class="chart-row two-col">' +
    chartCard('BTC vs ETH 走势对比', '累计涨跌(起点=0%) · 相对强弱', 'btcEth', 'tall') +
    chartCard('ETH/BTC 比率', 'Altcoin 季节性核心指标 · >0.05 ETH强势', 'ethBtc', 'tall') +
    '</div>';
  if (d.etfFlows && d.etfFlows.labels.length > 0) {
    html += chartCard('现货 ETF 日度净流入/流出', 'BTC $M / ETH $M · 红=流入 绿=流出', 'etfFlow', 'short');
  }
  html += sectionH('多尺度趋势追踪', '');
  html += trendTable(d.trendData);
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  c.innerHTML = html;

  if (d.btcEthChart && d.btcEthChart.series) {
    const be = d.btcEthChart;
    charts.btcEth = new Chart(document.getElementById('btcEth'), {
      type: 'line',
      data: {
        labels: be.labels,
        datasets: Object.keys(be.series).map((n, i) => ({
          label: n, data: be.series[n],
          borderColor: n === 'BTC' ? '#f7931a' : '#627eea',
          backgroundColor: 'transparent', borderWidth: 2.5, pointRadius: 0, tension: 0.3
        }))
      },
      options: baseOpts('%')
    });
  }
  if (d.ethBtcChart && d.ethBtcChart.series && d.ethBtcChart.series['ETH/BTC']) {
    const eb = d.ethBtcChart;
    charts.ethBtc = new Chart(document.getElementById('ethBtc'), {
      type: 'line',
      data: {
        labels: eb.labels,
        datasets: [{
          label: 'ETH/BTC', data: eb.series['ETH/BTC'],
          borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.08)',
          borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true
        }]
      },
      options: Object.assign(baseOpts(''), {
        scales: Object.assign({}, baseOpts('').scales, {
          y: Object.assign({}, baseOpts('').scales.y, {
            ticks: Object.assign({}, baseOpts('').scales.y.ticks, {
              callback: function(v) { return v.toFixed(4); }
            })
          })
        }),
        plugins: Object.assign({}, baseOpts('').plugins, {
          tooltip: Object.assign({}, baseOpts('').plugins.tooltip, {
            callbacks: { label: function(ctx) { return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(5); } }
          })
        })
      })
    });
  }
  if (d.etfFlows && d.etfFlows.labels.length > 0) {
    const ef = d.etfFlows;
    charts.etfFlow = new Chart(document.getElementById('etfFlow'), {
      type: 'bar',
      data: {
        labels: ef.labels,
        datasets: [
          { label: 'BTC ETF ($M)', data: ef.btc, backgroundColor: 'rgba(247,147,26,0.7)', borderColor: '#f7931a', borderWidth: 1, borderRadius: 3 },
          { label: 'ETH ETF ($M)', data: ef.eth, backgroundColor: 'rgba(98,126,234,0.7)', borderColor: '#627eea', borderWidth: 1, borderRadius: 3 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, position: 'top', labels: { color: COLORS.text, font: { size: 11 }, boxWidth: 12 } },
          tooltip: {
            backgroundColor: 'rgba(26,29,41,0.9)', titleColor: '#fff', bodyColor: '#c4c9d4',
            borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1, padding: 10, cornerRadius: 6,
            callbacks: { label: function(ctx) { return ctx.dataset.label + ': ' + (ctx.parsed.y >= 0 ? '+' : '') + ctx.parsed.y.toFixed(1) + 'M$'; } }
          }
        },
        scales: {
          x: { grid: { color: COLORS.grid, drawBorder: false }, ticks: { color: COLORS.text, font: { size: 10 }, maxTicksLimit: 15, callback: fmtDate } },
          y: {
            grid: { color: COLORS.grid, drawBorder: false },
            ticks: { color: COLORS.text, font: { size: 10 }, callback: function(v) { return (v >= 0 ? '+' : '') + v.toFixed(0) + 'M'; } }
          }
        }
      }
    });
  }
}

function renderCorr(container, cd) {
  const a = cd.assets, m = cd.matrix, n = a.length, cs = 42, lw = 60, lh = 30;
  let svg = '<svg viewBox="0 0 ' + (lw + n * cs + 20) + ' ' + (lh + n * cs + 40) + '" width="100%" style="max-width:' + (lw + n * cs + 20) + 'px">';
  a.forEach((x, i) => { svg += '<text x="' + (lw + i * cs + cs / 2) + '" y="' + (lh - 8) + '" text-anchor="middle" font-size="10" fill="' + COLORS.text + '">' + x + '</text>'; });
  a.forEach((x, i) => {
    svg += '<text x="' + (lw - 8) + '" y="' + (lh + i * cs + cs / 2 + 4) + '" text-anchor="end" font-size="10" fill="' + COLORS.text + '">' + x + '</text>';
    a.forEach((y, j) => {
      const v = m[i][j];
      if (v === null || v === undefined) {
        svg += '<rect x="' + (lw + j * cs) + '" y="' + (lh + i * cs) + '" width="' + (cs - 2) + '" height="' + (cs - 2) + '" rx="3" fill="#eef0f4"/>';
        svg += '<text x="' + (lw + j * cs + cs / 2) + '" y="' + (lh + i * cs + cs / 2 + 4) + '" text-anchor="middle" font-size="10" fill="' + COLORS.text + '">—</text>';
        return;
      }
      const int = Math.abs(v);
      const bg = v > 0 ? 'rgba(230,57,70,' + (0.1 + int * 0.7) + ')' : 'rgba(42,157,143,' + (0.1 + int * 0.7) + ')';
      svg += '<rect x="' + (lw + j * cs) + '" y="' + (lh + i * cs) + '" width="' + (cs - 2) + '" height="' + (cs - 2) + '" rx="3" fill="' + bg + '"/>';
      svg += '<text x="' + (lw + j * cs + cs / 2) + '" y="' + (lh + i * cs + cs / 2 + 4) + '" text-anchor="middle" font-size="10" fill="' + (int > 0.5 ? '#fff' : COLORS.text) + '">' + v.toFixed(2) + '</text>';
    });
  });
  svg += '</svg>';
  container.innerHTML = '<div style="overflow-x:auto">' + svg + '</div>' + (cd.note ? '<p style="font-size:12px;color:' + COLORS.up + ';margin-top:8px">' + cd.note + '</p>' : '');
}

function renderAssetHeat(container, tbl) {
  let html = '<div style="display:flex;flex-wrap:wrap;gap:6px;padding:8px 0">';
  tbl.forEach(r => {
    const ch = parseFloat(r.change), int = Math.min(Math.abs(ch) / 3, 1);
    let bg = '#eef0f4';
    if (r.dir === 'up') bg = 'rgba(230,57,70,' + (0.15 + int * 0.6) + ')';
    if (r.dir === 'down') bg = 'rgba(42,157,143,' + (0.15 + int * 0.6) + ')';
    const tc = int > 0.4 ? '#fff' : COLORS.text;
    html += '<div style="background:' + bg + ';border-radius:6px;padding:10px 14px;text-align:center;min-width:100px">' +
      '<div style="font-size:11px;color:' + tc + ';opacity:0.9">' + r.name + '</div>' +
      '<div style="font-size:14px;font-weight:600;color:' + tc + '">' + (ch > 0 ? '+' : '') + ch.toFixed(2) + '%</div></div>';
  });
  container.innerHTML = html + '</div>';
}

/* ================= 2. 利率 ================= */
function renderRates(c) {
  const d = DATA.rates;
  let html = '';
  html += regimeBanner(d.regime);
  html += sectionH('关键信号', '');
  html += signalList(d.keySignals);
  html += metricCardsV3(d.metrics);
  html += '<div class="chart-row two-col">' +
    chartCard('国债收益率曲线', '今日 vs 1月前 vs 1年前 · 熊陡=长端领涨', 'yc', 'tall') +
    chartCard('名义 vs 实际利率', '实际利率是估值的真实折现率', 'rateTrend', 'tall') +
  '</div>';
  html += '<div class="chart-row two-col">' +
    chartCard('10Y-2Y 利差', (d.chartNotes || {}).spreadNote || '曲线陡峭化/倒挂/平坦', 'spreadChart', 'tall') +
    chartCard('10Y 通胀预期 (Breakeven)', '名义利率 − 实际利率 = 市场通胀预期', 'breakevenChart', 'tall') +
  '</div>';
  html += sectionH('多尺度趋势追踪', (d.chartNotes || {}).trendNote || '日/周/月/半年变化 → 识别趋势确立、加速与反转');
  html += trendTable(d.trendData);
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  html += sectionH('关键期限利率拆解', '名义利率 = 实际利率 + 通胀预期');
  html += table(['期限', '名义利率', '日变动', '实际利率', '通胀预期', '数据源'], d.detailedTable.map(r => [r.maturity, r.rate, r.change, r.realRate, r.breakeven, r.source]));
  c.innerHTML = html;

  const yc = d.yieldCurve;
  charts.yc = new Chart(document.getElementById('yc'), {
    type: 'line',
    data: {
      labels: yc.maturities,
      datasets: [
        { label: '今日', data: yc.today, borderColor: COLORS.up, backgroundColor: 'transparent', borderWidth: 2.5, pointRadius: 4, tension: 0.4 },
        { label: '1月前', data: yc.oneMonthAgo, borderColor: COLORS.accent, backgroundColor: 'transparent', borderWidth: 1.5, borderDash: [5, 3], pointRadius: 2, tension: 0.4 },
        { label: '1年前', data: yc.oneYearAgo, borderColor: COLORS.neutral, backgroundColor: 'transparent', borderWidth: 1.5, borderDash: [5, 3], pointRadius: 2, tension: 0.4 }
      ]
    },
    options: baseOpts('%')
  });

  const cd = d.chartData;
  charts.rateTrend = new Chart(document.getElementById('rateTrend'), {
    type: 'line',
    data: {
      labels: cd.labels,
      datasets: Object.keys(cd.series).map((n, i) => ({
        label: n, data: cd.series[n], borderColor: COLORS.series[i],
        backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3
      }))
    },
    options: baseOpts('%')
  });

  const sd = d.spreadData;
  // 图1: 10Y-2Y 利差 (Y 轴按数据动态收紧，保留一点负区间以感知倒挂风险)
  const _spArr = sd.series['10Y-2Y利差'] || [];
  if (_spArr.length > 0) {
    const _spRange = _chartRange(_spArr, 0.25, -0.3);
    charts.spread = new Chart(document.getElementById('spreadChart'), {
      type: 'line',
      data: {
        labels: sd.labels,
        datasets: [{ label: '10Y-2Y利差', data: _spArr, borderColor: COLORS.series[0],
          backgroundColor: COLORS.series[0] + '15', borderWidth: 2, fill: true, pointRadius: 0, tension: 0.3 }]
      },
      options: Object.assign(baseOpts('%'), {
        scales: Object.assign({}, baseOpts('%').scales, {
          y: Object.assign({}, baseOpts('%').scales.y, {
            min: _spRange ? _spRange.min : -1.5,
            max: _spRange ? _spRange.max : 1.5,
            ticks: Object.assign({}, baseOpts('%').scales.y.ticks, {
              callback: function(v) { return v.toFixed(1) + '%'; }
            })
          })
        })
      })
    });
  }
  // 图2: Breakeven 通胀预期 (Y 轴按数据动态收紧，让 2.0~2.5% 区间的波动更明显)
  const _beArr = sd.series['通胀预期(Breakeven)'] || [];
  if (_beArr.length > 0) {
    const _beRange = _chartRange(_beArr, 0.2);
    charts.breakeven = new Chart(document.getElementById('breakevenChart'), {
      type: 'line',
      data: {
        labels: sd.labels,
        datasets: [{ label: 'Breakeven', data: _beArr, borderColor: '#e63946',
          backgroundColor: 'rgba(230,57,70,0.08)', borderWidth: 2, fill: true, pointRadius: 0, tension: 0.3 }]
      },
      options: Object.assign(baseOpts('%'), {
        scales: Object.assign({}, baseOpts('%').scales, {
          y: Object.assign({}, baseOpts('%').scales.y, {
            min: _beRange ? _beRange.min : 1.5,
            max: _beRange ? _beRange.max : 3.5,
            ticks: Object.assign({}, baseOpts('%').scales.y.ticks, {
              callback: function(v) { return v.toFixed(2) + '%'; }
            })
          })
        })
      })
    });
  }
}

/* ================= 3. 美联储 ================= */
function renderFed(c) {
  const d = DATA.fed;
  let html = '';
  html += regimeBanner(d.regime);
  html += sectionH('关键信号', '');
  html += signalList(d.keySignals);
  html += metricCardsV3(d.metrics);
  html += '<div class="chart-row two-col">' +
    chartCard('美联储资产负债表', '总资产/国债/MBS(万亿美元) · QT持续推进', 'fedBs', 'tall') +
    chartCard('鹰鸽指数', (d.chartNotes || {}).hawkNote || ('0=极度鸽派 / 10=极度鹰派 · 当前 ' + d.hawkishDovish.score + ' ' + d.hawkishDovish.label), 'hawkDov', 'tall') +
  '</div>';
  html += sectionCard('FOMC 会议时间线', '油价表态是7月会议的唯一看点', renderFomcTimeline(d.fomcTimeline));
  html += '<div style="height:16px"></div>';
  html += sectionCard('官员讲话追踪', '鹰鸽分化公开化=政策不确定性上升', renderSpeeches(d.speeches));
  html += '<div style="height:16px"></div>';
  html += sectionCard('利率路径预期', d.hawkishDovish.ratePath.note, renderRatePath(d.hawkishDovish.ratePath));
  html += '<div style="height:16px"></div>';
  html += sectionCard('市场隐含 Fed 路径', (d.impliedPath && d.impliedPath.note) || '收益率曲线短端反推的市场政策利率预期', renderImpliedPath(d.impliedPath));
  html += sectionH('多尺度趋势追踪', (d.chartNotes || {}).probNote || '日/周/月/半年变化 → 识别政策预期重定价');
  html += trendTable(d.trendData);
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  html += sectionH('政策工具箱状态', '');
  html += table(['项目', '数值', '变动', '备注'], d.policyTable.map(r => [r.item, r.value, r.change, r.note]));
  c.innerHTML = html;

  const cd = d.chartData;
  charts.fedBs = new Chart(document.getElementById('fedBs'), {
    type: 'line',
    data: {
      labels: cd.labels,
      datasets: Object.keys(cd.series).map((n, i) => ({
        label: n, data: cd.series[n], borderColor: COLORS.series[i],
        backgroundColor: i === 0 ? COLORS.series[i] + '15' : 'transparent',
        borderWidth: 2, fill: i === 0, pointRadius: 0, tension: 0.3
      }))
    },
    options: baseOpts('T$')
  });
  renderHawkDovGauge(d.hawkishDovish);
}

function renderFomcTimeline(tl) {
  let html = '<div style="display:flex;gap:12px;overflow-x:auto;padding:4px 0">';
  tl.forEach(e => {
    const dotColor = e.type === 'decision' ? '#e63946' : e.type === 'meeting' ? '#4361ee' : e.type === 'rate' ? '#f59e0b' : '#7209b7';
    html += '<div style="min-width:200px;border:1px solid #e5e7eb;border-radius:8px;padding:12px;background:#f8faff">' +
      '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px"><span style="width:8px;height:8px;border-radius:50%;background:' + dotColor + '"></span><span style="font-size:11px;color:' + COLORS.text + '">' + e.date + '</span></div>' +
      '<div style="font-size:13px;font-weight:500;margin-bottom:4px">' + e.event + '</div>' +
      '<div style="font-size:11px;color:' + COLORS.neutral + '">' + e.status + '</div></div>';
  });
  return html + '</div>';
}

function renderSpeeches(sp) {
  let html = '<div>';
  sp.forEach(s => {
    const stColor = s.stance === 'hawkish' ? '#e63946' : s.stance === 'dovish' ? '#2a9d8f' : '#6b7280';
    const stLabel = s.stance === 'hawkish' ? '鹰派' : s.stance === 'dovish' ? '鸽派' : '中性';
    const stBg = s.stance === 'hawkish' ? '#fde8ea' : s.stance === 'dovish' ? '#e4f4ef' : '#eef0f4';
    html += '<div style="display:flex;align-items:flex-start;gap:12px;padding:12px 0;border-bottom:1px solid #f0f0f0">' +
      '<div style="min-width:50px"><div style="font-size:12px;color:' + COLORS.text + '">' + s.date + '</div></div>' +
      '<div style="flex:1"><div style="font-size:13px;font-weight:500">' + s.speaker + '</div>' +
      '<div style="font-size:12px;color:' + COLORS.text + ';margin-top:2px">' + s.title + '</div>' +
      (s.url ? '<div style="font-size:11px;margin-top:5px"><a href="' + s.url + '" target="_blank" rel="noopener" style="color:#4361ee;text-decoration:none">查看原文 →</a></div>' : '') +
      '</div>' +
      '<div style="text-align:center;min-width:56px"><span style="padding:3px 10px;border-radius:12px;background:' + stBg + ';color:' + stColor + ';font-size:11px">' + stLabel + '</span></div></div>';
  });
  return html + '</div>';
}

function renderRatePath(rp) {
  let html = '<div><div style="display:flex;justify-content:space-between;margin-bottom:10px"><span style="font-size:13px">下次会议: ' + rp.nextMeeting + '</span></div>';
  const probs = [
    { label: '维持不变', val: rp.holdProb, color: '#6b7280' },
    { label: '降息25bp', val: rp.cut25bpProb, color: '#2a9d8f' },
    { label: '降息50bp', val: rp.cut50bpProb, color: '#4361ee' }
  ];
  html += '<div style="display:flex;gap:12px">';
  probs.forEach(p => {
    html += '<div style="flex:1;text-align:center">' +
      '<div style="height:8px;background:#eef0f4;border-radius:4px;overflow:hidden;margin-bottom:6px"><div style="height:100%;width:' + p.val + '%;background:' + p.color + ';border-radius:4px"></div></div>' +
      '<div style="font-size:11px;color:' + COLORS.text + '">' + p.label + '</div>' +
      '<div style="font-size:16px;font-weight:600;color:' + p.color + '">' + p.val + '%</div></div>';
  });
  return html + '</div></div>';
}

function renderImpliedPath(ip) {
  if (!ip) return '';
  const ff = ip.currentFF, cuts = ip.cuts12m, hikes = ip.hikes12m, term = ip.terminal2y, sig = ip.signal;
  let html = '<div>';
  if (ip.points && ip.points.length) {
    html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">';
    ip.points.forEach(p => {
      html += '<div style="flex:1;min-width:90px;text-align:center;background:#f8faff;border:1px solid #eef1f6;border-radius:8px;padding:10px 6px">' +
        '<div style="font-size:11px;color:#8a93a3">' + p.tenor + '</div>' +
        '<div style="font-size:18px;font-weight:600;color:#1f2937">' + p.rate.toFixed(2) + '%</div>' +
        '<div style="font-size:10px;color:#8a93a3">隐含政策利率</div></div>';
    });
    html += '</div>';
  }
  html += '<div style="display:flex;gap:10px;flex-wrap:wrap;font-size:12px">';
  if (cuts && cuts > 0) html += '<span style="padding:4px 10px;border-radius:12px;background:#e4f4ef;color:#2a9d8f">未来12个月隐含降息 ' + cuts + ' 次 (25bp)</span>';
  else if (hikes && hikes > 0) html += '<span style="padding:4px 10px;border-radius:12px;background:#fde8ea;color:#e63946">未来12个月隐含加息 ' + hikes + ' 次 (25bp)</span>';
  else html += '<span style="padding:4px 10px;border-radius:12px;background:#f3f4f6;color:#4b5563">未来12个月无隐含变动</span>';
  if (term !== null && term !== undefined) html += '<span style="padding:4px 10px;border-radius:12px;background:#eef1f6;color:#4361ee">2Y 隐含终值 ' + term.toFixed(2) + '%</span>';
  if (ff !== null && ff !== undefined) html += '<span style="padding:4px 10px;border-radius:12px;background:#f3f4f6;color:#4b5563">当前上限 ' + ff.toFixed(2) + '%</span>';
  html += '</div></div>';
  return html;
}

function renderHawkDovGauge(hd) {
  const canvas = document.getElementById('hawkDov');
  const score = hd.score || 0;
  const label = hd.label || '';
  const isHawk = score > 5;

  // 半圆仪表盘参数
  const cx = 200, cy = 140, r = 110;
  // score 0→角度180°(左/鸽), score 10→角度0°(右/鹰)
  const angleDeg = 180 - (score / 10) * 180;
  const angleRad = (angleDeg * Math.PI) / 180;

  // 指针坐标
  const needleLen = r - 18;
  const nx = cx + needleLen * Math.cos(angleRad);
  const ny = cy - needleLen * Math.sin(angleRad);
  const tailLen = 18;
  const tx = cx - tailLen * Math.cos(angleRad);
  const ty = cy + tailLen * Math.sin(angleRad);

  // 弧线颜色: 鸽绿(0) → 中黄(5) → 鹰红(10)
  let gaugeColor;
  if (score <= 5) {
    const t = score / 5;
    gaugeColor = 'rgb(' + Math.round(42 + t*192) + ',' + Math.round(157 - t*28) + ',' + Math.round(143 - t*99) + ')';
  } else {
    const t = (score - 5) / 5;
    gaugeColor = 'rgb(' + Math.round(234 + t*6) + ',' + Math.round(129 - t*113) + ',' + Math.round(44 - t*4) + ')';
  }

  let svg = '<svg viewBox="0 0 400 300" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block">';

  // ── 1. 背景弧（灰底半圆）──
  svg += '<path d="M' + (cx-r) + ',' + cy + ' A' + r + ',' + r + ' 0 0,1 ' + (cx+r) + ',' + cy + '" fill="none" stroke="#e8eaed" stroke-width="14" stroke-linecap="round"/>';

  // ── 2. 彩色填充弧（从左到当前值，large-arc 始终=0：半圆最大跨度=180°）──
  if (score > 0.02) {
    var ex = cx + r * Math.cos(angleRad);
    var ey = cy - r * Math.sin(angleRad);
    svg += '<path d="M' + (cx-r) + ',' + cy + ' A' + r + ',' + r + ' 0 0,1 ' + ex.toFixed(1) + ',' + ey.toFixed(1) + '" fill="none" stroke="' + gaugeColor + '" stroke-width="14" stroke-linecap="round"/>';
  }

  // ── 3. 刻度线 + 数字标签 ──
  [0, 2.5, 5, 7.5, 10].forEach(function(v) {
    var a = ((180 - v / 10 * 180) * Math.PI) / 180;
    var x1 = cx + (r + 10) * Math.cos(a), y1 = cy - (r + 10) * Math.sin(a);
    var x2 = cx + (r + 20) * Math.cos(a), y2 = cy - (r + 20) * Math.sin(a);
    svg += '<line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) + '" x2="' + x2.toFixed(1) + '" y2="' + y2.toFixed(1) + '" stroke="#9aa3b2" stroke-width="1.5" stroke-linecap="round"/>';
    var tx = cx + (r + 30) * Math.cos(a), ty = cy - (r + 30) * Math.sin(a);
    var anchor = v === 0 ? 'end' : v === 10 ? 'start' : 'middle';
    svg += '<text x="' + tx.toFixed(1) + '" y="' + (ty + 4).toFixed(1) + '" text-anchor="' + anchor + '" font-size="11" fill="#8892a0">' + v + '</text>';
  });

  // ── 4. 底部文字标签（鸽派/中性/鹰派）──
  svg += '<text x="' + (cx - r - 12) + '" y="' + (cy + 36) + '" text-anchor="end" font-size="12" font-weight="600" fill="#2a9d8f">鸽派</text>';
  svg += '<text x="' + cx + '" y="' + (cy + 36) + '" text-anchor="middle" font-size="11" fill="#9aa3b2">中性</text>';
  svg += '<text x="' + (cx + r + 12) + '" y="' + (cy + 36) + '" text-anchor="start" font-size="12" font-weight="600" fill="#e63946">鹰派</text>';

  // ── 5. 指针（带阴影）──
  svg += '<defs><filter id="hdS"><feDropShadow dx="0" dy="1.5" stdDeviation="2" flood-opacity="0.2"/></filter></defs>';
  svg += '<line x1="' + tx.toFixed(1) + '" y1="' + ty.toFixed(1) + '" x2="' + nx.toFixed(1) + '" y2="' + ny.toFixed(1) + '" stroke="#374151" stroke-width="2.5" stroke-linecap="round" filter="url(#hdS)"/>';
  svg += '<circle cx="' + cx + '" cy="' + cy + '" r="7" fill="#374151"/>';
  svg += '<circle cx="' + cx + '" cy="' + cy + '" r="3.5" fill="#fff"/>';

  // ── 6. 中心大字数值 + 标签 ──
  svg += '<text x="' + cx + '" y="' + (cy + 62) + '" text-anchor="middle" font-size="34" font-weight="700" fill="' + (isHawk ? '#e63946' : '#2a9d8f') + '">' + score.toFixed(1) + '</text>';
  svg += '<text x="' + cx + '" y="' + (cy + 82) + '" text-anchor="middle" font-size="13" font-weight="500" fill="#6b7280">' + label + '</text>';

  // ── 7. 方法说明小字 ──
  if (hd.method) {
    svg += '<text x="' + cx + '" y="' + (cy + 100) + '" text-anchor="middle" font-size="10" fill="#b0b8c4">' + hd.method + '</text>';
  }

  svg += '</svg>';

  // 替换 canvas 为 SVG
  canvas.parentElement.innerHTML = svg;

  // 官员标签行（追加到 chart-card 内）
  var card = canvas.parentElement.parentElement;
  var row = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;padding:0 4px">';
  hd.officials.forEach(function(o) {
    var sc = o.stance === 'hawkish' ? '#e63946' : o.stance === 'dovish' ? '#2a9d8f' : '#9aa3b2';
    var lb = o.stance === 'hawkish' ? '鹰' : o.stance === 'dovish' ? '鸽' : '中';
    row += '<div style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:14px;background:#f6f7f9">' +
      '<span style="font-size:11px;color:#374151;font-weight:500">' + o.name + '</span>' +
      '<span style="font-size:10px;padding:1px 6px;border-radius:10px;background:' + sc + ';color:#fff;font-weight:600">' + lb + o.score + '</span></div>';
  });
  card.insertAdjacentHTML('beforeend', row + '</div>');
}

/* ================= 4. 流动性 ================= */
function renderLiquidity(c) {
  const d = DATA.liquidity;
  let html = '';
  html += regimeBanner(d.regime);
  html += sectionH('关键信号', '');
  html += signalList(d.keySignals);
  html += sectionCard('净流动性公式', 'RRP耗尽后，QT与TGA的每一美元都直击准备金', renderNetLiqFormula(d.formula));
  html += '<div style="height:16px"></div>';
  html += metricCardsV3(d.metrics);
  html += '<div class="chart-row two-col">' +
    chartCard('流动性构成走势', '净流动性/准备金/TGA(万亿美元)', 'liqChart', 'tall') +
    chartCard('LPI 流动性压力指数', '规则型监测(0-10) · 结构紧但价格未确认', 'lpiChart', 'tall') +
  '</div>';
  html += renderLPIComponents(d.lpi);
  html += renderConfirmConds(d.lpi.confirmationConditions);
  html += sectionH('多尺度趋势追踪', (d.chartNotes || {}).trendNote || '日/周/月/半年变化 → 识别流动性收缩斜率');
  html += trendTable(d.trendData);
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  html += sectionH('各组件变动追踪', '信号列=对风险资产影响方向');
  html += table(['组成项', '当前值', '周变动', '月变动', '数据源', '信号'], d.weeklyChanges.map(r => [r.component, r.current, r.weekChange, r.monthChange, r.source, dirTag(r.signal)]));
  c.innerHTML = html;

  const cd = d.chartData;
  charts.liq = new Chart(document.getElementById('liqChart'), {
    type: 'line',
    data: {
      labels: cd.labels,
      datasets: Object.keys(cd.series).map((n, i) => ({
        label: n, data: cd.series[n], borderColor: COLORS.series[i],
        backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3
      }))
    },
    options: baseOpts('T$')
  });
  renderLPIGauge(d.lpi);
}

function renderNetLiqFormula(f) {
  let html = '<div style="display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;padding:12px 0">';
  f.components.forEach((comp, i) => {
    const valStr = comp.value < 0.01 ? comp.value.toFixed(4) : comp.value.toFixed(2);
    html += '<div style="text-align:center;min-width:130px">' +
      '<div style="font-size:11px;color:' + COLORS.text + '">' + comp.name + '</div>' +
      '<div style="font-size:20px;font-weight:700;color:' + comp.color + '">' + comp.sign + valStr + comp.unit + '</div>' +
      '<div style="font-size:10px;color:' + COLORS.neutral + '">' + comp.note + '</div></div>';
    if (i < f.components.length - 1) {
      html += '<div style="font-size:22px;color:' + COLORS.neutral + '">' + (f.components[i + 1].sign === '−' ? '−' : '+') + '</div>';
    }
  });
  html += '<div style="font-size:22px;color:' + COLORS.neutral + '">=</div>';
  html += '<div style="text-align:center;min-width:130px;padding:10px 18px;border:2px solid #4361ee;border-radius:8px;background:#e8ecff">' +
    '<div style="font-size:11px;color:#4361ee">净流动性</div>' +
    '<div style="font-size:24px;font-weight:700;color:#4361ee">$' + f.netLiquidity.toFixed(2) + 'T</div>' +
    '<div style="font-size:10px;color:' + COLORS.neutral + '">4周收缩 $58B，斜率变陡</div></div>';
  return html + '</div>';
}

function renderLPIGauge(lpi) {
  const canvas = document.getElementById('lpiChart');
  charts.lpi = new Chart(canvas, {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [3, 2, 2, 3],
        backgroundColor: ['#2a9d8f', '#f59e0b', '#e63946', '#7f1d1d'],
        borderWidth: 0, circumference: 180, rotation: 270
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      cutout: '70%'
    },
    plugins: [{
      id: 'lpiC',
      afterDraw(chart) {
        const ctx = chart.ctx;
        const cx = chart.chartArea.left + (chart.chartArea.right - chart.chartArea.left) / 2;
        const cy = chart.chartArea.bottom - 10;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.font = 'bold 36px sans-serif';
        ctx.fillStyle = '#f59e0b';
        ctx.fillText(lpi.score.toFixed(1), cx, cy - 20);
        ctx.font = '14px sans-serif';
        ctx.fillStyle = COLORS.text;
        ctx.fillText(lpi.level, cx, cy);
        ctx.font = '11px sans-serif';
        ctx.fillStyle = COLORS.neutral;
        ctx.fillText('趋势 ' + lpi.trend, cx, cy + 18);
        ctx.restore();
      }
    }]
  });
}

function renderLPIComponents(lpi) {
  let html = '<div class="chart-row one-col"><div class="chart-card"><div class="chart-header"><div><div class="chart-title">LPI 三大组成</div><div class="chart-subtitle">结构性缓冲45% + 融资确认35% + 风险传导20%</div></div></div><div style="padding:0 4px">';
  lpi.components.forEach(comp => {
    const pct = (comp.score / 10) * 100;
    const color = comp.score < 3 ? '#2a9d8f' : comp.score < 5 ? '#f59e0b' : '#e63946';
    html += '<div style="margin-bottom:14px">' +
      '<div style="display:flex;justify-content:space-between;margin-bottom:4px">' +
      '<span style="font-size:13px;font-weight:500">' + comp.name + '<span style="color:' + COLORS.neutral + ';font-weight:400"> (' + comp.weight + ')</span></span>' +
      '<span style="font-size:13px;font-weight:600;color:' + color + '">' + comp.score.toFixed(1) + '/10</span></div>' +
      '<div style="height:8px;background:#eef0f4;border-radius:4px;overflow:hidden"><div style="height:100%;width:' + pct + '%;background:' + color + ';border-radius:4px"></div></div>' +
      '<div style="font-size:11px;color:' + COLORS.text + ';margin-top:3px">' + comp.note + '</div></div>';
  });
  return html + '</div></div></div>';
}

function renderConfirmConds(conds) {
  let html = '<div class="chart-row one-col"><div class="chart-card"><div class="chart-header"><div><div class="chart-title">系统性压力确认条件</div><div class="chart-subtitle">价格信号触发前，结构性紧张不构成交易主线</div></div></div><div style="padding:4px 0">';
  conds.forEach(cnd => {
    const near = cnd.status === '接近触发';
    const sc = cnd.triggered ? '#e63946' : near ? '#f59e0b' : '#2a9d8f';
    const sb = cnd.triggered ? '#fde8ea' : near ? '#fdf3e2' : '#e4f4ef';
    html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid #f0f0f0">' +
      '<div><div style="font-size:13px;font-weight:500">' + cnd.name + '</div>' +
      '<div style="font-size:11px;color:' + COLORS.text + '">当前: ' + cnd.current + '</div></div>' +
      '<span style="padding:3px 10px;border-radius:12px;background:' + sb + ';color:' + sc + ';font-size:12px">' + cnd.status + '</span></div>';
  });
  return html + '</div></div></div>';
}

/* ================= 5. 经济数据 ================= */
function renderEconomy(c) {
  const d = DATA.economy;
  let html = '';
  html += riskScoreBar();
  html += regimeBanner(d.regime);
  if (d.generatedAt) {
    html += '<div style="font-size:11px;color:var(--text-tertiary,#8a93a3);margin:2px 0 14px;padding:7px 12px;background:rgba(154,163,178,0.08);border-radius:8px;display:flex;gap:6px;align-items:center">' +
      '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#4caf50"></span>' +
      '经济数据获取时间：<b style="color:var(--text-secondary,#4b5563);font-weight:600">' + d.generatedAt + '</b>' +
      ' · 各项指标已标注数据源与参考期' +
      '</div>';
  }
  // 数据源回退警告 (PMI / Empire State 静态兜底时提示)
  const _fallbackWarnings = [];
  if (d.pmi_meta && d.pmi_meta.is_fallback) {
    const asof = d.pmi_meta.asof ? (' 数据截至 ' + d.pmi_meta.asof) : '';
    _fallbackWarnings.push('<b style="color:#b76e00">PMI 数据源警告：当前为静态兜底数据</b><br>S&amp;P Global PMI 实时抓取失败，已回退至内置历史序列' + asof + '，可能非最新值。关注官方发布后自动恢复。');
  }
  if (d.empire_meta && d.empire_meta.is_fallback) {
    const easof = d.empire_meta.asof ? (' 数据截至 ' + d.empire_meta.asof) : '';
    _fallbackWarnings.push('<b style="color:#b76e00">Empire State 警告：当前为静态兜底数据</b><br>纽约联储 Empire State 制造业指数实时抓取失败，已回退至内置历史序列' + easof + '。NY Fed 官网可能暂时不可用，将在下次运行时重试。');
  }
  if (_fallbackWarnings.length) {
    html += '<div style="font-size:12px;color:#8a5a00;margin:2px 0 14px;padding:9px 12px;background:#fff6e5;border:1px solid #ffd591;border-radius:8px;display:flex;gap:8px;align-items:flex-start">' +
      '<span style="display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;background:#ffa940;color:#fff;font-weight:700;font-size:13px;flex-shrink:0">!</span>' +
      '<div>' + _fallbackWarnings.join('<br><br>') + '</div></div>';
  }
  html += sectionH('关键信号', '');
  html += signalList(d.keySignals);
  html += metricCardsV3(d.metrics);
  html += renderReleaseCompare(d.releases, d.releasesMeta);
  const cn = d.chartNotes || {};
  html += '<div class="chart-row two-col">' +
    chartCard('通胀三线图 (真实同比)', cn.inflNote || 'CPI/核心CPI/核心PCE 同比走势', 'inflChart', 'tall') +
    chartCard('GDP 增长: 名义 vs 实际', cn.gdpNote || '季度同比', 'gdpChart', 'tall') +
  '</div>';
  html += '<div class="chart-row one-col">' +
    chartCard('就业市场', cn.empNote || '失业率 + 劳动参与率', 'empChart', 'tall') +
  '</div>';
  html += '<div class="chart-row one-col">' +
    chartCard('PMI 景气指数 (荣枯线追踪)', cn.pmiNote || '制造业 + 服务业 PMI · 荣枯线50', 'pmiChart', 'tall') +
  '</div>';
  html += sectionCard('CPI 通胀分项拆解 (真实同比)', cn.breakdownSub || '分项同比 vs 上月', renderInflationBreakdown(d.inflationBreakdown));
  html += sectionH('多尺度趋势追踪', cn.trendNote || '月度指标: 月格=上月Δ, 半年格=6个月Δ');
  html += trendTable(d.trendData);
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  html += sectionH('消费数据追踪', '消费占GDP约68%，是增长的锚');
  html += table(['指标', '最新值', '前值', '趋势', '备注'], d.consumptionTable.map(r => [r.indicator, r.value, r.prev, { text: r.trend === 'up' ? '&#9650;' : '&#9660;', dir: r.trend }, r.note]));
  c.innerHTML = html;

  const id = d.inflationChart;
  charts.infl = new Chart(document.getElementById('inflChart'), {
    type: 'line',
    data: {
      labels: id.labels,
      datasets: Object.keys(id.series).map((n, i) => ({
        label: n, data: id.series[n], borderColor: COLORS.series[i],
        backgroundColor: 'transparent', borderWidth: 2, pointRadius: 3, tension: 0.3
      }))
    },
    options: baseOpts('%')
  });

  const gd = d.gdpChart;
  charts.gdp = new Chart(document.getElementById('gdpChart'), {
    type: 'bar',
    data: {
      labels: gd.labels,
      datasets: Object.keys(gd.series).map((n, i) => ({
        label: n, data: gd.series[n],
        backgroundColor: COLORS.series[i] + '90', borderColor: COLORS.series[i], borderWidth: 1, borderRadius: 3
      }))
    },
    options: baseOpts('%')
  });

  const ed = d.employmentChart;
  charts.emp = new Chart(document.getElementById('empChart'), {
    type: 'line',
    data: {
      labels: ed.labels,
      datasets: [
        {
          label: '失业率(%)', data: ed.series['失业率(%)'],
          borderColor: '#e63946', backgroundColor: 'transparent', borderWidth: 2.5, pointRadius: 3, tension: 0.3, yAxisID: 'y'
        },
        {
          label: '劳动参与率(%)', data: ed.series['劳动参与率(%)'],
          borderColor: '#4361ee', backgroundColor: 'transparent', borderWidth: 2.5, pointRadius: 3, tension: 0.3, yAxisID: 'y1'
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, position: 'top', labels: { color: COLORS.text, font: { size: 11 } } },
        tooltip: {
          backgroundColor: 'rgba(26,29,41,0.9)', titleColor: '#fff', bodyColor: '#c4c9d4', padding: 10,
          callbacks: { label: function (c) { return c.dataset.label + ': ' + c.parsed.y + '%'; } }
        }
      },
      scales: {
        x: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text, callback: fmtDate } },
        y: { position: 'left', grid: { color: COLORS.grid }, ticks: { color: COLORS.text, callback: function (v) { return v + '%'; } }, title: { display: true, text: '失业率 %', color: COLORS.text } },
        y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: COLORS.text, callback: function (v) { return v + '%'; } }, title: { display: true, text: '参与率 %', color: COLORS.text } }
      }
    }
  });

  const pd = d.pmiChart;
  if (pd && pd.labels && pd.labels.length) {
    const pmiColors = { '制造业PMI': '#4361ee', '服务业PMI': '#2a9d8f', '荣枯线(50)': '#e63946' };
    charts.pmi = new Chart(document.getElementById('pmiChart'), {
      type: 'line',
      data: {
        labels: pd.labels,
        datasets: Object.keys(pd.series).map(n => {
          const isThr = n.indexOf('荣枯线') >= 0;
          return {
            label: n, data: pd.series[n],
            borderColor: pmiColors[n] || '#888',
            backgroundColor: 'transparent',
            borderWidth: isThr ? 1.5 : 2,
            borderDash: isThr ? [6, 4] : [],
            pointRadius: isThr ? 0 : 3, tension: 0.3
          };
        })
      },
      options: baseOpts('')
    });
  }
}

function renderInflationBreakdown(items) {
  let html = '<div>';
  if (!items || !items.length) return '<div style="padding:12px;color:' + COLORS.text + ';font-size:12px">分项数据暂缺</div>';
  items.forEach(it => {
    const pct = Math.min(Math.abs(parseFloat(it.yoy)) / 6 * 100, 100);  // 条形=|同比|占6%比例
    const color = it.trend === 'up' ? '#e63946' : it.trend === 'down' ? '#2a9d8f' : '#6b7280';
    const trendLabel = it.trend === 'up' ? '↑ 加速' : it.trend === 'down' ? '↓ 回落' : '→ 持平';
    html += '<div style="display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid #f0f0f0">' +
      '<div style="min-width:150px"><div style="font-size:13px;font-weight:500">' + it.component + '</div>' +
      '<div style="font-size:11px;color:' + COLORS.neutral + '">' + it.note + '</div></div>' +
      '<div style="min-width:56px;text-align:right;font-size:13px;font-weight:600">' + it.yoy + '</div>' +
      '<div style="min-width:64px;text-align:right;font-size:11px;color:' + color + '">' + trendLabel + '</div>' +
      '<div style="min-width:60px;text-align:right;font-size:12px;color:' + COLORS.text + '" title="同比的上月变化">' + it.contribution + '</div>' +
      '<div style="flex:1;height:6px;background:#eef0f4;border-radius:3px;overflow:hidden"><div style="height:100%;width:' + pct + '%;background:' + color + ';border-radius:3px"></div></div></div>';
  });
  return html + '</div>';
}

// 经济数据公布对比：公布值 vs 市场预期（策展）
// 结论按"市场反应方向"着色：好于预期=绿、差于预期=红、符合预期=灰
function renderReleaseCompare(releases, meta) {
  if (!releases || !releases.length) return '';
  const V = {
    beat:   { t: '好于预期', c: '#1d9e75', bg: 'rgba(42,157,143,0.14)' },
    miss:   { t: '差于预期', c: '#c0392b', bg: 'rgba(230,57,70,0.14)' },
    inline: { t: '符合预期', c: '#6b7280', bg: 'rgba(107,114,128,0.12)' },
    na:     { t: '—', c: '#9ca3af', bg: 'rgba(107,114,128,0.10)' },
  };
  let nb = 0, nm = 0, ni = 0;
  const rows = releases.map(function (r) {
    const v = V[r.verdict] || V.na;
    if (r.verdict === 'beat') nb++; else if (r.verdict === 'miss') nm++; else if (r.verdict === 'inline') ni++;
    return '<tr>' +
      '<td><div style="font-weight:600;font-size:13px;color:var(--text-primary,#1f2937)">' + r.indicator + '</div>' +
        '<div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">' + r.periodLabel + ' · 公布 ' + r.releaseDate + '</div></td>' +
      '<td style="text-align:right"><b style="font-size:16px;font-weight:700">' + r.actualStr + '</b></td>' +
      '<td style="text-align:right;color:var(--text-secondary);font-size:14px">' + r.consensusStr + '</td>' +
      '<td style="text-align:right;color:var(--text-tertiary);font-size:13px">' + r.previousStr + '</td>' +
      '<td style="text-align:right;font-size:12px;font-weight:600;color:' + v.c + '">' + r.surpriseStr + '</td>' +
      '<td style="text-align:center"><span class="verdict-badge" style="color:' + v.c + ';background:' + v.bg + '">' + v.t + '</span></td>' +
      '<td style="font-size:11px;color:var(--text-secondary);line-height:1.5;max-width:260px">' + r.note + '</td>' +
    '</tr>';
  }).join('');
  const summary = '本批公布：<b style="color:#1d9e75">' + nb + ' 项好于预期</b> · <b style="color:#c0392b">' + nm + ' 项差于预期</b>' + (ni ? (' · <b style="color:#6b7280">' + ni + ' 项符合预期</b>') : '');
  const metaNote = (meta && meta.asOf) ? ('数据截至 ' + meta.asOf + ' · 市场预期=彭博/路透一致预期中值') : '市场预期=彭博/路透一致预期中值';
  return '<div class="chart-card"><div class="chart-header"><div><div class="chart-title">数据公布对比：公布值 vs 市场预期</div>' +
    '<div class="chart-subtitle">对比"市场预期值"比"与上期比较"更能反映预期差；结论按市场反应方向（通胀走低=好，就业/增长走高=好）</div></div></div>' +
    '<div style="padding:12px 16px">' +
      '<div style="font-size:12px;margin-bottom:10px;color:var(--text-secondary)">' + summary + ' &nbsp;·&nbsp; <span style="color:var(--text-tertiary)">' + metaNote + '</span></div>' +
      '<div class="table-card"><table class="data-table release-table"><thead><tr>' +
        '<th>指标 (参考期)</th><th style="text-align:right">公布值</th><th style="text-align:right">市场预期</th><th style="text-align:right">前值</th><th style="text-align:right">预期差</th><th style="text-align:center">结论</th><th>解读</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
    '</div></div>';
}

/* ================= 6. 信用市场 ================= */
function renderCredit(c) {
  const d = DATA.credit;
  let html = '';
  html += regimeBanner(d.regime);
  html += sectionH('关键信号', '');
  html += signalList(d.keySignals);
  html += metricCardsV3(d.metrics);
  html += '<div class="chart-row two-col">' +
    chartCard('各评级利差走势', 'CCC已率先走阔——信用分层的早期信号', 'creditChart', 'tall') +
    chartCard('利差阶梯：当前 vs 历史中位', (d.chartNotes || {}).ladderNote || 'vs中位为负=利差窄于历史中枢', 'ladderChart', 'tall') +
  '</div>';
  html += sectionH('多尺度趋势追踪', (d.chartNotes || {}).trendNote || 'HY vs CCC 内部背离是关键信号');
  html += trendTable(d.trendData);
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  html += sectionH('各评级利差明细', 'vs中位为负=利差窄于历史中枢');
  html += table(['评级', '当前OAS', '历史中位', 'vs中位', '5年违约率', '备注'], d.ratingTable.map(r => [r.rating, r.oas, r.median, r.vsMedian, r.default5y, r.note]));
  c.innerHTML = html;

  const cd = d.chartData;
  charts.credit = new Chart(document.getElementById('creditChart'), {
    type: 'line',
    data: {
      labels: cd.labels,
      datasets: Object.keys(cd.series).map((n, i) => ({
        label: n, data: cd.series[n], borderColor: COLORS.series[i],
        backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3
      }))
    },
    options: baseOpts('%')
  });

  const ld = d.ladder;
  charts.ladder = new Chart(document.getElementById('ladderChart'), {
    type: 'bar',
    data: {
      labels: ld.ratings,
      datasets: [
        { label: '当前OAS', data: ld.oas, backgroundColor: '#4361ee', borderRadius: 4 },
        { label: '历史中位', data: ld.histMedian, backgroundColor: '#c8cdd8', borderRadius: 4 },
        { label: '历史P10(最紧)', data: ld.histP10, backgroundColor: '#2a9d8f', borderRadius: 4 }
      ]
    },
    options: baseOpts('%')
  });
}

/* ================= 7. 波动率 ================= */
function renderVolatility(c) {
  const d = DATA.volatility;
  let html = '';
  html += regimeBanner(d.regime);
  html += sectionH('关键信号', '');
  html += signalList(d.keySignals);
  html += metricCardsV3(d.metrics);
  const vn = d.chartNotes || {};
  html += '<div class="chart-row two-col">' +
    chartCard('跨资产波动率走势 (累计涨跌)', vn.volNote || '起点=0%, 累计涨跌', 'volChart', 'tall') +
    chartCard('VIX 期限结构', vn.tsNote || 'Contango=未定价即时风险', 'termStruct', 'tall') +
  '</div>';
  html += sectionCard('跨资产波动率仪表盘', vn.dashNote || '压力区定位冲击源头', renderCrossAssetVol(d.crossAsset));
  html += sectionH('多尺度趋势追踪', vn.trendNote || '日/周/月/半年变化 → 识别波动率趋势');
  html += trendTable(d.trendData);
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  html += sectionH('波动率 Regime 表', '');
  html += table(['指标', '数值', '当前状态', '参考区间', '备注'], d.regimeTable.map(r => [r.indicator, r.value, r.current, r.range, r.note]));
  c.innerHTML = html;

  const cd = d.chartData;
  charts.vol = new Chart(document.getElementById('volChart'), {
    type: 'line',
    data: {
      labels: cd.labels,
      datasets: Object.keys(cd.series).map((n, i) => ({
        label: n, data: cd.series[n], borderColor: COLORS.series[i],
        backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3
      }))
    },
    options: baseOpts('%')
  });

  const ts = d.termStructure;
  charts.termStruct = new Chart(document.getElementById('termStruct'), {
    type: 'bar',
    data: {
      labels: ts.labels,
      datasets: [{
        label: 'VIX期限结构', data: ts.values,
        backgroundColor: ts.values.map((v, i) => 'rgba(67,97,238,' + (0.3 + i / ts.values.length * 0.5) + ')'),
        borderRadius: 4
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
      scales: {
        x: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text } },
        y: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text } }
      }
    }
  });
}

function renderCrossAssetVol(ca) {
  let html = '<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>波动率指标</th><th>当前值</th><th>1年分位</th><th>正常水平</th><th>压力线</th><th>状态</th></tr></thead><tbody>';
  ca.labels.forEach((label, i) => {
    const cur = ca.current[i], rank = ca.pctRank30d[i], norm = ca.normal[i], stress = ca.stress[i];
    let status, statusColor;
    if (cur >= stress) { status = '压力区'; statusColor = '#e63946'; }
    else if (cur >= norm) { status = '中性'; statusColor = '#f59e0b'; }
    else { status = '低位'; statusColor = '#2a9d8f'; }
    html += '<tr><td>' + label + '</td><td style="font-weight:600">' + cur + '</td>' +
      '<td><div style="display:flex;align-items:center;gap:6px"><div style="width:60px;height:6px;background:#eef0f4;border-radius:3px;overflow:hidden"><div style="height:100%;width:' + rank + '%;background:' + statusColor + ';border-radius:3px"></div></div><span style="font-size:11px;color:' + COLORS.neutral + '">' + rank + '%</span></div></td>' +
      '<td>' + norm + '</td><td>' + stress + '</td>' +
      '<td><span style="padding:2px 8px;border-radius:10px;background:' + statusColor + '20;color:' + statusColor + ';font-size:11px">' + status + '</span></td></tr>';
  });
  return html + '</tbody></table></div><div style="font-size:12px;color:' + COLORS.neutral + ';margin-top:8px">' + (ca.note || '') + '</div>';
}

/* ================= 全局风险评分条 (显示在每个板块顶部) ================= */
function riskScoreBar() {
  const rs = DATA.riskScore;
  if (!rs) return '';
  return '<div class="risk-score-bar">' +
    '<div class="risk-score-gauge" style="background:' + rs.color + '">' + rs.score + '</div>' +
    '<div class="risk-score-info">' +
      '<div class="risk-score-label">宏观风险: ' + rs.level + ' (' + rs.score + '/100)</div>' +
      '<div class="risk-score-desc">' + rs.summary + '</div>' +
      '<div class="risk-score-factors">' +
        rs.factors.map(function(f) {
          return '<span class="risk-factor-chip ' + f.status + '">' + f.label + ': ' + f.score + '</span>';
        }).join('') +
      '</div>' +
    '</div></div>';
}

/* ================= 8. 衰退信号仪表盘 ================= */
function renderRecession(c) {
  const d = DATA.recession;
  if (!d) { c.innerHTML = '<div class="loading">数据加载中...</div>'; return; }
  let html = '';
  html += riskScoreBar();
  html += regimeBanner(d.regime, 'recession');
  // 红绿灯面板
  html += '<div class="section-h">衰退先行指标红绿灯 <span class="section-h-sub">7项独立信号交叉验证</span></div>';
  html += '<div class="traffic-grid">';
  d.signals.forEach(function(s) {
    const icon = s.status === 'triggered' ? '🔴' : s.status === 'warning' ? '🟡' : s.status === 'safe' ? '🟢' : '⚪';
    const statusLabel = s.status === 'triggered' ? '已触发' : s.status === 'warning' ? '关注中' : s.status === 'safe' ? '安全' : '数据待更新';
    html += '<div class="traffic-item">' +
      '<div class="traffic-light ' + s.status + '">' + icon + '</div>' +
      '<div class="traffic-info">' +
        '<div class="traffic-label">' + s.label + ' <span style="font-size:10px;color:var(--text-tertiary)">阈值: ' + s.threshold + '</span></div>' +
        '<div class="traffic-value ' + s.status + '">' + (s.value !== null ? s.value : '—') + '</div>' +
        '<div class="traffic-meaning">' + s.meaning + '</div>' +
      '</div>' +
    '</div>';
  });
  html += '</div>';
  // 周期定位
  html += '<div class="chart-row one-col">' +
    '<div class="chart-card"><div class="chart-header"><div><div class="chart-title">经济周期定位</div><div class="chart-subtitle">基于衰退概率综合评分的粗粒度周期判断</div></div></div>' +
    '<div style="display:flex;align-items:center;gap:24px;padding:16px 0">' +
      '<div style="background:' + (d.score >= 40 ? '#fde8ea' : d.score >= 20 ? '#fdf3e2' : '#e4f4ef') + ';padding:16px 24px;border-radius:12px;text-align:center;min-width:120px">' +
        '<div style="font-size:28px;font-weight:700">' + d.score + '</div>' +
        '<div style="font-size:12px;margin-top:4px">衰退评分/100</div></div>' +
      '<div><div style="font-size:15px;font-weight:600">当前阶段: ' + (d.cyclePosition || '数据不足') + '</div>' +
      '<div style="font-size:12px;color:var(--text-secondary);margin-top:6px;line-height:1.6">衰退周期判定: 扩张早期(0-20) → 扩张后期(20-40) → 放缓(40-60) → 衰退(60-80) → 深度衰退(80+)</div></div>' +
    '</div></div></div>';
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  c.innerHTML = html;
}

/* ================= 9. 风险总览 ================= */
function renderRisk(c) {
  const d = DATA.riskScore;
  if (!d) { c.innerHTML = '<div class="loading">数据加载中...</div>'; return; }
  let html = '';
  html += '<div class="chart-row one-col">' +
    '<div class="chart-card"><div class="chart-header"><div><div class="chart-title">宏观风险评分仪表盘</div><div class="chart-subtitle">7板块加权聚合 0-100 · ' + d.level + '</div></div></div>' +
    '<div style="text-align:center;padding:20px 0">' +
      '<div style="display:inline-block;width:140px;height:140px;border-radius:50%;background:' + d.color + ';display:flex;flex-direction:column;align-items:center;justify-content:center">' +
        '<div style="font-size:40px;font-weight:700;color:#fff">' + d.score + '</div>' +
        '<div style="font-size:14px;color:rgba(255,255,255,0.85)">/ 100</div>' +
        '<div style="font-size:12px;color:rgba(255,255,255,0.7);margin-top:2px">' + d.level + '</div>' +
      '</div>' +
    '</div>' +
    '<div style="padding:0 20px 16px"><p style="font-size:13px;color:var(--text-secondary);line-height:1.7;text-align:center">' + d.description + '</p></div>' +
    '</div></div>';
  // 各因子详情
  html += '<div class="section-h">风险因子明细 <span class="section-h-sub">权重 × 得分 → 综合风险画像</span></div>';
  d.factors.forEach(function(f) {
    const barColor = f.status === 'bearish' ? '#e63946' : f.status === 'mixed' ? '#f59e0b' : '#2a9d8f';
    const statusLabel = f.status === 'bearish' ? '利空' : f.status === 'mixed' ? '中性' : '利多';
    html += '<div class="chart-card" style="margin-bottom:10px">' +
      '<div style="display:flex;align-items:center;gap:16px">' +
        '<div style="min-width:90px;font-size:14px;font-weight:600">' + f.label + '</div>' +
        '<div style="flex:1"><div style="height:10px;background:#eef0f4;border-radius:5px;overflow:hidden">' +
          '<div style="height:100%;width:' + f.score + '%;background:' + barColor + ';border-radius:5px"></div></div></div>' +
        '<div style="min-width:56px;text-align:right;font-size:18px;font-weight:700;color:' + barColor + '">' + f.score + '</div>' +
        '<span class="risk-factor-chip ' + f.status + '">' + statusLabel + ' · 权重' + f.weight + '%</span>' +
      '</div></div>';
  });
  html += '<div style="margin:16px 0">' + analystBox(d.summary) + '</div>';
  c.innerHTML = html;
}

/* ================= 经济数据板块增强 ================= */
// 重写 renderEconomy 以加入劳动力市场和通胀深化
var _origRenderEconomy = renderEconomy;
renderEconomy = function(c) {
  _origRenderEconomy(c);
  // 在 analystView 前插入劳动力市场面板和通胀深化
  var d = DATA.economy;
  var insertHtml = '';
  // 劳动力市场三角面板
  if (d.laborPanel) {
    var lp = d.laborPanel;
    insertHtml += '<div class="section-h">劳动力市场: 需求-供给-价格三角 <span class="section-h-sub">' + (lp.analystNote || '') + '</span></div>';
    insertHtml += '<div class="labor-grid">';
    // 需求列
    insertHtml += '<div class="labor-col"><div class="labor-col-header demand">需求 Demand</div>';
    lp.demand.forEach(function(item) {
      insertHtml += '<div class="labor-item"><div class="labor-item-name">' + item.indicator + '</div>' +
        '<div class="labor-item-val">' + item.value + '</div>' +
        '<div class="labor-item-note">' + (item.note || '') + (item.prev ? ' · ' + item.prev : '') + '</div></div>';
    });
    insertHtml += '</div>';
    // 供给列
    insertHtml += '<div class="labor-col"><div class="labor-col-header supply">供给 Supply</div>';
    lp.supply.forEach(function(item) {
      insertHtml += '<div class="labor-item"><div class="labor-item-name">' + item.indicator + '</div>' +
        '<div class="labor-item-val">' + item.value + '</div>' +
        '<div class="labor-item-note">' + (item.note || '') + (item.prev ? ' · ' + item.prev : '') + '</div></div>';
    });
    insertHtml += '</div>';
    // 价格列
    insertHtml += '<div class="labor-col"><div class="labor-col-header price">价格 Price</div>';
    lp.price.forEach(function(item) {
      insertHtml += '<div class="labor-item"><div class="labor-item-name">' + item.indicator + '</div>' +
        '<div class="labor-item-val">' + item.value + '</div>' +
        '<div class="labor-item-note">' + (item.note || '') + (item.prev ? ' · ' + item.prev : '') + '</div></div>';
    });
    insertHtml += '</div>';
    insertHtml += '</div>';
  }
  // 通胀深化
  if (d.inflationDeepening && d.inflationDeepening.annualized3m !== null) {
    var idp = d.inflationDeepening;
    insertHtml += '<div class="chart-row one-col"><div class="chart-card"><div class="chart-header"><div><div class="chart-title">通胀温度计</div><div class="chart-subtitle">美联储内部最看重的核心CPI 3月/6月年化 + 工资-通胀验证</div></div></div>' +
      '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;padding:8px 0">' +
        '<div style="text-align:center;padding:16px;border:1px solid var(--border-card);border-radius:8px;background:' + (idp.annualized3m > 3 ? '#fef2f2' : '#f0fdf4') + '">' +
          '<div style="font-size:11px;color:var(--text-secondary)">核心CPI 3月年化</div>' +
          '<div style="font-size:28px;font-weight:700;color:' + (idp.annualized3m > 3 ? '#e63946' : '#2a9d8f') + '">' + (idp.annualized3m ? idp.annualized3m.toFixed(1) + '%' : '—') + '</div>' +
          '<div style="font-size:11px;color:var(--text-tertiary)">vs 同比 ' + (DATA.economy.metrics[2] ? DATA.economy.metrics[2].value : '—') + '</div></div>' +
        '<div style="text-align:center;padding:16px;border:1px solid var(--border-card);border-radius:8px;background:' + (idp.annualized6m > 3 ? '#fef2f2' : '#f0fdf4') + '">' +
          '<div style="font-size:11px;color:var(--text-secondary)">核心CPI 6月年化</div>' +
          '<div style="font-size:28px;font-weight:700;color:' + (idp.annualized6m > 3 ? '#e63946' : '#2a9d8f') + '">' + (idp.annualized6m ? idp.annualized6m.toFixed(1) + '%' : '—') + '</div>' +
          '<div style="font-size:11px;color:var(--text-tertiary)">平滑版更可靠</div></div>' +
        '<div style="text-align:center;padding:16px;border:1px solid var(--border-card);border-radius:8px;background:' + (idp.wage_inflation_gap > 0 ? '#fef2f2' : '#f0fdf4') + '">' +
          '<div style="font-size:11px;color:var(--text-secondary)">工资-通胀差</div>' +
          '<div style="font-size:28px;font-weight:700;color:' + (idp.wage_inflation_gap > 0 ? '#e63946' : '#2a9d8f') + '">' + (idp.wage_inflation_gap ? idp.wage_inflation_gap.toFixed(1) + 'pt' : '—') + '</div>' +
          '<div style="font-size:11px;color:var(--text-tertiary)">' + (idp.wage_inflation_gap > 0 ? '工资料快于通胀' : '通胀快于工资') + '</div></div>' +
      '</div>' +
      '<div style="font-size:12px;color:var(--text-secondary);margin-top:8px;line-height:1.6">' + (d.inflationDeepening.analystNote || '') + '</div>' +
    '</div></div>';
  }
  // 插入到分析师观点前
  var els = c.querySelectorAll('.analyst-box');
  if (els.length > 0) {
    var beforeEl = els[0];
    var tempDiv = document.createElement('div');
    tempDiv.innerHTML = insertHtml;
    while (tempDiv.firstChild) {
      beforeEl.parentNode.insertBefore(tempDiv.firstChild, beforeEl);
    }
  }
};

/* ================= AI 产业链 (Jensen 五层蛋糕) ================= */
function _aiColor(v) {
  v = v || 0;
  if (v >= 65) return '#2a9d8f';
  if (v >= 48) return '#4361ee';
  if (v >= 35) return '#f59e0b';
  return '#e63946';
}
function _aiPct(x) {
  if (x === null || x === undefined) return { text: '—', dir: '' };
  var t = (x >= 0 ? '+' : '') + x.toFixed(1) + '%';
  return { text: t, dir: x > 0 ? 'up' : (x < 0 ? 'down' : '') };
}
function _aiBar(v, color) {
  v = Math.max(0, Math.min(100, v || 0));
  return '<div style="flex:1;height:8px;background:var(--border-card);border-radius:5px;overflow:hidden">'
    + '<div style="height:100%;width:' + v + '%;background:' + (color || 'var(--accent)') + ';border-radius:5px"></div></div>';
}
function _aiTags(tags) {
  if (!tags || !tags.length) return '<span style="color:var(--text-tertiary)">—</span>';
  var cmap = { '价值股候选': '#2a9d8f', '高估值': '#e63946', '领跑': '#4361ee', '高质量': '#b08968' };
  return tags.map(function (t) {
    var c = cmap[t] || '#6b7280';
    return '<span style="display:inline-block;font-size:10px;padding:2px 7px;border-radius:10px;color:#fff;background:' + c + ';margin:1px 2px 1px 0">' + t + '</span>';
  }).join('');
}
function _aiMkt(m) {
  var m2 = { 'US': { f: '🇺🇸', t: '美股' }, 'A': { f: '🇨🇳', t: 'A股' }, 'KR': { f: '🇰🇷', t: '韩股' } };
  var x = m2[m] || { f: '🌐', t: (m || '?') };
  return '<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:8px;background:rgba(67,97,238,0.12);color:var(--accent);margin-left:4px;white-space:nowrap">' + x.f + ' ' + x.t + '</span>';
}
function _aiCcySym(ccy) {
  return ({ 'USD': '$', 'CNY': '¥', 'KRW': '₩' })[ccy] || '$';
}
// 折叠面板：标题可点击展开/收起 (用于层内次要模块)
function _aiCollapse(title, bodyHtml, open) {
  return '<details class="ai-collapse"' + (open ? ' open' : '') + '><summary>' + title + '</summary><div class="ai-collapse-body">' + bodyHtml + '</div></details>';
}
function renderAiValuePicks(list) {
  if (!list || !list.length) return '<div style="color:var(--text-tertiary);font-size:12px">当前未筛选出明显被低估的标的（可放宽阈值或等待动量回撤）。</div>';
  var headers = ['公司', '所属层', 'AI价值分', '层内分位', '为何被低估'];
  var rows = list.map(function (p) {
    return ['<b>' + p.ticker + '</b> <span style="font-size:11px;color:var(--text-secondary)">' + p.name + '</span>',
      '<span style="font-size:11px">' + p.layer + '</span>',
      '<span style="font-weight:700;color:#2a9d8f">' + p.aiValue + '</span>',
      '<span style="font-size:11px;color:var(--text-tertiary)">P' + (p.layerPct != null ? p.layerPct : 50) + '</span>',
      '<span style="font-size:11px;color:var(--text-secondary)">' + p.why + '</span>'];
  });
  return table(headers, rows)
    + '<div style="font-size:11px;color:var(--text-tertiary);margin-top:8px;line-height:1.5">⚠ 跨层排名仅供参考——各层商业模式/估值体系不同（如 15 倍代工厂与 60 倍 SaaS 不可直接比绝对分），价值挖掘更应看「层内分位 P」与基本面质量。</div>';
}
function renderAiCycle(cyc) {
  if (!cyc) return '';
  var heat = cyc.heat || 0, hc = _aiColor(heat);
  var hlabel = (heat >= 65 ? '偏热 · 警惕' : heat >= 45 ? '温和偏热' : '冷静');
  var inner = '';
  inner += '<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:12px">'
    + '<div style="flex:1;min-width:230px"><div style="font-size:11px;color:var(--text-tertiary);margin-bottom:4px">AI 产业链热度计（数据驱动：价格动量 + 估值昂贵度 + 领跑广度）</div>'
    + _aiBar(heat, hc) + ' <b style="font-size:13px">' + heat + '</b> · ' + hlabel + '</div>'
    + '<div style="font-size:12px;color:var(--text-secondary)">阶段：<b>' + (cyc.stage || '—') + '</b></div></div>';
  if (cyc.capex && cyc.capex.length) {
    inner += '<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin:6px 0 6px">💰 四大 hyperscaler 资本开支 ($B, 策展估计)</div>';
    var ch = ['公司', 'FY25', 'FY26e', 'YoY', '备注'];
    var rows = cyc.capex.map(function (r) {
      return ['<b>' + r.name + '</b>' + (r.ticker ? ' <span style="font-size:10px;color:var(--text-tertiary)">' + r.ticker + '</span>' : ''),
        (r.fy25 != null ? r.fy25 : '—'), (r.fy26e != null ? r.fy26e : '—'),
        (r.yoy != null ? '<span style="color:' + (r.yoy >= 0 ? 'var(--up)' : 'var(--down)') + '">' + (r.yoy * 100).toFixed(0) + '%</span>' : '—'),
        '<span style="font-size:11px;color:var(--text-secondary)">' + (r.note || '') + '</span>'];
    });
    inner += table(ch, rows);
    inner += chartCard('💰 资本开支 ramp (FY25 → FY26e, $B)', '超级周期加速度：四大云厂 AI capex 同比继续扩张', 'aiCapex', '');
  }
  if (cyc.bottlenecks && cyc.bottlenecks.length) {
    inner += '<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin:12px 0 6px">🔧 供给瓶颈</div><div style="display:flex;gap:8px;flex-wrap:wrap">';
    cyc.bottlenecks.forEach(function (b) {
      var lv = b.level || 1, col = lv >= 3 ? '#e63946' : lv == 2 ? '#e9a23b' : '#2a9d8f';
      inner += '<div style="flex:1;min-width:150px;background:var(--bg-card);border:1px solid var(--border-card);border-radius:10px;padding:8px 10px">'
        + '<div style="font-weight:600;font-size:12px">' + b.name + ' <span style="font-size:10px;color:' + col + ';border:1px solid ' + col + ';border-radius:8px;padding:0 5px;margin-left:4px">' + (b.status || '') + '</span></div>'
        + '<div style="font-size:11px;color:var(--text-secondary);margin-top:3px">' + (b.detail || '') + '</div></div>';
    });
    inner += '</div>';
  }
  if (cyc.transition) inner += '<div style="font-size:12px;margin-top:12px"><b>🔀 ' + cyc.transition + '</b></div>';
  if (cyc.narrative) inner += '<div style="font-size:12px;color:var(--text-secondary);line-height:1.7;margin-top:6px;padding:10px 12px;background:var(--bg-card);border:1px solid var(--border-card);border-radius:8px">' + cyc.narrative + '</div>';
  if (cyc.privateModels && cyc.privateModels.length) {
    inner += '<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin:12px 0 6px">🛰️ 私有模型雷达（不可投，但决定下游估值）</div><div style="display:flex;gap:6px;flex-wrap:wrap">';
    cyc.privateModels.forEach(function (p) {
      inner += '<div style="font-size:11px;padding:3px 9px;border:1px solid var(--border-card);border-radius:12px;color:var(--text-secondary)" title="' + p.note + '"><b>' + p.name + '</b></div>';
    });
    inner += '</div>';
  }
  if (cyc.riskFlags && cyc.riskFlags.length) {
    inner += '<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin:12px 0 6px">⚠️ 风险旗标</div><div class="watch-list">';
    cyc.riskFlags.forEach(function (r) {
      inner += '<div class="watch-item"><div class="watch-trigger"><b>' + r.name + '</b></div><div class="watch-implication" style="font-size:11px;color:var(--text-secondary)">' + (r.detail || '') + '</div></div>';
    });
    inner += '</div>';
  }
  return sectionCard('🌀 AI 资本开支周期 · 超级周期位置', (cyc.asOf || ''), inner);
}
function _aiFmt(x, suffix) {
  if (x === null || x === undefined) return '—';
  if (suffix === '%') return Number(x).toFixed(x >= 10 || x <= -10 ? 0 : 1) + '%';
  if (suffix === 'x') return Number(x).toFixed(x >= 10 ? 1 : 1) + 'x';
  if (suffix === 'B') return '$' + Number(x).toFixed(1) + 'B';
  return String(x);
}
function _aiValColor(v, kind) {
  // 估值: 越低越绿(便宜); 质量: 越高越绿; 增速: 越高越绿
  if (kind === 'pe' || kind === 'fwdPe' || kind === 'peg') {
    if (v === null || v === undefined) return 'var(--text-secondary)';
    if (v <= 0) return '#9ca3af';
    if (v <= 15) return '#2a9d8f';
    if (v <= 30) return '#4361ee';
    if (v <= 50) return '#f59e0b';
    return '#e63946';
  }
  if (v === null || v === undefined) return 'var(--text-secondary)';
  if (v >= 70) return '#2a9d8f';
  if (v >= 45) return '#4361ee';
  if (v >= 25) return '#f59e0b';
  return '#e63946';
}
function _aiHighlightSummary(text) {
  if (!text) return '';
  // 高亮金额 $X.XB/M、百分比 +/-X%、季度/财年、指引
  var t = text.replace(/(\$[\d\.]+[BMK]?)/g, '<b style="color:#4361ee">$1</b>');
  t = t.replace(/([\+\-]?\d+(?:\.\d+)?%)/g, '<b style="color:#2a9d8f">$1</b>');
  t = t.replace(/\b(Q[1-4]|H1|H2|FY\d{2,4})\b/g, '<b style="color:#7f77dd">$1</b>');
  // 风险关键词标红
  var risks = ['风险', '承压', '客户集中', '债务', '下修', '不及预期', '估值过高', '放缓', '疲软', '亏损', '高 beta'];
  risks.forEach(function (w) {
    var re = new RegExp(w, 'g');
    t = t.replace(re, '<span style="color:#e63946;font-weight:600">' + w + '</span>');
  });
  return t;
}
function _aiResearchCard(c) {
  var r = c.research || {};
  var src = (r.sources && r.sources.length) ? '<a href="' + r.sources[0].url + '" target="_blank" style="color:var(--accent);font-size:11px;margin-left:6px">来源↗</a>' : '';
  var eps = c.epsRevision, epsStr = '';
  if (eps != null) {
    epsStr = '<span style="display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;background:' + (eps >= 0 ? '#e6f6ee' : '#fde2e2') + ';color:' + (eps >= 0 ? '#1d9e75' : '#c0392b') + ';margin-left:6px">EPS修正 ' + (eps >= 0 ? '+' : '') + eps + '%</span>';
  }
  var rt = c.ratingTrend, rtStr = '';
  if (rt != null) rtStr = '<span style="display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;background:#f3f4f6;color:#6b7280;margin-left:4px">评级' + (rt > 0.1 ? '↑' : rt < -0.1 ? '↓' : '→') + '</span>';
  var disp = (c.ratingDispersion != null) ? '<span style="font-size:11px;color:#9ca3af;margin-left:4px">分歧 ' + c.ratingDispersion + '</span>' : '';
  var consensusBadge = r.consensus ? '<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;background:#e8ecff;color:#4361ee;margin-right:6px">' + r.consensus + '</span>' : '';

  // 拆分 summary / notes：数字与风险高亮
  var summaryHtml = _aiHighlightSummary(r.summary || '');
  var notesHtml = _aiHighlightSummary(c.notes || '');

  // AI 卡位指标
  var aiKpi = '';
  if (c.aiRevPct != null) {
    aiKpi += '<div style="flex:1;min-width:80px;text-align:center;padding:8px;border:1px solid var(--border-card);border-radius:8px;background:#f8f9fc">'
      + '<div style="font-size:10px;color:var(--text-tertiary)">AI收入占比</div>'
      + '<div style="font-size:15px;font-weight:700;color:#4361ee">' + c.aiRevPct + '%</div></div>';
  }
  if (c.aiRevGrowth != null) {
    aiKpi += '<div style="flex:1;min-width:80px;text-align:center;padding:8px;border:1px solid var(--border-card);border-radius:8px;background:#f8f9fc">'
      + '<div style="font-size:10px;color:var(--text-tertiary)">AI增速</div>'
      + '<div style="font-size:15px;font-weight:700;color:#2a9d8f">+' + c.aiRevGrowth + '%</div></div>';
  }
  if (c.pricingPower != null) {
    aiKpi += '<div style="flex:1;min-width:80px;text-align:center;padding:8px;border:1px solid var(--border-card);border-radius:8px;background:#f8f9fc">'
      + '<div style="font-size:10px;color:var(--text-tertiary)">定价权</div>'
      + '<div style="font-size:15px;font-weight:700;color:#7f77dd">' + c.pricingPower + '</div></div>';
  }

  return '<div style="background:#fff;border:1px solid var(--border-card);border-radius:12px;padding:14px 16px;margin-bottom:10px">'
    + '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:10px">'
    + '<span class="ticker" style="font-size:14px">' + c.ticker + '</span>' + _aiMkt(c.market)
    + '<span style="font-size:12px;color:var(--text-secondary);margin-left:4px">' + c.name + '</span>'
    + '<div style="margin-left:auto;display:flex;align-items:center;gap:4px">'
    + consensusBadge + '<span style="font-size:12px;color:var(--text-secondary)">' + (r.ratingScore || '—') + '/5 · ' + (r.reports || 0) + '篇</span>' + epsStr + rtStr + disp + src + '</div></div>'
    + (aiKpi ? '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">' + aiKpi + '</div>' : '')
    + (summaryHtml ? '<div style="font-size:13px;line-height:1.8;color:var(--text-primary);margin-bottom:8px">' + summaryHtml + '</div>' : '')
    + (notesHtml ? '<div style="font-size:12px;line-height:1.7;color:var(--text-secondary);padding:8px 10px;background:var(--bg-card);border-radius:8px;border:1px solid var(--border-card)">' + notesHtml + '</div>' : '')
    + (c.stale ? '<div style="font-size:11px;color:#e9a23b;margin-top:8px">⚠ 财务数据较旧，更新于 ' + (c.curatedDate || '?') + '</div>' : '')
    + '</div>';
}
function _renderAiFinancials(L) {
  var rows = (L.companies || []).map(function (c) {
    return [
      '<div><span class="ticker">' + c.ticker + '</span>' + _aiMkt(c.market) + '<br><span style="font-size:11px;color:var(--text-secondary)">' + c.name + '</span></div>',
      '<div style="font-size:13px;font-weight:700;color:' + _aiValColor(c.marketCap, 'pe') + '">' + _aiFmt(c.marketCap, 'B') + '</div>',
      '<div style="font-size:13px;color:' + _aiValColor(c.pe, 'pe') + '">' + _aiFmt(c.pe, 'x') + '</div>',
      '<div style="font-size:13px;color:' + _aiValColor(c.fwdPe, 'pe') + '">' + _aiFmt(c.fwdPe, 'x') + '</div>',
      '<div style="font-size:13px;color:' + _aiValColor(c.peg, 'pe') + '">' + _aiFmt(c.peg, 'x') + '</div>',
      '<div style="font-size:13px;color:' + _aiValColor(c.revGrowth, '') + '">' + _aiFmt(c.revGrowth, '%') + '</div>',
      '<div style="font-size:13px;color:' + _aiValColor(c.grossMargin, '') + '">' + _aiFmt(c.grossMargin, '%') + '</div>',
      '<div style="font-size:13px;color:' + _aiValColor(c.fcfMargin, '') + '">' + _aiFmt(c.fcfMargin, '%') + '</div>',
      '<div style="font-size:13px;color:' + _aiValColor(c.roe, '') + '">' + _aiFmt(c.roe, '%') + '</div>'
    ];
  });
  return table(
    ['公司', '市值', 'PE', 'Fwd PE', 'PEG', '营收增速', '毛利率', 'FCF率', 'ROE'],
    rows
  ) + '<div style="font-size:11px;color:var(--text-tertiary);margin-top:6px">市值统一为 USD $B；带 <span style="color:#e9a23b">⚠</span> 或 est=true 的字段为策展估计值，需随财报刷新。</div>';
}
function renderAiLayer(L) {
  var s = L.stats || {};
  var inner = '';
  if (L.desc) inner += '<div style="font-size:12px;color:var(--text-secondary);line-height:1.6;margin-bottom:10px">' + L.desc + '</div>';
  if (L.techRoutes && L.techRoutes.length) {
    inner += '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">';
    L.techRoutes.forEach(function (r) {
      inner += '<span style="font-size:11px;padding:3px 9px;border:1px solid var(--border-card);border-radius:12px;color:var(--text-secondary)">' + r + '</span>';
    });
    inner += '</div>';
  }
  var headers = ['公司', '技术路线 / 产品方向', '周', '月', '半年', 'AI价值分', '标签'];
  var rows = (L.companies || []).map(function (c) {
    var ch = c.ch || {}, sc = c.scores || {}, col = _aiColor(sc.aiValue);
    var valCell = '<div style="display:flex;align-items:center;gap:6px"><span style="font-weight:700;min-width:24px">' + sc.aiValue + '</span>' + _aiBar(sc.aiValue, col) + '</div>'
      + '<div style="font-size:10px;color:var(--text-tertiary);margin-top:2px">层内分位 P' + (c.layerPct != null ? c.layerPct : 50) + '</div>';
    return [
      '<div><span class="ticker">' + c.ticker + '</span>' + _aiMkt(c.market) + (c.stale ? ' <span style="font-size:10px;color:#e9a23b">⚠较旧</span>' : '') + '<br><span style="font-size:11px;color:var(--text-secondary)">' + c.name + '</span>'
        + (c.price != null ? '<br><span style="font-size:11px;color:var(--text-tertiary)">' + _aiCcySym(c.ccy) + Number(c.price).toFixed(2) + '</span>' : '') + '</div>',
      '<div style="font-size:12px"><div>' + (c.techRoute || '—') + '</div><div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">' + (c.productDir || '') + '</div></div>',
      _aiPct(ch.w), _aiPct(ch.m), _aiPct(ch.h6), valCell, _aiTags(c.tags)
    ];
  });
  inner += table(headers, rows);
  // 财务基本面模块
  inner += sectionH('💵 财务基本面', '估值 / 盈利质量 / 成长（市值统一 USD $B；颜色越深/红=越高估或越弱）');
  inner += _renderAiFinancials(L);
  // 中美韩对比面板: 该层各市场领头羊 + 跨市场最佳 (折叠)
  var cmp = L.comparison || {}, leaders = cmp.leaders || {}, mkKeys = Object.keys(leaders);
  if (mkKeys.length > 1) {
    var _cmpInner = '<div style="display:flex;gap:8px;flex-wrap:wrap">';
    mkKeys.forEach(function (mk) {
      var ld = leaders[mk], isBest = (cmp.crossMarketBest && ld.ticker === cmp.crossMarketBest);
      _cmpInner += '<div style="flex:1;min-width:140px;background:var(--bg-card);border:1px solid ' + (isBest ? '#2a9d8f' : 'var(--border-card)') + ';border-radius:10px;padding:8px 10px">'
        + '<div style="font-size:11px;color:var(--text-tertiary)">' + _aiMkt(mk) + ' 领头羊' + (isBest ? ' · <b style="color:#2a9d8f">跨市场最佳</b>' : '') + '</div>'
        + '<div style="font-weight:700;margin-top:3px">' + ld.ticker + ' <span style="font-size:11px;font-weight:400;color:var(--text-secondary)">' + ld.name + '</span></div>'
        + '<div style="font-size:13px;margin-top:2px">AI价值分 <b>' + ld.aiValue + '</b> · ' + ld.count + ' 家</div></div>';
    });
    _cmpInner += '</div>';
    inner += _aiCollapse('🌍 中美韩对比 · 各市场领头羊', _cmpInner, true);
  }
  var rs = (L.companies || []).filter(function (c) { return c.research; });
  if (rs.length) {
    var _rsInner = rs.map(_aiResearchCard).join('');
    inner += _aiCollapse('📑 研报共识与备注', _rsInner, false);
  }
  return sectionCard(L.name + ' · ' + (L.en || ''), (s.count || 0) + ' 家公司 · 平均AI价值分 ' + (s.avgAiValue || 0) + (s.topPick ? ' · 优选 ' + s.topPick : ''), inner);
}
function renderAiChain(container) {
  var d = DATA.aiChain || { layers: [], bestValuePicks: [], summary: {}, meta: {} };
  var sm = d.summary || {};
  var html = '';
  html += sectionH('AI 产业链 · 黄仁勋五层蛋糕 + 网络连接层', '应用 → 模型 → 基础设施 → 网络连接 → 芯片 → 能源；股价动量自动(Yahoo)，基本面/研报/周期叙事为策展种子值');
  html += '<div class="metric-grid">';
  [['覆盖公司', (sm.companies || 0) + ' 家'], ['产业链层', (sm.layers || 0) + ' 层'], ['价值股候选', (sm.valuePicks || 0) + ' 只'],
   ['平均AI价值分', (sm.avgAiValue || 0) + ' /100'], ['平均动量', (sm.avgMomentum || 0) + ' /100']].forEach(function (kv) {
    html += '<div style="background:var(--bg-card);border:1px solid var(--border-card);border-radius:10px;padding:12px 14px">'
      + '<div style="font-size:11px;color:var(--text-tertiary)">' + kv[0] + '</div>'
      + '<div style="font-size:20px;font-weight:700;margin-top:4px">' + kv[1] + '</div></div>';
  });
  html += '</div>';
  // 市场分布汇总
  var ms = d.marketSummary || {}, msKeys = Object.keys(ms);
  if (msKeys.length > 1) {
    html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px">';
    msKeys.forEach(function (mk) {
      var m = ms[mk];
      html += '<div style="flex:1;min-width:120px;background:var(--bg-card);border:1px solid var(--border-card);border-radius:10px;padding:10px 12px">'
        + '<div style="font-size:11px;color:var(--text-tertiary)">' + _aiMkt(mk) + '</div>'
        + '<div style="font-size:18px;font-weight:700;margin-top:2px">' + m.count + ' 家</div>'
        + '<div style="font-size:11px;color:var(--text-secondary);margin-top:2px">平均AI价值分 ' + m.avgAiValue + ' · 最佳 ' + m.best + '</div></div>';
    });
    html += '</div>';
  }
  // 子页面导航：总览 + 各分层 + 国产替代
  var _icons = { '应用层': '📱', '模型层': '🧠', '基础设施层': '🏗️', '网络连接层': '🔌', '芯片层': '💡', '能源层': '⚡' };
  html += '<div class="ai-subnav" id="aiSubnav">'
    + '<button class="ai-subnav-btn active" data-ai-tab="overview">📊 总览</button>';
  (d.layers || []).forEach(function (L, i) {
    html += '<button class="ai-subnav-btn" data-ai-tab="' + i + '">' + (_icons[L.name] || '▸') + ' ' + L.name + '</button>';
  });
  html += '<button class="ai-subnav-btn" data-ai-tab="china">🇨🇳 国产替代</button>';
  html += '</div>';
  // 子页面容器
  html += '<div id="aiTabBody"></div>';
  container.innerHTML = html;
  _renderAiTab('overview', d);
}

// 矛盾信号面板：主导矛盾 / 领先确认 / 交叉验证
function renderMacroSignal(c) {
  const d = DATA.macroSignal;
  if (!d) { c.innerHTML = '<div class="loading">矛盾信号数据加载中...</div>'; return; }
  const STATUS = {
    on:      { bg: '#fef3e2', fg: '#b45309', label: '触发' },
    off:     { bg: '#f3f4f6', fg: '#6b7280', label: '未触发' },
    curated: { bg: '#e8ecff', fg: '#4361ee', label: '策展标注' },
    unknown: { bg: '#f3f4f6', fg: '#6b7280', label: '数据不足' }
  };
  const astatus = {};
  (d.anchors || []).forEach(function (a) { astatus[a.id] = a.status; });
  const pill = function (st) {
    const s = STATUS[st] || STATUS.unknown;
    return '<span style="display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;background:' + s.bg + ';color:' + s.fg + ';">' + s.label + '</span>';
  };
  const borderColor = function (st) {
    if (st === 'on') return '#f59e0b';
    if (st === 'curated') return '#4361ee';
    return '#9ca3af';
  };

  let h = '';

  // 判定依据 (数据驱动复合指标)
  const meta = d.dominantMeta || {};
  const comps = meta.composites || {};
  const CCOL = {
    on: {bg:'#fef3e2',fg:'#b45309'}, off:{bg:'#f3f4f6',fg:'#6b7280'},
    high:{bg:'#fde2e2',fg:'#c0392b'}, mod:{bg:'#fef3e2',fg:'#b45309'}, low:{bg:'#e6f6ee',fg:'#1d9e75'},
    tight:{bg:'#fde2e2',fg:'#c0392b'}, neutral:{bg:'#f3f4f6',fg:'#6b7280'}, easy:{bg:'#e6f6ee',fg:'#1d9e75'},
    weak:{bg:'#fde2e2',fg:'#c0392b'}, strong:{bg:'#e6f6ee',fg:'#1d9e75'},
    narrow:{bg:'#fde2e2',fg:'#c0392b'}, broad:{bg:'#e6f6ee',fg:'#1d9e75'}
  };
  const _chip = function (label, val, col) {
    const c = CCOL[col] || CCOL.neutral;
    return '<span style="display:inline-block;padding:3px 10px;border-radius:18px;font-size:11px;font-weight:600;background:' + c.bg + ';color:' + c.fg + ';margin:3px 5px 3px 0;">' + label + '：' + val + '</span>';
  };
  let compChips = '';
  if (comps.disagreement !== undefined) compChips += _chip('债股背离', comps.disagreement ? '触发' : '未触发', comps.disagreement ? 'on' : 'off');
  if (comps.inflation) compChips += _chip('通胀压力', comps.inflation === 'high' ? '高' : (comps.inflation === 'low' ? '低' : '中'), comps.inflation);
  if (comps.growth) compChips += _chip('增长', comps.growth === 'weak' ? '弱' : (comps.growth === 'strong' ? '强' : '中'), comps.growth);
  if (comps.liquidity) compChips += _chip('流动性', comps.liquidity === 'tight' ? '紧' : (comps.liquidity === 'easy' ? '松' : '中'), comps.liquidity);
  if (comps.breadth) compChips += _chip('涨势广度', comps.breadth === 'narrow' ? '窄' : (comps.breadth === 'broad' ? '广' : '中'), comps.breadth);
  const srcBadge = meta.source === 'override'
    ? '<span style="display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;background:#e8ecff;color:#4361ee;">✍️ 策展覆盖</span>'
    : '<span style="display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;background:#e6f6ee;color:#1d9e75;">🔄 数据自动判定</span>';

  // 主导矛盾
  const dom = d.dominant || {};
  h += '<div style="margin:6px 0 18px;padding:18px 20px;border-radius:12px;background:#15131f;color:#fff;border:1px solid #3a2f6b;">';
  h += '<div style="font-size:12px;color:#b9a8ff;letter-spacing:.5px;margin-bottom:8px;">主导矛盾 · ' + (dom.keyTension || '') + '</div>';
  h += '<div style="font-size:16px;font-weight:600;margin-bottom:8px;">' + (dom.title || '') + '</div>';
  h += '<div style="font-size:13px;line-height:1.8;color:#cfc7e6;">' + (dom.body || '') + '</div>';
  h += '</div>';
  h += '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:18px;">' + srcBadge + compChips
     + (meta.archetypeId ? ' <span style="font-size:11px;color:#9ca3af;">原型: ' + meta.archetypeId + '</span>' : '') + '</div>';

  // 当前情景判定
  const act = (d.scenarios || []).find(function (s) { return s.id === d.activeScenario; });
  h += sectionH('当前情景判定', act ? ('最匹配：' + act.label + ' · ' + act.desc) : '数据不足，无法自动判定');
  const scHtml = (d.scenarios || []).map(function (s) {
    const active = s.id === d.activeScenario;
    const trigHtml = (s.triggers || []).map(function (t) {
      const st = (s.triggerStatus && s.triggerStatus[t]) || 'unknown';
      return '<span style="display:inline-flex;align-items:center;gap:5px;margin:3px 6px 3px 0;font-size:11px;color:#374151;">' + pill(st) + '<span>' + t + '</span></span>';
    }).join('');
    return '<div style="background:' + (active ? '#fff' : '#fafafa') + ';border:1px solid ' + (active ? '#4361ee' : '#e5e7eb') + ';border-radius:10px;padding:14px;' + (active ? 'box-shadow:0 2px 10px rgba(67,97,238,.15)' : '') + '">'
      + '<div style="font-size:14px;font-weight:600;color:' + (active ? '#4361ee' : '#1a1d29') + ';margin-bottom:4px;">' + s.label + (s.tail ? ' ⚠️' : '') + '</div>'
      + '<div style="font-size:12px;color:#6b7280;margin-bottom:8px;line-height:1.6;">' + (s.desc || '') + '</div>'
      + '<div>' + trigHtml + '</div></div>';
  }).join('');
  h += '<div class="metric-grid" style="margin-bottom:24px;">' + scHtml + '</div>';

  // 信号分级：领先确认 + 交叉验证
  const lead = (d.anchors || []).filter(function (a) { return a.tier === 'leading'; });
  const cross = (d.anchors || []).filter(function (a) { return a.tier === 'cross'; });
  const anchorCard = function (a) {
    return '<div style="background:#fff;border:1px solid #e5e7eb;border-left:4px solid ' + borderColor(a.status) + ';border-radius:10px;padding:12px 14px;margin-bottom:10px;">'
      + '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">'
      + '<div style="font-size:13px;font-weight:600;color:#1a1d29;">' + a.label + '</div>' + pill(a.status) + '</div>'
      + '<div style="font-size:11px;color:#6b7280;margin-top:4px;line-height:1.5;">' + (a.detail || '') + '</div>'
      + '<div style="font-size:11px;color:#9ca3af;margin-top:3px;">' + (a.note || '') + '</div></div>';
  };
  h += sectionH('信号分级', '主导矛盾之下的硬指标分层');
  h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:24px;">';
  h += '<div><div style="font-size:12px;font-weight:600;color:#7f77dd;margin-bottom:8px;">① 领先确认 · 触发情景转换</div>' + lead.map(anchorCard).join('') + '</div>';
  h += '<div><div style="font-size:12px;font-weight:600;color:#1d9e75;margin-bottom:8px;">② 交叉验证 · 验证涨势广度与背离</div>' + cross.map(anchorCard).join('') + '</div>';
  h += '</div>';

  // 共识
  h += sectionH('市场共识', '已被定价 / 普遍认同');
  h += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 18px;margin-bottom:24px;">'
    + (d.consensus || []).map(function (t) {
        return '<div style="font-size:13px;color:#374151;line-height:1.8;padding-left:14px;position:relative;"><span style="position:absolute;left:0;color:#4361ee;">•</span>' + t + '</div>';
      }).join('')
    + '</div>';

  // 分歧
  h += sectionH('分歧点', '真正决定方向、尚未定论');
  h += (d.divergence || []).map(function (x) {
    let stp = '';
    if (x.anchor) { stp = ' <span style="margin-left:6px;">' + pill(astatus[x.anchor] || 'unknown') + '</span>'; }
    return '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;margin-bottom:10px;">'
      + '<div style="font-size:13px;font-weight:600;color:#1a1d29;margin-bottom:4px;">' + x.label + stp + '</div>'
      + '<div style="font-size:12px;color:#6b7280;line-height:1.6;">' + (x.text || '') + '</div></div>';
  }).join('');

  // footer
  const _srcTxt = meta.source === 'override' ? '策展覆盖' : (meta.archetypeId || '策展默认');
  h += '<div style="font-size:11px;color:#9ca3af;line-height:1.6;margin-top:8px;">主导矛盾来源 ' + _srcTxt + ' · 策展日期 ' + (d.curatedDate || '') + ' · 数据截至 ' + (d.asOf || '') + '<br>' + (d.method || '') + '</div>';

  c.innerHTML = h;
}

// 渲染指定子页面 (总览 / 各分层 index / china)
function _renderAiTab(tab, d) {
  var body = document.getElementById('aiTabBody');
  if (!body) return;
  // 销毁可能残留的 AI 图表，避免 canvas 复用冲突
  ['aiScatter', 'aiQuad', 'aiCapex'].forEach(function (k) { if (charts[k]) { charts[k].destroy(); delete charts[k]; } });
  var html;
  if (tab === 'overview') html = _renderAiOverview(d);
  else if (tab === 'china') html = _renderAiChina(d);
  else {
    var idx = parseInt(tab, 10);
    var L = (d.layers || [])[idx];
    html = L ? renderAiLayer(L) : '<div class="loading">未找到该层内容。</div>';
  }
  body.innerHTML = html;
  _initAiCharts(tab, d);
  // 更新按钮高亮
  var btns = document.querySelectorAll('#aiSubnav .ai-subnav-btn');
  btns.forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-ai-tab') === tab); });
}

function _aiFlowColor(score) {
  if (score >= 70) return '#e63946';
  if (score >= 55) return '#f59e0b';
  if (score >= 40) return '#4361ee';
  return '#2a9d8f';
}
function _renderAiFlow(d) {
  var fd = d.flowData || {};
  var layers = fd.layers || [];
  if (!layers.length) return '<div class="loading">资金流向数据加载中...</div>';
  var maxScore = Math.max.apply(null, layers.map(function (x) { return x.flowScore; })) || 1;
  var totalScore = layers.reduce(function (a, b) { return a + b.flowScore; }, 0);
  var maxLayer = fd.maxLayer || layers[0].name;

  // SVG 桑基风格流向图：左侧资金池(竖条) → 右侧各层节点, band 宽度 ∝ 资金份额
  var h = 320, w = 720, leftW = 72, leftX = 86, rightX = 560, nodeW = 132, nodeH = 28;
  var topMargin = 22, bottomMargin = 18;
  var usableH = h - topMargin - bottomMargin;
  var gap = usableH / Math.max(layers.length, 1);
  var poolTop = topMargin, poolBottom = h - bottomMargin;

  var svg = '<svg viewBox="0 0 ' + w + ' ' + h + '" style="width:100%;height:280px">';
  // 为每层定义渐变
  layers.forEach(function (ly, i) {
    var col = _aiFlowColor(ly.flowScore);
    svg += '<defs>'
      + '<linearGradient id="flowGrad' + i + '" x1="0%" y1="0%" x2="100%" y2="0%">'
      + '<stop offset="0%" stop-color="' + col + '" stop-opacity="0.45"/>'
      + '<stop offset="55%" stop-color="' + col + '" stop-opacity="0.8"/>'
      + '<stop offset="100%" stop-color="' + col + '" stop-opacity="1"/>'
      + '</linearGradient>'
      + '</defs>';
  });

  // 左侧资金池竖条
  svg += '<rect x="' + (leftX - leftW / 2) + '" y="' + poolTop + '" width="' + leftW + '" height="' + (poolBottom - poolTop) + '" rx="10" fill="#f8fafc" stroke="#9ca3af" stroke-width="1"/>'
    + '<text x="' + leftX + '" y="' + (h / 2 - 6) + '" text-anchor="middle" font-size="12" font-weight="600" fill="#374151">市场资金池</text>'
    + '<text x="' + leftX + '" y="' + (h / 2 + 12) + '" text-anchor="middle" font-size="10" fill="#6b7280">按份额估算</text>';

  // 计算各层 y 位置与 band 宽度(基于 flowScore / totalScore)
  var positions = layers.map(function (ly, i) {
    var y = topMargin + i * gap + (gap - nodeH) / 2;
    var share = totalScore ? ly.flowScore / totalScore : 0;
    var band = Math.max(5, Math.min(share * (poolBottom - poolTop) * 0.9, gap * 0.85));
    return { y: y, cy: y + nodeH / 2, band: band, share: share };
  });

  // 绘制 band: 从资金池右边缘对应垂直段 → 各层节点左侧(缩回 8px 给箭头留位)
  // 左端按层在资金池内均匀分布, 避免所有带汇聚到一个点
  positions.forEach(function (pos, i) {
    var ly = layers[i];
    var col = _aiFlowColor(ly.flowScore);
    var leftY0 = poolTop + (i + 0.08) * ((poolBottom - poolTop) / layers.length);
    var leftY1 = leftY0 + pos.band;
    var arrowW = 8;
    var rightEdge = rightX - nodeW / 2 - arrowW;
    var rightY0 = pos.cy - pos.band / 2;
    var rightY1 = pos.cy + pos.band / 2;
    var midX = (leftX + leftW / 2 + rightEdge) / 2;
    var dPath = 'M' + (leftX + leftW / 2) + ',' + leftY0
      + ' C' + midX + ',' + leftY0 + ' ' + (rightEdge - 20) + ',' + rightY0 + ' ' + rightEdge + ',' + rightY0
      + ' L' + rightEdge + ',' + rightY1
      + ' C' + (rightEdge - 20) + ',' + rightY1 + ' ' + midX + ',' + leftY1 + ' ' + (leftX + leftW / 2) + ',' + leftY1
      + ' Z';
    svg += '<path d="' + dPath + '" fill="url(#flowGrad' + i + ')" stroke="none"/>';
    // 独立绘制指向节点的实心三角箭头, 避免 marker 在闭合路径上的错位/反向问题
    svg += '<path d="M' + rightEdge + ',' + (pos.cy - 6) + ' L' + rightEdge + ',' + (pos.cy + 6) + ' L' + (rightEdge + arrowW + 2) + ',' + pos.cy + ' Z" fill="' + col + '" stroke="' + col + '" stroke-width="1"/>';
  });

  // 右侧层节点 + 标签
  positions.forEach(function (pos, i) {
    var ly = layers[i];
    var col = _aiFlowColor(ly.flowScore);
    svg += '<rect x="' + (rightX - nodeW / 2) + '" y="' + pos.y + '" width="' + nodeW + '" height="' + nodeH + '" rx="8" fill="#fff" stroke="' + col + '" stroke-width="2"/>'
      + '<text x="' + (rightX - 8) + '" y="' + (pos.y + 12) + '" text-anchor="end" font-size="11" font-weight="600" fill="#1a1d29">' + ly.name + '</text>'
      + '<text x="' + (rightX + 10) + '" y="' + (pos.y + 12) + '" text-anchor="start" font-size="12" font-weight="700" fill="' + col + '">' + ly.flowScore + '</text>'
      + '<text x="' + (rightX + nodeW / 2 + 10) + '" y="' + (pos.y + 12) + '" font-size="10" fill="#6b7280">占比 ' + Math.round(pos.share * 100) + '% · 动量 ' + ly.avgMomentum + ' · 领涨 ' + ly.breadthPct + '%</text>';
  });
  svg += '</svg>';

  var rankHtml = layers.map(function (ly, idx) {
    var col = _aiFlowColor(ly.flowScore);
    var share = totalScore ? ly.flowScore / totalScore : 0;
    return '<div style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-bottom:1px solid var(--border-card);font-size:12px">'
      + '<div style="font-weight:700;color:var(--text-tertiary);width:20px">#' + (idx + 1) + '</div>'
      + '<div style="flex:1;font-weight:600">' + ly.name + '</div>'
      + '<div style="width:110px">' + _aiBar(ly.flowScore, col) + '</div>'
      + '<div style="font-weight:700;color:' + col + ';width:36px;text-align:right">' + ly.flowScore + '</div>'
      + '<div style="font-size:11px;color:var(--text-secondary);width:90px;text-align:right">占比 ' + Math.round(share * 100) + '%</div></div>';
  }).join('');

  var inner = '<div style="display:grid;grid-template-columns:minmax(340px,1.4fr) minmax(260px,1fr);gap:18px;align-items:start">'
    + '<div>' + svg + '<div style="font-size:11px;color:var(--text-tertiary);margin-top:6px">' + (fd.method || '') + '</div></div>'
    + '<div style="background:var(--bg-card);border:1px solid var(--border-card);border-radius:10px;overflow:hidden">'
    + '<div style="padding:10px 12px;font-size:12px;font-weight:600;background:#fff;border-bottom:1px solid var(--border-card)">资金流向强度排行</div>' + rankHtml + '</div></div>';

  return sectionCard('💧 AI 产业链资金流向 · 当前资金聚焦：' + maxLayer, '箭头带宽 ≈ 资金份额；分数由 5 维度(动量/领涨广度/资金加速度/市值加权动量/估值热度)经 z-score + softmax 标准化得到，加总≈100', inner);
}

// 总览页：周期 + 各层热力 + 可视化 + 价值股
function _renderAiOverview(d) {
  var html = '';
  if (d.cycle) html += renderAiCycle(d.cycle);
  html += _renderAiFlow(d);
  html += sectionH('各层价值热力', '各层平均 AI 价值分：越高=该层整体性价比/被低估程度越高');
  html += '<div style="display:flex;flex-direction:column;gap:8px;margin-bottom:18px">';
  (d.layers || []).forEach(function (L) {
    var s = L.stats || {}, col = _aiColor(s.avgAiValue || 0);
    html += '<div style="background:var(--bg-card);border:1px solid var(--border-card);border-radius:10px;padding:10px 14px">'
      + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
      + '<span style="font-weight:600">' + L.name + ' <span style="font-size:11px;color:var(--text-tertiary)">' + (L.en || '') + '</span></span>'
      + '<span style="font-size:11px;color:var(--text-tertiary)">' + (s.count || 0) + ' 家 · 优选 ' + (s.topPick || '—') + '</span></div>'
      + '<div style="display:flex;align-items:center;gap:10px">' + _aiBar(s.avgAiValue || 0, col)
      + '<span style="font-weight:700;font-size:13px">' + (s.avgAiValue || 0) + '</span></div></div>';
  });
  html += '</div>';
  html += sectionH('📊 可视化分析', '性价比地图：横轴越右=越便宜、纵轴越高=AI价值越高、气泡越大=市值越大；象限图：左上=待挖掘, 右上=已定价, 右下=泡沫/拥挤, 左下=回避（AI价值分为跨层综合分, 层间不完全可比）');
  html += '<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px">'
    + '<div style="flex:1;min-width:320px">' + chartCard('🌐 中美韩性价比地图（气泡=市值）', '估值便宜度 × AI 价值分 × 市值', 'aiScatter', 'tall') + '</div>'
    + '<div style="flex:1;min-width:320px">' + chartCard('🎯 价值-动量象限', '高价值 + 低动量 = 待挖掘标的', 'aiQuad', 'tall') + '</div>'
    + '</div>';
  html += sectionCard('🔎 尚未被充分定价的 AI 价值股', '筛选：基本面强 + 估值便宜 + 尚未被拉涨', renderAiValuePicks(d.bestValuePicks || []));
  if (d.meta && d.meta.disclaimer) html += '<div style="font-size:11px;color:var(--text-tertiary);line-height:1.6;margin-top:14px;padding:10px 12px;border:1px dashed var(--border);border-radius:8px">' + d.meta.disclaimer + '</div>';
  return html;
}

// 国产替代 Thesis 专题页
function _renderAiChina(d) {
  var _sub = [];
  (d.layers || []).forEach(function (L) { (L.companies || []).forEach(function (c) { if (c.thesis === 'china-substitution') _sub.push(c); }); });
  if (!_sub.length) return '<div class="loading">暂无国产替代标的。</div>';
  var inner = '<div style="font-size:12px;color:var(--text-secondary);line-height:1.7;margin-bottom:10px">这些标的核心驱动是「美对华先进芯片/设备出口管制 → 国产算力替代」政策 thesis，而非自由市场竞争。其溢价来自信创与自主可控预期，与英伟达等美股标的不可直接类比；若管制放松或国产良率/生态不及预期，逻辑会逆转。</div>';
  inner += '<div class="watch-list">';
  _sub.forEach(function (c) {
    inner += '<div class="watch-item"><div class="watch-trigger"><b>' + c.ticker + '</b> <span style="font-size:11px;color:var(--text-secondary)">' + c.name + '</span> · <span style="font-size:11px;color:#e9a23b">国产替代</span> · AI价值分 ' + (c.scores ? c.scores.aiValue : '—') + ' (层内 P' + (c.layerPct != null ? c.layerPct : 50) + ')</div>'
      + '<div class="watch-implication" style="font-size:11px;color:var(--text-secondary)">' + (c.notes || '') + '</div></div>';
  });
  inner += '</div>';
  return sectionCard('🇨🇳 国产替代 Thesis', '出口管制受益 · 政策赌注 · 与美股非同一驱动', inner);
}

// 仅在总览页初始化 AI 图表 (子页面切换时由 _renderAiTab 负责销毁旧实例)
function _initAiCharts(tab, d) {
  if (typeof Chart === 'undefined') return;
  if (tab !== 'overview') return;
  var _cos = [];
  (d.layers || []).forEach(function (L) { _cos = _cos.concat(L.companies || []); });
  var _mkColor = { US: '#4f8cff', A: '#e63946', KR: '#2a9d8f' };
  var _mkLabel = { US: '🇺🇸 美股', A: '🇨🇳 A股', KR: '🇰🇷 韩股' };
  var _grid = 'rgba(140,140,160,0.12)';

  // ① 中美韩性价比气泡图
  if (document.getElementById('aiScatter')) {
    if (charts.aiScatter) charts.aiScatter.destroy();
    var _dsB = ['US', 'A', 'KR'].filter(function (m) { return _cos.some(function (c) { return c.market === m; }); })
      .map(function (m) {
        return {
          label: _mkLabel[m],
          data: _cos.filter(function (c) { return c.market === m; }).map(function (c) {
            return { x: c.scores.valuation, y: c.scores.aiValue, r: Math.max(4, Math.min(26, Math.sqrt(c.marketCap || 1) * 2.2)), t: c.ticker };
          }),
          backgroundColor: _mkColor[m] + 'b3', borderColor: _mkColor[m], borderWidth: 1
        };
      });
    charts.aiScatter = new Chart(document.getElementById('aiScatter'), {
      type: 'bubble',
      data: { datasets: _dsB },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: 'top', labels: { color: COLORS.text, font: { size: 11 }, boxWidth: 12 } },
          tooltip: { callbacks: { label: function (ctx) { var p = ctx.raw; return p.t + '：便宜度 ' + p.x + ' / AI价值 ' + p.y + ' / 市值约$' + Math.round(p.r * p.r / 4.84) + 'B'; } } }
        },
        scales: {
          x: { min: 0, max: 100, title: { display: true, text: '估值便宜度 →', color: COLORS.text }, ticks: { color: COLORS.text }, grid: { color: _grid } },
          y: { min: 0, max: 100, title: { display: true, text: 'AI 价值分 →', color: COLORS.text }, ticks: { color: COLORS.text }, grid: { color: _grid } }
        }
      }
    });
  }

  // ② 价值-动量象限图 (自定义插件画分隔线+标签)
  if (document.getElementById('aiQuad')) {
    if (charts.aiQuad) charts.aiQuad.destroy();
    var _qd = _cos.map(function (c) { return { x: c.scores.momentum, y: c.scores.aiValue, t: c.ticker, m: c.market }; });
    var _quadPlugin = {
      id: 'quadLines',
      afterDraw: function (chart) {
        var cx = chart.ctx, xa = chart.scales.x, ya = chart.scales.y;
        var x50 = xa.getPixelForValue(50), y50 = ya.getPixelForValue(50);
        cx.save();
        cx.strokeStyle = 'rgba(150,150,170,0.45)'; cx.setLineDash([5, 4]); cx.lineWidth = 1;
        cx.beginPath(); cx.moveTo(x50, ya.top); cx.lineTo(x50, ya.bottom); cx.stroke();
        cx.beginPath(); cx.moveTo(xa.left, y50); cx.lineTo(xa.right, y50); cx.stroke();
        cx.setLineDash([]); cx.fillStyle = 'rgba(150,150,170,0.85)'; cx.font = '11px sans-serif';
        cx.fillText('待挖掘', xa.left + 8, ya.top + 16);
        cx.fillText('已定价', xa.right - 52, ya.top + 16);
        cx.fillText('回避', xa.left + 8, ya.bottom - 10);
        cx.fillText('泡沫/拥挤', xa.right - 66, ya.bottom - 10);
        cx.restore();
      }
    };
    charts.aiQuad = new Chart(document.getElementById('aiQuad'), {
      type: 'scatter',
      data: { datasets: [{ label: '公司', data: _qd,
        backgroundColor: _qd.map(function (p) { return _mkColor[p.m] + 'cc'; }),
        borderColor: _qd.map(function (p) { return _mkColor[p.m]; }), pointRadius: 5, pointHoverRadius: 7 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (ctx) { var p = ctx.raw; return p.t + '：动量 ' + p.x + ' / 价值 ' + p.y; } } }
        },
        scales: {
          x: { min: 0, max: 100, title: { display: true, text: '价格动量 →', color: COLORS.text }, ticks: { color: COLORS.text }, grid: { color: _grid } },
          y: { min: 0, max: 100, title: { display: true, text: 'AI 价值分 →', color: COLORS.text }, ticks: { color: COLORS.text }, grid: { color: _grid } }
        }
      },
      plugins: [_quadPlugin]
    });
  }

  // ③ 资本开支 ramp 柱状图
  if (d.cycle && d.cycle.capex && d.cycle.capex.length && document.getElementById('aiCapex')) {
    if (charts.aiCapex) charts.aiCapex.destroy();
    var _cx = d.cycle.capex;
    charts.aiCapex = new Chart(document.getElementById('aiCapex'), {
      type: 'bar',
      data: {
        labels: _cx.map(function (r) { return r.name; }),
        datasets: [
          { label: 'FY25', data: _cx.map(function (r) { return r.fy25; }), backgroundColor: '#4361ee' },
          { label: 'FY26e', data: _cx.map(function (r) { return r.fy26e; }), backgroundColor: '#e63946' }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: 'top', labels: { color: COLORS.text, font: { size: 11 } } } },
        scales: {
          x: { ticks: { color: COLORS.text }, grid: { display: false } },
          y: { title: { display: true, text: '资本开支 ($B)', color: COLORS.text }, ticks: { color: COLORS.text }, grid: { color: _grid } }
        }
      }
    });
  }
}
