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
    crypto: renderCrypto, recession: renderRecession, risk: renderRisk
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
  // 图1: 10Y-2Y 利差 (独立 Y 轴 -3~+3)
  const _spArr = sd.series['10Y-2Y利差'] || [];
  if (_spArr.length > 0) {
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
            min: -1.5, max: 1.5,
            ticks: Object.assign({}, baseOpts('%').scales.y.ticks, {
              callback: function(v) { return v.toFixed(1) + '%'; }
            })
          })
        })
      })
    });
  }
  // 图2: Breakeven 通胀预期 (独立 Y 轴 ~1.5~3.5%)
  const _beArr = sd.series['通胀预期(Breakeven)'] || [];
  if (_beArr.length > 0) {
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
            min: 1.5, max: 3.5,
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
  const cn = d.chartNotes || {};
  html += '<div class="chart-row two-col">' +
    chartCard('通胀三线图 (真实同比)', cn.inflNote || 'CPI/核心CPI/核心PCE 同比走势', 'inflChart', 'tall') +
    chartCard('GDP 增长: 名义 vs 实际', cn.gdpNote || '季度同比', 'gdpChart', 'tall') +
  '</div>';
  html += '<div class="chart-row one-col">' +
    chartCard('就业市场', cn.empNote || '非农月增 + 失业率', 'empChart', 'tall') +
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
    type: 'bar',
    data: {
      labels: ed.labels,
      datasets: [
        {
          label: '非农就业变动(K)', data: ed.series['非农就业变动(K)'],
          backgroundColor: 'rgba(67,97,238,0.6)', borderRadius: 3, yAxisID: 'y'
        },
        {
          label: '失业率(%)', data: ed.series['失业率(%)'], type: 'line',
          borderColor: '#e63946', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 3, tension: 0.3, yAxisID: 'y1'
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, position: 'top', labels: { color: COLORS.text, font: { size: 11 } } },
        tooltip: { backgroundColor: 'rgba(26,29,41,0.9)', titleColor: '#fff', bodyColor: '#c4c9d4', padding: 10 }
      },
      scales: {
        x: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text, callback: fmtDate } },
        y: { position: 'left', grid: { color: COLORS.grid }, ticks: { color: COLORS.text }, title: { display: true, text: 'K', color: COLORS.text } },
        y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: COLORS.text, callback: function (v) { return v + '%'; } } }
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
