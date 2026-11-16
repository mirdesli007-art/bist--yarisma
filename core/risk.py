"""Pozisyon boyutu ve risk bekçisi."""
from __future__ import annotations

import math


def stock_size(equity: float, cash: float, entry: float, stop: float, risk_pct: float,
               max_pos_pct: float, commission: float = 0.0004) -> dict:
    risk_ps = entry - stop
    if entry <= 0 or risk_ps <= 0:
        return {"lot": 0, "hata": "Stop girişin altında olmalı"}
    risk_tl = equity * risk_pct / 100
    by_risk = risk_tl / (risk_ps + entry * 2 * commission)
    by_cap = min(equity * max_pos_pct / 100, cash) / (entry * (1 + commission))
    lot = int(max(0, math.floor(min(by_risk, by_cap))))
    return {
        "lot": lot, "tutar": lot * entry, "risk_tl": lot * risk_ps,
        "risk_%": lot * risk_ps / equity * 100 if equity else 0,
        "sınırlayan": "risk" if by_risk <= by_cap else "pozisyon/nakit limiti",
        "komisyon": lot * entry * commission * 2,
    }


def viop_size(equity: float, margin_per: float, multiplier: float, entry: float, stop: float,
              risk_pct: float, max_margin_pct: float) -> dict:
    risk_pc = abs(entry - stop) * multiplier
    if risk_pc <= 0 or margin_per <= 0:
        return {"kontrat": 0, "hata": "Stop ve teminat girilmeli"}
    by_risk = equity * risk_pct / 100 / risk_pc
    by_margin = equity * max_margin_pct / 100 / margin_per
    n = int(max(0, math.floor(min(by_risk, by_margin))))
    return {"kontrat": n, "teminat": n * margin_per, "risk_tl": n * risk_pc,
            "nominal": n * entry * multiplier,
            "sınırlayan": "risk" if by_risk <= by_margin else "teminat limiti"}


def guard(day_pnl_pct: float, trades_today: int, open_positions: int, rr: float,
          daily_loss_limit: float, max_trades: int, max_open: int, min_rr: float) -> list[str]:
    """Boş liste = GEÇER. Dolu = ENGEL nedenleri."""
    reasons = []
    if day_pnl_pct <= -abs(daily_loss_limit):
        reasons.append(f"Günlük zarar limiti (%{daily_loss_limit}) doldu - bugün işlem yok")
    if trades_today >= max_trades:
        reasons.append(f"Günlük işlem sayısı ({max_trades}) doldu")
    if open_positions >= max_open:
        reasons.append(f"Açık pozisyon sınırı ({max_open}) dolu")
    if rr < min_rr:
        reasons.append(f"Ödül/risk {rr:.2f} < {min_rr}")
    return reasons
