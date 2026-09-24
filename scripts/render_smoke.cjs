/* ============================================================
 * render_smoke.cjs — 无头渲染冒烟测试
 * 在 Node vm 中用 DOM/Chart 桩加载 data.js + app.js，
 * 依次执行 7 个板块的渲染函数，捕获运行时错误并扫描
 * 输出 HTML 中的 NaN / undefined / null 残留。
 * 用法: node scripts/render_smoke.cjs   (退出码 0 = 通过)
 * ============================================================ */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');

/* ---------- DOM 桩 ---------- */
let elCount = 0;

class ClassList {
  constructor() { this._set = new Set(); }
  add(...c) { c.forEach(x => this._set.add(x)); }
  remove(...c) { c.forEach(x => this._set.delete(x)); }
  toggle(c, force) {
    const want = force === undefined ? !this._set.has(c) : !!force;
    want ? this._set.add(c) : this._set.delete(c);
    return want;
  }
  contains(c) { return this._set.has(c); }
}

class El {
  constructor(tag) {
    this._id = ++elCount;
    this.tagName = (tag || 'div').toUpperCase();
    this.children = [];
    this.classList = new ClassList();
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this._innerHTML = '';
    this.textContent = '';
    this.className = '';
    this._parent = null;
    this._qsCache = {};
    this._listeners = {};
    this.value = '';
    this.checked = false;
  }
  get parentElement() {
    if (!this._parent) this._parent = new El('div'); // 自动虚化父节点(浏览器恒存在)
    return this._parent;
  }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(v) {
    this._innerHTML = String(v);
    if (this.onInnerHTML) this.onInnerHTML(this._innerHTML);
  }
  appendChild(c) { this.children.push(c); c._parent = this; return c; }
  insertAdjacentHTML(_pos, html) { this._innerHTML += String(html); if (this.onInnerHTML) this.onInnerHTML(this._innerHTML); }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k]; }
  addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); }
  removeEventListener() {}
  querySelector(sel) {
    if (!this._qsCache[sel]) this._qsCache[sel] = new El('span');
    return this._qsCache[sel];
  }
  querySelectorAll() { return []; }
  closest() { return this.parentElement; }
  getContext() { return { canvas: this }; }
  getBoundingClientRect() { return { width: 800, height: 400, top: 0, left: 0 }; }
  focus() {} blur() {} click() {}
}

/* ---------- document / Chart 桩 ---------- */
const SECTIONS = ['assets', 'rates', 'fed', 'liquidity', 'economy', 'credit', 'volatility', 'recession', 'risk',
                  'crypto', 'signal', 'ai', 'tradeRadar', 'positioning'];
const idRegistry = {};
const navItems = SECTIONS.map(s => { const e = new El('a'); e.dataset.section = s; e.classList.add('nav-item'); return e; });
let domReadyCb = null;

const documentStub = {
  getElementById(id) {
    if (!idRegistry[id]) { idRegistry[id] = new El('div'); idRegistry[id].attributes.id = id; }
    return idRegistry[id];
  },
  createElement(tag) { return new El(tag); },
  querySelectorAll(sel) {
    if (sel === '.nav-item') return navItems;
    return [];
  },
  querySelector() { return new El('div'); },
  addEventListener(ev, fn) { if (ev === 'DOMContentLoaded') domReadyCb = fn; },
  body: new El('body'),
  documentElement: new El('html')
};

const chartInstances = [];
class ChartStub {
  constructor(canvas, config) {
    this.canvas = canvas; this.config = config; this.destroyed = false;
    chartInstances.push(this);
  }
  destroy() { this.destroyed = true; }
  update() {}
  resize() {}
}

