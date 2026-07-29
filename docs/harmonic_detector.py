# -*- coding: utf-8 -*-
"""
和谐交易形态信号识别模块 v2（可回测 / 可接实时行情）
=====================================================
流程：ZigZag 取点 -> XABC 结构校验 -> D点/PRZ 投影 -> 信号输出

输入：pandas DataFrame，列要求 ['open','high','low','close']（索引为时间）
输出：每个形态一个 dict（形态名、方向、PRZ 区间、止损、分批止盈、汇聚度）
"""

import numpy as np
import pandas as pd


# ==================================================================
# ★★★ 调参中心（所有可优化参数集中于此，改参数只动这里）★★★
# ==================================================================
# 每个参数标注：含义 / 取值范围 / 回测依据 / 何时需要调整
# ------------------------------------------------------------------

CONFIG = {
    # ---------------- 1. 摆动点提取（ZigZag）----------------
    # 反转确认阈值：价格反向移动该比例才确认一个摆动点。
    # 范围 0.02~0.06。越小摆动点越多、信号越多但噪音越大。
    # 回测依据：BTC 2年4H 网格 {0.03,0.04,0.05} × {tol} × {止损} 共36组，
    #   0.03 总收益最高(+54.2%)且样本外不衰减 → 定为默认。
    # 何时调大：日线/周线等大周期（0.05~0.08）；高波动品种(ZEC)可 0.04。
    "ZZ_PCT": 0.03,

    # ---------------- 2. 形态比例容差 ----------------
    # 斐波那契比率允许的偏离度，如 0.12 表示 0.618 可接受 0.544~0.692。
    # 范围 0.05~0.15。太严漏信号，太宽混入假形态。
    # 回测依据：BTC 上 0.12 > 0.10 > 0.08（总收益 54.2/36.8/39.0），
    #   加密市场插针多，需要较宽容差。股票市场建议收紧到 0.08。
    "TOL": 0.12,

    # ---------------- 3. 启用的形态库 ----------------
    # 回测依据：Shark 在 BTC/ETH/BNB 三个品种全部"高胜率(80%)但总亏损"
    #   （小赢大亏结构，BTC 46笔 -9.3%）→ 全局剔除。
    #   Butterfly/Gartley 是 BTC 盈利主力（+34.6/+18.4），
    #   ETH 上盈利主力是 Crab/DeepCrab —— 扩展新品种时先回测再启用。
    "PATTERNS": ["Gartley", "Bat", "Butterfly", "Crab", "DeepCrab"],

    # ---------------- 4. 止损设置 ----------------
    # ATR 周期：4H 级别固定 14 即可，不建议动。
    "ATR_PERIOD": 14,
    # 止损缓冲 = 该系数 × ATR，放在 PRZ 外侧。
    # 范围 0.3~1.0。回测依据：BTC 网格 0.3/0.5/0.7/1.0 中 0.7 最优；
    #   0.7 与 1.0 差距不大(54.2 vs 50.3)，高波动品种可用 1.0。
    "STOP_ATR_BUF": 0.7,
    # calc_entry 未传 atr 时的兜底：腿幅 × 该系数
    "STOP_FALLBACK_XA": 0.05,

    # ---------------- 5. 止盈设置 ----------------
    # 分批止盈：AD 腿的 0.382 / 0.618 回撤位，TP1 平一半、TP2 全平。
    # 教科书标准值，回测中未做网格（改动会改变整个持仓管理逻辑，慎动）。
    "TP1_RATIO": 0.382,
    "TP2_RATIO": 0.618,

    # ---------------- 6. 信号质量分级 ----------------
    # PRZ 汇聚宽度（三投影点离散度）分级阈值。
    # 回测依据：BTC 上宽度 1~2% 单笔期望 +2.35%，>4% 仅 +0.19%。
    # 用法：width<PRZ_A 为 A级正常仓，<PRZ_B 为 B级减半，>=PRZ_B 放弃。
    "PRZ_GRADE_A": 0.02,
    "PRZ_GRADE_B": 0.04,

    # ---------------- 7. 回测专属（backtest.py 读取）----------------
    "BT_FEE": 0.0005,        # 单边手续费率（合约 taker 约 0.05%）
    "BT_SLIPPAGE": 0.0005,   # 单边滑点估计
    "BT_SIGNAL_TTL": 40,     # 信号有效期（根K线）：XABC确认后等价格走入PRZ的耐心
    "BT_MAX_HOLD": 60,       # 持仓超时强制平仓（根K线，4H下=10天）
    "BT_COOLDOWN": 2,        # 同结构信号冷却（根K线），防密集重复挂单
}
# ==================================================================


