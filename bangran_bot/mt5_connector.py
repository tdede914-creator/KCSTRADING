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


class MT5Connector:
    def __init__(self, cfg: MT5Config):
        if not MT5_AVAILABLE:
            raise RuntimeError(
                "Library MetaTrader5 tidak tersedia. Jalankan bot ini di Windows "
                "dengan MT5 terpasang (pip install MetaTrader5)."
            )
        self.cfg = cfg

    def connect(self) -> bool:
        kwargs = {}
        if self.cfg.terminal_path:
            kwargs["path"] = self.cfg.terminal_path
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"mt5.initialize gagal: {mt5.last_error()}")
        if self.cfg.login:
            ok = mt5.login(self.cfg.login, password=self.cfg.password, server=self.cfg.server)
            if not ok:
                raise RuntimeError(f"Login MT5 gagal: {mt5.last_error()}")
        # pastikan simbol aktif di Market Watch
        if not mt5.symbol_select(self.cfg.symbol if hasattr(self.cfg, "symbol") else "XAUUSD", True):
            pass
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
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
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
