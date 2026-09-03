/* ============================================================
 * app.js — US Macro Observer 应用逻辑 (v3 专业分析师版)
 * ============================================================ */

const charts = {};

// 确保 chartjs-plugin-zoom 已注册到 Chart.js (v2 UMD 仅暴露 window.ChartZoom，需手动注册)
(function () {
  try {
    const g = window.ChartZoom || (window['chartjs-plugin-zoom'] && window['chartjs-plugin-zoom'].Zoom);
    if (g && typeof Chart !== 'undefined' && Chart.register) {
      Chart.register(g);
    }
  } catch (e) { /* 插件缺失时静默降级，图表仍正常渲染(仅无缩放) */ }
})();

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
  tradeRadar: { title: '交易雷达',   subtitle: 'Radar · 预期差扫描 + 全品类映射' },
  positioning: { title: '市场定位',   subtitle: 'Positioning · 谁在动/定价到什么程度' },
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
    ai: renderAiChain, signal: renderMacroSignal, tradeRadar: renderTradeRadar,
    positioning: renderPositioning
  };
  renderers[section](content);
}

/* ================= 通用组件 ================= */

// Regime 横幅
function regimeBanner(r, extraClass) {
  const sigMap = {
    'risk-on':      { cls: 'risk-on', label: '对风险资产利多' },
    'risk-off':     { cls: 'risk-off', label: '对风险资产利空' },
    'stagflation':  { cls: 'risk-off', label: '滞胀 · 股债双杀风险' },
    'reflation':    { cls: 'risk-on', label: '再通胀 · 利好商品/顺周期' },
    'disinflation': { cls: 'mixed', label: '通胀回落 · 温和利多债市/成长' },
    'mixed':        { cls: 'mixed', label: '信号混杂' }
  };
  const s = sigMap[r.signal] || sigMap.mixed;
  return '<div class="regime-banner ' + s.cls + ' ' + (extraClass || '') + '">' +
    '<div class="regime-left">' +
      '<div class="regime-label">当前 Regime · ' + s.label + '</div>' +
      '<div class="regime-name">' + r.label + '</div>' +
      '<div class="regime-conf">' + r.confidence + '</div>' +
    '</div>' +
    '<div class="regime-right">' + r.description + '</div>' +
  '</div>';
}

