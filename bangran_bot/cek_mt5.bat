@echo off
chcp 65001 >nul
title Diagnostik Koneksi MT5
cd /d "%~dp0"
echo Pastikan aplikasi MT5 sudah DIBUKA dan LOGIN manual lebih dulu.
echo.
python cek_mt5.py
echo.
pause >nul
