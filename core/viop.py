"""VİOP: dayanak bazlı trend sinyalleri + vadeli taşıma maliyeti (baz) hesabı.

Önemli: Vadeli fiyat ≈ spot × (1 + faiz farkı × gün/365). TL faizi yüksek olduğundan TL bazlı vadeliler
spottan pahalıdır. Uzun (long) pozisyon bu farkı kaybeder, kısa (short) pozisyon kazanır.
3 yıllık test (taşıma dahil): BIST30 ve USD/TRY vadelide 'al ve tut' ve trend stratejileri zarar ettirdi;
ons altın ($) ve gümüşte EMA10/30 trend takibi son 1,5 yılda pozitif sonuç verdi.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .signals import atr

# ad: (yahoo sembolleri, kur çevrimi, taşıma türü, açıklama)
INSTRUMENTS = {
    "Ons Altın ($)": dict(sym="GC=F", kind="USD", note="VİOP ons altın vadeli (USD). Taşıma maliyeti düşük (USD faizi)."),
    "Gram Altın (TL)": dict(sym="GC=F", fx="USDTRY=X", div=31.1035, kind="TRY",
                            note="TL bazlı: vadeli fiyat TL faizi kadar pahalı → long için ciddi maliyet."),
    "Ons Gümüş ($)": dict(sym="SI=F", kind="USD", note="Çok oynak (yıllık ~%50). Küçük pozisyonla."),
    "BIST 30 Endeks": dict(sym="XU030.IS", kind="TRY",
                           note="Long için vadeli yerine hisse almak daha ucuz. VİOP'ta daha çok SHORT/korunma için."),
    "USD/TRY": dict(sym="USDTRY=X", kind="TRYUSD",
                    note="Long, faiz farkını öder (3 yılda yılda ~%15-20 kaybettirdi). Short faiz kazanır ama ani kur sıçramasında büyük zarar."),
}
USD_RATE = 0.045


def series(raw: dict, name: str) -> pd.DataFrame | None:
    spec = INSTRUMENTS[name]
    d = raw.get(spec["sym"])
    if d is None or d.empty:
        return None
    d = d[["Open", "High", "Low", "Close"]].copy()
    d.index = d.index.normalize().tz_localize(None)
    d = d[~d.index.duplicated(keep="last")]
    if "fx" in spec:
        fx = raw.get(spec["fx"])
        if fx is None:
            return None
        f = fx["Close"].copy()
        f.index = f.index.normalize().tz_localize(None)
        f = f[~f.index.duplicated(keep="last")].reindex(d.index).ffill()
        d = d.mul(f, axis=0) / spec["div"]
    return d.dropna()


def daily_carry(kind: str, tl_rate: float) -> float:
    if kind == "TRY":
        return tl_rate / 252
    if kind == "TRYUSD":
        return (tl_rate - USD_RATE) / 252
    return USD_RATE / 252


def signal(d: pd.DataFrame) -> dict:
    c = d["Close"]
    e10, e30 = c.ewm(span=10).mean(), c.ewm(span=30).mean()
    pos = np.sign(e10 - e30)
    cur = int(pos.iloc[-1])
    flips = pos.ne(pos.shift())
    since = pos.index[flips][-1] if flips.any() else pos.index[0]
    a = float(atr(d).iloc[-1])
    last = float(c.iloc[-1])
    lo10, hi10 = float(d["Low"].iloc[-10:].min()), float(d["High"].iloc[-10:].max())
    if cur > 0:
        stop = max(lo10, last - 2.5 * a)
    else:
        stop = min(hi10, last + 2.5 * a)
    gap = float((e10.iloc[-1] / e30.iloc[-1] - 1) * 100)
    return {"yön": "LONG" if cur > 0 else "SHORT", "başlangıç": since, "son": last, "ema10": float(e10.iloc[-1]),
            "ema30": float(e30.iloc[-1]), "fark%": gap, "atr": a, "atr%": a / last * 100, "stop": stop,
            "ret5%": float((c.iloc[-1] / c.iloc[-6] - 1) * 100), "ret21%": float((c.iloc[-1] / c.iloc[-22] - 1) * 100)}


def backtest(d: pd.DataFrame, kind: str, tl_rate: float, mode: str = "L/S") -> pd.Series:
    """EMA10/30 trend takibi, taşıma maliyeti dahil günlük getiri serisi (1x kaldıraç)."""
    c = d["Close"]
    ret = c.pct_change().fillna(0)
    sig = np.sign(c.ewm(span=10).mean() - c.ewm(span=30).mean())
    if mode == "long":
        sig = sig.clip(lower=0)
    elif mode == "short":
        sig = sig.clip(upper=0)
    elif mode == "hold_long":
        sig = pd.Series(1.0, index=c.index)
    elif mode == "hold_short":
        sig = pd.Series(-1.0, index=c.index)
    pos = sig.shift(1).fillna(0)
    cy = daily_carry(kind, tl_rate)
    return pos * ret - pos * cy - pos.diff().abs().fillna(0) * 0.0004


def stats(r: pd.Series, lev: float = 1.0) -> dict:
    x = r * lev
    eq = (1 + x).cumprod()
    m21 = ((1 + x).rolling(21).apply(np.prod, raw=True) - 1).dropna()
    yrs = len(x) / 252
    return {"yıllık%": round(((eq.iloc[-1]) ** (1 / yrs) - 1) * 100, 1) if yrs > 0 else None,
            "sharpe": round(x.mean() / x.std() * np.sqrt(252), 2) if x.std() > 0 else 0,
            "max düşüş%": round(float((eq / eq.cummax() - 1).min()) * 100, 1),
            "30g kötü (p10)%": round(float(m21.quantile(0.1)) * 100, 1),
            "30g orta%": round(float(m21.median()) * 100, 1),
            "30g iyi (p90)%": round(float(m21.quantile(0.9)) * 100, 1),
            "30g en kötü%": round(float(m21.min()) * 100, 1)}


def basis(spot: float, fut: float, days_to_expiry: int) -> dict:
    if spot <= 0 or fut <= 0 or days_to_expiry <= 0:
        return {}
    b = fut / spot - 1
    ann = b * 365 / days_to_expiry
    return {"baz%": b * 100, "yıllık%": ann * 100, "aylık%": ann / 12 * 100}
