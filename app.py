"""BIST Yarışma Asistanı - HEK Investing (200.000 TL hisse + 75.000 TL VİOP, 5 hafta).

Çalıştır:  streamlit run app.py
Emirleri Matriks'ten SEN girersin. Bu uygulama tarar, hesaplar, hatırlatır.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from core import data, journal, news, risk, signals
from core.universe import BIST100, INDEXES, MACRO

st.set_page_config(page_title="BIST Yarışma Asistanı", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown("""
<style>
.block-container {padding-top: 3rem; padding-left: .8rem; padding-right: .8rem;}
[data-testid="stMetricValue"] {font-size: 1.25rem;}
div[data-testid="stTabs"] button p {font-size: .95rem;}
</style>""", unsafe_allow_html=True)


def secret(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


# ---------------- isteğe bağlı şifre ----------------
pw = secret("APP_PASSWORD")
if pw and not st.session_state.get("ok"):
    x = st.text_input("Şifre", type="password")
    if x == pw:
        st.session_state.ok = True
        st.rerun()
    st.stop()

# ---------------- ayarlar ----------------
with st.sidebar:
    st.header("⚙️ Ayarlar")
    st.caption("Yarışma: 200.000 TL hisse + 75.000 TL VİOP")
    eq = st.number_input("Hisse bakiyesi (güncel, TL)", value=200_000.0, step=1000.0)
    cash = st.number_input("Kullanılabilir nakit (TL)", value=200_000.0, step=1000.0)
    risk_pct = st.slider("İşlem başı risk (% bakiye)", 0.5, 5.0, 1.5, 0.25,
                         help="Stop olursan bakiyenin en fazla bu kadarını kaybedersin.")
    max_pos = st.slider("Tek hisseye en fazla (% bakiye)", 10, 100, 35, 5)
    rr = st.slider("Hedef (risk'in kaç katı)", 1.0, 4.0, 2.0, 0.25)
    comm = st.number_input("Komisyon (tek yön, %)", value=0.04, step=0.01, format="%.3f") / 100
    st.divider()
    daily_loss = st.number_input("Günlük zarar limiti (%)", value=3.0, step=0.5)
    max_trades = st.number_input("Günlük max işlem", value=6, step=1)
    max_open = st.number_input("Max açık pozisyon", value=4, step=1)
    min_rr = st.number_input("Min ödül/risk", value=1.5, step=0.1)
    st.divider()
    st.subheader("VİOP")
    v_eq = st.number_input("VİOP bakiyesi (TL)", value=75_000.0, step=1000.0)
    v_mult = st.number_input("Kontrat çarpanı", value=10.0, step=1.0,
                             help="Matriks'te kontrat detayından kontrol et (1 puanın TL değeri).")
    v_margin = st.number_input("Kontrat başı başlangıç teminatı (TL)", value=0.0, step=100.0,
                               help="Matriks'te emir ekranında görünür. Girmeden kontrat hesaplanmaz.")
    v_max_margin = st.slider("Teminata en fazla (% VİOP bakiye)", 10, 90, 50, 5)
    st.divider()
    auto = st.toggle("Otomatik yenile (5 dk)", value=True)
    if st.button("🔄 Verileri şimdi yenile", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ---------------- veri (önbellekli) ----------------
@st.cache_data(ttl=300, show_spinner="BIST verileri çekiliyor…")
def load_intraday():
    return data.download(BIST100, "30d", "5m")


@st.cache_data(ttl=3600, show_spinner=False)
def load_daily():
    return data.download(BIST100 + list(INDEXES.values()), "1y", "1d")


@st.cache_data(ttl=300, show_spinner=False)
def load_market():
    syms = list(INDEXES.values()) + list(MACRO.values())
    return data.download(syms, "5d", "5m"), data.download(syms, "3mo", "1d")


@st.cache_data(ttl=600, show_spinner="Haberler çekiliyor…")
def load_news():
    return news.fetch_news(48)


@st.cache_data(ttl=1800, show_spinner="Zaman makinesi tüm hisselerde çalışıyor…")
def universe_bt(rr_: float, comm_: float):
    d5 = load_intraday()
    out, allr = {}, []
    for k, v in d5.items():
        b = signals.backtest(v, rr=rr_, commission=comm_)
        n_days = len(set(v.index.date)) - 1
        out[k.replace(".IS", "")] = signals.summarize(b, n_days)
        allr += list(b["R"])
    return out, np.array(allr)


def tg_send(text: str) -> bool:
    tok, chat = secret("TELEGRAM_TOKEN"), secret("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=10)
    return r.ok


def pct_change(df_d: dict, df_i: dict, sym: str):
    d, i = df_d.get(sym), df_i.get(sym)
    if d is None or len(d) < 2:
        return None, None
    last = float(i["Close"].iloc[-1]) if i is not None and not i.empty else float(d["Close"].iloc[-1])
    # önceki günün kapanışı
    today = (i.index[-1].date() if i is not None and not i.empty else d.index[-1].date())
    prev = d[d.index.date < today]["Close"]
    base = float(prev.iloc[-1]) if len(prev) else float(d["Close"].iloc[-2])
    return last, (last / base - 1) * 100


def build_scan():
    d5, dd = load_intraday(), load_daily()
    try:
        nws = load_news()
    except Exception:
        nws = pd.DataFrame()
    sent = news.ticker_sentiment(nws)
    bt, _ = universe_bt(rr, comm)
    rows = []
    for s in BIST100:
        a = signals.analyze(s, d5.get(f"{s}.IS"), dd.get(f"{s}.IS"), rr=rr)
        if not a:
            continue
        b = bt.get(s, {})
        a["Geçmiş kurulum"] = b.get("kurulum", 0)
        a["Geçmiş kazanma%"] = b.get("kazanma%")
        a["Geçmiş ort R"] = b.get("ort_R")
        a["Haber"] = sent.get(s, 0)
        g = a["Puan"]
        if b.get("kurulum", 0) >= 5:
            g += 1 if b["ort_R"] >= 0.3 else (-1 if b["ort_R"] < 0 else 0)
        g += int(np.sign(a["Haber"]))
        a["Güç"] = g
        sz = risk.stock_size(eq, cash, a["Giriş"], a["Stop"], risk_pct, max_pos, comm)
        a["Lot"] = sz.get("lot", 0)
        a["Tutar"] = round(sz.get("tutar", 0))
        rows.append(a)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Geçmişte bu kural bu hissede zarar ettirdiyse AL'ı İZLE'ye düşür
    weak_hist = (df["Geçmiş kurulum"] >= 5) & (df["Geçmiş ort R"] < 0)
    df.loc[(df["Sinyal"] == "AL") & weak_hist, "Sinyal"] = "İZLE"
    order = {"AL": 0, "İZLE": 1, "-": 2, "ZAYIF": 3}
    return df.sort_values(["Sinyal", "Güç"], key=lambda c: c.map(order) if c.name == "Sinyal" else -c)


# ---------------- başlık ----------------
is_open, status = data.market_status()
now = data.now_tr()
st.markdown(f"### 📈 BIST Yarışma Asistanı  \n{'🟢' if is_open else '🔴'} **{status}** · {now:%d.%m.%Y %H:%M} (TR)")
st.caption("Fiyatlar Yahoo Finance'ten, ~15 dk gecikmeli. Emir vermeden önce fiyatı Matriks'te kontrol et. "
           "Yatırım tavsiyesi değildir.")

tabs = st.tabs(["📡 Tarayıcı", "🔎 Hisse", "📰 Haberler", "📊 VİOP", "🧮 Risk", "📒 Günlük", "📋 Plan"])


# ================= 1) TARAYICI =================
def render_scanner():
    mi, md = load_market()
    parts = []
    for name, sym in list(INDEXES.items()) + list(MACRO.items()):
        last, ch = pct_change(md, mi, sym)
        if last is not None:
            col = "green" if ch >= 0 else "red"
            parts.append(f"**{name}** {last:,.2f} :{col}[{ch:+.2f}%]")
    st.markdown(" · ".join(parts))

    df = build_scan()
    if df.empty:
        st.warning("Veri gelmedi. Biraz sonra yenile.")
        return
    al = df[df["Sinyal"] == "AL"]
    st.markdown(f"🟢 **AL: {len(al)}** · 👀 İzle: {int((df['Sinyal'] == 'İZLE').sum())} · "
                f"Yükselen/Düşen: {int((df['Değ%'] > 0).sum())}/{int((df['Değ%'] < 0).sum())} · "
                f"Son veri: {df['Zaman'].max()}")

    view = st.radio("Göster", ["AL + İZLE", "Sadece AL", "Hepsi"], horizontal=True, label_visibility="collapsed")
    if view == "Sadece AL":
        df = df[df["Sinyal"] == "AL"]
    elif view == "AL + İZLE":
        df = df[df["Sinyal"].isin(["AL", "İZLE"])]

    show = ["Sembol", "Sinyal", "Güç", "Son", "Değ%", "Hacim x", "Giriş", "Stop", "Hedef", "R/R", "Lot", "Tutar",
            "Geçmiş kurulum", "Geçmiş kazanma%", "Geçmiş ort R", "Haber", "Neden"]
    st.dataframe(
        df[show], hide_index=True, use_container_width=True, height=min(640, 38 + 35 * max(len(df), 1)),
        column_config={
            "Sembol": st.column_config.TextColumn(pinned=True),
            "Değ%": st.column_config.NumberColumn(format="%.2f%%"),
            "Hacim x": st.column_config.NumberColumn(help="Bugün şu saate kadarki hacim / son 10 günün aynı saatteki ortalaması"),
            "Lot": st.column_config.NumberColumn(help="Ayarlardaki risk % ile önerilen adet"),
            "Geçmiş ort R": st.column_config.NumberColumn(help="Aynı kural son ~30 günde bu hissede ortalama kaç R kazandırdı. >0.3 iyi, <0 kötü"),
            "Haber": st.column_config.NumberColumn(help="Son 48 saatteki haberlerin olumlu(+)/olumsuz(-) skoru"),
        })
    st.caption("**AL** = açılış aralığı (10:00-10:30) yukarı kırıldı + VWAP üstü + hacim var + trend destekliyor. "
               "**Stop'u Matriks'te hemen gir**, hedefe gelince sat; gün sonunda pozisyonu taşıma kararını bilinçli ver.")

    if len(al) and secret("TELEGRAM_TOKEN"):
        if st.button("📲 AL sinyallerini Telegram'a gönder"):
            msg = "<b>BIST AL sinyalleri</b>\n" + "\n".join(
                f"{r.Sembol}: giriş {r.Giriş} stop {r.Stop} hedef {r.Hedef} lot {r.Lot}" for r in al.itertuples())
            st.success("Gönderildi") if tg_send(msg) else st.error("Gönderilemedi")


with tabs[0]:
    (st.fragment(run_every=300)(render_scanner) if auto else render_scanner)()


# ================= 2) HİSSE ANALİZİ =================
with tabs[1]:
    sym = st.selectbox("Hisse", BIST100, index=BIST100.index("THYAO"))
    d5, dd = load_intraday(), load_daily()
    df5, dfd = d5.get(f"{sym}.IS"), dd.get(f"{sym}.IS")
    if df5 is None:
        st.warning("Bu hisse için veri yok.")
    else:
        a = signals.analyze(sym, df5, dfd, rr=rr)
        c = st.columns(4)
        c[0].metric("Sinyal", a["Sinyal"], f"puan {a['Puan']}")
        c[1].metric("Son", a["Son"], f"{a['Değ%']:+.2f}%")
        c[2].metric("Göreli hacim", a["Hacim x"])
        c[3].metric("R/R", a["R/R"])
        st.write(f"**Giriş** {a['Giriş']} · **Stop** {a['Stop']} · **Hedef** {a['Hedef']}  \n_{a['Neden']}_")

        days = sorted(set(df5.index.date))[-2:]
        g = df5[np.isin(df5.index.date, days)]
        today = df5[df5.index.date == days[-1]]
        fig = go.Figure(go.Candlestick(x=g.index, open=g.Open, high=g.High, low=g.Low, close=g.Close, name=sym))
        fig.add_trace(go.Scatter(x=today.index, y=signals.vwap(today), name="VWAP", line=dict(width=1.5)))
        for y, n, col in [(a["ORB üst"], "ORB üst", "#888"), (a["ORB alt"], "ORB alt", "#888"),
                          (a["Stop"], "Stop", "#d62728"), (a["Hedef"], "Hedef", "#2ca02c")]:
            fig.add_hline(y=y, line_dash="dot", line_color=col, annotation_text=n, annotation_position="right")
        fig.update_layout(height=420, margin=dict(l=0, r=0, t=20, b=0), xaxis_rangeslider_visible=False,
                          xaxis=dict(rangebreaks=[dict(bounds=[18.2, 10], pattern="hour")]), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)

        if dfd is not None:
            x = dfd.iloc[-130:]
            f2 = go.Figure(go.Candlestick(x=x.index, open=x.Open, high=x.High, low=x.Low, close=x.Close, name="Günlük"))
            f2.add_trace(go.Scatter(x=x.index, y=dfd.Close.ewm(span=20).mean().iloc[-130:], name="EMA20", line=dict(width=1)))
            f2.add_trace(go.Scatter(x=x.index, y=dfd.Close.ewm(span=50).mean().iloc[-130:], name="EMA50", line=dict(width=1)))
            f2.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False,
                             legend=dict(orientation="h"))
            with st.expander("Günlük grafik (6 ay)"):
                st.plotly_chart(f2, use_container_width=True)

        st.subheader("⏳ Zaman makinesi")
        st.caption("Aynı kural (açılış aralığı kırılımı + VWAP) bu hissenin son ~30 işlem gününde tek tek denendi.")
        bt = signals.backtest(df5, rr=rr, commission=comm)
        sm = signals.summarize(bt, len(set(df5.index.date)) - 1)
        if sm["kurulum"] == 0:
            st.info("Son 30 günde bu kurulum hiç oluşmadı.")
        else:
            c = st.columns(5)
            c[0].metric("Kurulum günü", f"{sm['kurulum']}/{sm['gün']}")
            c[1].metric("Önce hedef", f"%{sm['hedef%']}")
            c[2].metric("Önce stop", f"%{sm['stop%']}")
            c[3].metric("Kapanışta açık", f"%{sm['kapanış%']}")
            c[4].metric("Ortalama", f"{sm['ort_R']} R", f"{sm['ort_getiri%']}%")
            if sm["kurulum"] < 5:
                st.warning("5'ten az örnek var, istatistiğe fazla güvenme.")
            mc = signals.monte_carlo(bt["R"].to_numpy(), trades=25, risk_frac=risk_pct / 100)
            p5, p50, p95 = np.percentile(mc, [5, 50, 95])
            st.write(f"**10.000 simülasyon, 25 işlem, işlem başı %{risk_pct} risk:** kötü senaryo (%5) "
                     f"**{(p5 - 1) * 100:+.1f}%**, orta **{(p50 - 1) * 100:+.1f}%**, iyi (%95) **{(p95 - 1) * 100:+.1f}%**")
            with st.expander("Gün gün sonuçlar"):
                st.dataframe(bt, hide_index=True, use_container_width=True)

        nws = load_news()
        if not nws.empty:
            mine = nws[nws["Hisse"].str.contains(rf"\b{sym}\b", regex=True)]
            st.subheader(f"📰 {sym} haberleri")
            if mine.empty:
                st.caption("Son 48 saatte bu hisseyle eşleşen haber yok. KAP'ı da kontrol et: kap.org.tr")
            for r in mine.head(10).itertuples():
                st.markdown(f"{r.Yön} [{r.Başlık}]({r.Link}) · _{r.Kaynak}_ · {r.Zaman:%d.%m %H:%M}")


# ================= 3) HABERLER =================
def render_news():
    nws = load_news()
    if nws.empty:
        st.warning("Haber çekilemedi.")
        return
    c1, c2 = st.columns([2, 1])
    tags = sorted({t for s in nws["Etiket"] for t in s.split(", ") if t})
    pick = c1.multiselect("Konu", tags, placeholder="Tüm konular")
    only = c2.toggle("Sadece piyasayı ilgilendirenler", value=True)
    x = nws
    if only:
        x = x[x["Önem"] > 0]
    if pick:
        x = x[x["Etiket"].map(lambda s: any(p in s for p in pick))]
    hot = x[x["Önem"] >= 3].head(5)
    if len(hot):
        st.markdown("#### 🔥 Önemli")
        for r in hot.itertuples():
            st.markdown(f"{r.Yön} **[{r.Başlık}]({r.Link})**  \n<small>{r.Etiket} · {r.Kaynak} · "
                        f"{r.Zaman:%d.%m %H:%M}{' · ' + r.Hisse if r.Hisse else ''}</small>", unsafe_allow_html=True)
    st.markdown("#### Akış")
    st.dataframe(x[["Zaman", "Yön", "Başlık", "Etiket", "Hisse", "Kaynak", "Link"]], hide_index=True,
                 use_container_width=True, height=520,
                 column_config={"Zaman": st.column_config.DatetimeColumn(format="DD.MM HH:mm"),
                                "Link": st.column_config.LinkColumn(display_text="aç")})
    st.caption("Kaynaklar: AA, Bloomberg HT, Google Haberler (KAP, TCMB, enflasyon, SPK, politika). "
               "🟢/🔴 kelime bazlı kaba bir yön tahminidir; başlığı kendin oku.")


with tabs[2]:
    (st.fragment(run_every=600)(render_news) if auto else render_news)()


# ================= 4) VİOP =================
with tabs[3]:
    st.caption("VİOP için 75.000 TL. Yahoo'da vadeli kontrat verisi yok; yön BIST 30 endeksi / USDTRY'den hesaplanır, "
               "kontrat fiyatını Matriks'ten gir.")
    under = st.radio("Dayanak", ["BIST 30 (XU030)", "USD/TRY"], horizontal=True)
    usym = "XU030.IS" if under.startswith("BIST") else "USDTRY=X"
    mi, md = load_market()
    i5, d1 = mi.get(usym), md.get(usym)
    if i5 is None or d1 is None:
        st.warning("Veri yok.")
    else:
        if usym.endswith(".IS"):
            i5 = i5.between_time("10:00", "18:05")
        last = float(i5.Close.iloc[-1])
        today = i5[i5.index.date == i5.index[-1].date()]
        e20d = float(d1.Close.ewm(span=20).mean().iloc[-1])
        e20i = float(i5.Close.ewm(span=20).mean().iloc[-1])
        r14 = float(signals.rsi(i5.Close).iloc[-1])
        atr_d = float(signals.atr(d1).iloc[-1])
        up = sum([last > e20d, last > e20i, last > float(today.Open.iloc[0]), r14 > 50])
        bias = "LONG (yükseliş)" if up >= 3 else ("SHORT (düşüş)" if up <= 1 else "NÖTR - bekle")
        c = st.columns(4)
        c[0].metric("Son", f"{last:,.2f}")
        c[1].metric("Yön", bias.split()[0])
        c[2].metric("5dk RSI", f"{r14:.0f}")
        c[3].metric("Günlük ATR", f"{atr_d:,.1f}")
        st.write(f"**Yön önerisi: {bias}** · günlük EMA20 {e20d:,.1f} · 5dk EMA20 {e20i:,.1f}")

        fig = go.Figure(go.Candlestick(x=today.index, open=today.Open, high=today.High, low=today.Low, close=today.Close))
        fig.add_trace(go.Scatter(x=today.index, y=today.Close.ewm(span=20).mean(), name="EMA20"))
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Kontrat hesabı")
        cc = st.columns(3)
        kp = cc[0].number_input("Kontrat fiyatı (Matriks)", value=0.0, step=0.25)
        ratio = kp / last if kp > 0 else 1
        sugg = round(kp - 0.6 * atr_d * ratio if up >= 2 else kp + 0.6 * atr_d * ratio, 2) if kp else 0.0
        ks = cc[1].number_input("Stop", value=sugg, step=0.25, help="Öneri: 0,6 x günlük ATR")
        side = cc[2].selectbox("Yön", ["Uzun (AL)", "Kısa (SAT)"], index=0 if up >= 2 else 1)
        if kp and ks and v_margin > 0:
            vs = risk.viop_size(v_eq, v_margin, v_mult, kp, ks, risk_pct, v_max_margin)
            tgt = kp + (kp - ks) * rr if side.startswith("Uzun") else kp - (ks - kp) * rr
            st.success(f"**{vs['kontrat']} kontrat** · teminat {vs['teminat']:,.0f} TL · stop olursa ≈ "
                       f"{vs['risk_tl']:,.0f} TL zarar · hedef {tgt:,.2f} ({vs['sınırlayan']} sınırladı)")
        elif v_margin <= 0:
            st.info("Ayarlar menüsüne (sol üst ›) kontrat teminatını ve çarpanını gir.")
        st.caption("VİOP kaldıraçlıdır: küçük endeks hareketi bakiyeyi hızlı değiştirir. Gece boyunca pozisyon taşıma "
                   "(akşam seansı) riskini bil.")


# ================= 5) RİSK =================
with tabs[4]:
    st.markdown("#### Hisse pozisyon hesabı")
    c = st.columns(3)
    e = c[0].number_input("Giriş", value=0.0, step=0.01, key="re")
    s_ = c[1].number_input("Stop", value=0.0, step=0.01, key="rs")
    t_ = c[2].number_input("Hedef (ops.)", value=0.0, step=0.01, key="rt")
    if e > 0 and 0 < s_ < e:
        sz = risk.stock_size(eq, cash, e, s_, risk_pct, max_pos, comm)
        rr_ = (t_ - e) / (e - s_) if t_ > e else rr
        st.success(f"**{sz['lot']} lot** · tutar {sz['tutar']:,.0f} TL · stop olursa ≈ {sz['risk_tl']:,.0f} TL "
                   f"(%{sz['risk_%']:.2f}) · {sz['sınırlayan']} sınırladı · R/R {rr_:.2f}")
    j = journal.pnl(journal.load(), comm)
    td = j[j["Tarih"] == f"{now:%Y-%m-%d}"]
    day_pnl = float(td["K/Z TL"].sum()) if len(td) else 0.0
    open_n = int((j["Durum"] == "Açık").sum())
    st.markdown("#### 🛡️ Risk bekçisi")
    rr_check = ((t_ - e) / (e - s_)) if (e > 0 and 0 < s_ < e and t_ > e) else rr
    reasons = risk.guard(day_pnl / eq * 100 if eq else 0, len(td), open_n, rr_check,
                         daily_loss, int(max_trades), int(max_open), min_rr)
    if reasons:
        st.error("**ENGEL**  \n" + "  \n".join(f"• {r}" for r in reasons))
    else:
        st.success(f"**GEÇER** · bugün {len(td)} işlem, K/Z {day_pnl:,.0f} TL, açık pozisyon {open_n}")
    st.caption("Bekçi, Günlük sekmesine girdiğin işlemlerden hesaplar.")


# ================= 6) GÜNLÜK =================
with tabs[5]:
    st.caption("Her işlemi buraya yaz. ⚠️ Bulut sürümünde dosya kalıcı değildir: her gün sonunda **CSV indir**, "
               "gerekirse geri yükle.")
    up_f = st.file_uploader("CSV yükle", type="csv", label_visibility="collapsed")
    if up_f is not None and st.session_state.get("loaded") != up_f.name:
        journal.save(pd.read_csv(up_f))
        st.session_state.loaded = up_f.name
    jdf = journal.load()
    edited = st.data_editor(
        jdf, num_rows="dynamic", use_container_width=True, hide_index=True, key="jed",
        column_config={
            "Tarih": st.column_config.TextColumn(default=f"{now:%Y-%m-%d}"),
            "Piyasa": st.column_config.SelectboxColumn(options=["Hisse", "VİOP"], default="Hisse"),
            "Sembol": st.column_config.TextColumn(),
            "Yön": st.column_config.SelectboxColumn(options=["AL", "SAT"], default="AL",
                                                    help="Hisse alımı = AL. VİOP kısa = SAT"),
            "Çarpan": st.column_config.NumberColumn(default=1.0, help="Hisse 1, VİOP kontrat çarpanı"),
        })
    c1, c2 = st.columns(2)
    if c1.button("💾 Kaydet", use_container_width=True):
        journal.save(edited)
        st.success("Kaydedildi")
    c2.download_button("⬇️ CSV indir", journal.normalize(edited).to_csv(index=False).encode("utf-8"),
                       f"islem_gunlugu_{now:%Y%m%d}.csv", "text/csv", use_container_width=True)
    p = journal.pnl(edited, comm)
    closed = p[p["Durum"] == "Kapalı"]
    if len(closed):
        tot = closed["K/Z TL"].sum()
        start = 275_000
        c = st.columns(4)
        c[0].metric("Toplam K/Z", f"{tot:,.0f} TL", f"{tot / start * 100:+.2f}%")
        c[1].metric("İşlem", len(closed))
        c[2].metric("Kazanma", f"%{(closed['K/Z TL'] > 0).mean() * 100:.0f}")
        w, l = closed.loc[closed["K/Z TL"] > 0, "K/Z TL"].mean(), closed.loc[closed["K/Z TL"] < 0, "K/Z TL"].mean()
        c[3].metric("Ort. kazanç / kayıp", f"{(w or 0):,.0f} / {(l or 0):,.0f}")
        curve = closed.groupby("Tarih")["K/Z TL"].sum().cumsum() + start
        st.line_chart(curve, height=220)
        st.dataframe(p[["Tarih", "Sembol", "Yön", "Adet", "Giriş", "Çıkış", "K/Z TL", "K/Z %", "Durum"]],
                     hide_index=True, use_container_width=True)


# ================= 7) PLAN =================
with tabs[6]:
    st.markdown("""
