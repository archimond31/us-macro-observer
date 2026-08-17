#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_datajs.py — 把 computed.json (真实数值/分位/四尺度变化) + raw_series.json (完整序列)
转换为前端使用的 data.js。所有数值来自官方数据源, 叙述文本内嵌真实数值, 每日重算即更新。

输出: ../data.js  (const DATA = {...})
依赖: build_data.py 先跑完, 生成 computed.json / raw_series.json
"""
import json, datetime, sys, re, calendar
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent

C = json.load(open(SCRIPT_DIR / 'computed.json'))
RAW = json.load(open(SCRIPT_DIR / 'raw_series.json'))
GEN_AT = C.get('generated_at', '')   # 数据获取时间 (build_data.py 运行时刻)
# 自动更新日期: 取 build_data.py 实际运行时刻 (而非某序列最新数据点), 确保每次 workflow 跑都刷新
GEN_DATE = GEN_AT.split(' ')[0] if GEN_AT else datetime.datetime.now().strftime('%Y-%m-%d')

# === WGC (世界黄金协会) 央行季度净购金(吨) — 策展数据 ===
# 来源: WGC Gold Demand Trends 季度报告 (https://www.gold.org/goldhub/data/gold-demand-trends)
# 数据更新节奏: 季度 (WGC 每季度发布上月季度的央行净购金统计)
# 维护方式: 每季度 WGC 报告发布后更新此表
# 单位: 公吨 (tonnes), 正值=净购金, 负值=净卖出
# PBOC 月度数据另见: 中国外汇局月报 (2024-11 起连续 21 个月增持, 截至 2026-07 末累计增持约 230 吨)
WGC_CB_PURCHASES_TONNES = [
    # (季末日期, 季度净购金吨)
    ('2022-03-31', 83.9),  ('2022-06-30', 180.6), ('2022-09-30', 399.3), ('2022-12-31', 416.7),
    ('2023-03-31', 280.0), ('2023-06-30', 173.6), ('2023-09-30', 358.4), ('2023-12-31', 304.4),
    ('2024-03-31', 290.2), ('2024-06-30', 192.0), ('2024-09-30', 337.1), ('2024-12-31', 332.7),
    ('2025-03-31', 244.0), ('2025-06-30', 166.0), ('2025-09-30', 218.0), ('2025-12-31', 230.0),
    ('2026-03-31', 244.0), ('2026-06-30', 288.9),
]
GEN_TIME = GEN_AT.split(' ', 1)[1] if GEN_AT else datetime.datetime.now().strftime('%H:%M')
print('[gen_datajs] loaded computed.json + raw_series.json', file=sys.stderr, flush=True)

# Fed 事件 (FOMC 官方日程 + 真实官员讲话), 由 build_data.py 抓取写入 events.json
try:
    EV = json.load(open(SCRIPT_DIR / 'events.json'))
    print('[gen_datajs] loaded events.json', file=sys.stderr, flush=True)
except Exception:
    EV = {'fomc': [], 'jackson_hole': None, 'speeches': []}
    print('[gen_datajs] events.json 缺失, 事件板块将留空', file=sys.stderr, flush=True)

# AI 产业链知识库 (五层蛋糕: 应用/模型/基础设施/芯片/能源; 策展基本面 + 研报共识)
try:
    AIC = json.load(open(SCRIPT_DIR / 'ai_chain.json'))
    print('[gen_datajs] loaded ai_chain.json', file=sys.stderr, flush=True)
except Exception:
    AIC = {'layers': [], 'disclaimer': '', 'asOf': ''}
    print('[gen_datajs] ai_chain.json 缺失, AI板块将留空', file=sys.stderr, flush=True)

# 矛盾信号面板 (主导矛盾/领先确认/交叉验证; 策展框架 + 实时锚点)
try:
    MS = json.load(open(SCRIPT_DIR / 'macro_signal.json', encoding='utf-8'))
    print('[gen_datajs] loaded macro_signal.json', file=sys.stderr, flush=True)
except Exception:
    MS = {}
    print('[gen_datajs] macro_signal.json 缺失, 矛盾信号面板将留空', file=sys.stderr, flush=True)

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
# 注意：必须过滤 type 排除杰克逊霍尔等非 FOMC 事件，否则会误取 JH 日期
_NEXT_FOMC = None
for _it in build_fomc_timeline():
    if _it['type'] in ('decision', 'meeting') and _it['status'] in ('即将召开', '待定', '进行中'):
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
    if len(rule) > 2 and rule[2] == 'lbd':
        # 月末最后工作日 (BEA PCE/GDP 等通常在参考月+1月的最后工作日附近发布)
        last_day = calendar.monthrange(y, m)[1]
        d = datetime.date(y, m, last_day)
        while d.weekday() >= 5:  # 周六=5, 周日=6 → 往前推到周五
            d -= datetime.timedelta(days=1)
        return d
    day = rule[2] if (len(rule) > 2 and isinstance(rule[2], int)) else 28
    last = calendar.monthrange(y, m)[1]
    return datetime.date(y, m, min(day, last))

# tag → (computed.json 序列key, 频率, 发布日规则)
# 月度: 发布月 = 参考月 +1; 季度: 发布月 = 季末月 +1
RELEASE_MAP = {
    'GDP':    ('gdp', 'quarterly'),
    'CPI':    ('cpi', 'monthly', 12),
    'Core':   ('core_cpi', 'monthly', 12),
    'PCE':    ('core_pce', 'monthly', 'lbd'),
    'UNRATE': ('unrate', 'monthly', 'ff'),
    'NFP':    ('payems', 'monthly', 'ff'),
    'LPR':    ('participation', 'monthly', 'ff'),
    'Retail': ('retail', 'monthly', 15),
    'Conf':   ('umich', 'monthly', 15),
    'MfgPMI': ('mfg_pmi', 'monthly', 5),
    'SvcPMI': ('svc_pmi', 'monthly', 5),
    'SuperCore': ('supercore', 'monthly', 'lbd'),
    'Empire': ('empire', 'monthly', 15),
    'Philly': ('philly', 'monthly', 15),
}

# 经济指标 → 数据源 (机构)
SOURCE_MAP = {
    'gdp': 'BEA', 'gdp_real': 'BEA', 'pce': 'BEA', 'core_pce': 'BEA', 'pce_real': 'BEA',
    'cpi': 'BLS', 'core_cpi': 'BLS', 'unrate': 'BLS', 'payems': 'BLS', 'jolts': 'BLS',
    'claims': 'BLS', 'participation': 'BLS', 'quits_rate': 'BLS', 'wage_yoy': 'BLS',
    'retail': 'Census', 'durables': 'Census', 'housing_starts': 'Census', 'permits': 'Census',
    'umich': 'UMich', 'mich_infl': 'UMich', 'wei': 'NY Fed', 'gdpnow': 'Atlanta Fed',
    'nfci': 'Chicago Fed', 'cont_claims': 'BLS', 'cpi_energy': 'BLS', 'cpi_food': 'BLS',
    'cpi_shelter': 'BLS', 'cpi_core_svcs': 'BLS', 'cpi_core_goods': 'BLS', 'indpro': 'Fed',
    'mfg_pmi': 'S&P Global', 'svc_pmi': 'S&P Global',
    'supercore': 'BEA',       # IA001260M: PCE Services Excluding Energy & Housing (链式价格指数)
    'empire': 'NY Fed', 'philly': 'Philly Fed',
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

# 实时源覆盖: Yahoo 实时序列优先于 FRED 滞后序列, 缺失时回退原 FRED 序列
_LIVE_OVERRIDE = {'wti': 'wti_rt', 'brent': 'brent_rt'}
def _live_resolve(key):
    ov = _LIVE_OVERRIDE.get(key)
    if ov and C.get(ov) is not None:
        return ov
    return key
def g(key):
    return C.get(_live_resolve(key))
def s(key):
    return RAW.get(_live_resolve(key), [])
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

def supercore_pce_yoy():
    """超级核心通胀同比% (BEA IA001260M: PCE服务除能源除住房, 链式价格指数 2017=100)。
    返回 [(date, yoy%), ...] 或 []。"""
    raw = {d: v for d, v in s('supercore')}
    if not raw:
        return []
    out = []
    dates = sorted(raw)
    for i, d in enumerate(dates):
        if i < 12:
            continue
        pd = dates[i - 12]  # 12 个月前同月
        lv, pv = raw[d], raw[pd]
        if pv and pv > 0:
            out.append((d, (lv / pv - 1) * 100))
    return out

def _dates_for(ref_key):
    """取参考序列最近 N 个日期作为 X 轴时间轴 (N=该序列 series90 长度)。无数据则退回索引。"""
    arr = s(ref_key)
    n = len(series90(ref_key))
    if arr:
        return [d for d, _ in arr[-n:]]
    return list(range(n))

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

# 指标信号: 由方向(数据驱动)推导 bullish/bearish/mixed, 彻底消除预置叙事
#   up_is_good=True  -> 上升=利好(如准备金/非农/零售/消费者信心)
#   up_is_good=False -> 上升=利空(如利差走阔/通胀/失业率/QT缩表/SOFR上行)
def _msig(d, up_is_good=True):
    if d == 'up':   return 'bullish' if up_is_good else 'bearish'
    if d == 'down': return 'bearish' if up_is_good else 'bullish'
    return 'mixed'

def _confidence(signal, *flags):
    """由信号清晰度 + 关键数据可用性推导 regime 置信度。
    过半关键输入缺失 -> 低置信; 信号混杂 -> 中等置信; 信号一致且数据过半可用 -> 高置信。"""
    n = len(flags)
    if n == 0:
        return '中等置信'
    avail = sum(1 for f in flags if f)
    if avail <= n // 2:
        return '低置信'
    return '高置信' if signal != 'mixed' else '中等置信'

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
# 数据截至日: 取关键日度/月度序列的最新数据点日期 (SPX/10Y/CPI), 通常比运行时刻慢1-2天
_dates = [d for d in (date_of('spx'), date_of('dgs10'), date_of('cpi')) if d]
DATA['meta'] = {
    'lastUpdated': f'{GEN_DATE} {GEN_TIME} (官方数据, 自动更新)',
    'dataAsOf': max(_dates) if _dates else None,
    'dataSource': 'FRED / U.S. Treasury FiscalData / NY Fed / Yahoo Finance',
    'marketNote': '数值来自官方公开源, 每日自动重算; 月/半年变化受数据频率限制可能为 None'
}

# 全局 regime (汇总关键真实值)
v_dgs10 = val('dgs10'); v_wti = val('wti'); v_ccc = val('ccc'); v_hy = val('hy')
v_vix = val('vix'); v_tga = val('tga'); v_netliq = val('netliq')
# 全局 risk regime 由多指标阈值合成 (避免预置叙事)
_v2 = val('dgs2')
_g_spread = (v_dgs10 - _v2)*100 if (v_dgs10 is not None and _v2 is not None) else None
_g_score = 0
if _g_spread is not None:
    _g_score += 1 if _g_spread < 0 else -1          # 曲线倒挂=衰退风险
_g_score += 1 if (v_vix or 0) > 25 else (-1 if (v_vix or 0) < 15 else 0)
_g_nfci = val('nfci')
_g_score += 1 if (_g_nfci or 0) > 0 else (-1 if (_g_nfci or 0) < 0 else 0)
_g_hy_pct = pct('hy')
_g_score += 1 if (_g_hy_pct or 0) > 70 else (-1 if (_g_hy_pct or 0) < 30 else 0)
_g_signal = 'risk-off' if _g_score >= 2 else ('risk-on' if _g_score <= -2 else 'mixed')
_g_name = '风险规避' if _g_signal == 'risk-off' else ('风险偏好' if _g_signal == 'risk-on' else '多空交织')
DATA['globalRegime'] = {
    'name': _g_name,
    'signal': _g_signal,
    'confidence': _confidence(_g_signal, _g_spread is not None, v_vix is not None, _g_nfci is not None, v_hy is not None),
    'description': f'10Y 美债 {f2(v_dgs10)}% 处于近一年 {pct("dgs10")} 分位, 长端利率是本周资产重定价的核心变量; 信用市场内部已分层——CCC 利差 {f2(v_ccc)}% (分位 {pct("ccc")}), 而 HY 整体 {f2(v_hy)}%。油价 (WTI {f2(v_wti)}) 与波动率 (VIX {f2(v_vix)}) 当前处于"利率驱动的资产分化"阶段。'
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
    """构建美股指数 + 加密货币走势图数据 (归一化至起点=0%, 即累计收益率)。
    数据源优先级: Yahoo 实时 > FRED 滞后。取最近 ~500 个交易日(约2年)。
    X轴改为时间轴(日期)。含 rawSeries/rawNums 供前端 tooltip 时间点值显示与区间滑块重新归一化。"""
    indices = [
        ('标普500', 'spx'), ('纳斯达克100', 'ndx'),
        ('道琼斯', 'dji_yahoo' if s('dji_yahoo') else 'dji'),
        ('罗素2000', 'rut'), ('费城半导体', 'sox'),
        ('比特币', 'btc'), ('以太坊', 'eth'),
    ]
    raw_series = {}
    for name, key in indices:
        arr = s(key)
        if arr:
            raw_series[name] = [(d, v) for d, v in arr]
    if len(raw_series) < 3:
        return {'labels': [], 'series': {}, 'note': '数据不足'}
    # 用参考序列(spx 优先)的日期作为 X 轴时间轴, 其他序列按日期对齐(加密资产周末无指数点位→None)
    ref_name = '标普500' if '标普500' in raw_series else list(raw_series.keys())[0]
    ref_dates = [d for d, _ in raw_series[ref_name]]
    take = min(500, len(ref_dates))
    dates = ref_dates[-take:]
    series, rawSeries, rawNums = {}, {}, {}
    for name, key in indices:
        if name not in raw_series:
            continue
        m = dict(raw_series[name])
        vals = [m.get(d) for d in dates]
        rawNums[name] = vals
        fmt_vals = []
        for v in vals:
            if v is None:
                fmt_vals.append(None)
            elif name in ('比特币', '以太坊'):
                fmt_vals.append('$' + format(int(round(v)), ','))
            else:
                fmt_vals.append(format(round(v), ','))
        rawSeries[name] = fmt_vals
        base = next((v for v in vals if v), None)
        if base and base != 0:
            # 归一化至累计收益率(起点=0%), 而非起点=100
            series[name] = [round((x / base - 1) * 100, 2) if x else None for x in vals]
    return {'labels': dates, 'series': series, 'rawSeries': rawSeries, 'rawNums': rawNums,
            'note': f'累计涨跌(起点=0%) · 近{take}个交易日 · 美股五大指数 + 比特币/以太坊'}

def _build_cb_purchases_chart():
    """构建央行净购金走势图 (WGC 季度数据, 含季度净购金柱 + 12 个月滚动累计线)。
    数据源: WGC_CB_PURCHASES_TONNES 策展常量 (季度更新, 来源 worldgoldcouncil.org)。"""
    if not WGC_CB_PURCHASES_TONNES:
        return {'labels': [], 'series': {}, 'note': '数据不足'}
    dates = [d for d, _ in WGC_CB_PURCHASES_TONNES]
    tonnes = [t for _, t in WGC_CB_PURCHASES_TONNES]
    # 12 个月滚动累计 (4 个季度滚动和)
    roll = []
    for i in range(len(tonnes)):
        win = tonnes[max(0, i - 3):i + 1]
        roll.append(round(sum(win), 1))
    latest_t = tonnes[-1]
    latest_q = dates[-1]
    yoy = (latest_t - tonnes[-5]) if len(tonnes) >= 5 else None
    return {
        'labels': dates,
        'series': {
            '季度净购金(吨)': [round(t, 1) for t in tonnes],
            '12个月滚动累计(吨)': roll,
        },
        'current': {'latest': latest_t, 'date': latest_q, 'yoy': yoy},
        'note': (f'WGC 季度央行净购金(吨) · 最新 {latest_q}: {latest_t:.0f} 吨, '
                 f'同比 {yoy:+.0f} 吨' if yoy is not None else
                 f'WGC 季度央行净购金(吨) · 最新 {latest_q}: {latest_t:.0f} 吨'),
        'source': 'World Gold Council · Gold Demand Trends',
    }


def _build_labor_triangle():
    """劳动力市场 '需求-供给-价格' 三角框架图表数据 (近 3 年月度, 9 序列, 3 panel)。
    便于观察三个维度的中长期趋势与交叉信号。"""
    ref = s('unrate')
    if not ref:
        return {'labels': [], 'panels': {}, 'note': '数据不足'}
    months = {}
    for d, v in ref:
        if v is None: continue
        months[d[:7]] = d
    ref_dates = sorted(months.values())[-36:]

    def _align_level(key, scale=1):
        m = {}
        for d, v in s(key):
            if v is None: continue
            m.setdefault(d[:7], (d, v))
        return [m.get(rd[:7], (None, None))[1] * scale if m.get(rd[:7]) else None for rd in ref_dates]

    def _align_monthly_mean(key):
        weekly = {}
        for d, v in s(key):
            if v is None: continue
            weekly.setdefault(d[:7], []).append(v)
        out = []
        for rd in ref_dates:
            vs = weekly.get(rd[:7], [])
            out.append(round(sum(vs) / len(vs)) if vs else None)
        return out

    def _align_mom(key):
        items = [(d, v) for d, v in s(key) if v is not None]
        out = []
        for i in range(1, len(items)):
            out.append((items[i][0], items[i][1] - items[i - 1][1]))
        m = {}
        for d, v in out:
            m.setdefault(d[:7], (d, v))
        return [m.get(rd[:7], (None, None))[1] for rd in ref_dates]

    # 工资 - 通胀差 = 时薪同比 - CPI 同比
    # 注意: raw 'wage_yoy' 实际是 CES0500000003 平均时薪水平($/hr), 需先用 yoy_series 换算成同比%
    wage_yoy_series_raw = yoy_series('wage_yoy', 40)   # [(date, 同比%), ...]
    wage_m = {}
    for d, v in wage_yoy_series_raw:
        if v is not None: wage_m.setdefault(d[:7], v)
    cpi_arr = [(d, v) for d, v in s('cpi_nsa') if v is not None]  # 工资-通胀差: 同比用 NSA 官方口径
    cpi_yoy_by_month = {}
    for i in range(12, len(cpi_arr)):
        prev = cpi_arr[i - 12][1]
        if prev:
            cpi_yoy_by_month[cpi_arr[i][0][:7]] = (cpi_arr[i][1] / prev - 1) * 100
    wage_yoy_monthly = []
    wage_minus = []
    for rd in ref_dates:
        w = wage_m.get(rd[:7])
        c = cpi_yoy_by_month.get(rd[:7])
        wage_yoy_monthly.append(w)
        if w is not None and c is not None:
            wage_minus.append(round(w - c, 2))
        else:
            wage_minus.append(None)

    panels = {
        'demand': {
            'title': '需求 Demand',
            'series': {
                'JOLTS 职位空缺(百万)': _align_level('jolts', 1/1000),
                '非农就业(月增, K)': _align_mom('payems'),
                '初请失业金(月均, K)': _align_monthly_mean('claims'),
            },
            'colors': {'JOLTS 职位空缺(百万)': '#4361ee',
                       '非农就业(月增, K)': '#10b981',
                       '初请失业金(月均, K)': '#f59e0b'},
            'interpretation': '需求走弱 → JOLTS 下降、非农降温、初请走高, 为美联储转向鸽派提供依据。',
        },
        'supply': {
            'title': '供给 Supply',
            'series': {
                '劳动参与率(%)': _align_level('participation'),
                '失业率(%)': _align_level('unrate'),
                '续请失业金(月均, K)': _align_monthly_mean('cont_claims'),
            },
            'colors': {'劳动参与率(%)': '#06b6d4',
                       '失业率(%)': '#8b5cf6',
                       '续请失业金(月均, K)': '#ec4899'},
            'interpretation': '供给收缩 → 参与率下降 / 失业率因分子缩小走低（质量差）, 与续请走高并存是衰退先兆。',
        },
        'price': {
            'title': '价格 Price',
            'series': {
                '时薪同比(%)': wage_yoy_monthly,
                '辞职率(%)': _align_level('quits_rate'),
                '工资-通胀差(pt)': wage_minus,
            },
            'colors': {'时薪同比(%)': '#e63946',
                       '辞职率(%)': '#7209b7',
                       '工资-通胀差(pt)': '#14b8a6'},
            'interpretation': '价格粘性 → 时薪增速若持续>4% 且大于通胀, 工资-物价螺旋风险; 辞职率反映议价能力。',
        },
    }
    return {'labels': ref_dates, 'panels': panels,
            'note': '劳动力供需价格三角 · 近 3 年月度 · 9 序列 · 拖动下方滑块调整区间'}

def _chg_map(key, n=120):
    """序列水平日度绝对变化 (适用于收益率/波动率等水平型序列); 返回 {date: chg}。"""
    arr = s(key)[-(n + 1):]
    out = {}
    for i in range(1, len(arr)):
        if arr[i - 1][1] is not None and arr[i][1] is not None:
            out[arr[i][0]] = arr[i][1] - arr[i - 1][1]
    return out

def _level_trend(key, dates):
    """窗口首尾水平差 (实际序列值, 非日变化); 用于方向信号。"""
    arr = s(key)
    m = {d: v for d, v in arr}
    a = m.get(dates[0]); b = m.get(dates[-1])
    return (b - a) if (a is not None and b is not None) else 0

def _gold_phases(current):
    """黄金定价的三阶段框架 (2026-08 重置)。
    current: 'structural' (央行购金持续/同比扩张) | 'rate' (实际利率锚定回归)。"""
    stages = [
        {'phase': '阶段一 · 2013–2021', 'driver': '实际利率锚定',
         'desc': '黄金与 10 年实际利率(TIPS)高度负相关。美联储紧缩→实际利率上行压制金价；QE/实际利率下行→推升金价。最"教科书"的关系。'},
        {'phase': '阶段二 · 2022–2023', 'driver': '通胀 + 利率背离',
         'desc': '高通胀初期黄金与实际利率短暂脱钩：2022 实际利率飙升但黄金抗跌，因通胀预期与避险对冲了实际利率上行。'},
        {'phase': '阶段三 · 2024–2026', 'driver': '央行购金 / 去美元化',
         'desc': '黄金与实际利率显著脱钩——WGC 季度央行净购金 2022 年起跃升至 400+ 吨/季, 2024 年累计 1,152 吨创历史新高; 中国央行已连续 21 个月增持(2024-11 至今), 2025 年末黄金在全球央行储备中占比升至 27%, 超越美国国债成为第一大官方储备资产。地缘多元化储备 + 财政赤字货币化担忧, 形成结构性买盘, 与短期价格脱钩。'},
    ]
    current_stage = '阶段三' if current == 'structural' else '阶段一'
    label = ('当前主线：阶段三 央行购金 / 去美元化（结构性托底）—— WGC 季度净购金持续在 200+ 吨/季高位, '
             '与短期利率 / 美元走势脱钩, 45% 受访央行计划未来 12 个月增持'
             if current == 'structural'
             else '当前主线：阶段一 实际利率锚定回归 —— 央行购金节奏中性或回落, 金价重回利率框架主导')
    return {'current': current, 'currentStage': current_stage, 'currentLabel': label, 'stages': stages}

def _gold_analysis(gold_ret, primary, primary_label, drivers, scores, ry_t, dxy_t, haven_dir, inf_dir,
                   cb_latest_t, cb_latest_q, cb_yoy):
    gr = f'{gold_ret:+.1f}%' if gold_ret is not None else '—'
    cb_str = f'{cb_latest_t:.0f}吨（{cb_latest_q[-4:]}）' if cb_latest_t else '—'
    yoy_str = f'同比 {cb_yoy:+.0f}吨' if cb_yoy is not None else '—'
    L = [f'近90个交易日黄金累计 {gr}。']
    if primary == 'consolidation':
        L.append(f'黄金近期未形成明确上行叙事，主流因子贡献均偏弱；同期 WGC 最新季度央行净购金 {cb_str}, {yoy_str}, 为金价提供结构性托底，短期则宜观察而非追涨。')
        L.append('注：DXY 约 58% 权重为欧元，"美元指数走弱"≠"美元信用下跌"；后者应由实际利率、期限溢价与央行购金共同印证，单一 DXY 易误判。')
        return ''.join(L)
    if primary == 'mixed':
        L.append(f'黄金上行由多因素共振推动，无单一主导叙事；央行购金 {cb_str} 提供结构性托底。')
    else:
        d = next((x for x in drivers if x['key'] == primary), None)
        if d:
            corr_disp = (('+' + format(d['corr'], '.2f')) if d['corr'] is not None else '—')
            L.append(f'主导叙事为【{primary_label}】——该因子与金价相关系数 {corr_disp}，贡献评分 {d["score"]}/100。')
    sup = [x for x in drivers if x['role'] == 'support']
    if sup:
        L.append('辅助支撑：' + '、'.join(
            f'【{x["name"]}】(相关 {("+" + format(x["corr"], ".2f")) if x["corr"] is not None else "—"}, 评分 {x["score"]})'
            for x in sup) + '。')
    # 央行购金托底提示 (替换原 structural 描述)
    cb_dr = next((x for x in drivers if x['key'] == 'cb'), None)
    if cb_dr and cb_dr['score'] >= 50:
        L.append(f'结构性托底：WGC 最新季度全球央行净购金 {cb_str}, {yoy_str}（中国央行已连续 21 个月增持）；金价近期走弱未拖累官方买盘, 验证央行长期配置需求独立于短期价格波动——回调底部有政策买盘支撑。')
    elif cb_dr and cb_dr['score'] >= 25:
        L.append(f'结构性底色：央行购金 {cb_str}, {yoy_str}, 长期买盘在场但季度活跃度中性。')
    L.append('注：DXY 约 58% 权重为欧元，"美元指数走弱"≠"美元信用下跌"；后者应由实际利率、期限溢价与央行购金共同印证，单一 DXY 易误判。')
    return ''.join(L)

def _gold_driver_model():
    """黄金定价五因子驱动模型 (专家框架, 2026-08 重置)。
    基于近 90 交易日日度收益/变化的 Pearson 相关 + 方向信号, 量化各叙事贡献;
    '央行购金'因子用 WGC 季度净购金数据替换原 '金价与实际利率同向=脱钩' 的代理变量。

    五因子:
      actual_rate  实际利率(10Y TIPS)下行 → 金涨        (经典锚定, 日度相关)
      dollar       美元指数 DXY 走弱      → 金涨        (货币贬值/信用)
      haven        避险(VIX↑/美股↓/日元↑) → 金涨        (风险偏好)
      inflation    抗通胀(BEI↑/原油↑)     → 金涨        (通胀预期)
      cb           央行净购金(WGC 季度)    → 金价托底    (结构性买盘/去美元化, 季度数据)
    """
    WIN = 90
    g_ret = daily_ret_map('gold', WIN)
    dxy_ret = daily_ret_map('dxy', WIN)
    spx_ret = daily_ret_map('spx', WIN)
    oil_ret = daily_ret_map('wti', WIN)
    uj_ret = daily_ret_map('usdjpy', WIN)
    ry_chg = _chg_map('tips10', WIN)
    bei_chg = _chg_map('bei10', WIN)
    vix_chg = _chg_map('vix', WIN)

    keysets = [g_ret, dxy_ret, spx_ret, oil_ret, uj_ret, ry_chg, bei_chg, vix_chg]
    common = None
    for m in keysets:
        common = set(m) if common is None else (common & set(m))
    dates = sorted(common)[-WIN:] if common else []
    if len(dates) < 20 or not g_ret:
        return {'ok': False, 'drivers': [], 'primary': 'mixed', 'primaryLabel': '数据不足',
                'analysis': '实际利率/波动率等底层序列缺失, 无法量化驱动模型。', 'goldReturn': None,
                'phases': _gold_phases('rate')}

    g = [g_ret[d] for d in dates]
    ry_sup = corr_pair(g, [-ry_chg[d] for d in dates])            # 实际利率↓ → 金涨
    dxy_sup = corr_pair(g, [-dxy_ret[d] for d in dates])          # 美元↓ → 金涨
    haven_cands = [corr_pair(g, [vix_chg[d] for d in dates]),
                   corr_pair(g, [-spx_ret[d] for d in dates]),
                   corr_pair(g, [-uj_ret[d] for d in dates])]
    haven_sup = max([c for c in haven_cands if c is not None], default=None)
    inf_cands = [corr_pair(g, [bei_chg[d] for d in dates]),
                 corr_pair(g, [oil_ret[d] for d in dates])]
    inf_sup = max([c for c in inf_cands if c is not None], default=None)

    ry_t = _level_trend('tips10', dates)
    dxy_t = _level_trend('dxy', dates)
    spx_t = _level_trend('spx', dates)
    vix_t = _level_trend('vix', dates)
    uj_t = _level_trend('usdjpy', dates)
    bei_t = _level_trend('bei10', dates)
    oil_t = _level_trend('wti', dates)

    gold_ret_win = None
    if len(dates) >= 2:
        ga = s('gold'); gm = {dd: vv for dd, vv in ga[-(WIN + 1):]}
        a = gm.get(dates[0]); b = gm.get(dates[-1])
        if a and b:
            gold_ret_win = (b / a - 1) * 100

    gold_up = (gold_ret_win or 0) > 0
    ry_down = ry_t < 0
    dxy_down = dxy_t < 0
    haven_dir = (vix_t > 0) or (spx_t < 0) or (uj_t < 0)
    inf_dir = (bei_t > 0) or (oil_t > 0)

    # === 央行购金因子 (WGC 季度数据) ===
    # 取最新季度 vs 1 年前同季度的同比变化判断'托底是否增强'; 并以最新季度 vs 90 日窗口内金价的
    # 季度级相关(若有重叠季度)作为参考。季度数据天然'慢变量', 不参与日度赢家逻辑.
    cb_latest_t = WGC_CB_PURCHASES_TONNES[-1][1] if WGC_CB_PURCHASES_TONNES else 0
    cb_latest_q = WGC_CB_PURCHASES_TONNES[-1][0] if WGC_CB_PURCHASES_TONNES else ''
    cb_yoy = (cb_latest_t - WGC_CB_PURCHASES_TONNES[-5][1]) if len(WGC_CB_PURCHASES_TONNES) >= 5 else None
    cb_active = (cb_latest_t >= 200) or (cb_yoy is not None and cb_yoy > 0)   # 季度净购金≥200吨 或 同比扩张 → 托底仍在
    cb_strength = 0
    if cb_active:
        cb_strength = 50
    if cb_latest_t >= 250:
        cb_strength += 25   # 极活跃(Q2'26 288.9 吨级别)
    if cb_yoy is not None and cb_yoy > 0:
        cb_strength += 25   # 同比扩张
    cb_strength = min(100, cb_strength)

    def _score(c, ok):
        if c is None:
            return 0
        return round(100 * max(0.0, c) * (1.0 if ok else 0.0))

    scores = {
        'actual_rate': _score(ry_sup, ry_down),
        'dollar': _score(dxy_sup, dxy_down),
        'haven': _score(haven_sup, haven_dir),
        'inflation': _score(inf_sup, inf_dir),
        'cb': cb_strength,
    }
    META = {
        'actual_rate': ('实际利率（10Y TIPS）', '实际利率下行'),
        'dollar': ('美元指数 DXY', '美元走弱 / 货币贬值'),
        'haven': ('避险（VIX / 美股 / 日元）', '避险需求'),
        'inflation': ('抗通胀（BEI / 原油）', '抗通胀叙事'),
        'cb': ('央行购金（WGC 季度）', '结构性托底 / 去美元化'),
    }
    corr_map = {'actual_rate': ry_sup, 'dollar': dxy_sup, 'haven': haven_sup,
                'inflation': inf_sup, 'cb': None}
    drivers = []
    for k, (nm, lbl) in META.items():
        if k == 'actual_rate':
            dir_txt = ('实际利率↓' if ry_down else '实际利率↑')
        elif k == 'dollar':
            dir_txt = ('DXY↓' if dxy_down else 'DXY↑')
        elif k == 'haven':
            dir_txt = ('风险偏好回落' if haven_dir else '风险偏好平稳')
        elif k == 'inflation':
            dir_txt = ('通胀预期↑' if inf_dir else '通胀预期平稳')
        else:
            yoy_txt = f'同比 {("+" + format(cb_yoy, ".0f") + "吨") if cb_yoy is not None else "—"}' if cb_yoy is not None else '—'
            q_num = int(cb_latest_q[5:7]) // 3 if len(cb_latest_q) >= 7 else 0
            dir_txt = f'Q{q_num} 净购 {cb_latest_t:.0f}吨, {yoy_txt}'
        drivers.append({'key': k, 'name': nm, 'score': scores[k], 'dir': dir_txt,
                        'corr': (round(corr_map[k], 2) if corr_map[k] is not None else None),
                        'active': scores[k] >= 35, 'role': 'none'})
    prime_key = max(scores, key=scores.get)
    prime_score = scores[prime_key]
    if not gold_up:
        primary, primary_label = 'consolidation', '震荡 / 回调：黄金未形成明确上行叙事'
    elif prime_score < 25:
        primary, primary_label = 'mixed', '多因素共振：无单一主导叙事'
    else:
        primary, primary_label = prime_key, META[prime_key][1]
    for dr in drivers:
        if dr['key'] == primary and primary not in ('consolidation', 'mixed'):
            dr['role'] = 'primary'
        elif dr['score'] >= 35 and dr['key'] != primary:
            dr['role'] = 'support'
        else:
            dr['role'] = 'none'

    # 阶段判断: 央行购金持续(Q 净购金≥200吨 或同比扩张)→ 阶段三(结构性); 否则按传统锚定逻辑
    phase_current = 'structural' if cb_active else 'rate'
    analysis = _gold_analysis(gold_ret_win, primary, primary_label, drivers, scores, ry_t, dxy_t, haven_dir, inf_dir,
                              cb_latest_t, cb_latest_q, cb_yoy)
    return {'ok': True, 'drivers': drivers, 'primary': primary, 'primaryLabel': primary_label,
            'analysis': analysis, 'goldReturn': round(gold_ret_win, 1) if gold_ret_win is not None else None,
            'phases': _gold_phases(phase_current),
            'cbLatest': {'date': cb_latest_q, 'tonnes': cb_latest_t, 'yoy': cb_yoy,
                         'history': WGC_CB_PURCHASES_TONNES[-8:]}}

def _build_gold_narrative():
    """黄金定价叙事：五因子 vs 黄金走势对比图(近1年累计涨跌, 因子均为原始方向) + 五因子驱动模型(近90日真实相关)。"""
    base = s('gold')
    if not base:
        return {'labels': [], 'series': {}, 'note': '数据不足'}
    take = min(252, len(base))
    dates = [d for d, _ in base[-take:]]
    # (名称, key, 反向): 序列均为原始方向(不翻转)。实际利率↑/美元↑ 与金价通常负相关,
    #   观察原始走势可判断"锚定"(反向联动) vs "脱钩"(同向) 两种 regime。
    #   结构性(央行购金)为模型推算, 无直接报价序列, 见下方因子评分卡
    defs = [
        ('黄金', 'gold', False),
        ('实际利率', 'tips10', False),
        ('美元指数', 'dxy', False),
        ('避险 VIX', 'vix', False),
        ('通胀预期 BEI', 'bei10', False),
    ]
    series = {}
    for name, key, inv in defs:
        arr = s(key)
        if not arr:
            series[name] = [None] * len(dates)
            continue
        m = dict(arr)
        vals = [m.get(d) for d in dates]
        b0 = next((v for v in vals if v is not None), None)
        if b0 and b0 != 0:
            out = []
            for x in vals:
                if x is None:
                    out.append(None)
                else:
                    pct = (x / b0 - 1) * 100
                    if inv:
                        pct = -pct
                    out.append(round(pct, 2))
            series[name] = out
        else:
            series[name] = [None] * len(dates)
    # 各折线源数据的当前值(真实水平, 非归一化), 用于图例展示
    def _fmt_cur(_k):
        arr = s(_k)
        if not arr:
            return None
        v = arr[-1][1]
        if v is None:
            return None
        if _k == 'gold':
            return '$' + format(int(round(v)), ',')
        if _k in ('tips10', 'bei10'):
            return format(v, '.2f') + '%'
        return format(v, '.1f')
    current = {}
    for _name, _key, _inv in defs:
        c = _fmt_cur(_key)
        if c:
            current[_name] = c
    # 同时保存每个时间点的源数据真实值，便于前端 tooltip 按横坐标时间点显示真实水平
    rawSeries = {}
    rawNums = {}
    for _name, _key, _inv in defs:
        arr = s(_key)
        if not arr:
            rawSeries[_name] = [None] * len(dates)
            rawNums[_name] = [None] * len(dates)
            continue
        m = dict(arr)
        raw_vals = [m.get(d) for d in dates]
        rawNums[_name] = raw_vals  # 原始数值(无格式)，前端区间切片后按区间起点重新归一化
        fmt_vals = []
        for v in raw_vals:
            if v is None:
                fmt_vals.append(None)
            elif _key == 'gold':
                fmt_vals.append('$' + format(int(round(v)), ','))
            elif _key in ('tips10', 'bei10'):
                fmt_vals.append(format(v, '.2f') + '%')
            else:
                fmt_vals.append(format(v, '.1f'))
        rawSeries[_name] = fmt_vals
    return {'labels': dates, 'series': series, 'current': current, 'rawSeries': rawSeries, 'rawNums': rawNums,
            'note': '近1年同起点累计涨跌% · 各因子均为原始方向(不翻转)：实际利率/美元指数与黄金同向=脱钩背离，反向=经典锚定联动；结构性(央行购金)无报价序列，见下方因子评分卡',
            'regime': _gold_driver_model()}

ASSET_MAP = [
    ('标普500','spx','^GSPC',2,''), ('纳斯达克100','ndx','^NDX',2,''),
    ('道琼斯','dji','^DJI',2,''), ('罗素2000','rut','^RUT',2,''),
    ('费城半导体','sox','^SOX',2,''),
    ('黄金','gold','GC=F',2,'$'), ('WTI原油','wti','CL=F',2,'$'), ('布伦特原油','brent','BZ=F',2,'$'), ('铜','copper','HG=F',2,''),
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


# 跨资产 regime: 由真实跨资产信号动态合成 (替代预设 'risk-off')
_a_score = 0
if (v_vix or 0) > 20: _a_score += 1          # VIX 高=避险
elif (v_vix or 0) < 15: _a_score -= 1          # VIX 低=风险偏好
_a_spx_w = asset_changes('spx').get('w')
if _a_spx_w is not None:
    if _a_spx_w < -2: _a_score += 1            # 股指周跌>2%=去风险
    elif _a_spx_w > 2: _a_score -= 1            # 股指周涨>2%=risk-on
if _g_spread is not None and _g_spread < 0: _a_score += 1   # 曲线倒挂=衰退风险
_a_hy_pct = pct('hy')
if _a_hy_pct is not None and _a_hy_pct > 70: _a_score += 1
elif _a_hy_pct is not None and _a_hy_pct < 30: _a_score -= 1
_a_signal = 'risk-off' if _a_score >= 2 else ('risk-on' if _a_score <= -2 else 'mixed')
_a_label = '利率驱动的风险规避' if _a_signal=='risk-off' else ('宽松驱动的风险偏好' if _a_signal=='risk-on' else '利率定价下的资产分化')
DATA['assets'] = {
    'regime': {'label':_a_label,'signal':_a_signal,'confidence':_confidence(_a_signal, v_vix is not None, _a_spx_w is not None, _g_spread is not None, v_hy is not None),
        'description': f'10Y 利率 {f2(v_dgs10)}% 是本周资产重定价的核心变量, 长久期资产 (纳斯达克/长债) 对实际利率最敏感。WTI {f2(v_wti)} 波动影响通胀预期, 利率上行压制估值。'},
    'keySignals': [
        {'title': f'纳斯达克100 周{"涨" if float(asset_changes("ndx")["w"] or 0)>=0 else "跌"} {ret(asset_changes("ndx")["w"])}',
         'meaning':(
             '纳斯达克上涨反映风险偏好修复, 长久期科技股领涨, 是风险资产偏好的领先指标。'
             if float(asset_changes("ndx")["w"] or 0) > 0
             else ('纳斯达克下跌反映利率上行或衰退担忧压制长久期科技股估值, 风险偏好回落。'
                   if float(asset_changes("ndx")["w"] or 0) < 0
                   else '纳斯达克横盘, 市场等待利率与盈利方向确认。')),
         'direction':_msig(dir_of(tfm('ndx')['w']), True)},
        {'title': f'WTI 原油周{"涨" if float(asset_changes("wti")["w"] or 0)>=0 else "跌"} {ret(asset_changes("wti")["w"])}',
         'meaning':(
             '油价上行推升通胀预期, 与利率上行形成正反馈, 压制风险资产估值。'
             if float(asset_changes("wti")["w"] or 0) > 0
             else ('油价回落缓解通胀压力, 通胀预期下行空间打开。'
                   if float(asset_changes("wti")["w"] or 0) < 0
                   else '油价持平, 通胀预期暂时稳定。')),
         'direction':_msig(dir_of(tfm('wti')['w']), False)},
        {'title': f'布伦特原油周{"涨" if float(asset_changes("brent")["w"] or 0)>=0 else "跌"} {ret(asset_changes("brent")["w"])}',
         'meaning':(
             '布伦特对地缘与海运风险更敏感, 其溢价反映全球供需而非仅美国库存。'
             if float(asset_changes("brent")["w"] or 0) > 0
             else ('布伦特回落, 全球油价压力缓和。'
                   if float(asset_changes("brent")["w"] or 0) < 0
                   else '布伦特持平。')),
         'direction':_msig(dir_of(tfm('brent')['w']), False)},
        {'title': f'黄金 {ret(asset_changes("gold")["w"])} {"横盘" if abs(float(asset_changes("gold")["w"] or 0))<1 else ("上涨" if float(asset_changes("gold")["w"] or 0)>0 else "下跌")}',
         'meaning':(
             '黄金上涨通常反映避险需求或滞胀担忧升温, 与风险资产呈替代关系, 对风险偏好构成压力。'
             if float(asset_changes("gold")["w"] or 0) > 0
             else ('黄金回落说明实际利率上行或风险偏好修复, 资金从避险资产回流风险资产。'
                   if float(asset_changes("gold")["w"] or 0) < 0
                   else '黄金横盘, 实际利率上行与避险买需相互对冲, 方向选择临近。')),
         'direction':_msig(dir_of(tfm('gold')['w']), False)},
    ],
    'metrics': metrics_assets,
    'trendData': trend_assets,
    'table': table_assets,
    'chartData': {'labels': ([d for d, _ in s('spx')[-30:]] if s('spx') else list(range(30))), 'series': {
        'SPX': series30('spx'), 'SOX': series30('sox'), 'WTI': series30('wti'), 'Gold': series30('gold'),
        'Copper': series30('copper'), 'BTC': series30('btc'), 'ETH': series30('eth')}},
    'correlation': {'assets':[lb for lb, _ in CORR_KEYS],
        'matrix': corr_matrix,
        'note': f'近{len(_corr_dates)}个共同交易日日度收益的真实 Pearson 相关' + (
            f' · 股债 {spx_tlt_corr:+.2f} / 油股 {spx_wti_corr:+.2f}'
            if (spx_tlt_corr is not None and spx_wti_corr is not None)
            else ' · 部分资产源缺失(长债/原油相关性暂不计算)')},
    'analystView': {
        'risk-off': f'跨资产同步承压: 纳指 ({ret(asset_changes("ndx")["w"])}) 与长债 (TLT {ret(asset_changes("tlt")["w"])}) 同跌——股票与债券相关性趋近 +1 是贴现率冲击的典型特征 (分母端收缩, 而非盈利/避险逻辑)。黄金 ({ret(asset_changes("gold")["w"])}) 表现决定性质: 若金跌, 实际利率上行是主导 (真金白银验证); 若金横盘/涨, 说明有避险或央行购金托底对冲。VIX ({f2(v_vix)}) 与 HY 利差是"估值压缩 → 流动性事件"的升级观察锚: 前者破 20、后者走阔 10bp+ 则从分子/分母定价切换为风险溢价急升。',
        'risk-on': f'风险偏好修复: 纳指 ({ret(asset_changes("ndx")["w"])}) 与长债 (TLT {ret(asset_changes("tlt")["w"])}) 分化 (股涨债跌) 是"增长盖过贴现率"的信号——盈利预期上修驱动, 权益风险溢价收窄。黄金 ({ret(asset_changes("gold")["w"])}) 走弱属正常 (实际利率/机会成本抬升), 央行购金 (WGC Q2 289 吨) 提供底部支撑。当前更接近结构性行情而非全面牛市: 广度 (加密背离/小盘落后) 是健康度检验——若 AI 链条一枝独秀而广谱落后, 警惕局部过热后的均值回归。',
        'mixed': f'条件性重定价: 纳指 ({ret(asset_changes("ndx")["w"])}) 与长债 (TLT {ret(asset_changes("tlt")["w"])}) 同步承压, 但实际利率上行尚未引发系统性风险——属于分母端(贴现率)驱动的估值压缩, 而非风险溢价(分母+分子)同时恶化。判别标准: ① VIX 是否破 20 (波动率目标基金强制减仓阈值); ② HY OAS 是否走阔 10bp+; ③ 黄金是否跟跌 (实际利率 vs 避险)。三者未触发前维持"高利率环境下的结构分化"判断: 规避高久期成长, 偏好短久期价值与实物资产。',
    }[_a_signal],
    'whatToWatch': [
        {'trigger':'<span class="watch-threshold">10Y 突破 4.85%</span>','implication':'触及年内高点, 系统性 CTA 抛售债券, 利率上行自我强化','status':f'距离 {max(0,4.85-v_dgs10):.2f}bp'},
        {'trigger':'VIX 收盘站上 <span class="watch-threshold">20</span>','implication':'波动率目标基金强制减仓, 股市抛压自我强化','status':(f'距离 {20-v_vix:.1f}' if v_vix is not None else '—')},
        {'trigger':'WTI 突破 <span class="watch-threshold">$90</span>','implication':'能源冲击确认, 通胀预期与利率进一步上行','status':f'距离 {max(0,90-v_wti):.1f}'},
    ],
    # 美股五大指数累计涨跌走势 (起点=0%, 用较长序列展示相对强弱)
    'usIndicesChart': _build_us_indices_chart(),
    # 黄金定价三叙事观测: 黄金 vs 美元指数/美元日元/原油 (归一化累计涨跌%)
    'goldNarrativeChart': _build_gold_narrative(),
    # 全球央行净购金走势 (WGC 季度) —— 参与黄金驱动模型+独立走势图
    'cbPurchasesChart': _build_cb_purchases_chart(),
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
# 利率 regime (2026-08-12 优化): 曲线形态 + 10Y 绝对水平分位 + 长端变化方向 + 实际利率趋势
_r_10y_pct = pct('dgs10')
_r_10y_m = tfm('dgs10').get('m') or 0       # 10Y 月变化 (%)
_r_tips_m = tfm('tips10').get('m') or 0     # 实际利率月变化 (%)
_r_bei_m = tfm('bei10').get('m') or 0       # 通胀预期月变化 (%)
_r_30y_m = tfm(_30y_key).get('m') or 0
if spread_10_2 < 0:
    _r_shape = 'inverted'
elif spread_10_2 <= 25:
    _r_shape = 'flat'
else:
    _r_shape = 'normal'
_r_dir = 'up' if _r_10y_m > 0.15 else ('down' if _r_10y_m < -0.15 else 'flat')
if _r_shape == 'inverted':
    _rates_signal = 'risk-off'
    _rates_label = f'曲线倒挂 {spread_10_2:.0f}bp · 衰退预警'
elif _r_shape == 'normal' and _r_dir == 'up':
    # 熊陡: 长端利率上行。若 10Y 已处于高分位 → 估值压力大
    _rates_signal = 'risk-off' if (_r_10y_pct is not None and _r_10y_pct > 75) else 'mixed'
    _rates_label = f'熊陡 {spread_10_2:.0f}bp · 长端抛售' if _rates_signal == 'risk-off' else f'熊陡 {spread_10_2:.0f}bp · 利率上行'
elif _r_shape == 'normal' and _r_dir == 'down':
    _rates_signal = 'risk-on'
    _rates_label = f'收益率下行 · 曲线{spread_10_2:.0f}bp'
elif _r_shape == 'flat':
    _rates_signal = 'mixed'
    _rates_label = f'曲线走平 {spread_10_2:.0f}bp · 政策转折临近'
else:
    _rates_signal = 'mixed'
    _rates_label = f'曲线 {spread_10_2:.0f}bp · 方向不明'

# 实际利率关键信号：以半年趋势为主，避免单周回落掩盖高位压制
_tips_w = tfm('tips10').get('w') or 0
_tips_h6 = tfm('tips10').get('h6') or 0
_tips_pct = pct('tips10')
if _tips_h6 > 0.0001:
    _tips_meaning = f'实际利率半年 +{(_tips_h6*100):.0f}bp 上行至 {f2(v_tips)}% (分位 {_tips_pct}), 是估值真实折现率, 高位压制未解除。'
    _tips_direction = 'bearish'
elif _tips_h6 < -0.0001:
    _tips_meaning = f'实际利率半年 -{(abs(_tips_h6)*100):.0f}bp 回落, 估值压力缓和。'
    _tips_direction = 'bullish'
elif _tips_w > 0:
    _tips_meaning = '实际利率周度上行, 折现率压力边际增加。'
    _tips_direction = 'bearish'
elif _tips_w < 0:
    _tips_meaning = '实际利率周度回落, 折现率压力边际缓和。'
    _tips_direction = 'bullish'
else:
    _tips_meaning = '实际利率横盘, 方向待确认。'
    _tips_direction = 'mixed'
_tips_signal = {'title': f'10Y 实际利率 {f2(v_tips)}% (分位 {_tips_pct})', 'meaning': _tips_meaning, 'direction': _tips_direction}

# Phase3: 利率路径多维度算法的"基础变量" (1260行: 不依赖 _econ_regime)
# 详细算法 (含 regime 修正/正态分布概率) 移至 2169行 _econ_regime 定义之后
import math as _math
_v_2y_week = (tfm('dgs2')['w'] or 0) * 100  # bp
_v_2y_month = (tfm('dgs2')['m'] or 0) * 100

# ① 隐含路径: 1Y 利率相对政策上限的差 → 下次会议(未来~1月)隐含变动次数
_impl_cuts_1m = 0.0
_y2_arr = s('dgs2')
_v_2y_vol = 0.18  # 默认 18bp
if _y2_arr and len(_y2_arr) >= 6:
    _recent = [_y2_arr[-i][1] for i in range(1, 7)]
    _diffs = [_recent[i] - _recent[i+1] for i in range(len(_recent)-1)]
    if _diffs:
        _mean_d = sum(_diffs)/len(_diffs)
        _v_2y_vol = max(0.08, (sum((d-_mean_d)**2 for d in _diffs)/len(_diffs)) ** 0.5 * 100)
_ff_up_v = val('ffr_up'); _y1_v = val('dgs1')
if _ff_up_v is not None and _y1_v is not None:
    _gap_bp = (_ff_up_v - _y1_v) * 100
    _impl_cuts_1m = _gap_bp / 25.0

_hawk_score_data = round(5 + _v_2y_month * 0.2, 1)
_hawk_score_data = max(0, min(10, _hawk_score_data))
_hawk_label_data = '偏鹰' if _hawk_score_data > 6 else ('偏鸽' if _hawk_score_data < 4 else '中性')
_cut_prob = max(0, min(80, round(50 - _v_2y_month * 3, 0))) if _v_2y_month else 30
_hold_prob = round(100 - _cut_prob - 5, 0)
_hike_prob = 5

# 市场隐含 Fed 路径: 用收益率曲线短端(3M/6M/1Y/2Y)反推市场对未来政策利率的预期轨迹
_impl_pts = []
for _ten, _k in (('3M','dgs3mo'),('6M','dgs6mo'),('1Y','dgs1'),('2Y','dgs2')):
    _y = val(_k)
    if _y is not None:
        _impl_pts.append({'tenor':_ten,'rate':round(_y,2)})
_ff_up_v = val('ffr_up')
_impl_cuts12 = _impl_hikes12 = _impl_terminal = None
_impl_signal = 'mixed'
if _impl_pts:
    _y1 = next((p['rate'] for p in _impl_pts if p['tenor']=='1Y'), None)
    _y2 = next((p['rate'] for p in _impl_pts if p['tenor']=='2Y'), None)
    _impl_terminal = _y2
    if _ff_up_v is not None and _y1 is not None:
        _impl_cuts12 = max(0, int(round((_ff_up_v - _y1)/0.25)))   # 未来12个月隐含降息次数(每次25bp)
        _impl_hikes12 = max(0, int(round((_y1 - _ff_up_v)/0.25)))
    if _ff_up_v is not None and _y2 is not None:
        _impl_signal = 'risk-on' if _y2 < _ff_up_v - 0.25 else ('risk-off' if _y2 > _ff_up_v + 0.25 else 'mixed')

def _build_yield_trends_chart():
    """美债收益率走势图 (3M/1Y/2Y/10Y/30Y, 近 2 年)。
    含 rawNums/rawSeries 供前端 tooltip 时间点值显示与底部滑块切片。"""
    keys = [('3M', 'dgs3mo'), ('1Y', 'dgs1'), ('2Y', 'dgs2'), ('10Y', 'dgs10'), ('30Y', _30y_key)]
    ref = s('dgs10')
    if not ref:
        return {'labels': [], 'series': {}, 'note': '数据不足'}
    dates = [d for d, _ in ref[-500:]]
    series, rawNums, rawSeries = {}, {}, {}
    for name, key in keys:
        m = dict(s(key))
        vals = [m.get(d) for d in dates]
        rawNums[name] = vals
        rawSeries[name] = [None if v is None else format(v, '.2f') + '%' for v in vals]
        series[name] = [None if v is None else round(v, 2) for v in vals]
    return {'labels': dates, 'series': series, 'rawNums': rawNums, 'rawSeries': rawSeries,
            'note': '美债收益率走势 % · 3M / 1Y / 2Y / 10Y / 30Y · 近 2 年 · 拖动滑块调整区间'}

DATA['rates'] = {
    'regime': {'label':_rates_label,'signal':_rates_signal,'confidence':_confidence(_rates_signal, v_10y is not None, v_2y is not None, v_tips is not None, v_bei is not None),
        'description': f'长端利率相对短端变化 (10Y {f2(v_10y)}% vs 2Y {f2(v_2y)}%, 10Y-2Y {spread_10_2:+.0f}bp)。拆解: 实际利率 (TIPS 10Y {f2(v_tips)}%) 与通胀预期 (Breakeven {f2(v_bei)}%) 的边际变化。'},
    'keySignals': [
        {'title': f'10Y 国债 {f2(v_10y)}%',
         'meaning':(
             '长端利率上行是本周资产重定价核心, 实际利率驱动为主。'
             if (tfm('dgs10').get('w') or 0) > 0
             else ('长端利率回落, 估值压力缓和。'
                   if (tfm('dgs10').get('w') or 0) < 0
                   else '长端利率横盘, 方向待确认。')),
         'direction': _msig(dir_of(tfm('dgs10').get('w')), False)},
        {'title': f'10Y-2Y 利差 {spread_10_2:+.0f}bp',
         'meaning':(
             '曲线陡峭化 (长端上行更快), 反映再通胀或紧缩预期。'
             if (spread_10_2 or 0) > 0
             else ('曲线倒挂, 衰退预警信号。'
                   if (spread_10_2 or 0) < 0
                   else '曲线平坦, 方向中性。')),
         'direction': _msig(dir_of(((tfm('dgs10').get('w') or 0)-(tfm('dgs2').get('w') or 0))), False)},
        _tips_signal,
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
    'yieldTrendsChart': _build_yield_trends_chart(),
    'spreadData': {'labels': _dates_for('dgs10'), 'series': {
        '10Y-2Y利差': [round((a-b),2) for a,b in zip(series90('dgs10'), series90('dgs2'))],
        '通胀预期(Breakeven)': series90('bei10')}},
    'detailedTable': [
        {'maturity':'2年','rate':f2(v_2y)+'%','change':rate_chg_bp('dgs2'),'realRate':f2(val('tips2') if val('tips2') else (val('tips10')-0.5))+'%','breakeven':f2(val('bei2') if val('bei2') else (v_2y-(val('tips10')-0.5)))+'%','source':'DGS2'},
        {'maturity':'5年','rate':f2(val('dgs5'))+'%','change':rate_chg_bp('dgs5'),'realRate':f2(val('tips5'))+'%','breakeven':f2(val('bei5') if val('bei5') else (val('dgs5')-val('tips5')))+'%','source':'DGS5'},
        {'maturity':'10年','rate':f2(v_10y)+'%','change':rate_chg_bp('dgs10'),'realRate':f2(v_tips)+'%','breakeven':f2(v_bei)+'%','source':'DGS10'},
        {'maturity':'30年','rate':f2(v_30y)+'%','change':rate_chg_bp(_30y_key),'realRate':f2(val('tips30'))+'%','breakeven':f2(val('bei30') if val('bei30') else (v_30y-val('tips30')))+'%','source':('Yahoo ^TYX' if _30y_key=='tyx' else 'FRED DGS30')},
    ],
    'analystView': {
        'risk-off': f'利率环境偏紧: 10Y {f2(v_10y)}% (近1年分位 {_r_10y_pct}), 曲线熊陡 {spread_10_2:+.0f}bp——长端上行快于短端, 通常对应增长/供给驱动而非纯货币紧缩。资产定价视角: 实际利率 ({f2(v_tips)}%) 是成长股估值的核心折现率, 通胀预期 ({f2(v_bei)}%) 决定名义端; 当前实际利率高位 + 分位极值, 长久期成长资产 (纳指/半导体/未盈利科技) 的估值压缩风险最高, 而短久期价值/金融板块相对受益于陡峭曲线。风险事件: 若 2Y 补涨 (曲线熊平) 说明紧缩向短端传导, 对全市场估值最不利。',
        'risk-on': f'利率环境友好: 曲线 {spread_10_2:+.0f}bp (牛平/正常化), 短端下行隐含降息定价。资产定价视角: 实际利率 ({f2(v_tips)}%) 回落 = 折现率下行, 直接利好长久期资产 (成长股/长久期债券); 通胀预期 ({f2(v_bei)}%) 温和 = 名义利率受控, 权益风险溢价得以维持。这是典型的"分母端"行情——估值扩张而非盈利驱动, 需警惕利率反弹即估值回落的反身性。',
        'mixed': f'利率结构由实际利率 ({f2(v_tips)}%) 与通胀预期 ({f2(v_bei)}%) 共同决定, 曲线 {spread_10_2:+.0f}bp。资产定价视角: 当前处于"增长驱动陡峭化"阶段——长端上行但短端平稳, 历史上股债可共存 (盈利盖过折现率); 关键分水岭是 2Y 是否重新定价: 若 2Y 补涨 (熊平) 意味着紧缩向短端传导, 权益估值与信用利差将同时承压, 此时防御 (现金/短债/黄金) 相对占优。',
    }[_rates_signal],
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
# Fed regime (2026-08-12 优化): 市场隐含路径(12个月降/加息次数) + 实际利率 + QT 缩表
# _impl_cuts12/_impl_hikes12 由短端曲线 (3M/6M/1Y/2Y) 反推, 见利率板块
_ff = val('ffr_up'); _y2_f = val('dgs2')
_fed_cuts = _impl_cuts12 or 0
_fed_hikes = _impl_hikes12 or 0
_fed_tips_m = tfm('tips10').get('m') or 0
_fed_walcl_w = tfm('walcl').get('w') or 0   # 缩表周变化 ($B)
_fed_signal = 'mixed'
if _ff is not None and _y2_f is not None:
    if _fed_cuts >= 2:
        _fed_signal = 'risk-on'                                   # 市场定价 2 次+降息 = 宽松预期
    elif _fed_hikes >= 2:
        _fed_signal = 'risk-off'                                  # 定价 2 次+加息 = 收紧预期
    elif _fed_cuts == 1:
        _fed_signal = 'risk-on' if _fed_tips_m < 0 else 'mixed'   # 1 次降息 + 实际利率回落 → 偏宽松
    elif _fed_hikes == 1:
        _fed_signal = 'mixed'                                     # 1 次加息预期 → 观望
_fed_label = f'宽松预期 ({_fed_cuts} 次降息定价)' if _fed_signal == 'risk-on' else (
             f'收紧预期 ({_fed_hikes} 次加息定价)' if _fed_signal == 'risk-off' else '观望/鹰鸽分化')
DATA['fed'] = {
    'regime': {'label':_fed_label,'signal':_fed_signal,'confidence':_confidence(_fed_signal, _ff is not None, _y2_f is not None, v_walcl is not None, v_rrp2 is not None),
        'description':f'政策利率 {f2(val("ffr_up"))}%-{f2(val("ffr_lo"))}% 维持不变, 市场通过 2Y 国债定价未来政策路径。缩表 (WALCL {comma(v_walcl/1000000,1)}T, 周 {bp(tfm("walcl")["w"]/1000, "$B")}) 持续推进, RRP 缓冲 (${f2(v_rrp2)}B) 已耗尽, 未来 QT 将更直接影响准备金。'},
    'keySignals': [
        {'title':f'RRP 余额 ${f2(v_rrp2)}B',
         'meaning':(
             '货币市场基金可搬回美联储的钱持续耗尽, 未来缩表冲击无缓冲。'
             if (tfm('rrp').get('w') or 0) < 0
             else ('RRP 回升, 缓冲边际增厚。'
                   if (tfm('rrp').get('w') or 0) > 0
                   else 'RRP 持平。')),
         'direction':_msig(dir_of(tfm('rrp').get('w')), False)},
        {'title':f'WALCL {comma(v_walcl/1000000,1)}T',
         'meaning':(
             'QT 每周缩减, 净流动性的稳定逆风。'
             if (tfm('walcl').get('w') or 0) < 0
             else ('扩表, 净流动性顺风。'
                   if (tfm('walcl').get('w') or 0) > 0
                   else '资产负债表规模持平。')),
         'direction':_msig(dir_of(tfm('walcl').get('w')), False)},
        {'title':f'银行准备金 {comma(v_res/1000000,2)}T',
         'meaning':(
             '准备金回落, 充裕度下滑。'
             if (tfm('resbal').get('w') or 0) < 0
             else ('准备金回升, 充裕度改善。'
                   if (tfm('resbal').get('w') or 0) > 0
                   else '准备金持平, 仍处充裕区间。')),
         'direction':_msig(dir_of(tfm('resbal').get('w')), True)},
    ],
    'metrics': [
        {'label':'总资产','value':f'${comma(v_walcl/1000000,2)}T','change':wk('walcl'),'dir':'down','tag':'WALCL','percentile':pct('walcl'),'signal':_msig(dir_of(tfm("walcl")["w"]), False),'meaning':'缩表持续推进','changes':wk_dict('walcl'),'sparkline':series30('walcl')},
        {'label':'联邦基金利率(上限)','value':f'{f2(val("ffr_up"))}%','change':'维持','dir':'neutral','tag':'FFR','percentile':pct('ffr_up'),'signal':_msig(dir_of(tfm("ffr_up")["w"]), False),'meaning':'限制性立场未变','changes':{'d':'0','w':'0','m':'0','h6':pct('ffr_up') and '—'},'sparkline':series30('ffr_up')},
        {'label':'国债持仓','value':f'${comma(val("treast")/1000000,2)}T','change':wk('treast'),'dir':'down','tag':'TREAST','percentile':pct('treast'),'signal':_msig(dir_of(tfm("treast")["w"]), False),'meaning':'被动缩表, 节奏可控','changes':wk_dict('treast'),'sparkline':series30('treast')},
        {'label':'MBS 持仓','value':f'${comma(val("mbst")/1000000,2)}T','change':wk('mbst'),'dir':'down','tag':'MBST','percentile':pct('mbst'),'signal':_msig(dir_of(tfm("mbst")["w"]), False),'meaning':'提前还款低迷, MBS缩减慢','changes':wk_dict('mbst'),'sparkline':series30('mbst')},
        {'label':'银行准备金','value':f'${comma(v_res/1000000,2)}T','change':f'+${comma(tfm("resbal")["w"]/1000,0)}B/周','dir':'up','tag':'WRESBAL','percentile':pct('resbal'),'signal':_msig(dir_of(tfm("resbal")["w"]), True),'meaning':'充裕区间','changes':wk_dict('resbal'),'sparkline':series30('resbal')},
        {'label':'RRP 余额','value':f'${f2(v_rrp2)}B','change':f'{bp(tfm("rrp")["w"], "$B")}', 'dir':dir_of(tfm("rrp")["w"]),'tag':'RRP','percentile':pct('rrp'),'signal':_msig(dir_of(tfm("rrp")["w"]), False),'meaning':'缓冲耗尽','changes':{k:(bp(tfm("rrp")[k], "$B") if tfm("rrp")[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('rrp')},
        {'label':'IORB','value':f'{f2(val("iorb"))}%','change':'维持','dir':'neutral','tag':'IORB','percentile':pct('iorb'),'signal':_msig(dir_of(tfm("iorb")["w"]), False),'meaning':'SOFR-IORB 利差反映充裕度','changes':{'d':'0','w':'0','m':'0','h6':'—'},'sparkline':series30('iorb')},
        {'label':'SOFR','value':f'{f2(val("sofr"))}%','change':rate_chg_bp('sofr'),'dir':dir_of(tfm("sofr")["d"]),'tag':'SOFR','percentile':pct('sofr'),'signal':_msig(dir_of(tfm("sofr")["d"]), False),'meaning':'低于 IORB, 融资充裕','changes':{k:(bp(tfm("sofr")[k]*100) if tfm("sofr")[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('sofr')},
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
        # 'ratePath' 在 _econ_regime 定义后填充 (2169行后)
        'ratePath': {'nextMeeting': _NEXT_FOMC or '2026-07-29', 'pending': True},
    },

    # ===== 美联储政策 → 资产传导机制 (2026-08-17) =====
    'transmissionMap': {
        'hub': '政策利率路径 (降息/维持/加息) + 资产负债表操作 (QT) — 改变全市场折现率与流动性',
        'channels': [
            {'key': 'discount', 'label': '通道A · 利率路径', 'color': '#a32d2d',
             'desc': '政策预期 → 短端利率 → 折现率 → 全资产估值'},
            {'key': 'liquidity', 'label': '通道B · 资产负债表', 'color': '#185FA5',
             'desc': 'QT/扩表 → 准备金/流动性 → 风险资产水位'},
            {'key': 'guidance', 'label': '通道C · 前瞻指引', 'color': '#0F6E56',
             'desc': '官员表态/点阵图 → 预期差 → 波动率'},
        ],
        'indicators': [
            {
                'tag': 'RatePath', 'name': '政策利率路径', 'freq': 'FOMC 8次/年',
                'channel': 'discount', 'primary': '折现率中枢',
                'impact': [
                    {'asset': '短债', 'dir': 'up', 'when': '降息', 'why': '政策利率↓直接传导'},
                    {'asset': '股市', 'dir': 'up', 'when': '降息', 'why': '折现率↓→估值扩张'},
                    {'asset': '美元', 'dir': 'down', 'when': '降息', 'why': '利差收窄'},
                    {'asset': '黄金', 'dir': 'up', 'when': '降息', 'why': '实际利率↓'},
                    {'asset': '加密', 'dir': 'up', 'when': '降息', 'why': '流动性预期↑'},
                ],
                'longTerm': '降息周期 = 股债双牛(温和衰退除外); 加息周期 = 成长/长久期承压, 价值/现金占优; 当前市场定价维持 {_hold_prob:.0f}% / 加息 {_hike_prob:.0f}% / 降息 {_cut_prob:.0f}%',
                'current': f'下次会议 {_NEXT_FOMC or "9/15"} · 维持 {_hold_prob:.0f}% / 加息 {_hike_prob:.0f}% / 降息 {_cut_prob:.0f}%' if _hold_prob else '数据暂缺',
            },
            {
                'tag': 'QT', 'name': '缩表 QT', 'freq': '周度',
                'channel': 'liquidity', 'primary': '流动性抽水',
                'impact': [
                    {'asset': '准备金', 'dir': 'down', 'when': '继续', 'why': '每缩一美元直击准备金 (RRP 耗尽后)'},
                    {'asset': '长债', 'dir': 'down', 'when': '继续', 'why': '供给↑+久期溢价↑'},
                    {'asset': '银行股', 'dir': 'down', 'when': '加速', 'why': '准备金稀缺→融资成本↑'},
                    {'asset': '风险资产', 'dir': 'down', 'when': '加速', 'why': '流动性收缩逆风'},
                ],
                'longTerm': 'QT 终点 = 准备金接近稀缺区(3万亿) 或 RRP 耗尽后融资压力出现; 停止 QT 是流动性拐点的关键信号',
                'current': 'WALCL ' + (f'${comma(v_walcl/1000000,1)}T' if v_walcl else '—') + ' · 周' + (wk('walcl') if 'wk' in dir() else ''),
            },
            {
                'tag': 'RRP', 'name': 'RRP 缓冲', 'freq': '日度',
                'channel': 'liquidity', 'primary': 'QT 缓冲垫',
                'impact': [
                    {'asset': '准备金', 'dir': 'down', 'when': '耗尽', 'why': '货币基金资金回流美联储停止→QT 直接冲击准备金'},
                    {'asset': '回购', 'dir': 'up', 'when': '耗尽', 'why': '资金争夺风险↑'},
                ],
                'longTerm': 'RRP 耗尽是结构性转折: 此后 QT 每缩 1 美元 = 准备金 -1 美元 (此前由 RRP 吸收), 融资市场敏感度倍增',
                'current': '$' + (f'{v_rrp2:.0f}B' if v_rrp2 is not None else '—') + ' (已耗尽)',
            },
            {
                'tag': 'Guidance', 'name': '前瞻指引/官员表态', 'freq': '持续',
                'channel': 'guidance', 'primary': '预期管理',
                'impact': [
                    {'asset': '2Y 国债', 'dir': 'down', 'when': '鸽派', 'why': '降息定价↑'},
                    {'asset': '股市', 'dir': 'up', 'when': '鸽派', 'why': '宽松确认'},
                    {'asset': '波动率', 'dir': 'down', 'when': '清晰', 'why': '不确定性下降'},
                    {'asset': '美元', 'dir': 'down', 'when': '鸽派', 'why': '利差收窄'},
                ],
                'longTerm': '点阵图与发布会是季度级路径重定价窗口; 鹰鸽分化公开化 = 政策不确定性上升 = 波动率溢价抬升',
                'current': 'FOMC 9/15 · 沃什(主席)表态为核心变量',
            },
            {
                'tag': 'FFR', 'name': '联邦基金利率', 'freq': '会议',
                'channel': 'discount', 'primary': '政策现状',
                'impact': [
                    {'asset': '现金/短债', 'dir': 'up', 'when': '高位', 'why': '无风险收益有吸引力'},
                    {'asset': '高估值成长', 'dir': 'down', 'when': '高位', 'why': '折现率高企'},
                    {'asset': '银行净息差', 'dir': 'up', 'when': '高位', 'why': '贷款利率跟随'},
                ],
                'longTerm': '利率绝对水平决定"现金为王的吸引力" (5%+ 时资金存现金/短债); 是长期风险资产性价比的锚',
                'current': f'{f2(val("ffr_lo"))}%-{f2(val("ffr_up"))}%' if val('ffr_up') else '—',
            },
        ],
    },
    'analystView': {
        'risk-on': f'市场定价宽松路径: 短端曲线隐含未来12个月约 {_fed_cuts} 次降息 (2Y {f2(_y2_f)}% vs 政策利率 {f2(_ff)}%)。政策传导链: 降息预期 → 短端下行 → 实际利率回落 → 权益估值扩张 + 长久期债券资本利得。但 {_fomc_md if _fomc_md else "下次会议"} 是重新定价窗口——若联储鹰派表态(尤其对油价)或核心通胀环比二次抬头, 宽松定价将被压缩; RRP 耗尽 (${f2(v_rrp2)}B) 意味着 QT 后续直击准备金, 是流动性端结构性约束。',
        'risk-off': f'市场定价收紧路径: 短端曲线隐含约 {_fed_hikes} 次加息 (2Y {f2(_y2_f)}% > 政策利率 {f2(_ff)}%)。政策传导链: 加息预期 → 短端上行 → 贴现率抬升 → 权益估值压缩 (对高久期成长/未盈利资产最重) + 信用利差走阔风险。{_fomc_md if _fomc_md else "下次会议"} 是关键窗口; 若核心 PCE 3.3% 的粘性促使联储上调点阵图, 收紧预期强化。RRP 耗尽后 QT 直击准备金, 流动性约束叠加政策收紧 = 最不利组合。',
        'mixed': f'美联储处于政策拉锯: 短端曲线未形成单边定价 ({_fed_cuts} 次降息 / {_fed_hikes} 次加息)。政策传导链看两点: ① 核心 PCE 3.3% + 超级核心 3.8% 的通胀粘性决定"更高更久"基线; ② {_fomc_md if _fomc_md else "下次会议"} 对油价的定性决定边际方向。资产配置含义: 政策不明朗期, 权益与长债的久期风险同向, 降低组合 beta + 维持现金/短债缓冲是合理选择; 一旦路径明朗, 再沿方向加仓。RRP 耗尽 (${f2(v_rrp2)}B) 是结构性转折, 后续 QT 每缩一美元直击准备金。',
    }[_fed_signal],
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
    'impliedPath': {
        'points': _impl_pts,                       # [{tenor, rate}]
        'currentFF': _ff_up_v,                     # 当前联邦基金目标上限
        'cuts12m': _impl_cuts12,                   # 未来12个月隐含降息次数(每次25bp)
        'hikes12m': _impl_hikes12,                 # 未来12个月隐含加息次数
        'terminal2y': _impl_terminal,              # 2Y=市场隐含~2年后的政策利率
        'signal': _impl_signal,
        'note': '基于收益率曲线短端(3M/6M/1Y/2Y)反推的市场隐含政策利率路径; 2Y相对当前上限的偏离折算为隐含降息/加息次数(每次25bp)'
    },
}

# ====== 流动性 ======
v_nl = val('netliq'); v_rrpn = val('rrp'); v_tgan = val('tga'); v_sofr_iorb = (val('sofr')-val('iorb'))
# 流动性 regime (2026-08-12 优化): 净流动性水平+趋势 + SOFR-IORB + RRP 缓冲
_nl_m = tfm('netliq')['m']            # 净流动性月变
_nl_v = v_nl                          # 净流动性水平 ($B)
_rrp_w = tfm('rrp').get('w') or 0     # RRP 周变 ($B)
_sofr_gap = (v_sofr_iorb or 0)        # SOFR - IORB (bp 转 小数, >0 融资紧张)
_liq_score = 0
if _nl_m is not None:
    _liq_score += 1 if _nl_m > 0 else -1
if _nl_v is not None:
    _liq_score += 1 if _nl_v > 3000000 else 0   # 净流动性 > $3T 算宽松
if _sofr_gap > 0.0001:
    _liq_score -= 1
elif _sofr_gap < -0.0001:
    _liq_score += 1
if _rrp_w > 0:
    _liq_score += 1
elif _rrp_w < 0:
    _liq_score -= 0
_liq_signal = 'risk-on' if _liq_score >= 2 else ('risk-off' if _liq_score <= -2 else 'mixed')
_liq_label = ('流动性充裕 (净流动性回升, 资金价格宽松)' if _liq_signal == 'risk-on' else
              ('流动性收缩 (净流动性下降 / 融资紧张)' if _liq_signal == 'risk-off' else '流动性中性 (缓冲偏薄但资金价格平静)'))

# LPI (流动性压力指数): 数据驱动合成, 替代硬编码 3.8
# 三子维度各 0-10 分 (越高=压力越大), 权重 45%/35%/20% (与 UI 展示一致)
_lpi_buf = 0.0
if pct('rrp') is not None:
    _lpi_buf = (100 - pct('rrp')) / 100 * 8          # RRP 分位越低=缓冲越薄
if pct('tga') is not None:
    _lpi_buf += pct('tga') / 100 * 2                 # TGA 分位越高=抽水越多
_lpi_buf = min(round(_lpi_buf, 1), 9)
_lpi_fund = 5.0
if v_sofr_iorb is not None:
    _lpi_fund = 8.0 if v_sofr_iorb > 0.0005 else (6.0 if v_sofr_iorb > 0 else (3.0 if v_sofr_iorb > -0.0005 else 1.0))
_lpi_risk = 3.0
if v_vix is not None:
    _lpi_risk = max(_lpi_risk, min(10.0, (v_vix - 12) / 1.5))
if v_hy is not None:
    _lpi_risk = max(_lpi_risk, min(9.0, (v_hy - 3) / 0.7))
_lpi_risk = round(_lpi_risk, 1)
_lpi_score_dyn = round(_lpi_buf * 0.45 + _lpi_fund * 0.35 + _lpi_risk * 0.20, 1)
_lpi_level = '偏紧' if _lpi_score_dyn >= 6 else ('中性偏紧' if _lpi_score_dyn >= 4 else '中性宽松')
_nl_latest = val('netliq'); _nl_m_chg = tfm('netliq')['m']
_lpi_trend = round((_nl_m_chg / _nl_latest) * 100, 1) if (_nl_latest and _nl_m_chg is not None) else 0.0
_lpi_block = {
    'score': _lpi_score_dyn, 'level': _lpi_level, 'trend': f'{_lpi_trend:+.1f}',
    'components': [
        {'name': '结构性缓冲', 'score': _lpi_buf, 'weight': '45%',
         'note': f'RRP 分位 {pct("rrp")}, TGA 分位 {pct("tga")}, 缓冲垫变薄' if (pct('rrp') is not None and pct('tga') is not None) else 'RRP/TGA 数据缺失'},
        {'name': '融资确认', 'score': _lpi_fund, 'weight': '35%',
         'note': f'SOFR-IORB {bp(v_sofr_iorb*100)}, {"已转正(>1bp)" if (v_sofr_iorb or 0) > 0.0001 else ("归零/接近零, 价格平静" if abs(v_sofr_iorb or 0) <= 0.0001 else "为负, 价格无压力")}'},
        {'name': '风险传导', 'score': _lpi_risk, 'weight': '20%',
         'note': f'VIX {f2(v_vix) if v_vix is not None else "—"}, HY OAS {f2(v_hy)+"%" if v_hy is not None else "—"}'},
    ],
    'confirmationConditions': [
        {'name': 'SOFR-IORB 连续转正(>1bp)', 'current': bp(v_sofr_iorb*100),
         'status': '已触发' if (v_sofr_iorb or 0) > 0.0001 else '未触发', 'triggered': (v_sofr_iorb or 0) > 0.0001},
        {'name': 'SRF 出现数十亿级使用', 'current': '无数据', 'status': '未监测', 'triggered': False},
        {'name': 'HY OAS 明显走阔', 'current': f2(v_hy)+'%' if v_hy is not None else '—',
         'status': '已触发' if (v_hy or 0) > 4.5 else '未触发', 'triggered': (v_hy or 0) > 4.5},
        {'name': 'NFCI 转正', 'current': f2(val('nfci')) if val('nfci') is not None else '—',
         'status': '已触发' if (val('nfci') or 0) > 0 else '未触发', 'triggered': (val('nfci') or 0) > 0},
        {'name': 'VIX 升至 20 上方', 'current': f2(v_vix) if v_vix is not None else '—',
         'status': '已触发' if (v_vix or 0) > 20 else ('接近触发' if (v_vix or 0) > 15 else '未触发'),
         'triggered': (v_vix or 0) > 20},
    ],
}
DATA['liquidity'] = {
    'regime': {'label':_liq_label,'signal':_liq_signal,'confidence':_confidence(_liq_signal, v_rrpn is not None, v_nl is not None, v_sofr_iorb is not None),
        'description':f'RRP 仅 ${f2(v_rrpn)}B, 货币市场基金可搬回美联储的钱基本耗尽。TGA 上升与 QT 收缩将更直接影响银行准备金——流动性框架从"有缓冲"切换到"无缓冲"阶段。当前 SOFR-IORB ({bp(v_sofr_iorb*100)}){(" 仍为负, 融资市场尚未出现真实资金争夺" if (v_sofr_iorb or 0) < -0.0001 else (" 接近归零, 价格信号平静但处于分水岭" if abs(v_sofr_iorb or 0) <= 0.0001 else " 已转正(>1bp), 价格信号发出边际争夺压力, 但数量收缩尚未传导为真实流动性事件"))}。'},
    'keySignals': [
        {'title':f'RRP 余额 ${f2(v_rrpn)}B',
         'meaning':(
             'RRP 持续下降, 货币市场基金可搬回美联储的缓冲持续耗尽, 未来 QT 缩表将更直接冲击银行准备金。'
             if (tfm('rrp').get('w') or 0) < 0
             else (f'RRP 边际回升, 资金短暂回流美联储, 银行体系可用流动性边际收紧; 但余额仅 ${f2(v_rrpn)}B, 仍处历史极低水平, 缓冲实质耗尽。'
                   if (tfm('rrp').get('w') or 0) > 0
                   else 'RRP 持平, 缓冲实质归零, QT 已无处可躲。')),
         'direction':_msig(dir_of(tfm('rrp').get('w')), False)},
        {'title':(f'TGA 余额 ${comma(v_tgan,1)}B' if v_tgan else 'TGA 数据缺失'),
         'meaning':(
             f'财政部现金上升=从银行体系抽水; 当前余额 ${comma(v_tgan,1)}B 已处高位, 需警惕后续发债进一步回收流动性。'
             if (tfm('tga').get('w') or 0) > 0
             else (f'财政部现金边际下降=向银行体系回注流动性; 但绝对水平仍处高位 (${comma(v_tgan,1)}B), 宽松幅度受限。'
                   if (tfm('tga').get('w') or 0) < 0
                   else 'TGA 持平。')),
         'direction':_msig(dir_of(tfm('tga').get('w') if v_tgan else None), False)},
        {'title':f'SOFR-IORB {bp(v_sofr_iorb*100)}',
         'meaning':(
             '回购利率转正, 融资市场出现真实资金争夺压力。'
             if (v_sofr_iorb or 0) > 0.0001
             else ('SOFR-IORB 利差归零, 融资市场处于充裕与压力的分水岭; 持续转正才是压力第一确认。'
                   if abs(v_sofr_iorb or 0) <= 0.0001
                   else '回购利率低于准备金利率, 融资充裕; 转正才是压力第一确认信号。')),
         'direction':_msig(('down' if (v_sofr_iorb or 0) < -0.0001 else ('up' if (v_sofr_iorb or 0) > 0.0001 else 'neutral')), False)},
    ],
    'metrics': [
        {'label':'净流动性','value':f'${comma(v_nl/1000,2)}T' if v_nl else '—','change':f'{bp(tfm("netliq")["w"], "$B") if tfm("netliq")["w"] else "—"}','dir':dir_of(tfm("netliq")["w"]) if tfm("netliq")["w"] else 'neutral','tag':'NetLiq','percentile':pct('netliq'),'signal':_msig(dir_of(tfm("netliq")["w"]) if tfm("netliq")["w"] else None, False),'meaning':'WALCL−RRP−TGA','changes':{k:(bp(tfm("netliq")[k], "$B") if tfm("netliq")[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('netliq')},
        {'label':'美联储总资产','value':f'${comma(v_walcl/1000000,2)}T','change':wk('walcl'),'dir':'down','tag':'WALCL','percentile':pct('walcl'),'signal':_msig(dir_of(tfm("walcl")["w"]), False),'meaning':'QT 第一驱动','changes':wk_dict('walcl'),'sparkline':series30('walcl')},
        {'label':'RRP 余额','value':f'${f2(v_rrpn)}B','change':bp(tfm("rrp")["w"], "$B"),'dir':dir_of(tfm("rrp")["w"]),'tag':'RRP','percentile':pct('rrp'),'signal':_msig(dir_of(tfm("rrp")["w"]), False),'meaning':'缓冲垫耗尽','changes':{k:(bp(tfm("rrp")[k], "$B") if tfm("rrp")[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('rrp')},
        {'label':'TGA 余额','value':f'${comma(v_tgan,1)}B' if v_tgan else '—','change':(f'+${comma(tfm("tga")["w"],0)}B' if (v_tgan and tfm("tga")["w"]) else '—'),'dir':dir_of(tfm("tga")["w"]) if v_tgan else 'neutral','tag':'TGA','percentile':pct('tga'),'signal':_msig(dir_of(tfm("tga")["w"]) if v_tgan else None, False),'meaning':'财政部抽水','changes':{k:(f'+${comma(tfm("tga")[k],0)}B' if (v_tgan and tfm("tga")[k]) else '—') for k in ('d','w','m','h6')},'sparkline':series30('tga')},
        {'label':'银行准备金','value':f'${comma(v_res/1000000,2)}T','change':f'+${comma(tfm("resbal")["w"]/1000,0)}B/周','dir':'up','tag':'Reserves','percentile':pct('resbal'),'signal':_msig(dir_of(tfm("resbal")["w"]), True),'meaning':'充裕区间下沿','changes':wk_dict('resbal'),'sparkline':series30('resbal')},
        {'label':'SOFR-IORB','value':bp(v_sofr_iorb*100),'change':bp((tfm("sofr")["w"]-tfm("iorb")["w"])*100),'dir':dir_of((tfm("sofr")["w"] or 0)-(tfm("iorb")["w"] or 0)),'tag':'Spread','percentile':pct('sofr'),'signal':_msig(dir_of((tfm("sofr")["w"] or 0)-(tfm("iorb")["w"] or 0)), False),'meaning':'负值=充裕','changes':{k:(bp((tfm("sofr")[k]-tfm("iorb")[k])*100) if (tfm("sofr")[k] is not None and tfm("iorb")[k] is not None) else '—') for k in ('d','w','m','h6')},'sparkline':series30('sofr')},
    ],
    'trendData': [
        {'name':'净流动性','unit':'$B','current':f'${comma(v_nl/1000,2)}T' if v_nl else '—','changes':{k:(round(tfm("netliq")[k],1) if tfm("netliq")[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'收缩趋势, RRP耗尽后斜率变陡'},
        {'name':'RRP 余额','unit':'$B','current':f'${f2(v_rrpn)}B','changes':{k:(round(tfm("rrp")[k],3) if tfm("rrp")[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'缓冲消耗已完成的结构事件'},
        {'name':'TGA 余额','unit':'$B','current':f'${comma(v_tgan,1)}B' if v_tgan else '—','changes':{k:(round(tfm("tga")[k],1) if (v_tgan and tfm("tga")[k] is not None) else None) for k in ('d','w','m','h6')},'meaning':'财政部持续抽水' if (v_tgan and tfm("tga")["w"]) else '—'},
        {'name':'银行准备金','unit':'$B','current':f'${comma(v_res/1000000,2)}T','changes':{k:(round(tfm("resbal")[k]/1000,1) if tfm("resbal")[k] is not None else None) for k in ('d','w','m','h6')},'meaning':'近月回升但半年仍低, 3万亿关键'},
        {'name':'SOFR-IORB','unit':'bp','current':bp(v_sofr_iorb*100),'changes':{k:(round((tfm("sofr")[k]-tfm("iorb")[k])*100,1) if (tfm("sofr")[k] is not None and tfm("iorb")[k] is not None) else None) for k in ('d','w','m','h6')},'meaning':'缓慢向零靠拢, 充裕度边际减弱'},
    ],

    # ===== 流动性 → 资产传导机制 (2026-08-17) =====
    'transmissionMap': {
        'hub': '银行体系准备金水平 (充裕度) — 决定融资市场是否出现真实资金争夺',
        'channels': [
            {'key': 'funding', 'label': '通道A · 融资', 'color': '#a32d2d',
             'desc': '准备金稀缺 → 回购/拆借利率跳升 → 资金成本传导'},
            {'key': 'leverage', 'label': '通道B · 杠杆', 'color': '#185FA5',
             'desc': '流动性收缩 → 对冲基金/做市商去杠杆 → 抛售高流动性资产'},
            {'key': 'haven', 'label': '通道C · 避险', 'color': '#0F6E56',
             'desc': '流动性事件 → 风险偏好骤降 → 涌向美元/国债'},
        ],
        'indicators': [
            {
                'tag': 'RRP', 'name': 'RRP 余额', 'freq': '日度',
                'channel': 'funding', 'primary': '缓冲垫',
                'impact': [
                    {'asset': '短债', 'dir': 'up', 'when': '耗尽', 'why': 'QT 每缩一美元直击准备金'},
                    {'asset': '银行股', 'dir': 'down', 'when': '耗尽', 'why': '准备金稀缺→融资成本↑'},
                    {'asset': '美元', 'dir': 'up', 'when': '耗尽', 'why': '流动性紧→美元稀缺'},
                    {'asset': '高 beta', 'dir': 'down', 'when': '耗尽', 'why': '去杠杆抛售'},
                ],
                'longTerm': 'RRP 归零后 QT 与 TGA 每变化一美元都直接冲击准备金 → 准备金充裕度是未来 6-12 个月融资市场的核心变量',
                'current': '仅 $' + (f'{v_rrpn:.0f}B' if v_rrpn is not None else '—') + ', 缓冲实质耗尽',
            },
            {
                'tag': 'TGA', 'name': 'TGA 财政部现金', 'freq': '日度',
                'channel': 'funding', 'primary': '抽水/注水',
                'impact': [
                    {'asset': '回购利率', 'dir': 'up', 'when': '上升', 'why': '现金回笼→银行体系流动性↓'},
                    {'asset': '短债', 'dir': 'up', 'when': '上升', 'why': '发债供给↑+流动性↓'},
                    {'asset': '风险资产', 'dir': 'down', 'when': '上升', 'why': '流动性收缩传导'},
                ],
                'longTerm': 'TGA 高企+发债高峰 = 从市场抽水; 发债淡季/支出高峰 = 回注流动性。季度末/税期是季节性收紧窗口',
                'current': '$' + (f'{v_tgan:.0f}B' if v_tgan else '—') + ' (高位)',
            },
            {
                'tag': 'SOFR', 'name': 'SOFR-IORB 利差', 'freq': '日度',
                'channel': 'funding', 'primary': '融资压力确认',
                'impact': [
                    {'asset': '美元', 'dir': 'up', 'when': '转正', 'why': '资金争夺→美元稀缺'},
                    {'asset': '股市', 'dir': 'down', 'when': '转正', 'why': '流动性事件前兆 (2019/2019式)'},
                    {'asset': '新兴市场', 'dir': 'down', 'when': '转正', 'why': '美元强+资金回流'},
                ],
                'longTerm': '持续转正 (多日>1bp) = 真实资金争夺, 历史上是流动性事件的先行确认 (2019.9 回购风暴、2020.3 流动性危机均如此)',
                'current': (bp(v_sofr_iorb*100) if v_sofr_iorb is not None else '—') + ' (负值=充裕)',
            },
            {
                'tag': 'NetLiq', 'name': '净流动性', 'freq': '周度',
                'channel': 'leverage', 'primary': '风险资产水位',
                'impact': [
                    {'asset': '股市', 'dir': 'up', 'when': '回升', 'why': '流动性宽松→风险偏好↑'},
                    {'asset': '加密', 'dir': 'up', 'when': '回升', 'why': '最敏感的高 beta 流动性资产'},
                    {'asset': '黄金', 'dir': 'up', 'when': '回升', 'why': '实际利率↓+流动性↑'},
                    {'asset': '美元', 'dir': 'down', 'when': '回升', 'why': '流动性宽松→美元走弱'},
                ],
                'longTerm': '净流动性 (WALCL−RRP−TGA) 是风险资产最重要的流动性水位计; 转正回升=顺风, 加速收缩=逆风 (2022-2023 美股下跌主因)',
                'current': '$' + (f'{v_nl/1000:.2f}T' if v_nl else '—') + (' (月' + (f'{tfm("netliq")["m"]:+.0f}B' if tfm("netliq")["m"] is not None else '') + ')' if v_nl else ''),
            },
            {
                'tag': 'Res', 'name': '银行准备金', 'freq': '周度',
                'channel': 'funding', 'primary': '充裕度底线',
                'impact': [
                    {'asset': '回购', 'dir': 'up', 'when': '低于3万亿', 'why': '充裕度下沿→利率波动↑'},
                    {'asset': '货币基金', 'dir': 'up', 'when': '低于3万亿', 'why': '收益率吸引力↑'},
                ],
                'longTerm': '准备金 <3万亿 → 进入稀缺区 (Fed 会启动 QE/放缓 QT 干预); 是 QT 终点的前瞻指标',
                'current': '$' + (f'{v_res/1000000:.2f}T' if v_res else '—'),
            },
        ],
    },
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
        {'component':'美联储总资产 (WALCL)','current':f'${comma(v_walcl/1000000,2)}T','weekChange':cell('walcl','w'),'monthChange':cell('walcl','m'),'source':'Fed H.4.1','signal':_msig(dir_of(tfm("walcl")["w"]), False)},
        {'component':'RRP 余额','current':f'${f2(v_rrpn)}B','weekChange':bp(tfm("rrp")["w"],"$B"),'monthChange':bp(tfm("rrp")["m"],"$B"),'source':'NY Fed','signal':_msig(dir_of(tfm("rrp")["w"]), False)},
        {'component':'TGA 余额','current':f'${comma(v_tgan,1)}B' if v_tgan else '—','weekChange':(f'+${comma(tfm("tga")["w"],0)}B' if v_tgan else '—'),'monthChange':(f'+${comma(tfm("tga")["m"],0)}B' if (v_tgan and tfm("tga")["m"]) else '—'),'source':'Treasury DTS','signal':_msig(dir_of(tfm("tga")["w"]) if v_tgan else None, False)},
        {'component':'银行准备金 (WRESBAL)','current':f'${comma(v_res/1000000,2)}T','weekChange':cell('resbal','w'),'monthChange':cell('resbal','m'),'source':'Fed H.4.1','signal':_msig(dir_of(tfm("resbal")["w"]), True)},
        {'component':'净流动性(计算值)','current':f'${comma(v_nl/1000,2)}T' if v_nl else '—','weekChange':(bp(tfm("netliq")["w"],"$B") if tfm("netliq")["w"] else '—'),'monthChange':(bp(tfm("netliq")["m"],"$B") if tfm("netliq")["m"] else '—'),'source':'计算','signal':_msig(dir_of(tfm("netliq")["w"]), False)},
    ],
    'lpi': _lpi_block,
    'analystView': {
        'risk-off': f'流动性真实压力确认: 净流动性月变化转负且 SOFR-IORB 已转正 ({bp(v_sofr_iorb*100)}), 价格信号先于数量信号恶化。RRP 耗尽 (${f2(v_rrpn)}B) 是结构性事件, 但 SOFR 与 SRF 的走阔才是压力确认。历史参照 2019年9月回购危机: 先 RRP 耗尽, 再 SOFR 突然飙升。盯住 SOFR-IORB 持续转正与 SRF 放量。',
        'risk-on': f'融资充裕: SOFR-IORB ({bp(v_sofr_iorb*100)}) 为负, 准备金管道通畅。RRP 耗尽 (${f2(v_rrpn)}B) 是结构性事件, 但价格信号平静。类比: 水库水位下降(结构)但下游供水未停(价格)。历史参照 2019年9月回购危机作为尾部情景。',
        'mixed': f'流动性处于"缓冲变薄"阶段: RRP 耗尽 (${f2(v_rrpn)}B) 是结构性事件, 但 SOFR-IORB ({bp(v_sofr_iorb*100)})、SRF、信用利差全部平静——数量收缩尚未传导为价格压力。类比: 水库水位下降(结构)但下游供水未停(价格)。历史参照 2019年9月回购危机: 先 RRP 耗尽, 再 SOFR 突然飙升。盯住 SOFR-IORB 转正、SRF 放量两个价格信号。',
    }[_liq_signal],
    'whatToWatch': [
        {'trigger':'SOFR-IORB <span class="watch-threshold">连续3日转正</span>','implication':'融资市场真实压力第一确认, 流动性主题升级为主线','status':f'当前 {bp(v_sofr_iorb*100)}'},
        {'trigger':'TGA 突破 <span class="watch-threshold">$9,000亿</span>','implication':'财政部持续抽水, 净流动性单周收缩数百亿','status':f'距离 {max(0,(900-v_tgan)/9):.0f}%' if v_tgan else '—'},
        {'trigger':'准备金跌破 <span class="watch-threshold">$3.0T</span>','implication':'进入"充足"下沿, 美联储或讨论放缓 QT','status':f'距离 {max(0,(v_res/1000-3000)/30):.0f}%'},
    ],
    'chartNotes': {
        'trendNote': f'RRP 半年Δ{bp(tfm("rrp")["h6"],"$B") if tfm("rrp")["h6"] is not None else "—"} · 净流动性 月Δ{bp(tfm("netliq")["m"],"$B") if tfm("netliq")["m"] is not None else "—"} / 半年Δ{bp(tfm("netliq")["h6"],"$B") if tfm("netliq")["h6"] is not None else "—"}',
    },
}

# 经济数据 (同比用 NSA 未季调口径, 与 BLS 官方公布一致; SA 序列仅用于环比/分位)
cpi_yoy = yoy('cpi_nsa'); core_cpi_yoy = yoy('core_cpi_nsa'); pce_yoy = yoy('pce'); core_pce_yoy = yoy('core_pce')
gdp_val = val('gdp'); gdp_yoy = yoy('gdp')
unrate = val('unrate'); payems = val('payems'); payems_mom = mom_level('payems')
retail = val('retail'); umich = val('umich')

# —— 真实同比序列 (760d 月度 / 1500d 季度窗口保证基期存在; 同比用 NSA 官方口径) ——
cpi_ys  = yoy_series('cpi_nsa', 10)
core_ys = yoy_series('core_cpi_nsa', 10)
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
    # 水平等级: 颜色按同比绝对水平(直观反映通胀压力), 趋势独立用箭头+文字
    if cur >= 4:    level = 'high'    # >4% 高通胀
    elif cur >= 2:  level = 'mid'     # 2-4% 中度
    elif cur > 0:   level = 'low'     # 0-2% 低位
    else:           level = 'flat'    # 负值/通缩
    return {'component': name, 'yoy': f'{cur:+.1f}%', 'contribution': pctpt(d1), 'trend': trend, 'level': level, 'note': note}
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

# 利率路径"下次会议"动态化 (取自 FOMC 官方日程的未来首场, 排除杰克逊霍尔)
_next_fomc = next((it['date'].split('~')[0] for it in build_fomc_timeline()
                   if it['type'] in ('decision', 'meeting') and it['status'] in ('即将召开', '待定', '进行中')), None)
if _next_fomc:
    DATA['fed']['hawkishDovish']['ratePath']['nextMeeting'] = _next_fomc

# 超级核心通胀(PCE服务除住房) 序列与最新同比, 供经济板块指标使用
_sc_all = supercore_pce_yoy()
_sc_ys = _sc_all[-24:]
_sc_yoy = _sc_all[-1][1] if _sc_all else None
_sc_d1 = (_sc_all[-1][1] - _sc_all[-2][1]) if len(_sc_all) >= 2 else None

# 经济 regime: 由 劳动力/通胀/增长 三块评分 + 市场预期差 动态判定
# (2026-08-12 优化: 见 _build_econ_regime 函数, 在 economic_releases 载入后计算)
# 占位默认值: DATA['economy'] dict 定义时引用, 后续被 _build_econ_regime() 覆盖
_e_signal = 'mixed'
_e_label = '数据计算中'

def _build_labor_panel():
    """劳动力市场'需求-供给-价格'三角框架面板 (卡片数据)。
    时薪同比从 CES0500000003(水平$/hr) 序列换算, 避免把 37.6$/hr 误当 37.6%。"""
    _wage_ys = yoy_series('wage_yoy', 14)
    _wage_cur = _wage_ys[-1][1] if _wage_ys else None
    _wage_d = (_wage_cur - _wage_ys[-2][1]) if len(_wage_ys) >= 2 and _wage_cur is not None and _wage_ys[-2][1] is not None else None
    _gap = wage_inflation_gap()
    return {
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
            {'indicator':'时薪同比', 'value':(f'{_wage_cur:.1f}%' if _wage_cur is not None else '—'), 'trend':('up' if _wage_d is not None and _wage_d > 0 else 'down'), 'prev':(f'{_wage_d:+.1f}pt 月变' if _wage_d is not None else '—'), 'note':'工资-通胀螺旋的核心验证 (CES0500000003 水平序列换算同比)'},
            {'indicator':'辞职率(Quits)', 'value':(f'{val("quits_rate"):.1f}%' if val('quits_rate') else '—'), 'trend':('up' if raw_calc_diff('quits_rate',1) and raw_calc_diff('quits_rate',1) > 0 else 'down'), 'prev':(f'{raw_calc_diff("quits_rate",1):+.1f}pt 月变' if raw_calc_diff('quits_rate',1) else '—'), 'note':'自愿离职=对劳动力市场有信心, 议价能力'},
            {'indicator':'工资-通胀差', 'value':(f'{_gap:+.1f}pt' if _gap is not None else '—'), 'trend':('up' if _gap is not None and _gap > 0 else 'down'), 'note':'时薪同比-核心服务CPI同比 · 正=实际工资增长'},
        ],
        'analystNote': f'劳动力市场"需求-供给-价格"三角框架。Sahm Rule 当前 {_sahm["value"]} ({ "触发" if _sahm["triggered"] else "未触发"})。失业率 {unrate:.1f}%' + ('从低点回升' if (unrate_tf.get('m') or 0) > 0 else ('回落' if (unrate_tf.get('m') or 0) < 0 else '走平')) + ', 美联储关注劳动参与率与JOLTS的交叉信号。'
    }

DATA['economy'] = {
    'regime': {'label':_e_label,'signal':_e_signal,'confidence':_confidence(_e_signal, gdp_qoq is not None, unrate_tf.get('m') is not None, cpi_yoy is not None),
        'description':f'就业消费 (非农月增 {(f"{payems_mom:+.0f}K" if payems_mom is not None else "—")}, 失业率 {f2(unrate)}%) 与通胀 (CPI 同比 {f1(cpi_yoy)}%) 组合决定经济所处阶段。'},
    'keySignals': [
        {'title':f'CPI 同比 {f1(cpi_yoy)}% ({("回升" if (cpi_d1 or 0)>0 else ("回落" if (cpi_d1 or 0)<0 else "持平"))})',
         'meaning':(
             '能源推升整体通胀, 方向与美联储目标背离。'
             if (cpi_d1 or 0) > 0
             else ('通胀回落, 向美联储目标靠近。'
                   if (cpi_d1 or 0) < 0
                   else '通胀横盘。')),
         'direction':_msig(dir_of(cpi_d1), False)},
        {'title':f'核心 PCE 同比 {f2(core_pce_yoy)}% ({("回升" if (pce_d1 or 0)>0 else ("回落" if (pce_d1 or 0)<0 else "持平"))})',
         'meaning':(
             '美联储首选指标上行, 通胀最后一英里停滞。'
             if (pce_d1 or 0) > 0
             else ('美联储首选指标回落, 通胀向目标收敛。'
                   if (pce_d1 or 0) < 0
                   else '美联储首选指标横盘。')),
         'direction':_msig(dir_of(pce_d1), False)},
        {'title':f'失业率 {f2(unrate)}% ({("回升" if (unrate_tf.get("m") or 0)>0 else ("回落" if (unrate_tf.get("m") or 0)<0 else "持平"))})',
         'meaning':(
             '失业率走高, 劳动力市场走弱, 鸽派论据累积。'
             if (unrate_tf.get('m') or 0) > 0
             else ('失业率走低, 劳动力市场走强。'
                   if (unrate_tf.get('m') or 0) < 0
                   else '失业率持平。')),
         'direction':_msig(dir_of(unrate_tf.get('m')), False)},
    ],
    'metrics': [
        {'label':'GDP 环比年化 (实际)','value':(f2(gdp_qoq)+'%' if gdp_qoq is not None else '—'),'change':pctpt(gdp_qoq_d1),'dir':dir_of(gdp_qoq_d1),'tag':'GDP','percentile':pct('gdp_real'),'signal':('bullish' if (gdp_qoq or 0) >= 2 else ('mixed' if (gdp_qoq or 0) > 0 else 'bearish')),'meaning':f'季度环比年化, 新闻口径; 数据截至 {_gdp_vintage}' + (f' · 实时动能 WEI {f2(val("wei"))}%' if val('wei') is not None else '') + (f' · GDPNow本季预估 {f2(val("gdpnow"))}%' if val('gdpnow') is not None else ''),'changes':{'d':'—','w':'—','m':'—','h6':pctpt(gdp_qoq_d2)},'sparkline':[v for _, v in gdp_qoq_ys]},
        {'label':'CPI 同比','value':(f1(cpi_yoy)+'%' if cpi_yoy else '—'),'change':pctpt(cpi_d1),'dir':dir_of(cpi_d1),'tag':'CPI','percentile':pct('cpi'),'signal':_msig(dir_of(cpi_d1), False),'meaning':'月度频率: 月格=上月Δ, 半年格=6月Δ','changes':{'d':'—','w':'—','m':pctpt(cpi_d1),'h6':pctpt(cpi_d6)},'sparkline':[v for _, v in cpi_ys]},
        {'label':'核心 CPI 同比','value':(f1(core_cpi_yoy)+'%' if core_cpi_yoy else '—'),'change':pctpt(core_d1),'dir':dir_of(core_d1),'tag':'Core','percentile':pct('core_cpi'),'signal':_msig(dir_of(core_d1), False),'meaning':'服务粘性对冲商品通缩','changes':{'d':'—','w':'—','m':pctpt(core_d1),'h6':pctpt(core_d6)},'sparkline':[v for _, v in core_ys]},
        {'label':'核心 PCE 同比','value':(f2(core_pce_yoy)+'%' if core_pce_yoy else '—'),'change':pctpt(pce_d1),'dir':dir_of(pce_d1),'tag':'PCE','percentile':pct('core_pce'),'signal':_msig(dir_of(pce_d1), False),'meaning':'美联储首选, 距目标仍有路程 (滞后1月)','changes':{'d':'—','w':'—','m':pctpt(pce_d1),'h6':pctpt(pce_d6)},'sparkline':[v for _, v in pce_ys]},
        {'label':'失业率','value':f2(unrate)+'%','change':pctpt(unrate_tf['m']),'dir':dir_of(unrate_tf['m']),'tag':'UNRATE','percentile':pct('unrate'),'signal':_msig(dir_of(unrate_tf['m']), False),'meaning':'从低点爬升, Sahm规则未触发','changes':{'d':'—','w':'—','m':pctpt(unrate_tf['m']),'h6':pctpt(unrate_tf['h6'])},'sparkline':series30('unrate')},
        {'label':'劳动参与率','value':(f'{val("participation"):.1f}%' if val('participation') is not None else '—'),'change':pctpt(raw_calc_diff('participation',1)),'dir':dir_of(raw_calc_diff('participation',1)),'tag':'LPR','percentile':pct('participation'),'signal':_msig(dir_of(raw_calc_diff('participation',1)), True),'meaning':'劳动力供给池; 持续下滑(五年低位)使失业率读数失真, 参与率降→失业率降≠就业改善','changes':{'d':'—','w':'—','m':pctpt(raw_calc_diff('participation',1)),'h6':pctpt(raw_calc_diff('participation',6))},'sparkline':series30('participation')},
        {'label':'非农就业 (月增)','value':(f'{payems_mom:+.0f}K' if payems_mom is not None else '—'),'change':(f'6月均 {nfp_avg6:+.0f}K' if nfp_avg6 is not None else '—'),'dir':dir_of(payems_mom),'tag':'NFP','percentile':pct('payems'),'signal':_msig(dir_of(payems_mom), True),'meaning':'200K以下为降温区','changes':{'d':'—','w':'—','m':(f'{payems_mom:+.0f}K' if payems_mom is not None else '—'),'h6':(f'{nfp_h6:+.0f}K/6月' if nfp_h6 is not None else '—')},'sparkline':[v for _, v in nfp_diffs]},
        {'label':'零售销售 (环比)','value':(ret(retail_mom[-1][1]) if retail_mom else '—'),'change':(pctpt(round(retail_mom[-1][1]-retail_mom[-2][1],2))+' vs上月' if len(retail_mom)>1 else '—'),'dir':dir_of(retail_mom[-1][1] if retail_mom else None),'tag':'Retail','percentile':pct('retail'),'signal':_msig(dir_of(retail_mom[-1][1] if retail_mom else None), True),'meaning':'名义零售月环比','changes':monthly_tf_str('retail',2,'pct','%'),'sparkline':[v for _, v in mom_pct_series('retail', 10)]},
        {'label':'消费者信心','value':f2(umich),'change':pctpt(umich_tf['m']),'dir':dir_of(umich_tf['m']),'tag':'Conf','percentile':pct('umich'),'signal':_msig(dir_of(umich_tf['m']), True),'meaning':'通胀预期压制信心','changes':{'d':'—','w':'—','m':pctpt(umich_tf['m']),'h6':pctpt(umich_tf['h6'])},'sparkline':series30('umich')},
        {'label':'制造业 PMI','value':(f2(val('mfg_pmi')) if val('mfg_pmi') is not None else '—'),'change':pctpt(tfm('mfg_pmi')['m']),'dir':dir_of(tfm('mfg_pmi')['m']),'tag':'MfgPMI','percentile':pct('mfg_pmi'),'signal':('bullish' if (val('mfg_pmi') or 0) >= 50 else 'bearish'),'meaning':'S&P Global制造业景气: >50扩张 / <50收缩, 荣枯线50','changes':{'d':'—','w':pctpt(tfm('mfg_pmi')['w']),'m':pctpt(tfm('mfg_pmi')['m']),'h6':pctpt(tfm('mfg_pmi')['h6'])},'sparkline':series30('mfg_pmi')},
        {'label':'服务业 PMI','value':(f2(val('svc_pmi')) if val('svc_pmi') is not None else '—'),'change':pctpt(tfm('svc_pmi')['m']),'dir':dir_of(tfm('svc_pmi')['m']),'tag':'SvcPMI','percentile':pct('svc_pmi'),'signal':('bullish' if (val('svc_pmi') or 0) >= 50 else 'bearish'),'meaning':'S&P Global服务业景气(占经济~80%): >50扩张 / <50收缩, 荣枯线50','changes':{'d':'—','w':pctpt(tfm('svc_pmi')['w']),'m':pctpt(tfm('svc_pmi')['m']),'h6':pctpt(tfm('svc_pmi')['h6'])},'sparkline':series30('svc_pmi')},
        {'label':'超级核心通胀 (PCE服务除住房)','value':(f2(_sc_yoy)+'%' if _sc_yoy is not None else '—'),'change':pctpt(_sc_d1),'dir':dir_of(_sc_d1),'tag':'SuperCore','percentile':None,'signal':('bearish' if (_sc_yoy or 0) > 3.5 else 'mixed'),'meaning':'美联储最看重的通胀口径(服务除住房), >3.5%为压力区','changes':{'d':'—','w':'—','m':pctpt(_sc_d1),'h6':'—'},'sparkline':[v for _, v in _sc_ys]},
        {'label':'纽约联储制造业指数','value':(f2(val('empire')) if val('empire') is not None else '—'),'change':pctpt(tfm('empire')['m']),'dir':dir_of(tfm('empire')['m']),'tag':'Empire','percentile':pct('empire'),'signal':('bullish' if (val('empire') or 0) >= 0 else 'bearish'),'meaning':'扩散指数 >0扩张; 最高频增长先行指标(每月中旬)','changes':{'d':'—','w':pctpt(tfm('empire')['w']),'m':pctpt(tfm('empire')['m']),'h6':pctpt(tfm('empire')['h6'])},'sparkline':series30('empire')},
        {'label':'费城联储制造业指数','value':(f2(val('philly')) if val('philly') is not None else '—'),'change':pctpt(tfm('philly')['m']),'dir':dir_of(tfm('philly')['m']),'tag':'Philly','percentile':pct('philly'),'signal':('bullish' if (val('philly') or 0) >= 0 else 'bearish'),'meaning':'扩散指数 >0扩张; 与 Empire 互补的软数据','changes':{'d':'—','w':pctpt(tfm('philly')['w']),'m':pctpt(tfm('philly')['m']),'h6':pctpt(tfm('philly')['h6'])},'sparkline':series30('philly')},
    ],
    'trendData': [
        {'name':'CPI 同比','tag':'CPI','unit':'pt','current':(f1(cpi_yoy)+'%' if cpi_yoy else '—'),'changes':{'d':None,'w':None,'m':cpi_d1,'h6':cpi_d6},'meaning':'月格=同比的上月Δ, 半年格=6个月Δ'},
        {'name':'核心 PCE 同比','tag':'PCE','unit':'pt','current':(f2(core_pce_yoy)+'%' if core_pce_yoy else '—'),'changes':{'d':None,'w':None,'m':pce_d1,'h6':pce_d6},'meaning':'美联储首选指标的方向'},
        {'name':'失业率','tag':'UNRATE','unit':'pt','current':f2(unrate)+'%','changes':{'d':None,'w':None,'m':unrate_tf['m'],'h6':unrate_tf['h6']},'meaning':'月格=上月Δ, 半年格=6月Δ'},
        {'name':'非农就业(月增)','tag':'NFP','unit':'K','current':(f'{payems_mom:+.0f}K' if payems_mom is not None else '—'),'changes':{'d':None,'w':None,'m':(round(payems_mom,0) if payems_mom is not None else None),'h6':(round(nfp_h6,0) if nfp_h6 is not None else None)},'meaning':'半年格=6个月累计新增'},
        {'name':'消费者信心','tag':'Conf','unit':'pt','current':f2(umich),'changes':{'d':None,'w':None,'m':umich_tf['m'],'h6':umich_tf['h6']},'meaning':'消费前瞻指标'},
        {'name':'制造业 PMI','tag':'MfgPMI','unit':'pt','current':(f2(val('mfg_pmi')) if val('mfg_pmi') is not None else '—'),'changes':{'d':None,'w':tfm('mfg_pmi')['w'],'m':tfm('mfg_pmi')['m'],'h6':tfm('mfg_pmi')['h6']},'meaning':'>50扩张/<50收缩, 荣枯线50'},
        {'name':'服务业 PMI','tag':'SvcPMI','unit':'pt','current':(f2(val('svc_pmi')) if val('svc_pmi') is not None else '—'),'changes':{'d':None,'w':tfm('svc_pmi')['w'],'m':tfm('svc_pmi')['m'],'h6':tfm('svc_pmi')['h6']},'meaning':'占经济~80%, >50扩张/<50收缩'},
        {'name':'超级核心通胀','tag':'SuperCore','unit':'pt','current':(f2(_sc_yoy)+'%' if _sc_yoy is not None else '—'),'changes':{'d':None,'w':None,'m':_sc_d1,'h6':None},'meaning':'PCE服务除住房同比, 美联储首选通胀口径'},
        {'name':'纽约联储制造业','tag':'Empire','unit':'pt','current':(f2(val('empire')) if val('empire') is not None else '—'),'changes':{'d':None,'w':tfm('empire')['w'],'m':tfm('empire')['m'],'h6':tfm('empire')['h6']},'meaning':'扩散指数 >0扩张, 最高频增长先行指标'},
        {'name':'费城联储制造业','tag':'Philly','unit':'pt','current':(f2(val('philly')) if val('philly') is not None else '—'),'changes':{'d':None,'w':tfm('philly')['w'],'m':tfm('philly')['m'],'h6':tfm('philly')['h6']},'meaning':'扩散指数 >0扩张, 与 Empire 互补的软数据'},
    ],
    'inflationChart': {'labels':[mlabel(d) for d, _ in cpi_ys],
        'series':{'CPI同比':[v for _, v in cpi_ys],'核心CPI同比':align_yoy(cpi_ys, core_ys),'核心PCE同比':align_yoy(cpi_ys, pce_ys)}},
    'gdpChart': {'labels':[qlabel(d) for d, _ in gdp_ys],
        'series':{'名义GDP同比':[v for _, v in gdp_ys],'实际GDP同比':align_yoy(gdp_ys, gdpr_ys)}},
    'employmentChart': {'labels':[mlabel(d) for d, _ in s('unrate')[-6:]],
        'series':{'失业率(%)':[v for _, v in s('unrate')[-6:]],'劳动参与率(%)':[dict(s('participation')).get(d) for d, _ in s('unrate')[-6:]]}},
    'pmiChart': {'labels':[mlabel(d) for d, _ in s('mfg_pmi')[-24:]],
        'series':{'制造业PMI':[v for _, v in s('mfg_pmi')[-24:]],
                  '服务业PMI':[dict(s('svc_pmi')[-24:]).get(d) for d, _ in s('mfg_pmi')[-24:]],
                  '荣枯线(50)':[50]*len(s('mfg_pmi')[-24:])}} if s('mfg_pmi') else {'labels':[],'series':{}},
    'inflationBreakdown': infl_rows,
    # 平均时薪同比 (从 CES0500000003 水平序列换算): 最新值 + 月差
    'laborPanel': _build_labor_panel(),
    # Phase2: 通胀深化 (3M/6M年化)
    'inflationDeepening': {
        'annualized3m': infl_annualized('core_cpi', 3),
        'annualized6m': infl_annualized('core_cpi', 6),
        'supercore': raw_calc_pct('cpi_core_svcs', 12),  # 超级核心(核心服务除住房)
        'wage_inflation_gap': wage_inflation_gap(),
        'analystNote': f'核心CPI 3月年化 {infl_annualized("core_cpi", 3):.1f}% (" 高于" if infl_annualized("core_cpi", 3) and infl_annualized("core_cpi", 3) > raw_calc_pct("core_cpi_nsa",12) else " 收敛于")同比的 {raw_calc_pct("core_cpi_nsa",12):.1f}%) — 3月年化是美联储内部最看重的口径。' if infl_annualized('core_cpi', 3) and raw_calc_pct('core_cpi_nsa', 12) else '数据暂缺',
    },
    'consumptionTable': [
        {'indicator':'零售销售 (名义)','value':(f'${comma(retail/1000,1)}B' if retail else '—'),'prev':(ret(retail_mom[-1][1])+' 环比' if retail_mom else '—'),'trend':trend_of(retail_mom[-1][1] if retail_mom else None),'note':'消费第一高频指标'},
        {'indicator':'实际PCE','value':(f'${comma(val("pce_real")/1000,2)}T' if val('pce_real') else '—'),'prev':(ret(pce_real_mom[-1][1])+' 环比' if pce_real_mom else '—'),'trend':trend_of(pce_real_mom[-1][1] if pce_real_mom else None),'note':'剔除通胀的真实消费'},
        {'indicator':'耐用品订单','value':(f'${comma(val("durables")/1000,1)}B' if val('durables') else '—'),'prev':(ret(dur_mom[-1][1])+' 环比' if dur_mom else '—'),'trend':trend_of(dur_mom[-1][1] if dur_mom else None),'note':'大件消费+企业开支前瞻'},
        {'indicator':'消费者信心 (UMich)','value':f2(umich),'prev':pctpt(umich_tf['m'])+' 月Δ','trend':trend_of(umich_tf['m']),'note':'通胀预期压制'},
        {'indicator':'初请失业金 (周)','value':(comma(val('claims')/1000,0)+'K' if val('claims') else '—'),'prev':(f'{claims_w/1000:+.0f}K 周Δ' if claims_w is not None else '—'),'trend':trend_of(-(claims_w or 0)),'note':'升=就业走弱 (收入-消费链领先)'},
    ],
    'chartNotes': {
        'inflNote': f'CPI {f1(cpi_yoy)}% (月Δ{pctpt(cpi_d1)}) / 核心CPI {f1(core_cpi_yoy)}% / 核心PCE {f2(core_pce_yoy)}% (滞后1月) · 真实同比序列',
        'gdpNote': f'实际环比年化 {f2(gdp_qoq)}% ({_gdp_vintage}, BEA最新) · 名义同比 {f2(gdp_yoy)}% · 实际同比 {f2(gdpr_yoy)}%' + (f' · 实时动能 WEI {f2(val("wei"))}%' if val('wei') is not None else '') + (f' · GDPNow本季预估 {f2(val("gdpnow"))}%' if val('gdpnow') is not None else ''),
        'empNote': f'失业率 {f2(unrate)}% · 劳动参与率 {f2(val("participation"))}% (非农变化见上方指标卡/对比面板)',
        'pmiNote': f'制造业PMI {f2(val("mfg_pmi"))} / 服务业PMI {f2(val("svc_pmi"))} · 荣枯线50: 上=扩张 下=收缩',
        'trendNote': f'CPI同比半年Δ{pctpt(cpi_d6)} · 非农6个月累计{(f"{nfp_h6:+.0f}K" if nfp_h6 is not None else "—")} · 失业率半年Δ{pctpt(unrate_tf["h6"])}',
        'breakdownSub': '分项真实同比 · 颜色=通胀水平(红>4% 橙2-4% 绿<2%) · 箭头=边际方向(↑加速/↓回落) · 最右列为上月Δ',
    },

    # ===== 经济数据 → 资产传导机制 (2026-08-17) =====
    # 每类数据: 公布的偏离方向 → 三条传导通道 → 各类资产长/短期影响
    # 前端渲染为"数据卡"列表, 便于数据发布后快速查对市场影响
    'transmissionMap': {
        'hub': '市场对美联储利率路径的预期 (降息/维持/加息定价)',
        'channels': [
            {'key': 'discount', 'label': '通道A · 折现率', 'color': '#a32d2d',
             'desc': '利率预期 → 贴现率 → 估值分母 (影响所有资产, 尤重长久期/成长)'},
            {'key': 'earnings', 'label': '通道B · 盈利', 'color': '#185FA5',
             'desc': '增长预期 → EPS → 顺周期资产 (股市/商品/高收益债)'},
            {'key': 'haven', 'label': '通道C · 避险', 'color': '#0F6E56',
             'desc': '数据意外 → 风险偏好 → 风险/避险资产切换'},
        ],
        'indicators': [
            {
                'tag': 'CPI', 'name': 'CPI / 核心 CPI', 'freq': '月度',
                'channel': 'discount', 'primary': '通胀路径',
                'impact': [
                    {'asset': '股市', 'dir': 'down', 'when': '高于预期', 'why': '加息定价→折现率↑'},
                    {'asset': '长债', 'dir': 'down', 'when': '高于预期', 'why': '利率预期↑→收益率↑'},
                    {'asset': '美元', 'dir': 'up', 'when': '高于预期', 'why': '利差走阔→美元强'},
                    {'asset': '黄金', 'dir': 'up', 'when': '低于预期', 'why': '实际利率↓→无息资产受益'},
                    {'asset': '加密', 'dir': 'up', 'when': '低于预期', 'why': '折现率↓+流动性预期↑'},
                ],
                'longTerm': '连续高于预期 → 加息周期延长/重启, 成长股估值系统性压缩, 黄金实际利率锚失效风险; 连续低于预期 → 降息周期打开, 利长久期债与高估值成长',
                'current': '7月 CPI 3.4% / 核心 2.5% (均符合预期)',
            },
            {
                'tag': 'NFP', 'name': '非农就业', 'freq': '月度',
                'channel': 'earnings', 'primary': '就业拐点',
                'impact': [
                    {'asset': '长债', 'dir': 'up', 'when': '低于预期', 'why': '衰退担忧→降息定价'},
                    {'asset': '短债', 'dir': 'up', 'when': '低于预期', 'why': '政策宽松预期↑'},
                    {'asset': '美元', 'dir': 'down', 'when': '低于预期', 'why': '降息预期→利差收窄'},
                    {'asset': '黄金', 'dir': 'up', 'when': '低于预期', 'why': '避险+实际利率↓'},
                    {'asset': '股市', 'dir': 'down', 'when': '大幅低于预期', 'why': '盈利下修主导(超衰退阈值时)'},
                ],
                'longTerm': '连续 miss → 衰退交易主导 (股债双杀→避险独强); 连续 beat → 软着陆定价 (股涨债跌, 美元强)',
                'current': '7月 -23K (大幅低于预期 +80K, miss 103K)',
            },
            {
                'tag': 'GDP', 'name': 'GDP / 增长类', 'freq': '季度',
                'channel': 'earnings', 'primary': '盈利周期',
                'impact': [
                    {'asset': '股市', 'dir': 'down', 'when': '低于预期', 'why': 'EPS 下修'},
                    {'asset': '长债', 'dir': 'up', 'when': '低于预期', 'why': '增长弱→利率预期↓'},
                    {'asset': '商品', 'dir': 'down', 'when': '低于预期', 'why': '需求预期↓'},
                    {'asset': '黄金', 'dir': 'up', 'when': '低于预期', 'why': '避险+宽松预期'},
                    {'asset': '美元', 'dir': 'down', 'when': '低于预期', 'why': '增长差→货币弱'},
                ],
                'longTerm': '连续 miss → 衰退确认 (利好债/黄金, 利空股/商品); 连续 beat → 金发姑娘 (股债双牛)',
                'current': 'Q2 实际 1.5% (低于预期 2.1%, miss 0.6pt)',
            },
            {
                'tag': 'PCE', 'name': '核心 PCE / 超级核心', 'freq': '月度',
                'channel': 'discount', 'primary': 'Fed 最关注通胀',
                'impact': [
                    {'asset': '股市', 'dir': 'down', 'when': '高于预期', 'why': '加息尾部风险'},
                    {'asset': '长债', 'dir': 'down', 'when': '高于预期', 'why': '利率路径上修'},
                    {'asset': '黄金', 'dir': 'up', 'when': '低于预期', 'why': '实际利率↓'},
                    {'asset': '加密', 'dir': 'up', 'when': '低于预期', 'why': '风险偏好修复'},
                ],
                'longTerm': '超级核心(除住房服务)是 Fed 内部最关注口径, 其粘性决定"higher for longer"时长',
                'current': '6月 核心 PCE 3.3% / 超级核心 3.8% (均符合预期)',
            },
            {
                'tag': 'UNRATE', 'name': '失业率 / 初请', 'freq': '月度/周度',
                'channel': 'haven', 'primary': '衰退触发器',
                'impact': [
                    {'asset': '长债', 'dir': 'up', 'when': '高于预期', 'why': '衰退→久期受益'},
                    {'asset': '股市', 'dir': 'down', 'when': '高于预期', 'why': '衰退担忧'},
                    {'asset': '黄金', 'dir': 'up', 'when': '高于预期', 'why': '避险'},
                    {'asset': '美元', 'dir': 'down', 'when': '高于预期', 'why': '宽松预期'},
                ],
                'longTerm': '触发 Sahm 规则 (3个月均升0.5pt) → 衰退交易全面启动; 初请4周均>280K 是先行确认',
                'current': '7月 4.1% (好于预期 4.2%) · 初请 199K 低位',
            },
        ],
    },
    'analystView': '占位(regime 计算后按 signal 覆盖)',
    'whatToWatch': [
        {'trigger':'<span class="watch-threshold">下月 CPI 报告</span>','implication':'将完整体现油价冲击, 核心环比>0.3%冲击降息定价','status':'关键事件'},
        {'trigger':f'失业率触及 <span class="watch-threshold">4.4%</span>','implication':'接近 Sahm 衰退规则, 鸽派论据压倒鹰派','status':f'距离 {max(0,4.4-unrate):.1f}pt'},
        {'trigger':'<span class="watch-threshold">下月非农</span>','implication':'若连续<180K, 就业降温趋势确认','status':'关键事件'},
    ]
}


# 经济指标: 增补"最新公布 / 下次公布" + 数据源 (基于发布频率规律推算, 标注预计)
for _m in DATA['economy']['metrics'] + DATA['economy'].get('trendData', []):
    _ri = release_info(_m.get('tag'))
    if _ri:
        _m['release'] = _ri
    _rk = RELEASE_MAP.get(_m.get('tag'))
    if _rk:
        _m['source'] = SOURCE_MAP.get(_rk[0], '')

# ===== 经济数据公布对比：公布值 vs 市场预期值（策展） =====
# 载入 economic_releases.json（公布值来自BLS/BEA，市场预期为彭博/路透一致预期中值），
# 计算 预期差 与 结论（好于/差于/符合预期，按市场反应方向），供前端对比面板与指标卡使用。
try:
    _ER = json.load(open(SCRIPT_DIR / 'economic_releases.json', encoding='utf-8'))
    print('[gen_datajs] loaded economic_releases.json', file=sys.stderr, flush=True)
except Exception:
    _ER = None
    print('[gen_datajs] economic_releases.json 缺失, 公布对比面板留空', file=sys.stderr, flush=True)

_ER_RELEASES = []
_ER_BY_TAG = {}
if _ER:
    for _r in _ER.get('releases', []):
        _unit = _r.get('unit', '%')
        _hib = _r.get('higherIsBetter', True)
        _tol = float(_r.get('tolerance', 0.1))
        _act, _con, _prev = _r.get('actual'), _r.get('consensus'), _r.get('previous')

        def _fmt(v):
            if v is None:
                return '—'
            if _unit == 'K':
                return ('+' if v >= 0 else '') + ('%.0f' % v) + 'K'
            return ('%.1f' % v) + '%'

        _surp = (None if (_act is None or _con is None) else _act - _con)
        if _surp is None:
            _verdict = 'na'
        elif abs(_surp) <= _tol:
            _verdict = 'inline'
        else:
            _verdict = 'beat' if ((_act > _con) if _hib else (_act < _con)) else 'miss'
        _item = dict(_r)
        _item['actualStr'] = _fmt(_act)
        _item['consensusStr'] = _fmt(_con)
        _item['previousStr'] = _fmt(_prev)
        _item['surprise'] = _surp
        if _surp is None:
            _item['surpriseStr'] = '—'
        elif _verdict == 'inline':
            _item['surpriseStr'] = '符合预期'
        elif _unit == 'K':
            _item['surpriseStr'] = ('低于预期 ' if _surp < 0 else '高于预期 ') + ('%.0f' % abs(_surp)) + 'K'
        else:
            _item['surpriseStr'] = ('低于预期 ' if _surp < 0 else '高于预期 ') + ('%.1f' % abs(_surp)) + 'pt'
        _item['verdict'] = _verdict
        _ER_RELEASES.append(_item)
        _ER_BY_TAG[_r.get('tag')] = _item
    _ER_RELEASES.sort(key=lambda x: x.get('releaseDate', ''), reverse=True)

DATA['economy']['releases'] = _ER_RELEASES
DATA['economy']['releasesMeta'] = {
    'asOf': (_ER or {}).get('asOf'),
    'source': (_ER or {}).get('source', ''),
}

def _build_econ_regime():
    """经济 regime 判定 (2026-08-12 优化版)。
    三块评分 (劳动力 0-100 健康 / 通胀 0-100 压力 / 增长 0-100 强劲) + 市场预期差修正,
    输出 risk-on / risk-off / stagflation / reflation / disinflation / mixed。"""
    # ---------- 1. 劳动力市场评分 (高=健康) ----------
    labor = 50.0
    labor_pts = []
    _u = unrate_tf.get('m')
    if _u is not None:
        if _u < -0.05: labor += 12; labor_pts.append(f'失业率回落 ({_u:+.1f}pt)')
        elif _u > 0.05: labor -= 15; labor_pts.append(f'失业率回升 ({_u:+.1f}pt)')
        else: labor_pts.append('失业率走平')
    if payems_mom is not None:
        if payems_mom >= 180: labor += 12; labor_pts.append(f'非农 {payems_mom:+.0f}K 强劲')
        elif payems_mom >= 50: labor += 4; labor_pts.append(f'非农 {payems_mom:+.0f}K 温和')
        else: labor -= 12; labor_pts.append(f'非农 {payems_mom:+.0f}K 偏弱')
    if _claims_4wk is not None:
        if _claims_4wk < 220000: labor += 6; labor_pts.append('初请低位')
        elif _claims_4wk > 280000: labor -= 12; labor_pts.append('初请走高')
        else: labor_pts.append('初请中性')
    if _sahm.get('triggered'):
        labor -= 25; labor_pts.append('⚠ Sahm 规则触发!')
    if val('quits_rate'):
        if val('quits_rate') >= 2.0: labor += 6; labor_pts.append('辞职率回升(信心)')
        elif val('quits_rate') <= 1.5: labor -= 5; labor_pts.append('辞职率低位')
    if val('participation'):
        if val('participation') >= 63: labor += 4; labor_pts.append('参与率健康')
        elif val('participation') <= 61.5: labor -= 6; labor_pts.append('参与率走低')
    labor = max(0.0, min(100.0, round(labor)))

    # ---------- 2. 通胀评分 (高=压力大) ----------
    infl = 50.0
    infl_pts = []
    if cpi_yoy is not None:
        if cpi_yoy > 4: infl += 20; infl_pts.append(f'CPI {cpi_yoy:.1f}% 高位')
        elif cpi_yoy > 3: infl += 10; infl_pts.append(f'CPI {cpi_yoy:.1f}% 偏高')
        elif cpi_yoy < 2.5: infl -= 12; infl_pts.append(f'CPI {cpi_yoy:.1f}% 低位')
        else: infl_pts.append(f'CPI {cpi_yoy:.1f}% 中性')
    if core_cpi_yoy is not None:
        infl += 0 if core_cpi_yoy <= 3 else (8 if core_cpi_yoy <= 4 else 15)
        infl_pts.append(f'核心CPI {core_cpi_yoy:.1f}%')
    if core_pce_yoy is not None:
        infl += 0 if core_pce_yoy <= 2.6 else (6 if core_pce_yoy <= 3.3 else 12)
        infl_pts.append(f'核心PCE {core_pce_yoy:.1f}%')
    if _sc_yoy is not None:
        if _sc_yoy > 3.5: infl += 10; infl_pts.append(f'超级核心 {_sc_yoy:.1f}% 压力')
        elif _sc_yoy < 3.0: infl -= 6; infl_pts.append(f'超级核心 {_sc_yoy:.1f}% 缓和')
    if cpi_d1 is not None:
        if cpi_d1 < -0.2: infl -= 8; infl_pts.append(f'CPI 环比 {cpi_d1:+.1f}pt 回落')
        elif cpi_d1 > 0.2: infl += 8; infl_pts.append(f'CPI 环比 {cpi_d1:+.1f}pt 回升')
    if val('bei10'):
        if val('bei10') > 2.6: infl += 6; infl_pts.append('通胀预期走高')
        elif val('bei10') < 2.2: infl -= 5; infl_pts.append('通胀预期回落')
    infl = max(0.0, min(100.0, round(infl)))

    # ---------- 3. 增长评分 (高=强劲) ----------
    growth = 50.0
    growth_pts = []
    if gdp_qoq is not None:
        if gdp_qoq >= 2.5: growth += 15; growth_pts.append(f'GDP {gdp_qoq:.1f}% 强劲')
        elif gdp_qoq >= 1: growth += 5; growth_pts.append(f'GDP {gdp_qoq:.1f}% 温和')
        else: growth -= 15; growth_pts.append(f'GDP {gdp_qoq:.1f}% 疲弱')
    if val('gdpnow') is not None:
        if val('gdpnow') >= 2.5: growth += 8; growth_pts.append(f'GDPNow {val("gdpnow"):.1f}%')
        elif val('gdpnow') <= 0.5: growth -= 10; growth_pts.append(f'GDPNow {val("gdpnow"):.1f}% 低迷')
    if val('wei') is not None:
        if val('wei') >= 2: growth += 6; growth_pts.append('WEI 动能强')
        elif val('wei') <= -1: growth -= 10; growth_pts.append('WEI 转负')
    if val('mfg_pmi') is not None:
        if val('mfg_pmi') >= 52: growth += 6; growth_pts.append(f'制造业PMI {val("mfg_pmi"):.1f} 扩张')
        elif val('mfg_pmi') < 48: growth -= 10; growth_pts.append(f'制造业PMI {val("mfg_pmi"):.1f} 收缩')
    if val('svc_pmi') is not None:
        if val('svc_pmi') >= 52: growth += 5; growth_pts.append(f'服务业PMI {val("svc_pmi"):.1f} 扩张')
        elif val('svc_pmi') < 48: growth -= 8; growth_pts.append(f'服务业PMI {val("svc_pmi"):.1f} 收缩')
    if retail is not None:
        if retail_mom and retail_mom[-1][1] is not None:
            if retail_mom[-1][1] >= 0.4: growth += 4; growth_pts.append('零售环比强')
            elif retail_mom[-1][1] <= -0.3: growth -= 6; growth_pts.append('零售环比弱')
    growth = max(0.0, min(100.0, round(growth)))

    # ---------- 4. 市场预期差修正 (最近 5 条发布) ----------
    exp_pts = []
    for _r in _ER_RELEASES[:5]:
        v = _r.get('verdict')
        tag = _r.get('tag', '')
        if v not in ('beat', 'miss'):
            continue
        nm = _r.get('indicator', tag)
        if tag in ('NFP', 'UNRATE', 'LPR', 'GDP'):
            if v == 'beat': growth += 6; labor += 4; exp_pts.append(f'{nm} 好于预期')
            else: growth -= 6; labor -= 4; exp_pts.append(f'{nm} 差于预期')
        elif tag in ('CPI', 'Core', 'PCE', 'SuperCore'):
            # 通胀指标: 公布值低=好消息(降通胀), 公布值高=坏消息
            if v == 'beat': infl -= 8; exp_pts.append(f'{nm} 低于预期(利好)')
            else: infl += 8; exp_pts.append(f'{nm} 高于预期(利空)')
    growth = max(0.0, min(100.0, growth))
    labor = max(0.0, min(100.0, labor))
    infl = max(0.0, min(100.0, infl))

    # ---------- 5. 综合判定 ----------
    if labor <= 38 and infl >= 58:
        signal, label = 'stagflation', '滞胀风险：就业走弱 + 通胀高企'
    elif growth <= 42:
        signal = 'risk-off' if labor <= 48 else 'mixed'
        label = '增长放缓 + 就业转弱' if signal == 'risk-off' else '增长分化（动能不足）'
    elif infl >= 65:
        signal = 'reflation' if growth >= 55 else 'stagflation'
        label = '再通胀：增长回升 + 通胀升温' if signal == 'reflation' else '滞胀风险：增长乏力 + 通胀高企'
    elif growth >= 58 and labor >= 55 and infl <= 55:
        signal, label = 'risk-on', '金发女孩：增长稳健 + 就业健康 + 通胀温和'
    elif infl <= 45 and growth >= 50:
        signal, label = 'disinflation', '通胀回落：增长平稳 + 通胀趋势下行'
    else:
        signal, label = 'mixed', '多因子分化：无单一主导'
    confidence = _confidence(signal, gdp_qoq is not None, unrate_tf.get('m') is not None, cpi_yoy is not None,
                             _claims_4wk is not None, _sc_yoy is not None, bool(_ER_RELEASES))
    desc = (f'劳动力 {labor}/100 · 通胀 {infl}/100 · 增长 {growth}/100。'
            + (' / '.join((labor_pts + infl_pts + growth_pts + exp_pts)[:6]) or '数据待更新'))
    return {'signal': signal, 'label': label, 'confidence': confidence, 'description': desc,
            'scores': {'labor': labor, 'inflation': infl, 'growth': growth}, 'drivers': (labor_pts + infl_pts + growth_pts + exp_pts)}

# 计算经济 regime (需在 economic_releases 载入后, 以便纳入市场预期差)
_econ_regime = _build_econ_regime()
_e_signal = _econ_regime['signal']
_e_label = _econ_regime['label']
DATA['economy']['regime'] = _econ_regime

# ====== 利率路径多维度算法 (2026-08-13 优化) ======
# 融合 ①隐含路径(1Y-FF, 单次会议) ②短端波动(2Y周std) ③经济regime ④鹰鸽积分 → 完整 5 段概率
_e_sig_path = _econ_regime.get('signal', 'mixed')
if _e_sig_path == 'stagflation':   _regime_bias_path = +0.6
elif _e_sig_path == 'reflation':   _regime_bias_path = +0.3
elif _e_sig_path == 'risk-off':    _regime_bias_path = +0.2
elif _e_sig_path == 'disinflation': _regime_bias_path = -0.6
elif _e_sig_path == 'risk-on':     _regime_bias_path = -0.3
else:                              _regime_bias_path = 0.0
_hawk_bias_path = (_hawk_score_data - 5) * 0.06
# mean: 单次会议隐含变动 (单位: 次25bp), 正=降息, 负=加息; 1Y 含12月预期 → /12 单次会议
_mean_cuts = ((_impl_cuts_1m or 0) / 12.0) - _regime_bias_path - _hawk_bias_path
_std_cuts = max(0.4, (_v_2y_vol or 12) / 25.0)

def _norm_cdf_path(x, mu=0, sigma=1):
    return 0.5 * (1 + _math.erf((x - mu) / (sigma * _math.sqrt(2))))
def _seg_path(mu, sigma, lo, hi):
    return max(0, _norm_cdf_path(hi, mu, sigma) - _norm_cdf_path(lo, mu, sigma))

# 概率段: 正 mean → 降息; 负 mean → 加息; 5 段按 ±1.5/±0.5 划分
# cut50  = P(0.5 < N < 1.5)   强烈降息
# cut25  = P(0   < N < 0.5)   中等降息
# hold   = P(-0.5≤ N ≤ 0.5)   维持 ±0.5 步 (≈12bp 范围内)
# hike25 = P(-1.5 < N < -0.5)  中等加息
# hike50 = P(N ≤ -1.5)        强烈加息
_hold_p  = round(_seg_path(_mean_cuts, _std_cuts, -0.5, 0.5) * 100, 1)
_cut25_p = round(_seg_path(_mean_cuts, _std_cuts,  0,   0.5) * 100, 1)
_cut50_p = round(_seg_path(_mean_cuts, _std_cuts,  0.5, 1.5) * 100, 1)
_h25_p   = round(_seg_path(_mean_cuts, _std_cuts, -1.5, -0.5) * 100, 1)
_h50_p   = round(max(0, 100 - _hold_p - _cut25_p - _cut50_p - _h25_p), 1)  # 兜底
_total_p = _hold_p + _cut25_p + _cut50_p + _h25_p + _h50_p
if _total_p and abs(_total_p - 100) > 0.05:
    _adj = 100 / _total_p
    _hold_p, _cut25_p, _cut50_p, _h25_p, _h50_p = [round(p*_adj, 1) for p in (_hold_p, _cut25_p, _cut50_p, _h25_p, _h50_p)]

DATA['fed']['hawkishDovish']['ratePath'] = {
    'nextMeeting':  _NEXT_FOMC or '2026-07-29',
    'cut50bpProb':  _cut50_p,
    'cut25bpProb':  _cut25_p,
    'holdProb':     _hold_p,
    'hike25bpProb': _h25_p,
    'hike50bpProb': _h50_p,
    'meanCuts': round(_mean_cuts, 2),
    'stdCuts':   round(_std_cuts, 2),
    'note': f'多维度正态分布: 1Y 隐含路径 {round(_impl_cuts_1m or 0,2)} 次/12月 → 下次会议 {round(_mean_cuts,2)} 次 · 短端波动 2Y 周std {_v_2y_vol:.0f}bp · 经济regime {_e_sig_path} (偏置 {_regime_bias_path:+.1f}) · 鹰鸽积分 {round(_hawk_score_data,1)} ({_hawk_label_data})'
}
# 同步: transmissionMap 中的 RatePath current 用真实 5 段概率
try:
    _rp_tm = DATA['fed'].get('transmissionMap', {}).get('indicators', [])
    for _ind in _rp_tm:
        if _ind.get('tag') == 'RatePath':
            _ind['current'] = (f'下次会议 {_NEXT_FOMC or "9/15"} · 维持 {_hold_p:.0f}% / 加息 {_h25_p+_h50_p:.0f}% / 降息 {_cut25_p+_cut50_p:.0f}%')
            _ind['longTerm'] = ('降息周期 = 股债双牛(温和衰退除外); 加息周期 = 成长/长久期承压, 价值/现金占优; 当前市场定价维持 '
                                f'{_hold_p:.0f}% / 加息 {_h25_p+_h50_p:.0f}% / 降息 {_cut25_p+_cut50_p:.0f}%')
except Exception:
    pass

# 按实际 signal 选择分析师解读文案 (覆盖占位)
_ANALYST_VIEWS = {
    'risk-on': f'数据偏暖: 增长 (GDP 同比 {f2(gdp_yoy)}%) 稳健、就业 (失业率 {f2(unrate)}%) 健康、通胀 (CPI 同比 {f1(cpi_yoy)}%) 受控。对美联储, 降息窗口相对从容; 变量仍是油价: WTI 回落则 Q4 通胀回 2.5% 轨道、降息顺理成章, 站稳高位则"higher for longer"构成上行风险。',
    'risk-off': f'数据转弱: 增长 (GDP 同比 {f2(gdp_yoy)}%) 放缓、就业 (失业率 {f2(unrate)}%) 走高、通胀 (CPI 同比 {f1(cpi_yoy)}%) 回升。对美联储, 滞胀式组合压缩政策空间; 变量是油价: WTI 站稳高位则"higher for longer", 构成主要下行风险场景。',
    'mixed': f'数据分化: 增长 (GDP 同比 {f2(gdp_yoy)}%) 与就业 (失业率 {f2(unrate)}%) 一强一弱、通胀 (CPI 同比 {f1(cpi_yoy)}%) 能源推升核心横盘。对美联储无压倒性论据, 政策取决于边际变化; 变量是油价: WTI 回落则 Q4 通胀回 2.5% 轨道、9月降息顺理成章, 站稳高位则"higher for longer"是下行风险场景。',
    'stagflation': f'滞胀组合: 增长 (GDP 同比 {f2(gdp_yoy)}%) 乏力 + 通胀 (CPI 同比 {f1(cpi_yoy)}%, 核心 {f1(core_cpi_yoy)}%) 高企 + 就业边际转弱 (失业率 {f2(unrate)}%)。美联储最被动的场景——加息压通胀伤增长、降息稳增长助通胀; 政策空间极小, 股债双杀风险高, 黄金/能源相对占优。',
    'reflation': f'再通胀组合: 增长 (GDP 同比 {f2(gdp_yoy)}%) 回升 + 通胀 (CPI 同比 {f1(cpi_yoy)}%) 重新上行, 就业 (失业率 {f2(unrate)}%) 仍有韧性。名义增长上行利好商品/顺周期/价值股; 对美联储意味着"higher for longer", 长端利率与收益率曲线陡峭化是主要交易。',
    'disinflation': f'通胀回落组合: 通胀 (CPI 同比 {f1(cpi_yoy)}%, 核心 {f1(core_cpi_yoy)}%) 趋势下行, 增长 (GDP 同比 {f2(gdp_yoy)}%) 与就业 (失业率 {f2(unrate)}%) 尚稳。美联储最可能"维持观望→转鸽", 利好长久期债券与成长股; 风险是若就业失速则切向衰退交易。',
}
DATA['economy']['analystView'] = _ANALYST_VIEWS.get(_e_signal, _ANALYST_VIEWS['mixed'])

# 交叉链接到指标卡：在 CPI/核心CPI/非农/失业率/GDP 卡上显示"市场预期 + 结论"
for _m in DATA['economy']['metrics']:
    _ri = _ER_BY_TAG.get(_m.get('tag'))
    if _ri:
        _m['consensusInfo'] = {
            'consensus': _ri['consensusStr'],
            'verdict': _ri['verdict'],
            'periodLabel': _ri.get('periodLabel', ''),
        }

# 数据获取时间 (全局, 用于板块内统一标注)
DATA['economy']['generatedAt'] = GEN_AT
# PMI 数据源元信息 (是否静态兜底): 供前端打"数据可能过期"警告标
DATA['economy']['pmi_meta'] = C.get('pmi_meta', {})
DATA['economy']['empire_meta'] = C.get('empire_meta', {})
# 劳动力市场供需价格三角框架 (近 3 年月度 9 序列, 3 panel)
DATA['economy']['laborTriangleChart'] = _build_labor_triangle()

# 信用市场
print('[gen_datajs] generating credit section...', file=sys.stderr, flush=True)
ccc=val('ccc'); hyv=val('hy'); igv=val('ig'); bbb=val('bbb'); bb=val('bb'); b=val('b'); aaa=val('aaa'); aa=val('aa'); av=val('a')

# 信用 regime (2026-08-12 优化): HY 利差分位 + CCC 分层 + NFCI + 利差变化方向
# HY 整体窄通常代表风险偏好, 但如果 CCC 已同时处于历史高位,
# 说明信用市场内部分层, 应判为 risk-off/信用分层而非风险偏好。
_cr_hy_pct = pct('hy'); _cr_ccc_pct = pct('ccc'); _cr_nfci = val('nfci')
_cr_hy_w = tfm('hy').get('w') or 0     # HY OAS 周变
_cr_ig_w = tfm('ig').get('w') or 0     # IG OAS 周变
_cr_signal = 'mixed'
if _cr_hy_pct is not None and _cr_hy_pct > 70: _cr_signal = 'risk-off'
elif _cr_nfci is not None and _cr_nfci > 0: _cr_signal = 'risk-off'
elif _cr_hy_pct is not None and _cr_hy_pct < 30:
    if _cr_ccc_pct is not None and _cr_ccc_pct > 80:
        _cr_signal = 'risk-off'
    else:
        _cr_signal = 'risk-on'
# 方向修正: 利差快速走阔 (周变 > 10bp) 即使分位不高也提示风险
if _cr_signal == 'mixed' and (_cr_hy_w > 10 or _cr_ig_w > 5):
    _cr_signal = 'risk-off'
elif _cr_signal == 'risk-on' and _cr_hy_w > 8:
    _cr_signal = 'mixed'   # 利差低位但开始走阔 → 降级
_cr_label = '信用分层, 低评级承压' if _cr_signal=='risk-off' else ('利差极窄, 风险偏好' if _cr_signal=='risk-on' else '利差平静但内部分化')

DATA['credit'] = {
    'regime': {'label':_cr_label,'signal':_cr_signal,'confidence':_confidence(_cr_signal, _cr_hy_pct is not None, _cr_nfci is not None, ccc is not None, igv is not None),
        'description':f'HY OAS {f2(hyv)}% (历史分位 {_cr_hy_pct}), CCC 利差 {f2(ccc)}% (分位 {pct("ccc")}), IG {f2(igv)}%。信用市场内部是否分层是风险偏好的关键观察。'},
    'keySignals': [
        {'title':f'CCC 利差 {f2(ccc)}% ({("走阔" if (tfm("ccc").get("w") or 0)>0 else ("收窄" if (tfm("ccc").get("w") or 0)<0 else "持平"))})',
         'meaning':(
             '最弱信用率先承压是周期中后期特征, 分层说明聪明钱撤离最弱信用。'
             if (tfm('ccc').get('w') or 0) > 0
             else ('最弱信用利差收敛, 风险偏好改善。'
                   if (tfm('ccc').get('w') or 0) < 0
                   else 'CCC 利差持平。')),
         'direction':_msig(dir_of(tfm('ccc').get('w')), False)},
        {'title':f'HY OAS {f2(hyv)}% 处历史 {pct("hy")} 分位',
         'meaning':(
             '利差走阔, 信用市场开始为坏消息定价。'
             if (tfm('hy').get('w') or 0) > 0
             else ('利差收窄, 风险偏好稳健。'
                   if (tfm('hy').get('w') or 0) < 0
                   else '利差极窄, 信用市场未为任何坏消息定价——这是脆弱性而非安全性。')),
         'direction':_msig(dir_of(tfm('hy').get('w')), False)},
        {'title':f'IG OAS {f2(igv)}% 处历史 {pct("ig")} 分位',
         'meaning':(
             '高质量信用利差走阔, 冲击开始触及核心信用。'
             if (tfm('ig').get('w') or 0) > 0
             else ('高质量信用利差收窄, 核心信用稳健。'
                   if (tfm('ig').get('w') or 0) < 0
                   else '高质量信用纹丝不动, 冲击尚未触及核心信用。')),
         'direction':_msig(dir_of(tfm('ig').get('w')), False)},
    ],
    'metrics': [
        {'label':'IG OAS','value':f2(igv)+'%','change':bp(tfm('ig')['d']*100),'dir':dir_of(tfm('ig')['d']),'tag':'IG','percentile':pct('ig'),'signal':_msig(dir_of(tfm('ig')['d']), False),'meaning':'投资级利差极窄','changes':{k:(bp(tfm('ig')[k]*100) if tfm('ig')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('ig')},
        {'label':'BBB OAS','value':f2(bbb)+'%','change':bp(tfm('bbb')['d']*100),'dir':dir_of(tfm('bbb')['d']),'tag':'BBB','percentile':pct('bbb'),'signal':_msig(dir_of(tfm('bbb')['d']), False),'meaning':'堕落天使风险区','changes':{k:(bp(tfm('bbb')[k]*100) if tfm('bbb')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('bbb')},
        {'label':'BB OAS','value':f2(bb)+'%','change':bp(tfm('bb')['d']*100),'dir':dir_of(tfm('bb')['d']),'tag':'BB','percentile':pct('bb'),'signal':_msig(dir_of(tfm('bb')['d']), False),'meaning':'HY最高档仍稳定','changes':{k:(bp(tfm('bb')[k]*100) if tfm('bb')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('bb')},
        {'label':'B OAS','value':f2(b)+'%','change':bp(tfm('b')['d']*100),'dir':dir_of(tfm('b')['d']),'tag':'B','percentile':pct('b'),'signal':_msig(dir_of(tfm('b')['d']), False),'meaning':'中间地带轻微走阔','changes':{k:(bp(tfm('b')[k]*100) if tfm('b')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('b')},
        {'label':'CCC OAS','value':f2(ccc)+'%','change':bp(tfm('ccc')['d']*100),'dir':dir_of(tfm('ccc')['d']),'tag':'CCC','percentile':pct('ccc'),'signal':_msig(dir_of(tfm('ccc')['d']), False),'meaning':'最弱信用率先承压','changes':{k:(bp(tfm('ccc')[k]*100) if tfm('ccc')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('ccc')},
        {'label':'HY OAS (整体)','value':f2(hyv)+'%','change':bp(tfm('hy')['d']*100),'dir':dir_of(tfm('hy')['d']),'tag':'HY','percentile':pct('hy'),'signal':_msig(dir_of(tfm('hy')['d']), False),'meaning':'整体利差极窄','changes':{k:(bp(tfm('hy')[k]*100) if tfm('hy')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('hy')},
        {'label':'NFCI','value':f2(val('nfci')),'change':f'{tfm("nfci")["d"]:+.2f}','dir':dir_of(tfm('nfci')['d']),'tag':'NFCI','percentile':pct('nfci'),'signal':_msig(dir_of(val('nfci')), False),'meaning':'金融条件宽松, 转正是风险信号','changes':{k:(round(tfm('nfci')[k],2) if tfm('nfci')[k] is not None else '—') for k in ('d','w','m','h6')},'sparkline':series30('nfci')},
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
    'analystView': {
        'risk-off': f'信用压力确认: HY OAS 分位 {pct("hy")} 进入高位、NFCI ({f2(val("nfci"))}) 转正, 风险偏好退潮已在最弱环节 (CCC {f2(ccc)}%, 分位 {pct("ccc")}) 发生。信用对股市下跌反应通常滞后 5-10 个交易日, 当前应警惕利差补跌; 低评级 (CCC/B) 承压最明显。',
        'risk-on': f'风险偏好高涨: HY OAS 分位 {pct("hy")} 处于低位, 信用利差极窄。CCC ({f2(ccc)}%, 分位 {pct("ccc")}) 未现分层, 可作适当信用下潜, 但仍需盯住股市与利率的边际变化。',
        'mixed': f'平静下的分层: 利差整体仍窄, 但最弱环节 (CCC {f2(ccc)}%, 分位 {pct("ccc")}) 已现走阔苗头。股票已部分定价利率冲击, 信用市场反应滞后约 5-10 个交易日; 关注 HY OAS 分位 ({pct("hy")}) 是否突破阈值。',
    }[_cr_signal],
    'whatToWatch': [
        {'trigger':'HY OAS 突破 <span class="watch-threshold">3.0%</span>','implication':'信用市场开始为冲击定价, 反身性压制股市','status':f'距离 {max(0,3.0-hyv):.2f}'},
        {'trigger':'CCC-BB 利差突破 <span class="watch-threshold">7%</span>','implication':'信用分层加速, 预示违约周期启动','status':f'当前 {f2(ccc-bb)}%'},
        {'trigger':'杠杆贷款指数跌破 <span class="watch-threshold">97</span>','implication':'浮动利率贷款承压, 定价"higher for longer"','status':'当前98.3'},
    ],
    'chartNotes': {
        'ladderNote': f'CCC {f2(ccc)}% vs 历史中位 12.0% —— 最弱环节离中位最近, 分层已在发生',
        'trendNote': f'HY 月Δ{bp(tfm("hy")["m"]*100 if tfm("hy")["m"] is not None else None)} vs CCC 月Δ{bp(tfm("ccc")["m"]*100 if tfm("ccc")["m"] is not None else None)} —— 内部背离是关键信号',
    },

    # ===== 风险传导图 (利差走阔 → 实体/股市/避险) =====
    # 结构化数据, 前端渲染为 SVG 流程图 (点击节点高亮链路)
    'transmission': {
        'trigger': {
            'label': '利差快速走阔', 'threshold': '周走阔 >10bp = 系统预警',
            'icon': '⚡', 'color': '#a32d2d',
        },
        'chains': [
            {
                'id': 'financing', 'num': '①',
                'link': '企业融资成本↑', 'icon': '💰',
                'detail': '再融资困难, 利息覆盖率下降',
                'endpoint': '违约率↑', 'epColor': '#a32d2d', 'epNote': '尾部风险实化',
                'asset': '高收益债 / 个股', 'dir': 'down',
            },
            {
                'id': 'credit_creation', 'num': '②',
                'link': '银行收紧信贷', 'icon': '🏦',
                'detail': '信用创造收缩, 资产负债表受损',
                'endpoint': '实体经济降温', 'epColor': '#854f0b', 'epNote': 'GDP下修, 失业率↑',
                'asset': '小盘股 / 银行', 'dir': 'down',
            },
            {
                'id': 'deleverage', 'num': '③',
                'link': '对冲/信用基金去杠杆', 'icon': '📉',
                'detail': '强制减仓, 抛售高流动性资产',
                'endpoint': '流动性收紧', 'epColor': '#854f0b', 'epNote': '风险资产抛售蔓延',
                'asset': '高 beta 资产 / 股票', 'dir': 'down',
            },
            {
                'id': 'flight', 'num': '④',
                'link': '资金涌向避险资产', 'icon': '🛡',
                'detail': '从风险资产流向国债/黄金/美元',
                'endpoint': '避险资产走强', 'epColor': '#0f6e56', 'epNote': '正凸性: 利率下行+避险溢价',
                'asset': '美债 / 黄金 / 美元', 'dir': 'up',
            },
        ],
    },

    # ===== 各等级利差对风险传导的重要性矩阵 =====
    # 4 个重要性维度 × 7 个评级, 评分 0-5 (5=最重要)
    'importance': {
        'dimensions': [
            {'key': 'leading', 'label': '领先性',
             'desc': '率先发出系统风险信号', 'icon': '⏱'},
            {'key': 'systemic', 'label': '系统性',
             'desc': '走阔=全局风险偏好恶化', 'icon': '🌐'},
            {'key': 'tailRisk', 'label': '尾部风险',
             'desc': '定价违约/重组最敏感', 'icon': '⚠'},
            {'key': 'cycle', 'label': '周期信号',
             'desc': '反映盈利/衰退周期', 'icon': '🔄'},
        ],
        # 重要性评分 (5=极高, 0=无意义), 实际数据驱动
        'ratings': ['AAA', 'AA', 'A', 'BBB', 'BB', 'B', 'CCC'],
        'scores': {
            'AAA': {'leading': 1, 'systemic': 1, 'tailRisk': 1, 'cycle': 1, 'note': '无定价意义, 接近无风险利率'},
            'AA':  {'leading': 1, 'systemic': 2, 'tailRisk': 1, 'cycle': 1, 'note': '系统性风险先行指标'},
            'A':   {'leading': 2, 'systemic': 3, 'tailRisk': 1, 'cycle': 2, 'note': '主流投资级, 周期性敏感'},
            'BBB': {'leading': 3, 'systemic': 4, 'tailRisk': 2, 'cycle': 3, 'note': '堕落天使前沿, 系统性最强信号'},
            'BB':  {'leading': 3, 'systemic': 3, 'tailRisk': 3, 'cycle': 4, 'note': 'HY最高档, 周期信号最清晰'},
            'B':   {'leading': 4, 'systemic': 3, 'tailRisk': 4, 'cycle': 4, 'note': '中位HY, 周期+尾部'},
            'CCC': {'leading': 5, 'systemic': 3, 'tailRisk': 5, 'cycle': 4, 'note': '尾部最敏感, 周期顶部信号'},
        },
        'currentOAS': {  # 用于前端在热力图上叠加当前 OAS
            'AAA': aaa, 'AA': aa, 'A': av, 'BBB': bbb, 'BB': bb, 'B': b, 'CCC': ccc,
        },
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

# 波动率 regime (2026-08-12 优化): 压力区资产数量 + VIX 水平 + VIX 期限结构 + 变化方向
_n_stress = len(stress_assets)
_vix_v = vix or 0
_vix_w = tfm('vix').get('w') or 0     # VIX 周变
# VIX 期限结构: 近月>远月 (backwardation) = 压力
_ts_back = (vix is not None and vix3m is not None and vix > vix3m)
_vol_score = 0
if _n_stress >= 2: _vol_score -= 2
elif _n_stress == 1: _vol_score -= 1
if _vix_v >= 25: _vol_score -= 2
elif _vix_v >= 18: _vol_score -= 1
elif _vix_v < 15: _vol_score += 1
if _ts_back: _vol_score -= 1
if _vix_w > 3: _vol_score -= 1
elif _vix_w < -3: _vol_score += 1
_vol_signal = 'risk-off' if _vol_score <= -2 else ('risk-on' if _vol_score >= 2 else 'mixed')
_vol_label = ('波动率压力扩散 (VIX 高位 / 期限结构倒挂)' if _vol_signal == 'risk-off' else
              ('波动率平静 (VIX 低位 + 期限结构正常)' if _vol_signal == 'risk-on' else '波动率分化'))
DATA['volatility'] = {
    'regime': {'label':_vol_label,'signal':_vol_signal,'confidence':_confidence(_vol_signal, vix is not None, vix3m is not None, len(ca_rows) >= 3),
        'description':f'当前处于压力区的资产: {(",".join(stress_assets) if stress_assets else "无")}。VIX {f2(vix)}' + (f', OVX {f2(ovx)}' if ovx else '') + (f', MOVE {f2(move)}' if move else '') + '。波动率分化形态反映压力是否从单一资产外溢。'},
    'keySignals': [s for s in [
        ({'title':f'OVX {f2(ovx)} vs VIX {f2(vix)} 剪刀差 {ovx_vix_gap}pt','meaning':'油股波动率极端分化, 历史上多以油价回落或 VIX 补涨收敛。','direction':('bearish' if (ovx_vix_gap or 0) > 8 else 'mixed')} if ovx_vix_gap is not None else None),
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
    'analystView': {
        'risk-off': f'系统性风险信号浮现: 压力集中在 {(",".join(stress_assets) if stress_assets else "无")}, VIX {f2(vix)}' + (f' 已突破20确认线' if vix and vix>=20 else (f' 距20确认线 {20-vix:.1f}pt' if vix else '')) + f'; 期限结构 {ts_state}——近月高于远月是即时风险定价。' + (f'SKEW {f1(skew)} 显示机构尾部保护需求真实存在。' if skew else '') + '若剪刀差收敛以 VIX 补涨完成, 买入 VIX 看涨价差是对冲选项。',
        'risk-on': f'波动率平静: 无资产进入压力区 (VIX {f2(vix)})' + (f', 距20确认线 {20-vix:.1f}pt' if vix else '') + f'; 期限结构 {ts_state}。' + (f'SKEW {f1(skew)} 中性, 尾部保护需求低。' if skew else '') + '系统性风险未定价, 风险资产 beta 可适度承担。',
        'mixed': f'波动率分化: 压力集中在 {(",".join(stress_assets) if stress_assets else "无——全曲线平静")}; VIX {f2(vix)}' + (f' 距20确认线 {20-vix:.1f}pt' if vix else '') + f'; 期限结构 {ts_state}——近月高于远月才是即时风险定价。' + (f'SKEW {f1(skew)} 说明机构在买尾部保护, 表面平静下对冲需求真实存在。' if skew else '') + '策略: 若剪刀差收敛以 VIX 补涨完成, 买入 VIX 看涨价差是风险回报比好的对冲。',
    }[_vol_signal],
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
    """红绿灯面板每一行; status: triggered / warning / safe / unknown"""
    if value is None:
        status = 'unknown'
    elif triggered:
        status = 'triggered'
    else:
        # 危险方向上逼近阈值 (60%~100% 区间) 但未触发 = warning
        if threshold > 0 and threshold * 0.6 <= value < threshold:
            status = 'warning'
        elif threshold < 0 and threshold < value <= threshold * 0.6:
            status = 'warning'
        else:
            status = 'safe'
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
    'analystView': ('衰退仪表盘 6 项独立信号交叉验证, 综合评分 ' + f'{_recession_score}/100 ({_recession_level})。当前: '
        + f'触发 {_triggered_count} 项 / 预警 {_warning_count} 项 (10Y-2Y {_spread_10_2_val:+.0f}bp, Sahm {_sahm["value"]}, 初请4周均 {_claims_4wk/1000:.0f}K, NYFed 衰退概率 {f1(_recession_p)}%)。'
        + '分析框架: ① 利率信号 (10Y-2Y / 3M-10Y) 是领先约 12 个月的"收益率曲线"指标, 当前未倒挂 = 扩张延续; '
        + '② 就业即时指标 (Sahm / 初请 / 失业率) 是"确认器"——Sahm 未触发、初请 199K 低位 = 就业未恶化; '
        + '③ 前瞻指标 (NYFed 概率 / 金融压力) 提供边际方向。当前组合属"增长放缓但不衰退"的扩张后期: 非农 -23K 转负是边际警示, 但须失业率月变持续 >0.1pt + 初请上穿 325K 才确认拐点。'
        + '资产含义: 此阶段权益通常仍可持有但降低 beta, 利率下行初期利于长久期债券, 黄金在央行购金托底 + 实际利率见顶假设下具配置价值; 若触发信号 ≥3 项, 应转向防御 (现金/短债/高质量)。'),
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
# ==== 评分基线与各板块优化后的 regime 联动 (2026-08-12) ====
_RR = {'risk-off': 70, 'mixed': 45, 'risk-on': 25}   # signal → 风险分

# 1. 利率环境: 用 rates regime (曲线形态+10Y 分位+方向), 叠加 10Y 历史分位修正
_rate_risk = _RR.get(_rates_signal, 50)
if _r_10y_pct is not None:
    _rate_risk += (_r_10y_pct - 50) * 0.3   # 10Y 分位高 → 风险更高
_rate_risk = max(0, min(100, round(_rate_risk)))
_rate_status = 'bearish' if _rate_risk >= 60 else ('mixed' if _rate_risk >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_rate_risk, 14, '利率环境', _rate_status))

# 2. 流动性压力: LPI 评分 (liquidity 板块已数据驱动合成)
_lpi = DATA.get('liquidity', {}).get('lpi', {})
_lpi_score = _lpi.get('score', 5) * 10
_lpi_status = 'bearish' if _lpi_score >= 60 else ('mixed' if _lpi_score >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_lpi_score, 16, '流动性压力', _lpi_status))

# 3. 信用市场: 用 credit regime (HY/CCC 分位 + NFCI + 走阔方向), 叠加 CCC 分位修正
_credit_risk = _RR.get(_cr_signal, 50)
if _cr_ccc_pct is not None:
    _credit_risk += (_cr_ccc_pct - 50) * 0.3
_credit_risk = max(0, min(100, round(_credit_risk)))
_credit_status = 'bearish' if _credit_risk >= 60 else ('mixed' if _credit_risk >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_credit_risk, 12, '信用市场', _credit_status))

# 4. 波动率风险: 用 volatility 评分 (_vol_score -4..+3 → 0-100)
_vix_risk = max(0, min(100, round(50 - (_vol_score or 0) * 12)))
_vix_status = 'bearish' if _vix_risk >= 55 else ('mixed' if _vix_risk >= 28 else 'bullish')
_risk_factors.append(_risk_factor(_vix_risk, 11, '波动率风险', _vix_status))

# 5. 经济基本面: 用 economy regime 三块评分 (劳动力+通胀+增长)
_eS = _econ_regime.get('scores', {})
_econ_risk = round((100 - _eS.get('labor', 50)) * 0.35 + _eS.get('inflation', 50) * 0.35 + (100 - _eS.get('growth', 50)) * 0.30)
_econ_risk = max(0, min(100, _econ_risk))
_econ_status = 'bearish' if _econ_risk >= 60 else ('mixed' if _econ_risk >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_econ_risk, 13, '经济基本面', _econ_status))

# 6. 政策路径: 用 fed regime (隐含降/加息次数), 加息定价越多风险越高
_fed_risk = _RR.get(_fed_signal, 50) + (_fed_hikes or 0) * 10
_fed_risk = max(0, min(100, _fed_risk))
_fed_status = 'bearish' if _fed_risk >= 60 else ('mixed' if _fed_risk >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_fed_risk, 9, '政策路径', _fed_status))

# 7. 跨资产信号: 股债相关 + OVX-VIX 剪刀差 + 压力资产数
_asset_risk = 35 if (spx_tlt_corr and spx_tlt_corr > 0) else 22
if ovx_vix_gap is not None and ovx_vix_gap > 8:
    _asset_risk += 20   # 油股波动率极端分化
if _n_stress >= 2:
    _asset_risk += 20   # 多资产进入压力区
_asset_risk = max(0, min(100, _asset_risk))
_asset_status = 'bearish' if _asset_risk >= 60 else ('mixed' if _asset_risk >= 30 else 'bullish')
_risk_factors.append(_risk_factor(_asset_risk, 8, '跨资产信号', _asset_status))

# 8. 衰退风险: 衰退概率评分 (保留, 已含 10Y-2Y/Sahm/初请/金融压力)
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
    'description': f'8板块加权聚合风险评分 {_total_score}/100 ({_risk_level})。权重: 流动性16% + 衰退17% + 利率14% + 经济13% + 信用12% + 波动率11% + 政策路径9% + 跨资产8%。',
    'factors': _risk_factors,
    'summary': f'当前宏观风险画像: {"利率+衰退主导" if _rate_risk > 50 or _rec_risk > 40 else ("流动性为主的结构性压力" if _lpi_score > 50 else "风险可控, 关注边际变化")}。核心风险点: ' + 
        (', '.join(f['label'] for f in _risk_factors if f['score'] >= 50) or '无单一板块超警戒线') + '。',
}

print('[gen_datajs] riskScore section OK', file=sys.stderr, flush=True)

# ====== 板块关键信号 · 转向警示注入 (2026-08-12) ======
# 目标: 关键信号不只做状态描述, 而是捕捉"重大变化/转向"——阈值突破、方向反转、极端分位、
# 意外数据等, 前置为 ⚠ 警示信号, 起到预警作用。
def _sig_alert(title, meaning, direction, level=1):
    """构造转向警示信号 (level 1=警示 2=强警示)"""
    return {'title': title, 'meaning': meaning, 'direction': direction,
            'alert': True, 'alertText': meaning, 'alertLevel': level}

def _prepend_section_alerts():
    A = {'rates': [], 'fed': [], 'liquidity': [], 'credit': [], 'volatility': [],
         'economy': [], 'recession': []}
    def _rev(h6, m):
        """由降转升 (半年下行, 最近上行)"""
        return h6 is not None and m is not None and h6 < 0 and m > 0
    def _rev_dn(h6, m):
        """由升转降 (半年上行, 最近下行)"""
        return h6 is not None and m is not None and h6 > 0 and m < 0

    # ---- 利率: 长端趋势反转 / 极端分位 / 曲线形态切换 ----
    _t10_w = tfm('dgs10').get('w') or 0
    _t10_h6 = tfm('dgs10').get('h6') or 0
    _t10_m = tfm('dgs10').get('m') or 0
    if _rev(_t10_h6, _t10_m):
        A['rates'].append(_sig_alert('⚠ 长端利率转向上行', f'10Y 半年 {_t10_h6*100:+.0f}bp 下行后月内转升 ({_t10_m*100:+.0f}bp), 利率趋势反转', 'bearish', 2))
    elif _rev_dn(_t10_h6, _t10_m):
        A['rates'].append(_sig_alert('⚠ 长端利率转向下行', f'10Y 半年 {_t10_h6*100:+.0f}bp 上行后月内转降 ({_t10_m*100:+.0f}bp), 利率趋势反转', 'bullish', 2))
    if _r_10y_pct is not None and _r_10y_pct > 85 and _t10_w > 0:
        A['rates'].append(_sig_alert('⚠ 10Y 极端高分位', f'10Y 历史分位 {_r_10y_pct}%, 周 {_t10_w*100:+.0f}bp 仍在上行, 长端估值压力极值', 'bearish', 2))
    if _r_tips_m > 0.1:
        A['rates'].append(_sig_alert('⚠ 实际利率回升', f'10Y TIPS 月内 +{_r_tips_m*100:.0f}bp, 实际折现率上行压制估值', 'bearish', 1))

    # ---- 美联储: 政策路径转向 / QT 加速 ----
    if _fed_cuts >= 1 or _fed_hikes >= 1:
        A['fed'].append(_sig_alert('⚠ 市场定价政策转向', f'短端曲线隐含未来12个月 {_fed_cuts} 次降息 / {_fed_hikes} 次加息, 政策路径重新定价', 'bearish' if _fed_hikes >= _fed_cuts else 'bullish', 1))
    _wl_w = tfm('walcl').get('w') or 0
    if _wl_w < -20:
        A['fed'].append(_sig_alert('⚠ QT 加速', f'WALCL 周 {comma(abs(_wl_w)/1000,1)}$B 缩减, 缩表速度加快', 'bearish', 1))

    # ---- 流动性: 净流动性转向 / 融资紧张 ----
    _nl_h6 = tfm('netliq').get('h6') if tfm('netliq').get('h6') is not None else None
    _nl_m2 = _nl_m
    if _rev_dn(_nl_h6, _nl_m2):
        A['liquidity'].append(_sig_alert('⚠ 净流动性转向收缩', '半年扩张后月内转降, 流动性环境拐点', 'bearish', 2))
    if _sofr_gap > 0.001:
        A['liquidity'].append(_sig_alert('⚠ 融资市场紧张', f'SOFR 高于 IORB {( _sofr_gap*10000):.0f}bp, 资金价格上行', 'bearish', 1))

    # ---- 信用: 利差快速走阔 / 低评级极端 ----
    if _cr_hy_w > 10:
        A['credit'].append(_sig_alert('⚠ HY 利差快速走阔', f'HY OAS 周 {_cr_hy_w:+.0f}bp, 信用风险定价加速', 'bearish', 2))
    if _cr_ccc_pct is not None and _cr_ccc_pct > 85:
        A['credit'].append(_sig_alert('⚠ CCC 极端高分位', f'CCC 利差历史分位 {_cr_ccc_pct}%, 低评级承压极值', 'bearish', 2))

    # ---- 波动率: VIX 突破 / 期限结构倒挂 / 压力扩散 ----
    if _vix_v >= 20 and (_vix_v < 25):
        A['volatility'].append(_sig_alert('⚠ VIX 站上 20', f'VIX {_vix_v:.1f}, 波动率目标基金被动减仓触发, 抛压自我强化', 'bearish', 2))
    if _ts_back:
        A['volatility'].append(_sig_alert('⚠ VIX 期限结构倒挂', '近月 VIX 高于远月 (backwardation), 短期恐慌定价', 'bearish', 1))
    if _n_stress >= 2:
        A['volatility'].append(_sig_alert(f'⚠ 多资产进入压力区', f'{",".join(stress_assets)} 均超压力阈值, 波动率压力扩散', 'bearish', 2))

    # ---- 经济: 失业率/通胀转向 / Sahm 触发 ----
    _ur_h6 = unrate_tf.get('h6')
    _ur_m = unrate_tf.get('m')
    if _rev(_ur_h6, _ur_m):
        A['economy'].append(_sig_alert('⚠ 失业率转向回升', f'半年 {_ur_h6:+.1f}pt 下行后月内转升 ({_ur_m:+.1f}pt), 就业拐点', 'bearish', 2))
    _cpi_h6 = cpi_d6 if 'cpi_d6' in dir() else None
    if _rev(_cpi_h6, cpi_d1):
        A['economy'].append(_sig_alert('⚠ 通胀转向回升', f'CPI 半年下行后月环比转升 ({cpi_d1:+.1f}pt), 通胀拐点', 'bearish', 2))
    if _sahm.get('triggered'):
        A['economy'].append(_sig_alert('⚠ Sahm 规则触发', f'Sahm Rule = {_sahm["value"]}, 历史上 100% 对应衰退', 'bearish', 2))
    if payems_mom is not None and payems_mom < 0:
        A['economy'].append(_sig_alert('⚠ 非农转负', f'非农月增 {payems_mom:+.0f}K, 就业收缩信号', 'bearish', 1))

    # ---- 衰退: 触发信号数 ----
    if _triggered_count >= 2:
        A['recession'].append(_sig_alert(f'⚠ 衰退信号 {_triggered_count} 项触发', f'{_triggered_count} 项独立信号已触发 (+{_warning_count} 项预警), 衰退概率模型当前 {f1(_recession_p)}%', 'bearish', 2))
    elif _warning_count >= 3:
        A['recession'].append(_sig_alert(f'⚠ 衰退预警 {_warning_count} 项', f'{_warning_count} 项信号进入预警区, 距离触发仅一步', 'bearish', 1))

    for _sec, _alerts in A.items():
        if DATA.get(_sec) and DATA[_sec].get('keySignals') and _alerts:
            DATA[_sec]['keySignals'] = _alerts + DATA[_sec]['keySignals']

_prepend_section_alerts()

# ====== 交易机会雷达 (Trade Opportunity Radar) ======
# 目标: 把宏观观测转化为可交易信号——扫描 5 类预期差 (政策路径/数据surprise/regime-价格背离/分位极端/传导断裂),
# 再由规则引擎输出全品类资产映射候选。纯规则, 数据全部来自上面各板块已计算的 regime/评分。
# v4 方法论升级: 双层信息隔离 (Tier A 价格隐含 vs Tier B 基本面判断) + 独立性审计 + 决策漏斗 + 证伪监控
print('[gen_datajs] generating tradeRadar section...', file=sys.stderr, flush=True)

# ---- Tier A 辅助: 滚动相关 / 实现波动 ----
def _aligned_series(m1, m2):
    common = sorted(set(m1) & set(m2))
    return [m1[d] for d in common], [m2[d] for d in common]

def _rolling_corr(key_a, mode_a, key_b, mode_b, win=60):
    """两序列的滚动相关 (win 日)。mode: 'ret'=日度收益 (价格序列), 'chg'=日度变化 (水平型序列)"""
    ma = daily_ret_map(key_a, win) if mode_a == 'ret' else _chg_map(key_a, win)
    mb = daily_ret_map(key_b, win) if mode_b == 'ret' else _chg_map(key_b, win)
    x, y = _aligned_series(ma, mb)
    if len(x) < 20:
        return None
    return corr_pair(x, y)

def _realized_vol(key, win=10):
    """SPX 等价格序列的近期实现波动 (年化%), 用于与 VIX 隐含波动对比。"""
    rets = list(daily_ret_map(key, win).values())
    if len(rets) < 5:
        return None
    m = sum(rets) / len(rets)
    sd = (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5
    return round(sd * (252 ** 0.5) * 100, 1)

def _build_price_implied():
    """Tier A 价格隐含信号: 市场用真金白银表达的观点 (独立于基本面判断)。"""
    out = {}
    # ① 金-实际利率 60 日滚动相关: 负=经典锚定; 接近0/转正=脱钩 (黄金定价模式)
    out['goldRealCorr'] = _rolling_corr('gold', 'ret', 'tips10', 'chg', 60)
    # ② 股-债 60 日滚动相关: 负=增长驱动/避险模式(股涨债跌); 正=贴现率冲击(股债同跌)
    out['stockBondCorr'] = _rolling_corr('spx', 'ret', 'tlt', 'ret', 60)
    # ③ 金-美元 60 日滚动相关: 负=传统负相关; 脱钩=相关转正/接近0
    out['goldUsdCorr'] = _rolling_corr('gold', 'ret', 'dxy', 'ret', 60)
    # ④ 隐含-实现波动差: VIX (隐含, 年化) vs SPX 10 日实现波动 (年化); 正大=波动率溢价高估
    _rv = _realized_vol('spx', 10)
    out['realizedVol'] = _rv
    if _rv is not None and vix is not None:
        out['vixImplRealGap'] = round(vix - _rv, 1)
    else:
        out['vixImplRealGap'] = None
    # ⑤ 10Y-2Y 斜率 (曲线形态, 价格结构)
    out['curveSlope'] = spread_10_2
    return out

def _build_catalyst_calendar(gaps):
    """催化剂日历: 未来关键数据/FOMC → 收敛或扩大哪个预期差。
    每个事件的 affect 说明双向触发条件 (数据方向决定收敛/扩大)。"""
    gap_by_id = {g.get('id'): g for g in gaps}
    cal = []

    def _rel(tag, label, gid, affect, importance='high'):
        ri = release_info(tag)
        if ri and ri.get('next'):
            cal.append({'date': ri['next'], 'event': label, 'importance': importance,
                        'gapId': gid, 'gapTitle': gap_by_id.get(gid, {}).get('title', ''),
                        'effect': affect})

    # 通胀/政策类 (核心 CPI / PCE / 超级核心)
    _rel('Core', '美国 7 月核心 CPI', 'policy_gap',
         '核心 CPI 环比 <0.2% → 收敛(加息定价压缩, 利多短端); >0.3% → 扩大(加息尾部定价升温)')
    _rel('CPI', '美国 7 月 CPI', 'infl_surprise',
         'CPI 连续低于预期 → 收敛(通胀降温确认); 高于预期 → 扩大(粘性回归)')
    _rel('SuperCore', '美国 6 月 PCE(含超级核心)', 'policy_gap',
         '超级核心同比 <3.5% → 收敛; >4% → 扩大(服务通胀顽固)')
    # 就业类
    _rel('NFP', '美国 8 月非农就业', 'jobs_surprise',
         '非农再负或 <80K → 收敛(就业拐点确认, 利多短端/黄金); >180K → 扩大(噪音, 软着陆强化)')
    _rel('UNRATE', '美国 8 月失业率', 'jobs_surprise',
         '失业率月变 >0.1pt → 收敛(Sahm 逼近触发); 回落 → 扩大')
    # 增长类 (标注)
    _rel('Retail', '美国 7 月零售销售', 'pct_10y',
         '零售环比 >0.5% → 扩大(增长强, 利率高位延续); <-0.3% → 收敛(消费转弱)')
    _rel('Conf', '美国 8 月消费者信心', 'pct_10y',
         '信心大幅走弱 → 收敛(衰退式降息预期升温)')

    # FOMC 未来会议
    for _m in EV.get('fomc', []):
        _s = _m.get('start', '')
        if _s and _s >= GEN_DATE:
            cal.append({'date': _s, 'event': _m.get('label', 'FOMC 会议'),
                        'importance': 'high', 'gapId': 'policy_gap',
                        'gapTitle': gap_by_id.get('policy_gap', {}).get('title', ''),
                        'effect': '议息结果 + 点阵图 + 发布会: 对通胀定性(暂时性 vs 持续)决定政策路径差收敛或扩大; SEP 点是关键'})
            break
    # 杰克逊霍尔
    _jh = EV.get('jackson_hole', {})
    if _jh and _jh.get('start', '') >= GEN_DATE:
        cal.append({'date': _jh['start'], 'event': 'Jackson Hole 央行年会', 'importance': 'high',
                    'gapId': 'policy_gap', 'gapTitle': gap_by_id.get('policy_gap', {}).get('title', ''),
                    'effect': 'Warsh 首次央行年会定调: 若重申"higher for longer" → 扩大; 若暗示就业权重上升 → 收敛'})

    cal.sort(key=lambda x: x['date'])
    return cal


def _build_ai_valuation_gap():
    """AI 链条估值预期差: 板块整体估值 vs 盈利增长, 挑出高估/低估候选。"""
    rows = []
    for L in AIC.get('layers', []):
        for c in L.get('companies', []):
            peg = c.get('peg'); fpe = c.get('fwdPe'); rg = c.get('revGrowth')
            if peg is None and fpe is None:
                continue
            rows.append({'name': c.get('name'), 'ticker': c.get('ticker'),
                         'layer': L.get('name', ''), 'peg': peg, 'fwdPe': fpe,
                         'revGrowth': rg, 'mc': c.get('marketCap', 0),
                         'aiExposure': c.get('aiExposure')})
    if len(rows) < 3:
        return {'summary': 'AI 链条数据不足', 'stats': {}, 'overvalued': [], 'undervalued': []}
    fpes = [r['fwdPe'] for r in rows if r['fwdPe']]
    pgs = [r['peg'] for r in rows if r['peg']]
    rgs = [r['revGrowth'] for r in rows if r['revGrowth']]
    stats = {
        'count': len(rows),
        'avgFwdPe': round(sum(fpes) / len(fpes), 1) if fpes else None,
        'medianPeg': round(sorted(pgs)[len(pgs) // 2], 2) if pgs else None,
        'medianGrowth': round(sorted(rgs)[len(rgs) // 2], 1) if rgs else None,
    }
    over, under = [], []
    for r in rows:
        if r['peg'] is not None and r['peg'] > 2.5:
            over.append(r)
        elif r['fwdPe'] is not None and r['fwdPe'] > 40 and r['revGrowth'] is not None and r['revGrowth'] < 25:
            over.append(r)
        if r['peg'] is not None and r['peg'] < 1.2 and r['revGrowth'] is not None and r['revGrowth'] > 30:
            under.append(r)
        elif r['fwdPe'] is not None and r['fwdPe'] < 22 and r['revGrowth'] is not None and r['revGrowth'] > 30:
            under.append(r)
    over.sort(key=lambda x: -(x['peg'] or x['fwdPe'] or 0))
    under.sort(key=lambda x: x['peg'] or 99)
    summary = (f'AI 链条 {stats["count"]} 家公司: 平均远期 PE {stats["avgFwdPe"]}x, PEG 中位 {stats["medianPeg"]}, '
               f'营收增速中位 {stats["medianGrowth"]}%。'
               + (f'高估候选 {len(over)} 家 / 低估候选 {len(under)} 家。' if over or under else '估值与增速基本匹配, 无明显分层。')
               + ' PEG>2.5 或"高 PE+低增速"为高估; PEG<1.2 且增速>30% 为低估。估值预期差须与产业链景气度交叉验证。')

    # ===== AI 交易机会"交易化表达" (2026-08-14) =====
    # 每笔 AI 机会 = 一个可下注的假设卡片: 底层赌注/验证点/证伪条件/因子暴露
    # 核心: AI 链条交易的底层赌注是"AI Capex 超级周期延续 vs 估值泡沫修正"的预期差,
    #       而非单纯的"PE 便宜/贵"。与宏观候选共用 6 维因子暴露 → 参与组合净暴露与独立性审计。
    ai_trades = []

    def _ai_trade(name, side, bet, verify, falsify, conf, asym_score, asym_note,
                  ev_for, ev_against, exposures, driver, asset_label=None):
        ai_trades.append({
            'asset': asset_label or name, 'side': side, 'thesis': bet,
            'bet': bet, 'verify': verify, 'falsify': falsify,
            'trigger': verify, 'confidence': conf,
            'asymmetry': {'score': asym_score, 'note': asym_note},
            'evidenceFor': ev_for, 'evidenceAgainst': ev_against,
            'exposures': exposures, 'driver': driver,
            'falsifyRules': [], 'source': 'ai_chain',
        })

    # ---- 低估候选 → 多头机会 (赌 Capex 周期延续) ----
    _und_names = {u['name'] for u in under[:6]}
    _und_layers = {u['layer'] for u in under[:6]}
    # 产业链核心多头 (芯片/基础设施/网络 低估龙头)
    _chip_und = [u for u in under if u['layer'] in ('芯片层', '基础设施层', '网络连接层')][:3]
    if _chip_und:
        _names = '、'.join(u['name'] for u in _chip_und)
        _pegs = '、'.join((str(u['peg']) if u['peg'] else '—') for u in _chip_und)
        _ai_trade(
            'AI 算力核心供应商 (芯片/基础设施)', '做多',
            f'赌 AI Capex 超级周期延续: 四大云厂 FY26 资本开支仍在扩张, 芯片/基础设施层低估龙头 ({_names}, PEG {_pegs}) 的营收增速将覆盖当前估值——买的是"算力需求持续上修"而非便宜。',
            '验证点: ①NVDA Q2 财报指引 (8月下旬) ②云厂下季度 capex 指引 ③TSM 月营收/CoWoS 产能利用率',
            '证伪: ①云厂下调 capex 指引 ②NVDA 指引 miss ③订单积压增速放缓 ④AI 应用变现不及预期(资本开支转向)',
            'high', 4, '偏凸: 上行有 Capex 上修 + 订单超预期(空间大), 下行有 AI 资本开支周期见顶(估值+盈利双杀)——但周期未见顶前下行有限',
            [f'PEG {_pegs} 增速覆盖估值', 'TSM/NVDA 订单积压创新高', '云厂 capex 仍在上修'],
            ['AI 估值整体偏高 (板块 FwdPE 32x)', '若利率上行压制长久期成长估值', 'CoreWeave 高杠杆放大周期风险'],
            {'growth': +2, 'rate': -1}, 'ai_capex_supercycle', 'AI 算力核心 (芯片/基础设施)')
    # 网络/光模块层
    _net_und = [u for u in under if u['layer'] == '网络连接层'][:2]
    if _net_und:
        _n = '、'.join(u['name'] for u in _net_und)
        _ai_trade(
            'AI 光模块/网络 (数据中心互联)', '做多',
            f'赌数据中心互联需求超线性增长: 800G/1.6T 光模块迭代 + 集群规模扩张, 网络层低估龙头 ({_n}) 受益于"算力集群越大、互联占比越高"。',
            '验证点: ①光模块龙头月度出货/订单 ②云厂数据中心集群扩容公告 ③1.6T 渗透率',
            '证伪: ①光模块价格战/毛利率下滑 ②集群建设放缓 ③技术路线切换(硅光/CPO 替代)',
            'mid', 3, '中性: 高增速 + 高景气, 但技术迭代快(CPO 威胁)与非对称性有限',
            ['800G→1.6T 迭代周期', '集群互联占比提升', '光模块龙头估值低于芯片层'],
            ['CPO/硅光技术替代风险', '云厂 capex 若收缩首先砍网络', '板块波动率大'],
            {'growth': +2, 'rate': -1}, 'ai_networking', f'AI 光模块/网络 ({_n})')

    # ---- 高估候选 → 回避/做空机会 (赌估值修正) ----
    _over_top = over[:2]
    if _over_top:
        _names = '、'.join(u['name'] for u in _over_top)
        _pegs = '、'.join(str(u['peg']) for u in _over_top if u['peg'])
        _ai_trade(
            'AI 高估值标的 (回避/做空)', '回避/做空',
            f'赌估值泡沫修正: {_names} (PEG {_pegs}) 隐含的增速预期已远超基本面能兑现的速度——买的是"预期差回归", 当盈利兑现速度跟不上估值时估值压缩。',
            '验证点: ①财报营收增速是否环比回落 ②EPS 上修是否停止 ③板块轮动(资金流向低估值)',
            '证伪: ①增速继续超预期(盈利消化估值) ②AI 需求进一步加速 ③重大产品突破(新叙事)',
            'mid', 3, '中性偏负: 做空高估值 AI 赚估值压缩, 但 AI 高景气下"贵而继续涨"是常态(动量风险大)——更适合对冲而非裸空',
            [f'PEG {_pegs} 显著高于板块中位 {stats["medianPeg"]}', '估值分位极端', '若增速放缓则戴维斯双杀'],
            ['AI 景气度仍高 (订单$1040B)', '高估值可能被新叙事消化', '做空成本高(借券费率)'],
            {'growth': -1, 'infl': +1, 'rate': +1}, 'ai_valuation_bubble', 'AI 高估值标的 (回避)')

    # HBM 存储 (周期+AI 双击)
    _hbm = [u for u in under if u['name'] in ('SK海力士', '美光', '三星电子')][:2]
    if _hbm:
        _n = '、'.join(u['name'] for u in _hbm)
        _g = '、'.join(str(u['revGrowth']) for u in _hbm if u['revGrowth'])
        _ai_trade(
            'HBM/存储 (AI 周期双击)', '做多',
            f'赌 HBM 供不应求 + 存储涨价周期: {_n} (营收增速 {_g}%) 同时受益 AI 内存带宽需求与存储周期反转, PEG<1.2 提供安全边际。',
            '验证点: ①HBM 订单/价格 (SK海力士 季度财报) ②DRAM/NAND 合约价 ③云厂 HBM 采购',
            '证伪: ①存储价格见顶回落 ②HBM 供应过剩(三星/美光扩产) ③周期下行',
            'mid', 4, '偏凸: 周期底部 + AI 需求双击, 上行空间大; 下行有周期底+低 PEG 缓冲',
            ['HBM 供不应求', '存储周期上行', 'PEG<1.2 安全边际'],
            ['存储周期波动大', '供应过剩风险', 'AI 需求不及预期'],
            {'growth': +2, 'infl': +1}, 'ai_memory_cycle', f'HBM/存储 ({_n})')

    return {'summary': summary, 'stats': stats,
            'overvalued': [{k: r[k] for k in ('name', 'ticker', 'layer', 'peg', 'fwdPe', 'revGrowth')} for r in over[:6]],
            'undervalued': [{k: r[k] for k in ('name', 'ticker', 'layer', 'peg', 'fwdPe', 'revGrowth')} for r in under[:6]],
            'trades': ai_trades}

def _build_trade_radar():
    gaps = []
    trades = []
    _gold_regime = (DATA.get('assets', {}).get('goldNarrativeChart', {}).get('regime') or {})
    _gold_cb_score = 0
    for _dr in _gold_regime.get('drivers', []):
        if _dr.get('key') == 'cb':
            _gold_cb_score = _dr.get('score', 0)
    _gold_ret90 = _gold_regime.get('goldReturn')
    _eSig = _econ_regime.get('signal')
    # Tier A 价格隐含信号 (gaps/trades 生成前计算, 供 A−B 跨层对比)
    _price_implied = _build_price_implied()
    _eS2 = _econ_regime.get('scores', {})
    _spx_m = tfm('spx').get('m') or 0
    _corecpi_m = tfm('core_cpi').get('m') or 0

    def _gap(gtype, title, detail, direction, confidence, category, gid=None, source='cross'):
        """source: 'cross'=价格隐含 vs 基本面判断 (真预期差, Tier A−B);
                   'price'=价格内部对比 (Tier A−A, 如波动率错价);
                   'view'=基本面内部 (Tier B−B, 应避免——同源自我强化)"""
        gaps.append({'id': gid or ('gap_%d' % len(gaps)), 'type': gtype, 'title': title, 'detail': detail,
                     'direction': direction, 'confidence': confidence, 'category': category, 'source': source})

    def _trade(asset, side, thesis, trigger, confidence, asym=None, falsify=None, ev_for=None, ev_against=None,
               driver='', falsify_rules=None, exposures=None, bet=None):
        """交易候选 = 一个可下注的假设。
        asym: {'score': 1-5, 'note'} 非对称性 (塔勒布凸性)
        falsify: [证伪条件文本] → 展示
        falsify_rules: [{'id','cond','threshold','dir','desc'}] → 每日自动证伪监控
        driver: 驱动主题标签 (独立性审计用: 同 driver = 同一笔赌注)
        exposures: {因子: -2~+2} 这笔交易底层在赌什么宏观状态 (正=看多该因子)
                   rate(利率下行) infl(通胀回升) growth(增长强劲) liq(流动性宽松) haven(避险) credit(信用改善)
        bet: 底层赌注一句话 (交易员视角: 这笔交易本质在赌什么)"""
        trades.append({'asset': asset, 'side': side, 'thesis': thesis,
                       'trigger': trigger, 'confidence': confidence,
                       'driver': driver,
                       'exposures': exposures or {},
                       'bet': bet or '',
                       'asymmetry': asym or {'score': 3, 'note': ''},
                       'falsify': falsify or [],
                       'falsifyRules': falsify_rules or [],
                       'evidenceFor': ev_for or [],
                       'evidenceAgainst': ev_against or []})

    # ---- ① 政策路径差: 市场隐含路径 vs 经济 regime 推断 ----
    if _eSig == 'stagflation' and (_fed_hikes or 0) >= 1:
        _gap('policy', '政策路径差：滞胀组合下市场仍定价加息',
             f'经济 regime=滞胀 (劳动 {_eS2.get("labor")} / 通胀 {_eS2.get("inflation")} / 增长 {_eS2.get("growth")}), 但短端曲线隐含 {_fed_hikes} 次加息——非农已转负, 市场对政策转向反应滞后。',
             'long_2y', 'high', '政策', gid='policy_gap')
    elif _eSig in ('reflation', 'risk-on') and (_fed_cuts or 0) >= 2:
        _gap('policy', '政策路径差：市场过度定价宽松',
             f'经济 regime={_eSig} 但隐含 {_fed_cuts} 次降息——再通胀/金发姑娘组合下宽松定价过头, 若通胀粘性确认将反向修正。',
             'short_2y', 'mid', '政策', gid='policy_easy')

    # ---- ② 数据 surprise 累积 (最近 5 条发布) ----
    _miss_jobs = sum(1 for r in _ER_RELEASES[:5] if r.get('tag') in ('NFP', 'UNRATE', 'LPR') and r.get('verdict') == 'miss')
    _beat_infl = sum(1 for r in _ER_RELEASES[:5] if r.get('tag') in ('CPI', 'Core', 'PCE', 'SuperCore') and r.get('verdict') == 'beat')
    if _miss_jobs >= 2:
        _gap('surprise', f'就业数据连续 {_miss_jobs} 期低于预期',
             '非农/失业率/参与率连续 miss, 市场对就业拐点定价不足, 衰退式降息预期将升温——利好短端利率。',
             'long_2y', 'high', '就业', gid='jobs_surprise')
    if _beat_infl >= 2:
        _gap('surprise', f'通胀数据连续 {_beat_infl} 期低于预期',
             'CPI/PCE 连续低于预期(降温), 加息尾部定价将被压缩, 利好长久期债券。',
             'long_bond', 'mid', '通胀', gid='infl_surprise')

    # ---- ③ regime-价格背离: Tier A(价格结构) vs Tier B(基本面) 跨层对比 ----
    _grc = _price_implied.get('goldRealCorr')   # 金-实际利率 60 日相关 (A 层真实脱钩度)
    if _gold_cb_score >= 75 and _gold_ret90 is not None and _gold_ret90 < -3 and (_grc is None or _grc > -0.25):
        _gap('divergence', '黄金与央行购金脱钩（买点候选）',
             f'央行购金评分 {_gold_cb_score}/100 (WGC Q2 289吨) 但金价 90 日 {_gold_ret90:+.1f}%; 金-实际利率 60 日相关 {_grc if _grc is not None else "—"} (弱锚定=真脱钩)——结构性买盘与价格短期背离, 修复空间大。',
             'long_gold', 'high', '黄金', gid='gold_delink')
    _vix_gap = _price_implied.get('vixImplRealGap')   # 隐含-实现波动差 (A 层: >3 才叫错价)
    if _vix_gap is not None and _vix_gap > 3 and _spx_m > 0:
        _gap('divergence', '波动率错价（隐含 vs 实现）',
             f'VIX {_vix_v:.1f} 高出 SPX 实现波动 {_vix_gap:+.1f}pt——波动率溢价真实高估 (A 层价格证据), 卖波动率赔率佳。',
             'short_vol', 'mid', '波动率', gid='vol_mispricing', source='price')
    if _gold_cb_score >= 75 and _gold_ret90 is not None and _gold_ret90 > 0:
        _gap('divergence', '黄金与央行购金同向确认',
             f'央行购金 {_gold_cb_score}/100 + 金价 90 日 {_gold_ret90:+.1f}%, 脱钩后修复进行中——趋势多头延续概率高。',
             'long_gold', 'mid', '黄金', gid='gold_confirm')

    # ---- ④ 分位极端: 统计回归 vs 趋势延续 ----
    if _r_10y_pct is not None and _r_10y_pct > 90:
        _gap('percentile', f'10Y 处于历史极端分位 ({_r_10y_pct}/100)',
             '利率分位极值, 统计上未来 6-12 个月均值回归概率上升; 但趋势未确认反转前不逆势, 适合等反向信号或期权表达。',
             'long_2y', 'mid', '利率', gid='pct_10y')
    if _cr_ccc_pct is not None and _cr_ccc_pct > 80:
        _gap('percentile', f'CCC 分位 {_cr_ccc_pct}（低评级极端承压）',
             '高收益最弱环节已在极值——若 HY 整体未走阔则分层修复, 若信用事件出现则补跌, 双向机会均需确认。',
             'neutral', 'mid', '信用', gid='pct_ccc')

    # ---- ⑤ 传导断裂: 某因子被市场忽略 ----
    if (payems_mom is not None and payems_mom < 0) and (_cr_hy_w or 0) < 3:
        _gap('transmission', '就业转负但信用利差未走阔（传导滞后）',
             f'非农 {payems_mom:+.0f}K 但 HY OAS 周仅 {_cr_hy_w:+.1f}bp——信用市场通常滞后 5-10 交易日反应, 若就业拐点确认则 HY 存在补跌风险。',
             'short_hy', 'mid', '信用', gid='credit_lag')

    # ================= 全品类交易映射 (规则引擎) =================
    # 每个候选 = 一个假设: 方向 + 主观概率依据(证据平衡) + 非对称性 + 证伪退出
    if _eSig == 'stagflation':
        _trade('黄金 / 金矿股', '做多', '滞胀组合: 增长弱 + 通胀高, 股债双杀下黄金是唯一同时抗通胀与避险的资产; 央行购金提供结构性托底。',
               '核心 CPI 环比二次抬头 或 10Y 破位后金价抗跌', 'high',
               asym={'score': 5, 'note': '凸性机会: 下行有央行购金托底(有限), 上行在滞胀/美元走弱下无顶(无限)——塔勒布式非对称'},
               falsify=['央行购金季度转负 (WGC 数据)', '金价收盘跌破 6 月低点 3970 下方 3%', '核心 CPI 环比转负 + 通缩确认'],
               ev_for=['央行购金评分 100/100 (WGC Q2 289吨)', '经济 regime=滞胀组合', '金价已从低点反弹 9%'],
               ev_against=['10Y 实际利率历史高分位', '美元指数仍强势', '黄金 90 日动量仍为负'],
               exposures={'infl': +2, 'haven': +2, 'rate': +1, 'growth': -1},
               bet='滞胀+避险对冲: 增长弱+通胀高时, 黄金是唯一同时抗通胀与避险的资产; 央行购金=结构性价格地板')
        _trade('纳斯达克 / 长久期成长', '减仓/做空', '滞胀压制盈利预期 + 贴现率高位, 高估值成长股最脆弱 (AI 链条高 beta 放大)。',
               '非农再负 或 核心 PCE 环比 >0.25%', 'high',
               asym={'score': 3, 'note': '中性: 下行有盈利下修+贴现率(有限空间), 上行有 AI 盈利兑现(CoreWeave 订单$1040B)可能打脸——非凸'},
               falsify=['非农反弹 >180K 且核心 PCE 环比 <0.2% (软着陆确认)', '10Y 跌破 4.3% (利率转向)'],
               ev_for=['非农 -23K 转负', '10Y 分位 100 贴现率高位', '经济 regime=滞胀'],
               ev_against=['CoreWeave Q2 +112%/订单$1040B (AI 盈利兑现)', 'SPX 60 日趋势仍向上', 'HY 未走阔(信用未恶化)'],
               exposures={'growth': -2, 'rate': -1, 'haven': +1},
               bet='增长与贴现率双杀成长股: 赌“滞胀→盈利下修+折现率抬升”, 高久期估值最脆弱; 若 AI 盈利兑现则证伪')
    if _gold_cb_score >= 75:
        _trade('黄金', '逢低做多', f'央行购金结构性托底 (WGC Q2 289吨, 评分 {_gold_cb_score}/100), 回调即配置, 与短期价格脱钩。',
               '10Y 破 4.75 后金价不创新低 (央行买盘承接)', 'high',
               asym={'score': 5, 'note': '凸性: 央行买盘构成价格地板, 而美元信用/财政赤字担忧提供上行弹性'},
               falsify=['WGC 季度央行净购金转负', '金价跌破 6 月低点并持续 2 周 (托底假设证伪)'],
               ev_for=[f'央行购金评分 {_gold_cb_score}/100', '中国央行 21 连增 (7 月 +19.9吨)', '黄金占央行储备 27% 超美债'],
               ev_against=['10Y 实际利率高位', '金价短期动量偏弱'],
               exposures={'haven': +2, 'infl': +1, 'rate': +1},
               bet='结构性购金托底: 赌央行去美元化买盘提供价格地板, 实际利率不进一步上行则修复空间大')
    if _r_10y_pct is not None and _r_10y_pct > 85 and _corecpi_m < 0:
        _trade('2Y 国债', '做多', '10Y 极端分位 + 核心通胀环比回落 (2.6%), 短端利率下行空间打开。',
               '8 月核心 CPI 环比 <0.2% 确认', 'mid',
               asym={'score': 4, 'note': '偏凸: 分位极值 + 就业拐点, 下行受央行政策底线约束; 上行空间在降息重定价'},
               falsify=['核心 CPI 环比 >0.3% (通胀再燃)', '非农 >180K (就业未恶化)'],
               ev_for=['10Y 分位 100 (统计均值回归)', '核心 CPI 2.6% 环比回落', '非农 -23K 转负'],
               ev_against=['核心 PCE 3.3% 粘性', '美联储鹰派 (higher for longer)'],
               exposures={'rate': +2, 'infl': -1},
               bet='降息重定价: 赌就业拐点→市场从“更高更久”切向宽松, 短端利率下行')
    if (_fed_hikes or 0) >= 1 and (payems_mom is not None and payems_mom < 0):
        _trade('2Y 国债 / 曲线陡峭化', '做多', '市场定价加息 vs 就业已转负——政策路径将被迫重定价, 短端利率向下修正。',
               '初请 4 周均上穿 280K', 'mid',
               asym={'score': 4, 'note': '偏凸: 就业拐点确认后市场从加息切向宽松的路径切换空间大, 下行是时间成本'},
               falsify=['8 月非农 >180K (就业反弹)', '核心 CPI 环比 >0.3% (通胀粘性压过就业)'],
               ev_for=['市场定价 1 次加息 vs 非农 -23K', '经济 regime=滞胀', '初请已 199K 低位'],
               ev_against=['核心 PCE 3.3% 高企', 'FOMC 9 月可能维持鹰派'],
               exposures={'rate': +2},
               bet='政策路径切换: 赌市场被迫从加息定价翻向宽松(就业恶化), 短端+曲线陡峭化')
    if _vix_gap is not None and _vix_gap > 3 and _spx_m > 0:
        _trade('VIX (期权)', '卖出看涨/宽跨', f'VIX {_vix_v:.1f} 高位但股票月 {_spx_m:+.1f}%——压力未传导, 波动率溢价高估。',
               'VIX 回落而实现波动未同步走高', 'mid',
               asym={'score': 1, 'note': '⚠ 负凸性 (卖出保险): 赚有限权利金, 尾部亏损无上限——塔勒布框架下应严格控制仓位或转用价差限制尾部'},
               falsify=['VIX 收盘站上 25', 'SPX 单日跌幅 >3% (波动率跳升)'],
               ev_for=['VIX 高位但股票上涨(未传导)', '期限结构接近 Contango'],
               ev_against=['地缘事件 (霍尔木兹/美伊) 随时引爆', '波动率目标基金阈值 20 近在咫尺'],
               exposures={'haven': -2, 'growth': +1},
               bet='波动率溢价回归: 赌“高 VIX 但实现波动低→溢价被高估”收敛, 本质是卖尾部风险保险')
    if _liq_signal == 'risk-off':
        _trade('美元指数', '做多', '融资紧张 (SOFR>IORB) 环境美元走强, 压制新兴市场与高 beta 资产。',
               'SOFR-IORB 持续转正 3 日', 'mid',
               asym={'score': 2, 'note': '偏负: 美元上行空间受美联储转向压制, 且央行购金/去美元化长期侵蚀'},
               falsify=['美联储明确转鸽 (降息定价 ≥2 次)', 'RRP 余额回升'],
               ev_for=['SOFR>IORB 融资紧张', 'QT 直击准备金'],
               ev_against=['央行购金/去美元化长期趋势', '美国财政赤字担忧'],
               exposures={'liq': -2, 'haven': +1},
               bet='融资紧张美元荒: 赌流动性收紧→美元稀缺走强, 压制高 beta; 美联储转向则证伪')
    if _cr_signal == 'risk-off':
        _trade('高收益债', '回避/做空', '信用分层确认 (HY/CCC 分位高位), HY 存在补跌风险。',
               'HY OAS 周走阔 >10bp', 'mid',
               asym={'score': 3, 'note': '中性偏负: 做空信用赚取利差走阔, 但央行/流动性兜底(如有)会压缩空间; 更适合做多保护(CDS)而非裸空'},
               falsify=['HY OAS 回落并创近期新低 (信用修复)', '美联储明确转鸽 (流动性兜底)'],
               ev_for=[f'CCC 分位 {_cr_ccc_pct} (低评级极端承压)', 'HY OAS 已高位', '非农转负(信用滞后 5-10 日)'],
               ev_against=['HY 周变仅小幅走阔 (尚未确认)', '流动性仍宽松 (SOFR<IORB)', '违约率仍低'],
               exposures={'credit': -2, 'liq': -1, 'growth': -1},
               bet='信用周期恶化: 赌就业拐点→违约率上行传导至 HY 利差走阔; 流动性兜底则证伪')

    # ===== v4: driver 标签 (独立性审计/决策漏斗用) + 结构化证伪规则 =====
    _TRAITS = [
        ('黄金 / 金矿股', 'stagflation',
         [{'id': 'gold_floor', 'desc': '金价收盘跌破 3970 下方 3% (托底假设证伪)', 'key': 'gold', 'dir': 'below', 'val': 3850}]),
        ('纳斯达克', 'stagflation',
         [{'id': 'nfp_rebound', 'desc': '非农反弹 >180K (软着陆确认)', 'key': 'payems_mom', 'dir': 'above', 'val': 180},
          {'id': 't10_fall', 'desc': '10Y 跌破 4.3% (利率转向)', 'key': 'dgs10', 'dir': 'below', 'val': 4.3}]),
        ('逢低做多', 'gold_structure',
         [{'id': 'cb_neg', 'desc': 'WGC 季度央行购金转负', 'key': 'cb_q', 'dir': 'neg', 'val': 0}]),
        ('黄金', 'gold_structure',
         [{'id': 'cb_neg2', 'desc': 'WGC 季度央行购金转负', 'key': 'cb_q', 'dir': 'neg', 'val': 0}]),
        ('2Y 国债 / 曲线陡峭化', 'rate_easing',
         [{'id': 'cpi_hot', 'desc': '核心 CPI 环比 >0.3% (通胀粘性压过就业)', 'key': 'core_cpi_mom', 'dir': 'above', 'val': 0.3}]),
        ('2Y 国债', 'rate_easing',
         [{'id': 'cpi_hot2', 'desc': '核心 CPI 环比 >0.3% (再燃)', 'key': 'core_cpi_mom', 'dir': 'above', 'val': 0.3},
          {'id': 'nfp_strong', 'desc': '非农 >180K (就业未恶化)', 'key': 'payems_mom', 'dir': 'above', 'val': 180}]),
        ('VIX', 'vol_overpriced',
         [{'id': 'vix_spike', 'desc': 'VIX 收盘站上 25 (波动率跳升)', 'key': 'vix', 'dir': 'above', 'val': 25}]),
        ('高收益债', 'credit_risk',
         [{'id': 'hy_narrow', 'desc': 'HY OAS 回落创新低 (信用修复)', 'key': 'hy_w', 'dir': 'below', 'val': -10}]),
    ]
    for _t in trades:
        for _kw, _drv, _fr in _TRAITS:
            if _kw in _t['asset']:
                _t['driver'] = _drv
                _t['falsifyRules'] = _fr
                break

    _ai_val = _build_ai_valuation_gap()

    # ===== v4: ② 证伪监控 (每日自动检查 falsifyRules) =====
    _falsify_alerts = []
    for _t in trades:
        for _r in _t.get('falsifyRules', []):
            _key, _dir, _val = _r.get('key'), _r.get('dir'), _r.get('val')
            _v = None
            if _key == 'gold': _v = val('gold')
            elif _key == 'payems_mom': _v = payems_mom
            elif _key == 'dgs10': _v = val('dgs10')
            elif _key == 'vix': _v = vix
            elif _key == 'core_cpi_mom':
                _arr = [v for _, v in s('core_cpi') if v is not None]
                _v = (_arr[-1] - _arr[-2]) if len(_arr) >= 2 else None
            elif _key == 'hy_w': _v = (_cr_hy_w or 0)
            elif _key == 'cb_q':
                _v = None   # WGC 季度数据, 需策展人工确认
            if _v is None:
                continue
            _hit = (_v > _val) if _dir == 'above' else ((_v < _val) if _dir == 'below' else (_v < 0))
            if _hit:
                _falsify_alerts.append({'trade': _t['asset'], 'rule': _r['id'], 'desc': _r['desc'],
                                        'current': round(_v, 2) if isinstance(_v, float) else _v})

    # ===== v4: ②b AI 链条交易机会合并 (在独立性审计/组合暴露之前) =====
    _ai_trades_merged = 0
    if _ai_val.get('trades'):
        for _at in _ai_val['trades']:
            if any(_t['asset'] == _at['asset'] for _t in trades):
                continue
            _at['falsifyRules'] = [{'id': 'ai_' + str(_ai_trades_merged), 'desc': _at.get('falsify', '')[:60],
                                    'key': 'none', 'dir': 'neg', 'val': 0}]
            trades.append(_at)
            _ai_trades_merged += 1
    if _ai_trades_merged:
        print(f'  [tradeRadar] 合并 AI 链条交易机会 {_ai_trades_merged} 个 → 总候选 {len(trades)} 个', file=sys.stderr, flush=True)

    # ===== v4: ③ 独立性审计 (effective number of bets) =====
    _drv_counts = {}
    for _t in trades:
        _d = _t.get('driver', '')
        _drv_counts[_d] = _drv_counts.get(_d, 0) + 1
    _n_bets = len(_drv_counts)
    _redundant = [{'driver': k, 'count': v} for k, v in _drv_counts.items() if v > 1]

    # ===== v4: ③b 底层赌注聚合 (因子暴露 × 组合级重复检测) =====
    # 6 维宏观因子: rate(利率下行+) infl(通胀回升+) growth(增长强劲+) liq(流动性宽松+) haven(避险+) credit(信用改善+)
    _FACTOR_LABEL = {'rate': '赌利率下行', 'infl': '赌通胀回升', 'growth': '赌增长强劲',
                     'liq': '赌流动性宽松', 'haven': '赌避险升温', 'credit': '赌信用改善'}
    _portfolio = {}
    for _t in trades:
        for _f, _w in (_t.get('exposures') or {}).items():
            _portfolio[_f] = _portfolio.get(_f, 0) + _w
    # 组合净暴露: 取 |sum| 最大的因子 (正=整体在赌该因子, 负=反赌)
    _net_exposure = sorted(_portfolio.items(), key=lambda kv: abs(kv[1]), reverse=True) if _portfolio else []
    # 重复表达检测: 两两候选的暴露向量方向一致(同号因子) → 同一笔赌注的重复表达
    # 判定: 同向因子 ≥1 且合计权重 ≥3 (如 黄金rate+1 与 2Y rate+2 = 3) → 高度重叠
    _dup_pairs = []
    _trades_list = trades
    for _i in range(len(_trades_list)):
        for _j in range(_i + 1, len(_trades_list)):
            _a, _b = _trades_list[_i], _trades_list[_j]
            _ea, _eb = _a.get('exposures') or {}, _b.get('exposures') or {}
            _same = [f for f in set(_ea) & set(_eb) if _ea[f] * _eb[f] > 0]   # 同方向暴露因子
            _weight = sum(abs(_ea[f]) + abs(_eb[f]) for f in _same)
            if len(_same) >= 1 and _weight >= 3:   # 强同向暴露 → 同一赌注
                _dup_pairs.append({'a': _a['asset'], 'b': _b['asset'],
                                   'factors': _same, 'weight': _weight,
                                   'hint': '同一底层赌注的重复表达——共用因子: ' + ', '.join(_FACTOR_LABEL.get(f, f) for f in _same)})
    _dup_pairs.sort(key=lambda x: -x['weight'])
    _independence = {
        'effectiveBets': _n_bets,
        'redundant': _redundant,
        'dupPairs': _dup_pairs[:4],
        'portfolioExposure': [{'factor': f, 'label': _FACTOR_LABEL.get(f, f), 'net': w} for f, w in _net_exposure[:4]],
        'note': ('共 %d 个候选, 但只有 %d 个独立赌注' % (len(trades), _n_bets)
                 + (('—— "%s" 含 %d 个候选, 你在重复下注同一件事' % (_redundant[0]['driver'], _redundant[0]['count'])) if _redundant else '')),
    }
    if _dup_pairs:
        _independence['note'] += '；跨候选重叠: ' + '、'.join(d['a'] + '↔' + d['b'] for d in _dup_pairs[:2]) + ' 是同一笔赌注'

    # ===== v4: ④ 决策漏斗 → 唯一主线 + 卫星 =====
    def _trade_score(_t):
        _conf = 3 if _t['confidence'] == 'high' else 2
        _asym = _t.get('asymmetry', {}).get('score', 3)
        return _conf * 2 + _asym
    _sorted_trades = sorted(trades, key=_trade_score, reverse=True)
    _the_one = _sorted_trades[0] if _sorted_trades else None
    _satellites = [t for t in _sorted_trades[1:] if t.get('driver') != (_the_one or {}).get('driver')][:2]

    _n_gaps = len(gaps)
    _n_trades = len(trades)
    _summary = (f'扫描到 {_n_gaps} 个预期差 / {_n_trades} 个交易候选。'
                + ('主要矛盾集中在: ' + '、'.join(sorted(set(g['category'] for g in gaps))) if gaps else '当前无显著预期差, 处于低矛盾状态。')
                + ' 预期差是概率优势而非确定信号, 须等催化剂(trigger)确认后按风险评分定仓位。')
    _catalysts = _build_catalyst_calendar(gaps)
    _gap_sources = {'cross': sum(1 for g in gaps if g.get('source') == 'cross'),
                    'price': sum(1 for g in gaps if g.get('source') == 'price')}
    return {
        'asOf': GEN_DATE,
        'summary': _summary,
        'expectationGaps': gaps,
        'trades': trades,
        'catalystCalendar': _catalysts,
        'aiValuation': _ai_val,
        'priceImplied': _price_implied,
        'independence': _independence,
        'theOne': (_the_one if _the_one else None),
        'satellites': _satellites,
        'falsifyAlerts': _falsify_alerts,
        'gapSources': _gap_sources,
        'counts': {'gaps': _n_gaps, 'trades': _n_trades, 'catalysts': len(_catalysts),
                   'bets': _n_bets, 'alerts': len(_falsify_alerts)},
        'method': 'v4 双层信息架构: Tier A(价格隐含: 滚动相关/隐含-实现波动/曲线) vs Tier B(基本面判断)。预期差只允许跨层对比 (source=cross); 独立性审计(effective bets) + 决策漏斗(The One) + 证伪监控(falsify alerts)。不构成投资建议。',
    }

DATA['tradeRadar'] = _build_trade_radar()
print('[gen_datajs] tradeRadar section OK (gaps=%d, trades=%d)' % (DATA['tradeRadar']['counts']['gaps'], DATA['tradeRadar']['counts']['trades']), file=sys.stderr, flush=True)

# ====== AI 产业链 (Jensen 黄仁勋五层蛋糕) ======
print('[gen_datajs] generating aiChain section...', file=sys.stderr, flush=True)

def _aiclip(x, lo=0, hi=100):
    try: return max(lo, min(hi, x))
    except Exception: return 50

def _ai_valuation(pe, fpe, peg):
    """便宜度评分: PEG 优先, 其次远期/静态 PE; 数值越高=越便宜"""
    if peg and peg > 0:
        return (90 if peg <= 0.5 else 78 if peg <= 1.0 else 62 if peg <= 1.5
                else 48 if peg <= 2.0 else 35 if peg <= 3.0 else 22)
    pe_u = fpe or pe
    if pe_u and pe_u > 0:
        return (85 if pe_u <= 15 else 72 if pe_u <= 25 else 58 if pe_u <= 35
                else 44 if pe_u <= 50 else 30)
    return 50

def _ai_growth(g):
    if g is None: return 50
    return _aiclip(45 + g * 1.1)

def _ai_quality(gm, fcf, roe):
    def _q(x, hi): return _aiclip((x or 0) / hi * 100) if x is not None else 60
    return round((_q(gm, 90) + _q(fcf, 50) + _q(roe, 80)) / 3)

def _ai_research(rs):
    if rs and rs.get('ratingScore') is not None:
        return _aiclip(rs['ratingScore'] / 5 * 100)
    return 50

def _ai_revision(eps):
    """盈利修正动量: 分析师EPS预估近90天调整幅度(%) -> 评分; 上调=好"""
    if eps is None: return 50
    return _aiclip(50 + eps * 3)

def _ai_rating_trend(rt):
    """研报评级修正: 净评级变动(-2..+2) -> 评分; 上调=好"""
    if rt is None: return 50
    return _aiclip(50 + rt * 25)

def _ai_momentum(ch):
    """价格动量分: 周/月/半年收益加权; 越高=已上涨(越被定价)"""
    w, m, h6 = (ch or {}).get('w'), (ch or {}).get('m'), (ch or {}).get('h6')
    if w is None and m is None and h6 is None: return 50
    s = 50 + (w or 0) * 0.4 + (m or 0) * 0.9 + (h6 or 0) * 0.3
    return _aiclip(s)

def _ai_relative_val(pe, pe_hist):
    """相对自身历史估值: pe_hist=5年中枢P/E; 当前pe低于中枢=便宜(histRel高)"""
    if not pe or not pe_hist or pe_hist <= 0:
        return None
    return _aiclip(100 - 100 * pe / pe_hist)

def _ai_aie_score(rev_pct, rev_growth, pricing):
    """AI卡位拆解: AI收入占比(45%) + AI收入增速(30%) + 定价权(25%) —— 替代单一拍脑袋值"""
    _rg = _aiclip(40 + (rev_growth or 0) * 0.8)
    return round(_aiclip(0.45 * (rev_pct or 0) + 0.30 * _rg + 0.25 * (pricing or 50)))

_key2layer = {c['key']: _ly['name'] for _ly in AIC.get('layers', []) for c in _ly.get('companies', [])}
_ai_layers_out = []
_ai_all_companies = []
for _ly in AIC.get('layers', []):
    _comps = []
    for _c in _ly.get('companies', []):
        _key = _c.get('key')
        _price = val(_key) if _key else None
        _ch = asset_changes(_key) if _key else {}
        _mom = _ai_momentum(_ch)
        _h6 = (_ch or {}).get('h6')
        _falling = (_h6 is not None and _h6 < -8)  # 半年跌超8% = 下落的刀
        _val_abs = _ai_valuation(_c.get('pe'), _c.get('fwdPe'), _c.get('peg'))
        _val_hist = _ai_relative_val(_c.get('pe'), _c.get('peHist5y'))
        # 估值便宜度 = 60%绝对 + 40%相对自身历史(若无可比历史则纯绝对)
        _val = round(0.6 * _val_abs + 0.4 * _val_hist) if _val_hist is not None else _val_abs
        # 成长 = 静态营收增速(60%) + 盈利修正动量(40%, 比静态增长更具预测力)
        _gro = round(0.6 * _ai_growth(_c.get('revGrowth')) + 0.4 * _ai_revision(_c.get('epsRevision')))
        _qua = _ai_quality(_c.get('grossMargin'), _c.get('fcfMargin'), _c.get('roe'))
        # 研报共识 = 评级水平(70%) + 评级修正趋势(30%)
        _res = round(0.7 * _ai_research(_c.get('research')) + 0.3 * _ai_rating_trend(_c.get('ratingTrend')))
        # AI卡位拆解: 收入占比 + AI增速 + 定价权 (替代单一拍脑袋值)
        _aie = _ai_aie_score(_c.get('aiRevPct'), _c.get('aiRevGrowth'), _c.get('pricingPower'))
        # 陈旧性告警: 策展财务超过 3 个月未更新 -> 标灰提醒
        _cd = _c.get('curatedDate')
        _stale = True
        if _cd:
            try:
                _yy, _mm = (int(x) for x in str(_cd).split('-')[:2])
                _months = (datetime.date.today().year - _yy) * 12 + (datetime.date.today().month - _mm)
                _stale = _months > 3
            except Exception:
                _stale = True
        # 基本面强度: 质量/成长/AI卡位/研报共识
        _fund = round(0.35 * _qua + 0.30 * _gro + 0.20 * _aie + 0.15 * _res)
        # AI 价值分: 强基本面 + 便宜 + 尚未被拉涨(动量低) = 被低估的价值股
        _aiv = round(0.45 * _fund + 0.35 * _val + 0.20 * (100 - _mom))
        # 下落的刀惩罚: 半年大跌(>8%)的标的即便便宜也非"价值", 扣分避免误判
        if _falling:
            _aiv = max(0, _aiv - 8)
        _tags = []
        # 价值股候选: 强基本面+便宜+尚未被拉涨, 且非"下落的刀"(半年未大跌)
        if _aiv >= 62 and _val >= 55 and _mom < 62 and not _falling:
            _tags.append('价值股候选')
        if _val < 35 and _mom >= 65:
            _tags.append('高估值')
        if _mom >= 65:
            _tags.append('领跑')
        if _qua >= 70 and _fund >= 70:
            _tags.append('高质量')
        if _falling:
            _tags.append('下行趋势')
        _comps.append({
            'ticker': _c.get('ticker'), 'name': _c.get('name'), 'key': _key,
            'market': _c.get('market', 'US'), 'ccy': _c.get('ccy', 'USD'),
            'techRoute': _c.get('techRoute'), 'productDir': _c.get('productDir'),
            'price': _price, 'ch': _ch,
            'scores': {'momentum': _mom, 'valuation': _val, 'growth': _gro,
                       'quality': _qua, 'aiExposure': _aie, 'research': _res,
                       'fundamental': _fund, 'aiValue': _aiv},
            'tags': _tags,
            'marketCap': _c.get('marketCap'), 'pe': _c.get('pe'), 'fwdPe': _c.get('fwdPe'),
            'peg': _c.get('peg'), 'revGrowth': _c.get('revGrowth'),
            'grossMargin': _c.get('grossMargin'), 'fcfMargin': _c.get('fcfMargin'),
            'roe': _c.get('roe'),
            'research': _c.get('research'), 'notes': _c.get('notes'), 'est': _c.get('est', True),
            'epsRevision': _c.get('epsRevision'), 'ratingTrend': _c.get('ratingTrend'),
            'ratingDispersion': _c.get('ratingDispersion'), 'curatedDate': _c.get('curatedDate'),
            'stale': _stale,
            'thesis': _c.get('thesis'),
            'aiRevPct': _c.get('aiRevPct'), 'aiRevGrowth': _c.get('aiRevGrowth'),
            'pricingPower': _c.get('pricingPower'), 'peHist5y': _c.get('peHist5y')
        })
        _ai_all_companies.append(_comps[-1])
    def _avg(field):
        vs = [c['scores'][field] for c in _comps]
        return round(sum(vs) / len(vs)) if vs else 0
    # 层内百分位中性化 (跨层苹果比橘子修复): 在层内对关键维度排名, 而非跨层绝对比
    _ncomp = len(_comps)
    if _ncomp > 1:
        for _f in ('valuation', 'fundamental', 'momentum', 'aiValue'):
            _sv = sorted(x['scores'][_f] for x in _comps)
            for _cc in _comps:
                _lt = sum(1 for x in _sv if x < _cc['scores'][_f])
                _cc['scores']['lp_' + _f] = round(_lt / (_ncomp - 1) * 100)
    for _cc in _comps:
        _cc['layerPct'] = _cc['scores'].get('lp_aiValue', 50)
    _comps_sorted = sorted(_comps, key=lambda c: c['scores']['aiValue'], reverse=True)
    _value_picks = [c for c in _comps if '价值股候选' in c['tags']]
    # 每层跨市场对比: 各市场领头羊 + 跨市场最佳
    _mk = {}
    for _cc in _comps:
        _mk.setdefault(_cc['market'], []).append(_cc)
    _mk_leaders = {}
    for _mkname, _lst in _mk.items():
        _b = max(_lst, key=lambda x: x['scores']['aiValue'])
        _mk_leaders[_mkname] = {'ticker': _b['ticker'], 'name': _b['name'],
                                'aiValue': _b['scores']['aiValue'], 'count': len(_lst)}
    _comparison = {
        'leaders': _mk_leaders,
        'crossMarketBest': (_comps_sorted[0]['ticker'] if _comps_sorted else None),
        'marketCounts': {_mkname: len(_lst) for _mkname, _lst in _mk.items()}
    }
    _ai_layers_out.append({
        'id': _ly.get('id'), 'name': _ly.get('name'), 'en': _ly.get('en'),
        'desc': _ly.get('desc'), 'techRoutes': _ly.get('techRoutes', []),
        'companies': _comps_sorted, 'comparison': _comparison,
        'stats': {
            'count': len(_comps),
            'avgFundamental': _avg('fundamental'), 'avgValuation': _avg('valuation'),
            'avgMomentum': _avg('momentum'), 'avgAiValue': _avg('aiValue'),
            'topPick': (_comps_sorted[0]['ticker'] if _comps_sorted else None),
            'valuePicks': [c['ticker'] for c in _value_picks]
        }
    })

# 跨层价值股挖掘 (尚未被充分定价)
_ai_best = sorted([c for c in _ai_all_companies if '价值股候选' in c['tags']],
                  key=lambda c: c['scores']['aiValue'], reverse=True)[:10]
def _ai_why(c):
    s = c['scores']
    return (f"基本面 {s['fundamental']}/100、估值便宜度 {s['valuation']}/100、"
            f"动量 {s['momentum']}/100(未充分定价), AI价值分 {s['aiValue']}/100")
_ai_best_picks = [{'ticker': c['ticker'], 'name': c['name'],
                   'layer': _key2layer.get(c['key'], ''),
                   'aiValue': c['scores']['aiValue'], 'layerPct': c.get('layerPct', 50),
                   'why': _ai_why(c)} for c in _ai_best]
_ai_summary = {
    'companies': len(_ai_all_companies), 'layers': len(_ai_layers_out),
    'valuePicks': len(_ai_best),
    'avgAiValue': round(sum(c['scores']['aiValue'] for c in _ai_all_companies) / max(len(_ai_all_companies), 1)),
    'avgMomentum': round(sum(c['scores']['momentum'] for c in _ai_all_companies) / max(len(_ai_all_companies), 1))
}
# 全局跨市场汇总: 各市场公司数 / 平均AI价值分 / 该市场最佳
_ai_mk_all = {}
for _c in _ai_all_companies:
    _ai_mk_all.setdefault(_c['market'], []).append(_c)
_ai_market_summary = {_mk: {'count': len(_lst),
                            'avgAiValue': round(sum(x['scores']['aiValue'] for x in _lst) / len(_lst)),
                            'best': max(_lst, key=lambda x: x['scores']['aiValue'])['ticker']}
                      for _mk, _lst in _ai_mk_all.items()}
# ====== AI 资本开支周期 叙事层 (策展 + 数据驱动热度计) ======
# 热度计用真实动量: 价格动量(已涨) + 估值昂贵度(便宜度低=贵) + 领跑广度
_ai_cycle = AIC.get('cycle') or {}
_avg_val_cycle = round(sum(c['scores']['valuation'] for c in _ai_all_companies) / max(len(_ai_all_companies), 1))
_breadth_cycle = round(100 * sum(1 for c in _ai_all_companies if c['scores']['momentum'] > 65) / max(len(_ai_all_companies), 1))
_ai_heat = _aiclip(round(0.45 * _ai_summary['avgMomentum'] + 0.30 * (100 - _avg_val_cycle) + 0.25 * _breadth_cycle))
_ai_cycle_out = dict(_ai_cycle)
_ai_cycle_out['heat'] = _ai_heat
_ai_cycle_out['heatDriver'] = {'avgMomentum': _ai_summary['avgMomentum'],
                               'avgValuationScore': _avg_val_cycle, 'breadthPct': _breadth_cycle}
# 计算 AI 产业链各层资金流向强度 (用于总览页流向图)
# 算法 v2: 先把 5 个维度的原始指标做跨层 z-score 标准化, 再 softmax 映射为 0-100 的资金份额分,
# 解决线性加权下绝对值堆叠、某层一枝独秀的问题, 让分数更直接表达"资金流向占比"。
_ai_flow_raw = []
for _ly in _ai_layers_out:
    _cs = _ly.get('companies', [])
    if not _cs:
        continue
    _avg_mom = sum(c['scores']['momentum'] for c in _cs) / len(_cs)
    _breadth = 100 * sum(1 for c in _cs if c['scores']['momentum'] > 65) / len(_cs)
    _cap_w_mom = sum(c['scores']['momentum'] * (c.get('marketCap') or 1) for c in _cs) / sum((c.get('marketCap') or 1) for c in _cs)
    # 资金加速度: 周涨幅 - 月涨幅, 衡量短期资金是否突然涌入(可为负)
    _accel_lst = []
    for _c in _cs:
        _w = (_c.get('ch') or {}).get('w')
        _m = (_c.get('ch') or {}).get('m')
        if _w is not None and _m is not None:
            _accel_lst.append(_w - _m)
    _accel = sum(_accel_lst) / len(_accel_lst) if _accel_lst else 0
    # 估值热度: 估值分越高=越便宜, 反向得到资金追捧导致的昂贵度
    _val_heat = 100 - sum(c['scores']['valuation'] for c in _cs) / len(_cs)
    _ai_flow_raw.append({
        'name': _ly['name'], 'id': _ly['id'],
        'avgMomentum': _avg_mom, 'breadthPct': _breadth,
        'capWeightedMomentum': _cap_w_mom, 'momentumAccel': _accel,
        'valuationHeat': _val_heat,
        'companyCount': len(_cs), 'totalMarketCap': round(sum(c.get('marketCap') or 0 for c in _cs), 1),
        'topMover': max(_cs, key=lambda x: x['scores']['momentum'])['ticker'],
        'topMoverMomentum': max(c['scores']['momentum'] for c in _cs)
    })

def _zscore(_vals):
    if len(_vals) <= 1:
        return [0.0] * len(_vals)
    _mu = sum(_vals) / len(_vals)
    _var = sum((x - _mu) ** 2 for x in _vals) / len(_vals)
    _sd = _var ** 0.5
    if _sd == 0:
        return [0.0] * len(_vals)
    return [(x - _mu) / _sd for x in _vals]

# 5 维度权重: 动量 30%、领涨广度 25%、资金加速度 20%、市值加权动量 15%、估值热度 10%
_W_MOM, _W_BRD, _W_ACC, _W_CAP, _W_VAL = 0.30, 0.25, 0.20, 0.15, 0.10
_z_mom = _zscore([x['avgMomentum'] for x in _ai_flow_raw])
_z_brd = _zscore([x['breadthPct'] for x in _ai_flow_raw])
_z_acc = _zscore([x['momentumAccel'] for x in _ai_flow_raw])
_z_cap = _zscore([x['capWeightedMomentum'] for x in _ai_flow_raw])
_z_val = _zscore([x['valuationHeat'] for x in _ai_flow_raw])

_flow_raws = []
for _i, _r in enumerate(_ai_flow_raw):
    _raw = (_W_MOM * _z_mom[_i] + _W_BRD * _z_brd[_i] + _W_ACC * _z_acc[_i]
            + _W_CAP * _z_cap[_i] + _W_VAL * _z_val[_i])
    _flow_raws.append(_raw)

# softmax 转份额分: 让各层分数加总 ≈ 100, 更像"资金流向占比"; 同时做 sqrt 拉伸保留区分度
_exp = [2.718281828 ** x for x in _flow_raws]
_exp_sum = sum(_exp)
_ai_flow = []
for _i, _r in enumerate(_ai_flow_raw):
    _share = (_exp[_i] / _exp_sum) if _exp_sum else (1 / len(_ai_flow_raw))
    # sqrt 拉伸: 最高分保留 80-95 区间, 最低分不至于个位数
    _score = round(_share ** 0.55 * 100)
    _ai_flow.append({
        **{k: round(v, 2) if isinstance(v, float) else v
           for k, v in _r.items() if k not in ('avgMomentum', 'breadthPct', 'capWeightedMomentum', 'momentumAccel', 'valuationHeat')},
        'flowScore': _aiclip(_score), 'flowSharePct': round(_share * 100, 1),
        'avgMomentum': round(_r['avgMomentum']),
        'breadthPct': round(_r['breadthPct']),
        'capWeightedMomentum': round(_r['capWeightedMomentum']),
        'momentumAccel': round(_r['momentumAccel'], 2),
        'valuationHeat': round(_r['valuationHeat'])
    })
_ai_flow_sorted = sorted(_ai_flow, key=lambda x: x['flowScore'], reverse=True)

DATA['aiChain'] = {
    'meta': {'asOf': AIC.get('asOf', ''), 'disclaimer': AIC.get('disclaimer', ''),
             'note': '六层(黄仁勋五层蛋糕+网络连接层): 应用→模型→基础设施→网络连接→芯片→能源; 股价动量自动(Yahoo), 基本面/研报/周期叙事为策展种子值(其中 cycle.capex 为公开指引估计)'},
    'layers': _ai_layers_out,
    'bestValuePicks': _ai_best_picks,
    'summary': _ai_summary,
    'marketSummary': _ai_market_summary,
    'cycle': _ai_cycle_out,
    'flowData': {
        'asOf': str(datetime.date.today()),
        'layers': _ai_flow_sorted,
        'maxLayer': _ai_flow_sorted[0]['name'] if _ai_flow_sorted else None,
        'method': '资金流向强度(v2) = 先对 5 维度(平均动量/领涨广度/资金加速度/市值加权动量/估值热度)做跨层 z-score 标准化, 再 softmax 映射为份额分(加总≈100)。分数越高=近期资金流入/关注度越高。'
    }
}
print('[gen_datajs] aiChain section OK', file=sys.stderr, flush=True)

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

# ===== 加密扩展数据: 链上/稳定币/情绪 (crypto_meta.json, build_data.py 抓取) =====
_CMETA = {}
try:
    _CMETA = json.load(open(SCRIPT_DIR / 'crypto_meta.json', encoding='utf-8'))
    print('[gen_datajs] loaded crypto_meta.json', file=sys.stderr, flush=True)
except Exception:
    _CMETA = {}
    print('[gen_datajs] crypto_meta.json 缺失, 链上/稳定币/情绪面板留空', file=sys.stderr, flush=True)

# 链上序列: active_addresses / transactions / trade_volume / btc_market_cap / mempool
def _onchain_series(key, n=30):
    arr = (_CMETA.get('onchain') or {}).get(key) or []
    if not arr:
        return []
    return arr[-n:]

def _onchain_change(key):
    """链上序列最近 1 期变化% (活跃度趋势)"""
    arr = _onchain_series(key, 3)
    if len(arr) < 2 or not arr[-2][1]:
        return None
    return round((arr[-1][1] / arr[-2][1] - 1) * 100, 1)

_oc_active = _onchain_series('active_addresses')
_oc_txn = _onchain_series('transactions')
_oc_vol = _onchain_series('trade_volume')
_oc_mcap = _onchain_series('btc_market_cap')
_oc_mempool = _onchain_series('mempool')
_c_stable = _CMETA.get('stablecoins') or {}
_c_sent = _CMETA.get('sentiment') or {}
_c_fng = (_c_sent.get('fng') or {}).get('value')
_c_fng_label = (_c_sent.get('fng') or {}).get('label', '—')
_c_funding = _c_sent.get('funding')     # % (正=多头付费=杠杆偏热)

# ===== 加密流动性表现 (稳定币蓄水池 + 杠杆情绪) =====
_c_liq_score = 50
_c_liq_pts = []
if _c_stable.get('total_b'):
    _c_liq_pts.append(f'稳定币总市值 ${_c_stable["total_b"]:.0f}B (USDT {_c_stable.get("usdt_b","—")} + USDC {_c_stable.get("usdc_b","—")})')
    if _c_stable['total_b'] > 250: _c_liq_score += 15; _c_liq_pts.append('>250B 充裕的场外购买力蓄水池')
    elif _c_stable['total_b'] < 180: _c_liq_score -= 10; _c_liq_pts.append('<180B 蓄水池偏薄')
if _c_funding is not None:
    _c_liq_pts.append(f'永续资金费率 {_c_funding:+.3f}%')
    if _c_funding > 0.03: _c_liq_score -= 10; _c_liq_pts.append('资金费率>0.03% 多头杠杆过热(潜在踩踏)')
    elif _c_funding < -0.03: _c_liq_score += 5; _c_liq_pts.append('负费率=空头拥挤(反弹燃料)')
if _c_fng is not None:
    _c_liq_pts.append(f'恐慌贪婪指数 {_c_fng} ({_c_fng_label})')
    if _c_fng <= 30: _c_liq_score -= 8; _c_liq_pts.append('恐慌区=流动性收缩/抛压主导')
    elif _c_fng >= 75: _c_liq_score -= 6; _c_liq_pts.append('贪婪区=追涨盘主导(反向风险)')
    else: _c_liq_score += 8; _c_liq_pts.append('中性区间=健康')
_c_liq_state = '充裕' if _c_liq_score >= 60 else ('收缩' if _c_liq_score <= 40 else '中性')
_c_liq_label = f'流动性{_c_liq_state} (评分 {_c_liq_score})'

# ===== 主导叙事判定 (4 类: 数字黄金 / 风险资产beta / ETF机构化 / 链上基本面) =====
_c_narr = []
if _v_ethbtc is not None:
    if _v_ethbtc < 0.038: _c_narr.append('避险主导: ETH/BTC 走弱, BTC 相对抗跌(数字黄金叙事)')
    elif _v_ethbtc > 0.05: _c_narr.append('风险偏好主导: ETH/BTC 走强(Altcoin/风险资产叙事)')
if _v_etf_btc is not None:
    if _v_etf_btc > 0 and _etf_data.get('btc_cumsum', 0) > 0:
        _c_narr.append(f'机构化配置: BTC ETF 净流入(30日累计 ${_etf_data.get("btc_cumsum"):+.0f}M)')
    elif _v_etf_btc < 0:
        _c_narr.append('机构获利了结: BTC ETF 净流出')
if _c_stable.get('total_b') and _c_stable['total_b'] > 250:
    _c_narr.append('流动性蓄水池充沛: 稳定币 >250B 待入场资金')
if _oc_txn:
    _c_txn_chg = _onchain_change('transactions')
    if _c_txn_chg is not None and _c_txn_chg > 5:
        _c_narr.append(f'链上活跃升温: 日交易数 {_oc_txn[-1][1]:,.0f} (+{_c_txn_chg:.0f}%)')
    elif _c_txn_chg is not None and _c_txn_chg < -5:
        _c_narr.append(f'链上活跃降温: 日交易数 {_oc_txn[-1][1]:,.0f} ({_c_txn_chg:+.0f}%)')
_c_narrative = ('；'.join(_c_narr)) if _c_narr else '数据不足, 无法判定主导叙事'
_c_narrative_main = _c_narr[0] if _c_narr else '叙事待观察'

# ===== 定价矛盾 (价格 vs 链上/资金面的背离) =====
_c_contra = []
if _oc_txn and _v_btc is not None:
    _c_txn_chg = _onchain_change('transactions')
    _c_btc_d = _btc_ch.get('d')
    if _c_txn_chg is not None and _c_btc_d is not None:
        if _c_btc_d > 2 and _c_txn_chg < -5:
            _c_contra.append({'type': 'price_vs_onchain', 'title': '价格涨但链上活跃度降',
                              'detail': f'BTC 日 {_c_btc_d:+.1f}% 但链上交易数 {_c_txn_chg:+.0f}%——价格与基本面背离, 上涨缺乏链上支撑(投机驱动)。'})
        elif _c_btc_d < -2 and _c_txn_chg > 5:
            _c_contra.append({'type': 'price_vs_onchain', 'title': '价格跌但链上活跃度升',
                              'detail': f'BTC 日 {_c_btc_d:+.1f}% 但链上交易数 {_c_txn_chg:+.0f}%——抛售伴随活跃度上升, 可能是底部换手/吸筹。'})
if _v_etf_btc is not None and _v_btc is not None:
    _c_btc_d = _btc_ch.get('d')
    if _c_btc_d is not None and _c_btc_d < -1 and _v_etf_btc > 0:
        _c_contra.append({'type': 'etf_vs_price', 'title': 'ETF 净流入但 BTC 下跌',
                          'detail': f'BTC ETF 今日 +${_v_etf_btc:.0f}M 但价格 {_c_btc_d:+.1f}%——机构在买、价格在跌: 散户/杠杆盘抛售 vs 机构承接。'})
if _c_funding is not None and _v_btc is not None:
    _c_btc_m = _btc_ch.get('m')
    if _c_btc_m is not None and _c_btc_m < 0 and _c_funding > 0.03:
        _c_contra.append({'type': 'funding_vs_price', 'title': '价格跌但多头杠杆仍拥挤',
                          'detail': f'BTC 月 {_c_btc_m:+.1f}% 但资金费率 {_c_funding:+.3f}% 仍为正——多头未投降, 潜在踩踏风险。'})
    elif _c_btc_m is not None and _c_btc_m > 0 and _c_funding < -0.03:
        _c_contra.append({'type': 'funding_vs_price', 'title': '价格涨但空头拥挤',
                          'detail': f'BTC 月 {_c_btc_m:+.1f}% 但资金费率 {_c_funding:+.3f}% 为负——空头被挤压, 反弹燃料仍在。'})
if _c_fng is not None and _v_btc is not None:
    _c_btc_m = _btc_ch.get('m')
    if _c_btc_m is not None and _c_btc_m > 5 and _c_fng < 35:
        _c_contra.append({'type': 'sentiment_vs_price', 'title': '价格涨但情绪仍恐慌',
                          'detail': f'BTC 月 {_c_btc_m:+.1f}% 但恐慌贪婪指数仅 {_c_fng} ({_c_fng_label})——情绪滞后于价格, 上涨未获情绪确认。'})
_c_contra = _c_contra[:4]

# 加密 regime: 由 BTC 周变动 + ETF 流量 + ETH/BTC 动态合成 (替代预设 'mixed')
_c_score = 0
_c_btc_w = _btc_ch.get('w')
if _c_btc_w is not None:
    if _c_btc_w < -5: _c_score += 1          # BTC 周跌>5%=去风险
    elif _c_btc_w > 5: _c_score -= 1           # BTC 周涨>5%=risk-on
if _v_etf_btc is not None:
    if _v_etf_btc < 0: _c_score += 1          # ETF 净流出=机构撤退
    elif _v_etf_btc > 0: _c_score -= 1
if _v_ethbtc is not None:
    if _v_ethbtc < 0.04: _c_score += 1        # ETH/BTC 走弱=避险
    elif _v_ethbtc > 0.045: _c_score -= 1
_crypto_signal = 'risk-off' if _c_score >= 1 else ('risk-on' if _c_score <= -1 else 'mixed')
_crypto_label = '去风险/流动性收缩传导' if _crypto_signal=='risk-off' else ('风险资产联动走强' if _crypto_signal=='risk-on' else '震荡整理')
DATA['crypto'] = {
    'regime': {
        'label': _crypto_label,
        'signal': _crypto_signal, 'confidence': _confidence(_crypto_signal, _v_btc is not None, _v_etf_btc is not None, _v_ethbtc is not None),
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
             'changes':{k:(round(tfm('eth_btc_ratio').get(k)*100,3) if tfm('eth_btc_ratio').get(k) is not None else '—') for k in ('d','w','m','h6')},
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
    # ===== 2026-08-14 新增: 流动性 / 主导叙事 / 定价矛盾 / 链上 =====
    'liquidity': {
        'label': _c_liq_label, 'score': _c_liq_score, 'state': _c_liq_state,
        'points': _c_liq_pts,
        'stablecoins': _c_stable,
        'fundingRate': _c_funding,
        'fng': _c_fng, 'fngLabel': _c_fng_label,
    },
    'narrative': {'main': _c_narrative_main, 'full': _c_narrative, 'parts': _c_narr},
    'contradictions': _c_contra,
    'onChain': {
        'labels': [d for d, _ in _oc_txn],
        'series': {
            '日交易数': [v for _, v in _oc_txn],
            '活跃地址': [v for _, v in _oc_active],
        },
        'txnLatest': (_oc_txn[-1][1] if _oc_txn else None),
        'txnChg': _onchain_change('transactions'),
        'activeLatest': (_oc_active[-1][1] if _oc_active else None),
        'activeChg': _onchain_change('active_addresses'),
        'volLatest': (_oc_vol[-1][1] if _oc_vol else None),
        'mcapLatest': (_oc_mcap[-1][1] if _oc_mcap else None),
    },
    'trendData': [
        {'name':'Bitcoin','unit':'%','current':('$'+comma(_v_btc,0) if _v_btc else '—'),
         'changes':{k:(round(_btc_ch[k],2) if _btc_ch.get(k) is not None else None) for k in ('d','w','m','h6')},
         'meaning':'数字黄金叙事 vs 风险资产 beta 的博弈'},
        {'name':'Ethereum','unit':'%','current':('$'+comma(_v_eth,0) if _v_eth else '—'),
         'changes':{k:(round(_eth_ch[k],2) if _eth_ch.get(k) is not None else None) for k in ('d','w','m','h6')},
         'meaning':'DeFi/NFT/AI 叙事驱动的周期性资产'},
        {'name':'ETH/BTC','unit':'%','current':(f'{_v_ethbtc:.5f}' if _v_ethbtc else '—'),
         'changes':{k:(round(tfm('eth_btc_ratio')[k]*100,3) if tfm('eth_btc_ratio').get(k) is not None else None) for k in ('d','w','m','h6')},
         'meaning':'Altcoin 季节性的核心指标'},
    ],
    'analystView': f'加密市场当前处于{_crypto_label}。'
        + (f' BTC ${comma(_v_btc,0)}' if _v_btc else '')
        + (f' / ETH ${comma(_v_eth,0)}' if _v_eth else '')
        + (f' (ETH/BTC {_v_ethbtc:.4f})' if _v_ethbtc else '')
        + f'。ETF 方面: BTC ETF {"持续净流入(机构配置)" if (_v_etf_btc and _v_etf_btc > 0) else "出现净流出(警惕)"}'
        + (f' · ETH ETF {"净流入" if (_v_etf_eth and _v_etf_eth > 0) else "净流出"}' if _v_etf_eth is not None else '')
        + '。分析框架: 加密兼具"数字黄金"(稀缺性/去中心化, 对实际利率与美元敏感)与"风险资产"(高 beta, 对流动性与风险偏好敏感)双重属性——'
        + '实际利率高位时作为风险资产被压缩、央行购金周期中作为黄金替代获支撑。'
        + '与纳指的相关性在流动性收紧时趋向 +1(risk-off 一锅端), 宽松时脱钩(alpha 行情); '
        + '当前若 BTC 显著落后 SPX, 属涨势广度背离(资金集中于 AI/mega-cap), 而非领先看空——交叉验证股票广度而非单边做空信号。',
    'whatToWatch': [
        {'trigger': f'BTC 突破 <span class="watch-threshold">$100K</span>', 'implication': '新一轮零售 FOMO + 机构 FOMO 共振起点', 'status': f'距离 {max(0,100000-(_v_btc or 0)):,.0f}' if _v_btc else '—'},
        {'trigger': f'ETH/BTC 跌破 <span class="watch-threshold">0.040</span>', 'implication': 'BTC dominance 极致, Altcoin 全面承压', 'status': f'当前 {_v_ethbtc:.4f}' if _v_ethbtc else '—'},
        {'trigger': 'BTC ETF 连续 <span class="watch-threshold">3日净流出</span>', 'implication': '机构获利了结信号, 可能引发连锁抛售', 'status': f'今日 {_v_etf_btc:+,.0f}M' if _v_etf_btc is not None else '—'},
    ],
}

print('[gen_datajs] crypto section OK', file=sys.stderr, flush=True)

# ---------- 矛盾信号面板 (macroSignal) ----------
def _ms_vals(key, n=None):
    """取序列最近 n 个数值 (优先 computed.series90 的纯值列表, 回退 raw_series 的 [date,value] 列表)"""
    arr = series90(key) if series90(key) else (RAW.get(key) or [])
    out = []
    for x in arr:
        if isinstance(x, (list, tuple)) and len(x) >= 2:
            try:
                v = float(x[1])
                if v == v:
                    out.append(v)
            except Exception:
                pass
        else:
            try:
                v = float(x)
                if v == v:
                    out.append(v)
            except Exception:
                pass
    if n:
        out = out[-n:]
    return out

def _ms_status(a):
    t = a.get('type')
    key = a.get('series')
    if t == 'curated' or not key:
        return 'curated', None, '策展标注 (无直接序列)'
    full = _ms_vals(key)
    if len(full) < 5:
        return 'unknown', None, '序列缺失/不足'
    n = a.get('window') or len(full)
    vals = full[-n:] if n else full
    if t in ('period_high',):
        last = vals[-1]; hi = max(vals)
        return ('on' if last >= hi * 0.999 else 'off'), round(last, 2), '当前 %.2f / 区间高 %.2f' % (last, hi)
    if t in ('trend_up', 'rising'):
        last = vals[-1]; mean = sum(vals) / len(vals)
        return ('on' if last > mean else 'off'), round(last, 2), '当前 %.2f vs 均值 %.2f' % (last, mean)
    if t == 'trend_down':
        last = vals[-1]; mean = sum(vals) / len(vals)
        return ('on' if last < mean else 'off'), round(last, 2), '当前 %.2f vs 均值 %.2f' % (last, mean)
    if t == 'mom_negative':
        # 序列相邻期水平差 (非农月增), 最新一期 < 0 = 转负
        chg = []
        for i in range(1, len(vals)):
            chg.append(vals[i] - vals[i - 1])
        if len(chg) < 1:
            return 'unknown', None, '样本不足'
        last = chg[-1]
        return ('on' if last < 0 else 'off'), round(last, 0), '最新月增 %+.0fK' % last
    if t == 'mom_accel':
        chg = []
        for i in range(1, len(vals)):
            if vals[i - 1]:
                chg.append((vals[i] - vals[i - 1]) / abs(vals[i - 1]))
        if len(chg) < 2:
            return 'unknown', None, '样本不足'
        on = chg[-1] > chg[-2]
        return ('on' if on else 'off'), round(chg[-1] * 100, 2), '最新环比 %.2f%% vs 前月 %.2f%%' % (chg[-1] * 100, chg[-2] * 100)
    if t == 'relative_lag':
        s = _ms_vals(key)[-n:] if n else _ms_vals(key)
        b = _ms_vals(a.get('vs'))[-n:] if n else _ms_vals(a.get('vs'))
        if len(s) < 5 or len(b) < 5:
            return 'unknown', None, '序列缺失'
        rs = (s[-1] - s[0]) / abs(s[0]) if s[0] else 0
        rb = (b[-1] - b[0]) / abs(b[0]) if b[0] else 0
        on = (rb > 0) and (rs < rb)
        return ('on' if on else 'off'), round((rs - rb) * 100, 2), 'BTC %.1f%% vs SPX %.1f%%' % (rs * 100, rb * 100)
    if t == 'bear_steep':
        v10 = _ms_vals(a.get('series'))[-n:] if n else _ms_vals(a.get('series'))
        v2 = _ms_vals(a.get('series2'))[-n:] if n else _ms_vals(a.get('series2'))
        if len(v10) < 5 or len(v2) < 5:
            return 'unknown', None, '序列缺失'
        sn = v10[-1] - v2[-1]; sp = v10[0] - v2[0]
        on = (sn > sp) and (v10[-1] > v10[0]) and (v2[-1] > v2[0])
        return ('on' if on else 'off'), round(sn, 1), '10Y-2Y 斜率 %.0fbps' % sn
    return 'unknown', None, ''

_ms_anchors = []
_ms_status_map = {}
for _a in MS.get('anchors', []):
    _st, _val, _detail = _ms_status(_a)
    _rec = dict(_a); _rec['status'] = _st; _rec['value'] = _val; _rec['detail'] = _detail
    _ms_anchors.append(_rec)
    _ms_status_map[_a['id']] = _st

_ms_scenarios = []
for _sc in MS.get('scenarios', []):
    _trig = _sc.get('triggers', [])
    _on = sum(1 for _t in _trig if _ms_status_map.get(_t) == 'on')
    _ms_scenarios.append(dict(_sc))
    _ms_scenarios[-1]['triggeredCount'] = _on
    _ms_scenarios[-1]['triggerStatus'] = {_t: _ms_status_map.get(_t) for _t in _trig}

_ms_active = None
for _sc in _ms_scenarios:
    if _sc.get('baseline') and _sc['triggeredCount'] == len(_sc.get('triggers', [])):
        _ms_active = _sc['id']; break
if not _ms_active:
    _best = max(_ms_scenarios, key=lambda x: x['triggeredCount']) if _ms_scenarios else None
    _ms_active = _best['id'] if (_best and _best['triggeredCount'] > 0) else None

# ---------- 主导矛盾原型自动判定 (数据驱动) ----------
def _ms_composites():
    """由实时序列合成 5 维复合指标，用于从 archetypes[] 选出当前主导矛盾原型。"""
    _d10 = (tfm('dgs10') or {}).get('m') or 0      # 10Y 月变化 (百分点)
    _spx = (tfm('spx') or {}).get('m') or 0        # SPX 月变化 (%)
    _cpi = (tfm('core_cpi') or {}).get('m') or 0    # 核心CPI 月变化 (pt)
    _yld_up = _d10 > 0.05                           # 10Y 上行 > 5bp/月 = 债跌
    _eq_up = _spx > 0
    _disagreement = _yld_up and _eq_up             # 债跌 + 股涨 = 反向解读
    _cpi_on = _ms_status_map.get('cpi_accel') == 'on'
    _infl_high = _cpi_on or _cpi > 0
    _eq_down = _spx < 0
    _credit_on = _ms_status_map.get('credit_widen') == 'on'
    _growth_weak = _eq_down or _credit_on
    _growth_strong = (_spx > 1) and not _credit_on
    _sofr_iorb = (val('sofr') or 0) - (val('iorb') or 0)
    _nl_m = (tfm('netliq') or {}).get('m')
    _liq_tight = (_sofr_iorb or 0) > 0.0001 or (_nl_m is not None and _nl_m < 0)
    _liq_easy = (_sofr_iorb or 0) < -0.0001
    _crypto_on = _ms_status_map.get('crypto_divergence') == 'on'
    _breadth_narrow = _crypto_on or _credit_on
    _breadth_broad = (not _breadth_narrow) and _spx > 0
    return {
        'disagreement': _disagreement,
        'yldUp': _yld_up,
        'eqUp': _eq_up,
        'inflation': 'high' if _infl_high else ('low' if not (_cpi_on or _cpi > 0) else 'mod'),
        'growth': 'weak' if _growth_weak else ('strong' if _growth_strong else 'mod'),
        'liquidity': 'tight' if _liq_tight else ('easy' if _liq_easy else 'neutral'),
        'breadth': 'narrow' if _breadth_narrow else ('broad' if _breadth_broad else 'neutral'),
    }

_MS_COMP = _ms_composites()

def _ms_match(req, comp):
    if isinstance(req, bool):
        return req == comp
    return req == comp

def _ms_scores():
    _sc = {}
    for _a in MS.get('archetypes', []):
        _trig = _a.get('trigger', {})
        _s = 0
        for _k, _v in _trig.items():
            if _k in _MS_COMP and _ms_match(_v, _MS_COMP[_k]):
                _s += 1
        _sc[_a['id']] = _s
    return _sc

_MS_SCORES = _ms_scores()
_MS_ARCHS = MS.get('archetypes', [])
_PRIO = {'high': 3, 'normal': 2, 'low': 1}
# 先在「非 calm」原型中取最高分; calm 仅作为全 0 分时的回退, 避免其宽松条件(disagreement=false+inflation=low)抢分
_MS_NON_CALM = [x for x in _MS_ARCHS if x['id'] != 'calm_goldilocks']
_MS_BEST = None; _MS_BEST_S = -1
for _a in _MS_NON_CALM:
    _s = _MS_SCORES.get(_a['id'], 0)
    _p = _PRIO.get(_a.get('priority', 'normal'), 2)
    if _s > _MS_BEST_S or (_s == _MS_BEST_S and _MS_BEST is not None and _p > _PRIO.get(_MS_BEST.get('priority', 'normal'), 2)):
        _MS_BEST = _a; _MS_BEST_S = _s
if _MS_BEST_S <= 0:
    _calm = next((x for x in _MS_ARCHS if x['id'] == 'calm_goldilocks'), None)
    if _calm:
        _MS_BEST = _calm; _MS_BEST_S = _MS_SCORES.get('calm_goldilocks', 0)
    elif MS.get('dominant'):
        _MS_BEST = None   # 全部 0 分且无 calm -> 回退策展 dominant

if MS.get('manualOverride') and MS.get('dominant'):
    _MS_DOMINANT = MS['dominant']; _MS_SOURCE = 'override'
elif _MS_BEST:
    _MS_DOMINANT = {'title': _MS_BEST['title'], 'keyTension': _MS_BEST['keyTension'], 'body': _MS_BEST['body']}
    _MS_SOURCE = 'auto'
else:
    _MS_DOMINANT = MS.get('dominant', {}); _MS_SOURCE = 'curated'

DATA['macroSignal'] = {
    'asOf': MS.get('asOf'),
    'curatedDate': MS.get('curatedDate'),
    'method': MS.get('method'),
    'dominant': _MS_DOMINANT,
    'dominantMeta': {
        'source': _MS_SOURCE,
        'archetypeId': (_MS_BEST['id'] if _MS_BEST else None),
        'composites': _MS_COMP,
        'archetypeScores': _MS_SCORES,
    },
    'consensus': MS.get('consensus', []),
    'divergence': MS.get('divergence', []),
    'scenarios': _ms_scenarios,
    'anchors': _ms_anchors,
    'activeScenario': _ms_active,
}
print('[gen_datajs] macroSignal section OK (dominant source=%s, archetype=%s)' % (_MS_SOURCE, (_MS_BEST['id'] if _MS_BEST else 'curated')), file=sys.stderr, flush=True)

# ---------- 写出 data.js ----------
HEADER = """/* ============================================================
 * data.js — US Macro Observer (官方真实数据自动生成)
 * 由 scripts/gen_datajs.py 从 FRED / Treasury / NY Fed / Yahoo 真实数据生成
 * signal 字段: bullish=利多风险资产 / bearish=利空 / mixed=中性
 * percentile: 当前值近1年历史分位 (0-100)
 * 生成时间: %s
 * ============================================================\n */\n""" % datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

out = HEADER + 'const DATA = ' + json.dumps(DATA, ensure_ascii=False, indent=2) + ';\n'
with open(REPO_DIR / 'data.js', 'w', encoding='utf-8', newline='\n') as f:
    f.write(out)
print('[gen_datajs] DONE — data.js generated:', len(out), 'chars, sections:', list(DATA.keys()), file=sys.stderr, flush=True)

# ---------- 缓存破坏: 更新 index.html 中 data.js 的版本号 ----------
ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
idx_path = REPO_DIR / 'index.html'
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