# ------------------------------------------------------------------
# 0. ATR 辅助（复盘新增：此前每次在内联重复计算，统一到模块）
# ------------------------------------------------------------------
def atr(df: pd.DataFrame, period: int = None) -> pd.Series:
    """Wilder 式 ATR（简单滚动均值版）。period 默认取 CONFIG['ATR_PERIOD']。"""
    period = period or CONFIG['ATR_PERIOD']
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                   axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ------------------------------------------------------------------
# 1. ZigZag 摆动点提取
# ------------------------------------------------------------------
def zigzag(df: pd.DataFrame, pct: float = 0.03) -> pd.DataFrame:
    """
    基于百分比反转阈值的 ZigZag。
    pct: 反转确认阈值，如 0.03 表示价格反向移动 3% 才确认一个摆动点。
         4H/日线建议 0.03~0.05；BTC 可用 0.04 起步再调。
    返回 DataFrame: ['idx'(bar序号), 'price', 'type'('H'高点/'L'低点)]
    """
    highs, lows = df["high"].values, df["low"].values
    n = len(df)
    if n < 6:
        return pd.DataFrame(columns=["idx", "price", "type"])

    pivots = []          # [(idx, price, 'H'/'L')] 严格交替
    trend = None         # 'up' 找高点 / 'down' 找低点
    ext_idx, ext_price = 0, df["close"].iloc[0]  # 当前段极值

    for i in range(1, n):
        h, l = highs[i], lows[i]
        if trend is None:
            # 尚未确立方向：追踪首个超过阈值的单边运动
            if h >= ext_price * (1 + pct):
                # 从起点上涨 -> 起点记为 L，转入找高点
                pivots.append((ext_idx, ext_price, "L"))
                trend, ext_idx, ext_price = "up", i, h
            elif l <= ext_price * (1 - pct):
                pivots.append((ext_idx, ext_price, "H"))
                trend, ext_idx, ext_price = "down", i, l
            else:
                # 区间内波动，更新起点为更极端值
                if l < ext_price:
                    ext_idx, ext_price = i, l
        elif trend == "up":
            if h >= ext_price:
                ext_idx, ext_price = i, h
            elif l <= ext_price * (1 - pct):
                pivots.append((ext_idx, ext_price, "H"))
                trend, ext_idx, ext_price = "down", i, l
        else:  # down
            if l <= ext_price:
                ext_idx, ext_price = i, l
            elif h >= ext_price * (1 + pct):
                pivots.append((ext_idx, ext_price, "L"))
                trend, ext_idx, ext_price = "up", i, h

    # 收尾：当前段未确认的极值也保留（实盘里它可能就是正在形成的 D 点）
    if trend == "up":
        pivots.append((ext_idx, ext_price, "H"))
    elif trend == "down":
        pivots.append((ext_idx, ext_price, "L"))

    zz = pd.DataFrame(pivots, columns=["idx", "price", "type"])
    # 保证 H/L 严格交替
    zz = zz[zz["type"] != zz["type"].shift()].reset_index(drop=True)
    return zz


