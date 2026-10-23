# -*- coding: utf-8 -*-
"""结构面信号层 —— 结构广度 / 资本分配容忍度 / 信用-结构-指数 lead-lag

设计约束（与仓库既有约定一致）
1. 纯函数：不做网络或文件 I/O，便于本地用真实缓存数据验证；
2. 纯标准库：不引入 numpy/pandas；
3. 分位统一为「近 1 年 252 个观测」的经验分位，与 gen_datajs.pct() 同口径，
   避免长窗口带来窗口漂移；
4. 任何参数改动都须经 scripts/backtest_leadlag.py 的 walk-forward + 对照组验证，
   未通过不得默认开启（见 config 中的 *_ENABLED 开关）。

三个信号的分工
- build_breadth()      结构链：市场内部结构是否领先指数（新高新低/广度/质量）
- capital_allocation() 信用链子信号：资金对「扩张 vs 回报股东」的容忍度
- lead_lag()           把「信用 → 结构 → 指数」的先后次序转成风险评分的加权
"""

US_BREADTH_UNIVERSE = [
    'msft', 'crm', 'now', 'pltr', 'adbe', 'snow', 'googl', 'meta', 'amzn', 'orcl',
    'crwv', 'anet', 'vrt', 'dell', 'nvda', 'amd', 'avgo', 'tsm', 'arm', 'mrvl',
    'amat', 'asml', 'mu', 'cohr', 'lite', 'ceg', 'vst', 'nee', 'gev', 'tln',
    'ccj', 'oklo', 'etn',
]

# ---- 可审计参数（改动须回测）----
BREADTH_WEIGHTS = {'ma50': 0.40, 'adv20': 0.25, 'hl': 0.20, 'quality': 0.15}
CATI_WEIGHTS = {'ccc_hy': 0.40, 'bbb_ig': 0.20, 'cost': 0.20, 'bond_pnl': 0.20}

QUALITY_SPLIT_MAP = 2.5     # 质量多空价差(%p) → 分位映射斜率
HL_WINDOW = 252             # 52 周新高/新低窗口
CATI_WINDOW = 252           # 容忍度分位窗口
RET_WINDOW = 60             # 质量因子与债券盈亏的动量窗口

LEAD_THRESHOLD = 8.0        # 单链领先指数的门槛（分）
LEAD_STRONG = 25.0          # 强领先
LEAD_PREMIUM_W_CREDIT = 0.10     # 信用链领先缺口 → 溢价斜率（信用是更早的一环）
LEAD_PREMIUM_W_STRUCTURE = 0.06  # 结构链领先缺口 → 溢价斜率
LEAD_PREMIUM_CAP = 12.0     # 溢价上限（分）
LEAD_TILT_SLOPE = 0.25      # 缺口 → 权重迁移斜率
LEAD_TILT_CAP = 6.0         # 权重迁移上限（个百分点）

# 回测未通过前保持 False，接线处只计算不生效
LEAD_PREMIUM_ENABLED = False


# ------------------------------------------------------------------ helpers
def _series(data, key):
    """取 [(date, value)]，过滤 None。"""
    out = []
    for row in (data.get(key) or []):
        if len(row) >= 2 and row[1] is not None:
            out.append((row[0], float(row[1])))
    return out


def _pct(vals, v, window=CATI_WINDOW):
    """近 window 个观测的经验分位（0-100）。"""
    win = vals[-window:] if len(vals) > window else list(vals)
    if not win:
        return None
    return 100.0 * sum(1 for x in win if x <= v) / len(win)


