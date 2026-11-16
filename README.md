# 📈 BIST Yarışma Asistanı

HEK Investing yarışması için hazırlandı: 200.000 TL hisse ve 75.000 TL VİOP, 5 hafta.
Uygulama piyasayı tarar, haberleri izler, giriş/stop/hedef ve lot hesabını yapar.
**Emirleri Matriks Web Trader'dan sen girersin.**

## Ne yapar?

| Sekme | İşlevi |
|---|---|
| 📡 Tarayıcı | 104 BIST hissesini 5 dakikalık mumlarla tarar. Açılış aralığı kırılımı, VWAP, göreli hacim ve günlük trende bakarak **AL / İZLE / ZAYIF** sinyali verir. Her sinyal için giriş, stop, hedef ve lot önerir. Her hissenin geçmiş başarısını da gösterir. |
| 🔎 Hisse | Seçilen hissenin grafiği (VWAP, açılış aralığı, stop ve hedef çizgileriyle). **Zaman makinesi**: aynı kuralın son 30 günde bu hissede nasıl sonuç verdiğini ve 10.000 Monte Carlo simülasyonunu gösterir. Hisseyle ilgili haberleri listeler. |
| 📰 Haberler | AA, Bloomberg HT ve Google Haberler (KAP, TCMB, enflasyon, SPK, politika). Haberleri konuya göre etiketler, önem ve yön (🟢/🔴) belirler, hisse koduyla eşleştirir. |
| 📊 VİOP | BIST 30 / USDTRY için yön önerisi (LONG / SHORT / NÖTR). Teminata ve riske göre kaç kontrat açılacağını hesaplar. |
| 🧮 Risk | Lot hesaplayıcı ve **risk bekçisi**: günlük zarar limiti, işlem sayısı, açık pozisyon ve ödül/risk kontrolü yapar (GEÇER / ENGEL). |
| 📒 Günlük | İşlem günlüğü, kâr/zarar ve bakiye eğrisi. CSV olarak indirilip geri yüklenebilir. |
| 📋 Plan | Günlük rutin ve yarışma stratejisi. |

Veriler 5 dakikada bir otomatik yenilenir. Yahoo Finance'teki BIST verisi **~15 dakika gecikmelidir**; emir vermeden önce fiyatı Matriks'te kontrol et.

## Telefonda kullanmak için (ücretsiz, ~10 dk)

1. Bu klasörü GitHub'da bir repoya yükle (Claude bunu senin yerine yapabilir).
2. **share.streamlit.io** adresine git ve GitHub hesabınla giriş yap.
3. **Create app** → repoyu seç → Main file: `app.py` → **Deploy**.
4. Sana `https://....streamlit.app` gibi bir link verilir. Telefonda aç ve **Ana ekrana ekle** de, artık uygulama gibi açılır.
5. (İsteğe bağlı) Streamlit'te uygulama **Settings → Secrets** bölümüne şifre ekleyebilirsin:
   ```toml
   APP_PASSWORD = "bir-sifre"
   ```

## Telegram bildirimleri (uygulama kapalıyken de)

Hafta içi 09:15'te ve seans boyunca 30 dakikada bir AL sinyallerini ve önemli haberleri telefonuna gönderir.

1. Telegram'da **@BotFather**'a `/newbot` yaz ve botun **token**'ını al.
2. Kendi botuna bir mesaj at. Ardından tarayıcıda `https://api.telegram.org/bot<TOKEN>/getUpdates` adresini aç ve `"chat":{"id": ...}` içindeki sayıyı al. Bu sayı **chat id**'dir.
3. GitHub repo → **Settings → Secrets and variables → Actions** → `TELEGRAM_TOKEN` ve `TELEGRAM_CHAT_ID` ekle.
4. **Actions** sekmesinde iş akışını etkinleştir. Denemek için **Run workflow**'a bas.
5. Aynı iki değeri Streamlit Secrets'a da eklersen uygulamada "Telegram'a gönder" düğmesi çıkar.

GitHub'ın zamanlanmış görevleri birkaç dakika gecikebilir.

## Bilgisayarda çalıştırmak

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Sinyal kuralı (açık ve test edilebilir)

- **Açılış aralığı:** 10:00–10:30 arası.
- **Giriş:** 10:30'dan sonra, fiyat aralığın tepesinin **ve** VWAP'ın üstünde kapanınca.
- **Stop:** aralığın dibi (en fazla %3 ve 0,8 × günlük ATR).
- **Hedef:** 2R (tavanı geçmez).
- **AL için ek şartlar:** puan ≥ 5, göreli hacim ≥ 1 ve hissede bu kural geçmişte zarar ettirmemiş olmalı.

Son 30 günlük testte bu kural **tüm hisselere körü körüne** uygulandığında ortalama sonuç ≈ 0R'dir. Avantaj, geçmişte işe yarayan hisseleri seçmekten, hacim filtresinden ve disiplinli stop'tan gelir. "Geçmiş ort R" sütununu ciddiye al.

> Yatırım tavsiyesi değildir. Sinyaller olasılıktır, kesinlik değildir. Son karar senin.
