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

from core import data, journal, news, risk, signals, swing, viop
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
    v_risk = st.slider("VİOP işlem başı risk (% VİOP bakiye)", 1.0, 15.0, 5.0, 0.5,
                       help="Stop olursan VİOP bakiyesinin bu kadarını kaybedersin. Yarışmada VİOP küçük bir "
                            "kısım olduğu için hisseden yüksek tutulabilir.")
    v_max_lev = st.slider("En fazla kaldıraç (nominal / VİOP bakiye)", 1.0, 10.0, 4.0, 0.5,
                          help="Açtığın kontratların toplam büyüklüğü bakiyenin en fazla kaç katı olsun.")
    v_max_margin = st.slider("Teminata en fazla (% VİOP bakiye)", 10, 90, 60, 5)
    tl_rate = st.number_input("TL faizi (yıllık %, taşıma maliyeti için)", value=35.0, step=1.0,
                              help="TCMB politika faizine yakın bir değer gir. VİOP sekmesindeki baz hesabı "
                                   "gerçek taşıma maliyetini zaten gösterir.") / 100
    st.divider()
    auto = st.toggle("Otomatik yenile (5 dk)", value=True)
    if st.button("🔄 Verileri şimdi yenile", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ---------------- veri (önbellekli) ----------------
@st.cache_data(ttl=300, show_spinner="BIST verileri çekiliyor…")
def load_intraday():
    return data.download(BIST100, "30d", "5m")


@st.cache_data(ttl=1800, show_spinner="Günlük veriler çekiliyor…")
def load_daily():
    return data.download(BIST100 + list(INDEXES.values()), "3y", "1d")


@st.cache_data(ttl=1800, show_spinner="VİOP dayanak verileri çekiliyor…")
def load_viop():
    return data.download(["GC=F", "SI=F", "XU030.IS", "USDTRY=X"], "3y", "1d")


@st.cache_data(ttl=6 * 3600, show_spinner="Momentum stratejisi 3 yıllık veride test ediliyor…")
def swing_bt():
    return swing.backtest_breakout(load_daily())


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

tabs = st.tabs(["🚀 Momentum", "📊 VİOP", "⚡ Gün içi", "🔎 Hisse", "📰 Haberler", "🧮 Risk", "📒 Günlük",
                "📋 Plan"])
T_MOM, T_VIOP, T_INTRA, T_STOCK, T_NEWS, T_RISK, T_JOURNAL, T_PLAN = tabs


# ================= MOMENTUM (hisse swing) =================
with T_MOM:
    dd_all = load_daily()
    xu = dd_all.get("XU100.IS")
    if xu is not None:
        reg = swing.market_regime(xu)
        if reg["yukarı"]:
            st.success(f"**Piyasa trendi: YUKARI** · BIST 100 haftalık, 10 haftalık ortalamanın "
                       f"%{reg['uzaklık%']:+.1f} üstünde → momentum alımları için uygun ortam.")
        else:
            st.warning(f"**Piyasa trendi: AŞAĞI/ZAYIF** · BIST 100, 10 haftalık ortalamanın "
                       f"%{reg['uzaklık%']:+.1f} altında. Testte rotasyon stratejisi bu dönemlerde **nakitte** "
                       f"bekliyordu → yeni alımları küçük tut, pozisyon sayısını azalt.")
    sc = swing.scan(dd_all)
    if sc.empty:
        st.warning("Veri yok.")
    else:
        def size(r):
            z = risk.stock_size(eq, cash, r["Son"], r["Stop (10G dip)"], risk_pct, max_pos, comm)
            return pd.Series({"Lot": z.get("lot", 0), "Tutar": round(z.get("tutar", 0))})
        sc[["Lot", "Tutar"]] = sc.apply(size, axis=1)
        brk = sc[sc["Sinyal"] == "KIRILIM AL"].sort_values("Momentum sırası")
        trd = sc[sc["Sinyal"] == "TRENDDE"].sort_values("Momentum sırası")
        top = sc[sc["50G ort üstü"]].sort_values("Momentum sırası").head(10)
        cols = ["Sembol", "Sinyal", "Son", "Gün%", "1A%", "3A%", "Hacim x", "Stop (10G dip)", "Risk%", "RSI",
                "Momentum sırası", "Lot", "Tutar"]
        cfg = {"Sembol": st.column_config.TextColumn(pinned=True),
               "Stop (10G dip)": st.column_config.NumberColumn(help="Kapanış bunun altına inerse sat"),
               "Risk%": st.column_config.NumberColumn(help="Girişten stop'a uzaklık. %8 üstü ise lot küçülür."),
               "Hacim x": st.column_config.NumberColumn(
                   help="Bugünkü hacim / 20 günlük ortalama. Seans içinde gün bitmediği için düşük görünür; "
                        "kırılım teyidi için 17:00 sonrasına bak."),
               "Momentum sırası": st.column_config.NumberColumn(help="Son 3 ayın getirisine göre sıra (1 = en güçlü)")}

        st.markdown(f"#### 🚀 Bugün kırılım yapanlar ({len(brk)})")
        st.caption("20 günlük zirveyi **1,5x hacimle** kırdı ve 50 günlük ortalamanın üstünde. "
                   "Testte: ertesi açılışta al, kapanış 10 günlük dibin altına inince sat.")
        if brk.empty:
            st.info("Bugün kriterleri sağlayan kırılım yok. (Gün içinde değişebilir; kapanışa doğru tekrar bak.)")
        else:
            st.dataframe(brk[cols], hide_index=True, use_container_width=True, column_config=cfg)

        st.markdown(f"#### 📈 Son 5 günde kırılım yapıp trendde kalanlar ({len(trd)})")
        if not trd.empty:
            st.dataframe(trd[cols], hide_index=True, use_container_width=True, column_config=cfg)

        st.markdown("#### 🏆 Momentum ilk 10 (son 3 ay, 50G ortalama üstü)")
        st.caption("Haftalık rotasyon: her cuma ilk 5'i tut, listeden düşeni sat. Piyasa trendi AŞAĞI iken nakitte bekle.")
        st.dataframe(top[cols], hide_index=True, use_container_width=True, column_config=cfg)

        ex = sc[sc["Sinyal"] == "ÇIKIŞ"]
        if len(ex):
            with st.expander(f"🔻 10 günlük dibin altına inenler ({len(ex)}) — elinde varsa SAT"):
                st.dataframe(ex[cols], hide_index=True, use_container_width=True)

        with st.expander("📊 Bu strateji geçmişte ne yaptı? (3 yıl, tüm hisseler)"):
            bt = swing_bt()
            cut = pd.Timestamp.now(tz="Europe/Istanbul") - pd.Timedelta(days=548)
            s_all, s_rec = swing.bt_summary(bt), swing.bt_summary(bt, cut)
            st.dataframe(pd.DataFrame({"3 yıl": s_all, "Son 1,5 yıl": s_rec}), use_container_width=True)
            st.caption("Kazanma oranı düşük (%40 civarı) ama kazananlar kaybedenlerden çok daha büyük; ortalamayı onlar "
                       "taşıyor. Bu yüzden **stop'a sadık kal, kazananı erken satma.** Uyarı: test bugünkü BIST 100 "
                       "listesiyle yapıldı (geçmişte yükselenler listede kaldığı için sonuçlar olduğundan iyi görünebilir). "
                       "Aşırı uç sonuçlar (veri hatası şüphesi) hariç tutuldu.")


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


with T_INTRA:
    st.error("⚠️ **Dürüst uyarı:** Bu gün içi AL algoritması son 60 işlem gününde ileriye bakmadan test edildi: "
             "518 işlem, %39 kazanma, işlem başı ortalama **−0,05R** (yani zarar). Tek başına para kazandırmıyor. "
             "Bu sekmeyi giriş zamanlaması ve gün içi takip için kullan; **hisse seçimini Momentum sekmesinden yap.**")
    (st.fragment(run_every=300)(render_scanner) if auto else render_scanner)()


# ================= 2) HİSSE ANALİZİ =================
with T_STOCK:
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


with T_NEWS:
    (st.fragment(run_every=600)(render_news) if auto else render_news)()


# ================= 4) VİOP =================
with T_VIOP:
    st.caption(f"VİOP bakiyesi {v_eq:,.0f} TL · Sistem: günlük **EMA10/30 trend takibi** (hızlı ortalama yavaşın "
               "üstündeyse LONG, altındaysa SHORT). Testler **vadeli taşıma maliyeti dahil** yapıldı.")
    vraw = load_viop()
    rows, sers = [], {}
    for name, spec in viop.INSTRUMENTS.items():
        d = viop.series(vraw, name)
        if d is None or len(d) < 120:
            continue
        sers[name] = d
        sg = viop.signal(d)
        rec = viop.backtest(d, spec["kind"], tl_rate, "L/S").iloc[-375:]
        stt = viop.stats(rec, v_max_lev)
        st1 = viop.stats(rec, 1)
        if name == "BIST 30 Endeks":
            verdict = "⛔ Long yok · SHORT sadece korunma" if sg["yön"] == "SHORT" else "⛔ Long için hisse al"
        elif name == "USD/TRY":
            verdict = "⛔ Long taşıma kaybettirir"
        elif st1["sharpe"] >= 0.5:
            verdict = f"✅ Trend takibi uygun → {sg['yön']}"
        else:
            verdict = "⚠️ Zayıf geçmiş"
        rows.append({"Araç": name, "Trend": sg["yön"], "Başlangıç": sg["başlangıç"].strftime("%d.%m"),
                     "Son": round(sg["son"], 2), "5G%": round(sg["ret5%"], 1), "1A%": round(sg["ret21%"], 1),
                     "Günlük oynaklık%": round(sg["atr%"], 2), "Test yıllık% (1x)": st1["yıllık%"],
                     "Sharpe": st1["sharpe"], f"30g kötü% ({v_max_lev:g}x)": stt["30g kötü (p10)%"],
                     f"30g orta% ({v_max_lev:g}x)": stt["30g orta%"], f"30g iyi% ({v_max_lev:g}x)": stt["30g iyi (p90)%"],
                     "Öneri": verdict})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={"Araç": st.column_config.TextColumn(pinned=True),
                                    "Test yıllık% (1x)": st.column_config.NumberColumn(
                                        help="Son 1,5 yılda bu trend sisteminin kaldıraçsız yıllık getirisi (taşıma dahil)"),
                                    "Sharpe": st.column_config.NumberColumn(help=">0,5 iyi, <0 kötü")})
        st.caption("30g kötü/orta/iyi: son 1,5 yılda herhangi bir 30 günlük dönemde, seçili kaldıraçla VİOP bakiyene "
                   "ne olurdu (en kötü %10, ortanca, en iyi %10). Kaldıraç kazancı da kaybı da aynı oranda büyütür.")

    pick = st.selectbox("Detay", list(sers), index=0)
    d = sers.get(pick)
    if d is not None:
        spec = viop.INSTRUMENTS[pick]
        sg = viop.signal(d)
        st.info(spec["note"])
        x = d.iloc[-130:]
        fig = go.Figure(go.Candlestick(x=x.index, open=x.Open, high=x.High, low=x.Low, close=x.Close, name=pick))
        fig.add_trace(go.Scatter(x=x.index, y=d.Close.ewm(span=10).mean().iloc[-130:], name="EMA10", line=dict(width=1.5)))
        fig.add_trace(go.Scatter(x=x.index, y=d.Close.ewm(span=30).mean().iloc[-130:], name="EMA30", line=dict(width=1.5)))
        fig.add_hline(y=sg["stop"], line_dash="dot", line_color="#d62728", annotation_text="Stop")
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False,
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
        st.write(f"**Trend: {sg['yön']}** ({sg['başlangıç']:%d.%m.%Y}'den beri) · son {sg['son']:,.2f} · "
                 f"önerilen stop (spot) **{sg['stop']:,.2f}** · EMA10/EMA30 farkı %{sg['fark%']:+.2f}")

        modes = {"Trend L/S": "L/S", "Sadece long": "long", "Sadece short": "short",
                 "Al-tut (long)": "hold_long", "Sürekli short (taşıma kazancı)": "hold_short"}
        tbl = {k: viop.stats(viop.backtest(d, spec["kind"], tl_rate, m).iloc[-375:], 1) for k, m in modes.items()}
        with st.expander("Strateji karşılaştırması (son 1,5 yıl, 1x, taşıma dahil)"):
            st.dataframe(pd.DataFrame(tbl).T, use_container_width=True)

        st.markdown("#### 🧾 Taşıma maliyeti (baz) — Matriks'ten vadeli fiyatı gir")
        b1, b2 = st.columns(2)
        fut = b1.number_input("Vadeli kontrat fiyatı", value=0.0, step=0.01, key=f"fut_{pick}")
        dte = b2.number_input("Vadeye kalan gün", value=30, step=1, key=f"dte_{pick}")
        spot_conv = sg["son"]
        if fut > 0:
            bs = viop.basis(spot_conv, fut, int(dte))
            if bs:
                st.write(f"Vadeli spottan **%{bs['baz%']:+.2f}** farklı (yıllık %{bs['yıllık%']:.1f}, aylık "
                         f"%{bs['aylık%']:.2f}). LONG açarsan başa baş için dayanağın vadeye kadar en az bu kadar "
                         f"yükselmesi gerekir; SHORT açarsan bu fark lehine çalışır.")
                st.caption("Not: Spot fiyat Yahoo'dan ve gecikmeli; birim farkı varsa (ör. endeks puanı) baz yanlış çıkar, "
                           "o zaman Matriks'teki spot ile kendin karşılaştır.")

        st.markdown("#### 🧮 Kontrat hesabı")
        k1, k2, k3 = st.columns(3)
        kp = k1.number_input("Kontrat fiyatı", value=float(fut) if fut else 0.0, step=0.01, key=f"kp_{pick}")
        mult = k2.number_input("Kontrat büyüklüğü / çarpan", value=1.0, step=0.1, key=f"mul_{pick}",
                               help="1 fiyat biriminin kaç TL ettiği (Matriks kontrat detayı). $ bazlı kontratta "
                                    "dolar kuruyla çarp.")
        marg = k3.number_input("Kontrat başı teminat (TL)", value=0.0, step=100.0, key=f"mar_{pick}")
        side_long = sg["yön"] == "LONG"
        ratio = kp / sg["son"] if kp > 0 else 1
        stop_k = round(sg["stop"] * ratio, 4) if kp else 0.0
        ks = st.number_input("Stop (kontrat fiyatıyla)", value=float(stop_k), step=0.01, key=f"ks_{pick}",
                             help="Trend stop'unun kontrat fiyatına çevrilmiş hali")
        if kp > 0 and mult > 0 and ks > 0 and abs(kp - ks) > 0:
            risk_pc = abs(kp - ks) * mult
            n_risk = v_eq * v_risk / 100 / risk_pc
            n_lev = v_eq * v_max_lev / (kp * mult)
            n_mar = (v_eq * v_max_margin / 100 / marg) if marg > 0 else float("inf")
            n = int(max(0, min(n_risk, n_lev, n_mar)))
            lim = min([("risk", n_risk), ("kaldıraç", n_lev), ("teminat", n_mar)], key=lambda t: t[1])[0]
            nom = n * kp * mult
            move = sg["atr%"] / 100 * kp * mult * n
            st.success(f"**{n} kontrat {'AL (LONG)' if side_long else 'SAT (SHORT)'}** · nominal {nom:,.0f} TL "
                       f"(**{nom / v_eq:.1f}x** kaldıraç) · stop olursa ≈ {n * risk_pc:,.0f} TL "
                       f"(%{n * risk_pc / v_eq * 100:.1f}) · {lim} sınırladı")
            st.write(f"Günlük ortalama hareket (1 ATR) ≈ **±{move:,.0f} TL** · %5'lik hareket ≈ "
                   f"**±{nom * 0.05:,.0f} TL** (VİOP bakiyenin %{nom * 0.05 / v_eq * 100:.0f}'i)")
        else:
            st.caption("Kontrat fiyatı, çarpan ve stop girince kaç kontrat açacağını hesaplarım.")
        st.caption("Kural: Trend yönü değişince (EMA10 EMA30'u keserse) pozisyonu çevir veya kapat. Stop'u her gün "
                   "trend yönünde güncelle, asla geri çekme. VİOP'ta akşam seansı ve hafta sonu boşluk riski var.")


