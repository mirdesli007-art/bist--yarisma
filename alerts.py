"""Telefona Telegram bildirimi: seans içinde AL sinyallerini ve önemli haberleri gönderir.

GitHub Actions ile 30 dakikada bir otomatik çalışır (.github/workflows/alerts.yml).
Gerekli ortam değişkenleri: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
İsteğe bağlı: RISK_PCT (vars. 1.5), EQUITY (vars. 200000), RR (vars. 2)
Elle deneme:  TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=... python alerts.py --force
"""
from __future__ import annotations

import html
import os
import sys

import numpy as np
import requests

from core import data, news, risk, signals
from core.universe import BIST100


def send(text: str) -> None:
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print(text)
        return
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": "true"}, timeout=15)
    print("telegram:", r.status_code, r.text[:200])


def main(force: bool = False) -> None:
    is_open, status = data.market_status()
    t = data.now_tr()
    if not force and not is_open and not (t.weekday() < 5 and t.hour == 9):
        print("Piyasa kapalı:", status)
        return

    eq = float(os.environ.get("EQUITY", 200_000))
    risk_pct = float(os.environ.get("RISK_PCT", 1.5))
    rr = float(os.environ.get("RR", 2.0))

    lines = [f"<b>📈 BIST Asistanı · {t:%d.%m %H:%M}</b> ({status})"]

    if is_open or force:
        d5 = data.download(BIST100, "30d", "5m")
        dd = data.download(BIST100, "1y", "1d")
        picks = []
        for s in BIST100:
            df5 = d5.get(f"{s}.IS")
            a = signals.analyze(s, df5, dd.get(f"{s}.IS"), rr=rr)
            if not a or a["Sinyal"] != "AL":
                continue
            sm = signals.summarize(signals.backtest(df5, rr=rr), 0)
            if sm["kurulum"] >= 5 and sm["ort_R"] < 0:
                continue  # bu hissede kural geçmişte çalışmamış
            sz = risk.stock_size(eq, eq, a["Giriş"], a["Stop"], risk_pct, 35)
            picks.append((a["Puan"] + (1 if sm.get("ort_R", 0) >= 0.3 else 0), a, sm, sz["lot"]))
        picks.sort(key=lambda x: -x[0])
        if picks:
            lines.append("\n<b>AL sinyalleri</b> (fiyatı Matriks'te teyit et):")
            for _, a, sm, lot in picks[:6]:
                hist = f"geçmiş {sm['kurulum']} kurulum, ort {sm['ort_R']}R" if sm["kurulum"] else "geçmiş yok"
                lines.append(f"• <b>{a['Sembol']}</b> {a['Son']} ({a['Değ%']:+.1f}%) → giriş {a['Giriş']} "
                             f"stop {a['Stop']} hedef {a['Hedef']} · {lot} lot · hacim {a['Hacim x']}x · {hist}")
        else:
            lines.append("\nŞu an kriterleri sağlayan AL sinyali yok.")

    try:
        nws = news.fetch_news(hours=2 if is_open else 16)
        hot = nws[nws["Önem"] >= 3].head(6)
        if len(hot):
            lines.append("\n<b>Önemli haberler</b>")
            for r in hot.itertuples():
                lines.append(f"{r.Yön} <a href=\"{html.escape(r.Link)}\">{html.escape(r.Başlık)}</a> [{r.Etiket}]")
    except Exception as e:  # haber hatası sinyali engellemesin
        print("haber hatası:", e)

    if len(lines) > 1:
        send("\n".join(lines)[:4000])


if __name__ == "__main__":
    np.seterr(all="ignore")
    main(force="--force" in sys.argv)
