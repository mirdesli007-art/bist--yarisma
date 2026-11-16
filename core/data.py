"""Fiyat verisi: Yahoo Finance (BIST ~15 dk gecikmeli). İşlem fiyatını Matriks'ten teyit et."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from .universe import yahoo

TZ = ZoneInfo("Europe/Istanbul")


def now_tr() -> dt.datetime:
    return dt.datetime.now(TZ)


def market_status(t: dt.datetime | None = None) -> tuple[bool, str]:
    t = t or now_tr()
    if t.weekday() >= 5:
        return False, "Hafta sonu - piyasa kapalı"
    hm = t.hour * 60 + t.minute
    if hm < 9 * 60 + 40:
        return False, "Açılış öncesi (seans 10:00'da)"
    if hm < 10 * 60:
        return False, "Açılış seansı (09:40-10:00)"
    if hm < 18 * 60:
        return True, "Sürekli işlem - piyasa AÇIK"
    if hm < 18 * 60 + 10:
        return False, "Kapanış seansı (18:00-18:10)"
    return False, "Seans kapandı"


def _split(raw: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out
    if isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            if t in raw.columns.get_level_values(0):
                df = raw[t].dropna(subset=["Close"])
                if not df.empty:
                    out[t] = df
    else:
        df = raw.dropna(subset=["Close"])
        if not df.empty:
            out[tickers[0]] = df
    for t, df in out.items():
        idx = df.index
        if idx.tz is None:
            df.index = idx.tz_localize("UTC").tz_convert(TZ)
        else:
            df.index = idx.tz_convert(TZ)
    return out


def download(symbols: list[str], period: str, interval: str) -> dict[str, pd.DataFrame]:
    tickers = [yahoo(s) for s in symbols]
    raw = yf.download(
        tickers, period=period, interval=interval, group_by="ticker",
        progress=False, threads=True, auto_adjust=False,
    )
    data = _split(raw, tickers)
    if interval.endswith("m"):
        # BIST sürekli işlem saatleri dışındaki boş/yanlış barları at
        for k, df in data.items():
            if k.endswith(".IS"):
                data[k] = df.between_time("10:00", "18:05")
    return data