// 关键信号列表 (alert: 重大变化/转向警示, 高亮显示)
function signalList(signals) {
  let html = '<div class="signal-list">';
  signals.forEach(s => {
    const isAlert = !!s.alert;
    const badgeLabel = s.direction === 'bearish' ? '利空' : s.direction === 'bullish' ? '利多' : '中性';
    if (isAlert) {
      // 转向警示信号: 红色高亮 + ⚠ 图标
      const lv2 = s.alertLevel >= 2;
      html += '<div class="signal-item signal-alert' + (lv2 ? ' signal-alert-lv2' : '') + '">' +
        '<span class="signal-badge alert">' + (lv2 ? '⚠⚠ 强警示' : '⚠ 转向警示') + '</span>' +
        '<div class="signal-body">' +
          '<div class="signal-title">' + s.title + '</div>' +
          '<div class="signal-meaning">' + s.meaning + '</div>' +
        '</div>' +
      '</div>';
    } else {
      html += '<div class="signal-item">' +
        '<span class="signal-badge ' + s.direction + '">' + badgeLabel + '</span>' +
        '<div class="signal-body">' +
          '<div class="signal-title">' + s.title + '</div>' +
          '<div class="signal-meaning">' + s.meaning + '</div>' +
        '</div>' +
      '</div>';
    }
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
    na:     ['无一致预期', '#8a93a3', 'rgba(138,147,163,0.12)'],
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

function chartCard(title, sub, id, h, actions, footer) {
  const act = actions ? '<div class="chart-actions">' + actions + '</div>' : '';
  const ft = footer ? '<div class="chart-footer">' + footer + '</div>' : '';
  return '<div class="chart-card"><div class="chart-header"><div><div class="chart-title">' + title + '</div><div class="chart-subtitle">' + sub + '</div></div>' + act + '</div><div class="chart-body ' + (h || '') + '"><canvas id="' + id + '"></canvas></div>' + ft + '</div>';
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

// 横轴拖拽缩放配置：拖拽框选时间区间放大 / 滚轮缩放 / Shift+拖拽平移
// 用于多折线相关性观察，方便锁定某段时间窗口
// dragEnabled=false 时关闭框选放大（用于黄金图，由底部 range slider 选择区间）
function zoomXOpts(dragEnabled) {
  dragEnabled = dragEnabled !== false;
  return {
    zoom: {
      wheel: { enabled: true, speed: 0.08 },
      pinch: { enabled: true },
      drag: dragEnabled ? {
        enabled: true,
        backgroundColor: 'rgba(224,168,0,0.12)',
        borderColor: 'rgba(224,168,0,0.6)',
        borderWidth: 1,
        mode: 'x'
      } : { enabled: false },
      mode: 'x'
    },
    pan: {
      enabled: true,
      mode: 'x',
      modifierKey: dragEnabled ? 'shift' : null   // 无框选时直接拖拽平移
    },
    limits: {
      x: { minRange: 5 }     // 至少保留约 5 个数据点，防止无限放大
    }
  };
}

/* ================= 底部时间区间滑块 (双 thumb range slider) ================= */
function rangeSliderHTML(id) {
  return '<div class="range-slider-wrap" id="' + id + 'Slider" data-chart="' + id + '">' +
    '<div class="range-slider-track">' +
      '<div class="range-slider-fill"></div>' +
      '<div class="range-slider-thumb start" data-side="start"></div>' +
      '<div class="range-slider-thumb end" data-side="end"></div>' +
    '</div>' +
    '<div class="range-slider-labels">' +
      '<span class="range-start"></span>' +
      '<span class="range-end"></span>' +
    '</div>' +
  '</div>';
}

function initRangeSlider(chart, id, opts) {
  // opts: { labels: [日期...], nums: [[原始数值]×datasets顺序], raws: [[原始值字符串]×datasets顺序] }
  const wrap = document.getElementById(id + 'Slider');
  if (!wrap || !chart) return;
  const track = wrap.querySelector('.range-slider-track');
  const fill = wrap.querySelector('.range-slider-fill');
  const thumbs = {
    start: wrap.querySelector('.range-slider-thumb.start'),
    end: wrap.querySelector('.range-slider-thumb.end')
  };
  const lbls = {
    start: wrap.querySelector('.range-start'),
    end: wrap.querySelector('.range-end')
  };
  const labels = opts.labels || [];
  const len = labels.length;
  if (len < 2) return;

  let state = { start: 0, end: len - 1 };

  function fmtShortDate(d) {
    if (!d || typeof d !== 'string') return '—';
    const p = d.split('-');
    return p.length === 3 ? p[0].slice(2) + '/' + p[1] : d;
  }

  function updateUI() {
    const sPct = (state.start / (len - 1)) * 100;
    const ePct = (state.end / (len - 1)) * 100;
    thumbs.start.style.left = sPct + '%';
    thumbs.end.style.left = ePct + '%';
    fill.style.left = sPct + '%';
    fill.style.width = (ePct - sPct) + '%';
    lbls.start.textContent = fmtShortDate(labels[state.start]);
    lbls.end.textContent = fmtShortDate(labels[state.end]);
  }

  // 数据切片方案：直接裁剪 labels/datasets，并按区间内起点重新归一化(%)
  // 不依赖 scale min/max(Chart.js v4 category 轴对其更新有兼容问题)，100% 可靠
  function applyChart() {
    const s = state.start, e = state.end;
    chart.data.labels = labels.slice(s, e + 1);
    chart.data.datasets.forEach(function (ds, i) {
      const nums = (opts.nums && opts.nums[i]) || [];
      const sl = nums.slice(s, e + 1);
      let b0 = null;
      for (let j = 0; j < sl.length; j++) {
        if (sl[j] != null) { b0 = sl[j]; break; }
      }
      ds.data = sl.map(function (v) {
        if (v == null || b0 == null || b0 === 0) return null;
        return Math.round((v / b0 - 1) * 10000) / 100;
      });
      if (ds.rawData && opts.raws && opts.raws[i]) {
        ds.rawData = opts.raws[i].slice(s, e + 1);
      }
    });
    chart.update();
  }

  function indexFromEvent(e) {
    const rect = track.getBoundingClientRect();
    const cx = e.touches && e.touches.length ? e.touches[0].clientX : e.clientX;
    let pct = (cx - rect.left) / rect.width;
    pct = Math.max(0, Math.min(1, pct));
    return Math.round(pct * (len - 1));
  }

  let activeSide = null;

  function onMove(e) {
    if (!activeSide) return;
    e.preventDefault();
    let idx = indexFromEvent(e);
    if (activeSide === 'start') {
      idx = Math.min(idx, state.end - 5);
      state.start = Math.max(0, idx);
    } else {
      idx = Math.max(idx, state.start + 5);
      state.end = Math.min(len - 1, idx);
    }
    updateUI();
    applyChart();
  }

  function onUp(e) {
    activeSide = null;
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    document.removeEventListener('pointercancel', onUp);
    if (thumbs.start) thumbs.start.classList.remove('dragging');
    if (thumbs.end) thumbs.end.classList.remove('dragging');
  }

  function onDown(e, side) {
    e.preventDefault();
    e.stopPropagation();
    activeSide = side;
    if (thumbs[side]) thumbs[side].classList.add('dragging');
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    document.addEventListener('pointercancel', onUp);
  }

  thumbs.start.addEventListener('pointerdown', function (e) { onDown(e, 'start'); });
  thumbs.end.addEventListener('pointerdown', function (e) { onDown(e, 'end'); });

  // 点击轨道空白处：把较近的一侧 thumb 跳到该位置
  track.addEventListener('pointerdown', function (e) {
    if (e.target.classList.contains('range-slider-thumb')) return;
    const idx = indexFromEvent(e);
    const side = (Math.abs(idx - state.start) <= Math.abs(idx - state.end)) ? 'start' : 'end';
    onDown(e, side);
    if (side === 'start') {
      state.start = Math.max(0, Math.min(idx, state.end - 5));
    } else {
      state.end = Math.min(len - 1, Math.max(idx, state.start + 5));
    }
    updateUI();
    applyChart();
  });

  // 重置按钮：恢复全时间范围
  const resetBtn = document.getElementById(id + 'Reset');
  if (resetBtn) {
    resetBtn.onclick = function () {
      state.start = 0;
      state.end = len - 1;
      updateUI();
      applyChart();
    };
  }

  updateUI();
}

// ===== 共享时间区间滑块 (多 chart 同步切片, 不重新归一化 — 用于量纲不同的多 panel) =====
// panels: [{ chart, series: {seriesName: [..]}, labelFmt? }, ...]
function initSharedSlider(panels, id, labels) {
  const wrap = document.getElementById(id + 'Slider');
  if (!wrap || !panels || !panels.length) return;
  const track = wrap.querySelector('.range-slider-track');
  const fill = wrap.querySelector('.range-slider-fill');
  const thumbs = {
    start: wrap.querySelector('.range-slider-thumb.start'),
    end: wrap.querySelector('.range-slider-thumb.end')
  };
  const lbls = {
    start: wrap.querySelector('.range-start'),
    end: wrap.querySelector('.range-end')
  };
  const len = labels.length;
  if (len < 2) return;

  let state = { start: 0, end: len - 1 };

  function updateUI() {
    const sPct = (state.start / (len - 1)) * 100;
    const ePct = (state.end / (len - 1)) * 100;
    thumbs.start.style.left = sPct + '%';
    thumbs.end.style.left = ePct + '%';
    fill.style.left = sPct + '%';
    fill.style.width = (ePct - sPct) + '%';
    lbls.start.textContent = labels[state.start].slice(0, 7);
    lbls.end.textContent = labels[state.end].slice(0, 7);
  }

  function applyChart() {
    const s = state.start, e = state.end;
    const sl = labels.slice(s, e + 1).map(function (s) { return s.slice(0, 7); });
    panels.forEach(function (p) {
      p.chart.data.labels = sl;
      p.chart.data.datasets.forEach(function (ds) {
        const key = ds.origLabel || ds.label;
        const arr = p.series[key];
        if (arr) ds.data = arr.slice(s, e + 1);
      });
      p.chart.update();
    });
  }

  function indexFromEvent(e) {
    const rect = track.getBoundingClientRect();
    const cx = e.touches && e.touches.length ? e.touches[0].clientX : e.clientX;
    let pct = (cx - rect.left) / rect.width;
    pct = Math.max(0, Math.min(1, pct));
    return Math.round(pct * (len - 1));
  }

  let activeSide = null;
  function onMove(e) {
    if (!activeSide) return;
    e.preventDefault();
    let idx = indexFromEvent(e);
    if (activeSide === 'start') {
      idx = Math.min(idx, state.end - 1);
      state.start = Math.max(0, idx);
    } else {
      idx = Math.max(idx, state.start + 1);
      state.end = Math.min(len - 1, idx);
    }
    updateUI();
    applyChart();
  }
  function onUp() {
    activeSide = null;
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    document.removeEventListener('pointercancel', onUp);
    if (thumbs.start) thumbs.start.classList.remove('dragging');
    if (thumbs.end) thumbs.end.classList.remove('dragging');
  }
  function onDown(e, side) {
    e.preventDefault();
    e.stopPropagation();
    activeSide = side;
    if (thumbs[side]) thumbs[side].classList.add('dragging');
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    document.addEventListener('pointercancel', onUp);
  }
  thumbs.start.addEventListener('pointerdown', function (e) { onDown(e, 'start'); });
  thumbs.end.addEventListener('pointerdown', function (e) { onDown(e, 'end'); });
  track.addEventListener('pointerdown', function (e) {
    if (e.target.classList.contains('range-slider-thumb')) return;
    const idx = indexFromEvent(e);
    const side = (Math.abs(idx - state.start) <= Math.abs(idx - state.end)) ? 'start' : 'end';
    onDown(e, side);
    if (side === 'start') state.start = Math.max(0, Math.min(idx, state.end - 1));
    else state.end = Math.min(len - 1, Math.max(idx, state.start + 1));
    updateUI();
    applyChart();
  });
  updateUI();
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
  // ===== 关键资产阈值警报 (市场公认关口, 突破 = 宏观信号确认) =====
  const kal = d.keyAlerts || [];
  const kalTrg = kal.filter(function (a) { return a.status === 'triggered'; });
  const kalNear = kal.filter(function (a) { return a.status === 'near'; });
  if (kalTrg.length || kalNear.length) {
    html += '<div style="margin:6px 0 14px;padding:12px 16px;border-radius:10px;background:#fbf6f0;border:1px solid #e8d5b5;">'
      + '<div style="font-size:12px;font-weight:600;color:#2c2c2a;margin-bottom:6px;">⚠ 关键资产阈值警报 <span style="font-weight:400;color:#9ca3af;font-size:11px;">突破市场公认关口 = 宏观信号确认</span></div>'
      + kalTrg.map(function (a) {
          return '<div style="font-size:12px;color:#a32d2d;line-height:1.7;margin-top:4px;">🔴 <b>' + a.name + '</b> ' + a.value + a.unit + ' 已突破 <b>' + a.label + '</b> — ' + a.meaning + '</div>';
        }).join('')
      + kalNear.map(function (a) {
          return '<div style="font-size:12px;color:#b45309;line-height:1.7;margin-top:4px;">🟠 <b>' + a.name + '</b> ' + a.value + a.unit + ' 逼近 <b>' + a.label + '</b>（相距 ' + a.distPct + '%）— ' + a.meaning + '</div>';
        }).join('')
      + '</div>';
  }
  html += sectionH('关键信号', '按对风险资产的影响方向排序');
  html += signalList(d.keySignals);
  html += metricCardsV3(d.metrics);
  html += '<div class="chart-row two-col">' +
    chartCard('资产走势对比', '近30日累计涨跌(起点=0%)', 'assetsPerf', 'tall') +
    chartCard('跨资产相关性矩阵', '共同交易日日度收益真实相关 · 股债/油股符号变化是regime信号', 'corr', 'tall') +
  '</div>';
  html += chartCard('大类资产热力图', '日涨跌幅 · 红=涨 绿=跌', 'heatmap', 'short');
  html += '<div class="chart-row one-col">' +
    chartCard('美股指数 + 加密货币走势（累计涨跌）', (d.usIndicesChart.note || '累计涨跌(起点=0%) · 美股五大指数 + 比特币/以太坊') + ' · 拖动下方滑块调整时间区间', 'usIndices', 'tall', '<button class="chart-zoom-reset" id="usIndicesReset">重置</button>', rangeSliderHTML('usIndices')) +
    '</div>';
  html += '<div class="chart-row one-col">' +
    chartCard('黄金定价 · 五因子 vs 黄金走势', (d.goldNarrativeChart.note || '近1年同起点累计涨跌% · 五因子与黄金走势对比') + ' · 拖动下方滑块调整时间区间', 'goldNarr', 'tall', '<button class="chart-zoom-reset" id="goldNarrReset">重置</button>', rangeSliderHTML('goldNarr')) +
    '</div>';
  html += '<div class="chart-row one-col">' +
    chartCard('全球央行净购金（WGC 季度）', (d.cbPurchasesChart.note || 'WGC 季度央行净购金(吨) · 含12个月滚动累计') + ' · 参与黄金驱动模型评分', 'cbPurchases', 'tall') +
    '</div>';
  html += renderGoldDrivers(d.goldNarrativeChart);
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
  // 美股五大指数 + 加密货币归一化走势 (与黄金图一致: tooltip 显示时间点真实值 + 底部时间区间滑块)
  if (d.usIndicesChart && d.usIndicesChart.series && Object.keys(d.usIndicesChart.series).length > 0) {
    const uid = d.usIndicesChart;
    const uiNames = Object.keys(uid.series);
    const uiOpts = baseOpts('%');
    uiOpts.plugins.tooltip.callbacks.label = function (ctx) {
      const ds = ctx.dataset;
      const idx = ctx.dataIndex;
      const raw = (ds.rawData && ds.rawData[idx]) ? ds.rawData[idx] : '';
      const y = ctx.parsed.y;
      const sign = y >= 0 ? '+' : '';
      return ds.origLabel + (raw ? ' ' + raw : '') + ' · 累计 ' + sign + y.toFixed(2) + '%';
    };
    charts.usIndices = new Chart(document.getElementById('usIndices'), {
      type: 'line',
      data: {
        labels: uid.labels,
        datasets: uiNames.map((n, i) => ({
          label: n,
          origLabel: n,
          data: uid.series[n],
          rawData: (uid.rawSeries && uid.rawSeries[n]) ? uid.rawSeries[n] : null,
          borderColor: COLORS.series[i % COLORS.series.length],
          backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3,
          spanGaps: true
        }))
      },
      options: uiOpts
    });
    // 底部时间区间滑块 (数据切片方案, 与黄金图一致); 不再启用 zoom 插件
    initRangeSlider(charts.usIndices, 'usIndices', {
      labels: uid.labels,
      nums: uiNames.map(function (n) { return (uid.rawNums && uid.rawNums[n]) ? uid.rawNums[n] : null; }),
      raws: uiNames.map(function (n) { return (uid.rawSeries && uid.rawSeries[n]) ? uid.rawSeries[n] : null; })
    });
  }
  // 黄金定价五因子: 黄金 vs 实际利率/美元指数/避险VIX/通胀预期BEI (归一化累计涨跌, 因子均为原始方向不翻转)
  if (d.goldNarrativeChart && d.goldNarrativeChart.labels && d.goldNarrativeChart.labels.length) {
    const gn = d.goldNarrativeChart;
    const gnOrder = ['黄金', '实际利率', '美元指数', '避险 VIX', '通胀预期 BEI'];
    const gnColors = { '黄金': '#e0a800', '实际利率': '#4361ee', '美元指数': '#10b981', '避险 VIX': '#ef4444', '通胀预期 BEI': '#8b5cf6' };
    const gnDash = { '避险 VIX': [5, 3] };
    const gnNames = gnOrder.filter(function (n) { return gn.series[n]; });
    const gnDatasets = gnNames.map(function (n) {
      const isGold = (n === '黄金');
      const cur = (gn.current && gn.current[n]) ? '  ' + gn.current[n] : '';
      return {
        label: n + cur,
        origLabel: n,
        data: gn.series[n],
        rawData: (gn.rawSeries && gn.rawSeries[n]) ? gn.rawSeries[n] : null,
        borderColor: gnColors[n],
        backgroundColor: isGold ? 'rgba(224,168,0,0.12)' : 'transparent',
        borderWidth: isGold ? 3 : 2,
        pointRadius: 0,
        tension: 0.3,
        borderDash: gnDash[n] || undefined,
        fill: isGold
      };
    });
    const gnOpts = baseOpts('%');
    // tooltip 显示横坐标对应时间点的源数据真实值 + 累计涨跌，避免图例固定当前值造成误读
    gnOpts.plugins.tooltip.callbacks.label = function (ctx) {
      const ds = ctx.dataset;
      const idx = ctx.dataIndex;
      const raw = (ds.rawData && ds.rawData[idx]) ? ds.rawData[idx] : '';
      const y = ctx.parsed.y;
      const sign = y >= 0 ? '+' : '';
      return ds.origLabel + (raw ? ' ' + raw : '') + ' · 累计 ' + sign + y.toFixed(2) + '%';
    };
    charts.goldNarr = new Chart(document.getElementById('goldNarr'), {
      type: 'line',
      data: { labels: gn.labels, datasets: gnDatasets },
      options: gnOpts
    });
    // 滑块用数据切片方案(区间内按区间起点重新归一化)，100% 可靠，不依赖 scale min/max；
    // 故黄金图不再启用 zoom 插件，滑块是唯一横轴控制器
    initRangeSlider(charts.goldNarr, 'goldNarr', {
      labels: gn.labels,
      nums: gnNames.map(function (n) { return (gn.rawNums && gn.rawNums[n]) ? gn.rawNums[n] : null; }),
      raws: gnNames.map(function (n) { return (gn.rawSeries && gn.rawSeries[n]) ? gn.rawSeries[n] : null; })
    });
  }
  // 央行净购金走势图 (WGC 季度数据, 柱状 + 12个月滚动累计线)
  if (d.cbPurchasesChart && d.cbPurchasesChart.labels && d.cbPurchasesChart.labels.length) {
    const cb = d.cbPurchasesChart;
    charts.cbPurchases = new Chart(document.getElementById('cbPurchases'), {
      type: 'bar',
      data: {
        labels: cb.labels.map(function (s) { return s.slice(0, 7); }),
        datasets: [
          {
            type: 'bar',
            label: '季度净购金(吨)',
            data: cb.series['季度净购金(吨)'] || [],
            backgroundColor: 'rgba(224,168,0,0.55)',
            borderColor: '#e0a800',
            borderWidth: 1.5,
            yAxisID: 'y',
            order: 2
          },
          {
            type: 'line',
            label: '12个月滚动累计(吨)',
            data: cb.series['12个月滚动累计(吨)'] || [],
            borderColor: '#4361ee',
            backgroundColor: 'transparent',
            borderWidth: 2.5,
            pointRadius: 3,
            pointBackgroundColor: '#4361ee',
            tension: 0.25,
            yAxisID: 'y1',
            order: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#6b7280', font: { size: 11 }, boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                const v = ctx.parsed.y;
                return ctx.dataset.label + ': ' + (v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(0) + ' 吨');
              }
            }
          }
        },
        scales: {
          x: {
            grid: { color: '#eef0f3', drawBorder: false },
            ticks: { color: '#6b7280', font: { size: 10 } }
          },
          y: {
            position: 'left',
            title: { display: true, text: '季度净购金(吨)', color: '#6b7280', font: { size: 10 } },
            grid: { color: '#eef0f3', drawBorder: false },
            ticks: { color: '#6b7280', font: { size: 10 } }
          },
          y1: {
            position: 'right',
            title: { display: true, text: '12个月累计(吨)', color: '#6b7280', font: { size: 10 } },
            grid: { drawOnChartArea: false },
            ticks: { color: '#6b7280', font: { size: 10 } }
          }
        }
      }
    });
  }
  // 两个带滑块图表的"重置"按钮复位逻辑在 initRangeSlider 内绑定(id+Reset);
  // 黄金图五因子驱动模型以下不再需要单独 resetZoom
}

// 黄金定价五因子驱动模型 (专家框架) + 三阶段叙事
function renderGoldDrivers(gn) {
  const r = (gn && gn.regime) || {};
  if (!r.ok) return '';
  let h = sectionH('黄金定价驱动因子', '五因子评分 · 量化各叙事对金价上行的贡献（基于近90日真实相关性，非互斥）');
  const gr = (r.goldReturn == null) ? '' : ('近90日黄金累计 ' + (r.goldReturn >= 0 ? '+' : '') + r.goldReturn + '%');
  const primeCls = (r.primary === 'consolidation') ? 'gv-down' : ((r.primary === 'mixed') ? 'gv-mixed' : 'gv-up');
  h += '<div class="gold-verdict ' + primeCls + '">' +
    '<div class="gold-verdict-main">主导叙事：<b>' + (r.primaryLabel || '—') + '</b></div>' +
    (gr ? '<div class="gold-verdict-sub">' + gr + '</div>' : '') +
    '</div>';
  h += '<div class="gold-drivers">';
  (r.drivers || []).forEach(function (dr) {
    const roleCls = dr.role === 'primary' ? 'role-primary' : (dr.role === 'support' ? 'role-support' : 'role-none');
    const roleTxt = dr.role === 'primary' ? '主因' : (dr.role === 'support' ? '辅助' : '不成立');
    const corrTxt = dr.corr == null ? '—' : ((dr.corr >= 0 ? '+' : '') + dr.corr.toFixed(2));
    const corrCls = (dr.corr == null) ? '' : (dr.corr > 0 ? 'corr-pos' : 'corr-neg');
    h += '<div class="gold-driver ' + roleCls + '">' +
      '<div class="gd-head"><span class="gd-name">' + dr.name + '</span>' +
        '<span class="gd-role">' + roleTxt + '</span></div>' +
      '<div class="gd-dir">' + dr.dir + '</div>' +
      '<div class="gd-bar-wrap"><div class="gd-bar" style="width:' + Math.min(100, dr.score) + '%"></div>' +
        '<span class="gd-score">' + dr.score + '</span></div>' +
      '<div class="gd-corr ' + corrCls + '">相关 ' + corrTxt + '</div>' +
      '</div>';
  });
  h += '</div>';
  // 专家解读
  h += '<div class="gold-analysis"><div class="ga-title">专家解读</div><div class="ga-body">' +
    (r.analysis || '') + '</div></div>';
  // 三阶段叙事
  const ph = r.phases || {};
  h += sectionH('黄金定价的三个阶段', ph.currentLabel || '');
  h += '<div class="gold-phases">';
  (ph.stages || []).forEach(function (st) {
    const cur = (ph.currentStage && st.phase.indexOf(ph.currentStage) === 0);
    h += '<div class="gold-phase' + (cur ? ' phase-current' : '') + '">' +
      '<div class="gp-phase">' + st.phase + '</div>' +
      '<div class="gp-driver">' + st.driver + '</div>' +
      '<div class="gp-desc">' + st.desc + '</div>' +
      '</div>';
  });
  h += '</div>';
  return h;
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

  // ===== 流动性表现 =====
  if (d.liquidity) {
    const liq = d.liquidity;
    const liqCls = liq.state === '充裕' ? '#0f6e56' : (liq.state === '收缩' ? '#a32d2d' : '#854f0b');
    const liqBg = liq.state === '充裕' ? '#e6f6ee' : (liq.state === '收缩' ? '#fcebeb' : '#faeeda');
    html += sectionH('流动性表现', '稳定币蓄水池 + 杠杆情绪 + 市场情绪 —— 加密的"水位"');
    html += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin-bottom:12px;">'
      + '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px;">'
      + '<span style="padding:3px 12px;border-radius:14px;font-size:12px;font-weight:600;background:' + liqBg + ';color:' + liqCls + ';">' + (liq.label || '流动性中性') + '</span>'
      + (liq.stablecoins && liq.stablecoins.total_b != null ? '<span style="font-size:12px;color:#374151;">稳定币总市值 <b style="color:#0f6e56;">$' + liq.stablecoins.total_b + 'B</b></span>' : '')
      + (liq.fundingRate != null ? '<span style="font-size:12px;color:#374151;">资金费率 <b style="color:' + (liq.fundingRate > 0.03 ? '#a32d2d' : '#0f6e56') + ';">' + (liq.fundingRate > 0 ? '+' : '') + liq.fundingRate.toFixed(3) + '%</b></span>' : '')
      + (liq.fng != null ? '<span style="font-size:12px;color:#374151;">恐慌贪婪 <b style="color:' + (liq.fng <= 30 ? '#a32d2d' : (liq.fng >= 75 ? '#e85d04' : '#0f6e56')) + ';">' + liq.fng + ' (' + (liq.fngLabel || '') + ')</b></span>' : '')
      + '</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:6px;">'
      + (liq.points || []).map(function (p) { return '<span style="font-size:11px;color:#5f5e5a;background:#f7f8fa;border:1px solid #e5e7eb;border-radius:6px;padding:4px 8px;">' + p + '</span>'; }).join('')
      + '</div></div>';
  }

  // ===== 主导叙事 + 定价矛盾 =====
  if (d.narrative || d.contradictions) {
    html += sectionH('主导叙事与定价矛盾', '当前市场在交易什么故事 · 价格 vs 基本面的背离');
    html += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin-bottom:12px;">'
      + '<div style="font-size:13px;font-weight:600;color:#1a1d29;margin-bottom:4px;">📖 主导叙事</div>'
      + '<div style="font-size:12px;color:#374151;line-height:1.7;">' + (d.narrative ? d.narrative.full : '数据不足') + '</div>';
    if (d.contradictions && d.contradictions.length) {
      html += '<div style="margin-top:10px;font-size:13px;font-weight:600;color:#a32d2d;margin-bottom:4px;">⚠ 定价矛盾 (' + d.contradictions.length + ')</div>'
        + d.contradictions.map(function (x) {
            return '<div style="font-size:12px;color:#791f1f;background:#fff3f3;border:1px solid #f7c1c1;border-radius:8px;padding:8px 10px;margin-bottom:6px;line-height:1.6;">'
              + '<b>' + x.title + '</b> · ' + x.detail + '</div>';
          }).join('');
    } else {
      html += '<div style="margin-top:8px;font-size:12px;color:#0f6e56;">✓ 当前价格与链上/资金面无显著背离</div>';
    }
    html += '</div>';
  }

  // ===== 链上数据 =====
  if (d.onChain && d.onChain.labels && d.onChain.labels.length > 1) {
    const oc = d.onChain;
    html += sectionH('链上数据', '真实网络活动 — 价格之外的"实体"验证');
    html += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin-bottom:12px;">'
      + '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">'
      + (oc.txnLatest != null ? '<span style="font-size:12px;color:#374151;">日交易数 <b>' + Number(oc.txnLatest).toLocaleString() + '</b> <span style="color:' + (oc.txnChg > 0 ? '#0f6e56' : '#a32d2d') + ';">(' + (oc.txnChg > 0 ? '+' : '') + oc.txnChg + '%)</span></span>' : '')
      + (oc.activeLatest != null ? '<span style="font-size:12px;color:#374151;">活跃地址 <b>' + Number(oc.activeLatest).toLocaleString() + '</b></span>' : '')
      + (oc.volLatest != null ? '<span style="font-size:12px;color:#374151;">链上交易量 <b>$' + (Number(oc.volLatest) / 1e9).toFixed(2) + 'B</b></span>' : '')
      + '</div>'
      + chartCard('链上活跃度 (日交易数 vs 活跃地址)', '真实网络使用强度 · 与价格背离=警示', 'onChainChart', 'short')
      + '</div>';
  }

  html += '<div class="chart-row two-col">' +
    chartCard('BTC vs ETH 走势对比', '累计涨跌(起点=0%) · 相对强弱', 'btcEth', 'tall') +
    chartCard('ETH/BTC 比率', 'Altcoin 季节性核心指标 · >0.05 ETH强势', 'ethBtc', 'tall') +
    '</div>';
  html += '<div class="chart-row two-col">' +
    chartCard('黄金 vs BTC 走势对比', '共同交易日累计涨跌(起点=0%) · 近一年 · 数字黄金 vs 风险资产', 'goldBtc', 'tall') +
    chartCard('黄金 vs BTC 滚动相关性', '日度收益 Pearson 相关 · 30日(虚线)灵敏 / 90日(实线)平滑 · 近一年 · >+0.3 同向联动', 'goldBtcCorr', 'tall') +
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
  if (d.goldBtcChart && d.goldBtcChart.labels && d.goldBtcChart.labels.length) {
    const gb = d.goldBtcChart;
    charts.goldBtc = new Chart(document.getElementById('goldBtc'), {
      type: 'line',
      data: {
        labels: gb.labels,
        datasets: Object.keys(gb.series).map(function (n) {
          return {
            label: n, data: gb.series[n],
            borderColor: n === 'BTC' ? '#f7931a' : '#d4a017',
            backgroundColor: 'transparent', borderWidth: 2.5, pointRadius: 0, tension: 0.3
          };
        })
      },
      options: baseOpts('%')
    });
  }
  if (d.goldBtcCorr && d.goldBtcCorr.labels && d.goldBtcCorr.labels.length) {
    const gc = d.goldBtcCorr;
    const gColors = { '30日滚动相关': '#0ea5e9', '90日滚动相关': '#7c3aed' };
    charts.goldBtcCorr = new Chart(document.getElementById('goldBtcCorr'), {
      type: 'line',
      data: {
        labels: gc.labels,
        datasets: Object.keys(gc.series).map(function (n) {
          return {
            label: n, data: gc.series[n],
            borderColor: gColors[n] || '#7c3aed', backgroundColor: 'transparent',
            borderWidth: n.indexOf('90') === 0 ? 2.5 : 1.4,
            borderDash: n.indexOf('90') === 0 ? [] : [3, 3],
            pointRadius: 0, tension: 0.3
          };
        }).concat([{
          label: '基准线(0)', data: gc.labels.map(function () { return 0; }),
          borderColor: 'rgba(148,163,184,0.55)', borderWidth: 1, borderDash: [4, 4],
          pointRadius: 0, fill: false, hitRadius: 0
        }])
      },
      options: Object.assign(baseOpts(''), {
        scales: Object.assign({}, baseOpts('').scales, {
          y: Object.assign({}, baseOpts('').scales.y, {
            min: -1, max: 1,
            ticks: Object.assign({}, baseOpts('').scales.y.ticks, {
              stepSize: 0.5,
              callback: function (v) { return v.toFixed(1); }
            })
          })
        }),
        plugins: Object.assign({}, baseOpts('').plugins, {
          legend: Object.assign({}, baseOpts('').plugins.legend, {
            labels: Object.assign({}, baseOpts('').plugins.legend.labels, {
              filter: function (item) { return item.text !== '基准线(0)'; }
            })
          }),
          tooltip: Object.assign({}, baseOpts('').plugins.tooltip, {
            callbacks: {
              label: function (ctx) {
                if (ctx.dataset.label === '基准线(0)') return '';
                if (ctx.parsed.y == null || isNaN(ctx.parsed.y)) return '';
                return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2);
              }
            }
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
  if (d.onChain && d.onChain.labels && d.onChain.labels.length > 1) {
    const oc2 = d.onChain;
    charts.onChainChart = new Chart(document.getElementById('onChainChart'), {
      type: 'line',
      data: {
        labels: oc2.labels,
        datasets: [
          { label: '日交易数', data: oc2.series['日交易数'], borderColor: '#f7931a', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3, yAxisID: 'y' },
          { label: '活跃地址', data: oc2.series['活跃地址'], borderColor: '#627eea', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3, yAxisID: 'y1' }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, position: 'top', labels: { color: COLORS.text, font: { size: 11 }, boxWidth: 12 } },
          tooltip: { callbacks: { label: function(ctx) { return ctx.dataset.label + ': ' + Number(ctx.parsed.y).toLocaleString(); } } }
        },
        scales: {
          x: { grid: { color: COLORS.grid, drawBorder: false }, ticks: { color: COLORS.text, font: { size: 10 }, maxTicksLimit: 10, callback: fmtDate } },
          y: { grid: { color: COLORS.grid, drawBorder: false }, ticks: { color: COLORS.text, font: { size: 10 }, callback: function(v) { return Number(v).toLocaleString(); } } },
          y1: { position: 'right', grid: { drawBorder: false }, ticks: { color: COLORS.text, font: { size: 10 }, callback: function(v) { return Number(v).toLocaleString(); } } }
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

  // ===== 利率 → 资产传导机制 =====
  if (d.transmissionMap) {
    html += sectionH('利率 → 资产传导机制', '收益率曲线 (水平/斜率/实际利率) → 折现率/曲线/实际利率三通道 → 各类资产 (速查)');
    html += _renderTransmissionMap(d.transmissionMap);
  }

  html += metricCardsV3(d.metrics);
  html += '<div class="chart-row two-col">' +
    chartCard('国债收益率曲线', '今日 vs 1月前 vs 1年前 · 熊陡=长端领涨', 'yc', 'tall') +
    chartCard('名义 vs 实际利率', '实际利率是估值的真实折现率', 'rateTrend', 'tall') +
  '</div>';
  html += '<div class="chart-row two-col">' +
    chartCard('10Y-2Y 利差', (d.chartNotes || {}).spreadNote || '曲线陡峭化/倒挂/平坦', 'spreadChart', 'tall') +
    chartCard('10Y 通胀预期 (Breakeven)', '名义利率 − 实际利率 = 市场通胀预期', 'breakevenChart', 'tall') +
  '</div>';
  html += '<div class="chart-row one-col">' +
    chartCard('美债收益率走势', (d.yieldTrendsChart.note || '3M/1Y/2Y/10Y/30Y 收益率走势') + ' · 拖动下方滑块调整时间区间', 'yieldTrends', 'tall', '<button class="chart-zoom-reset" id="yieldTrendsReset">重置</button>', rangeSliderHTML('yieldTrends')) +
    '</div>';
  html += sectionH('多尺度趋势追踪', (d.chartNotes || {}).trendNote || '日/周/月/半年变化 → 识别趋势确立、加速与反转');
  html += trendTable(d.trendData);
  html += analystBox(d.analystView);
  html += watchList(d.whatToWatch);
  html += sectionH('关键期限利率拆解', '名义利率 = 实际利率 + 通胀预期');
  html += table(['期限', '名义利率', '日变动', '实际利率', '通胀预期', '数据源'], d.detailedTable.map(r => [r.maturity, r.rate, r.change, r.realRate, r.breakeven, r.source]));

  // ===== 美国国债拍卖利率追踪 =====
  if (d.auctions) {
    const a = d.auctions;
    const aSub = '各期限最新拍卖中标利率与需求 · 来源 ' + (a.source || 'U.S. Treasury') + (a.asOf ? ' · 截至 ' + a.asOf : '');
    html += sectionH('美国国债拍卖利率追踪', aSub);
    if (a.note) html += '<div class="section-note" style="margin:-4px 0 10px;">' + a.note + '</div>';
    html += table(
      ['期限', '类型', '拍卖日', '中标利率', '较前次', '投标倍数', '间接认购%', '发行量', '性质'],
      a.table.map(r => [r.label, r.type, r.date, r.rate, r.changeBp, r.bidToCover, r.indirectPct, r.offeringB, (r.reopening ? '重发' : '新发')])
    );
    html += '<div class="chart-row one-col">' +
      chartCard('拍卖收益率曲线', '各期限最新拍卖中标利率 (名义 vs TIPS 实利率)', 'auctCurve', 'tall') +
      '</div>';
    html += '<div class="chart-row one-col">' +
      chartCard('拍卖中标利率历史', '2Y / 5Y / 10Y / 30Y 历次拍卖中标利率走势 (横轴为拍卖日)', 'auctHistory', 'tall') +
      '</div>';
  }
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
  // 美债收益率走势 (3M/1Y/2Y/10Y/30Y, 真实收益率水平值, tooltip 时间点值 + 底部滑块)
  const yt = d.yieldTrendsChart;
  if (yt && yt.labels && yt.labels.length && yt.series && Object.keys(yt.series).length) {
    const ytNames = Object.keys(yt.series);
    const ytColors = { '3M': '#f59e0b', '1Y': '#10b981', '2Y': '#3a86ff', '10Y': '#4361ee', '30Y': '#7209b7' };
    const ytOpts = baseOpts('%');
    ytOpts.plugins.tooltip.callbacks.label = function (ctx) {
      const ds = ctx.dataset;
      const idx = ctx.dataIndex;
      const raw = (ds.rawData && ds.rawData[idx]) ? ds.rawData[idx] : '';
      const y = ctx.parsed.y;
      // 直接展示该时间点的真实收益率 (水平值), 不统计涨跌
      return ds.origLabel + ' 收益率: ' + (raw || (y == null ? '—' : y.toFixed(2) + '%'));
    };
    charts.yieldTrends = new Chart(document.getElementById('yieldTrends'), {
      type: 'line',
      data: {
        labels: yt.labels,
        datasets: ytNames.map(n => {
          // 图例标注当前真实收益率, 便于一眼确认是水平值
          const raws = (yt.rawSeries && yt.rawSeries[n]) || [];
          let cur = '';
          for (let i = raws.length - 1; i >= 0; i--) { if (raws[i]) { cur = '  ' + raws[i]; break; } }
          return {
            label: n + cur, origLabel: n,
            data: yt.series[n],
            rawData: (yt.rawSeries && yt.rawSeries[n]) ? yt.rawSeries[n] : null,
            borderColor: ytColors[n] || COLORS.series[ytNames.indexOf(n) % COLORS.series.length],
            backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3,
            spanGaps: true
          };
        })
      },
      options: ytOpts
    });
    initRangeSlider(charts.yieldTrends, 'yieldTrends', {
      labels: yt.labels,
      nums: ytNames.map(function (n) { return (yt.rawNums && yt.rawNums[n]) ? yt.rawNums[n] : null; }),
      raws: ytNames.map(function (n) { return (yt.rawSeries && yt.rawSeries[n]) ? yt.rawSeries[n] : null; })
    });
  }

  // 美国国债拍卖利率追踪: 拍卖收益率曲线 + 拍卖历史
  const ac = d.auctions;
  if (ac && ac.curve && ac.curve.labels && ac.curve.labels.length) {
    const cv = ac.curve;
    charts.auctCurve = new Chart(document.getElementById('auctCurve'), {
      type: 'line',
      data: {
        labels: cv.labels,
        datasets: [
          { label: '名义中标利率', data: cv.nominal, borderColor: '#4361ee',
            backgroundColor: 'rgba(67,97,238,0.08)', borderWidth: 2.5, fill: true, pointRadius: 3, tension: 0.3, spanGaps: true },
          { label: 'TIPS 实利率', data: cv.tips, borderColor: '#e63946',
            backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 3], pointRadius: 3, tension: 0.3, spanGaps: true }
        ]
      },
      options: Object.assign(baseOpts('%'), {
        plugins: { tooltip: { callbacks: { label: function (ctx) {
          return ctx.dataset.label + ': ' + (ctx.parsed.y == null ? '—' : ctx.parsed.y.toFixed(3) + '%');
        } } } }
      })
    });
  }
  if (ac && ac.history && ac.history.labels && ac.history.labels.length) {
    const h = ac.history;
    const hColors = { '2年': '#3a86ff', '5年': '#10b981', '10年': '#4361ee', '30年': '#7209b7' };
    charts.auctHistory = new Chart(document.getElementById('auctHistory'), {
      type: 'line',
      data: {
        labels: h.labels,
        datasets: Object.keys(h.series).map(function (n) {
          return {
            label: n, data: h.series[n], borderColor: hColors[n] || COLORS.series[Object.keys(h.series).indexOf(n) % COLORS.series.length],
            backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3, spanGaps: true
          };
        })
      },
      options: Object.assign(baseOpts('%'), {
        plugins: { tooltip: { callbacks: { label: function (ctx) {
          return ctx.dataset.label + ' 拍卖: ' + (ctx.parsed.y == null ? '—' : ctx.parsed.y.toFixed(3) + '%');
        } } } }
      })
    });
  }
}
function renderFed(c) {
  const d = DATA.fed;
  let html = '';
  html += regimeBanner(d.regime);
  html += sectionH('关键信号', '');
  html += signalList(d.keySignals);

  // ===== 美联储 → 资产传导机制 =====
  if (d.transmissionMap) {
    html += sectionH('美联储政策 → 资产传导机制', '政策利率路径 + QT → 折现率/流动性/前瞻指引三通道 → 各类资产 (速查)');
    html += _renderTransmissionMap(d.transmissionMap);
  }
  html += metricCardsV3(d.metrics);
  html += '<div class="chart-row two-col">' +
    chartCard('美联储资产负债表', '总资产/国债/MBS(万亿美元) · QT持续推进', 'fedBs', 'tall') +
    chartCard('鹰鸽指数', (d.chartNotes || {}).hawkNote || ('0=极度鸽派 / 10=极度鹰派 · 当前 ' + d.hawkishDovish.score + ' ' + d.hawkishDovish.label), 'hawkDov', 'tall') +
  '</div>';
  const _nf = (d.fomcTimeline||[]).find(e => ['decision','meeting'].includes(e.type) && ['即将召开','进行中','待定'].includes(e.status));
  const _fomcSub = _nf ? (_nf.date.split('~')[0].slice(5).replace('-','/') + ' 会议 · 油价/通胀粘性定性是核心看点') : '油价/通胀粘性定性是每次会议的核心看点';
  html += sectionCard('FOMC 会议时间线', _fomcSub, renderFomcTimeline(d.fomcTimeline));
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
  let html = '<div><div style="display:flex;justify-content:space-between;margin-bottom:10px"><span style="font-size:13px">下次会议: ' + rp.nextMeeting + '</span>' +
    '<span style="font-size:11px;color:#6b7280">隐含均值 ' + (rp.meanCuts>0?'+':'') + rp.meanCuts + ' 次25bp · 不确定 ' + rp.stdCuts + '</span></div>';
  const probs = [
    { label: '降息50bp', val: rp.cut50bpProb,  color: '#4361ee' },
    { label: '降息25bp', val: rp.cut25bpProb,  color: '#2a9d8f' },
    { label: '维持不变', val: rp.holdProb,     color: '#6b7280' },
    { label: '加息25bp', val: rp.hike25bpProb, color: '#e85d04' },
    { label: '加息50bp', val: rp.hike50bpProb, color: '#c1121f' }
  ];
  html += '<div style="display:flex;gap:8px">';
  probs.forEach(p => {
    html += '<div style="flex:1;text-align:center">' +
      '<div style="height:8px;background:#eef0f4;border-radius:4px;overflow:hidden;margin-bottom:6px"><div style="height:100%;width:' + Math.max(0, p.val) + '%;background:' + p.color + ';border-radius:4px"></div></div>' +
      '<div style="font-size:10px;color:' + COLORS.text + '">' + p.label + '</div>' +
      '<div style="font-size:15px;font-weight:600;color:' + p.color + '">' + (p.val != null ? p.val : 0) + '%</div></div>';
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

  // ===== 流动性 → 资产传导机制 =====
  if (d.transmissionMap) {
    html += sectionH('流动性 → 资产传导机制', '准备金充裕度 → 融资/杠杆/避险三通道 → 各类资产 (速查)');
    html += _renderTransmissionMap(d.transmissionMap);
  }

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
// 经济数据 → 资产传导机制面板
// 数据发布后: ①看它如何改变利率路径预期 ②沿三条通道 (折现率/盈利/避险) 判断各资产方向
function _renderTransmissionMap(tm) {
  if (!tm || !tm.indicators || !tm.indicators.length) return '';
  let h = '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;margin-bottom:14px;">';
  // 顶部: 传导中枢说明
  h += '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px;">'
    + '<span style="font-size:13px;font-weight:600;color:#1a1d29;">传导中枢: </span>'
    + '<span style="padding:3px 10px;border-radius:14px;background:#eeedfe;color:#3c3489;font-size:12px;font-weight:500;">' + (tm.hub || '利率路径预期') + '</span>'
    + '</div>';
  // 三条通道图例
  h += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">'
    + (tm.channels || []).map(function (ch) {
        return '<div style="flex:1;min-width:190px;padding:7px 10px;background:' + ch.color + '11;border:1px solid ' + ch.color + ';border-radius:8px;">'
          + '<div style="font-size:12px;font-weight:600;color:' + ch.color + ';">' + ch.label + '</div>'
          + '<div style="font-size:10px;color:#5f5e5a;line-height:1.5;margin-top:2px;">' + ch.desc + '</div></div>';
      }).join('')
    + '</div>';
  // 各数据卡
  tm.indicators.forEach(function (ind) {
    const ch = (tm.channels || []).find(function (x) { return x.key === ind.channel; });
    const chColor = ch ? ch.color : '#5f5e5a';
    h += '<div style="border:1px solid #e5e7eb;border-radius:10px;margin-bottom:10px;overflow:hidden;">'
      + '<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:#f7f8fa;border-bottom:1px solid #e5e7eb;flex-wrap:wrap;">'
      + '<span style="font-size:13px;font-weight:600;color:#1a1d29;">' + ind.name + '</span>'
      + '<span style="font-size:10px;color:#888780;">' + (ind.freq || '') + '</span>'
      + '<span style="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;background:' + chColor + '22;color:' + chColor + ';">' + (ind.primary || ind.channel) + '</span>'
      + '<span style="margin-left:auto;font-size:11px;color:#854f0b;">' + (ind.current || '') + '</span>'
      + '</div>'
      + '<div style="padding:8px 12px;">'
      // 各资产影响 chips
      + '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;">'
      + (ind.impact || []).map(function (im) {
          const up = im.dir === 'up';
          const col = up ? '#0f6e56' : '#a32d2d';
          const bg = up ? '#e6f6ee' : '#fcebeb';
          return '<div style="padding:4px 8px;background:' + bg + ';border-radius:6px;font-size:11px;color:' + col + ';border:1px solid ' + col + '33;">'
            + '<b>' + im.asset + '</b> ' + (up ? '↑' : '↓') + ' <span style="color:#5f5e5a;">' + im.when + '</span>'
            + '<div style="font-size:10px;color:#5f5e5a;margin-top:1px;">' + im.why + '</div></div>';
        }).join('')
      + '</div>'
      + '<div style="font-size:11px;color:#5f5e5a;background:#f7f8fa;border-radius:6px;padding:6px 10px;line-height:1.6;">'
      + '<b style="color:#2c2c2a;">长期含义:</b> ' + (ind.longTerm || '—') + '</div>'
      + '</div></div>';
  });
  h += '</div>';
  return h;
}

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

  // ===== 经济数据 → 资产传导机制 =====
  if (d.transmissionMap) {
    html += sectionH('经济数据 → 资产传导机制', '数据发布 → 改变利率路径预期 → 三条通道 → 各类资产长短影响 (速查)');
    html += _renderTransmissionMap(d.transmissionMap);
  }

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
  // 劳动力市场供需价格三角框架 (3 联图: 需求 / 供给 / 价格)
  if (d.laborTriangleChart && d.laborTriangleChart.panels && Object.keys(d.laborTriangleChart.panels).length) {
    const lt = d.laborTriangleChart;
    html += sectionH('劳动力供需价格三角', lt.note + ' · 解读见三图下方');
    html += '<div class="chart-row three-col">' +
      chartCard('需求 Demand', lt.panels.demand.interpretation, 'labDemand', 'short') +
      chartCard('供给 Supply', lt.panels.supply.interpretation, 'labSupply', 'short') +
      chartCard('价格 Price', lt.panels.price.interpretation, 'labPrice', 'short') +
    '</div>';
    html += '<div class="chart-row one-col">' +
      '<div class="chart-card"><div class="chart-body" style="height:auto;padding:8px 16px 14px">' +
        rangeSliderHTML('laborTriangle') +
      '</div></div>' +
    '</div>';
  }
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

  // 劳动力市场供需价格三角 (3 panel chart + 共享滑块)
  if (d.laborTriangleChart && d.laborTriangleChart.panels && Object.keys(d.laborTriangleChart.panels).length) {
    const lt = d.laborTriangleChart;
    const datesFull = lt.labels;
    function _buildLaborChart(canvasId, panel) {
      const ds = Object.keys(panel.series).map(n => ({
        label: n,
        origLabel: n,
        data: panel.series[n],
        rawData: null,
        borderColor: panel.colors[n],
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 1.5,
        tension: 0.3
      }));
      return new Chart(document.getElementById(canvasId), {
        type: 'line',
        data: { labels: datesFull.map(function (s) { return s.slice(0, 7); }), datasets: ds },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { labels: { color: COLORS.text, font: { size: 10 }, boxWidth: 10 } },
            tooltip: { callbacks: { label: function (ctx) {
              return ctx.dataset.label + ': ' + (ctx.parsed.y == null ? '—' : ctx.parsed.y.toFixed(2));
            } } }
          },
          scales: {
            x: { grid: { color: COLORS.grid, drawBorder: false }, ticks: { color: COLORS.text, font: { size: 9 }, maxRotation: 0, autoSkip: true } },
            y: { position: 'left', grid: { color: COLORS.grid, drawBorder: false }, ticks: { color: COLORS.text, font: { size: 9 } } }
          }
        }
      });
    }
    charts.labDemand = _buildLaborChart('labDemand', lt.panels.demand);
    charts.labSupply = _buildLaborChart('labSupply', lt.panels.supply);
    charts.labPrice = _buildLaborChart('labPrice', lt.panels.price);
    // 共享滑块: 同时切 3 个 chart 的数据 (单位各异, 不重新归一化, 仅切片)
    initSharedSlider([
      { chart: charts.labDemand, series: lt.panels.demand.series },
      { chart: charts.labSupply, series: lt.panels.supply.series },
      { chart: charts.labPrice, series: lt.panels.price.series }
    ], 'laborTriangle', datesFull);
  }

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
  // 颜色按同比绝对水平 (直观反映通胀压力): 高>4%红 / 中2-4%橙 / 低0-2%绿 / 通缩蓝
  // 箭头+文字按边际方向 (同比 vs 上月 yoy): ↑加速/→持平/↓回落
  const levelColor = { high: '#c1121f', mid: '#e85d04', low: '#2a9d8f', flat: '#5b8def' };
  const trendColor = { up: '#c1121f', down: '#2a9d8f', flat: '#6b7280' };
  const trendLabel = t => t === 'up' ? '↑ 加速' : t === 'down' ? '↓ 回落' : '→ 持平';
  items.forEach(it => {
    const pct = Math.min(Math.abs(parseFloat(it.yoy)) / 6 * 100, 100);  // 条形=|同比|占6%比例
    const level = it.level || 'low';
    const cLevel = levelColor[level] || levelColor.low;
    const cTrend = trendColor[it.trend] || trendColor.flat;
    html += '<div style="display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid #f0f0f0">' +
      '<div style="min-width:150px"><div style="font-size:13px;font-weight:500">' + it.component + '</div>' +
      '<div style="font-size:11px;color:' + COLORS.neutral + '">' + it.note + '</div></div>' +
      '<div style="min-width:56px;text-align:right;font-size:13px;font-weight:600;color:' + cLevel + '">' + it.yoy + '</div>' +
      '<div style="min-width:64px;text-align:right;font-size:11px;color:' + cTrend + '">' + trendLabel(it.trend) + '</div>' +
      '<div style="min-width:60px;text-align:right;font-size:12px;color:' + COLORS.text + '" title="同比的上月变化">' + it.contribution + '</div>' +
      '<div style="flex:1;height:6px;background:#eef0f4;border-radius:3px;overflow:hidden"><div style="height:100%;width:' + pct + '%;background:' + cLevel + ';border-radius:3px"></div></div></div>';
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
function _renderCreditTransmission(tx, imp) {
  // 上半: 风险传导链 (左中右三列布局: 触发 → 中间 4 链路 → 终点 + 受益资产)
  // 颜色: 终点 red(下行/违约) vs green(上行/避险); 中间链 amber
  let h = '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px 20px;margin-bottom:14px;">';
  // 触发节点 + 4 条链路 (并排) + 终点 (4 列网格)
  h += '<div style="display:grid;grid-template-columns:0.7fr 1.4fr 1fr 1.2fr;gap:10px;align-items:center;">';
  // 1. 触发节点
  h += '<div style="text-align:center;padding:12px 8px;background:#fcebeb;border:1px solid #f09595;border-radius:10px;">'
    + '<div style="font-size:18px;">⚡</div>'
    + '<div style="font-size:13px;font-weight:600;color:#791f1f;margin-top:2px;">' + tx.trigger.label + '</div>'
    + '<div style="font-size:11px;color:#a32d2d;margin-top:2px;">' + tx.trigger.threshold + '</div>'
    + '</div>';
  // 2. 中间 4 链路 (2x2)
  h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">';
  tx.chains.forEach(function (c) {
    h += '<div style="padding:7px 8px;background:#faeeda;border:1px solid #ef9f27;border-radius:8px;font-size:11px;color:#633806;line-height:1.5;">'
      + '<div style="font-weight:600;color:#854f0b;">' + c.num + ' ' + c.link + '</div>'
      + '<div style="color:#a32d2d;font-size:10px;margin-top:1px;">' + c.detail + '</div></div>';
  });
  h += '</div>';
  // 3+4. 终点 + 受益资产 (4 列, 与链路 1:1)
  h += '<div></div>';  // 占位 - 我们直接接 4 终点
  h += '</div>';
  // 第二行: 终点 + 资产 (4 列对齐链路)
  h += '<div style="display:grid;grid-template-columns:0.7fr 1fr 1fr 1fr;gap:10px;align-items:start;margin-top:6px;">';
  h += '<div style="font-size:11px;color:#9ca3af;text-align:center;">触发</div>';
  tx.chains.forEach(function (c) {
    const dirIcon = c.dir === 'up' ? '↗' : '↘';
    const dirColor = c.dir === 'up' ? '#0f6e56' : '#a32d2d';
    h += '<div style="padding:8px;background:' +c.epColor +'11;border:1px solid ' + c.epColor + ';border-radius:8px;">'
      + '<div style="font-size:11px;font-weight:600;color:' + c.epColor + ';">' + dirIcon + ' ' + c.endpoint + '</div>'
      + '<div style="font-size:10px;color:#5f5e5a;margin-top:2px;line-height:1.5;">' + c.epNote + '</div>'
      + '<div style="margin-top:4px;padding:3px 6px;background:#f7f8fa;border-radius:4px;font-size:10px;color:' + dirColor + ';font-weight:600;">'
      + '→ ' + c.asset + '</div>'
      + '</div>';
  });
  h += '</div>';
  h += '</div>';

  // 下半: 各等级 × 重要性维度 热力图
  h += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;">';
  h += '<div style="font-size:13px;font-weight:600;color:#1a1d29;margin-bottom:8px;">各等级 × 重要性维度 (评分 0-5, 越高=该等级对风险信号越敏感)</div>';
  // 表头: 评级 + 4 维度
  h += '<div style="display:grid;grid-template-columns:80px repeat(4,1fr);gap:4px;align-items:center;">';
  h += '<div style="font-size:11px;font-weight:600;color:#5f5e5a;">评级</div>';
  imp.dimensions.forEach(function (d) {
    h += '<div style="text-align:center;font-size:11px;font-weight:600;color:#5f5e5a;line-height:1.3;padding:4px;">'
      + '<div style="font-size:14px;">' + d.icon + '</div>' + d.label + '<div style="font-size:10px;color:#9ca3af;font-weight:400;">' + d.desc + '</div></div>';
  });
  h += '</div>';
  // 行: 评级 × 维度分数 + 当前 OAS 注释
  imp.ratings.forEach(function (r) {
    const sc = imp.scores[r];
    const oas = imp.currentOAS ? imp.currentOAS[r] : null;
    const oasStr = oas != null ? oas.toFixed(2) + '%' : '—';
    h += '<div style="display:grid;grid-template-columns:80px repeat(4,1fr);gap:4px;align-items:center;margin-top:4px;">';
    h += '<div style="font-size:13px;font-weight:600;color:#1a1d29;padding:6px 4px;">' + r + '</div>';
    imp.dimensions.forEach(function (d) {
      const v = sc[d.key];
      const bg = v >= 4 ? '#fce8e8' : (v >= 3 ? '#fbe7d6' : (v >= 2 ? '#fef0db' : '#f1efe8'));
      const fg = v >= 4 ? '#a32d2d' : (v >= 3 ? '#854f0b' : (v >= 2 ? '#a37105' : '#888780'));
      const w = 0.4 + (v || 0) * 0.12;   // 透明度 0.4-1.0
      h += '<div style="text-align:center;padding:8px 4px;background:' + bg + ';color:' + fg + ';border-radius:6px;font-size:12px;font-weight:600;opacity:' + w + ';">' + (v || 0) + '</div>';
    });
    h += '</div>';
  });
  h += '</div>';

  // 评级注释 (合并到表格下方)
  h += '<div style="margin-top:14px;padding-top:10px;border-top:0.5px solid #e5e7eb;">';
  h += '<div style="font-size:11px;font-weight:600;color:#5f5e5a;margin-bottom:4px;">各评级观察要点:</div>';
  imp.ratings.forEach(function (r) {
    h += '<div style="font-size:11px;color:#374151;line-height:1.7;padding:2px 0;"><span style="font-weight:600;color:#185FA5;">' + r + '</span> · ' + imp.scores[r].note + '</div>';
  });
  h += '</div>';

  h += '</div>';
  return h;
}
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

  // ===== 风险传导链 (SVG流程图 + 等级重要性热力图) =====
  if (d.transmission && d.importance) {
    html += sectionH('风险传导链与各等级重要性', '利差快速走阔 → 4 条传导路径; 各等级对风险信号的敏感度');
    html += _renderCreditTransmission(d.transmission, d.importance);
  }

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

  // ===== 波动率 → 资产传导机制 =====
  if (d.transmissionMap) {
    html += sectionH('波动率 → 资产传导机制', '波动率水平/期限结构/跨资产压力 → 去杠杆/对冲/风险偏好三通道 → 各类资产 (速查)');
    html += _renderTransmissionMap(d.transmissionMap);
  }

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
function _aiFmt(x, suffix, ccy) {
  if (x === null || x === undefined) return '—';
  if (suffix === '%') return Number(x).toFixed(x >= 10 || x <= -10 ? 0 : 1) + '%';
  if (suffix === 'x') return Number(x).toFixed(x >= 10 ? 1 : 1) + 'x';
  if (suffix === 'B') {
    // marketCap 按市场币种存储: 美股 USD $B / A股 ¥亿(人民币, 腾讯自选股实时) / 韩股 KRW 万亿
    var sym = _aiCcySym(ccy);
    if (ccy === 'CNY') {
      var v = Number(x);
      if (v >= 10000) return '¥' + (v / 10000).toFixed(2) + '万亿';
      return '¥' + Math.round(v) + '亿';
    }
    if (ccy === 'KRW') return sym + Number(x).toFixed(1) + '万亿';
    return sym + Number(x).toFixed(1) + 'B';
  }
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
      '<div style="font-size:13px;font-weight:700;color:' + _aiValColor(c.marketCap, 'pe') + '">' + _aiFmt(c.marketCap, 'B', c.ccy) + '</div>',
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
  if (L.scarcity != null) {
    var _sc = L.scarcity;
    var _scCol = _sc >= 75 ? '#993c1d' : _sc >= 60 ? '#854f0b' : '#5f5e5a';
    var _scBg = _sc >= 75 ? '#fbeaf0' : _sc >= 60 ? '#faedda' : '#f1efe8';
    var _scLbl = _sc >= 75 ? '瓶颈稀缺·吃超额利润' : _sc >= 60 ? '供给偏紧·景气托底' : _sc >= 45 ? '中性·商品化中' : '承压·被平台挤压';
    inner += '<div style="margin:2px 0 10px"><span style="font-size:11px;padding:3px 10px;border-radius:12px;font-weight:600;background:' + _scBg + ';color:' + _scCol + '">结构性稀缺 ' + _sc + ' · ' + _scLbl + '</span></div>';
  }
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
      + '<div>' + trigHtml + '</div>'
      + (s.next ? '<div style="font-size:11px;color:#7f77dd;margin-top:8px;padding-top:8px;border-top:1px dashed #e5e7eb;line-height:1.6;"><b style="color:#5b4fd1;">演化方向 →</b> ' + s.next + '</div>' : '')
      + '</div>';
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

// ===== 市场定位: 谁在动 / 定价到什么程度 (P0-P1) =====
// CFTC 投机净持仓(谁) + 期限溢价 ACM(10Y拆解) + SLOOS(信贷领先) + NFCI分项(压力定位) + 实体锚
function renderPositioning(c) {
  const d = DATA.marketPositioning;
  if (!d) { c.innerHTML = '<div class="loading">市场定位数据加载中...</div>'; return; }
  let h = '';
  h += '<div style="margin:6px 0 18px;padding:14px 18px;border-radius:12px;background:#f7f8fa;border:1px solid #d3d1c7;">'
    + '<div style="font-size:13px;font-weight:500;color:#2c2c2a;margin-bottom:6px;">市场定位 · 回答"为什么动 + 谁在动"</div>'
    + '<div style="font-size:12px;color:#5f5e5a;line-height:1.7;">' + (d.analystView || '数据暂缺') + '</div>'
    + '</div>';

  // ===== 1. CFTC 离散持仓: 谁在动 (dealer / assetMgr / leveraged 三分法) =====
  const GLABEL = { dealer: '交易商/中介', assetMgr: '资产管理/真实资金', leveraged: '杠杆基金' };
  const GCOLOR = { dealer: '#185FA5', assetMgr: '#0F6E56', leveraged: '#a32d2d' };
  const GROLE = { dealer: '做市对冲·方向弱', assetMgr: '长期资金·方向强', leveraged: '投机动量·拥挤易反转' };
  h += sectionH('CFTC 离散持仓（谁在动）', 'CFTC TFF 报告: 交易商/中介 · 资产管理(真实资金) · 杠杆基金 三分法 — 取代 legacy 投机/套保二分 · 周更新');
  const cda = d.cftcDisagg || [];
  if (cda.length) {
    // 三方角色定位 (明确区分"谁在动、立场含义")
    h += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px;margin-bottom:12px;">'
      + '<div style="background:#e6f1fb;border:1px solid #b5d4f4;border-radius:8px;padding:8px 10px;"><span style="font-size:11px;font-weight:600;color:#185FA5;">交易商/中介</span><span style="font-size:10px;color:#374151;display:block;margin-top:2px;">银行做市商 · 净头寸多为对冲客户订单, <b>方向参考性弱</b></span></div>'
      + '<div style="background:#e6f6ee;border:1px solid #b7e0cf;border-radius:8px;padding:8px 10px;"><span style="font-size:11px;font-weight:600;color:#0F6E56;">资产管理/真实资金</span><span style="font-size:10px;color:#374151;display:block;margin-top:2px;">养老金/保险/共同基金 · 押注中期趋势, <b>方向信号强</b></span></div>'
      + '<div style="background:#fcebeb;border:1px solid #f0b8b8;border-radius:8px;padding:8px 10px;"><span style="font-size:11px;font-weight:600;color:#a32d2d;">杠杆基金</span><span style="font-size:10px;color:#374151;display:block;margin-top:2px;">对冲基金/CTA · 投机动量, <b>拥挤时易反转</b></span></div>'
      + '</div>';
    // 看图引导 (数据如何看 + 如何影响市场)
    h += '<details style="margin-bottom:12px;background:#f7f8fa;border:1px solid #e5e7eb;border-radius:8px;padding:6px 12px;">'
      + '<summary style="cursor:pointer;font-size:11px;color:#5f5e5a;outline:none;">📖 怎么看这张表（净持仓 / 周变化 / 拥挤度 → 立场）</summary>'
      + '<div style="font-size:11px;color:#374151;line-height:1.7;padding:6px 2px 4px;">'
      + '① <b>净持仓</b> = 多空轧差: 正值 = 净多头(押注上涨), 负值 = 净空头(押注下跌) → 立场列直接给出结论; '
      + '② <b>周变化</b> = 本周加减仓方向; '
      + '③ <b>拥挤度</b> = 净持仓/总持仓(OI): &gt;30% = 极端单边, 拥挤交易反转风险上升; '
      + '④ <b>怎么影响市场</b>: 资产管理 vs 杠杆基金方向相反 = 市场分歧; 杠杆基金极端单边 + 反向变化 = 轧空/踩踏燃料; 交易商净空多为做市对冲, 不直接解读为看空。</div>'
      + '</details>';
    cda.forEach(function (c) {
      const mover = c.mover;
      h += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;margin-bottom:12px;">';
      h += '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
        + '<span style="font-size:14px;font-weight:700;color:#1a1d29;">' + c.asset + '</span>'
        + '<span style="font-size:11px;color:#9ca3af;">' + (c.note || '') + ' · OI ' + (c.oi != null ? Number(c.oi).toLocaleString() : '—') + ' · ' + (c.date || '') + '</span></div>';
      h += '<div style="display:grid;grid-template-columns:1.6fr 0.6fr 1fr 1fr 0.7fr;gap:4px;font-size:10px;color:#9ca3af;padding:0 2px 4px;border-bottom:1px solid #eee;">'
        + '<span>参与方 (角色)</span><span style="text-align:center;">立场</span><span style="text-align:right;">净持仓(手)</span><span style="text-align:right;">周变化</span><span style="text-align:right;">拥挤度</span></div>';
      (c.groups || []).forEach(function (g) {
        const gk = g.group;
        const isMover = (gk === mover);
        const stance = (g.net == null) ? null : ((g.net > 0) ? 'long' : 'short');   // 立场: 净多=看涨 / 净空=看跌
        const netCol = stance === 'long' ? '#0f6e56' : '#a32d2d';
        const chgCol = (g.chgNet == null) ? '#9ca3af' : ((g.chgNet >= 0) ? '#0f6e56' : '#a32d2d');
        const crowd = (g.pctOi != null && g.pctOi > 30);
        const stBadge = stance === 'long' ? '<span style="padding:1px 7px;border-radius:9px;font-size:10px;font-weight:700;background:#e6f6ee;color:#0f6e56;">看涨</span>'
                     : stance === 'short' ? '<span style="padding:1px 7px;border-radius:9px;font-size:10px;font-weight:700;background:#fcebeb;color:#a32d2d;">看跌</span>'
                     : '<span style="font-size:10px;color:#9ca3af;">—</span>';
        h += '<div style="display:grid;grid-template-columns:1.6fr 0.6fr 1fr 1fr 0.7fr;gap:4px;align-items:center;padding:6px 2px;border-bottom:1px solid #f5f5f5;'
          + (isMover ? 'background:#fff8ec;border-radius:6px;' : '') + '">';
        h += '<span style="font-size:12px;font-weight:600;color:' + GCOLOR[gk] + ';">' + (GLABEL[gk] || gk)
          + '<span style="display:block;font-size:9px;color:#9ca3af;font-weight:400;">' + (GROLE[gk] || '') + '</span>'
          + (isMover ? ' <span style="font-size:9px;background:#854f0b;color:#fff;padding:1px 5px;border-radius:8px;font-weight:600;vertical-align:middle;">本周主导</span>' : '') + '</span>';
        h += '<span style="text-align:center;">' + stBadge + '</span>';
        h += '<span style="text-align:right;font-size:12px;font-weight:600;color:' + netCol + ';">' + (g.net == null ? '—' : ((g.net > 0 ? '+' : '') + Number(g.net).toLocaleString())) + '</span>';
        h += '<span style="text-align:right;font-size:12px;color:' + chgCol + ';">' + (g.chgNet == null ? '—' : ((g.chgNet > 0 ? '+' : '') + Number(g.chgNet).toLocaleString()) + (g.chgNet >= 0 ? ' <span style="font-size:9px;opacity:.7;">增</span>' : ' <span style="font-size:9px;opacity:.7;">减</span>')) + '</span>';
        h += '<span style="text-align:right;font-size:12px;' + (crowd ? 'color:#a32d2d;font-weight:700;' : 'color:#374151;') + '">' + (g.pctOi == null ? '—' : (g.pctOi + '%')) + (crowd ? ' ⚠' : '') + '</span>';
        h += '</div>';
      });
      h += '</div>';
    });
    const cdg = d.cftcDisaggCrowded || [];
    if (cdg.length) h += '<div style="margin-top:2px;padding:8px 12px;background:#fff3f3;border:1px solid #f7c1c1;border-radius:8px;font-size:12px;color:#a32d2d;">⚠ 拥挤警示: ' + cdg.join('；') + '</div>';
    // 数据驱动解读(规则生成, 非固定叙事): 拆行为逐条要点, 避免一大段密文
    const cds = d.cftcDisaggSummary || '';
    if (cds) {
      const cdsLines = cds.split(' · ').filter(function (s) { return s; });
      h += '<div style="margin-top:12px;padding:12px 14px;background:#f0f7fb;border:1px solid #cce3f0;border-radius:8px;font-size:12px;color:#2c3e50;line-height:1.7;"><b style="color:#185FA5;">数据解读：</b>'
        + cdsLines.map(function (s) { return '<div style="margin-top:3px;">· ' + s + '</div>'; }).join('')
        + '</div>';
    }
  } else {
    // 回退: legacy 投机净持仓 (非商业)
    const cf = d.cftc || [];
    if (!cf.length) {
      h += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;color:#6b7280;font-size:13px;">CFTC 数据暂缺 (每周五更新)</div>';
    } else {
      h += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;">';
      cf.forEach(function (r) {
        const long = r.dir === 'long';
        const col = long ? '#0f6e56' : '#a32d2d';
        const bg = long ? '#e6f6ee' : '#fcebeb';
        const crowded = r.crowding > 25;
        h += '<div style="background:' + bg + ';border:1px solid ' + col + ';border-radius:10px;padding:10px 12px;">'
          + '<div style="display:flex;justify-content:space-between;align-items:center;">'
          + '<span style="font-size:13px;font-weight:600;color:#1a1d29;">' + r.asset + '</span>'
          + (crowded ? '<span style="padding:2px 8px;border-radius:10px;background:#fff;color:#a32d2d;font-size:10px;font-weight:600;border:1px solid #f09595;">拥挤 ' + r.crowding + '%</span>' : '')
          + '</div>'
          + '<div style="font-size:11px;color:#6b7280;margin:2px 0 6px;">' + (r.note || '') + ' · ' + (r.date || '') + '</div>'
          + '<div style="font-size:18px;font-weight:600;color:' + col + ';">' + (r.net > 0 ? '+' : '') + Number(r.net).toLocaleString() + ' 手</div>'
          + '<div style="font-size:11px;color:#5f5e5a;margin-top:4px;">' + (long ? '净多头' : '净空头')
          + (r.chgLabel ? ' · <b style="color:' + (r.chgLabel.indexOf('增') >= 0 ? '#a32d2d' : '#0f6e56') + ';">' + r.chgLabel + '</b>'
                         : (r.chg != null ? ' · 周变化 ' + (r.chg > 0 ? '+' : '') + Number(r.chg).toLocaleString() : '')) + '</div>'
          + '<div style="height:5px;background:rgba(0,0,0,0.08);border-radius:3px;margin-top:6px;overflow:hidden;">'
          + '<div style="height:100%;width:' + Math.min(Math.abs(r.crowding) * 2, 100) + '%;background:' + col + ';border-radius:3px;"></div></div>'
          + '<div style="font-size:10px;color:#9ca3af;margin-top:2px;">单边度 ' + r.crowding + '% (OI)</div>'
          + '</div>';
      });
      h += '</div>';
      if (d.cftcCrowded && d.cftcCrowded.length) {
        h += '<div style="margin-top:10px;padding:8px 12px;background:#fff3f3;border:1px solid #f7c1c1;border-radius:8px;font-size:12px;color:#a32d2d;">⚠ 拥挤警示: ' + d.cftcCrowded.join('；') + '</div>';
      }
    }
  }

  // ===== 2. 期限溢价: 10Y 拆解 =====
  h += sectionH('期限溢价分解（为什么动）', '10Y 收益率 = 预期短端路径 + 期限溢价 · ACM 模型 · 判断"政策预期 vs 供给/财政"驱动');
  if (d.termPremium && d.termPremium.value != null) {
    const tp = d.termPremium;
    const tpCol = tp.signal === 'bearish' ? '#a32d2d' : (tp.signal === 'bullish' ? '#0f6e56' : '#854f0b');
    const _10y = (tp.expPath != null) ? (tp.expPath + tp.value) : null;
    const _pathPct = _10y ? (tp.expPath / _10y * 100) : 0;
    const _tpPct = _10y ? (tp.value / _10y * 100) : 0;
    h += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;">'
      + '<div style="margin-bottom:10px;">'
      + '<div style="display:flex;height:30px;border-radius:6px;overflow:hidden;font-size:12px;font-weight:600;color:#fff;">'
      + '<div style="width:' + _pathPct.toFixed(1) + '%;background:#185FA5;display:flex;align-items:center;justify-content:center;">预期路径 ' + (tp.expPath != null ? tp.expPath.toFixed(2) : '—') + '%</div>'
      + '<div style="width:' + _tpPct.toFixed(1) + '%;background:#a32d2d;display:flex;align-items:center;justify-content:center;">期限溢价 ' + tp.value.toFixed(2) + '%</div>'
      + '</div>'
      + '<div style="display:flex;justify-content:space-between;font-size:11px;color:#6b7280;margin-top:4px;">'
      + '<span>10Y 名义 ' + (_10y != null ? _10y.toFixed(2) : '—') + '%</span>'
      + '<span>来源: FRED THREEFYTP10 (ACM 模型)</span>'
      + '</div></div>'
      + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin-top:4px;">'
      + '<div style="background:#f7f8fa;border-radius:8px;padding:9px 11px;"><div style="font-size:11px;font-weight:600;color:#185FA5;margin-bottom:3px;">① 溢价怎么来</div><div style="font-size:11px;color:#374151;line-height:1.6;">ACM 模型把 10Y 拆成「未来短端利率预期」+「持有长债的额外补偿」。这 ' + tp.value.toFixed(2) + '% 是超出政策预期的那部分补偿。</div></div>'
      + '<div style="background:#fdf5f4;border-radius:8px;padding:9px 11px;"><div style="font-size:11px;font-weight:600;color:#a32d2d;margin-bottom:3px;">② 为什么偏高<span style="display:inline-block;background:#fff4e5;color:#9a5b00;border:1px solid #f0c98a;border-radius:4px;font-size:10px;padding:0 5px;margin-left:5px;font-weight:600;">模型假设</span></div><div style="font-size:11px;color:#374151;line-height:1.6;">平台判据 &gt;0.5% 即偏高(偏空信号)。长端上行由<b>供给/财政/久期风险</b><span style="display:inline-block;background:#fff4e5;color:#9a5b00;border:1px solid #f0c98a;border-radius:4px;font-size:10px;padding:0 5px;margin-left:3px;font-weight:600;">模型假设</span>驱动, 而非单纯降息预期, 美联储也压不住长端。此因果归因并非数据实证, 仅作分析框架假设。</div></div>'
      + '<div style="background:#fff8ec;border-radius:8px;padding:9px 11px;"><div style="font-size:11px;font-weight:600;color:#854f0b;margin-bottom:3px;">③ 留意什么</div><div style="font-size:11px;color:#374151;line-height:1.6;">危险阈值 <b>1.0%</b>(财政驱动强化); 数据截至 ' + (tp.date || '—') + ' 有滞后; 需与 CFTC 持仓、30Y-10Y 利差交叉验证才可靠。</div></div>'
      + '</div>'
      + '<div style="font-size:12px;color:#374151;line-height:1.7;margin-top:8px;"><b style="color:' + tpCol + ';">' + tp.text + '</b>' + (tp.modelAssumption ? ' <span style="display:inline-block;background:#fff4e5;color:#9a5b00;border:1px solid #f0c98a;border-radius:4px;font-size:10px;padding:0 5px;font-weight:600;">模型假设</span>' : '') + '</div>'
      + '</div>';
  }

  // ===== 3. SLOOS + NFCI 分项 =====
  h += sectionH('信贷领先指标（定价到什么程度）', 'SLOOS 银行信贷意愿 + NFCI 分项 — 压力藏在哪');
  h += '<div class="chart-row two-col">'
    + '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;">'
    + '<div style="font-size:13px;font-weight:600;color:#1a1d29;margin-bottom:4px;">SLOOS 银行信贷意愿</div>'
    + (d.sloos && d.sloos.value != null
        ? '<div style="font-size:12px;color:' + (d.sloos.signal === 'bearish' ? '#a32d2d' : (d.sloos.signal === 'bullish' ? '#0f6e56' : '#854f0b')) + ';line-height:1.7;">' + d.sloos.text + '</div>'
          + '<div style="font-size:11px;color:#9ca3af;margin-top:4px;">' + (d.sloos.date || '') + '</div>'
        : '<div style="font-size:12px;color:#6b7280;">数据暂缺 (季度发布)</div>')
    + '</div>'
    + '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;">'
    + '<div style="font-size:13px;font-weight:600;color:#1a1d29;margin-bottom:4px;">NFCI 分项（压力定位）</div>'
    + (d.nfciParts && d.nfciParts.length
        ? d.nfciParts.map(function (r) {
            const col = r.signal === 'bearish' ? '#a32d2d' : (r.signal === 'bullish' ? '#0f6e56' : '#854f0b');
            return '<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #f0f0f0;font-size:12px;">'
              + '<span style="color:#374151;">' + r.key + '</span>'
              + '<span style="font-weight:600;color:' + col + ';">' + (r.value > 0 ? '+' : '') + r.value + ' <span style="font-weight:400;color:#6b7280;">' + r.meaning + '</span></span></div>';
          }).join('')
        : '<div style="font-size:12px;color:#6b7280;">数据暂缺</div>')
    + '</div></div>';

  // ===== 4. 实体锚 =====
  h += sectionH('实体端锚', '家庭净资产 + 银行信贷 — 消费与信用创造的底层水位');
  h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">'
    + '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;">'
    + '<div style="font-size:11px;color:#6b7280;">家庭净资产 (财富效应 → 消费)</div>'
    + '<div style="font-size:20px;font-weight:600;color:#1a1d29;">$' + (d.householdNetWorth ? d.householdNetWorth.value : '—') + 'T</div>'
    + '<div style="font-size:11px;color:#9ca3af;">' + (d.householdNetWorth ? d.householdNetWorth.date : '') + '</div></div>'
    + '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;">'
    + '<div style="font-size:11px;color:#6b7280;">银行信贷总量 (信用创造)</div>'
    + '<div style="font-size:20px;font-weight:600;color:#1a1d29;">$' + (d.bankCredit ? d.bankCredit.value : '—') + 'T</div>'
    + '<div style="font-size:11px;color:#9ca3af;">' + (d.bankCredit ? d.bankCredit.date : '') + '</div></div>'
    + '</div>';

  // ===== 传导机制 =====
  if (d.transmissionMap) {
    h += sectionH('市场定位 → 资产传导机制', '谁在动 × 为什么动 × 到哪一步 × 压力点 → 各类资产 (速查)');
    h += _renderTransmissionMap(d.transmissionMap);
  }

  h += watchList(d.whatToWatch);
  c.innerHTML = h;
}

// ===== 交易机会雷达: 预期差扫描 + 全品类映射 =====
function renderTradeRadar(c) {
  const d = DATA.tradeRadar;
  if (!d) { c.innerHTML = '<div class="loading">交易雷达数据加载中...</div>'; return; }
  const GAP_TYPE = {
    policy:      { label: '政策路径差',   color: '#185fa5', bg: '#e6f1fb' },
    surprise:    { label: '数据预期差',   color: '#0f6e56', bg: '#e1f5ee' },
    divergence:  { label: '价格背离',     color: '#854f0b', bg: '#faeeda' },
    percentile:  { label: '分位极端',     color: '#a32d2d', bg: '#fcebeb' },
    transmission:{ label: '传导断裂',     color: '#993c1d', bg: '#faece7' }
  };
  const DIR = {
    long_gold: { t: '利多黄金', c: '#0f6e56' }, long_2y: { t: '利多短端利率', c: '#0f6e56' },
    short_2y:  { t: '利空短端', c: '#a32d2d' }, long_bond: { t: '利多长债', c: '#0f6e56' },
    short_vol: { t: '利空波动率', c: '#185fa5' }, short_hy: { t: '利空信用', c: '#a32d2d' },
    neutral:   { t: '双向待确认', c: '#5f5e5a' }
  };
  let h = '';

  h += '<div style="margin:6px 0 18px;padding:16px 20px;border-radius:12px;background:#f7f8fa;border:1px solid #d3d1c7;" title="' + (d.method || '') + '">'
    + '<div style="font-size:13px;font-weight:500;color:#2c2c2a;margin-bottom:6px;">扫描结果 · ' + (d.counts ? (d.counts.gaps + ' 个预期差 / ' + d.counts.trades + ' 个候选 / ' + d.counts.bets + ' 个独立赌注') : '') + '</div>'
    + '<div style="font-size:12px;color:#5f5e5a;line-height:1.7;">' + (d.summary || '') + '</div>'
    + '</div>';

  // ===== 唯一主线 (The One) — 决策漏斗输出 =====
  const theOne = d.theOne;
  if (theOne) {
    const tSideCls = theOne.side.indexOf('做空') >= 0 || theOne.side.indexOf('回避') >= 0 || theOne.side.indexOf('卖出') >= 0 ? '#a32d2d' : '#0f6e56';
    const tAsym = theOne.asymmetry || { score: 3 };
    h += '<div style="margin:0 0 14px;padding:16px 20px;border-radius:12px;background:#15131f;color:#fff;border:1px solid #3a2f6b;">'
      + '<div style="font-size:11px;color:#b9a8ff;letter-spacing:.5px;margin-bottom:6px;">唯一主线 · THE ONE (决策漏斗收敛) · 驱动主题: ' + (theOne.driver || '—') + '</div>'
      + '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px;">'
      + '<span style="font-size:16px;font-weight:600;">' + theOne.asset + '</span>'
      + '<span style="padding:2px 12px;border-radius:14px;font-size:12px;font-weight:600;background:' + tSideCls + '33;color:#fff;">' + theOne.side + '</span>'
      + '<span style="font-size:11px;color:#cfc7e6;">非对称性 ' + tAsym.score + '/5</span>'
      + '<span style="font-size:11px;color:#cfc7e6;">' + (theOne.confidence === 'high' ? '高置信' : '中置信') + '</span>'
      + '</div>'
      + '<div style="font-size:12px;line-height:1.7;color:#cfc7e6;">' + (theOne.bet || theOne.thesis || '') + '</div>'
      + '<div style="font-size:11px;color:#9ca3af;margin-top:8px;">入场催化剂: ' + theOne.trigger + '</div>'
      + '</div>';
    const sats = d.satellites || [];
    if (sats.length) {
      h += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;">'
        + sats.map(function (s) {
            const sc = s.side.indexOf('做空') >= 0 ? '#a32d2d' : '#0f6e56';
            return '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:8px 14px;font-size:12px;">卫星: <b style="color:#1a1d29;">' + s.asset + '</b> <span style="color:' + sc + ';">' + s.side + '</span> <span style="color:#9ca3af;">(' + (s.driver || '—') + ')</span></div>';
          }).join('')
        + '</div>';
    }
  }

  // ===== 证伪警报 =====
  const falerts = d.falsifyAlerts || [];
  if (falerts.length) {
    h += '<div style="margin:0 0 14px;padding:12px 16px;border-radius:10px;background:#fcebeb;border:1px solid #e24b4a;">'
      + '<div style="font-size:12px;font-weight:600;color:#a32d2d;margin-bottom:6px;">⚠ ' + falerts.length + ' 条证伪警报 — 假设已被数据证伪, 建议平仓</div>'
      + falerts.map(function (a) {
          return '<div style="font-size:12px;color:#791f1f;line-height:1.6;">· ' + a.trade + ': ' + a.desc + ' (当前 ' + a.current + ')</div>';
        }).join('')
      + '</div>';
  }

  // ===== 独立性审计 + 组合赌注 =====
  const ind = d.independence;
  if (ind) {
    const indCls = ind.effectiveBets < (d.trades || []).length ? '#a32d2d' : '#0f6e56';
    let indHtml = '<div style="margin:0 0 14px;padding:10px 16px;border-radius:10px;background:' + (ind.effectiveBets < (d.trades || []).length ? '#fcebeb' : '#e6f6ee') + ';border:1px solid ' + indCls + ';">'
      + '<div style="font-size:12px;font-weight:600;color:' + indCls + ';">独立性审计: ' + (d.counts ? d.counts.bets : '') + ' 个独立赌注 — ' + ind.note + '</div>';
    // 组合净暴露 (你整体在赌什么)
    const pe = ind.portfolioExposure || [];
    if (pe.length) {
      indHtml += '<div style="margin-top:8px;font-size:11px;font-weight:600;color:#5f5e5a;">你整个组合底层在赌: </div>'
        + '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:5px;">'
        + pe.map(function (p) {
            const isNeg = p.net < 0;
            const w = Math.min(Math.abs(p.net) / 4 * 100, 100);
            const col = isNeg ? '#a32d2d' : '#0f6e56';
            const dirTxt = isNeg ? '反向' : '';
            return '<div style="flex:1;min-width:120px;text-align:center;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:6px 4px;">'
              + '<div style="font-size:11px;color:#374151;">' + p.label + (dirTxt ? ' <span style="color:' + col + '">' + dirTxt + '</span>' : '') + '</div>'
              + '<div style="height:5px;background:#eef0f4;border-radius:3px;margin:4px 0;overflow:hidden;"><div style="height:100%;width:' + w + '%;background:' + col + ';border-radius:3px;"></div></div>'
              + '<div style="font-size:12px;font-weight:600;color:' + col + ';">' + (p.net > 0 ? '+' : '') + p.net + '</div></div>';
          }).join('')
        + '</div>';
    }
    // 跨候选重复表达警告
    const dup = ind.dupPairs || [];
    if (dup.length) {
      indHtml += '<div style="margin-top:8px;background:#fff3f3;border:1px solid #f7c1c1;border-radius:8px;padding:7px 10px;">'
        + dup.map(function (x) {
            return '<div style="font-size:11px;color:#a32d2d;line-height:1.6;">⚠ ' + x.a + ' ↔ ' + x.b + '：' + x.hint + '</div>';
          }).join('')
        + '</div>';
    }
    indHtml += '</div>';
    h += indHtml;
  }

  // ===== Tier A 价格隐含信号 =====
  const pi = d.priceImplied;
  if (pi) {
    const corrFmt = function (v) { return v == null ? '—' : v.toFixed(2); };
    h += '<div style="margin:0 0 14px;padding:12px 16px;border-radius:10px;background:#e6f1fb;border:1px solid #185fa5;">'
      + '<div style="font-size:12px;font-weight:600;color:#0c447c;margin-bottom:6px;">Tier A · 价格隐含信号（市场真金白银的表达，与基本面判断隔离）</div>'
      + '<div style="display:flex;gap:8px;flex-wrap:wrap;">'
      + '<span class="pi-chip" style="background:#fff;border:1px solid #b5d4f4;border-radius:14px;padding:3px 10px;font-size:11px;color:#0c447c;">金-实际利率 60日相关 ' + corrFmt(pi.goldRealCorr) + (pi.goldRealCorr != null && pi.goldRealCorr > -0.25 ? ' (脱钩)' : ' (锚定)') + '</span>'
      + '<span class="pi-chip" style="background:#fff;border:1px solid #b5d4f4;border-radius:14px;padding:3px 10px;font-size:11px;color:#0c447c;">股-债 60日相关 ' + corrFmt(pi.stockBondCorr) + (pi.stockBondCorr != null && pi.stockBondCorr > 0 ? ' (贴现率冲击)' : ' (增长/避险)') + '</span>'
      + '<span class="pi-chip" style="background:#fff;border:1px solid #b5d4f4;border-radius:14px;padding:3px 10px;font-size:11px;color:#0c447c;">金-美元相关 ' + corrFmt(pi.goldUsdCorr) + '</span>'
      + '<span class="pi-chip" style="background:#fff;border:1px solid #b5d4f4;border-radius:14px;padding:3px 10px;font-size:11px;color:#0c447c;">隐含-实现波动差 ' + (pi.vixImplRealGap == null ? '—' : pi.vixImplRealGap.toFixed(1) + 'pt') + (pi.vixImplRealGap != null && pi.vixImplRealGap > 3 ? ' (错价)' : ' (定价合理)') + '</span>'
      + '<span class="pi-chip" style="background:#fff;border:1px solid #b5d4f4;border-radius:14px;padding:3px 10px;font-size:11px;color:#0c447c;">曲线斜率 ' + pi.curveSlope + 'bp</span>'
      + '</div></div>';
  }

  // 预期差扫描器
  h += sectionH('预期差扫描器', '市场定价 − 基本面/模型判断 → 概率优势的来源');
  const gaps = d.expectationGaps || [];
  if (!gaps.length) {
    h += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;color:#6b7280;font-size:13px;">当前未扫描到显著预期差——市场定价与基本面大体一致, 低矛盾状态, 等待新的数据/事件打破平衡。</div>';
  } else {
    gaps.forEach(function (g) {
      const t = GAP_TYPE[g.type] || GAP_TYPE.transmission;
      const dr = DIR[g.direction] || DIR.neutral;
      const confBg = g.confidence === 'high' ? '#fde2e2' : (g.confidence === 'mid' ? '#fdf3e2' : '#e6f6ee');
      const confFg = g.confidence === 'high' ? '#c0392b' : (g.confidence === 'mid' ? '#b45309' : '#1d9e75');
      h += '<div style="background:#fff;border:1px solid #e5e7eb;border-left:4px solid ' + t.color + ';border-radius:10px;padding:12px 16px;margin-bottom:10px;">'
        + '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
        + '<span style="display:inline-block;padding:2px 9px;border-radius:14px;font-size:11px;font-weight:600;background:' + t.bg + ';color:' + t.color + ';">' + t.label + '</span>'
        + '<span style="font-size:13px;font-weight:600;color:#1a1d29;">' + g.title + '</span>'
        + '<span style="display:inline-block;padding:2px 9px;border-radius:14px;font-size:11px;font-weight:600;background:' + dr.c + '22;color:' + dr.c + ';">' + dr.t + '</span>'
        + '<span style="display:inline-block;padding:2px 9px;border-radius:14px;font-size:11px;font-weight:600;background:' + confBg + ';color:' + confFg + ';">' + (g.confidence === 'high' ? '高置信' : g.confidence === 'mid' ? '中置信' : '低置信') + '</span>'
        + '<span style="font-size:11px;color:#9ca3af;">[' + g.category + ']</span>'
        + '</div>'
        + '<div style="font-size:12px;color:#6b7280;line-height:1.7;margin-top:6px;" title="' + String(g.detail || '').replace(/"/g, '&quot;') + '">' + ((g.detail || '').length > 90 ? g.detail.slice(0, 90) + '…' : g.detail) + '</div>'
        + '</div>';
    });
  }

  // 全品类交易映射 (可折叠假设卡片: 摘要行 + 展开详情)
  h += sectionH('全品类交易映射', '每个候选 = 一个可下注的假设: 主观概率(证据平衡) + 非对称性 + 证伪退出 · 点击展开 · 不构成投资建议');
  const trades = d.trades || [];
  if (!trades.length) {
    h += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;color:#6b7280;font-size:13px;">当前无规则触发的交易候选。</div>';
  } else {
    trades.forEach(function (t) {
      const sideCls = t.side.indexOf('做空') >= 0 || t.side.indexOf('回避') >= 0 || t.side.indexOf('卖出') >= 0 ? '#a32d2d' : '#0f6e56';
      const confTxt = t.confidence === 'high' ? '高置信' : (t.confidence === 'mid' ? '中置信' : '低置信');
      const confBg = t.confidence === 'high' ? '#fde2e2' : (t.confidence === 'mid' ? '#fdf3e2' : '#e6f6ee');
      const confFg = t.confidence === 'high' ? '#c0392b' : (t.confidence === 'mid' ? '#b45309' : '#1d9e75');
      const asym = t.asymmetry || { score: 3, note: '' };
      const asymCls = asym.score >= 4 ? '#0f6e56' : (asym.score === 3 ? '#854f0b' : '#a32d2d');
      const asymBg = asym.score >= 4 ? '#e1f5ee' : (asym.score === 3 ? '#faeeda' : '#fcebeb');
      const asymLabel = asym.score >= 4 ? '凸性' : (asym.score === 3 ? '中性' : '⚠负凸');
      const falsifyRaw = t.falsify;
      const falsify = Array.isArray(falsifyRaw) ? falsifyRaw : (falsifyRaw ? [falsifyRaw] : []);
      const evFor = t.evidenceFor || [];
      const evAg = t.evidenceAgainst || [];
      // 摘要行 (默认显示)
      const srcTag = t.source === 'cftc_positioning' ? '<span style="margin-left:6px;padding:1px 8px;border-radius:10px;font-size:10px;font-weight:600;background:#eeedfe;color:#3c3489;">CFTC 定位</span>' : (t.source === 'ai_chain' ? '<span style="margin-left:6px;padding:1px 8px;border-radius:10px;font-size:10px;font-weight:600;background:#fbeaf0;color:#993556;">AI 链条</span>' : '');
      const mainTag = (theOne && t.asset === theOne.asset) ? '<span style="margin-left:6px;padding:1px 8px;border-radius:10px;font-size:10px;font-weight:600;background:#15131f;color:#b9a8ff;">⭐ 主线</span>' : '';
      const summaryHtml = '<span style="font-size:13px;font-weight:600;color:#1a1d29;">' + t.asset + '</span>' + mainTag + srcTag
        + '<span style="margin-left:8px;padding:1px 9px;border-radius:12px;font-size:11px;font-weight:600;background:' + sideCls + '22;color:' + sideCls + ';">' + t.side + '</span>'
        + '<span style="margin-left:6px;padding:1px 9px;border-radius:12px;font-size:11px;font-weight:600;background:' + asymBg + ';color:' + asymCls + ';">非对称 ' + asym.score + '/5 ' + asymLabel + '</span>'
        + '<span style="margin-left:6px;padding:1px 9px;border-radius:12px;font-size:11px;font-weight:600;background:' + confBg + ';color:' + confFg + ';">' + confTxt + '</span>';
      // 展开详情 (精简: bet 已含核心论点, 证据/反证/证伪各限前2条)
      const bodyHtml = '<div style="padding:10px 4px 2px;">'
        + (t.bet ? '<div style="font-size:12px;font-weight:600;color:#15131f;background:#f1eefc;border-left:3px solid #534ab7;border-radius:6px;padding:7px 10px;margin-bottom:8px;line-height:1.6;">底层赌注: ' + t.bet + '</div>' : '<div style="font-size:12px;color:#374151;line-height:1.7;margin-bottom:8px;">' + (t.thesis || '') + '</div>')
        + (asym.note ? '<div style="font-size:11px;color:' + asymCls + ';line-height:1.6;margin-bottom:8px;">非对称性解读: ' + asym.note + '</div>' : '')
        + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:8px;">'
        + '<div style="background:#e6f6ee;border-radius:8px;padding:8px 10px;"><div style="font-size:11px;font-weight:600;color:#0f6e56;margin-bottom:4px;">支持证据' + (evFor.length > 2 ? ' (前2)' : '') + '</div>'
        + (evFor.slice(0, 2).map(function (e) { return '<div style="font-size:11px;color:#0f6e56;line-height:1.5;">· ' + e + '</div>'; }).join('') || '<div style="font-size:11px;color:#0f6e56;">—</div>')
        + '</div>'
        + '<div style="background:#fcebeb;border-radius:8px;padding:8px 10px;"><div style="font-size:11px;font-weight:600;color:#a32d2d;margin-bottom:4px;">反对证据' + (evAg.length > 2 ? ' (前2)' : '') + '</div>'
        + (evAg.slice(0, 2).map(function (e) { return '<div style="font-size:11px;color:#a32d2d;line-height:1.5;">· ' + e + '</div>'; }).join('') || '<div style="font-size:11px;color:#a32d2d;">—</div>')
        + '</div></div>'
        + '<div style="background:#fff3f3;border:1px solid #f7c1c1;border-radius:8px;padding:8px 10px;margin-bottom:8px;">'
        + '<div style="font-size:11px;font-weight:600;color:#a32d2d;margin-bottom:4px;">证伪退出（触发即假设错误 → 平仓）' + (falsify.length > 2 ? ' (前2)' : '') + '</div>'
        + (falsify.slice(0, 2).map(function (f) { return '<div style="font-size:11px;color:#a32d2d;line-height:1.5;">· ' + f + '</div>'; }).join('') || '<div style="font-size:11px;color:#a32d2d;">—</div>')
        + '</div>'
        + '<div style="font-size:11px;color:#854f0b;">入场催化剂: ' + t.trigger + '</div>'
        + '</div>';
      h += '<details class="trade-details" style="background:#fff;border:1px solid #e5e7eb;border-left:4px solid ' + sideCls + ';border-radius:10px;padding:10px 14px;margin-bottom:10px;">'
        + '<summary style="cursor:pointer;list-style:none;outline:none;">'
        + '<span style="font-size:11px;color:#9ca3af;margin-right:6px;">▸</span>' + summaryHtml
        + '</summary>' + bodyHtml + '</details>';
    });
  }
  h += '<div style="font-size:11px;color:#9ca3af;line-height:1.6;margin-top:8px;">数据截至 ' + (d.asOf || '') + ' · 预期差是概率优势而非确定信号: 单次数据是噪音, 连续同向 surprise 才是系统性定价错误; 分歧大时等催化剂, 赔率好时再下注。</div>';

  // ===== 催化剂日历 =====
  const cats = d.catalystCalendar || [];
  if (cats.length) {
    h += sectionH('催化剂日历', '未来数据/FOMC 发布 → 收敛或扩大哪个预期差');
    h += '<div class="table-wrap"><table class="data-table"><thead><tr><th>日期</th><th>事件</th><th>影响预期差</th><th>方向含义</th></tr></thead><tbody>';
    cats.forEach(function (c) {
      h += '<tr>'
        + '<td style="white-space:nowrap;font-weight:600;color:#185fa5;">' + c.date + (c.importance === 'high' ? ' <span style="color:#e24b4a;font-size:11px;">★</span>' : '') + '</td>'
        + '<td style="font-weight:500;color:#1a1d29;">' + c.event + '</td>'
        + '<td style="font-size:12px;color:#854f0b;">' + (c.gapTitle ? c.gapTitle : c.gapId) + '</td>'
        + '<td style="font-size:12px;color:#374151;line-height:1.6;">' + c.effect + '</td>'
        + '</tr>';
    });
    h += '</tbody></table></div>';
  }

  // ===== AI 链条估值预期差 =====
  const av = d.aiValuation;
  if (av && av.stats && av.stats.count) {
    h += sectionH('AI 链条估值预期差', '板块整体估值 vs 盈利增速 · PEG 高低估扫描');
    h += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 16px;margin-bottom:12px;font-size:12px;color:#374151;line-height:1.7;">'
      + av.summary + '</div>';
    h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">';
    const valCard = function (title, list, color, isOver) {
      if (!list || !list.length) return '<div><div style="font-size:12px;font-weight:600;color:' + color + ';margin-bottom:6px;">' + title + ' · 无</div></div>';
      let rows = list.map(function (x) {
        const peg = x.peg != null ? x.peg.toFixed(1) : '—';
        const fpe = x.fwdPe != null ? x.fwdPe.toFixed(0) + 'x' : '—';
        const rg = x.revGrowth != null ? x.revGrowth + '%' : '—';
        return '<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px;background:#fafafa;border-radius:8px;margin-bottom:6px;border-left:3px solid ' + color + ';">'
          + '<div><span style="font-size:13px;font-weight:600;color:#1a1d29;">' + x.name + '</span>'
          + '<span style="font-size:11px;color:#9ca3af;"> ' + x.ticker + ' · ' + x.layer + '</span></div>'
          + '<div style="font-size:11px;color:#6b7280;white-space:nowrap;">PEG ' + peg + ' · FwdPE ' + fpe + ' · 增速 ' + rg + '</div></div>';
      }).join('');
      return '<div><div style="font-size:12px;font-weight:600;color:' + color + ';margin-bottom:6px;">' + title + ' (' + list.length + ')</div>' + rows + '</div>';
    };
    h += valCard('⚠ 高估候选', av.overvalued, '#a32d2d', true);
    h += valCard('✓ 低估候选', av.undervalued, '#0f6e56', false);
    h += '</div>';
    // 注: AI 交易机会已合并进上方"全品类交易映射" (带 AI 链条 tag), 不再重复渲染
  }

  // ===== 交易日志 (localStorage) =====
  h += sectionH('交易日志与复盘', '记录假设 → 主观概率 → 证伪 → 复盘 (本地存储)');
  h += '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin-bottom:12px;">'
    + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">'
    + '<input id="tlAsset" placeholder="资产 (如 黄金/2Y/纳指)" style="flex:1;min-width:120px;padding:7px 10px;border:1px solid #d3d1c7;border-radius:8px;font-size:12px;">'
    + '<input id="tlSide" placeholder="方向 (多/空)" style="flex:0 0 70px;padding:7px 10px;border:1px solid #d3d1c7;border-radius:8px;font-size:12px;">'
    + '<input id="tlPrice" placeholder="入场价" style="flex:0 0 90px;padding:7px 10px;border:1px solid #d3d1c7;border-radius:8px;font-size:12px;">'
    + '<input id="tlProb" placeholder="主观概率%" style="flex:0 0 90px;padding:7px 10px;border:1px solid #d3d1c7;border-radius:8px;font-size:12px;">'
    + '<input id="tlNote" placeholder="假设/依据 (哪个预期差)" style="flex:1;min-width:150px;padding:7px 10px;border:1px solid #d3d1c7;border-radius:8px;font-size:12px;">'
    + '<button onclick="_tlAdd()" style="padding:7px 14px;background:#4361ee;color:#fff;border:none;border-radius:8px;font-size:12px;cursor:pointer;">记录</button>'
    + '<button onclick="_tlClear()" style="padding:7px 14px;background:#f3f4f6;color:#6b7280;border:none;border-radius:8px;font-size:12px;cursor:pointer;">清空</button>'
    + '</div>'
    + '<div style="font-size:11px;color:#9ca3af;margin-top:6px;">记录时写下假设与主观概率；行情发展后点击 <b>✓证伪</b> 或 <b>✓兑现</b> 复盘——兑现率是检验你宏观判断能力的最好标尺。</div>'
    + '<div id="tlList" style="margin-top:10px;"></div>'
    + '</div>';

  c.innerHTML = h;
  _tlRender();
}

// 交易日志: localStorage 存储 (假设 + 主观概率 + 证伪/兑现标记)
function _tlGet() {
  try { return JSON.parse(localStorage.getItem('umo_trade_log') || '[]'); } catch (e) { return []; }
}
function _tlSave(list) {
  try { localStorage.setItem('umo_trade_log', JSON.stringify(list)); } catch (e) {}
}
function _tlAdd() {
  const a = document.getElementById('tlAsset'), s = document.getElementById('tlSide'),
        p = document.getElementById('tlPrice'), pr = document.getElementById('tlProb'),
        n = document.getElementById('tlNote');
  const asset = (a && a.value || '').trim(), side = (s && s.value || '').trim(),
        price = (p && p.value || '').trim(), prob = (pr && pr.value || '').trim(),
        note = (n && n.value || '').trim();
  if (!asset) return;
  const list = _tlGet();
  list.push({ asset: asset, side: side, price: price, prob: prob, note: note,
              date: new Date().toISOString().slice(0, 10), verdict: null });
  _tlSave(list);
  if (a) a.value = ''; if (s) s.value = ''; if (p) p.value = ''; if (pr) pr.value = ''; if (n) n.value = '';
  _tlRender();
}
function _tlClear() {
  if (!confirm('清空全部交易日志？')) return;
  _tlSave([]);
  _tlRender();
}
function _tlVerdict(idx, v) {
  const list = _tlGet();
  if (!list[idx]) return;
  list[idx].verdict = v;
  _tlSave(list);
  _tlRender();
}
function _tlRender() {
  const el = document.getElementById('tlList');
  if (!el) return;
  const list = _tlGet();
  if (!list.length) {
    el.innerHTML = '<div style="font-size:12px;color:#9ca3af;">暂无记录。记录一笔"假设 + 主观概率", 之后用 ✓兑现 / ✗证伪 复盘, 积累你的宏观判断胜率。</div>';
    return;
  }
  const wins = list.filter(function (t) { return t.verdict === 'hit'; }).length;
  const fails = list.filter(function (t) { return t.verdict === 'miss'; }).length;
  const judged = wins + fails;
  const rateTxt = judged ? ('  ·  兑现 ' + wins + '/' + judged + ' (' + Math.round(wins / judged * 100) + '%)') : '';
  el.innerHTML = '<div style="font-size:11px;color:#6b7280;margin-bottom:8px;">共 ' + list.length + ' 笔' + rateTxt + '</div>'
    + list.map(function (t, i) {
      const sideCls = t.side.indexOf('空') >= 0 ? '#a32d2d' : '#0f6e56';
      const vCls = t.verdict === 'hit' ? '#0f6e56' : (t.verdict === 'miss' ? '#a32d2d' : '#6b7280');
      const vTxt = t.verdict === 'hit' ? '✓ 兑现' : (t.verdict === 'miss' ? '✗ 证伪' : '待定');
      return '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding:7px 10px;background:#fafafa;border-radius:8px;margin-bottom:6px;border-left:3px solid ' + sideCls + ';">'
        + '<div style="flex:1;"><span style="font-size:13px;font-weight:600;color:#1a1d29;">' + t.asset + '</span>'
        + (t.side ? ' <span style="font-size:11px;font-weight:600;color:' + sideCls + ';">' + t.side + '</span>' : '')
        + (t.price ? ' <span style="font-size:11px;color:#6b7280;">入场 ' + t.price + '</span>' : '')
        + (t.prob ? ' <span style="font-size:11px;color:#185fa5;">P=' + t.prob + '%</span>' : '')
        + (t.note ? ' <span style="font-size:11px;color:#854f0b;">' + t.note + '</span>' : '')
        + '</div>'
        + '<div style="white-space:nowrap;display:flex;align-items:center;gap:6px;">'
        + '<span style="font-size:11px;font-weight:600;color:' + vCls + ';">' + vTxt + '</span>'
        + (t.verdict === null ? '<button onclick="_tlVerdict(' + i + ',\'hit\')" style="border:none;background:#e6f6ee;color:#0f6e56;border-radius:6px;padding:2px 7px;font-size:11px;cursor:pointer;">兑现</button>'
           + '<button onclick="_tlVerdict(' + i + ',\'miss\')" style="border:none;background:#fcebeb;color:#a32d2d;border-radius:6px;padding:2px 7px;font-size:11px;cursor:pointer;">证伪</button>' : '')
        + '<span style="font-size:11px;color:#9ca3af;">' + t.date + '</span>'
        + '<button onclick="_tlDel(' + i + ')" style="border:none;background:none;color:#a32d2d;cursor:pointer;font-size:11px;">✕</button>'
        + '</div></div>';
    }).join('');
}
function _tlDel(idx) {
  const list = _tlGet();
  list.splice(idx, 1);
  _tlSave(list);
  _tlRender();
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
