@echo off
chcp 65001 >nul
title Setup bangran_bot

cd /d "%~dp0"
echo ================================================
echo   LANGKAH 1: Install library yang dibutuhkan
echo ================================================
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [GAGAL] Install library error. Pastikan Python sudah terpasang
    echo dan tercentang "Add Python to PATH" saat instalasi.
    pause
    exit /b 1
)

echo.
echo ================================================
echo   LANGKAH 2: Uji logika strategi (tanpa risiko)
echo ================================================
python selftest.py

echo.
echo ================================================
echo   Setup selesai.
echo   Selanjutnya: edit run_bot.bat (isi data akun),
echo   lalu double-click run_bot.bat untuk menjalankan.
echo ================================================
pause >nul
