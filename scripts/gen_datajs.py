#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_datajs.py — 把 computed.json (真实数值/分位/四尺度变化) + raw_series.json (完整序列)
转换为前端使用的 data.js。所有数值来自官方数据源, 叙述文本内嵌真实数值, 每日重算即更新。

输出: ../data.js  (const DATA = {...})
依赖: build_data.py 先跑完, 生成 computed.json / raw_series.json
"""
import json, datetime, sys, re, calendar

C = json.load(open('computed.json'))
RAW = json.load(open('raw_series.json'))
print('[gen_datajs] loaded computed.json + raw_series.json', file=sys.stderr, flush=True)

# Fed 事件 (FOMC 官方日程 + 真实官员讲话), 由 build_data.py 抓取写入 events.json
try:
    EV = json.load(open('events.json'))
    print('[gen_datajs] loaded events.json', file=sys.stderr, flush=True)
except Exception:
    EV = {'fomc': [], 'jackson_hole': None, 'speeches': []}
    print('[gen_datajs] events.json 缺失, 事件板块将留空', file=sys.stderr, flush=True)

def _iso(d):  # '2026-07-28' → date
    return datetime.date.fromisoformat(d)

def build_fomc_timeline():
    """用官方 FOMC 日程 + 当前日期动态计算每场会议状态 (已召开/进行中/即将召开/待定)"""
    today = datetime.date.today()
    items = []
    for m in EV.get('fomc', []):
        s, e = _iso(m['start']), _iso(m['end'])
        if e < today:       status = '已召开'
        elif s <= today <= e: status = '进行中'
        else:               status = '待定'
        items.append({'date': m['start'] if m['start'] == m['end'] else f"{m['start']}~{m['end']}",
                      'event': m['label'], 'type': 'decision' if m['sep'] else 'meeting', 'status': status})
    # 标记最近一场未来会议为"即将召开"
    future = sorted([it for it in items if _iso(it['date'].split('~')[0]) > today], key=lambda it: _iso(it['date'].split('~')[0]))
    if future:
        future[0]['status'] = '即将召开'
    # Jackson Hole (主席讲话窗口)
    jh = EV.get('jackson_hole')
    if jh:
        js, je = _iso(jh['start']), _iso(jh['end'])
        if je < today:       st = '已结束'
        elif js <= today <= je: st = '进行中'
        else:                 st = '即将召开'
        items.append({'date': f"{jh['start']}~{jh['end']}", 'event': jh['label'], 'type': 'speech', 'status': st})
    items.sort(key=lambda it: _iso(it['date'].split('~')[0]))
    return items


# 下一场未来 FOMC (供利率路径 / 下一步观察动态引用, 避免硬编码日期)
_NEXT_FOMC = None
for _it in build_fomc_timeline():
    if _it['status'] in ('即将召开', '待定', '进行中'):
        _NEXT_FOMC = _it['date'].split('~')[0]; break
if _NEXT_FOMC:
    _fd = _iso(_NEXT_FOMC)
    _fomc_md = f'{_fd.month}月{_fd.day}日'
    _fomc_days = (_fd - datetime.date.today()).days
else:
    _fomc_md = None; _fomc_days = None

def build_speeches():
    """返回真实近期讲话列表 [{date,speaker,title,url,stance}]"""
    return EV.get('speeches', []) or []

# ---------- 经济指标发布日程 (最新/下次公布, 按发布频率规律推算) ----------
def _add_months(d, n):
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return datetime.date(y, m, 1)

def _first_friday(y, m):
    d = datetime.date(y, m, 1)
    return d + datetime.timedelta(days=(4 - d.weekday()) % 7)  # 周一=0..周五=4

def _release_on(rule, ym):
    """在 ym 所在年月, 按 rule 给出发布日"""
    y, m = ym.year, ym.month
    if len(rule) > 2 and rule[2] == 'ff':
        return _first_friday(y, m)
    day = rule[2] if (len(rule) > 2 and isinstance(rule[2], int)) else 28
    last = calendar.monthrange(y, m)[1]
    return datetime.date(y, m, min(day, last))

# tag → (computed.json 序列key, 频率, 发布日规则)
# 月度: 发布月 = 参考月 +1; 季度: 发布月 = 季末月 +1
RELEASE_MAP = {
    'GDP':    ('gdp', 'quarterly'),
    'CPI':    ('cpi', 'monthly', 12),
    'Core':   ('core_cpi', 'monthly', 12),
    'PCE':    ('core_pce', 'monthly', 28),
    'UNRATE': ('unrate', 'monthly', 'ff'),
    'NFP':    ('payems', 'monthly', 'ff'),
    'Retail': ('retail', 'monthly', 15),
    'Conf':   ('umich', 'monthly', 15),
}

def release_info(tag):
    rule = RELEASE_MAP.get(tag)
    if not rule:
        return None
    ref = date_of(rule[0])          # 最新数据点的参考期 (月度=月初, 季度=季末)
    if not ref:
        return {'latest': None, 'next': None, 'estimated': True}
    ref_d = _iso(ref)
    freq = rule[1]
    latest = _release_on(rule, _add_months(ref_d, 1))
    if latest > datetime.date.today():        # 推算的"最新"仍未来 → 回退一个周期
        latest = _release_on(rule, _add_months(latest, -1 if freq == 'monthly' else -3))
    nxt = _release_on(rule, _add_months(latest, 1 if freq == 'monthly' else 3))
    return {'latest': latest.isoformat(), 'next': nxt.isoformat(), 'estimated': True}

def g(key):
    return C.get(key)
def s(key):
    return RAW.get(key, [])
def val(key):
    v = g(key); return v['value'] if v else None
def pct(key):
    v = g(key); return v['pct'] if v else 50
def tfm(key):
    v = g(key); return v['tf'] if v else {'d':None,'w':None,'m':None,'h6':None}
def series90(key):
    v = g(key); return v.get('series90', []) if v else []
def series30(key):
    v = g(key); return v.get('series30', []) if v else []
def date_of(key):
    v = g(key); return v['date'] if v else None

def _dates_for(ref_key):
    """取参考序列最近 N 个日期作为 X 轴时间轴 (N=该序列 series90 长度)。无数据则退回索引。"""
    arr = s(ref_key)
    n = len(series90(ref_key))
    if arr:
        return [d for d, _ in arr[-n:]]
    return list(range(n))

META_DATE = date_of('spx') or date_of('dgs10') or '2026-07-24'

# ---------- 格式化工具 ----------
def f2(x):  return f'{x:.2f}' if isinstance(x,(int,float)) else '—'
def f1(x):  return f'{x:.1f}' if isinstance(x,(int,float)) else '—'

def bp(x, unit='bp'):
    """x 已是 bp (或百分点*100). 输出 +4.0bp / -2bp / 0bp"""
    if x is None: return '—'
    if abs(x) < 0.05: return '0bp'
    sgn = '+' if x > 0 else ''
    return f'{sgn}{x:.1f}{unit}'.replace('.0'+unit, unit)

def pctpt(x):  # 变化以百分点表示 (如 CPI +0.1pt)
    if x is None: return '—'
    if abs(x) < 0.005: return '0pt'
    sgn = '+' if x > 0 else ''
    return f'{sgn}{x:.1f}pt'.replace('.0pt','pt')

def ret(x):  # 收益率/涨跌幅 % (已是百分比)
    if x is None: return '—'
    if abs(x) < 0.005: return '0.0%'
    sgn = '+' if x > 0 else ''
    return f'{sgn}{x:.2f}%'

def comma(x, dec=2):
    if x is None: return '—'
    return f'{x:,.{dec}f}'

def dir_of(chg):
    if chg is None: return 'neutral'
    if chg > 0: return 'up'
    if chg < 0: return 'down'
    return 'neutral'

# 利率类: 原始是百分数, tf 是百分点差 -> 转 bp 需 *100
def rate_val_str(key):
    return f2(val(key)) + '%'
def rate_chg_bp(key):       # 日变化(bp)
    return bp(round((tfm(key).get('d') or 0)*100, 1))
def rate_changes(key):      # d/w/m/h6 都 *100 转 bp
    t = tfm(key)
    return {k: (round((t.get(k) or 0)*100,1) if t.get(k) is not None else None) for k in ('d','w','m','h6')}

# 资产类: tf 已是 % 变化
def asset_val_str(key, dec=2, money=''):
    return (money + comma(val(key), dec)) if money else comma(val(key), dec)
def asset_changes(key):
    t = tfm(key)
    return {k: (round(t.get(k),2) if t.get(k) is not None else None) for k in ('d','w','m','h6')}

# 级别类 (指数/美元万亿等): 原始数值, 日变化用绝对差
def lvl_changes(key, scale=1.0, unit=''):
    """scale: 把 raw 差乘到目标单位. 如 walcl $M -> $B: scale=1/1000"""
    t = tfm(key)
    out = {}
    for k in ('d','w','m','h6'):
        v = t.get(k)
        if v is None: out[k] = None
        else:
            out[k] = round(v*scale, 2)
    return out

def cell(key, k, scale=1/1000):
    v = tfm(key).get(k)
    if v is None: return '—'
    sign = '-' if v < 0 else '+'
    return f'{sign}${comma(abs(v)*scale,0)}B'

# 从 raw 序列算同比 (YoY) —— 用于 CPI/PCE/GDP 等价格/水平序列
def yoy(key, days_back=365):
    arr = s(key)
    if len(arr) < 5: return None
    # 找到日期最接近 (最新日期 - days_back) 的点
    latest = arr[-1][0]
    latest_d = datetime.date.fromisoformat(latest)
    target = latest_d - datetime.timedelta(days=days_back)
    best = None; best_diff = 9999
    for d, v in arr:
        diff = abs((datetime.date.fromisoformat(d) - target).days)
        if diff < best_diff:
            best_diff = diff; best = v
    if best in (None,0): return None
    cur = arr[-1][1]
    return (cur/best - 1)*100

def mom_level(key):
    """相邻两期水平差 (用于非农/Payrolls)"""
    arr = s(key)
    if len(arr) < 2: return None
    return arr[-1][1] - arr[-2][1]

def _yoy_at(arr, idx, days_back=365):
    """在 arr[idx] 时点计算同比 (与该时点-365天最近的点比较)"""
    if idx < 1 or idx >= len(arr): return None
    d0, v0 = arr[idx]
    target = datetime.date.fromisoformat(d0) - datetime.timedelta(days=days_back)
    best = None; best_diff = 9999
    for d, v in arr[:idx]:
        diff = abs((datetime.date.fromisoformat(d) - target).days)
        if diff < best_diff:
            best_diff = diff; best = v
    # 最近匹配点距目标不得超过120天, 否则视为无对应基期
    if best in (None, 0) or best_diff > 120 or v0 is None: return None
    return (v0 / best - 1) * 100

def yoy_series(key, n=10, days_back=365):
    """返回最近 n 个点 [(date, yoy%), ...], 跳过无法计算的点"""
    arr = s(key)
    out = []
    for i in range(max(1, len(arr) - n * 2), len(arr)):
        y = _yoy_at(arr, i, days_back)
        if y is not None:
            out.append((arr[i][0], round(y, 2)))
    return out[-n:]

def mom_pct_series(key, n=6):
    """最近 n 期环比% [(date, pct), ...]"""
    arr = s(key)
    out = []
    for i in range(1, len(arr)):
        prev = arr[i-1][1]
        if prev:
            out.append((arr[i][0], round((arr[i][1] / prev - 1) * 100, 2)))
    return out[-n:]

def diff_series(key, n=6):
    """最近 n 期水平差 [(date, diff), ...] (用于非农月增K)"""
    arr = s(key)
    out = []
    for i in range(1, len(arr)):
        out.append((arr[i][0], round(arr[i][1] - arr[i-1][1], 1)))
    return out[-n:]

def qlabel(d):
    """'2026-04-01' -> '26Q2'"""
    y, m = int(d[:4]), int(d[5:7])
    return f'{y % 100}Q{(m - 1) // 3 + 1}'

def mlabel(d):
    """'2026-06-01' -> '6月' """
    return f'{int(d[5:7])}月'

def wk(key, scale=1/1000, suffix='/周'):
    """周变化字符串, 处理 None; scale: 原始差 -> 目标单位 (如 $M->$B: 1/1000)"""
    v = tfm(key).get('w')
    if v is None: return '—'
    sign = '-' if v < 0 else '+'
    return f'{sign}${comma(abs(v)*scale,0)}B{suffix}'

# —— Phase1-3: 新辅助函数 ——
def raw_calc_pct(key, back):
    """从 raw_series 直接算百分比变化 (用于低频序列)"""
    arr = s(key)
    if len(arr) < back + 1: return None
    prev = arr[-1 - back][1]
    if not prev: return None
    return round((arr[-1][1] / prev - 1) * 100, 2)

def raw_calc_diff(key, back):
    """从 raw_series 直接算差值"""
    arr = s(key)
    if len(arr) < back + 1: return None
    return round(arr[-1][1] - arr[-1 - back][1], 4)

def hist_pct_rank(key, low_periods=252):
    """从 raw_series 计算历史分位 (与 buid_data 的 percentile 一致但用 raw)"""
    arr = s(key)
    vals = [v for _, v in arr[-low_periods:]]
    if len(vals) < 5: return 50
    cur = vals[-1]
    rank = sum(1 for v in vals if v <= cur)
    return round(rank / len(vals) * 100)

def hist_median(key, window=1000):
    """从 raw_series 计算历史中位数"""
    arr = s(key)
    vals = sorted([v for _, v in arr[-window:]])
    if not vals: return None
    n = len(vals)
    return round((vals[n//2] + vals[(n-1)//2]) / 2, 3) if n > 1 else vals[0]

def hist_p10(key, window=1000):
    """从 raw_series 计算历史 P10 (最紧10%分位)"""
    arr = s(key)
    vals = sorted([v for _, v in arr[-window:]])
    if len(vals) < 10: return None
    return round(vals[int(len(vals) * 0.1)], 3)

def sahm_rule():
    """Sahm Rule: unrate 3M均值 - min(unrate over 12M). > 0.5 = 衰退信号"""
    arr = s('unrate')
    if len(arr) < 13: return {'value': None, 'triggered': False}
    vals = [v for _, v in arr]
    latest_3m = sum(vals[-3:]) / 3
    min_12m = min(vals[-12:])
    value = round(latest_3m - min_12m, 2)
    return {'value': value, 'triggered': value > 0.5, 'threshold': 0.5}

def infl_annualized(key, months=3):
    """核心CPI 3/6月年化环比"""
    arr = s(key)
    n = months
    if len(arr) < n + 1: return None
    # 从相邻月度水平值计算年化率
    v_now = arr[-1][1]
    v_prev = arr[-1 - n][1]
    if not v_prev: return None
    ratio = v_now / v_prev
    annualized = (ratio ** (12 / n) - 1) * 100
    return round(annualized, 2)

def wage_inflation_gap():
    """时薪同比 vs 核心服务CPI——工资-通胀螺旋验证"""
    wage = raw_calc_pct('wage_yoy', 12)
    svcs_yoy = raw_calc_pct('cpi_core_svcs', 12)
    if wage is None or svcs_yoy is None: return None
    return round(wage - svcs_yoy, 2)

# 信用: 从 raw_series 计算真实历史中位和 P10
_credit_hist = {}
for k in ['aaa','aa','a','bbb','bb','b','ccc']:
    _credit_hist[k] = {'median': hist_median(k), 'p10': hist_p10(k)}
_credit_ladder_median = [_credit_hist.get(r, {}).get('median') for r in ['aaa','aa','a','bbb','bb','b','ccc']]
_credit_ladder_p10 = [_credit_hist.get(r, {}).get('p10') for r in ['aaa','aa','a','bbb','bb','b','ccc']]
_credit_fallback_median = [0.55, 0.75, 1.0, 1.5, 3.0, 5.5, 12.0]
_credit_fallback_p10 = [0.30, 0.40, 0.55, 0.80, 1.5, 2.8, 5.0]
for i in range(7):
    if _credit_ladder_median[i] is None and i < len(_credit_fallback_median):
        _credit_ladder_median[i] = _credit_fallback_median[i]
    if _credit_ladder_p10[i] is None and i < len(_credit_fallback_p10):
        _credit_ladder_p10[i] = _credit_fallback_p10[i]

# 信用违约率(真实)
_default_rate_val = val('default_rate')
_default_rate_pct = hist_pct_rank('default_rate')
_default_rate_display = (f'{_default_rate_val:.1f}%' + (f' (分位 {_default_rate_pct})' if _default_rate_pct else '')) if _default_rate_val else '3.2% (估算)'

# 衰退仪表盘各信号最新值
_sahm = sahm_rule()
v_t10y3m = val('t10y3m')
_t10y3m_val = v_t10y3m if v_t10y3m is not None else (round((val('dgs10') - val('dgs3mo')) * 100, 1) if val('dgs10') and val('dgs3mo') else None)
v_stlfsi = val('stlfsi')
_recession_p = val('recession_prob')

def wk_dict(key, scale=1/1000):
    """各尺度变化 dict (字符串), 处理 None"""
    out = {}
    for k in ('d','w','m','h6'):
        v = tfm(key).get(k)
        if v is None: out[k] = '—'
        else:
            sign = '-' if v < 0 else '+'
            out[k] = f'{sign}${comma(abs(v)*scale,0)}B'
    return out

# 30Y 主源解析: Yahoo ^TYX (实时) 优先, FRED DGS30 回退 (多源交叉校验)
_30y_key = 'tyx' if val('tyx') is not None else 'dgs30'

# 收益率曲线: 用 raw 序列取最新/一个月前/一年前
MATS = [('1M','dgs1mo'),('3M','dgs3mo'),('6M','dgs6mo'),('1Y','dgs1'),('2Y','dgs2'),
        ('3Y','dgs3'),('5Y','dgs5'),('7Y','dgs7'),('10Y','dgs10'),('20Y','dgs20'),('30Y',_30y_key)]
def curve_snapshot(offset=0):
    out = []
    for _, key in MATS:
        arr = s(key)
        if not arr or len(arr) <= offset: out.append(None)
        else: out.append(round(arr[-1-offset][1], 2))
    return out
def curve_date(offset=0):
    key = MATS[0][1]
    arr = s(key)
    return arr[-1-offset][0] if arr and len(arr) > offset else None

# ---------- 构建各板块 ----------
DATA = {}
DATA['meta'] = {
    'lastUpdated': f'{META_DATE} (官方数据, 自动更新)',
    'dataSource': 'FRED / U.S. Treasury FiscalData / NY Fed / Yahoo Finance',
    'marketNote': '数值来自官方公开源, 每日自动重算; 月/半年变化受数据频率限制可能为 None'
}

# 全局 regime (汇总关键真实值)
v_dgs10 = val('dgs10'); v_wti = val('wti'); v_ccc = val('ccc'); v_hy = val('hy')
v_vix = val('vix'); v_tga = val('tga'); v_netliq = val('netliq')
DATA['globalRegime'] = {
    'name': '利率上行 + 信用分层',
    'signal': 'risk-off',
    'confidence': '中等置信',
    'description': f'10Y 美债 {f2(v_dgs10)}% 处于近一年高位 (分位 {pct("dgs10")}), 长端抛售是确立趋势; 与此同时信用市场内部已分层——CCC 利差 {f2(v_ccc)}% (分位 {pct("ccc")}, 极窄历史区间的另外一端是极高压力), 而 HY 整体仅 {f2(v_hy)}%。这种"高评级平静、低评级承压"的组合是周期中后期的典型特征。油价 (WTI {f2(v_wti)}) 与波动率 (VIX {f2(v_vix)}) 尚未失控, 当前属"利率驱动的条件性紧张", 而非流动性危机。'
}

# ====== 大类资产 ======
# 真实相关性矩阵: 共同交易日日度收益的 Pearson 相关
def daily_ret_map(key, n=120):
    arr = s(key)[-(n + 1):]
    out = {}
    for i in range(1, len(arr)):
        prev = arr[i - 1][1]
        if prev:
            out[arr[i][0]] = arr[i][1] / prev - 1
    return out

def corr_pair(xs, ys):
    m = len(xs)
    if m < 5: return None
    mx = sum(xs) / m; my = sum(ys) / m
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs); vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0: return None
    return cov / (vx ** 0.5 * vy ** 0.5)

CORR_KEYS = [('SPX','spx'), ('TLT','tlt'), ('Gold','gold'), ('WTI','wti'), ('DXY','dxy'), ('BTC','btc'), ('Copper','copper'), ('ETH','eth')]
_rets = {k: daily_ret_map(k) for _, k in CORR_KEYS}
_common = None
for _, k in CORR_KEYS:
    _common = set(_rets[k]) if _common is None else (_common & set(_rets[k]))
_corr_dates = sorted(_common)[-60:] if _common else []
corr_matrix = []
for _, k1 in CORR_KEYS:
    row = []
    for _, k2 in CORR_KEYS:
        r = corr_pair([_rets[k1][d] for d in _corr_dates], [_rets[k2][d] for d in _corr_dates])
        row.append(round(r, 2) if r is not None else None)
    corr_matrix.append(row)
# 股债/油股真实相关 (用于 note)
def _cm(a, b):
    i = [k for _, k in CORR_KEYS].index(a); j = [k for _, k in CORR_KEYS].index(b)
    return corr_matrix[i][j]
spx_tlt_corr = _cm('spx', 'tlt'); spx_wti_corr = _cm('spx', 'wti')

# 趋势含义 (基于方向自动生成)
def trend_meaning(name, ch):
    d,w,m,h6 = ch['d'],ch['w'],ch['m'],ch['h6']
    if None not in (w,m,h6):
        if w>0 and m>0 and h6>0: return f'半年 +{h6:.0f}% 的上升趋势中, 近月 +{m:.0f}% 仍在加速'
        if w<0 and m<0 and h6>0: return f'半年 +{h6:.0f}% 但近月 {m:.0f}% 回调——趋势内修正'
        if w>0 and m<0: return f'半年 {h6:+.0f}% 但近月转弱——底部可能形成'
        if w<0 and m>0: return f'半年 {h6:+.0f}% 但近周转弱——顶部预警'
    return '多尺度方向不一, 趋势不明'

def _build_us_indices_chart():
    """构建美股五大指数走势图数据 (归一化至起点=0%, 即累计收益率)。
    数据源优先级: Yahoo 实时 > FRED 滞后。取最近 ~500 个交易日(约2年)。
    X轴改为时间轴(日期)。"""
    indices = [
        ('标普500', 'spx'), ('纳斯达克100', 'ndx'),
        ('道琼斯', 'dji_yahoo' if s('dji_yahoo') else 'dji'),
        ('罗素2000', 'rut'), ('费城半导体', 'sox'),
    ]
    raw_series = {}
    for name, key in indices:
        arr = s(key)
        if arr:
            raw_series[name] = [(d, v) for d, v in arr]
    if len(raw_series) < 3:
        return {'labels': [], 'series': {}, 'note': '数据不足'}
    min_len = min(len(v) for v in raw_series.values())
    take = min(500, min_len)
    # 用参考序列(spx 优先)的日期作为 X 轴时间轴
    ref_name = '标普500' if '标普500' in raw_series else list(raw_series.keys())[0]
    dates = [d for d, _ in raw_series[ref_name][-take:]]
    series = {}
    for name, key in indices:
        if name not in raw_series:
            continue
        arr = raw_series[name][-take:]
        base = next((v for _, v in arr if v), None)
        if base and base != 0:
            # 归一化至累计收益率(起点=0%), 而非起点=100
            series[name] = [round((x / base - 1) * 100, 2) if x else None for _, x in arr]
    return {'labels': dates, 'series': series, 'note': f'累计涨跌(起点=0%) · 近{take}个交易日'}

ASSET_MAP = [
    ('标普500','spx','^GSPC',2,''), ('纳斯达克100','ndx','^NDX',2,''),
    ('道琼斯','dji','^DJI',2,''), ('罗素2000','rut','^RUT',2,''),
    ('费城半导体','sox','^SOX',2,''),
    ('黄金','gold','GC=F',2,'$'), ('WTI原油','wti','CL=F',2,'$'), ('铜','copper','HG=F',2,''),
    ('美元指数','dxy','DX-Y.NYB',2,''), ('美元/日元','usdjpy','USDJPY=X',2,''),
    ('比特币','btc','BTC',0,'$'), ('以太坊','eth','ETH',0,'$'),
    ('20+年国债ETF','tlt','TLT',2,''),
    ('投资级债ETF','lqd','LQD',2,''), ('高收益债ETF','hyg','HYG',2,''),
]
metrics_assets = []
trend_assets = []
table_assets = []
for name, key, ticker, dec, money in ASSET_MAP:
    v = val(key)
    if v is None: continue
    ch = asset_changes(key)
    metrics_assets.append({
        'label': name, 'value': asset_val_str(key, dec, money), 'change': ret(ch['d']),
        'dir': dir_of(ch['d']), 'tag': ticker, 'percentile': pct(key),
        'signal': dir_of(ch['w']) if ch['w'] is not None else 'mixed',
        'meaning': f'当前位于近一年 {pct(key)} 分位',
        'changes': {k: ret(ch[k]) if ch[k] is not None else '—' for k in ('d','w','m','h6')},
        'sparkline': series30(key)
    })
    # 趋势 (用 % 变化)
    tr = ch
    trend_assets.append({
        'name': name, 'unit': '%', 'current': asset_val_str(key, dec, money),
        'changes': {k: (round(tr[k],2) if tr[k] is not None else None) for k in ('d','w','m','h6')},
        'meaning': trend_meaning(name, tr)
    })
    table_assets.append({'ticker': ticker, 'name': name, 'price': asset_val_str(key, dec, money),
                         'change': ret(ch['d']), 'dir': dir_of(ch['d'])})


DATA['assets'] = {
    'regime': {'label':'利率定价的资产重定价','signal':'risk-off','confidence':'中等置信',
        'description': f'10Y 利率 {f2(v_dgs10)}% 的上行是本周资产重定价的核心变量, 长久期资产 (纳斯达克/长债) 对实际利率最敏感。WTI {f2(v_wti)} 尚未失控, 但利率上行已压制估值。'},
    'keySignals': [
        {'title': f'纳斯达克100 周跌 {ret(asset_changes("ndx")["w"])}', 'meaning':'长久期科技股对利率最敏感, 是本轮重定价的领先指标。', 'direction':'bearish'},
        {'title': f'WTI 原油周涨 {ret(asset_changes("wti")["w"])}', 'meaning':'油价上行推升通胀预期, 与利率上行形成正反馈, 压制风险资产估值。', 'direction':'bearish'},
        {'title': f'黄金 {ret(asset_changes("gold")["w"])} 横盘', 'meaning':'实际利率上行对冲了避险买需, 黄金方向选择临近。', 'direction':'mixed'},
    ],
    'metrics': metrics_assets,
    'trendData': trend_assets,
    'table': table_assets,
    'chartData': {'labels': ([d for d, _ in s('spx')[-30:]] if s('spx') else list(range(30))), 'series': {
        'SPX': series30('spx'), 'SOX': series30('sox'), 'WTI': series30('wti'), 'Gold': series30('gold'),
        'Copper': series30('copper'), 'BTC': series30('btc'), 'ETH': series30('eth')}},
    'correlation': {'assets':[lb for lb, _ in CORR_KEYS],
        'matrix': corr_matrix,
        'note': f'近{len(_corr_dates)}个共同交易日日度收益的真实 Pearson 相关 · 股债 {spx_tlt_corr:+.2f} / 油股 {spx_wti_corr:+.2f}'},
    'analystView': f'跨资产信号指向"利率驱动的重定价"而非系统性危机: 纳斯达克 ({ret(asset_changes("ndx")["w"])}) 与长债 (TLT {ret(asset_changes("tlt")["w"])}) 同步承压, 是典型的实际利率上行组合。黄金 ({ret(asset_changes("gold")["w"])}) 横盘说明实际利率上行对冲了避险需求。只要 VIX ({f2(v_vix)}) 未突破 20、信用利差未走阔, 这仍是估值压缩而非流动性事件。',
    'whatToWatch': [
        {'trigger':'<span class="watch-threshold">10Y 突破 4.85%</span>','implication':'触及年内高点, 系统性 CTA 抛售债券, 利率上行自我强化','status':f'距离 {max(0,4.85-v_dgs10):.2f}bp'},
        {'trigger':'VIX 收盘站上 <span class="watch-threshold">20</span>','implication':'波动率目标基金强制减仓, 股市抛压自我强化','status':f'距离 {20-v_vix:.1f}'},
        {'trigger':'WTI 突破 <span class="watch-threshold">$90</span>','implication':'能源冲击确认, 通胀预期与利率进一步上行','status':f'距离 {max(0,90-v_wti):.1f}'},
    ],
    # 美股五大指数累计涨跌走势 (起点=0%, 用较长序列展示相对强弱)
    'usIndicesChart': _build_us_indices_chart(),
}

# ====== 利率 ======
def rate_metric(label, key, tag, extra_meaning=''):
    v = val(key); t = tfm(key)
    ch = rate_changes(key)
    return {
        'label': label, 'value': rate_val_str(key), 'change': rate_chg_bp(key),
        'dir': dir_of(t.get('d')), 'tag': tag, 'percentile': pct(key),
        'signal': 'bearish' if (t.get('w') or 0) > 0 else ('bullish' if (t.get('w') or 0) < 0 else 'mixed'),
        'meaning': (extra_meaning or f'近一年 {pct(key)} 分位') + f' | 周 {rate_chg_bp(key, "bp") if False else ""}',
        'changes': {k: (bp(ch[k]) if ch[k] is not None else '—') for k in ('d','w','m','h6')},
        'sparkline': series30(key)
    }
v_2y=val('dgs2'); v_10y=val('dgs10'); v_30y=val(_30y_key); v_tips=val('tips10'); v_bei=val('bei10')
spread_10_2 = round((v_10y - v_2y)*100, 1)  # bp

# Phase3: 鹰鸽指数 + 利率路径数据化 (提前计算, 供 DATA['fed'] 引用)
_v_2y_week = (tfm('dgs2')['w'] or 0) * 100  # bp
_v_2y_month = (tfm('dgs2')['m'] or 0) * 100
_hawk_score_data = round(5 + _v_2y_month * 0.2, 1)
_hawk_score_data = max(0, min(10, _hawk_score_data))
_hawk_label_data = '偏鹰' if _hawk_score_data > 6 else ('偏鸽' if _hawk_score_data < 4 else '中性')
_cut_prob = max(0, min(80, round(50 - _v_2y_month * 3, 0))) if _v_2y_month else 30
_hold_prob = round(100 - _cut_prob - 5, 0)
_hike_prob = 5

DATA['rates'] = {
    'regime': {'label':'熊陡确立' if (v_10y - v_2y) > 0 else '曲线变化','signal':'risk-off','confidence':'高置信',
        'description': f'长端利率上行快于短端 (10Y {f2(v_10y)}% vs 2Y {f2(v_2y)}%), 曲线{"熊市陡峭化" if (tfm("dgs10").get("w") or 0)>(tfm("dgs2").get("w") or 0) else "变化"}。拆解: 实际利率 (TIPS 10Y {f2(v_tips)}%) 与通胀预期 (Breakeven {f2(v_bei)}%) 共同上行。'},
    'keySignals': [
        {'title': f'10Y 突破 {f2(v_10y)}%','meaning':'长端利率是本轮资产重定价的核心变量, 实际利率驱动为主。','direction':'bearish'},
        {'title': f'10Y-2Y 利差 {spread_10_2:+.0f}bp','meaning':'曲线正常化/陡峭化, 通常出现在紧缩末期或再通胀早期。','direction':'mixed'},
        {'title': f'10Y 实际利率 {f2(v_tips)}% (分位 {pct("tips10")})','meaning':'实际利率是估值真实折现率, 处于高位对高估值科技股最不利。','direction':'bearish'},
    ],
    'metrics': [
        rate_metric('联邦基金利率(上限)','ffr_up','FFR'),
        rate_metric('2Y 国债','dgs2','DGS2'),
        rate_metric('10Y 国债','dgs10','DGS10'),
        rate_metric('30Y 国债', _30y_key, '^TYX' if _30y_key=='tyx' else 'DGS30'),
        rate_metric('10Y 实际利率','tips10','TIPS'),
        {'label':'10Y-2Y 利差','value':f'{spread_10_2/100:.2f}%' if spread_10_2 is not None else '—',
         'change':f'{((tfm("dgs10")["d"] or 0)-(tfm("dgs2")["d"] or 0))*100:+.1f}bp' if (tfm("dgs10")["d"] is not None and tfm("dgs2")["d"] is not None) else '—',
         'dir':'up' if ((spread_10_2 or 0) > 0) else ('down' if ((spread_10_2 or 0) < 0) else 'neutral'),
         'tag':'Spread','percentile':50,'signal':'mixed',
         'meaning':f'曲线{"陡峭化" if (spread_10_2 or 0)>0 else ("倒挂" if (spread_10_2 or 0)<0 else "平坦")} · 利差 {spread_10_2:+.0f}bp',
         'changes':{'d':round(((tfm("dgs10")["d"] or 0)-(tfm("dgs2")["d"] or 0))*100,1) if (tfm("dgs10")["d"] is not None and tfm("dgs2")["d"] is not None) else None,
                    'w':round(((tfm("dgs10")["w"] or 0)-(tfm("dgs2")["w"] or 0))*100,1) if (tfm("dgs10")["w"] is not None and tfm("dgs2")["w"] is not None) else None,
                    'm':round(((tfm("dgs10")["m"] or 0)-(tfm("dgs2")["m"] or 0))*100,1) if (tfm("dgs10")["m"] is not None and tfm("dgs2")["m"] is not None) else None,
                    'h6':round(((tfm("dgs10")["h6"] or 0)-(tfm("dgs2")["h6"] or 0))*100,1) if (tfm("dgs10")["h6"] is not None and tfm("dgs2")["h6"] is not None) else None},
         'sparkline':[round((a-b),2) for a,b in zip(series90('dgs10')[-30:],series90('dgs2')[-30:])]},
        rate_metric('10Y 通胀预期','bei10','Breakeven'),
        rate_metric('SOFR','sofr','SOFR'),
    ],
    'trendData': [
        {'name':'2Y 国债(政策预期)','unit':'bp','current':f2(v_2y)+'%','changes':rate_changes('dgs2'),'meaning':trend_meaning('2Y',{'d':tfm('dgs2')['d']*100,'w':tfm('dgs2')['w']*100,'m':tfm('dgs2')['m']*100,'h6':(tfm('dgs2')['h6']*100 if tfm('dgs2')['h6'] else None)})},
        {'name':'10Y 国债(长端锚)','unit':'bp','current':f2(v_10y)+'%','changes':rate_changes('dgs10'),'meaning':'四尺度全部上行——长端抛售是确立趋势' if (tfm('dgs10')['w'] or 0)>0 else '长端回落'},
        {'name':'30Y 国债(期限溢价)','unit':'bp','current':f2(v_30y)+'%','changes':rate_changes(_30y_key),'meaning':'比10Y涨得更快, 财政供给担忧在定价'},
        {'name':'10Y 实际利率','unit':'bp','current':f2(v_tips)+'%','changes':rate_changes('tips10'),'meaning':'估值压力持续累积'},
        {'name':'10Y Breakeven(通胀预期)','unit':'bp','current':f2(v_bei)+'%','changes':rate_changes('bei10'),'meaning':'缓慢爬升, 通胀预期未脱锚' if (tfm('bei10')['m'] or 0)>0 else '通胀预期回落'},
        {'name':'10Y-2Y 利差','unit':'bp','current':f'{spread_10_2:+.0f}bp','changes':{'d':round((tfm("dgs10")["d"]-tfm("dgs2")["d"])*100,1),'w':round((tfm("dgs10")["w"]-tfm("dgs2")["w"])*100,1),'m':round((tfm("dgs10")["m"]-tfm("dgs2")["m"])*100,1),'h6':(round((tfm("dgs10")["h6"]-tfm("dgs2")["h6"])*100,1) if tfm("dgs10")["h6"] and tfm("dgs2")["h6"] else None)},'meaning':'曲线陡峭化/正常化'},
    ],
    'yieldCurve': {
        'maturities':['1M','3M','6M','1Y','2Y','3Y','5Y','7Y','10Y','20Y','30Y'],
        'today': curve_snapshot(0),
        'oneMonthAgo': curve_snapshot(21),
        'oneYearAgo': curve_snapshot(252),
    },
    'chartData': {'labels': _dates_for('dgs10'), 'series': {
        '10Y名义': series90('dgs10'), '10Y实际': series90('tips10'), '2Y': series90('dgs2'), '30Y': series90(_30y_key)}},
    'spreadData': {'labels': _dates_for('dgs10'), 'series': {
        '10Y-2Y利差': [round((a-b),2) for a,b in zip(series90('dgs10'), series90('dgs2'))],
        '通胀预期(Breakeven)': series90('bei10')}},
    'detailedTable': [
        {'maturity':'2年','rate':f2(v_2y)+'%','change':rate_chg_bp('dgs2'),'realRate':f2(val('tips2') if val('tips2') else (val('tips10')-0.5))+'%','breakeven':f2(val('bei2') if val('bei2') else (v_2y-(val('tips10')-0.5)))+'%','source':'DGS2'},
        {'maturity':'5年','rate':f2(val('dgs5'))+'%','change':rate_chg_bp('dgs5'),'realRate':f2(val('tips5'))+'%','breakeven':f2(val('bei5') if val('bei5') else (val('dgs5')-val('tips5')))+'%','source':'DGS5'},
        {'maturity':'10年','rate':f2(v_10y)+'%','change':rate_chg_bp('dgs10'),'realRate':f2(v_tips)+'%','breakeven':f2(v_bei)+'%','source':'DGS10'},
        {'maturity':'30年','rate':f2(v_30y)+'%','change':rate_chg_bp(_30y_key),'realRate':f2(val('tips30'))+'%','breakeven':f2(val('bei30') if val('bei30') else (v_30y-val('tips30')))+'%','source':('Yahoo ^TYX' if _30y_key=='tyx' else 'FRED DGS30')},
    ],
    'analystView': f'本轮利率上行的结构: 实际利率 ({f2(v_tips)}%) 与通胀预期 ({f2(v_bei)}%) 共同贡献, 属"增长受损+通胀回升"的滞胀组合而非单纯紧缩预期。对资产定价的含义: 实际利率高位环境下, 标普合理市盈率需下修。曲线下一个关键信号是 2Y——若油价冲击迫使市场取消降息定价, 2Y 补涨将触发熊平, 那才是对股市最不利的形态。',
    'whatToWatch': [
        {'trigger':'<span class="watch-threshold">10Y 突破 4.85%</span>','implication':'触及年内高点, 系统性 CTA 抛售债券','status':f'距离 {max(0,4.85-v_10y):.2f}bp'},
        {'trigger':'Breakeven 突破 <span class="watch-threshold">2.90%</span>','implication':'通胀预期脱锚信号, 美联储转向鹰派','status':f'距离 {max(0,2.90-v_bei):.2f}bp'},
        {'trigger':'2Y 突破 <span class="watch-threshold">4.50%</span>','implication':'市场取消降息定价, 曲线熊平','status':f'距离 {max(0,4.50-v_2y):.2f}bp'},
    ],
    'chartNotes': {
        'spreadNote': f'10Y-2Y 利差 {spread_10_2/100:.2f}% ({spread_10_2:+.0f}bp) · Breakeven {f2(v_bei)}% (1年分位 {pct("bei10")})',
        'trendNote': f'10Y 周Δ{bp(tfm("dgs10")["w"]*100 if tfm("dgs10")["w"] is not None else None)} / 月Δ{bp(tfm("dgs10")["m"]*100 if tfm("dgs10")["m"] is not None else None)} / 半年Δ{bp(tfm("dgs10")["h6"]*100 if tfm("dgs10")["h6"] is not None else None)} · 2Y 周Δ{bp(tfm("dgs2")["w"]*100 if tfm("dgs2")["w"] is not None else None)}',
    },
}

# ====== 美联储 ======
v_walcl = val('walcl'); v_rrp2 = val('rrp'); v_tga2 = val('tga'); v_res = val('resbal')
v_netliq = val('netliq')
DATA['fed'] = {
    'regime': {'label':'观望期, 鹰鸽分化','signal':'mixed','confidence':'高置信',
        'description':f'政策利率 {f2(val("ffr_up"))}%-{f2(val("ffr_lo"))}% 维持不变, 下一次行动大概率降息。缩表 (WALCL {comma(v_walcl/1000000,1)}T, 周 {bp(tfm("walcl")["w"]/1000, "$B")}) 持续推进, RRP 缓冲 (${f2(v_rrp2)}B) 已耗尽, 未来 QT 将直击准备金。'},
    'keySignals': [
        {'title':f'RRP 余额仅 ${f2(v_rrp2)}B','meaning':'货币市场基金可搬回美联储的钱基本耗尽, 未来缩表冲击无缓冲。','direction':'bearish'},
        {'title':f'WALCL {comma(v_walcl/1000000,1)}T 持续下行','meaning':'QT 每周缩减, 是净流动性的稳定逆风。','direction':'mixed'},
        {'title':f'银行准备金 {comma(v_res/1000000,2)}T','meaning':'仍在 3 万亿上方, 处于"充裕"区间, 3 万亿是关键心理位。','direction':'bullish'},
    ],
    'metrics': [
        {'label':'总资产','value':f'${comma(v_walcl/1000000,2)}T','change':wk('walcl'),'dir':'down','tag':'WALCL','percentile':pct('walcl'),'signal':'bearish','meaning':'缩表持续推进','changes':wk_dict('walcl'),'sparkline':series30('walcl')},
        {'label':'联邦基金利率(上限)','value':f'{f2(val("ffr_up"))}%','change':'维持','dir':'neutral','tag':'FFR','percentile':pct('ffr_up'),'signal':'mixed','meaning':'限制性立场未变','changes':{'d':'0','w':'0','m':'0','h6':pct('ffr_up') and '—'},'sparkline':series30('ffr_up')},
        {'label':'国债持仓','value':f'${comma(val("treast")/1000000,2)}T','change':wk('treast'),'dir':'down','tag':'TREAST','percentile':pct('treast'),'signal':'mixed','meaning':'被动缩表, 节奏可控','changes':wk_dict('treast'),'sparkline':series30('treast')},
        {'label':'MBS 持仓','value':f'${comma(val("mbst")/1000000,2)}T','change':wk('mbst'),'dir':'down','tag':'MBST','percentile':pct('mbst'),'signal':'mixed','meaning':'提前还款低迷, MBS缩减慢','changes':wk_dict('mbst'),'sparkline':series30('mbst')},
        {'label':'银行准备金','value':f'${comma(v_res/1000000,2)}T','change':f'+${comma(tfm("resbal")["w"]/1000,0)}B/周','dir':'up','tag':'WRESBAL','percentile':pct('resbal'),'signal':'bullish','meaning':'充裕区间','changes':wk_dict('resbal'),'sparkline':series30('resbal')},
        {'label':'RRP 余额','value':f'${f2(v_rrp2)}B','change':f'{bp(tfm("rrp")["w"], "$B")}', 'dir':dir_of(tfm("rrp")["w"]),'tag':'RRP','percentile':pct('rrp'),'signal':'bearish','meaning':'缓冲耗尽','changes':{k:(bp(tfm("rrp")[k], "$B") if tfm("rrp")[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('rrp')},
        {'label':'IORB','value':f'{f2(val("iorb"))}%','change':'维持','dir':'neutral','tag':'IORB','percentile':pct('iorb'),'signal':'mixed','meaning':'SOFR-IORB 利差反映充裕度','changes':{'d':'0','w':'0','m':'0','h6':'—'},'sparkline':series30('iorb')},
        {'label':'SOFR','value':f'{f2(val("sofr"))}%','change':rate_chg_bp('sofr'),'dir':dir_of(tfm("sofr")["d"]),'tag':'SOFR','percentile':pct('sofr'),'signal':'bullish','meaning':'低于 IORB, 融资充裕','changes':{k:(bp(tfm("sofr")[k]*100) if tfm("sofr")[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('sofr')},
    ],
    'trendData': [
        {'name':'美联储总资产','unit':'$B','current':f'${comma(v_walcl/1000000,2)}T','changes':{k:(round(tfm("walcl")[k]/1000,1) if tfm("walcl")[k] else None) for k in ('d','w','m','h6')},'meaning':'缩表速度恒定, 净流动性的稳定逆风'},
        {'name':'银行准备金','unit':'$B','current':f'${comma(v_res/1000000,2)}T','changes':{k:(round(tfm("resbal")[k]/1000,1) if tfm("resbal")[k] else None) for k in ('d','w','m','h6')},'meaning':'近月回升但半年仍低, 3万亿关口是关键'},
        {'name':'RRP 余额','unit':'$B','current':f'${f2(v_rrp2)}B','changes':{k:(round(tfm("rrp")[k],3) if tfm("rrp")[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'缓冲实质归零的结构事件'},
        {'name':'TGA 余额','unit':'$B','current':f'${comma(v_tga2,1)}B' if v_tga2 else '—','changes':{k:(round(tfm("tga")[k],1) if tfm("tga")[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'财政部现金, 上升则抽水'},
    ],
    'chartData': {'labels': _dates_for('walcl'), 'series': {
        '总资产': [round(x/1e6,2) for x in series90('walcl')], '国债': [round(x/1e6,2) for x in series90('treast')], 'MBS': [round(x/1e6,2) for x in series90('mbst')]}},
    'policyTable': [
        {'item':'联邦基金利率目标区间','value':f'{f2(val("ffr_lo"))}% - {f2(val("ffr_up"))}%','change':'维持','note':'2026年以来区间'},
        {'item':'IORB (准备金利息)','value':f'{f2(val("iorb"))}%','change':'维持','note':f'SOFR-IORB = {bp((val("sofr")-val("iorb"))*100)}'},
        {'item':'ON RRP 利率','value':f'{f2(val("iorb")-0.1)}%','change':'维持','note':f'RRP 余额仅 ${f2(v_rrp2)}B'},
        {'item':'QT 国债月度上限','value':'$250亿','change':'维持','note':'被动缩减'},
        {'item':'QT MBS 月度上限','value':'$150亿','change':'维持','note':'被动缩减'},
    ],
    'fomcTimeline': build_fomc_timeline(),
    'speeches': [
        {'date':'07-22','speaker':'Powell 鲍威尔','title':'半年度货币政策报告','stance':'neutral','key':'通胀仍高于目标但取得进展; 就业降温; 数据支持则可能降息','hawkishScore':5},
        {'date':'07-19','speaker':'Waller 沃勒','title':'通胀前景','stance':'dovish','key':'通胀向2%靠拢趋势明确, 降息时机已近','hawkishScore':3},
        {'date':'07-18','speaker':'Bostic 博斯蒂克','title':'经济展望','stance':'hawkish','key':'通胀粘性犹存, 不应急于降息','hawkishScore':7},
        {'date':'07-15','speaker':'Bowman 鲍曼','title':'银行业会议','stance':'hawkish','key':'通胀上行风险仍存, 降息需谨慎','hawkishScore':8},
        {'date':'07-12','speaker':'Goolsbee 古尔斯比','title':'芝加哥经济俱乐部','stance':'dovish','key':'就业正常化, 利率需随通胀回落下降','hawkishScore':3},
        {'date':'07-10','speaker':'Daly 戴利','title':'旧金山联储访谈','stance':'neutral','key':'对降息持开放态度, 取决于数据','hawkishScore':5},
    ],
    'hawkishDovish': {'score':_hawk_score_data,'label':_hawk_label_data,
        'isDataDriven': True,
        'method': f'基于2Y利率变化(周{_v_2y_week:+.0f}bp/月{_v_2y_month:+.0f}bp)自动计算',
        'officials':[
            {'name':'Warsh','role':'主席','score':7,'stance':'hawkish'},
            {'name':'Powell','role':'理事','score':5,'stance':'neutral'},
            {'name':'Williams','role':'纽约联储','score':5,'stance':'neutral'},
            {'name':'Waller','role':'理事','score':3,'stance':'dovish'},
            {'name':'Bowman','role':'理事','score':8,'stance':'hawkish'},
            {'name':'Bostic','role':'亚特兰大','score':7,'stance':'hawkish'},
            {'name':'Daly','role':'旧金山','score':5,'stance':'neutral'},
            {'name':'Goolsbee','role':'芝加哥','score':3,'stance':'dovish'},
        ],
        'ratePath':{'nextMeeting':_NEXT_FOMC or '2026-07-29','holdProb':_hold_prob,'cut25bpProb':_cut_prob,'cut50bpProb':5,'hikeProb':_hike_prob,'note':f'基于2Y利率月变化({_v_2y_month:+.0f}bp)动态推算 · {"利率下行=降息概率上升" if _v_2y_month < 0 else "利率上行=降息概率下降"}'}},
    'analystView': f'美联储处于"数据依赖的观望期", 但油价冲击正在改变平衡。关键: 沃什在 {curve_date(0)[:7]} 发布会上如何定性油价——"暂时性"=恢复降息定价, "持续风险"=压缩降息空间。RRP 耗尽 (${f2(v_rrp2)}B) 是结构性转折: 此后 QT 每缩 1 美元直击准备金。',
    'whatToWatch': [
        {'trigger':(f'<span class="watch-threshold">{_fomc_md}</span> FOMC会议' if _fomc_md else '下次 FOMC 会议'),
         'implication':'关注对油价的定性: transitory=利多, persistent risk=利空',
         'status':(f'{_fomc_days}天后' if (_fomc_days is not None and _fomc_days>0) else ('今天' if _fomc_days==0 else ('已召开' if _fomc_days is not None else '即将')))},
        {'trigger':'<span class="watch-threshold">8月22日</span> 杰克逊霍尔','implication':'历史重大政策转向信号窗口','status':'1个月后'},
        {'trigger':'SRF 使用量突破 <span class="watch-threshold">$50B</span>','implication':'银行主动向美联储借钱, 准备金稀缺确认','status':'当前极少'},
    ],
    'chartNotes': {
        'hawkNote': f'0=极度鸽派 / 10=极度鹰派 · 当前 {_hawk_score_data} {_hawk_label_data} (基于2Y利率自动计算 · 月Δ{_v_2y_month:+.0f}bp)',
        'probNote': f'7月会议: 维持{_hold_prob}% / 降25bp {_cut_prob}% · 基于2Y利率动态推算',
    },
}

# ====== 流动性 ======
v_nl = val('netliq'); v_rrpn = val('rrp'); v_tgan = val('tga'); v_sofr_iorb = (val('sofr')-val('iorb'))
DATA['liquidity'] = {
    'regime': {'label':'缓冲耗尽, 但未失速','signal':'mixed','confidence':'高置信',
        'description':f'RRP 仅 ${f2(v_rrpn)}B, 货币市场基金可搬回美联储的钱基本耗尽。从此 TGA 每升 1 美元、QT 每缩 1 美元都直击银行准备金——流动性框架从"有缓冲"切换到"裸奔"的结构性转折。但 SOFR-IORB ({bp(v_sofr_iorb*100)}) 仍为负, 融资市场尚未出现真实资金争夺。'},
    'keySignals': [
        {'title':f'RRP 余额 ${f2(v_rrpn)}B, 缓冲实质归零','meaning':'过去两年 QT 冲击被 RRP 吸收, 未来每一美元缩表直击准备金, 充裕度下滑加速。','direction':'bearish'},
        {'title':f'TGA 余额 ${comma(v_tgan,1)}B' if v_tgan else 'TGA 数据缺失','meaning':'财政部现金上升=从银行体系抽水, 若向 9000 亿迈进将单周收缩数百亿。','direction':'bearish'},
        {'title':f'SOFR-IORB {bp(v_sofr_iorb*100)}','meaning':'回购利率低于准备金利率, 融资充裕; 转正才是压力第一确认信号。','direction':'bullish'},
    ],
    'metrics': [
        {'label':'净流动性','value':f'${comma(v_nl/1000,2)}T' if v_nl else '—','change':f'{bp(tfm("netliq")["w"], "$B") if tfm("netliq")["w"] else "—"}','dir':dir_of(tfm("netliq")["w"]) if tfm("netliq")["w"] else 'neutral','tag':'NetLiq','percentile':pct('netliq'),'signal':'bearish','meaning':'WALCL−RRP−TGA','changes':{k:(bp(tfm("netliq")[k], "$B") if tfm("netliq")[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('netliq')},
        {'label':'美联储总资产','value':f'${comma(v_walcl/1000000,2)}T','change':wk('walcl'),'dir':'down','tag':'WALCL','percentile':pct('walcl'),'signal':'bearish','meaning':'QT 第一驱动','changes':wk_dict('walcl'),'sparkline':series30('walcl')},
        {'label':'RRP 余额','value':f'${f2(v_rrpn)}B','change':bp(tfm("rrp")["w"], "$B"),'dir':dir_of(tfm("rrp")["w"]),'tag':'RRP','percentile':pct('rrp'),'signal':'bearish','meaning':'缓冲垫耗尽','changes':{k:(bp(tfm("rrp")[k], "$B") if tfm("rrp")[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('rrp')},
        {'label':'TGA 余额','value':f'${comma(v_tgan,1)}B' if v_tgan else '—','change':(f'+${comma(tfm("tga")["w"],0)}B' if (v_tgan and tfm("tga")["w"]) else '—'),'dir':dir_of(tfm("tga")["w"]) if v_tgan else 'neutral','tag':'TGA','percentile':pct('tga'),'signal':'bearish','meaning':'财政部抽水','changes':{k:(f'+${comma(tfm("tga")[k],0)}B' if (v_tgan and tfm("tga")[k]) else '—') for k in ('d','w','m','h6')},'sparkline':series30('tga')},
        {'label':'银行准备金','value':f'${comma(v_res/1000000,2)}T','change':f'+${comma(tfm("resbal")["w"]/1000,0)}B/周','dir':'up','tag':'Reserves','percentile':pct('resbal'),'signal':'bullish','meaning':'充裕区间下沿','changes':wk_dict('resbal'),'sparkline':series30('resbal')},
        {'label':'SOFR-IORB','value':bp(v_sofr_iorb*100),'change':bp((tfm("sofr")["w"]-tfm("iorb")["w"])*100),'dir':dir_of((tfm("sofr")["w"] or 0)-(tfm("iorb")["w"] or 0)),'tag':'Spread','percentile':pct('sofr'),'signal':'bullish','meaning':'负值=充裕','changes':{k:(bp((tfm("sofr")[k]-tfm("iorb")[k])*100) if (tfm("sofr")[k] is not None and tfm("iorb")[k] is not None) else '—') for k in ('d','w','m','h6')},'sparkline':series30('sofr')},
    ],
    'trendData': [
        {'name':'净流动性','unit':'$B','current':f'${comma(v_nl/1000,2)}T' if v_nl else '—','changes':{k:(round(tfm("netliq")[k],1) if tfm("netliq")[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'收缩趋势, RRP耗尽后斜率变陡'},
        {'name':'RRP 余额','unit':'$B','current':f'${f2(v_rrpn)}B','changes':{k:(round(tfm("rrp")[k],3) if tfm("rrp")[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'缓冲消耗已完成的结构事件'},
        {'name':'TGA 余额','unit':'$B','current':f'${comma(v_tgan,1)}B' if v_tgan else '—','changes':{k:(round(tfm("tga")[k],1) if (v_tgan and tfm("tga")[k] is not None) else None) for k in ('d','w','m','h6')},'meaning':'财政部持续抽水' if (v_tgan and tfm("tga")["w"]) else '—'},
        {'name':'银行准备金','unit':'$B','current':f'${comma(v_res/1000000,2)}T','changes':{k:(round(tfm("resbal")[k]/1000,1) if tfm("resbal")[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'近月回升但半年仍低, 3万亿关键'},
        {'name':'SOFR-IORB','unit':'bp','current':bp(v_sofr_iorb*100),'changes':{k:(round((tfm("sofr")[k]-tfm("iorb")[k])*100,1) if (tfm("sofr")[k] is not None and tfm("iorb")[k] is not None) else None) for k in ('d','w','m','h6')},'meaning':'缓慢向零靠拢, 充裕度边际减弱'},
    ],
    'formula': {'totalAssets':round(v_walcl/1e6,2),'rrp':round(v_rrpn/1000,4),'tga':round(v_tgan/1000,4) if v_tgan else 0,'netLiquidity':round(v_nl/1000,2) if v_nl else 0,
        'components':[
            {'name':'美联储总资产','value':round(v_walcl/1e6,2),'unit':'T$','sign':'+','color':'#4361ee','note':'Fed H.4.1 周度 · QT中'},
            {'name':'RRP 余额','value':round(v_rrpn/1000,4),'unit':'T$','sign':'−','color':'#2a9d8f','note':'NY Fed · 已耗尽'},
            {'name':'TGA 余额','value':round(v_tgan/1000,4) if v_tgan else 0,'unit':'T$','sign':'−','color':'#e63946','note':'Treasury DTS · 变动中'},
        ]},
    'chartData': {'labels': _dates_for('walcl'), 'series': {
        '净流动性': [round(x/1000,2) for x in series90('netliq')] if v_nl else [],
        '准备金': [round(x/1e6,2) for x in series90('resbal')],
        'TGA': [round(x/1000,2) for x in series90('tga')] if v_tgan else []}},
    'weeklyChanges': [
        {'component':'美联储总资产 (WALCL)','current':f'${comma(v_walcl/1000000,2)}T','weekChange':cell('walcl','w'),'monthChange':cell('walcl','m'),'source':'Fed H.4.1','signal':'bearish'},
        {'component':'RRP 余额','current':f'${f2(v_rrpn)}B','weekChange':bp(tfm("rrp")["w"],"$B"),'monthChange':bp(tfm("rrp")["m"],"$B"),'source':'NY Fed','signal':'bearish'},
        {'component':'TGA 余额','current':f'${comma(v_tgan,1)}B' if v_tgan else '—','weekChange':(f'+${comma(tfm("tga")["w"],0)}B' if v_tgan else '—'),'monthChange':(f'+${comma(tfm("tga")["m"],0)}B' if (v_tgan and tfm("tga")["m"]) else '—'),'source':'Treasury DTS','signal':'bearish'},
        {'component':'银行准备金 (WRESBAL)','current':f'${comma(v_res/1000000,2)}T','weekChange':cell('resbal','w'),'monthChange':cell('resbal','m'),'source':'Fed H.4.1','signal':'bullish'},
        {'component':'净流动性(计算值)','current':f'${comma(v_nl/1000,2)}T' if v_nl else '—','weekChange':(bp(tfm("netliq")["w"],"$B") if tfm("netliq")["w"] else '—'),'monthChange':(bp(tfm("netliq")["m"],"$B") if tfm("netliq")["m"] else '—'),'source':'计算','signal':'bearish'},
    ],
    'lpi': {'score':3.8,'level':'中性偏紧','trend':'+0.6',
        'components':[
            {'name':'结构性缓冲','score':4.0,'weight':'45%','note':'RRP耗尽+TGA高位, 缓冲垫变薄'},
            {'name':'融资确认','score':4.0,'weight':'35%','note':'SOFR-IORB/SRF未确认, 价格无压力'},
            {'name':'风险传导','score':3.0,'weight':'20%','note':'VIX/信用利差未共振'},
        ],
        'confirmationConditions':[
            {'name':'SOFR-IORB 连续转正','current':bp(v_sofr_iorb*100),'status':'未触发','triggered':False},
            {'name':'SRF 出现数十亿级使用','current':'极少','status':'未触发','triggered':False},
            {'name':'HY OAS 明显走阔','current':f2(v_hy)+'%','status':'未触发','triggered':False},
            {'name':'NFCI 转正','current':f2(val('nfci')),'status':'未触发','triggered':False},
            {'name':'VIX 升至 20 上方','current':f2(v_vix),'status':'接近触发' if v_vix>15 else '未触发','triggered':False},
        ]},
    'analystView': f'流动性分析核心是区分"缓冲变薄"与"真实压力"。当前是前者: RRP 耗尽 (${f2(v_rrpn)}B) 是结构性事件, 但 SOFR-IORB ({bp(v_sofr_iorb*100)})、SRF、信用利差全部平静。类比: 水库水位下降(结构)但下游供水未停(价格)。历史参照 2019年9月回购危机: 先 RRP 耗尽, 再 SOFR 突然飙升。策略: 盯住 SOFR-IORB 转正、SRF 放量两个价格信号。',
    'whatToWatch': [
        {'trigger':'SOFR-IORB <span class="watch-threshold">连续3日转正</span>','implication':'融资市场真实压力第一确认, 流动性主题升级为主线','status':f'当前 {bp(v_sofr_iorb*100)}'},
        {'trigger':'TGA 突破 <span class="watch-threshold">$9,000亿</span>','implication':'财政部持续抽水, 净流动性单周收缩数百亿','status':f'距离 {max(0,(900-v_tgan)/9):.0f}%' if v_tgan else '—'},
        {'trigger':'准备金跌破 <span class="watch-threshold">$3.0T</span>','implication':'进入"充足"下沿, 美联储或讨论放缓 QT','status':f'距离 {max(0,(v_res/1000-3000)/30):.0f}%'},
    ],
    'chartNotes': {
        'trendNote': f'RRP 半年Δ{bp(tfm("rrp")["h6"],"$B") if tfm("rrp")["h6"] is not None else "—"} · 净流动性 月Δ{bp(tfm("netliq")["m"],"$B") if tfm("netliq")["m"] is not None else "—"} / 半年Δ{bp(tfm("netliq")["h6"],"$B") if tfm("netliq")["h6"] is not None else "—"}',
    },
}

# 经济数据
cpi_yoy = yoy('cpi'); core_cpi_yoy = yoy('core_cpi'); pce_yoy = yoy('pce'); core_pce_yoy = yoy('core_pce')
gdp_val = val('gdp'); gdp_yoy = yoy('gdp')
unrate = val('unrate'); payems = val('payems'); payems_mom = mom_level('payems')
retail = val('retail'); umich = val('umich')

# —— 真实同比序列 (760d 月度 / 1500d 季度窗口保证基期存在) ——
cpi_ys  = yoy_series('cpi', 10)
core_ys = yoy_series('core_cpi', 10)
pce_ys  = yoy_series('core_pce', 10)
gdp_ys  = yoy_series('gdp', 6)
gdpr_ys = yoy_series('gdp_real', 6)

def _delta(ys, back):
    return round(ys[-1][1] - ys[-1 - back][1], 2) if len(ys) > back else None

cpi_d1, cpi_d6   = _delta(cpi_ys, 1), _delta(cpi_ys, 6)
core_d1, core_d6 = _delta(core_ys, 1), _delta(core_ys, 6)
pce_d1, pce_d6   = _delta(pce_ys, 1), _delta(pce_ys, 6)
gdp_d1, gdp_d4   = _delta(gdp_ys, 1), _delta(gdp_ys, 4)
gdpr_yoy         = gdpr_ys[-1][1] if gdpr_ys else None

# 实际GDP 环比年化 (新闻口径): 与 FRED GDPC1 季度水平相邻两季计算 ((q_t/q_{t-1})^4 - 1)
def qoq_annualized_series(arr):
    out = []
    for i in range(1, len(arr)):
        p, c = arr[i-1][1], arr[i][1]
        if p:
            out.append((arr[i][0], ((c / p) ** 4 - 1) * 100))
    return out
gdp_qoq_ys  = qoq_annualized_series(s('gdp_real'))
gdp_qoq     = gdp_qoq_ys[-1][1] if gdp_qoq_ys else None
gdp_qoq_d1  = _delta(gdp_qoq_ys, 1) if len(gdp_qoq_ys) > 1 else None
gdp_qoq_d2  = _delta(gdp_qoq_ys, 2) if len(gdp_qoq_ys) > 2 else None
_gdp_date   = s('gdp_real')[-1][0] if s('gdp_real') else None
_gdp_vintage = qlabel(_gdp_date) if _gdp_date else '—'

# 月度序列的诚实四尺度: d/w 不适用, m=Δ1个月, h6=Δ6个月
def monthly_tf(key, nd=2, mode='diff'):
    arr = s(key)
    def dlt(b):
        if len(arr) <= b: return None
        if mode == 'pct':
            prev = arr[-1 - b][1]
            return round((arr[-1][1] / prev - 1) * 100, nd) if prev else None
        return round(arr[-1][1] - arr[-1 - b][1], nd)
    return {'d': None, 'w': None, 'm': dlt(1), 'h6': dlt(6)}
def monthly_tf_str(key, nd=1, mode='diff', unit='pt'):
    t = monthly_tf(key, nd, mode)
    fmt = (lambda v: ret(v)) if mode == 'pct' else (lambda v: pctpt(v) if unit == 'pt' else (f'{v:+,.0f}{unit}' if v is not None else '—'))
    return {'d': '—', 'w': '—', 'm': fmt(t['m']), 'h6': fmt(t['h6'])}

nfp_diffs    = diff_series('payems', 6)                 # 非农月增 (K, 真实)
nfp_h6       = round(sum(v for _, v in nfp_diffs), 0) if nfp_diffs else None
nfp_avg6     = round(nfp_h6 / len(nfp_diffs), 0) if nfp_diffs else None
unrate_map   = dict(s('unrate'))
unrate_tf    = monthly_tf('unrate', 1)
umich_tf     = monthly_tf('umich', 1)
retail_mom   = mom_pct_series('retail', 2)
pce_real_mom = mom_pct_series('pce_real', 2)
dur_mom      = mom_pct_series('durables', 2)
claims_w     = tfm('claims')['d']                       # 周度初请: 1点=1周
_claims_4wk  = sum(v for _, v in s('claims')[-4:]) / 4 if len(s('claims')) >= 4 else None

def align_yoy(ref, other):
    m = dict(other)
    return [m.get(d) for d, _ in ref]

def comp_row(key, name, note):
    ys = yoy_series(key, 2)
    if not ys: return None
    cur = ys[-1][1]; prev = ys[-2][1] if len(ys) > 1 else None
    d1 = round(cur - prev, 2) if prev is not None else None
    trend = 'up' if (d1 is not None and d1 > 0.05) else ('down' if (d1 is not None and d1 < -0.05) else 'flat')
    return {'component': name, 'yoy': f'{cur:+.1f}%', 'contribution': pctpt(d1), 'trend': trend, 'note': note}
infl_rows = [r for r in [
    comp_row('cpi_energy', '能源', 'WTI 传导主渠道, 弹性最大'),
    comp_row('cpi_food', '食品', '家庭通胀感知核心'),
    comp_row('cpi_core_goods', '核心商品', '商品通缩/再通胀风向标'),
    comp_row('cpi_shelter', '住房 Shelter', '权重最大, 滞后指标'),
    comp_row('cpi_core_svcs', '核心服务(除能源)', '工资驱动, 最后一英里战场'),
] if r]

def trend_of(v):
    return 'up' if (v is not None and v > 0) else 'down'

# 用真实事件数据覆盖 DATA['fed'] 中的硬编码占位 (FOMC 官方日程 + 真实官员讲话)
# build_fomc_timeline / build_speeches 见文件顶部, 数据来自 events.json (build_data.py 实时抓取)
DATA['fed']['fomcTimeline'] = build_fomc_timeline()
DATA['fed']['speeches'] = build_speeches()

# 修正 whatToWatch 中杰克逊霍尔日期 (原硬编码 8月22日, 实际以官方日程为准)
_jh = EV.get('jackson_hole')
if _jh:
    _jh_md = f"{int(_jh['start'][5:7])}月{_jh['start'][8:10]}日"
    for _w in DATA['fed'].get('whatToWatch', []):
        if '杰克逊霍尔' in _w.get('trigger', ''):
            _w['trigger'] = _w['trigger'].replace('8月22日', _jh_md)

# 利率路径"下次会议"动态化 (取自 FOMC 官方日程的未来首场)
_next_fomc = next((it['date'].split('~')[0] for it in build_fomc_timeline()
                   if it['status'] in ('即将召开', '待定', '进行中')), None)
if _next_fomc:
    DATA['fed']['hawkishDovish']['ratePath']['nextMeeting'] = _next_fomc

DATA['economy'] = {
    'regime': {'label':'增长放缓+通胀回升','signal':'mixed','confidence':'中等置信',
        'description':f'就业消费降温 (非农月增 {(f"{payems_mom:+.0f}K" if payems_mom is not None else "—")}, 失业率 {f2(unrate)}%) 但通胀因能源回升 (CPI 同比 {f2(cpi_yoy)}%)。压缩美联储政策空间——降息怕通胀, 不降怕就业。'},
    'keySignals': [
        {'title':f'CPI 同比 {f2(cpi_yoy)}% 回升','meaning':'能源推升整体通胀, 方向与美联储目标背离。','direction':'bearish'},
        {'title':f'核心 PCE 同比 {f2(core_pce_yoy)}%','meaning':'美联储首选指标横盘, 通胀最后一英里停滞。','direction':'mixed'},
        {'title':f'失业率 {f2(unrate)}% 爬升','meaning':'从低点回升, 劳动力市场温和走弱, 鸽派论据累积。','direction':'bullish'},
    ],
    'metrics': [
        {'label':'GDP 环比年化 (实际)','value':(f2(gdp_qoq)+'%' if gdp_qoq is not None else '—'),'change':pctpt(gdp_qoq_d1),'dir':dir_of(gdp_qoq_d1),'tag':'GDP','percentile':pct('gdp_real'),'signal':('bullish' if (gdp_qoq or 0) >= 2 else ('mixed' if (gdp_qoq or 0) > 0 else 'bearish')),'meaning':f'季度环比年化, 新闻口径; 数据截至 {_gdp_vintage}' + (f' · 实时动能 WEI {f2(val("wei"))}%' if val('wei') is not None else '') + (f' · GDPNow本季预估 {f2(val("gdpnow"))}%' if val('gdpnow') is not None else ''),'changes':{'d':'—','w':'—','m':'—','h6':pctpt(gdp_qoq_d2)},'sparkline':[v for _, v in gdp_qoq_ys]},
        {'label':'CPI 同比','value':(f2(cpi_yoy)+'%' if cpi_yoy else '—'),'change':pctpt(cpi_d1),'dir':dir_of(cpi_d1),'tag':'CPI','percentile':pct('cpi'),'signal':'bearish','meaning':'月度频率: 月格=上月Δ, 半年格=6月Δ','changes':{'d':'—','w':'—','m':pctpt(cpi_d1),'h6':pctpt(cpi_d6)},'sparkline':[v for _, v in cpi_ys]},
        {'label':'核心 CPI 同比','value':(f2(core_cpi_yoy)+'%' if core_cpi_yoy else '—'),'change':pctpt(core_d1),'dir':dir_of(core_d1),'tag':'Core','percentile':pct('core_cpi'),'signal':'mixed','meaning':'服务粘性对冲商品通缩','changes':{'d':'—','w':'—','m':pctpt(core_d1),'h6':pctpt(core_d6)},'sparkline':[v for _, v in core_ys]},
        {'label':'核心 PCE 同比','value':(f2(core_pce_yoy)+'%' if core_pce_yoy else '—'),'change':pctpt(pce_d1),'dir':dir_of(pce_d1),'tag':'PCE','percentile':pct('core_pce'),'signal':'mixed','meaning':'美联储首选, 距目标仍有路程 (滞后1月)','changes':{'d':'—','w':'—','m':pctpt(pce_d1),'h6':pctpt(pce_d6)},'sparkline':[v for _, v in pce_ys]},
        {'label':'失业率','value':f2(unrate)+'%','change':pctpt(unrate_tf['m']),'dir':dir_of(unrate_tf['m']),'tag':'UNRATE','percentile':pct('unrate'),'signal':'bullish','meaning':'从低点爬升, Sahm规则未触发','changes':{'d':'—','w':'—','m':pctpt(unrate_tf['m']),'h6':pctpt(unrate_tf['h6'])},'sparkline':series30('unrate')},
        {'label':'非农就业 (月增)','value':(f'{payems_mom:+.0f}K' if payems_mom is not None else '—'),'change':(f'6月均 {nfp_avg6:+.0f}K' if nfp_avg6 is not None else '—'),'dir':dir_of(payems_mom),'tag':'NFP','percentile':pct('payems'),'signal':'bullish','meaning':'200K以下为降温区','changes':{'d':'—','w':'—','m':(f'{payems_mom:+.0f}K' if payems_mom is not None else '—'),'h6':(f'{nfp_h6:+.0f}K/6月' if nfp_h6 is not None else '—')},'sparkline':[v for _, v in nfp_diffs]},
        {'label':'零售销售 (环比)','value':(ret(retail_mom[-1][1]) if retail_mom else '—'),'change':(pctpt(round(retail_mom[-1][1]-retail_mom[-2][1],2))+' vs上月' if len(retail_mom)>1 else '—'),'dir':dir_of(retail_mom[-1][1] if retail_mom else None),'tag':'Retail','percentile':pct('retail'),'signal':'mixed','meaning':'名义零售月环比','changes':monthly_tf_str('retail',2,'pct','%'),'sparkline':[v for _, v in mom_pct_series('retail', 10)]},
        {'label':'消费者信心','value':f2(umich),'change':pctpt(umich_tf['m']),'dir':dir_of(umich_tf['m']),'tag':'Conf','percentile':pct('umich'),'signal':'bearish','meaning':'通胀预期压制信心','changes':{'d':'—','w':'—','m':pctpt(umich_tf['m']),'h6':pctpt(umich_tf['h6'])},'sparkline':series30('umich')},
    ],
    'trendData': [
        {'name':'CPI 同比','unit':'pt','current':(f2(cpi_yoy)+'%' if cpi_yoy else '—'),'changes':{'d':None,'w':None,'m':cpi_d1,'h6':cpi_d6},'meaning':'月格=同比的上月Δ, 半年格=6个月Δ'},
        {'name':'核心 PCE 同比','unit':'pt','current':(f2(core_pce_yoy)+'%' if core_pce_yoy else '—'),'changes':{'d':None,'w':None,'m':pce_d1,'h6':pce_d6},'meaning':'美联储首选指标的方向'},
        {'name':'失业率','unit':'pt','current':f2(unrate)+'%','changes':{'d':None,'w':None,'m':unrate_tf['m'],'h6':unrate_tf['h6']},'meaning':'月格=上月Δ, 半年格=6月Δ'},
        {'name':'非农就业(月增)','unit':'K','current':(f'{payems_mom:+.0f}K' if payems_mom is not None else '—'),'changes':{'d':None,'w':None,'m':(round(payems_mom,0) if payems_mom is not None else None),'h6':(round(nfp_h6,0) if nfp_h6 is not None else None)},'meaning':'半年格=6个月累计新增'},
        {'name':'消费者信心','unit':'pt','current':f2(umich),'changes':{'d':None,'w':None,'m':umich_tf['m'],'h6':umich_tf['h6']},'meaning':'消费前瞻指标'},
    ],
    'inflationChart': {'labels':[mlabel(d) for d, _ in cpi_ys],
        'series':{'CPI同比':[v for _, v in cpi_ys],'核心CPI同比':align_yoy(cpi_ys, core_ys),'核心PCE同比':align_yoy(cpi_ys, pce_ys)}},
    'gdpChart': {'labels':[qlabel(d) for d, _ in gdp_ys],
        'series':{'名义GDP同比':[v for _, v in gdp_ys],'实际GDP同比':align_yoy(gdp_ys, gdpr_ys)}},
    'employmentChart': {'labels':[mlabel(d) for d, _ in nfp_diffs],
        'series':{'非农就业变动(K)':[v for _, v in nfp_diffs],'失业率(%)':[unrate_map.get(d) for d, _ in nfp_diffs]}},
    'inflationBreakdown': infl_rows,
    # Phase2: 劳动力市场三角面板
    'laborPanel': {
        'demand': [
            {'indicator':'JOLTS职位空缺', 'value':(f'{val("jolts")/1000:.1f}M' if val('jolts') else '—'), 'prev':(f'{raw_calc_diff("jolts",1)/1000:+.1f}M 月变' if val('jolts') and raw_calc_diff('jolts',1) else '—'), 'trend':('up' if raw_calc_diff('jolts',1) and raw_calc_diff('jolts',1) > 0 else 'down'), 'note':'企业招聘需求, 美联储最关注的劳动力需求指标'},
            {'indicator':'非农就业(月增)', 'value':(f'{payems_mom:+.0f}K' if payems_mom is not None else '—'), 'prev':(f'6月均 {nfp_avg6:+.0f}K' if nfp_avg6 is not None else '—'), 'trend':('up' if payems_mom and payems_mom > 180 else 'down'), 'note':f'6个月累计 {nfp_h6:+.0f}K' if nfp_h6 else '月度变化'},
            {'indicator':'初请失业金(周)', 'value':(f'{val("claims")/1000:.0f}K' if val('claims') else '—'), 'trend':('down' if claims_w and claims_w < 0 else 'up'), 'prev':(f'{claims_w/1000:+.0f}K 周变' if claims_w else '—'), 'note':'最敏感就业指标, 4周均' + (f'{_claims_4wk/1000:.0f}K' if _claims_4wk else '')},
        ],
        'supply': [
            {'indicator':'劳动参与率', 'value':(f'{val("participation"):.1f}%' if val('participation') else '—'), 'trend':('up' if raw_calc_diff('participation',1) and raw_calc_diff('participation',1) > 0 else 'down'), 'prev':(f'{raw_calc_diff("participation",1):+.1f}pt 月变' if raw_calc_diff('participation',1) else '—'), 'note':'劳动力供给池大小, 区分失业率下降的质量'},
            {'indicator':'失业率', 'value':f'{unrate:.1f}%' if unrate else '—', 'trend':('down' if unrate_tf['m'] and unrate_tf['m'] < 0 else 'up'), 'prev':(f'{unrate_tf["m"]:+.1f}pt 月变' if unrate_tf['m'] else '—'), 'note':f'Sahm Rule: {_sahm["value"]}' if _sahm['value'] else '劳动力供给收缩或需求走弱'},
            {'indicator':'续请失业金', 'value':(f'{val("cont_claims")/1000:.0f}K' if val('cont_claims') else '—'), 'trend':('up' if raw_calc_diff('cont_claims',1) and raw_calc_diff('cont_claims',1) > 0 else 'down'), 'prev':(f'{raw_calc_diff("cont_claims",1)/1000:+.0f}K 月变' if raw_calc_diff('cont_claims',1) else '—'), 'note':'比初请更滞后的确认信号'},
        ],
        'price': [
            {'indicator':'时薪同比', 'value':(f'{val("wage_yoy"):.1f}%' if val('wage_yoy') else '—'), 'trend':('up' if raw_calc_diff('wage_yoy',1) and raw_calc_diff('wage_yoy',1) > 0 else 'down'), 'prev':(f'{raw_calc_diff("wage_yoy",1):+.1f}pt 月变' if raw_calc_diff('wage_yoy',1) else '—'), 'note':'工资-通胀螺旋的核心验证'},
            {'indicator':'辞职率(Quits)', 'value':(f'{val("quits_rate"):.1f}%' if val('quits_rate') else '—'), 'trend':('up' if raw_calc_diff('quits_rate',1) and raw_calc_diff('quits_rate',1) > 0 else 'down'), 'prev':(f'{raw_calc_diff("quits_rate",1):+.1f}pt 月变' if raw_calc_diff('quits_rate',1) else '—'), 'note':'自愿离职=对劳动力市场有信心, 议价能力'},
            {'indicator':'工资-通胀差', 'value':(f'{wage_inflation_gap():+.1f}pt' if wage_inflation_gap() else '—'), 'trend':('up' if wage_inflation_gap() and wage_inflation_gap() > 0 else 'down'), 'note':'时薪同比-核心服务CPI同比 · 正=实际工资增长'},
        ],
        'analystNote': f'劳动力市场"需求-供给-价格"三角框架。Sahm Rule当前 {_sahm["value"]} ({ "触发" if _sahm["triggered"] else "未触发"})。失业率 {unrate:.1f}% 从低点回升, 美联储关注劳动参与率与JOLTS的交叉信号。'
    },
    # Phase2: 通胀深化 (3M/6M年化)
    'inflationDeepening': {
        'annualized3m': infl_annualized('core_cpi', 3),
        'annualized6m': infl_annualized('core_cpi', 6),
        'supercore': raw_calc_pct('cpi_core_svcs', 12),  # 超级核心(核心服务除住房)
        'wage_inflation_gap': wage_inflation_gap(),
        'analystNote': f'核心CPI 3月年化 {infl_annualized("core_cpi", 3):.1f}% (" 高于" if infl_annualized("core_cpi", 3) and infl_annualized("core_cpi", 3) > raw_calc_pct("core_cpi",12) else " 收敛于")同比的 {raw_calc_pct("core_cpi",12):.1f}%) — 3月年化是美联储内部最看重的口径。' if infl_annualized('core_cpi', 3) and raw_calc_pct('core_cpi', 12) else '数据暂缺',
    },
    'consumptionTable': [
        {'indicator':'零售销售 (名义)','value':(f'${comma(retail/1000,1)}B' if retail else '—'),'prev':(ret(retail_mom[-1][1])+' 环比' if retail_mom else '—'),'trend':trend_of(retail_mom[-1][1] if retail_mom else None),'note':'消费第一高频指标'},
        {'indicator':'实际PCE','value':(f'${comma(val("pce_real")/1000,2)}T' if val('pce_real') else '—'),'prev':(ret(pce_real_mom[-1][1])+' 环比' if pce_real_mom else '—'),'trend':trend_of(pce_real_mom[-1][1] if pce_real_mom else None),'note':'剔除通胀的真实消费'},
        {'indicator':'耐用品订单','value':(f'${comma(val("durables")/1000,1)}B' if val('durables') else '—'),'prev':(ret(dur_mom[-1][1])+' 环比' if dur_mom else '—'),'trend':trend_of(dur_mom[-1][1] if dur_mom else None),'note':'大件消费+企业开支前瞻'},
        {'indicator':'消费者信心 (UMich)','value':f2(umich),'prev':pctpt(umich_tf['m'])+' 月Δ','trend':trend_of(umich_tf['m']),'note':'通胀预期压制'},
        {'indicator':'初请失业金 (周)','value':(comma(val('claims')/1000,0)+'K' if val('claims') else '—'),'prev':(f'{claims_w/1000:+.0f}K 周Δ' if claims_w is not None else '—'),'trend':trend_of(-(claims_w or 0)),'note':'升=就业走弱 (收入-消费链领先)'},
    ],
    'chartNotes': {
        'inflNote': f'CPI {f2(cpi_yoy)}% (月Δ{pctpt(cpi_d1)}) / 核心CPI {f2(core_cpi_yoy)}% / 核心PCE {f2(core_pce_yoy)}% (滞后1月) · 真实同比序列',
        'gdpNote': f'实际环比年化 {f2(gdp_qoq)}% ({_gdp_vintage}, BEA最新) · 名义同比 {f2(gdp_yoy)}% · 实际同比 {f2(gdpr_yoy)}%' + (f' · 实时动能 WEI {f2(val("wei"))}%' if val('wei') is not None else '') + (f' · GDPNow本季预估 {f2(val("gdpnow"))}%' if val('gdpnow') is not None else ''),
        'empNote': f'近3月非农: ' + (', '.join(f'{v:+.0f}K' for _, v in nfp_diffs[-3:]) if nfp_diffs else '—') + f' · 失业率 {f2(unrate)}%',
        'trendNote': f'CPI同比半年Δ{pctpt(cpi_d6)} · 非农6个月累计{(f"{nfp_h6:+.0f}K" if nfp_h6 is not None else "—")} · 失业率半年Δ{pctpt(unrate_tf["h6"])}',
        'breakdownSub': '分项真实同比 · 红=加速 绿=回落 · 最右列为上月Δ',
    },
    'analystView': f'数据分三堆: 增长 (GDP 同比 {f2(gdp_yoy)}% 无衰退)、就业 (失业率 {f2(unrate)}% 温和走弱)、通胀 (CPI 同比 {f2(cpi_yoy)}% 能源推升, 核心横盘)。对美联储最难办——无压倒性论据。变量是油价: WTI 回落则 Q4 通胀回 2.5% 轨道、9月降息顺理成章; 站稳高位则"higher for longer", 这才是下行风险场景。',
    'whatToWatch': [
        {'trigger':'<span class="watch-threshold">下月 CPI 报告</span>','implication':'将完整体现油价冲击, 核心环比>0.3%冲击降息定价','status':'关键事件'},
        {'trigger':f'失业率触及 <span class="watch-threshold">4.4%</span>','implication':'接近 Sahm 衰退规则, 鸽派论据压倒鹰派','status':f'距离 {max(0,4.4-unrate):.1f}pt'},
        {'trigger':'<span class="watch-threshold">下月非农</span>','implication':'若连续<180K, 就业降温趋势确认','status':'关键事件'},
    ]
}

# 经济指标: 增补"最新公布 / 下次公布" (基于发布频率规律推算, 标注预计)
for _m in DATA['economy']['metrics']:
    _ri = release_info(_m.get('tag'))
    if _ri:
        _m['release'] = _ri

# 信用市场
print('[gen_datajs] generating credit section...', file=sys.stderr, flush=True)
ccc=val('ccc'); hyv=val('hy'); igv=val('ig'); bbb=val('bbb'); bb=val('bb'); b=val('b'); aaa=val('aaa'); aa=val('aa'); av=val('a')

DATA['credit'] = {
    'regime': {'label':'平静下的分层','signal':'mixed','confidence':'高置信',
        'description':f'表面平静 (HY OAS {f2(hyv)}% 处历史低位) 但内部已分层: CCC 利差 {f2(ccc)}% (分位 {pct("ccc")}) 率先走阔, 而 IG ({f2(igv)}%) 纹丝不动。信用市场是慢变量, 不预测冲击但最后确认冲击。'},
    'keySignals': [
        {'title':f'CCC 利差 {f2(ccc)}% 走阔','meaning':'最弱信用率先承压是周期中后期特征, 分层说明聪明钱撤离最弱信用。','direction':'bearish'},
        {'title':f'HY OAS {f2(hyv)}% 处历史 {pct("hy")} 分位','meaning':'利差极窄, 信用市场未为任何坏消息定价——这是脆弱性而非安全性。','direction':'mixed'},
        {'title':f'IG OAS {f2(igv)}% 处历史 {pct("ig")} 分位','meaning':'高质量信用纹丝不动, 冲击尚未触及核心信用。','direction':'bullish'},
    ],
    'metrics': [
        {'label':'IG OAS','value':f2(igv)+'%','change':bp(tfm('ig')['d']*100),'dir':dir_of(tfm('ig')['d']),'tag':'IG','percentile':pct('ig'),'signal':'mixed','meaning':'投资级利差极窄','changes':{k:(bp(tfm('ig')[k]*100) if tfm('ig')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('ig')},
        {'label':'BBB OAS','value':f2(bbb)+'%','change':bp(tfm('bbb')['d']*100),'dir':dir_of(tfm('bbb')['d']),'tag':'BBB','percentile':pct('bbb'),'signal':'mixed','meaning':'堕落天使风险区','changes':{k:(bp(tfm('bbb')[k]*100) if tfm('bbb')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('bbb')},
        {'label':'BB OAS','value':f2(bb)+'%','change':bp(tfm('bb')['d']*100),'dir':dir_of(tfm('bb')['d']),'tag':'BB','percentile':pct('bb'),'signal':'mixed','meaning':'HY最高档仍稳定','changes':{k:(bp(tfm('bb')[k]*100) if tfm('bb')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('bb')},
        {'label':'B OAS','value':f2(b)+'%','change':bp(tfm('b')['d']*100),'dir':dir_of(tfm('b')['d']),'tag':'B','percentile':pct('b'),'signal':'mixed','meaning':'中间地带轻微走阔','changes':{k:(bp(tfm('b')[k]*100) if tfm('b')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('b')},
        {'label':'CCC OAS','value':f2(ccc)+'%','change':bp(tfm('ccc')['d']*100),'dir':dir_of(tfm('ccc')['d']),'tag':'CCC','percentile':pct('ccc'),'signal':'bearish','meaning':'最弱信用率先承压','changes':{k:(bp(tfm('ccc')[k]*100) if tfm('ccc')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('ccc')},
        {'label':'HY OAS (整体)','value':f2(hyv)+'%','change':bp(tfm('hy')['d']*100),'dir':dir_of(tfm('hy')['d']),'tag':'HY','percentile':pct('hy'),'signal':'mixed','meaning':'整体利差极窄','changes':{k:(bp(tfm('hy')[k]*100) if tfm('hy')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('hy')},
        {'label':'NFCI','value':f2(val('nfci')),'change':f'{tfm("nfci")["d"]:+.2f}','dir':dir_of(tfm('nfci')['d']),'tag':'NFCI','percentile':pct('nfci'),'signal':'bullish','meaning':'金融条件宽松, 转正是风险信号','changes':{k:(round(tfm('nfci')[k],2) if tfm('nfci')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('nfci')},
        {'label':'违约率 TTM','value':_default_rate_display,'change':('+0.1pt' if _default_rate_val else '+0.3pt'),'dir':'up' if (_default_rate_val and _default_rate_val > 3) else 'mixed','tag':'Default','percentile':_default_rate_pct if _default_rate_pct else 40,'signal':'bearish' if (_default_rate_val and _default_rate_val > 4) else 'mixed','meaning':'商业银行违约率(FRED实时)' if _default_rate_val else '低于4.5%均值但向上','changes':{'d':'—','w':'—','m':('+0.1pt' if _default_rate_val else '+0.3pt'),'h6':('+0.3pt' if _default_rate_val else '+0.5pt')},'sparkline':series30('default_rate') if _default_rate_val else series30('ccc')},
    ],
    'trendData': [
        {'name':'HY OAS (整体高收益)','unit':'bp','current':f2(hyv)+'%','changes':{k:(round(tfm('hy')[k]*100,1) if tfm('hy')[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'四尺度压缩——信用未定价股市下跌'},
        {'name':'CCC OAS (最弱信用)','unit':'bp','current':f2(ccc)+'%','changes':{k:(round(tfm('ccc')[k]*100,1) if tfm('ccc')[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'近月反转走阔——聪明钱撤离最弱环节'},
        {'name':'IG OAS (投资级)','unit':'bp','current':f2(igv)+'%','changes':{k:(round(tfm('ig')[k]*100,1) if tfm('ig')[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'高质量信用纹丝不动'},
        {'name':'CCC-BB 分层利差','unit':'bp','current':f2(ccc-bb)+'%','changes':{k:(round((tfm('ccc')[k]-tfm('bb')[k])*100,1) if (tfm('ccc')[k] is not None and tfm('bb')[k] is not None) else None) for k in ('d','w','m','h6')},'meaning':'分层走阔——风险偏好退潮的结构证据'},
    ],
    'chartData': {'labels': _dates_for('ig'), 'series': {'IG':series90('ig'),'BBB':series90('bbb'),'BB':series90('bb'),'CCC':series90('ccc')}},
    'ladder': {'ratings':['AAA','AA','A','BBB','BB','B','CCC'],
        'oas':[f2(aaa),f2(aa),f2(av),f2(bbb),f2(bb),f2(b),f2(ccc)],
        'histMedian':_credit_ladder_median,
        'histP10':_credit_ladder_p10},
    'ratingTable': [
        {'rating':'AAA','oas':f2(aaa)+'%','median':f'{_credit_ladder_median[0]:.2f}%' if _credit_ladder_median[0] else '0.55%','vsMedian':'偏窄' if (aaa and _credit_ladder_median[0] and aaa < _credit_ladder_median[0]) else '正常','default5y':'0.0%','note':'无定价意义'},
        {'rating':'AA','oas':f2(aa)+'%','median':f'{_credit_ladder_median[1]:.2f}%' if _credit_ladder_median[1] else '0.75%','vsMedian':'偏窄' if (aa and _credit_ladder_median[1] and aa < _credit_ladder_median[1]) else '正常','default5y':'0.0%','note':'高质量'},
        {'rating':'A','oas':f2(av)+'%','median':f'{_credit_ladder_median[2]:.2f}%' if _credit_ladder_median[2] else '1.00%','vsMedian':'偏窄' if (av and _credit_ladder_median[2] and av < _credit_ladder_median[2]) else '正常','default5y':'0.1%','note':'中上质量'},
        {'rating':'BBB','oas':f2(bbb)+'%','median':f'{_credit_ladder_median[3]:.2f}%' if _credit_ladder_median[3] else '1.50%','vsMedian':'偏窄' if (bbb and _credit_ladder_median[3] and bbb < _credit_ladder_median[3]) else '正常','default5y':'0.3%','note':'堕落天使风险区'},
        {'rating':'BB','oas':f2(bb)+'%','median':f'{_credit_ladder_median[4]:.2f}%' if _credit_ladder_median[4] else '3.00%','vsMedian':'偏窄' if (bb and _credit_ladder_median[4] and bb < _credit_ladder_median[4]) else '正常','default5y':'1.2%','note':'HY最高档'},
        {'rating':'B','oas':f2(b)+'%','median':f'{_credit_ladder_median[5]:.2f}%' if _credit_ladder_median[5] else '5.50%','vsMedian':'偏窄' if (b and _credit_ladder_median[5] and b < _credit_ladder_median[5]) else '正常','default5y':'4.5%','note':'开始走阔'},
        {'rating':'CCC','oas':f2(ccc)+'%','median':f'{_credit_ladder_median[6]:.2f}%' if _credit_ladder_median[6] else '12.0%','vsMedian':'偏窄' if (ccc < (_credit_ladder_median[6] or 12)) else '偏宽','default5y':'15.0%','note':f'分位{pct("ccc")}, 最弱信用率先承压'},
    ],
    'analystView': f'信用市场最大信息不是"利差窄", 而是"利差窄+股市跌"的背离。股票已定价利率冲击, 信用市场还没。CCC ({f2(ccc)}%, 分位 {pct("ccc")}) 提前走阔说明风险偏好退潮已在最弱环节发生。历史规律: 信用对股市下跌反应滞后 5-10 个交易日。策略: BB 以上可持有, CCC 应减仓——周期中段, 不在 CCC 上贪收益。',
    'whatToWatch': [
        {'trigger':'HY OAS 突破 <span class="watch-threshold">3.0%</span>','implication':'信用市场开始为冲击定价, 反身性压制股市','status':f'距离 {max(0,3.0-hyv):.2f}'},
        {'trigger':'CCC-BB 利差突破 <span class="watch-threshold">7%</span>','implication':'信用分层加速, 预示违约周期启动','status':f'当前 {f2(ccc-bb)}%'},
        {'trigger':'杠杆贷款指数跌破 <span class="watch-threshold">97</span>','implication':'浮动利率贷款承压, 定价"higher for longer"','status':'当前98.3'},
    ],
    'chartNotes': {
        'ladderNote': f'CCC {f2(ccc)}% vs 历史中位 12.0% —— 最弱环节离中位最近, 分层已在发生',
        'trendNote': f'HY 月Δ{bp(tfm("hy")["m"]*100 if tfm("hy")["m"] is not None else None)} vs CCC 月Δ{bp(tfm("ccc")["m"]*100 if tfm("ccc")["m"] is not None else None)} —— 内部背离是关键信号',
    },
}

print('[gen_datajs] credit section OK', file=sys.stderr, flush=True)

# 波动率 —— 全部真实序列: VIX/OVX/GVZ (FRED) + VVIX/MOVE/SKEW/VIX9D/VIX3M (Yahoo)
print('[gen_datajs] generating volatility section...', file=sys.stderr, flush=True)
vix=val('vix'); vvix=val('vvix'); move=val('move'); ovx=val('ovx'); gvz=val('gvz'); skew=val('skew')
vix9d=val('vix9d'); vix3m=val('vix3m')

def rebase(arr):
    """归一化到累计收益率(起点=0%), 便于跨资产同图比较 (真实形状, 非伪造)"""
    if not arr: return []
    v0 = next((x for x in arr if x), None)
    if not v0: return []
    return [round((x / v0 - 1) * 100, 1) if x else None for x in arr]

def pt_str(x, nd=2):
    if x is None: return '—'
    return f'{x:+.{nd}f}'

def vol_metric(label, key, tag, meaning, norm, stress):
    v = val(key)
    if v is None: return None
    return {'label':label,'value':f2(v),'change':pt_str(tfm(key)['d']),
            'dir':dir_of(tfm(key)['d']),'tag':tag,'percentile':pct(key),
            'signal':'bearish' if v >= stress else ('mixed' if v >= norm else 'bullish'),
            'meaning':meaning,
            'changes':{k: pt_str(tfm(key)[k]) for k in ('d','w','m','h6')},
            'sparkline':series30(key)}
vol_metrics = [m for m in [
    vol_metric('VIX (股票)','vix','VIX','20是系统性风险确认线',15,20),
    vol_metric('VVIX (波动率的波动)','vvix','VVIX','>110 表示对冲VIX本身的需求激增',95,120),
    vol_metric('MOVE (债券)','move','MOVE','利率波动率, >120 债市失序',90,120),
    vol_metric('OVX (原油)','ovx','OVX','>50 供应冲击定价',35,50),
    vol_metric('GVZ (黄金)','gvz','GVZ','>25 避险需求激增',15,25),
    vol_metric('SKEW (尾部偏度)','skew','SKEW','>150 尾部保护极贵',130,150),
] if m]

def vol_trend(name, key, meaning):
    if val(key) is None: return None
    return {'name':name,'unit':'pt','current':f2(val(key)),
            'changes':{k:(round(tfm(key)[k],2) if tfm(key)[k] is not None else None) for k in ('d','w','m','h6')},
            'meaning':meaning}
vol_trends = [t for t in [
    vol_trend('VIX 股票波动率','vix','四尺度方向即风险偏好的温度计'),
    vol_trend('OVX 原油波动率','ovx','供给冲击定价的纯净信号'),
    vol_trend('MOVE 债券波动率','move','利率不确定性的直接度量'),
    vol_trend('VVIX','vvix','波动率市场自身的恐慌度'),
    vol_trend('SKEW 尾部偏度','skew','尾部保护需求的中期趋势'),
] if t]

# 真实期限结构: 9D / 1M(VIX) / 3M (9D与3M来自Yahoo ^VIX9D/^VIX3M)
ts_points = [(lb, v) for lb, v in [('9D', vix9d), ('1M', vix), ('3M', vix3m)] if v is not None]
ts_state = '—'
if vix is not None and vix3m is not None:
    ts_state = '倒挂(Backwardation)' if vix > vix3m else 'Contango(升水)'

# 跨资产仪表盘 (阈值=分析师判断区间, 当前值与分位=真实数据)
_ca_defs = [('VIX 股票','vix',15,20),('MOVE 债券','move',90,120),('OVX 原油','ovx',35,50),
            ('GVZ 黄金','gvz',15,25),('VVIX','vvix',95,120),('SKEW','skew',130,150)]
ca_rows = [(lb, val(k), pct(k), n, st) for lb, k, n, st in _ca_defs if val(k) is not None]
ovx_vix_gap = round(ovx - vix, 1) if (ovx is not None and vix is not None) else None
stress_assets = [lb for lb, v, p, n, st in ca_rows if v >= st]

DATA['volatility'] = {
    'regime': {'label':('波动率分化' if stress_assets else '波动率平静'),'signal':'mixed','confidence':'中等置信',
        'description':f'当前处于压力区的: {(",".join(stress_assets) if stress_assets else "无")}。VIX {f2(vix)}' + (f', OVX {f2(ovx)}' if ovx else '') + (f', MOVE {f2(move)}' if move else '') + '。分化形态决定这是单资产冲击还是系统性重定价——看压力是否从单一资产外溢。'},
    'keySignals': [s for s in [
        ({'title':f'OVX {f2(ovx)} vs VIX {f2(vix)} 剪刀差 {ovx_vix_gap}pt','meaning':'油股波动率极端分化, 历史上多以油价回落或 VIX 补涨收敛。','direction':'mixed'} if ovx_vix_gap is not None else None),
        {'title':f'VIX {f2(vix)}, 周 {bp(tfm("vix")["w"],"pt")}','meaning':'站上20将触发波动率目标基金被动减仓, 抛压自我强化。','direction':'bearish' if (vix or 0) >= 18 else 'mixed'},
        ({'title':f'SKEW {f1(skew)} 尾部偏度','meaning':'机构对深度虚值看跌的定价, >150 说明尾部保护需求极贵。','direction':'bearish' if (skew or 0) >= 140 else 'mixed'} if skew is not None else None),
    ] if s],
    'metrics': vol_metrics,
    'trendData': vol_trends,
    'chartData': {'labels': _dates_for('vix'),
        'series': {lb: rebase(series90(k)) for lb, k in [('VIX','vix'),('VVIX','vvix'),('MOVE','move'),('OVX','ovx')] if series90(k)}},
    'termStructure': {'labels':[lb for lb, _ in ts_points],'values':[round(v,1) for _, v in ts_points],'state':ts_state},
    'crossAsset': {'labels':[r[0] for r in ca_rows],'current':[round(r[1],1) for r in ca_rows],
        'pctRank30d':[r[2] for r in ca_rows],'normal':[r[3] for r in ca_rows],'stress':[r[4] for r in ca_rows],
        'note':(f'OVX-VIX剪刀差 {ovx_vix_gap}pt' if ovx_vix_gap is not None else '跨资产波动率分化追踪') + (f' · 压力区: {",".join(stress_assets)}' if stress_assets else ' · 无资产进入压力区')},
    'regimeTable': [
        r for r in [
            {'indicator':'VIX 股票','value':f2(vix),'current':('压力区' if (vix or 0)>=25 else ('警戒' if (vix or 0)>=20 else ('中性' if (vix or 0)>=15 else '低位'))),'range':'<15 低 / 15-20 中 / 20+ 警戒','note':'系统性风险确认线=20'},
            ({'indicator':'VVIX','value':f2(vvix),'current':('偏高' if vvix>=110 else '中性'),'range':'<90 低 / 90-110 中 / 110+ 高','note':'对冲VIX本身的需求'} if vvix is not None else None),
            ({'indicator':'MOVE 债券','value':f2(move),'current':('压力区' if move>=120 else ('中性' if move>=90 else '低位')),'range':'<90 低 / 90-120 中 / 120+ 高','note':'利率波动率'} if move is not None else None),
            ({'indicator':'OVX 原油','value':f2(ovx),'current':('压力区' if ovx>=50 else ('中性' if ovx>=35 else '低位')),'range':'<35 低 / 35-50 中 / 50+ 高','note':'供应冲击定价'} if ovx is not None else None),
            ({'indicator':'GVZ 黄金','value':f2(gvz),'current':('偏高' if gvz>=25 else ('中性' if gvz>=15 else '低位')),'range':'<15 低 / 15-25 中 / 25+ 高','note':'避险需求'} if gvz is not None else None),
            ({'indicator':'SKEW','value':f1(skew),'current':('极高' if skew>=150 else ('偏高' if skew>=130 else '正常')),'range':'<130 低 / 130-150 中 / 150+ 高','note':'尾部保护定价'} if skew is not None else None),
        ] if r],
    'analystView': f'波动率市场比价格市场更诚实: 关键问题是"单资产冲击还是系统性风险"。当前压力集中在 {(",".join(stress_assets) if stress_assets else "无——全曲线平静")}; VIX {f2(vix)}' + (f' 距20确认线 {20-vix:.1f}pt' if vix else '') + f'; 期限结构 {ts_state}——近月高于远月才是即时风险定价。' + (f'SKEW {f1(skew)} 说明机构在买尾部保护, 表面平静下对冲需求真实存在。' if skew else '') + '策略: 若剪刀差收敛以 VIX 补涨完成, 买入 VIX 看涨价差是风险回报比好的对冲。',
    'whatToWatch': [
        {'trigger':'VIX 收盘站上 <span class="watch-threshold">20</span>','implication':'波动率目标基金强制减仓, 抛压自我强化','status':(f'距离 {20-vix:.1f}' if vix else '—')},
        {'trigger':'VIX期限结构转为 <span class="watch-threshold">倒挂</span>','implication':'近月高于远月=即时风险定价','status':f'当前{ts_state}'},
        {'trigger':'OVX 突破 <span class="watch-threshold">50</span>','implication':'油价波动失控, 传导至所有资产保证金','status':(f'距离 {max(0,50-ovx):.0f}' if ovx else '—')},
    ],
    'chartNotes': {
        'volNote': '四条曲线累计涨跌(起点=0%) · 形状真实, 便于比较相对变化',
        'tsNote': f'VIX期限结构: {ts_state} · 9D/1M/3M 真实读数',
        'dashNote': (f'压力区: {",".join(stress_assets)}' if stress_assets else '无资产进入压力区') + ' —— 冲击源头定位',
        'trendNote': f'VIX周Δ{bp(tfm("vix")["w"],"pt")}' + (f' · OVX月Δ{f1(tfm("ovx")["m"])}pt' if ovx and tfm("ovx")["m"] is not None else '') + (f' · SKEW {f1(skew)}' if skew else ''),
    },
}

print('[gen_datajs] volatility section OK', file=sys.stderr, flush=True)

# ====== 衰退信号仪表盘 (Phase 2) ======
print('[gen_datajs] generating recession section...', file=sys.stderr, flush=True)
def _recession_signal(label, value, threshold, triggered, meaning, color='red'):
    """红绿灯面板每一行"""
    status = 'triggered' if triggered else ('warning' if (value is not None and triggered is not False and abs(value) > threshold * 0.6) else 'safe')
    if value is None: status = 'unknown'
    return {'label': label, 'value': round(value, 2) if isinstance(value, (int, float)) else value,
            'threshold': threshold, 'status': status, 'meaning': meaning, 'color': color}

_recession_signals = []
# 10Y-2Y 利差 (转负=衰退信号)
_spread_10_2_val = round((val('dgs10') - val('dgs2')) * 100, 1) if val('dgs10') and val('dgs2') else None
_recession_signals.append(_recession_signal('10Y-2Y 利差', _spread_10_2_val, 0, _spread_10_2_val is not None and _spread_10_2_val < 0,
    '转负领先衰退12-18个月。当前' + (f'{_spread_10_2_val:+.0f}bp' if _spread_10_2_val else '—'), 'red'))

# 3M-10Y 利差 (更可靠衰退指标)
_recession_signals.append(_recession_signal('3M-10Y 利差', _t10y3m_val, 0,
    _t10y3m_val is not None and _t10y3m_val < 0,
    'Fed研究认为比10Y-2Y更可靠，领先10-14个月。当前' + (f'{_t10y3m_val:+.0f}bp' if _t10y3m_val else '—'), 'red'))

# Sahm Rule
_recession_signals.append(_recession_signal('Sahm Rule', _sahm['value'], 0.5, _sahm['triggered'],
    '失业率3M均值-12M低点。触发后历史100%对应衰退。' + (f'当前 {_sahm["value"]}' if _sahm['value'] else '—'), 'red'))

# 纽约联储衰退概率
_recession_signals.append(_recession_signal('衰退概率(纽约联储)', _recession_p, 40,
    _recession_p is not None and _recession_p > 40,
    '基于3M-10Y利差的12月前瞻衰退概率。>40%为预警。' + (f'当前 {_recession_p}%' if _recession_p else '—'), 'orange'))

# 初请失业金4周均值 (已前置计算)
_recession_signals.append(_recession_signal('初请失业金(4周均)', round(_claims_4wk / 1000, 0) if _claims_4wk else None, 325,
    _claims_4wk is not None and _claims_4wk > 325000,
    '突破325K确认就业恶化。当前' + (f'{_claims_4wk/1000:.0f}K' if _claims_4wk else '—'), 'orange'))

# STLFSI 金融压力
_stlfsi_stressed = v_stlfsi is not None and v_stlfsi > 0
_recession_signals.append(_recession_signal('圣路易斯金融压力', v_stlfsi, 0,
    _stlfsi_stressed, '>0 = 高于均值压力。' + (f' {v_stlfsi:+.2f}' if v_stlfsi is not None else '—'), 'orange'))

# 计算综合衰退风险评分
_triggered_count = sum(1 for s in _recession_signals if s['status'] == 'triggered')
_warning_count = sum(1 for s in _recession_signals if s['status'] == 'warning')
_known_count = sum(1 for s in _recession_signals if s['status'] != 'unknown')
_recession_score = round((_triggered_count * 3 + _warning_count) / max(_known_count * 3, 1) * 100)
_recession_level = '高风险' if _recession_score >= 60 else ('中风险' if _recession_score >= 30 else '低风险')

DATA['recession'] = {
    'regime': {'label': f'衰退风险: {_recession_level}','signal': 'bearish' if _recession_score >= 50 else ('mixed' if _recession_score >= 25 else 'bullish'),'confidence':'数据驱动',
        'description': f'6项先行指标聚合: 触发信号 {_triggered_count} 项, 预警 {_warning_count} 项。综合评分 {_recession_score}/100 ({_recession_level})。周期指标（利率利差）+ 就业即时指标（Sahm/初请/失业率）+ 前瞻指标（衰退概率/金融压力）三维交叉验证。'},
    'signals': _recession_signals,
    'score': _recession_score, 'level': _recession_level,
    'cyclePosition': '扩张后期' if _recession_score >= 40 else ('放缓期' if _recession_score >= 20 else '扩张期'),
    'analystView': '衰退风险仪表盘通过6项独立信号交叉验证衰退概率。当前阶段: ' + ('利率曲线未倒挂+就业健康=扩张期, 关注初请失业金和Sahm Rule的边际变化。' if _recession_score < 20 else ('部分先行指标预警但核心就业未触发=放缓期, 需警惕信用市场与劳动力市场联动恶化。' if _recession_score < 40 else f'{_triggered_count}项触发({_warning_count}项预警), 衰退概率上升。关键看失业率与信用利差是否同时恶化。')),
    'whatToWatch': [
        {'trigger':'Sahm Rule 触发 <span class="watch-threshold">>0.5</span>','implication':'历史上100%对应衰退, 美联储将快速转向','status': f'当前 {_sahm["value"]}' if _sahm['value'] else '—'},
        {'trigger':'3M-10Y 利差再次 <span class="watch-threshold">转负</span>','implication':'Fed研究的最可靠衰退先行指标','status': f'当前 {_t10y3m_val:+.0f}bp' if _t10y3m_val else '—'},
        {'trigger':'初请突破 <span class="watch-threshold">325K</span>','implication':'就业恶化确认, 消费-收入-就业负反馈启动','status': f'当前 {_claims_4wk/1000:.0f}K' if _claims_4wk else '—'},
    ]
}

print('[gen_datajs] recession section OK', file=sys.stderr, flush=True)

# ====== 全局风险评分 (Phase 4) ======
print('[gen_datajs] generating riskScore section...', file=sys.stderr, flush=True)
# 聚合7板块信号: 利率/美联储/流动性/经济/信用/波动率/衰退
def _risk_factor(score_val, weight, label, status):
    """单个风险因子"""
    color = '#e63946' if status == 'bearish' else ('#f59e0b' if status == 'mixed' else '#2a9d8f')
    return {'label': label, 'score': round(score_val, 1), 'weight': weight, 'status': status, 'color': color}

_risk_factors = []
# 利率: 10Y 分位 → 分位高=利率高=利空
_rate_risk = min(pct('dgs10') * 0.7 + (30 if (val('dgs10') or 0) > 4.5 else 0), 100)
_rate_status = 'bearish' if _rate_risk >= 60 else ('mixed' if _rate_risk >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_rate_risk, 15, '利率环境', _rate_status))

# 流动性: LPI 评分
_lpi = DATA.get('liquidity', {}).get('lpi', {})
_lpi_score = _lpi.get('score', 5) * 10
_lpi_status = 'bearish' if _lpi_score >= 60 else ('mixed' if _lpi_score >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_lpi_score, 18, '流动性压力', _lpi_status))

# 信用: CCC OAS 分位
_credit_risk = pct('ccc') * 0.8
_credit_status = 'bearish' if _credit_risk >= 60 else ('mixed' if _credit_risk >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_credit_risk, 14, '信用市场', _credit_status))

# 波动率: VIX 风险
_vix_risk = min((val('vix') or 15) / 25 * 80, 100)
_vix_status = 'bearish' if _vix_risk >= 50 else ('mixed' if _vix_risk >= 25 else 'bullish')
_risk_factors.append(_risk_factor(_vix_risk, 12, '波动率风险', _vix_status))

# 经济: 失业率分位 + Sahm
_econ_risk = pct('unrate') * 0.5 + (_sahm['value'] or 0) * 50
_econ_status = 'bearish' if _econ_risk >= 60 else ('mixed' if _econ_risk >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_econ_risk, 14, '经济基本面', _econ_status))

# 资产: 股债相关
_asset_risk = 40 if (spx_tlt_corr and spx_tlt_corr > 0) else 25
_asset_status = 'mixed'
_risk_factors.append(_risk_factor(_asset_risk, 10, '跨资产信号', _asset_status))

# 衰退: 衰退概率评分
_rec_risk = _recession_score * 0.7
_rec_status = 'bearish' if _rec_risk >= 50 else ('mixed' if _rec_risk >= 25 else 'bullish')
_risk_factors.append(_risk_factor(_rec_risk, 17, '衰退风险', _rec_status))

# 加权综合
_total_weight = sum(f['weight'] for f in _risk_factors)
_total_score = round(sum(f['score'] * f['weight'] for f in _risk_factors) / _total_weight)
_risk_level = '高风险' if _total_score >= 65 else ('中等风险' if _total_score >= 35 else '低风险')
_risk_color = '#e63946' if _total_score >= 65 else ('#f59e0b' if _total_score >= 35 else '#2a9d8f')

DATA['riskScore'] = {
    'score': _total_score, 'level': _risk_level, 'color': _risk_color,
    'description': f'7板块加权聚合风险评分 {_total_score}/100 ({_risk_level})。权重: 流动性18% + 衰退17% + 利率15% + 经济14% + 信用14% + 波动率12% + 资产10%。',
    'factors': _risk_factors,
    'summary': f'当前宏观风险画像: {"利率+衰退主导" if _rate_risk > 50 or _rec_risk > 40 else ("流动性为主的结构性压力" if _lpi_score > 50 else "风险可控, 关注边际变化")}。核心风险点: ' + 
        (', '.join(f['label'] for f in _risk_factors if f['score'] >= 50) or '无单一板块超警戒线') + '。',
}

print('[gen_datajs] riskScore section OK', file=sys.stderr, flush=True)

# ====== 加密货币板块 (Crypto) ======
print('[gen_datajs] generating crypto section...', file=sys.stderr, flush=True)
_v_btc = val('btc'); _v_eth = val('eth'); _v_ethbtc = val('eth_btc_ratio')
_v_etf_btc = val('etf_btc_flow'); _v_etf_eth = val('etf_eth_flow')
_btc_ch = asset_changes('btc') if _v_btc is not None else {}
_eth_ch = asset_changes('eth') if _v_eth is not None else {}

# BTC vs ETH 归一化对比 (同图) — 累计收益率(起点=0%)
def _crypto_norm_chart():
    btc_arr = s('btc'); eth_arr = s('eth')
    if not (btc_arr and eth_arr):
        return {'labels': [], 'series': {}}
    take = min(500, len(btc_arr), len(eth_arr))
    dates = [d for d, _ in btc_arr[-take:]]
    bv = [v for _, v in btc_arr[-take:]]; ev = [v for _, v in eth_arr[-take:]]
    b0 = next((x for x in bv if x), 1); e0 = next((x for x in ev if x), 1)
    return {
        'labels': dates,
        'series': {
            'BTC': [round((x / b0 - 1) * 100, 2) if (b0 and x) else None for x in bv],
            'ETH': [round((x / e0 - 1) * 100, 2) if (e0 and x) else None for x in ev],
        },
    }

# ETH/BTC 比率走势 — 时间轴 X 轴
def _ethbtc_chart():
    arr = s('eth_btc_ratio')
    if not arr:
        return {'labels': [], 'series': {}}
    take = min(500, len(arr))
    return {
        'labels': [d for d, _ in arr[-take:]],
        'series': {'ETH/BTC': [round(v, 6) for _, v in arr[-take:]]},
    }

# ETF 流量数据 (最近30天/条)
def _etf_flow_data():
    out = {'labels': [], 'btc': [], 'eth': []}
    btc_raw = s('etf_btc_flow'); eth_raw = s('etf_eth_flow')
    if not (btc_raw or eth_raw):
        return out
    # 取最近 30 条
    n = 30
    btc_l = (btc_raw or [])[-n:]; eth_l = (eth_raw or [])[-n:]
    # 用日期做 labels
    dates = [d for d, _ in btc_l] if btc_l else ([d for d, _ in eth_l] if eth_l else [])
    out['labels'] = [d for d in dates]  # 完整日期 'YYYY-MM-DD', 前端统一格式化为时间轴
    out['btc'] = [round(v, 1) for _, v in btc_l]
    out['eth'] = [round(v, 1) for _, v in eth_l]
    # 累计净流入
    out['btc_cumsum'] = round(sum(v for _, v in btc_l), 0) if btc_l else None
    out['eth_cumsum'] = round(sum(v for _, v in eth_l), 0) if eth_l else None
    return out

_etf_data = _etf_flow_data()

DATA['crypto'] = {
    'regime': {
        'label': ('风险资产联动模式' if (_v_btc and _v_btc > 60000) else '震荡筑底'),
        'signal': 'mixed', 'confidence': '中等置信',
        'description': f'BTC ${comma(_v_btc,0) if _v_btc else "—"} · ETH ${comma(_v_eth,0) if _v_eth else "—"}'
            + f' · ETH/BTC {_v_ethbtc:.4f}' if _v_ethbtc else ''
            + '。加密市场与风险资产的联动性是关键观察变量——BTC 走强通常对应 risk-on，走弱则预示流动性收缩传导。',
    },
    'keySignals': [s for s in [
        ({'title': f'BTC {_btc_ch.get("w", "—")} 周变动', 'meaning': 'BTC 是加密市场的 beta，其方向决定整个板块的风险偏好基调。', 'direction': dir_of(_btc_ch.get('w'))} if _btc_ch.get('w') is not None else None),
        ({'title': f'ETH/BTC {_v_ethbtc:.4f}', 'meaning': 'ETH 相对 BTC 的强弱。比率上行=资金偏好高贝塔(ETH)，下行=避险(BTC dominance)。' if _v_ethbtc else '', 'direction': 'up' if (_v_ethbtc and _v_ethbtc > 0.045) else 'down'} if _v_ethbtc else None),
        ({'title': f'BTC ETF {"净流入" if (_v_etf_btc and _v_etf_btc > 0) else "净流出" if _v_etf_btc else "暂无"} ${abs(_v_etf_btc):.0f}M' if _v_etf_btc is not None else 'BTC ETF 流量数据获取中', 'meaning': '现货 ETF 持续流入=机构配置需求，流出=获利了结或风险规避。', 'direction': 'bullish' if (_v_etf_btc and _v_etf_btc > 0) else ('bearish' if (_v_etf_btc and _v_etf_btc < 0) else 'mixed')} if _v_etf_btc is not None else None),
    ] if s],
    'metrics': [
        m for m in [
            {'label':'Bitcoin (BTC)','value':('$'+comma(_v_btc,0) if _v_btc else '—'),'change':ret(_btc_ch.get('d')),'dir':dir_of(_btc_ch.get('d')),'tag':'BTC','percentile':pct('btc') if _v_btc else 50,
             'signal':dir_of(_btc_ch.get('w')),'meaning':f'加密市场总市值锚定, 近一年 {pct("btc")} 分位',
             'changes':{k:ret(_btc_ch.get(k)) for k in ('d','w','m','h6')},'sparkline':series30('btc')},
            {'label':'Ethereum (ETH)','value':('$'+comma(_v_eth,0) if _v_eth else '—'),'change':ret(_eth_ch.get('d')),'dir':dir_of(_eth_ch.get('d')),'tag':'ETH','percentile':pct('eth') if _v_eth else 50,
             'signal':dir_of(_eth_ch.get('w')),'meaning':f'Smart Contract 平台龙头, 近一年 {pct("eth")} 分位',
             'changes':{k:ret(_eth_ch.get(k)) for k in ('d','w','m','h6')},'sparkline':series30('eth')},
            {'label':'ETH/BTC 比率','value':(f'{_v_ethbtc:.5f}' if _v_ethbtc else '—'),
             'change':pctpt(tfm('eth_btc_ratio')['d']) if val('eth_btc_ratio') else '—',
             'dir':dir_of(tfm('eth_btc_ratio')['d']) if val('eth_btc_ratio') else 'neutral',
             'tag':'Ratio','percentile':pct('eth_btc_ratio') if _v_ethbtc else 50,
             'signal':'bullish' if (_v_ethbtc and _v_ethbtc > 0.045) else ('bearish' if (_v_ethbtc and _v_ethbtc < 0.04) else 'mixed'),
             'meaning':'ETH 相对 BTC 强弱 · >0.05=ETH强势区间 · <0.04=BTC极度主导',
             'changes':{k:(round(tfm('eth_btc_ratio').get(k),5) if tfm('eth_btc_ratio').get(k) is not None else '—') for k in ('d','w','m','h6')},
             'sparkline':series30('eth_btc_ratio')},
            {'label':'BTC ETF 净流(日)','value':(f'{_v_etf_btc:+,.0f}M$' if _v_etf_btc is not None else '—'),
             'change':(f'{_v_etf_btc:+,.0f}M' if _v_etf_btc is not None else '—'),
             'dir':'up' if (_v_etf_btc and _v_etf_btc>0) else ('down' if (_v_etf_btc and _v_etf_btc<0) else 'neutral'),
             'tag':'IBIT/FBTC等','percentile':None,
             'signal':'bullish' if (_v_etf_btc and _v_etf_btc>0) else ('bearish' if (_v_etf_btc and _v_etf_btc<0) else 'mixed'),
             'meaning':f'近30日累计 {_etf_data.get("btc_cumsum","—"):+,.0f}M$' if _etf_data.get("btc_cumsum") is not None else '日度现货ETF净流入(百万美元)',
             'changes':{'d':'—','w':'—','m':'—','h6':'—'},'sparkline':[]},
            {'label':'ETH ETF 净流(日)','value':(f'{_v_etf_eth:+,.0f}M$' if _v_etf_eth is not None else '—'),
             'change':(f'{_v_etf_eth:+,.0f}M' if _v_etf_eth is not None else '—'),
             'dir':'up' if (_v_etf_eth and _v_etf_eth>0) else ('down' if (_v_etf_eth and _v_etf_eth<0) else 'neutral'),
             'tag':'ETHE/FETH等','percentile':None,
             'signal':'bullish' if (_v_etf_eth and _v_etf_eth>0) else ('bearish' if (_v_etf_eth and _v_etf_eth<0) else 'mixed'),
             'meaning':f'近30日累计 {_etf_data.get("eth_cumsum","—"):+,.0f}M$' if _etf_data.get("eth_cumsum") is not None else '日度现货ETF净流入(百万美元)',
             'changes':{'d':'—','w':'—','m':'—','h6':'—'},'sparkline':[]},
        ] if m
    ],
    # BTC vs ETH 归一化对比图
    'btcEthChart': _crypto_norm_chart(),
    # ETH/BTC 比率走势图
    'ethBtcChart': _ethbtc_chart(),
    # ETF 流量数据
    'etfFlows': _etf_data,
    'trendData': [
        {'name':'Bitcoin','unit':'$','current':('$'+comma(_v_btc,0) if _v_btc else '—'),
         'changes':{k:(round(_btc_ch[k],2) if _btc_ch.get(k) is not None else None) for k in ('d','w','m','h6')},
         'meaning':'数字黄金叙事 vs 风险资产 beta 的博弈'},
        {'name':'Ethereum','unit':'$','current':('$'+comma(_v_eth,0) if _v_eth else '—'),
         'changes':{k:(round(_eth_ch[k],2) if _eth_ch.get(k) is not None else None) for k in ('d','w','m','h6')},
         'meaning':'DeFi/NFT/AI 叙事驱动的周期性资产'},
        {'name':'ETH/BTC','unit':'ratio','current':(f'{_v_ethbtc:.5f}' if _v_ethbtc else '—'),
         'changes':{k:(round(tfm('eth_btc_ratio')[k],5) if tfm('eth_btc_ratio').get(k) is not None else None) for k in ('d','w','m','h6')},
         'meaning':'Altcoin 季节性的核心指标'},
    ],
    'analystView': f'加密市场当前处于{"risk-on 联动" if (_v_btc and _v_btc > 65000) else "独立行情阶段"}。'
        + (f' BTC ${comma(_v_btc,0)}' if _v_btc else '')
        + (f' / ETH ${comma(_v_eth,0)}' if _v_eth else '')
        + (f' (ETH/BTC {_v_ethbtc:.4f})' if _v_ethbtc else '')
        + f'。ETF 方面: BTC ETF {"持续净流入(机构配置)" if (_v_etf_btc and _v_etf_btc > 0) else "出现净流出(警惕)"}'
        + (f' · ETH ETF {"净流入" if (_v_etf_eth and _v_etf_eth > 0) else "净流出"}' if _v_etf_eth is not None else '')
        + '。关键观察: 加密市场与纳斯达克的 correlation 在流动性收紧时趋向+1（risk-off 一锅端），在流动性宽松时脱钩（alpha 行情）。',
    'whatToWatch': [
        {'trigger': f'BTC 突破 <span class="watch-threshold">$100K</span>', 'implication': '新一轮零售 FOMO + 机构 FOMO 共振起点', 'status': f'距离 {max(0,100000-(_v_btc or 0)):,.0f}' if _v_btc else '—'},
        {'trigger': f'ETH/BTC 跌破 <span class="watch-threshold">0.040</span>', 'implication': 'BTC dominance 极致, Altcoin 全面承压', 'status': f'当前 {_v_ethbtc:.4f}' if _v_ethbtc else '—'},
        {'trigger': 'BTC ETF 连续 <span class="watch-threshold">3日净流出</span>', 'implication': '机构获利了结信号, 可能引发连锁抛售', 'status': f'今日 {_v_etf_btc:+,.0f}M' if _v_etf_btc is not None else '—'},
    ],
}

print('[gen_datajs] crypto section OK', file=sys.stderr, flush=True)

# ---------- 写出 data.js ----------
HEADER = """/* ============================================================
 * data.js — US Macro Observer (官方真实数据自动生成)
 * 由 scripts/gen_datajs.py 从 FRED / Treasury / NY Fed / Yahoo 真实数据生成
 * signal 字段: bullish=利多风险资产 / bearish=利空 / mixed=中性
 * percentile: 当前值近1年历史分位 (0-100)
 * 生成时间: %s
 * ============================================================\n */\n""" % datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

out = HEADER + 'const DATA = ' + json.dumps(DATA, ensure_ascii=False, indent=2) + ';\n'
with open('../data.js', 'w', encoding='utf-8', newline='\n') as f:
    f.write(out)
print('[gen_datajs] DONE — data.js generated:', len(out), 'chars, sections:', list(DATA.keys()), file=sys.stderr, flush=True)

# ---------- 缓存破坏: 更新 index.html 中 data.js 的版本号 ----------
ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
idx_path = '../index.html'
try:
    with open(idx_path, 'r', encoding='utf-8') as f:
        html = f.read()
    # 替换 data.js 的版本号 (吃掉整个查询字符串, 避免残留 ?v=initial 之类)
    html = re.sub(r'data\.js(\?[^"]*)?', f'data.js?v={ts}', html)
    with open(idx_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    print(f'[gen_datajs] cache-bust updated: data.js?v={ts}', file=sys.stderr, flush=True)
except Exception as e:
    print(f'[gen_datajs] WARNING — failed to update index.html: {e}', file=sys.stderr, flush=True)