# ------------------------------------------------------------------
# 2. 形态定义库（比率区间 = 理想值 ± 容差）
# ------------------------------------------------------------------
# 每个形态定义四条腿的比例约束：
#   B/XA : B 点相对 XA 腿的回撤
#   C/AB : C 点相对 AB 腿的回撤
#   D/XA : D 点相对 XA 腿的回撤(含延伸>1)   —— PRZ 核心度量之一
#   CD/BC: CD 腿相对 BC 腿的投影           —— PRZ 核心度量之二
PATTERNS = {
    "Gartley":   {"B/XA": (0.618, 0.618), "C/AB": (0.382, 0.886),
                  "D/XA": (0.786, 0.786), "CD/BC": (1.272, 1.618)},
    "Bat":       {"B/XA": (0.382, 0.50),  "C/AB": (0.382, 0.886),
                  "D/XA": (0.886, 0.886), "CD/BC": (1.618, 2.618)},
    "Butterfly": {"B/XA": (0.786, 0.786), "C/AB": (0.382, 0.886),
                  "D/XA": (1.272, 1.618), "CD/BC": (1.618, 2.24)},
    "Crab":      {"B/XA": (0.382, 0.618), "C/AB": (0.382, 0.886),
                  "D/XA": (1.618, 1.618), "CD/BC": (2.24, 3.618)},
    "DeepCrab":  {"B/XA": (0.886, 0.886), "C/AB": (0.382, 0.886),
                  "D/XA": (1.618, 1.618), "CD/BC": (2.0, 3.618)},
    "Shark":     {"B/XA": (0.382, 0.618), "C/AB": (1.13, 1.618),
                  "D/XA": (0.886, 1.13),  "CD/BC": (1.618, 2.24)},
}


def _in_range(ratio, lo, hi, tol):
    return lo * (1 - tol) <= ratio <= hi * (1 + tol)


# ------------------------------------------------------------------
# 3. 五点位校验 + PRZ 计算
# ------------------------------------------------------------------
def validate_pattern(X, A, B, C, D, name, tol=None):
    tol = tol if tol is not None else CONFIG['TOL']
    """
    五点均为 (idx, price)。 bullish: X低A高B低C高D低；bearish 反之。
    返回 dict 或 None。
    """
    spec = PATTERNS[name]
    xp, ap, bp, cp, dp = X[1], A[1], B[1], C[1], D[1]

    bullish = ap > xp
    xa = abs(ap - xp)
    ab = abs(bp - ap)
    bc = abs(cp - bp)
    cd = abs(dp - cp)
    if xa == 0 or ab == 0 or bc == 0:
        return None

    # 方向结构校验
    if bullish and not (bp < ap and cp > bp and dp < cp):
        return None
    if not bullish and not (bp > ap and cp < bp and dp > cp):
        return None

    r_BXA = ab / xa
    r_CAB = bc / ab
    r_DXA = (abs(ap - dp) / xa)
    r_CDBC = cd / bc

    if not _in_range(r_BXA, *spec["B/XA"], tol):
        return None
    if not _in_range(r_CAB, *spec["C/AB"], tol):
        return None
    if not _in_range(r_DXA, *spec["D/XA"], tol):
        return None
    if not _in_range(r_CDBC, *spec["CD/BC"], tol):
        return None

    # ---- PRZ 计算：多个度量的汇聚区间 ----
    # 度量1: XA 的目标回撤/延伸位（取区间端点）
    if bullish:
        m1 = [ap - xa * spec["D/XA"][0], ap - xa * spec["D/XA"][1]]
        # 度量2: BC 投影（从 C 点向下投影 CD/BC 区间）
        m2 = [cp - bc * spec["CD/BC"][1], cp - bc * spec["CD/BC"][0]]
    else:
        m1 = [ap + xa * spec["D/XA"][0], ap + xa * spec["D/XA"][1]]
        m2 = [cp + bc * spec["CD/BC"][0], cp + bc * spec["CD/BC"][1]]

    prz_lo = max(min(m1), min(m2))
    prz_hi = min(max(m1), max(m2))
    if prz_lo > prz_hi:  # 两个度量不重叠 -> 退化为并集的外包区间
        prz_lo, prz_hi = min(min(m1), min(m2)), max(max(m1), max(m2))

    # ---- 止损：PRZ 外侧 + 0.5 个形态腿幅缓冲（也可用 ATR）----
    buf = 0.5 * xa * 0.1
    if bullish:
        stop = prz_lo - buf
        tp1 = dp + (ap - dp) * CONFIG['TP1_RATIO']
        tp2 = dp + (ap - dp) * CONFIG['TP2_RATIO']
    else:
        stop = prz_hi + buf
        tp1 = dp - (dp - ap) * CONFIG['TP1_RATIO']
        tp2 = dp - (dp - ap) * CONFIG['TP2_RATIO']

    risk = abs(dp - stop)
    return {
        "pattern": name,
        "direction": "bullish" if bullish else "bearish",
        "X": X, "A": A, "B": B, "C": C, "D": D,
        "ratios": {"B/XA": round(r_BXA, 3), "C/AB": round(r_CAB, 3),
                   "D/XA": round(r_DXA, 3), "CD/BC": round(r_CDBC, 3)},
        "PRZ": (round(prz_lo, 4), round(prz_hi, 4)),
        "entry_ref": dp,
        "stop": round(stop, 4),
        "tp1": round(tp1, 4),
        "tp2": round(tp2, 4),
        "rr_tp1": round(abs(tp1 - dp) / risk, 2) if risk else None,
        "rr_tp2": round(abs(tp2 - dp) / risk, 2) if risk else None,
    }


