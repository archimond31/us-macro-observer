#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_signal_propose.py — 矛盾信号面板「策展层」定期维护辅助

用途
----
矛盾信号面板的骨架(锚点状态 / 情景激活 / 主导矛盾原型)已由 gen_datajs.py
实时自动计算；但以下策展字段仍需人工随市场演进刷新：
  - macro_signal.json 的 consensus[5] / divergence[5] 文案
  - archetypes[] 各原型 body 叙述
  - 必要时新增/退役锚点或原型

本脚本读取 scripts/ 下由 CI 生成的 computed.json + raw_series.json，
复用与 gen_datajs.py 完全一致的判定逻辑，打印一份「刷新草案报告」，
帮助你决定要改哪些文案、当前数据把主导矛盾判定成了哪个原型。

依赖
----
  - scripts/computed.json   (build_data.py + gen_datajs.py 产物, CI 已提交)
  - scripts/raw_series.json
  - scripts/macro_signal.json (你维护的策展源文件)
  本地执行前请先 `git pull` 拿到最新产物。

用法
----
  python scripts/macro_signal_propose.py
  python scripts/macro_signal_propose.py --write-draft   # 另写 macro_signal_draft.json
"""
import json
import sys
import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

def _load(name):
    p = SCRIPT_DIR / name
    if not p.exists():
        print('[propose] 缺少 %s (请先 git pull 拿 CI 产物)' % name, file=sys.stderr)
        sys.exit(1)
    return json.load(open(p, encoding='utf-8'))

C = _load('computed.json')
RAW = _load('raw_series.json')
MS = _load('macro_signal.json')

# ---------- 与 gen_datajs.py 保持一致的 helper ----------
def val(key):
    v = C.get(key)
    return v['value'] if v else None

def tfm(key):
    v = C.get(key)
    return v['tf'] if v else {'d': None, 'w': None, 'm': None, 'h6': None}

def series90(key):
    v = C.get(key)
    return v.get('series90', []) if v else []

def _ms_vals(key, n=None):
    arr = series90(key) if series90(key) else (RAW.get(key) or [])
    out = []
    for el in arr:
        try:
            v = float(el[1])
            if v == v:
                out.append(v)
        except Exception:
            pass
    return out[-n:] if n else out

def _ms_status(a):
    t = a.get('type'); key = a.get('series')
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

# 锚点状态
_status_map = {}
_anchors = []
for _a in MS.get('anchors', []):
    st, v, detail = _ms_status(_a)
    _status_map[_a['id']] = st
    _anchors.append(dict(_a, status=st, value=v, detail=detail))

# 复合指标 (与 gen_datajs._ms_composites 一致)
_d10 = (tfm('dgs10') or {}).get('m') or 0
_spx = (tfm('spx') or {}).get('m') or 0
_cpi = (tfm('core_cpi') or {}).get('m') or 0
_yld_up = _d10 > 0.05
_eq_up = _spx > 0
_disagreement = _yld_up and _eq_up
_cpi_on = _status_map.get('cpi_accel') == 'on'
_infl_high = _cpi_on or _cpi > 0
_eq_down = _spx < 0
_credit_on = _status_map.get('credit_widen') == 'on'
_growth_weak = _eq_down or _credit_on
_growth_strong = (_spx > 1) and not _credit_on
_sofr_iorb = (val('sofr') or 0) - (val('iorb') or 0)
_nl_m = (tfm('netliq') or {}).get('m')
_liq_tight = (_sofr_iorb or 0) > 0.0001 or (_nl_m is not None and _nl_m < 0)
_liq_easy = (_sofr_iorb or 0) < -0.0001
_crypto_on = _status_map.get('crypto_divergence') == 'on'
_breadth_narrow = _crypto_on or _credit_on
_breadth_broad = (not _breadth_narrow) and _spx > 0
COMPS = {
    'disagreement': _disagreement, 'yldUp': _yld_up, 'eqUp': _eq_up,
    'inflation': 'high' if _infl_high else ('low' if not (_cpi_on or _cpi > 0) else 'mod'),
    'growth': 'weak' if _growth_weak else ('strong' if _growth_strong else 'mod'),
    'liquidity': 'tight' if _liq_tight else ('easy' if _liq_easy else 'neutral'),
    'breadth': 'narrow' if _breadth_narrow else ('broad' if _breadth_broad else 'neutral'),
}

# 原型打分
def _match(req, comp):
    if isinstance(req, bool):
        return req == comp
    return req == comp
_scores = {}
for _a in MS.get('archetypes', []):
    s = 0
    for k, v in _a.get('trigger', {}).items():
        if k in COMPS and _match(v, COMPS[k]):
            s += 1
    _scores[_a['id']] = s
_PRIO = {'high': 3, 'normal': 2, 'low': 1}
# calm 仅作为全 0 分回退, 不参与主竞赛, 避免其宽松条件抢分
_NON_CALM = [x for x in MS.get('archetypes', []) if x['id'] != 'calm_goldilocks']
_best = None; _best_s = -1
for _a in _NON_CALM:
    s = _scores.get(_a['id'], 0); p = _PRIO.get(_a.get('priority', 'normal'), 2)
    if s > _best_s or (s == _best_s and _best is not None and p > _PRIO.get(_best.get('priority', 'normal'), 2)):
        _best = _a; _best_s = s
if _best_s <= 0:
    _calm = next((x for x in MS.get('archetypes', []) if x['id'] == 'calm_goldilocks'), None)
    if _calm:
        _best = _calm; _best_s = _scores.get('calm_goldilocks', 0)
    elif MS.get('dominant'):
        _best = None

# ---------- 输出报告 ----------
_today = datetime.date.today()
_suggest_asof = _today.isoformat()
_suggest_cd = '%04d-%02d' % (_today.year, _today.month)

print('=' * 64)
print(' 矛盾信号面板 · 策展层刷新草案')
print('=' * 64)
print('当前 curatedDate :', MS.get('curatedDate'), ' -> 建议:', _suggest_cd)
print('当前 asOf        :', MS.get('asOf'), ' -> 建议:', _suggest_asof)
print('manualOverride   :', MS.get('manualOverride'))
print('-' * 64)
print('【数据自动判定】主导矛盾原型 =', (_best['id'] if _best else '策展默认(dominant)'),
      ' (score=%d)' % _best_s)
if _best:
    print('   标题 :', _best.get('title'))
    print('   张力 :', _best.get('keyTension'))
print('-' * 64)
print('【复合指标维度】')
for k, v in COMPS.items():
    print('   %-12s %s' % (k, v))
print('-' * 64)
print('【各锚点实时状态】')
for a in _anchors:
    print('   %-18s %-8s %s' % (a['id'], a['status'], a.get('detail', '')))
print('-' * 64)
print('【原型得分】')
for _a in MS.get('archetypes', []):
    print('   %-18s score=%d  trigger=%s' % (_a['id'], _scores.get(_a['id'], 0), _a.get('trigger', {})))
print('-' * 64)
print('【待复核策展字段建议】')
_on = [a['id'] for a in _anchors if a['status'] == 'on']
print('   当前触发(on)的锚点:', ', '.join(_on) if _on else '(无)')
print('   → 请核对 divergence[] 中 anchor 挂在这些 id 的条目文案是否与当前状态一致')
print('   → 若市场进入新 regime 而现有 5 个原型都不贴切, 可在 archetypes[] 增删原型')
print('   → consensus[] 中「通胀是头号风险」等表述需与实际 COMPS.inflation 对齐')
if MS.get('manualOverride'):
    print('   ⚠ manualOverride=true: 面板当前强制使用 dominant 策展文案, 自动判定被压制')
else:
    print('   ✓ manualOverride=false: 面板由数据自动选原型, 你只需维护文案质量')
print('=' * 64)

# 可选: 写出草案
if '--write-draft' in sys.argv:
    draft = dict(MS)
    draft['asOf'] = _suggest_asof
    draft['curatedDate'] = _suggest_cd
    draft['_propose_note'] = '由 macro_signal_propose.py 于 %s 生成草案; 请人工复核后覆盖 macro_signal.json' % _suggest_asof
    outp = SCRIPT_DIR / 'macro_signal_draft.json'
    json.dump(draft, open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('[propose] 已写出草案:', outp)