/* ---------- vm 沙箱 ---------- */
const sandbox = {
  document: documentStub,
  Chart: ChartStub,
  window: {},
  console,
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Math, JSON, Object, Array, Number, String, Boolean, RegExp, Error, Map, Set, Promise, Intl,
  isNaN, isFinite, parseFloat, parseInt
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

function load(file) {
  const code = fs.readFileSync(file, 'utf8');
  vm.runInContext(code, sandbox, { filename: file });
}

/* ---------- 执行 ---------- */
const results = [];
let failures = 0;

/* 产物冲突标记守卫
 * 背景: 2026-09-24 rebase origin/main 时 data.js / index.html 冲突, gen_datajs.py 只对
 *   index.html 做版本号正则替换、不重写整份文件, 于是冲突标记被原样留在产物里并提交。
 *   冲突标记不会让渲染报错, 只会让页面静默坏掉 —— 必须在这里 fail fast。 */
try {
  const dirty = [];
  for (const f of ['index.html', 'data.js', 'app.js', 'styles.css',
                   'scripts/ai_chain.json', 'scripts/ai_scissors.json']) {
    const p = path.join(ROOT, f);
    if (!fs.existsSync(p)) continue;
    const txt = fs.readFileSync(p, 'utf8');
    const hit = (txt.match(/^(<{7}|={7}|>{7})/gm) || []).length;
    if (hit) dirty.push(f + '(' + hit + ' 处)');
  }
  if (dirty.length) throw new Error('文件残留 git 冲突标记: ' + dirty.join(', '));
  results.push(['产物冲突标记扫描', 'OK']);
} catch (e) {
  results.push(['产物冲突标记扫描', 'FAIL: ' + e.message]);
  failures++;
}

try {
  load(path.join(ROOT, 'data.js'));
  results.push(['加载 data.js', 'OK']);
} catch (e) {
  results.push(['加载 data.js', 'FAIL: ' + e.message]);
  report(1);
}
try {
  load(path.join(ROOT, 'app.js'));
  results.push(['加载 app.js', 'OK']);
} catch (e) {
  results.push(['加载 app.js', 'FAIL: ' + e.message]);
  report(1);
}

/* 扫描 HTML 输出中的脏数据 */
/* 注意: 这里对 null / undefined 做的是「裸词」匹配, 强度刻意保留 —— 目的是宁可误报,
 * 也不放过任何一个「未渲染值漏进 DOM」。代价是 **策展正文 (macro_signal.json 等) 里
 * 不得出现裸的 null / undefined / NaN 字样**, 否则会以正确的输出触发失败。
 * 描述「无激活情景」请写字面中文 (如「未达成」), 与前端 activeScenario 为空时的展示一致。
 * 2026-09-24: 曾因 scenarios[1].next 写「回落为 null(四条情景无一全命中)」误报过一次。 */
const BAD = [/>\s*NaN\s*</, /NaN\s*(bp|%|pt|\$)/, /undefined/, /[^a-zA-Z]null[^a-zA-Z]/, />\s*-\s*</];
function scanHtml(section, html) {
  const hits = [];
  for (const re of BAD) {
    // 必须用全局匹配计数: String.match(非全局) 只回首个匹配,
    // 曾因此让 6 处同类问题在日志里只显示成 1 处, 多花了一轮排查。
    const g = new RegExp(re.source, re.flags.indexOf('g') >= 0 ? re.flags : re.flags + 'g');
    const all = html.match(g);
    if (!all) continue;
    const i = html.search(re);
    const ctx = html.slice(Math.max(0, i - 50), i + all[0].length + 50).replace(/\s+/g, ' ');
    hits.push('"' + all[0].trim() + '" ×' + all.length + ' 处 · 位置 ' + i + ' · …' + ctx + '…');
  }
  return hits;
}

/* 触发 DOMContentLoaded(渲染 assets 首屏) */
const contentEl = documentStub.getElementById('content');
let currentHtml = '';
contentEl.onInnerHTML = (h) => { currentHtml = h; };

try {
  if (!domReadyCb) throw new Error('DOMContentLoaded 回调未注册');
  domReadyCb();
  results.push(['DOMContentLoaded 初始化', 'OK']);
} catch (e) {
  results.push(['DOMContentLoaded 初始化', 'FAIL: ' + (e.stack || e.message).split('\n').slice(0, 3).join(' | ')]);
  failures++;
}

/* 逐板块渲染 */
for (const sec of SECTIONS) {
  const chartsBefore = chartInstances.length;
  try {
    sandbox.switchSection(sec);
    const len = currentHtml.length;
    const dirty = scanHtml(sec, currentHtml);
    const nCharts = chartInstances.length - chartsBefore;
    if (len < 500) throw new Error('内容过短 (' + len + ' 字符),疑似渲染不完整');
    if (dirty.length) throw new Error('HTML 含脏数据: ' + dirty.join(', '));
    results.push(['渲染 ' + sec, 'OK (' + len + ' 字符, ' + nCharts + ' 图表)']);
  } catch (e) {
    results.push(['渲染 ' + sec, 'FAIL: ' + (e.stack || e.message).split('\n').slice(0, 3).join(' | ')]);
    failures++;
  }
}

/* 图表配置有效性:每个 Chart 都应有 type+data */
let badCharts = 0;
for (const c of chartInstances) {
  if (!c.config || !c.config.type || !c.config.data) badCharts++;
}
results.push(['图表配置完整性 (' + chartInstances.length + ' 个)', badCharts === 0 ? 'OK' : 'FAIL: ' + badCharts + ' 个配置不完整']);
if (badCharts) failures++;

/* 数值合理性: trendData 中 unit='%' 的变化幅度不得超过 ±300% (防止"点位差冒充百分比"类错误) */
const D = vm.runInContext('DATA', sandbox);
const crazy = [];
for (const sec of SECTIONS) {
  const td = (D[sec] || {}).trendData || [];
  for (const t of td) {
    if (t.unit !== '%') continue;
    for (const k of ['d', 'w', 'm', 'h6']) {
      const v = (t.changes || {})[k];
      if (typeof v === 'number' && Math.abs(v) > 300) crazy.push(sec + '.' + t.name + '.' + k + '=' + v + '%');
    }
  }
}
results.push(['数值合理性(%变化≤300)', crazy.length === 0 ? 'OK' : 'FAIL: ' + crazy.join(', ')]);
if (crazy.length) failures++;

/* 数据要点抽验(真实数据锚点) — const 声明不挂到全局对象,须在 vm 内取值 */
const anchors = [];
try {
  anchors.push(['meta.lastUpdated', D.meta.lastUpdated]);
  const tenY = (D.rates.metrics || []).find(m => /10年|10Y/i.test(m.name || ''));
  if (tenY) anchors.push(['10Y美债', tenY.value]);
  anchors.push(['板块数', Object.keys(D).filter(k => SECTIONS.includes(k)).length]);
  results.push(['数据锚点: ' + anchors.map(a => a[0] + '=' + a[1]).join(' | '), 'OK']);
} catch (e) {
  results.push(['数据锚点抽验', 'FAIL: ' + e.message]);
  failures++;
}

report();

function report(forceExit) {
  console.log('\n================ 渲染冒烟测试 ================');
  for (const [name, res] of results) console.log((res.startsWith('OK') ? '  [PASS] ' : '  [FAIL] ') + name + (res === 'OK' ? '' : ' — ' + res.replace(/^OK ?/, '')));
  console.log('============================================');
  console.log(failures === 0 ? '结果: 全部通过' : '结果: ' + failures + ' 项失败');
  process.exit(forceExit !== undefined ? forceExit : (failures === 0 ? 0 : 1));
}