#### Günlük rutin (TR saati)
| Saat | Ne yap |
|---|---|
| **09:00-09:40** | **Haberler** sekmesi: TCMB, enflasyon, politika, KAP. Gece ABD ve Asya nasıl kapandı? Önemli olumsuz haber varsa bugün küçük oyna. |
| **10:00-10:30** | **İşlem yapma**, açılış aralığının oluşmasını bekle. VİOP yönüne bak. |
| **10:30-12:30** | **Tarayıcı**: `AL` sinyalleri. Geçmiş ort R > 0 ve hacim > 1,5x olanları seç. **Hisse** sekmesinde grafiğe bak, Matriks'te fiyatı teyit et, **Risk** sekmesindeki lot ile emir gir ve **stop emrini hemen koy**. |
| **12:30-16:00** | Yeni giriş az. Hedefe gelenleri sat, kârdaki pozisyonda stop'u girişe çek (başa baş). |
| **16:00-17:50** | ABD açılışı (16:30) oynaklık getirir. Günlük işlemleri kapatmayı düşün. |
| **18:00 sonrası** | **Günlük** sekmesine işlemleri yaz, CSV indir. Ne işe yaradı, ne yaramadı? |

#### Yarışma stratejisi (5 hafta, 275.000 TL)
- **Kural 1 - büyük kayıp yok:** Tek işlemde bakiyenin %1,5-2'sinden fazla riske girme. Günde %3 kayıp = o gün biter.
- **Kural 2 - kazananı büyüt:** Hedef stop'un en az 2 katı. %40 kazanma oranıyla bile 2R hedef kâr bırakır.
- **Kural 3 - az ama iyi işlem:** Günde 2-4 kaliteli işlem, onlarca rastgele işlemden iyidir (komisyon da yer).
- **Sıralamaya göre ayar:** İlk 2 hafta temkinli (%1-1,5 risk). Son hafta sıralamada gerideysen riski %2-3'e çıkar, öndeysen düşür ve koru.
- **VİOP (75.000 TL):** Yalnız yön netken (LONG/SHORT) ve en fazla 1-2 kontratla gir. Teminatın yarısından fazlasını kullanma.
- **Bakiye dağılımı:** %80 hisse / %20 VİOP zaten yarışmanın kuralı. Hisse tarafında aynı anda 3-4 pozisyondan fazlası takibi zorlaştırır.
- **Haber günleri:** PPK faiz kararı, TÜFE açıklaması (ayın 3'ü, 10:00) ve büyük politik olay günlerinde pozisyonu küçült.

> Bu uygulama olasılık verir, kesinlik değil. Son karar ve emir senin.
""")
