# -*- coding: utf-8 -*-
"""领先溢价的 walk-forward 回测（无前视）

问题：把「信用链 / 结构链领先于指数」的缺口转成 riskScore 溢价，是否真的有预测价值？
做法：
  1. 逐日重建三条压力序列（只用当日及之前的数据，分位用滚动 252 观测，无前视）
  2. 用 structure.lead_lag 算溢价
  3. 比较「溢价 > 0」与「溢价 = 0」两组的前瞻收益 / 前瞻最大回撤
  4. 对照组：把领先缺口打乱（shuffle）后同样计算，检验是否只是随机

用法：
  python scripts/backtest_leadlag.py --data scripts/raw_series.json --chain scripts/ai_chain.json
"""
import argparse
import bisect
import json
import math
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import structure as S

WINDOW = 252
HORIZONS = (5, 10, 20)


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def load_quality(chain_path):
    chain = load(chain_path)
    rows = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get('companies'), list):
                rows.extend(o['companies'])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(chain)
    q = {}
    for r in rows:
        k, roe = r.get('key'), r.get('roe')
        if k and roe is not None and k not in q:
            q[k] = float(roe)
    return q


def indexer(data):
    """key -> (dates[], values[])，供 bisect 切片。"""
    out = {}
    for k, rows in data.items():
        ds, vs = [], []
        for row in rows or []:
            if len(row) >= 2 and row[1] is not None:
                ds.append(row[0])
                vs.append(float(row[1]))
        if ds:
            out[k] = (ds, vs)
    return out


def slice_upto(idx, date_iso):
    """返回只含 <= date_iso 的 data 字典。"""
    out = {}
    for k, (ds, vs) in idx.items():
        j = bisect.bisect_right(ds, date_iso)
        if j:
            out[k] = list(zip(ds[:j], vs[:j]))
    return out


