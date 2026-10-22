@echo off
chcp 65001 >nul
title Bot Scalping XAUUSD - bangran_bot

REM ============================================================
REM   ISI DATA ANDA DI BAWAH INI (edit SEKALI SAJA, lalu simpan)
REM   Klik kanan file ini -> Edit untuk mengubah nilainya.
REM ============================================================

REM --- Akun MetaTrader 5 (Exness) ---
set MT5_LOGIN=12345678
set MT5_PASSWORD=PasswordDemoAnda
REM   SERVER: lihat persis di MT5 (akun cent real biasanya Exness-MT5Real...)
set MT5_SERVER=Exness-MT5Real8
REM   SYMBOL: akun cent Exness pakai akhiran c -> XAUUSDc (cek di Market Watch)
set MT5_SYMBOL=XAUUSDc

REM --- Telegram ---
set TELEGRAM_TOKEN=123456:ABC-TokenDariBotFather
set TELEGRAM_CHAT_IDS=123456789

REM --- Mode ---
REM   DRY_RUN=1  -> HANYA kirim sinyal (AMAN, tidak order sungguhan)
REM   DRY_RUN=0  -> order otomatis sungguhan (pakai akun DEMO dulu!)
set DRY_RUN=1

REM ============================================================
REM   JANGAN ubah bagian di bawah ini
REM ============================================================

cd /d "%~dp0"
echo.
echo ================================================
echo   Menjalankan bot... (DRY_RUN=%DRY_RUN%)
echo   Buka Telegram dan kirim /start
echo   Tutup jendela ini untuk menghentikan bot.
echo ================================================
echo.
python main.py

echo.
echo Bot berhenti. Tekan tombol apa saja untuk menutup.
pause >nul
