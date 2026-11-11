"""
Konektor ke MetaTrader 5 (Exness).

PENTING: Library `MetaTrader5` HANYA berjalan di Windows dengan aplikasi MT5
terpasang. Import dibungkus try/except agar modul tetap bisa diimpor di Linux
(mis. untuk backtest), namun fungsi live hanya berfungsi di Windows.
"""
from __future__ import annotations

import time
from datetime import datetime

import pandas as pd

from config import MT5Config

try:
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
except Exception:  # pragma: no cover - hanya gagal di non-Windows
    mt5 = None
    MT5_AVAILABLE = False


# pemetaan string timeframe -> konstanta MT5
def _tf_const(tf: str):
    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
    }
    return mapping[tf]


# penjelasan kode hasil order MT5 dalam bahasa manusia (Indonesia)
_RETCODE_INFO = {
    10004: "Requote (harga berubah). Bot akan coba lagi di sinyal berikutnya.",
    10006: "Order ditolak broker.",
    10013: "Permintaan tidak valid.",
    10014: "Volume (lot) tidak valid untuk simbol ini.",
    10015: "Harga tidak valid.",
    10016: "SL/TP tidak valid — biasanya terlalu dekat ke harga (jarak stop minimum broker).",
    10017: "Trading dinonaktifkan untuk akun/simbol ini.",
    10018: "Market TUTUP (mis. akhir pekan / di luar jam sesi).",
    10019: "Dana tidak cukup untuk membuka posisi dengan lot ini.",
    10020: "Harga berubah.",
    10021: "Tidak ada quote (harga) — simbol mungkin tidak aktif.",
    10024: "Terlalu banyak permintaan (rate limit).",
    10026: "AutoTrading dinonaktifkan di sisi SERVER broker.",
    10027: "AutoTrading dinonaktifkan di TERMINAL — aktifkan tombol 'Algo Trading' di MT5 (harus hijau).",
    10030: "Tipe filling order tidak didukung simbol ini (bot akan pilih otomatis).",
    10031: "Tidak ada koneksi ke server trading.",
}


def describe_retcode(code: int) -> str:
    return _RETCODE_INFO.get(code, "Kode tidak dikenal — cek jurnal MT5 tab 'Experts'/'Journal'.")


class MT5Connector:
    def __init__(self, cfg: MT5Config):
        if not MT5_AVAILABLE:
            raise RuntimeError(
                "Library MetaTrader5 tidak tersedia. Jalankan bot ini di Windows "
                "dengan MT5 terpasang (pip install MetaTrader5)."
            )
        self.cfg = cfg

    def connect(self) -> bool:
        # Teruskan kredensial LANGSUNG ke initialize() -> cara paling andal,
        # sering memperbaiki error -6 'Authorization failed'.
        init_kwargs = {}
        if self.cfg.terminal_path:
            init_kwargs["path"] = self.cfg.terminal_path
        if self.cfg.login:
            init_kwargs["login"] = int(self.cfg.login)
            init_kwargs["password"] = self.cfg.password
            init_kwargs["server"] = self.cfg.server

        ok = mt5.initialize(**init_kwargs)
        if not ok:
            err = mt5.last_error()
            # fallback: coba attach ke terminal yang sudah login manual (tanpa kredensial)
            mt5.shutdown()
            if mt5.initialize():
                info = mt5.account_info()
                if info is not None:
                    return self._ensure_symbol()
            raise RuntimeError(
                f"mt5.initialize gagal: {err}. Cek hal berikut:\n"
                "1) MT5 sudah DIBUKA dan LOGIN manual ke akun yang benar dulu.\n"
                "2) LOGIN, PASSWORD, dan SERVER di run_bot.bat PERSIS sama "
                "(server akun cent biasanya seperti 'Exness-MT5Real...' bukan 'Trial').\n"
                "3) Tombol 'Algo Trading' di MT5 aktif (hijau).\n"
                "4) Password yang dipakai adalah password akun, bukan password investor."
            )

        info = mt5.account_info()
        if info is None:
            raise RuntimeError(
                f"Terhubung tapi account_info kosong: {mt5.last_error()}. "
                "Pastikan akun benar-benar login di MT5."
            )
        return self._ensure_symbol()

    def _ensure_symbol(self) -> bool:
        symbol = getattr(self.cfg, "symbol", None) or "XAUUSD"
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(
                f"Simbol '{symbol}' tidak ditemukan di MT5. Buka Market Watch -> "
                "klik kanan -> Show All, cari 'XAU', lalu set MT5_SYMBOL sesuai nama persisnya "
                "(akun cent Exness biasanya 'XAUUSDc')."
            )
        return True

    def shutdown(self):
        mt5.shutdown()

    # ---- data ----
    def get_rates(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(symbol, _tf_const(timeframe), 0, count)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"Gagal ambil data {symbol} {timeframe}: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        return df[["open", "high", "low", "close"]]

    # ---- akun ----
    def account_balance(self) -> float:
        info = mt5.account_info()
        return float(info.balance) if info else 0.0

    def account_equity(self) -> float:
        info = mt5.account_info()
        return float(info.equity) if info else 0.0

    def open_positions(self, symbol: str | None = None):
        pos = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        return list(pos) if pos else []

    # ---- helper order ----
    def _pick_filling(self, symbol: str):
        """Pilih tipe filling yang didukung simbol (cegah error 10030)."""
        info = mt5.symbol_info(symbol)
        mode = getattr(info, "filling_mode", 0) if info else 0
        if mode & 2:   # SYMBOL_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        if mode & 1:   # SYMBOL_FILLING_FOK
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def _clamp_volume(self, symbol: str, lot: float) -> float:
        info = mt5.symbol_info(symbol)
        if info is None:
            return lot
        step = info.volume_step or 0.01
        lot = round(round(lot / step) * step, 2)
        return max(info.volume_min, min(info.volume_max, lot))

    def _normalize_stops(self, symbol: str, side: str, price: float, sl: float, tp: float):
        """Bulatkan ke digit simbol & jaga jarak stop minimum broker (cegah 10016)."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return round(sl, 2), round(tp, 2)
        digits = info.digits
        point = info.point
        min_dist = (getattr(info, "trade_stops_level", 0) or 0) * point
        if min_dist > 0:
            if side == "BUY":
                sl = min(sl, price - min_dist)
                tp = max(tp, price + min_dist)
            else:
                sl = max(sl, price + min_dist)
                tp = min(tp, price - min_dist)
        return round(sl, digits), round(tp, digits)

    # ---- order ----
    def market_order(self, symbol: str, side: str, lot: float, sl: float, tp: float,
                     deviation: int, magic: int, comment: str = "bangran_bot"):
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"Tidak ada tick untuk {symbol}")
        if side == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        lot = self._clamp_volume(symbol, float(lot))
        sl, tp = self._normalize_stops(symbol, side, price, float(sl), float(tp))
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._pick_filling(symbol),
        }
        result = mt5.order_send(request)
        return result

    def close_position(self, position, deviation: int, magic: int):
        symbol = position.symbol
        tick = mt5.symbol_info_tick(symbol)
        if position.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": position.volume,
            "type": order_type,
            "position": position.ticket,
            "price": price,
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": "bangran_bot_close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        return mt5.order_send(request)