def _sma_last(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / float(n)


def _chg(vals, n):
    if len(vals) <= n:
        return None
    prev = vals[-1 - n]
    if not prev:
        return None
    return (vals[-1] / prev - 1.0) * 100.0


def _aligned_pairs(data, a, b):
    """共同交易日上对齐两条序列。"""
    da = dict(_series(data, a))
    db = dict(_series(data, b))
    keys = sorted(set(da) & set(db))
    return [da[k] - db[k] for k in keys]


def _clip(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


# ------------------------------------------------------------------ 结构广度
def build_breadth(data, quality=None, universe=None):
    """结构广度：市场内部结构是否领先指数。

    返回 score 0-100（越高=结构越健康），四腿：
      ma50    —— 站上 50 日均线的比例
      adv20   —— 近 20 日上涨家数比例
      hl      —— 52 周新高/新低净家数（映射到 0-100）
      quality —— 高 ROE 三分位 vs 低 ROE 三分位的 60 日相对强弱
    """
    quality = quality or {}
    keys = [k for k in (universe or US_BREADTH_UNIVERSE) if _series(data, k)]
    n = len(keys)
    if n < 8:
        return {'ok': False, 'reason': f'可用标的仅 {n} 只, 不足 8 只', 'score': None,
                'legs': {}, 'n': n}

    above = adv = nh = nl = 0
    rets = {}
    for k in keys:
        vals = [v for _, v in _series(data, k)]
        if len(vals) < 55:
            continue
        sma = _sma_last(vals, 50)
        if sma and vals[-1] > sma:
            above += 1
        r20 = _chg(vals, 20)
        if r20 is not None and r20 > 0:
            adv += 1
        if len(vals) >= 120:
            w = min(HL_WINDOW, len(vals))
            win = vals[-w:]
            if vals[-1] >= max(win):
                nh += 1
            elif vals[-1] <= min(win):
                nl += 1
        r6 = _chg(vals, RET_WINDOW)
        if r6 is not None:
            rets[k] = r6

    pct_above = 100.0 * above / n
    pct_adv = 100.0 * adv / n
    hl_balance = (nh - nl) / float(n)
    hl_map = _clip(50.0 + 50.0 * hl_balance)

    # 质量腿：按 ROE 三分位做多空
    roe_map = {k: quality[k] for k in keys if quality.get(k) is not None and k in rets}
    quality_leg = None
    q_detail = {}
    if len(roe_map) >= 9:
        ordered = sorted(roe_map.items(), key=lambda kv: kv[1], reverse=True)
        cut = max(3, len(ordered) // 3)
        hi_names = [k for k, _ in ordered[:cut]]
        lo_names = [k for k, _ in ordered[-cut:]]
        hi_avg = sum(rets[k] for k in hi_names) / float(len(hi_names))
        lo_avg = sum(rets[k] for k in lo_names) / float(len(lo_names))
        spread = hi_avg - lo_avg
        quality_leg = _clip(50.0 + QUALITY_SPLIT_MAP * spread)
        q_detail = {'hi': [k for k in hi_names], 'lo': [k for k in lo_names],
                    'hi_ret': round(hi_avg, 2), 'lo_ret': round(lo_avg, 2),
                    'spread': round(spread, 2)}

    legs = {'ma50': pct_above, 'adv20': pct_adv, 'hl': hl_map, 'quality': quality_leg}
    used = {k: w for k, w in BREADTH_WEIGHTS.items() if legs.get(k) is not None}
    total_w = sum(used.values())
    score = sum(legs[k] * w for k, w in used.items()) / total_w if total_w else None

    if score is None:
        verdict = '样本不足'
    elif score >= 65:
        verdict = '结构健康——广度与质量同步确认指数'
    elif score >= 45:
        verdict = '结构中性——指数与内部结构基本同步'
    elif score >= 30:
        verdict = '结构转弱——指数强于内部结构, 广度未确认'
    else:
        verdict = '结构恶化——内部结构显著弱于指数, 指数上涨缺乏广度支撑'

    return {
        'ok': True, 'score': round(score, 1), 'verdict': verdict, 'n': n,
        'legs': {k: (round(v, 1) if v is not None else None) for k, v in legs.items()},
        'weights': {k: w for k, w in used.items()},
        'counts': {'above_ma50': above, 'adv20': adv, 'new_high': nh, 'new_low': nl,
                   'scored': len(rets)},
        'quality_detail': q_detail,
    }


# ------------------------------------------------------------------ 资本分配容忍度
def capital_allocation(data):
    """资本分配容忍度：资金对企业「扩张 vs 回报股东」的容忍还剩多少。

    返回 score 0-100（越高 = 容忍度越接近耗尽 / 压力越大），四腿：
      ccc_hy    —— CCC 与 HY 的分层利差（最弱信用被抛弃的程度）
      bbb_ig    —— BBB 与 IG 的利差（堕落天使压力）
      cost      —— 10Y 收益率分位（再融资成本）
      bond_pnl  —— LQD 60 日收益的分位取反（债券持有人已亏多少）
    """
    need = ['ccc', 'hy', 'bbb', 'ig', 'dgs10', 'lqd']
    missing = [k for k in need if not _series(data, k)]
    if missing:
        return {'ok': False, 'reason': f'缺少序列: {", ".join(missing)}', 'score': None, 'legs': {}}

    sp_cc = _aligned_pairs(data, 'ccc', 'hy')
    sp_bi = _aligned_pairs(data, 'bbb', 'ig')
    if len(sp_cc) < 30 or len(sp_bi) < 30:
        return {'ok': False, 'reason': '利差对齐样本不足', 'score': None, 'legs': {}}

    ccc_hy_pct = _pct(sp_cc, sp_cc[-1])
    bbb_ig_pct = _pct(sp_bi, sp_bi[-1])

    y = [v for _, v in _series(data, 'dgs10')]
    cost_pct = _pct(y, y[-1])

    lq = [v for _, v in _series(data, 'lqd')]
    roll = []
    for i in range(RET_WINDOW, len(lq)):
        if lq[i - RET_WINDOW]:
            roll.append((lq[i] / lq[i - RET_WINDOW] - 1.0) * 100.0)
    bond_pnl_pct = None
    if roll and len(roll) >= 30:
        cur = (lq[-1] / lq[-RET_WINDOW] - 1.0) * 100.0 if lq[-RET_WINDOW] else None
        if cur is not None:
            bond_pnl_pct = 100.0 - _pct(roll, cur)   # 亏得越多 → 压力越大

    legs = {'ccc_hy': ccc_hy_pct, 'bbb_ig': bbb_ig_pct, 'cost': cost_pct, 'bond_pnl': bond_pnl_pct}
    used = {k: w for k, w in CATI_WEIGHTS.items() if legs.get(k) is not None}
    total_w = sum(used.values())
    score = sum(legs[k] * w for k, w in used.items()) / total_w if total_w else None
    if score is None:
        return {'ok': False, 'reason': '分项全缺失', 'score': None, 'legs': {}}

    if score >= 70:
        band, verdict = '耗尽', '容忍度已耗尽——低评级被系统性重定价, 高评级几乎不动, 是典型的分层而非全面风险'
    elif score >= 50:
        band, verdict = '承压', '容忍度承压——资金开始要求更高补偿, 资本分配政策进入被审视区间'
    elif score >= 30:
        band, verdict = '中性', '容忍度中性——分层不显著'
    else:
        band, verdict = '宽容', '容忍度宽容——信用市场未对资本分配政策定价'

    return {
        'ok': True, 'score': round(score, 1), 'band': band, 'verdict': verdict,
        'legs': {k: (round(v, 1) if v is not None else None) for k, v in legs.items()},
        'weights': {k: w for k, w in used.items()},
        'raw': {
            'ccc_hy_bp': round(sp_cc[-1] * 100, 0),
            'ccc_hy_chg_1m_bp': round((sp_cc[-1] - sp_cc[-22]) * 100, 0) if len(sp_cc) > 22 else None,
            'bbb_ig_bp': round(sp_bi[-1] * 100, 0),
            'ust10y': round(y[-1], 2), 'lqd_60d_pct': round(cur, 2) if bond_pnl_pct is not None else None,
        },
    }


# ------------------------------------------------------------------ lead-lag
def lead_lag(credit_stress, structure_stress, index_stress):
    """把「信用 → 结构 → 指数」的先后次序转成风险评分的加权。

    两条领先链分别计算相对指数的领先缺口：
      credit_gap    = 信用压力 − 指数压力   （信用是最早的一环）
      structure_gap = 结构压力 − 指数压力   （市场结构是中间一环）
    任何一条领先链先恶化，即便指数未跌，riskScore 都应提前抬升——
    这就是「领先」在评分上的落地含义。信用链权重更高，因为它更早。
    """
    if None in (credit_stress, structure_stress, index_stress):
        return {'ok': False, 'reason': '因子缺失', 'premium': 0.0, 'tilt': 0.0,
                'state': 'unknown', 'note': ''}

    credit_gap = credit_stress - index_stress
    structure_gap = structure_stress - index_stress
    credit_vs_structure = credit_stress - structure_stress

    # 溢价：两条链各自超出指数的部分都要计入
    premium = _clip(LEAD_PREMIUM_W_CREDIT * max(0.0, credit_gap) +
                    LEAD_PREMIUM_W_STRUCTURE * max(0.0, structure_gap),
                    0.0, LEAD_PREMIUM_CAP)
    tilt = _clip(LEAD_TILT_SLOPE * max(credit_gap, structure_gap), 0.0, LEAD_TILT_CAP)

    if credit_gap >= LEAD_STRONG and structure_gap >= LEAD_STRONG and abs(credit_vs_structure) <= 8:
        state, label = 'both_lead', '双链同报·指数未确认'
    elif credit_gap >= LEAD_STRONG and credit_vs_structure >= 0:
        state, label = 'credit_leads_strong', '信用强领先·指数未确认'
    elif structure_gap >= LEAD_STRONG and credit_vs_structure < 0:
        state, label = 'structure_leads_strong', '结构强领先·指数未确认'
    elif credit_gap >= LEAD_THRESHOLD and credit_vs_structure > -5:
        state, label = 'credit_leads', '信用领先·指数未确认'
    elif structure_gap >= LEAD_THRESHOLD:
        state, label = 'structure_leads', '结构领先·指数未确认'
    elif index_stress > max(credit_stress, structure_stress) + LEAD_THRESHOLD:
        state, label = 'index_leads', '指数先行·领先链未确认'
    else:
        state, label = 'aligned', '三链基本同步'

    if state == 'both_lead':
        note = (f'信用链比指数早 {credit_gap:.0f} 分、结构链早 {structure_gap:.0f} 分同时报警, '
                f'而指数仍处高位——两条领先链都未获指数确认, 这是领先价值最高、也最容易被忽视的状态。'
                f'对应领先溢价 +{premium:.1f} 分。')
    elif state == 'credit_leads_strong':
        note = (f'信用链比指数早 {credit_gap:.0f} 分恶化, 结构链早 {structure_gap:.0f} 分——'
                f'两条领先链同时报警而指数尚未下跌, 对应领先溢价 +{premium:.1f} 分。')
    elif state == 'structure_leads_strong':
        note = (f'结构链比指数早 {structure_gap:.0f} 分恶化, 且比信用链还早 {abs(credit_vs_structure):.0f} 分——'
                f'广度/质量先于信用与指数转弱, 对应领先溢价 +{premium:.1f} 分。')
    elif state == 'credit_leads':
        note = (f'信用链比指数早 {credit_gap:.0f} 分恶化, 结构链早 {structure_gap:.0f} 分, '
                f'指数尚未跟上; 对应领先溢价 +{premium:.1f} 分。')
    elif state in ('structure_leads',):
        note = (f'结构链比指数早 {structure_gap:.0f} 分恶化（广度/质量不确认指数）, 信用链早 {credit_gap:.0f} 分; '
                f'指数仍在高位。结构是第二环, 先于指数但晚于信用, 对应领先溢价 +{premium:.1f} 分。')
    elif state == 'index_leads':
        note = (f'指数已先跌 {index_stress:.0f} 分, 而信用({credit_stress:.0f})与结构({structure_stress:.0f})未确认——'
                f'属于情绪性下跌, 领先链尚未补跌, 不构成领先信号。')
    else:
        note = (f'信用({credit_stress:.0f})、结构({structure_stress:.0f})、指数({index_stress:.0f})三链基本同步, '
                f'无显著领先缺口。')

    if premium > 0:
        note += ('（已计入总分）' if LEAD_PREMIUM_ENABLED
                 else '（未计入总分：回测未通过预设标准, 见 scripts/backtest_leadlag.py）')

    return {
        'ok': True, 'state': state, 'label': label,
        'gap': round(max(credit_gap, structure_gap), 1),
        'credit_gap': round(credit_gap, 1),
        'structure_gap': round(structure_gap, 1),
        'credit_vs_structure': round(credit_vs_structure, 1),
        'premium': round(premium, 1), 'tilt': round(tilt, 1),
        'credit_stress': round(credit_stress, 1),
        'structure_stress': round(structure_stress, 1),
        'index_stress': round(index_stress, 1),
        'enabled': LEAD_PREMIUM_ENABLED, 'note': note,
    }
