"""Gün içi sinyaller: açılış aralığı kırılımı (ORB) + VWAP + göreli hacim + günlük trend.

Kural (backtest ile aynı):
  - Açılış aralığı = 10:00-10:30 arası ilk 6 adet 5 dakikalık mum.
  - 10:30'dan sonra bir mum aralığın tepesinin ÜSTÜNDE ve VWAP'ın üstünde kapanırsa -> giriş.
  - Stop = aralığın dibi (en fazla %MAX_STOP uzaklıkta).
  - Hedef = giriş + RR x risk (tavanı geçemez). Gün sonu açık kalan pozisyon kapanışta kapatılır.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

ORB_BARS = 6          # 6 x 5dk = 30 dk
MAX_STOP = 0.03       # stop en fazla %3 uzakta
LIMIT = 0.10          # BIST tavan/taban
COMMISSION = 0.0004   # tek yön (varsayılan, ayarlardan değişir)


# ---------- göstergeler ----------
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def vwap(day: pd.DataFrame) -> pd.Series:
    tp = (day["High"] + day["Low"] + day["Close"]) / 3
    v = day["Volume"].replace(0, np.nan).fillna(0)
    cv = v.cumsum()
    return (tp * v).cumsum() / cv.replace(0, np.nan)


def by_day(df5: pd.DataFrame) -> dict:
    return {d: g for d, g in df5.groupby(df5.index.date)}


def daily_features(dd: pd.DataFrame) -> dict:
    c = dd["Close"]
    if len(c) < 30:
        return {}
    e20, e50 = c.ewm(span=20).mean(), c.ewm(span=50).mean()
    return {
        "ema20": e20.iloc[-1], "ema50": e50.iloc[-1],
        "rsi_d": rsi(c).iloc[-1], "atr_d": atr(dd).iloc[-1],
        "ret5": c.iloc[-1] / c.iloc[-6] - 1, "ret20": c.iloc[-1] / c.iloc[-21] - 1,
        "hi20": dd["High"].iloc[-21:-1].max(),
    }


# ---------- tek hisse anlık analiz ----------
def analyze(sym: str, df5: pd.DataFrame, dd: pd.DataFrame | None, rr: float = 2.0) -> dict | None:
    if df5 is None or df5.empty:
        return None
    days = by_day(df5)
    keys = sorted(days)
    today = days[keys[-1]]
    prev_days = [days[k] for k in keys[:-1]]
    last = float(today["Close"].iloc[-1])
    prev_close = float(prev_days[-1]["Close"].iloc[-1]) if prev_days else float(today["Open"].iloc[0])
    vw = vwap(today)
    vw_last = float(vw.iloc[-1]) if not math.isnan(vw.iloc[-1]) else last

    orb = today.iloc[:ORB_BARS]
    orb_hi, orb_lo = float(orb["High"].max()), float(orb["Low"].min())
    orb_done = len(today) > ORB_BARS

    # göreli hacim: bugün şu saate kadarki hacim / önceki günlerin aynı saate kadarki ortalaması
    t_last = today.index[-1].time()
    prior = [g[g.index.time <= t_last]["Volume"].sum() for g in prev_days[-10:]]
    prior = [p for p in prior if p > 0]
    rvol = float(today["Volume"].sum() / np.mean(prior)) if prior else float("nan")

    r5 = float(rsi(df5["Close"]).iloc[-1])
    chg = last / prev_close - 1
    feat = daily_features(dd) if dd is not None else {}

    # --- puanlama ---
    score, why = 0, []
    if feat:
        if last > feat["ema20"]:
            score += 1; why.append("günlük EMA20 üstü")
        if feat["ema20"] > feat["ema50"]:
            score += 1; why.append("yükselen trend")
        if feat["rsi_d"] > 75:
            score -= 1; why.append("günlük RSI aşırı alım")
        if last > feat.get("hi20", 1e18):
            score += 1; why.append("20 günlük zirve kırılımı")
    if last > vw_last:
        score += 1; why.append("VWAP üstü")
    else:
        score -= 1
    breakout = orb_done and last > orb_hi
    breakdown = orb_done and last < orb_lo
    if breakout:
        score += 2; why.append("açılış aralığı kırıldı")
    if breakdown:
        score -= 2; why.append("açılış aralığı dibi kırıldı")
    if not math.isnan(rvol):
        if rvol >= 2.5:
            score += 2; why.append(f"hacim {rvol:.1f}x")
        elif rvol >= 1.5:
            score += 1; why.append(f"hacim {rvol:.1f}x")
    if 50 <= r5 <= 75:
        score += 1
    elif r5 > 82:
        score -= 1; why.append("5dk RSI şişkin")
    if chg >= LIMIT - 0.01:
        score -= 3; why.append("tavana yakın - kovalamaya değmez")

    # --- giriş / stop / hedef ---
    entry = last
    stop = max(orb_lo, entry * (1 - MAX_STOP))
    if feat and feat.get("atr_d"):
        stop = max(stop, entry - 0.8 * feat["atr_d"])
    if stop >= entry * 0.997:
        stop = entry * 0.985
    risk = entry - stop
    tavan = prev_close * (1 + LIMIT)
    target = min(entry + rr * risk, tavan * 0.995)
    rr_real = (target - entry) / risk if risk > 0 else 0

    if breakout and last > vw_last and score >= 5 and rr_real >= 1.3 and (math.isnan(rvol) or rvol >= 1.0):
        action = "AL"
    elif score >= 3 and not breakdown:
        action = "İZLE"
    elif breakdown or score <= -1:
        action = "ZAYIF"
    else:
        action = "-"

    return {
        "Sembol": sym, "Sinyal": action, "Puan": score, "Son": round(last, 2),
        "Değ%": round(chg * 100, 2), "Hacim x": round(rvol, 2) if not math.isnan(rvol) else None,
        "RSI5": round(r5, 0), "VWAP": round(vw_last, 2),
        "ORB üst": round(orb_hi, 2), "ORB alt": round(orb_lo, 2),
        "Giriş": round(entry, 2), "Stop": round(stop, 2), "Hedef": round(target, 2),
        "R/R": round(rr_real, 2), "Neden": ", ".join(why),
        "Zaman": today.index[-1].strftime("%d.%m %H:%M"),
    }


# ---------- Zaman makinesi: aynı kuralı geçmiş günlerde dene ----------
def backtest(df5: pd.DataFrame, rr: float = 2.0, commission: float = COMMISSION,
             min_rvol: float = 0.0, include_today: bool = False) -> pd.DataFrame:
    days = by_day(df5)
    keys = sorted(days)
    if not include_today and keys:
        keys = keys[:-1]
    rows = []
    vols = []
    for k in keys:
        g = days[k]
        if len(g) < ORB_BARS + 6:
            vols.append(g["Volume"].sum()); continue
        orb = g.iloc[:ORB_BARS]
        hi, lo = orb["High"].max(), orb["Low"].min()
        vw = vwap(g)
        avg_vol = np.mean(vols[-10:]) if vols else np.nan
        entry_i = None
        for i in range(ORB_BARS, len(g) - 1):
            c = g["Close"].iloc[i]
            if c > hi and c > vw.iloc[i]:
                if min_rvol > 0 and not np.isnan(avg_vol):
                    frac = (i + 1) / len(g)
                    if g["Volume"].iloc[: i + 1].sum() < min_rvol * avg_vol * frac:
                        continue
                entry_i = i
                break
        vols.append(g["Volume"].sum())
        if entry_i is None:
            continue
        entry = g["Close"].iloc[entry_i]
        stop = max(lo, entry * (1 - MAX_STOP))
        if stop >= entry * 0.997:
            stop = entry * 0.985
        risk = entry - stop
        target = entry + rr * risk
        outcome, exit_p = "Kapanışta kapandı", g["Close"].iloc[-1]
        for j in range(entry_i + 1, len(g)):
            if g["Low"].iloc[j] <= stop:      # temkinli: aynı mumda ikisi de varsa stop say
                outcome, exit_p = "Stop", stop; break
            if g["High"].iloc[j] >= target:
                outcome, exit_p = "Hedef", target; break
        ret = exit_p / entry - 1 - 2 * commission
        rows.append({"Tarih": k, "Giriş saati": g.index[entry_i].strftime("%H:%M"), "Giriş": round(entry, 2),
                     "Stop": round(stop, 2), "Hedef": round(target, 2), "Çıkış": round(exit_p, 2),
                     "Sonuç": outcome, "Getiri%": round(ret * 100, 2), "R": round((exit_p - entry) / risk, 2)})
    cols = ["Tarih", "Giriş saati", "Giriş", "Stop", "Hedef", "Çıkış", "Sonuç", "Getiri%", "R"]
    return pd.DataFrame(rows, columns=cols)


def summarize(bt: pd.DataFrame, n_days: int) -> dict:
    if bt.empty:
        return {"gün": n_days, "kurulum": 0}
    return {
        "gün": n_days, "kurulum": len(bt),
        "hedef%": round((bt["Sonuç"] == "Hedef").mean() * 100),
        "stop%": round((bt["Sonuç"] == "Stop").mean() * 100),
        "kapanış%": round((bt["Sonuç"] == "Kapanışta kapandı").mean() * 100),
        "kazanma%": round((bt["Getiri%"] > 0).mean() * 100),
        "ort_R": round(bt["R"].mean(), 2),
        "ort_getiri%": round(bt["Getiri%"].mean(), 2),
    }


def monte_carlo(r_values: np.ndarray, trades: int = 25, risk_frac: float = 0.015,
                sims: int = 10_000, seed: int = 28) -> np.ndarray:
    """Geçmiş R sonuçlarından rastgele seçerek `trades` işlemlik bakiye çarpanı dağılımı üretir."""
    if len(r_values) == 0:
        return np.array([])
    rng = np.random.default_rng(seed)
    draws = rng.choice(r_values, size=(sims, trades), replace=True)
    return np.prod(1 + draws * risk_frac, axis=1)