def pct_trailing(ds, vs, date_iso, window=WINDOW):
    j = bisect.bisect_right(ds, date_iso)
    if j < 30:
        return None
    cur = vs[j - 1]
    win = vs[max(0, j - window):j]
    return 100.0 * sum(1 for x in win if x <= cur) / len(win)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=os.path.join(os.path.dirname(__file__), 'raw_series.json'))
    ap.add_argument('--chain', default=os.path.join(os.path.dirname(__file__), 'ai_chain.json'))
    ap.add_argument('--shuffle', type=int, default=5, help='对照组打乱次数')
    a = ap.parse_args()

    data = load(a.data)
    quality = load_quality(a.chain)
    idx = indexer(data)
    # 基准序列：优先用长度足够的（spx 在缓存里常只有 1 年，spy 有 2 年）
    ref = None
    for cand in ('spy', 'spx'):
        if cand in idx and len(idx[cand][0]) > WINDOW + max(HORIZONS) + 10:
            ref = cand
            break
    if ref is None:
        for k, (ds, vs) in idx.items():
            if len(ds) > WINDOW + max(HORIZONS) + 10:
                ref = k
                break
    if ref is None:
        print('没有足够长的基准序列', file=sys.stderr)
        return 1
    print(f'基准序列: {ref}  ({len(idx[ref][0])} 观测)', file=sys.stderr)
    spx_d, spx_v = idx[ref]
    hy_d, hy_v = idx.get('hy', ([], []))
    cc_d, cc_v = idx.get('ccc', ([], []))

    rows = []
    for i in range(WINDOW, len(spx_d) - max(HORIZONS) - 1):
        d = spx_d[i]
        hy_pct = pct_trailing(hy_d, hy_v, d)
        cc_pct = pct_trailing(cc_d, cc_v, d)
        if hy_pct is None or cc_pct is None:
            continue
        credit_stress = 0.6 * hy_pct + 0.4 * cc_pct

        cut = slice_upto(idx, d)
        b = S.build_breadth(cut, quality)
        if not b.get('ok'):
            continue
        structure_stress = 100.0 - b['score']

        hi = max(spx_v[max(0, i - WINDOW):i + 1])
        dd = (hi - spx_v[i]) / hi * 100.0
        index_stress = max(0.0, min(100.0, dd / 15.0 * 100.0))

        ll = S.lead_lag(credit_stress, structure_stress, index_stress)
        rec = {'date': d, 'premium': ll['premium'], 'gap': ll['gap'],
               'state': ll['state'], 'credit': credit_stress,
               'structure': structure_stress, 'index': index_stress}
        for h in HORIZONS:
            if i + h < len(spx_v):
                rec[f'fwd{h}'] = (spx_v[i + h] / spx_v[i] - 1.0) * 100.0
                seg = spx_v[i:i + h + 1]
                rec[f'mdd{h}'] = (min(seg) / seg[0] - 1.0) * 100.0
        rows.append(rec)

    if not rows:
        print('样本不足', file=sys.stderr)
        return 1

    def corr(xs, ys):
        n = min(len(xs), len(ys))
        if n < 10:
            return 0.0
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs[:n], ys[:n]))
        vx = sum((x - mx) ** 2 for x in xs[:n])
        vy = sum((y - my) ** 2 for y in ys[:n])
        return cov / math.sqrt(vx * vy) if vx and vy else 0.0

    def summarize(rs, label):
        n = len(rs)
        out = [f'{label:<24} n={n:<4}']
        for h in HORIZONS:
            v = [r[f'fwd{h}'] for r in rs if f'fwd{h}' in r]
            dd = [r[f'mdd{h}'] for r in rs if f'mdd{h}' in r]
            if not v:
                continue
            avg = sum(v) / len(v)
            neg = 100.0 * sum(1 for x in v if x < 0) / len(v)
            mdd = sum(dd) / len(dd) if dd else 0.0
            out.append(f'{h}d 均值{avg:+.2f}% 下跌{neg:.0f}% 回撤{mdd:+.2f}%')
        return '  |  '.join(out)

    # ---- 溢价分布（先看有没有区分度）----
    prem_all = sorted(r['premium'] for r in rows)
    nz = [p for p in prem_all if p > 0]
    print('=' * 108)
    print('领先溢价 walk-forward 回测（无前视；分位为滚动 252 观测）')
    print('=' * 108)
    print(f'样本区间: {rows[0]["date"]} → {rows[-1]["date"]}   交易日 {len(rows)}   基准: {ref}')
    print(f'溢价分布: min={prem_all[0]:.1f}  p33={prem_all[len(prem_all)//3]:.1f}  '
          f'中位={prem_all[len(prem_all)//2]:.1f}  p67={prem_all[2*len(prem_all)//3]:.1f}  max={prem_all[-1]:.1f}')
    print(f'溢价>0 的天数: {len(nz)}/{len(rows)}  '
          f'（说明: 该区间指数持续走高、领先链持续偏弱, 溢价为常态正值而非事件信号）')
    print()

    # ---- 三分位分组 ----
    q33 = prem_all[len(prem_all) // 3]
    q67 = prem_all[2 * len(prem_all) // 3]
    lo = [r for r in rows if r['premium'] <= q33]
    mid = [r for r in rows if q33 < r['premium'] <= q67]
    hi = [r for r in rows if r['premium'] > q67]
    print(summarize(rows, '全样本'))
    print(summarize(lo, f'溢价低三分位 (≤{q33:.1f})'))
    print(summarize(mid, f'溢价中三分位'))
    print(summarize(hi, f'溢价高三分位 (>{q67:.1f})'))
    half = len(rows) // 2
    print()
    print(summarize(rows[:half], f'前半段 {rows[0]["date"]}→{rows[half]["date"]}'))
    print(summarize(rows[half:], f'后半段 {rows[half]["date"]}→{rows[-1]["date"]}'))
    print()

    print('溢价水平 vs 前瞻收益 相关（领先有效应为负）：')
    for h in HORIZONS:
        xs = [r['premium'] for r in rows if f'fwd{h}' in r]
        ys = [r[f'fwd{h}'] for r in rows if f'fwd{h}' in r]
        print(f'  {h:>2}d  corr = {corr(xs, ys):+.3f}')
    print()

    # ---- 置换检验: 高三分位 − 低三分位 的 20 日收益差 ----
    def spread_of(rs):
        p = sorted(r['premium'] for r in rs)
        a = p[len(p) // 3]; b = p[2 * len(p) // 3]
        g_hi = [r['fwd20'] for r in rs if r['premium'] > b and 'fwd20' in r]
        g_lo = [r['fwd20'] for r in rs if r['premium'] <= a and 'fwd20' in r]
        if not g_hi or not g_lo:
            return None
        return sum(g_hi) / len(g_hi) - sum(g_lo) / len(g_lo)

    base_rows = [r for r in rows if 'fwd20' in r]
    obs = spread_of(base_rows)
    rnd = random.Random(20261023)
    N_PERM = 500
    null = []
    if obs is not None:
        labels = [r['premium'] for r in base_rows]
        for _ in range(N_PERM):
            rnd.shuffle(labels)
            fake = [dict(r, premium=p) for r, p in zip(base_rows, labels)]
            s = spread_of(fake)
            if s is not None:
                null.append(s)
    print(f'置换检验（{N_PERM} 次）: 高三分位 − 低三分位 的 20 日收益差')
    if obs is None or not null:
        print('  样本不足, 无法检验')
    else:
        null.sort()
        pval = sum(1 for x in null if x <= obs) / len(null)   # 单尾: 高溢价组更差
        print(f'  实际观测差 = {obs:+.2f}%   (期望为负 = 领先有效)')
        print(f'  随机置换分布: 均值 {sum(null)/len(null):+.2f}%  p5 {null[int(0.05*len(null))]:+.2f}%  '
              f'p95 {null[int(0.95*len(null))]:+.2f}%')
        print(f'  单尾 p 值 = {pval:.3f}')
    print()

    # ---- 把关 1: 非重叠抽样（每 20 个交易日取一个），消除窗口重叠导致的显著性虚高 ----
    stride_rows = base_rows[::20]
    obs_s = spread_of(stride_rows)
    null_s = []
    if obs_s is not None and len(stride_rows) >= 15:
        labels = [r['premium'] for r in stride_rows]
        for _ in range(N_PERM):
            rnd.shuffle(labels)
            fake = [dict(r, premium=p) for r, p in zip(stride_rows, labels)]
            s = spread_of(fake)
            if s is not None:
                null_s.append(s)
    print(f'把关1 · 非重叠抽样（每 20 日取 1 个, n={len(stride_rows)}）:')
    if obs_s is None or len(null_s) < 50:
        print('  样本太少, 无法检验 → 视为未通过')
    else:
        null_s.sort()
        p_s = sum(1 for x in null_s if x <= obs_s) / len(null_s)
        print(f'  实际观测差 = {obs_s:+.2f}%   单尾 p = {p_s:.3f}   → '
              f'{"通过" if (obs_s < 0 and p_s < 0.10) else "未通过"}')
    print()

    # ---- 把关 2: 单调性 + 前后两段同向 ----
    def tercile_means(rs):
        p = sorted(r['premium'] for r in rs)
        if len(p) < 30:
            return None
        a, b = p[len(p) // 3], p[2 * len(p) // 3]
        g = {}
        for name, sel in (('lo', lambda x: x <= a), ('mid', lambda x: a < x <= b), ('hi', lambda x: x > b)):
            v = [r['fwd20'] for r in rs if sel(r['premium']) and 'fwd20' in r]
            g[name] = sum(v) / len(v) if v else None
        return g

    print('把关2 · 单调性与分段同向（20 日收益）:')
    for label, rs in (('全样本', base_rows), ('前半段', base_rows[:len(base_rows)//2]),
                      ('后半段', base_rows[len(base_rows)//2:])):
        g = tercile_means(rs)
        if not g or None in g.values():
            print(f'  {label}: 样本不足')
            continue
        mono = '单调递减✓' if (g['lo'] > g['mid'] > g['hi']) else '非单调✗'
        print(f'  {label}: 低{g["lo"]:+.2f}% 中{g["mid"]:+.2f}% 高{g["hi"]:+.2f}%  '
              f'高-低={g["hi"]-g["lo"]:+.2f}%  {mono}')
    print()

    print('判定标准（事先约定，防止事后找理由）：')
    print('  ① 高溢价三分位 20 日收益低于低三分位；② 全样本置换检验单尾 p < 0.10；')
    print('  ③ 非重叠抽样同向且 p < 0.10；④ 单调递减；⑤ 前后两段同向。')
    print('  五条全部满足才置 LEAD_PREMIUM_ENABLED=True，任一不过则保持 False。')
    print('  另注：前瞻窗口重叠, 有效独立样本远少于 n, 实际把握度应再打折。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
