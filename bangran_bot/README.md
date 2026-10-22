# Bot Scalping XAU/USD Multi-Timeframe (MT5 + Telegram)

Bot trading otomatis untuk **XAU/USD (emas)** di **MetaTrader 5 (Exness)**, dikontrol
lewat **Telegram**. Strategi merupakan *padanan otomatis* dari pendekatan multi-timeframe
gaya "Bang Ran": channel diagonal + zona support/resistance.

> ⚠️ **PENTING — baca dulu**
> - Ini **alat bantu**, bukan mesin uang. Trading forex berisiko tinggi; Anda bisa
>   kehilangan modal. **Tidak ada jaminan profit.**
> - Target seperti "profit tetap per hari" **tidak realistis** dan berbahaya. Fokuslah
>   pada manajemen risiko dan konsistensi, bukan target harian paksaan.
> - **Uji di akun DEMO** dan mode `DRY_RUN` dulu sampai Anda paham perilakunya.
> - Strategi ini **tidak 100% meniru** keputusan manual manusia (lihat bagian Strategi).

## Cara kerja strategi

Keputusan bertingkat dari timeframe besar ke kecil:

| TF | Peran | Metode otomatis |
|----|-------|-----------------|
| **H1** | Arah tren besar (filter utama) | Linear Regression (slope + R²) |
| **M30** | Konfirmasi tren (channel) | Linear Regression Channel |
| **M5** | Zona Support/Resistance | Deteksi pivot swing + clustering |
| **M1** | Trigger entry (scalping) | Sentuhan zona + konfirmasi candle |

**Aturan entry:**
- Tren H1 **dan** M30 harus searah (keduanya naik atau keduanya turun), dan harga
  harus mengikuti garis dengan rapi (R² di atas ambang) — menyaring pasar sideways.
- **BUY**: tren naik + harga M1 menyentuh **support** M5 + candle konfirmasi bullish.
- **SELL**: tren turun + harga M1 menyentuh **resistance** M5 + candle konfirmasi bearish.
- **SL**: di luar zona (buffer berbasis ATR). **TP**: `2 × jarak SL` (risk:reward **1:2**).

### Kenapa tidak persis seperti di video?
Bang Ran menggambar channel & zona **secara manual dengan mata**. Bot memakai padanan
matematis (Linear Regression Channel + deteksi pivot otomatis). Hasilnya menangkap
*logika* yang sama, tetapi titik pastinya bisa berbeda dan bot tak bisa "merasa" kapan
harus mengabaikan channel seperti manusia. Karena itu **wajib di-backtest & demo** dulu.

## Struktur proyek

```
bangran_bot/
├── config.py         # semua parameter (strategi, risk, MT5, Telegram)
├── indicators.py     # linreg channel, ATR, pivot, clustering zona
├── strategy.py       # logika sinyal multi-timeframe
├── risk.py           # position sizing + batas loss harian
├── data_utils.py     # resample TF + data sintetis untuk backtest
├── backtest.py       # backtester (butuh numpy+pandas, OS apa saja)
├── mt5_connector.py  # koneksi & order ke MT5 (WINDOWS ONLY)
├── engine.py         # loop trading (data→sinyal→risk→order)
├── telegram_bot.py   # kontrol & notifikasi Telegram
├── main.py           # titik masuk live
├── selftest.py       # uji logika inti (murni Python, tanpa dependency)
└── requirements.txt
```

## Instalasi

### 1. Backtest dulu (bisa di Windows/Mac/Linux)
```bash
pip install numpy pandas
python backtest.py                 # pakai data sintetis (uji pipeline)
python backtest.py --csv data.csv  # pakai data historis M1 asli (disarankan)
```
Format CSV M1: kolom `time,open,high,low,close` (time = tanggal atau epoch detik).
> Data sintetis hanya membuktikan pipeline berjalan — **bukan** performa pasar nyata.
> Ekspor data historis asli dari MT5 untuk evaluasi yang bermakna.

### 2. Live / Demo (WAJIB Windows + MT5 terpasang)
```bash
pip install -r requirements.txt
```

Set environment variable (jangan hard-code kredensial di kode):
```bat
set MT5_LOGIN=12345678
set MT5_PASSWORD=passwordAnda
set MT5_SERVER=Exness-MT5Trial        REM sesuaikan server Exness Anda
set MT5_SYMBOL=XAUUSDm                 REM cek nama simbol gold di broker Anda
set TELEGRAM_TOKEN=token_dari_BotFather
set TELEGRAM_CHAT_IDS=123456789        REM chat ID Anda (boleh beberapa, pisah koma)
set DRY_RUN=1                          REM 1 = hanya sinyal; 0 = order sungguhan
python main.py
```

### 3. Kontrol via Telegram
| Perintah | Fungsi |
|----------|--------|
| `/start` | mulai bot |
| `/stop` | hentikan |
| `/pause` / `/resume` | jeda / lanjut entry baru |
| `/status` | status + P/L hari ini |
| `/balance` | balance & equity |
| `/positions` | posisi terbuka |

## Manajemen risiko (bawaan)
- Risiko per trade: **1%** dari balance (`risk.risk_per_trade_pct`).
- **Batas rugi harian 5%** → bot berhenti entry otomatis hari itu.
- Maks **1 posisi** sekaligus + batas jumlah trade harian.
- Position sizing otomatis menyesuaikan lot agar risiko tetap sesuai jarak SL.

## Alur yang disarankan
1. `python selftest.py` → pastikan logika inti lulus.
2. `python backtest.py --csv <data M1 asli>` → lihat win rate, profit factor, drawdown.
3. **Tuning parameter** di `config.py` (periode regresi, ambang R², ATR, dll).
4. Jalankan **DEMO** Exness dengan `DRY_RUN=1` beberapa hari.
5. Jika konsisten, baru pertimbangkan `DRY_RUN=0` di akun kecil — **uang yang Anda siap rugi.**

## Disclaimer
Perangkat lunak ini untuk tujuan edukasi & riset. Bukan nasihat finansial. Penggunaan
sepenuhnya risiko Anda sendiri.
