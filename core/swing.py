"""Hisse momentum / swing stratejisi (birkaç gün - birkaç hafta tutma).

Test (3 yıl, günlük): 20 günlük zirveyi hacimle kıran ve 50 günlük ortalamanın üstündeki hisseyi
ertesi açılışta al, 10 günlük dibin altında kapanınca sat. Son 1,5 yılda işlem başı ort. +%2,5
(endeksin aynı süredeki ~%1,2 getirisinin üstünde). İlk 1,5 yılda avantaj zayıftı.
Haftalık rotasyon: son 3 ayın en güçlü 5 hissesi, endeks 10 haftalık ortalamanın üstündeyken.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .signals import atr, rsi

COMM = 0.0004


def market_regime(xu: pd.DataFrame) -> dict:
    """BIST 100 haftalık kapanış 10 haftalık ortalamanın üstünde mi?"""
    w = xu["Close"].resample("W-FRI").last().dropna()
    sma = w.rolling(10).mean()
    d = xu["Close"]
    up = bool(w.iloc[-1] > sma.iloc[-1])
    return {"yukarı": up, "xu": float(d.iloc[-1]), "sma10w": float(sma.iloc[-1]),
            "uzaklık%": float((w.iloc[-1] / sma.iloc[-1] - 1) * 100),
            "ret20%": float((d.iloc[-1] / d.iloc[-21] - 1) * 100)}


def scan(daily: dict[str, pd.DataFrame], xu_ret63: float | None = None) -> pd.DataFrame:
    rows = []
    for k, d in daily.items():
        if not k.endswith(".IS") or k.startswith("XU") or len(d) < 80:
            continue
        c, h, l, v = d["Close"], d["High"], d["Low"], d["Volume"]
        hi20 = h.rolling(20).max().shift()
        lo10 = l.rolling(10).min().shift()
        v20 = v.rolling(20).mean().shift()
        s50 = c.rolling(50).mean()
        last = float(c.iloc[-1])
        ret63 = float(c.iloc[-1] / c.iloc[-64] - 1) if len(c) > 64 else np.nan
        ret21 = float(c.iloc[-1] / c.iloc[-22] - 1)
        vol_x = float(v.iloc[-1] / v20.iloc[-1]) if v20.iloc[-1] > 0 else np.nan
        brk = last > hi20.iloc[-1]
        brk_vol = brk and vol_x >= 1.5 and last > s50.iloc[-1]
        # son 5 gün içinde kırılım olduysa ve hâlâ trenddeyse
        recent = False
        for j in range(2, 7):
            if len(c) > j and c.iloc[-j] > hi20.iloc[-j] and v.iloc[-j] > 1.5 * v20.iloc[-j] and c.iloc[-j] > s50.iloc[-j]:
                recent = True
                break
        stop = float(lo10.iloc[-1])
        a = float(atr(d).iloc[-1])
        if stop >= last:
            stop = last - 2 * a
        risk_pct = (last - stop) / last * 100
        sig = "KIRILIM AL" if brk_vol else ("TRENDDE" if recent and last > stop and last > s50.iloc[-1] else
                                             ("ÇIKIŞ" if last < lo10.iloc[-1] else "-"))
        rows.append({
            "Sembol": k.replace(".IS", ""), "Sinyal": sig, "Son": round(last, 2),
            "Gün%": round(float(c.iloc[-1] / c.iloc[-2] - 1) * 100, 2),
            "1A%": round(ret21 * 100, 1), "3A%": round(ret63 * 100, 1) if not np.isnan(ret63) else None,
            "Hacim x": round(vol_x, 2) if not np.isnan(vol_x) else None,
            "20G zirve": round(float(hi20.iloc[-1]), 2), "Stop (10G dip)": round(stop, 2),
            "Risk%": round(risk_pct, 1), "RSI": round(float(rsi(c).iloc[-1]), 0),
            "50G ort üstü": bool(last > s50.iloc[-1]),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["Momentum sırası"] = df["3A%"].rank(ascending=False, method="min").astype("Int64")
    return df


def backtest_breakout(daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Kırılım kuralını tüm hisselerde günlük veriyle test eder (işlem listesi)."""
    tr = []
    for k, d in daily.items():
        if not k.endswith(".IS") or k.startswith("XU") or len(d) < 120:
            continue
        c, h, l, v, o = d["Close"].values, d["High"], d["Low"], d["Volume"], d["Open"].values
        hi20 = h.rolling(20).max().shift().values
        lo10 = l.rolling(10).min().shift().values
        v20 = v.rolling(20).mean().shift().values
        s50 = d["Close"].rolling(50).mean().values
        vv = v.values
        idx = d.index
        i = 60
        n = len(c)
        while i < n - 2:
            if c[i] > hi20[i] and vv[i] > 1.5 * v20[i] and c[i] > s50[i]:
                e = o[i + 1]
                j = i + 1
                while j < n - 1 and c[j] > lo10[j] and j - i < 30:
                    j += 1
                tr.append((idx[i], k.replace(".IS", ""), c[j] / e - 1 - 2 * COMM, j - i, j == n - 1))
                i = j
            i += 1
    return pd.DataFrame(tr, columns=["Tarih", "Sembol", "Getiri", "Gün", "Açık"])


def bt_summary(bt: pd.DataFrame, since: pd.Timestamp | None = None) -> dict:
    x = bt[~bt["Açık"]]
    x = x[x["Getiri"] > -0.5]  # bedelsiz/bölünme kaynaklı veri hatalarını dışla (10G dip stop'u ile -%50 olmaz)
    if since is not None:
        x = x[x["Tarih"] >= since]
    if x.empty:
        return {"işlem": 0}
    return {"işlem": len(x), "kazanma%": round((x["Getiri"] > 0).mean() * 100),
            "ort%": round(x["Getiri"].mean() * 100, 2), "medyan%": round(x["Getiri"].median() * 100, 2),
            "ort gün": round(x["Gün"].mean(), 1),
            "en iyi%": round(x["Getiri"].max() * 100, 1), "en kötü%": round(x["Getiri"].min() * 100, 1)}