# ================= 5) RİSK =================
with T_RISK:
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
with T_JOURNAL:
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
with T_PLAN:
    st.markdown("""
#### Testlerden çıkan dersler
| Ne denendi | Sonuç | Karar |
|---|---|---|
| Gün içi açılış kırılımı (AL sinyali), 60 gün | İşlem başı −0,05R, %39 kazanma | ❌ Tek başına kullanma |
| Hisse: 20G zirve + hacim kırılımı, 3 yıl | İşlem başı ort. +%1,6 (son 1,5 yıl +%2,5), ~19 gün tutma | ✅ **Ana hisse stratejisi** |
| Hisse: haftalık momentum ilk 5 | Son 1,5 yıl haftalık +%1,9 (endeks ~+%0,3) | ✅ Piyasa trendi yukarıyken |
| VİOP BIST30 / USD-TRY long | Taşıma maliyeti yüzünden zarar | ❌ Long açma |
| VİOP ons altın / gümüş trend takibi | Son 1,5 yıl yıllık +%25 / +%44 (gümüş çok oynak) | ✅ **Ana VİOP stratejisi** |

#### Bakiye planı (275.000 TL, 5 hafta)
- **Hisse 200.000 TL:** Aynı anda **4-5 momentum pozisyonu**, her biri bakiyenin %20-35'i. İşlem başı risk %1,5-2
  (stop = 10 günlük dip). Piyasa trendi AŞAĞI iken 2-3 pozisyona in, kalan nakitte beklesin.
- **VİOP 75.000 TL:** **Altın (ons) ana pozisyon**, trend yönünde. İsteğe bağlı küçük gümüş. Kaldıraç 2-4x,
  işlem başı risk VİOP bakiyesinin %5'i. BIST30 vadeliyi yalnız piyasa trendi AŞAĞI iken **short ile korunma** için kullan.

#### Günlük rutin
| Saat | Ne yap |
|---|---|
| **09:30** | Ayarlar: bakiyeleri güncelle. **Haberler** → 🔥 Önemli. |
| **10:00-10:30** | İşlem yok. Açılış oynaklığı geçsin. |
| **10:30-11:30** | **📊 VİOP**: trend yönü değişti mi? Stop'u güncelle. **🚀 Momentum**: elindeki hisselerden "ÇIKIŞ" listesine düşen var mı? Varsa sat. |
| **17:00-17:50** | **🚀 Momentum → Bugün kırılım yapanlar**. Kapanışa yakın kırılımı teyit edilenlerden en yüksek momentumlu 1-2 tanesini al (kapanışta veya ertesi sabah). **⚡ Gün içi** sekmesi giriş zamanlaması için yardımcıdır. |
| **18:00 sonrası** | **Günlük**'e yaz, CSV indir. |
| **Cuma** | Momentum ilk 5 listesine bak: listeden çok düşmüş, zayıflamış pozisyonları güçlülerle değiştir. |

#### Altın kurallar
1. **Stop'a sadık kal, kazananı erken satma.** Stratejinin kârı az sayıdaki büyük kazançtan geliyor (%40 kazanma, büyük ortalama).
2. **Kaybedeni büyütme, ortalama düşürme yapma.**
3. **Sıralama taktiği:** İlk 2 hafta normal risk. Son 1-2 haftada sıralamada gerideysen hisse riskini %2,5-3'e, VİOP kaldıracını 5-6x'e çıkar;
   öndeysen riski yarıya indir ve koru. (Kaldıraç kaybı da aynı oranda büyütür.)
4. **Haber günleri:** PPK faiz kararı, TÜFE (ayın 3'ü 10:00), ABD Fed/enflasyon verisi (altını etkiler) öncesi pozisyonu küçült.

> Geçmiş test gelecek garantisi değildir. Bu uygulama olasılık verir; son karar ve emir senin.
""")