# ------------------------------------------------------------------
# 4. 主扫描入口
# ------------------------------------------------------------------
def scan(df: pd.DataFrame, zz_pct=None, tol=None,
         patterns=None, only_latest: bool = True) -> list:
    """
    扫描全部 XABCD 组合（ZigZag 相邻五点滑动窗口）。
    only_latest=True 时只返回 D 点为最近摆动点的信号（实盘用）。
    """
    zz_pct = zz_pct if zz_pct is not None else CONFIG['ZZ_PCT']
    tol = tol if tol is not None else CONFIG['TOL']
    zz = zigzag(df, pct=zz_pct)
    signals = []
    if len(zz) < 5:
        return signals

    names = patterns or CONFIG['PATTERNS']
    pts = [(int(r.idx), float(r.price)) for r in zz.itertuples()]
    n = len(pts)
    start = n - 1 if only_latest else 4

    for i in range(start, n):
        X, A, B, C, D = pts[i - 4:i + 1]
        for name in names:
            sig = validate_pattern(X, A, B, C, D, name, tol=tol)
            if sig:
                sig["D_time"] = str(df.index[D[0]]) if hasattr(df.index, "strftime") else D[0]
                signals.append(sig)
    return signals


# ------------------------------------------------------------------
# 4.5 宏观方向层：日线 EMA200 偏离度 -> 仓位系数建议
# ------------------------------------------------------------------
# 回测依据（BTC两年4H）：和谐信号本质是均值回归，逆EMA200的信号
# 总收益(+45.8%)反而高于顺势(+17.3%)——所以EMA200不做入场过滤，
# 只用于仓位权重和持仓管理：
#   顺势信号(与EMA200同向): 系数1.0，可拿波段
#   逆势信号: 系数0.6，到TP就走
#   极端乖离(>20%)时的逆势信号: 系数1.2（牛市顶/熊市底反转概率最高，
#     回测中牛市环境逆势做空胜率84.2%）
# ------------------------------------------------------------------
def macro_bias(daily_close: pd.Series, signal_dir: int = 1) -> dict:
    """
    参数:
        daily_close: 日线收盘价 Series（需 >=210 根）
        signal_dir : 1 做多 / -1 做空
    返回: ema200、乖离率、斜率、与信号的关系、仓位系数、持仓建议
    """
    if daily_close is None or len(daily_close) < 210:
        return {"macro": "数据不足(<210根日K)", "size_mult": 0.8}
    e200 = daily_close.ewm(span=200, adjust=False).mean()
    e50 = daily_close.ewm(span=50, adjust=False).mean()
    p, v200, v50 = daily_close.iloc[-1], e200.iloc[-1], e50.iloc[-1]
    dev = (p / v200 - 1) * 100
    slope = (e200.iloc[-1] / e200.iloc[-21] - 1) * 100
    bull = p > v200

    with_trend = (signal_dir == 1) == bull
    extreme = abs(dev) > 20
    if with_trend:
        mult, advice = 1.0, "顺势信号：可拿波段，尾仓看趋势延伸"
    elif extreme:
        mult, advice = 1.2, "极端位逆势信号：反转概率高（回测84%胜率区），可正常/加仓但TP必须分批走"
    else:
        mult, advice = 0.6, "逆势信号：反弹/回调单，仓位6折，到TP就走、移动止损贴身"

    return {
        "ema200": round(float(v200), 2),
        "ema50": round(float(v50), 2),
        "deviation_pct": round(dev, 1),
        "ema200_slope_20d": round(slope, 1),
        "macro_dir": "牛市(价>EMA200)" if bull else "熊市(价<EMA200)",
        "signal_vs_macro": "顺势" if with_trend else "逆势",
        "size_mult": mult,
        "advice": advice,
    }


