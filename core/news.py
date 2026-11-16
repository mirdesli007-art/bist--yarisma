"""Finansal ve politik haber takibi (AA, Bloomberg HT, Google Haberler/KAP) + etiketleme."""
from __future__ import annotations

import calendar
import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

import feedparser
import pandas as pd
import requests

from .data import TZ
from .universe import BIST100, NAMES

UA = {"User-Agent": "Mozilla/5.0 (BIST yarisma asistani)"}


def gnews(q: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(q)}+when:2d&hl=tr&gl=TR&ceid=TR:tr"


FEEDS = {
    "AA Ekonomi": "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
    "AA Gündem": "https://www.aa.com.tr/tr/rss/default?cat=guncel",
    "Bloomberg HT": "https://www.bloomberght.com/rss",
    "G-Borsa İstanbul": gnews("Borsa İstanbul"),
    "G-KAP": gnews("KAP açıklama hisse"),
    "G-TCMB": gnews("Merkez Bankası faiz"),
    "G-Enflasyon": gnews("enflasyon TÜİK"),
    "G-Politika": gnews("Erdoğan OR TBMM OR seçim OR kabine ekonomi"),
    "G-SPK": gnews("SPK"),
}

# (etiket, anahtar kelimeler, önem 1-3)
TAGS = [
    ("TCMB/Faiz", ["merkez bankası", "tcmb", "ppk", "politika faizi", "faiz kararı", "karahan", "rezerv"], 3),
    ("Enflasyon", ["enflasyon", "tüfe", "üfe", "tüik"], 3),
    ("Politika", ["erdoğan", "cumhurbaşkanı", "tbmm", "meclis", "seçim", "kabine", "bakan", "chp", "ak parti", "muhalefet", "gözaltı", "tutuklama", "dava"], 2),
    ("Jeopolitik", ["savaş", "saldırı", "israil", "iran", "rusya", "ukrayna", "suriye", "nato", "füze", "ateşkes"], 2),
    ("Kur", ["dolar", "euro", "döviz", "dolar/tl", "kur farkı"], 2),
    ("Maliye", ["şimşek", "vergi", "bütçe", "cari açık", "kredi notu", "moody's", "fitch", "s&p"], 2),
    ("Global", ["fed", "powell", "abd", "çin", "trump", "avrupa merkez", "ecb", "petrol", "brent"], 1),
    ("Bilanço", ["bilanço", "net kâr", "net kar", "finansal sonuç", "çeyrek", "zarar açıkladı"], 3),
    ("Temettü", ["temettü", "kâr payı", "kar payı"], 2),
    ("Bedelsiz/Sermaye", ["bedelsiz", "sermaye artırımı", "bölünme", "tahsisli"], 3),
    ("Geri alım", ["geri alım", "pay geri"], 2),
    ("Anlaşma/İhale", ["ihale", "sözleşme", "anlaşma imzala", "sipariş", "satın al", "devral", "iş ilişkisi"], 2),
    ("SPK/Borsa", ["spk", "tedbir", "brüt takas", "kredili işlem yasağı", "açığa satış", "devre kesici", "halka arz"], 3),
]

POS = ["yükseldi", "rekor", "artış", "arttı", "kazandı", "olumlu", "toparlan", "güçlü", "büyüdü", "anlaşma imzala",
       "ihale kazan", "faiz indir", "indirim", "not artır", "yükseliş", "prim", "temettü", "geri alım", "sipariş"]
NEG = ["düştü", "geriledi", "kayıp", "zarar", "olumsuz", "sert düş", "gerile", "daraldı", "faiz artır", "artırım kararı",
       "yaptırım", "gözaltı", "tutuklan", "savaş", "saldırı", "not indir", "satış baskısı", "tedbir", "iflas", "konkordato"]

_CODE_RE = re.compile(r"\b(" + "|".join(BIST100) + r")\b")


def _fetch(item):
    name, url = item
    try:
        r = requests.get(url, headers=UA, timeout=12)
        f = feedparser.parse(r.content)
    except Exception:
        return []
    out = []
    for e in f.entries[:40]:
        t = e.get("published_parsed") or e.get("updated_parsed")
        when = dt.datetime.fromtimestamp(calendar.timegm(t), dt.timezone.utc).astimezone(TZ) if t else None
        title = (e.get("title") or "").strip()
        src = name
        if name.startswith("G-") and " - " in title:
            title, s = title.rsplit(" - ", 1)
            src = s.strip()
        out.append({"Zaman": when, "Kaynak": src, "Başlık": title, "Link": e.get("link", ""), "Akış": name})
    return out


def _low(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def _rx(words: list[str]) -> re.Pattern:
    # kelime başı sınırı: "çin" -> "için" içinde eşleşmesin, ama "Çin'in" eşleşsin
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(_low(w).strip()) for w in words) + ")")


_TAG_RX = [(t, _rx(kws), w) for t, kws, w in TAGS]
_POS_RX, _NEG_RX = _rx(POS), _rx(NEG)
_NAME_RX = {sym: _rx(names) for sym, names in NAMES.items()}


def tag(title: str) -> tuple[list[str], int, int, list[str]]:
    low = _low(title)
    tags, imp = [], 0
    for t, rx, w in _TAG_RX:
        if rx.search(low):
            tags.append(t); imp = max(imp, w)
    sent = len(_POS_RX.findall(low)) - len(_NEG_RX.findall(low))
    syms = set(_CODE_RE.findall(title))
    for sym, rx in _NAME_RX.items():
        if rx.search(low):
            syms.add(sym)
    return tags, imp, sent, sorted(syms)


def fetch_news(hours: int = 48) -> pd.DataFrame:
    with ThreadPoolExecutor(8) as ex:
        rows = [r for rs in ex.map(_fetch, FEEDS.items()) for r in rs]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates("Başlık")
    cutoff = dt.datetime.now(TZ) - dt.timedelta(hours=hours)
    df = df[df["Zaman"].isna() | (df["Zaman"] >= cutoff)]
    t = df["Başlık"].map(tag)
    df["Etiket"] = t.map(lambda x: ", ".join(x[0]))
    df["Önem"] = t.map(lambda x: x[1])
    df["Yön"] = t.map(lambda x: "🟢" if x[2] > 0 else ("🔴" if x[2] < 0 else "⚪"))
    df["Skor"] = t.map(lambda x: x[2])
    df["Hisse"] = t.map(lambda x: ", ".join(x[3]))
    return df.sort_values("Zaman", ascending=False, na_position="last").reset_index(drop=True)


def ticker_sentiment(news: pd.DataFrame) -> dict[str, int]:
    out: dict[str, int] = {}
    if news is None or news.empty:
        return out
    for _, r in news.iterrows():
        for s in filter(None, r["Hisse"].split(", ")):
            out[s] = out.get(s, 0) + int(r["Skor"])
    return out
