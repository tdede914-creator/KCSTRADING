"""
Alat diagnostik koneksi MT5 — TERPISAH dari bot & Telegram.

Tidak butuh isi login/password. Syaratnya: aplikasi MetaTrader 5 sudah DIBUKA
dan sudah LOGIN manual ke akun Anda. Script ini mencoba "menempel" ke terminal
itu lalu melaporkan: status koneksi, info akun, dan daftar simbol emas (XAU)
yang tersedia di akun Anda.

Jalankan lewat cek_mt5.bat (double-click).
"""
import sys

try:
    import MetaTrader5 as mt5
except Exception as e:
    print("[GAGAL] Library MetaTrader5 belum terpasang:", e)
    print("Jalankan dulu: pip install MetaTrader5")
    sys.exit(1)

print("=" * 56)
print("   DIAGNOSTIK KONEKSI MT5")
print("=" * 56)
print("Mencoba menempel ke MT5 yang sudah terbuka & login...\n")

ok = mt5.initialize()
print(f"initialize(): {ok}   last_error: {mt5.last_error()}")

if not ok:
    print("\n[GAGAL MENEMPEL KE MT5]")
    print("Kemungkinan penyebab:")
    print("  1) Aplikasi MT5 belum dibuka / belum login manual.")
    print("  2) MT5 dijalankan sebagai Administrator tapi script tidak (atau sebaliknya)")
    print("     -> jalankan keduanya dengan hak akses sama.")
    print("  3) Di MT5: Tools > Options > Expert Advisors -> centang 'Allow algorithmic trading'.")
    print("  4) Tombol 'Algo Trading' di toolbar MT5 harus menyala.")
    sys.exit(1)

ti = mt5.terminal_info()
ai = mt5.account_info()

print("\n--- STATUS TERMINAL ---")
if ti is not None:
    print(f"  Terhubung ke server : {ti.connected}")
    print(f"  Trade diizinkan     : {ti.trade_allowed}")
    print(f"  Path                : {ti.path}")
print("\n--- INFO AKUN ---")
if ai is not None:
    print(f"  Login   : {ai.login}")
    print(f"  Server  : {ai.server}")
    print(f"  Balance : {ai.balance} {ai.currency}")
    print(f"  Leverage: 1:{ai.leverage}")
else:
    print("  (account_info kosong — akun belum benar-benar login di MT5)")

print("\n--- CARI SIMBOL EMAS (XAU) ---")
syms = mt5.symbols_get()
xau = sorted([s.name for s in syms if "XAU" in s.name.upper()]) if syms else []
if xau:
    print("  Simbol emas yang tersedia di akun ini:")
    for name in xau:
        print(f"    -> {name}")
    print("\n  Pakai SALAH SATU nama di atas untuk MT5_SYMBOL di run_bot.bat.")
else:
    print("  (!) Tidak ada simbol XAU/emas di akun ini.")
    print("      Akun cent Anda kemungkinan tidak menyediakan emas.")
    print("      Perlu tipe akun lain (mis. Standard) untuk trading XAUUSD.")

mt5.shutdown()
print("\n" + "=" * 56)
print("  Selesai. Kirim hasil di atas ke asisten untuk dibantu.")
print("=" * 56)