# ------------------------------------------------------------------
# 5. 精确入场点计算：缓存的 XABC 结构 -> D 点预测 + 挂单方案
# ------------------------------------------------------------------
def calc_entry(X_p, A_p, B_p, C_p, pattern="Gartley", atr=0.0,
               mode="ladder", tol=None, daily_close=None):
    tol = tol if tol is not None else CONFIG['TOL']
    """
    形态未走完时，用已确认的 XABC 四点预测 D 点精确落点。

    参数:
        X_p..C_p : 缓存的摆动点价格（看涨: X低A高B低C高；看跌反之）
        pattern  : 形态名，决定用哪些斐波那契系数
        atr      : 当前 4H ATR，用于止损缓冲（0 则用腿幅的 10%）
        mode     : 'aggressive' 中心挂单 / 'ladder' 三档分批 / 'confirm' 区间提醒
    返回:
        dict: PRZ 区间、挂单列表、止损、TP1/TP2、AB=CD 校验
    """
    spec = PATTERNS[pattern]
    bullish = A_p > X_p
    xa = abs(A_p - X_p)
    ab = abs(B_p - A_p)
    bc = abs(C_p - B_p)

    # B 点校验：结构不达标就放弃这次机会
    r_BXA = ab / xa
    if not _in_range(r_BXA, *spec["B/XA"], tol):
        return {"valid": False, "reason": f"B点回撤 {r_BXA:.3f} 不符合 {pattern}"}

    # C 点校验（复盘修复：此前只校验B点，导致 C 越界的假形态被采纳，
    #  如 AAVE 2026-07 窗口 C>A 仍给出 Gartley 信号）
    # 1) 结构方向：看涨形态 C 不应高于 A 太多；看跌反之（±5% 容差带，与回测引擎一致）
    if bullish and C_p > A_p * 1.05:
        return {"valid": False, "reason": f"结构非法：看涨{pattern}的C点({C_p})明显高于A点({A_p})"}
    if not bullish and C_p < A_p * 0.95:
        return {"valid": False, "reason": f"结构非法：看跌{pattern}的C点({C_p})明显低于A点({A_p})"}
    # 2) C/AB 回撤比率须落在形态定义区间内
    r_CAB = bc / ab
    if not _in_range(r_CAB, *spec["C/AB"], tol):
        return {"valid": False, "reason": f"C点回撤 {r_CAB:.3f} 不符合 {pattern} 的C/AB范围"}

    s = 1 if bullish else -1  # 方向因子
    # 三个独立投影公式
    D1 = A_p - s * xa * spec["D/XA"][0]          # XA 目标回撤/延伸
    D2 = C_p - s * bc * np.mean(spec["CD/BC"])   # BC 腿投影（取系数中值）
    D3 = C_p - s * ab                            # AB=CD 等距投影

    prz_lo, prz_hi = min(D1, D2, D3), max(D1, D2, D3)
    center = np.mean([D1, D2, D3])

    buf = atr * CONFIG['STOP_ATR_BUF'] if atr else xa * CONFIG['STOP_FALLBACK_XA']
    stop = prz_lo - buf if bullish else prz_hi + buf

    # 分批挂单：PRZ 25% / 50% / 75% 三档
    if mode == "aggressive":
        orders = [round(center, 2)]
    elif mode == "ladder":
        orders = [round(prz_lo + (prz_hi - prz_lo) * f, 2) for f in (0.25, 0.5, 0.75)]
    else:  # confirm
        orders = []

    tp1 = center + s * abs(A_p - center) * CONFIG['TP1_RATIO']
    tp2 = center + s * abs(A_p - center) * CONFIG['TP2_RATIO']

    # PRZ 汇聚度分级（回测：窄 PRZ 单笔期望显著更高）
    width_pct = (prz_hi - prz_lo) / abs(center)
    grade = "A" if width_pct < CONFIG['PRZ_GRADE_A'] else \
            ("B" if width_pct < CONFIG['PRZ_GRADE_B'] else "C(放弃)")

    result = {
        "valid": True,
        "pattern": pattern,
        "direction": "bullish" if bullish else "bearish",
        "grade": grade,
        "prz_width_pct": round(width_pct * 100, 2),
        "B_ratio": round(r_BXA, 3),
        "projections": {"D1_XA回撤": round(D1, 2), "D2_BC投影": round(D2, 2),
                        "D3_AB=CD": round(D3, 2)},
        "PRZ": (round(prz_lo, 2), round(prz_hi, 2)),
        "entry_center": round(center, 2),
        "orders": orders,
        "stop": round(stop, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "rr_tp1": round(abs(tp1 - center) / abs(center - stop), 2),
    }
    # 宏观方向层（可选）：传入日线收盘价则附 EMA200 仓位系数建议
    if daily_close is not None:
        result["macro"] = macro_bias(daily_close, signal_dir=s)
    return result



# ------------------------------------------------------------------
# 4.6 形成中形态扫描器（复盘新增：实盘主扫描入口）
# 此前这段逻辑散落在分析脚本里，导致三个漏洞反复人工兜底：
#   ① C点超期的 stale 信号被当成可执行（BNB 2026-07，C点96根K线前）
#   ② C点后价格已破止损的"尸体信号"被采纳（AAVE 2026-07）
#   ③ 形态级别、PRZ内/外、距离全靠人肉判断
# 本函数把 ①②③ 全部内置，输出可直接交易评估的信号列表。
# ------------------------------------------------------------------
def scan_forming(df: pd.DataFrame, daily_close: pd.Series = None,
                 zz_pct: float = None, tol: float = None,
                 n_piv: int = 14, max_ttl: int = None,
                 patterns: list = None) -> list:
    """
    在最近 n_piv 个 ZigZag 摆动点中，枚举全部连续 XABC 四点窗口，
    对每个形态测算 D 点，并按实盘纪律过滤：
      - 只保留 A/B 级 PRZ（C级放弃）
      - TTL：C 点到现在的K线数 <= max_ttl（默认 CONFIG['BT_SIGNAL_TTL']），
        超期的信号标记 stale=True 降级为"参考区"，不作为可执行信号
      - 路径完整性：C 点之后价格曾穿越止损位 -> 信号已死，直接剔除
      - 已过 TP2 的（行情走完）剔除
    返回 list[dict]，按 grade 优先、距离现价由近到远排序。
    """
    zz_pct = zz_pct if zz_pct is not None else CONFIG['ZZ_PCT']
    tol = tol if tol is not None else CONFIG['TOL']
    max_ttl = max_ttl if max_ttl is not None else CONFIG['BT_SIGNAL_TTL']
    names = patterns or CONFIG['PATTERNS']

    a = atr(df).iloc[-1]
    zz = zigzag(df, pct=zz_pct)
    if len(zz) < 4:
        return []
    zz = zz.copy()
    zz['time'] = df.index[zz['idx']]
    pts = zz.tail(n_piv).reset_index(drop=True)
    cur = df['close'].iloc[-1]

    out = []
    for w in range(len(pts) - 3):
        seg = pts.iloc[w:w + 4]
        X, A_, B, C = seg['price'].values
        c_idx, c_time = int(seg['idx'].iloc[3]), seg['time'].iloc[3]
        bars_since_c = len(df) - 1 - c_idx
        after = df.iloc[c_idx + 1:]
        for pat in names:
            r = calc_entry(X, A_, B, C, pattern=pat, atr=a, tol=tol,
                           daily_close=daily_close)
            if not r.get('valid') or r['grade'].startswith('C'):
                continue
            bullish = r['direction'] == 'bullish'
            # 路径完整性：C点后曾破止损 -> 信号尸体，剔除
            if len(after):
                breached = (after['low'] < r['stop']).any() if bullish \
                    else (after['high'] > r['stop']).any()
                if breached:
                    continue
            # 已走过TP2 -> 行情完成，剔除
            if (cur > r['tp2']) if bullish else (cur < r['tp2']):
                continue
            lo, hi = r['PRZ']
            in_prz = lo <= cur <= hi
            # 到PRZ最近边缘的距离%：>0 表示价格还需朝PRZ方向走多少才触及
            if in_prz:
                dist_pct = 0.0
            elif bullish:   # 看涨PRZ在下方：现价高于PRZ上沿 -> 需回调 (hi/cur-1) 为负，取正距离
                dist_pct = abs(hi / cur - 1) * 100 if cur > hi else abs(lo / cur - 1) * 100
            else:           # 看跌PRZ在上方：需反弹触及
                dist_pct = abs(lo / cur - 1) * 100 if cur < lo else abs(hi / cur - 1) * 100
            out.append({
                "pattern": pat, "direction": r['direction'],
                "grade": r['grade'], "XABC": (X, A_, B, C),
                "C_time": str(c_time), "bars_since_c": bars_since_c,
                "stale": bars_since_c > max_ttl,
                "PRZ": r['PRZ'], "entry_center": r['entry_center'],
                "orders": r['orders'], "stop": r['stop'],
                "tp1": r['tp1'], "tp2": r['tp2'], "rr_tp1": r['rr_tp1'],
                "in_prz": in_prz, "dist_pct": round(dist_pct, 2),
                "macro": r.get('macro'),
            })
    grade_rank = {"A": 0, "B": 1}
    out.sort(key=lambda s: (s['stale'], grade_rank.get(s['grade'], 2),
                            abs(s['dist_pct'])))
    return out


if __name__ == "__main__":
    # 教科书级看涨 Gartley：
    # X=100, A=110, B=103.82(XA回撤0.618), C=107.64(AB回撤0.618),
    # D=102.14(XA回撤0.786, CD/BC=1.44)  -> 之后价格反转上行
    path = [100, 104, 110, 107, 103.82, 106, 107.64, 105, 102.14, 104, 106]
    rows = []
    for i, p in enumerate(path):
        rows.append({"open": p, "high": p, "low": p, "close": p})
    df = pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(rows), freq="D"))

    for sig in scan(df, zz_pct=0.02, tol=0.10, only_latest=False):
        print(f"[{sig['pattern']}] {sig['direction']}  D={sig['D'][1]:.2f}")
        print(f"  ratios : {sig['ratios']}")
        print(f"  PRZ    : {sig['PRZ']}")
        print(f"  stop   : {sig['stop']}  tp1={sig['tp1']} (RR {sig['rr_tp1']})  "
              f"tp2={sig['tp2']} (RR {sig['rr_tp2']})")
