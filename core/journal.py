"""İşlem günlüğü (CSV). Streamlit Cloud'da disk kalıcı değildir -> düzenli olarak CSV'yi indir."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PATH = Path(__file__).resolve().parent.parent / "data" / "journal.csv"
COLS = ["Tarih", "Piyasa", "Sembol", "Yön", "Adet", "Giriş", "Çıkış", "Çarpan", "Neden", "Not"]


def empty() -> pd.DataFrame:
    df = pd.DataFrame(columns=COLS)
    return df.astype({"Adet": "float", "Giriş": "float", "Çıkış": "float", "Çarpan": "float",
                      "Tarih": "string", "Piyasa": "string", "Sembol": "string", "Yön": "string",
                      "Neden": "string", "Not": "string"})


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in COLS:
        if c not in df.columns:
            df[c] = None
    df = df[COLS]
    for c in ["Adet", "Giriş", "Çıkış", "Çarpan"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Çarpan"] = df["Çarpan"].fillna(1.0)
    for c in ["Tarih", "Piyasa", "Sembol", "Yön", "Neden", "Not"]:
        df[c] = df[c].astype("string")
    return df


def load() -> pd.DataFrame:
    if PATH.exists():
        try:
            return normalize(pd.read_csv(PATH))
        except Exception:
            pass
    return empty()


def save(df: pd.DataFrame) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    normalize(df).to_csv(PATH, index=False)


def pnl(df: pd.DataFrame, commission: float) -> pd.DataFrame:
    df = normalize(df)
    yon = df["Yön"].fillna("AL").astype(str).str.upper()
    sign = pd.Series(np.where(yon.str.startswith(("SAT", "AÇIĞA", "SHORT")), -1.0, 1.0), index=df.index)
    closed = df["Çıkış"].notna() & df["Giriş"].notna() & df["Adet"].notna()
    gross = (df["Çıkış"] - df["Giriş"]) * df["Adet"] * df["Çarpan"] * sign
    is_stock = df["Piyasa"].fillna("Hisse").astype(str).str.lower().str.startswith("his").astype(float)
    comm = (df["Giriş"] + df["Çıkış"]) * df["Adet"] * commission * is_stock
    df["K/Z TL"] = (gross - comm).where(closed)
    df["K/Z %"] = ((df["Çıkış"] / df["Giriş"] - 1) * 100 * sign).where(closed).round(2)
    df["Durum"] = closed.map({True: "Kapalı", False: "Açık"})
    return df
