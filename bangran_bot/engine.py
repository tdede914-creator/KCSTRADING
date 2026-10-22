"""
Mesin trading: menyatukan data MT5 + strategi + manajemen risiko.

Dirancang agar bisa dikontrol dari luar (mis. bot Telegram): start/stop,
status, dan notifikasi lewat callback.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from config import AppConfig
from risk import RiskGuard, calc_lot_size
from strategy import Side, generate_signal


@dataclass
class EngineState:
    running: bool = False
    paused: bool = False
    last_signal: str = "-"
    last_error: str = "-"
    last_check: str = "-"
    trades_today: int = 0
    balance: float = 0.0
    equity: float = 0.0
    open_positions: int = 0


class TradingEngine:
    """Loop utama. Membutuhkan konektor MT5 (hanya jalan di Windows)."""

    def __init__(self, cfg: AppConfig, connector, notify: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.connector = connector
        self.notify = notify or (lambda msg: None)
        self.state = EngineState()
        self.risk = RiskGuard(cfg.risk)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ---- kontrol ----
    def start(self):
        if self.state.running:
            return "Bot sudah berjalan."
        self._stop.clear()
        self.state.running = True
        self.state.paused = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return "Bot dimulai."

    def stop(self):
        self._stop.set()
        self.state.running = False
        return "Bot dihentikan."

    def pause(self):
        self.state.paused = True
        return "Bot dijeda (tidak entry baru)."

    def resume(self):
        self.state.paused = False
        return "Bot dilanjutkan."

    def status_text(self) -> str:
        s = self.state
        return (
            f"📊 STATUS BOT\n"
            f"Jalan: {'✅' if s.running else '⛔'}  |  Jeda: {'⏸' if s.paused else '▶️'}\n"
            f"Balance: {s.balance:,.2f}  |  Equity: {s.equity:,.2f}\n"
            f"Posisi terbuka: {s.open_positions}\n"
            f"Trade hari ini: {self.risk.trades_today}\n"
            f"P/L hari ini: {self.risk.realized_pnl_today:,.2f}\n"
            f"Sinyal terakhir: {s.last_signal}\n"
            f"Cek terakhir: {s.last_check}\n"
            f"Error terakhir: {s.last_error}"
        )

    # ---- loop ----
    def _run(self):
        scfg = self.cfg.strategy
        try:
            self.connector.connect()
            self.notify("✅ Terhubung ke MT5. Bot aktif.")
        except Exception as e:
            self.state.last_error = str(e)
            self.state.running = False
            self.notify(f"❌ Gagal konek MT5: {e}")
            return

        while not self._stop.is_set():
            try:
                self._tick(scfg)
            except Exception as e:
                self.state.last_error = str(e)
                self.notify(f"⚠️ Error loop: {e}")
                traceback.print_exc()
            self._stop.wait(self.cfg.poll_seconds)

        try:
            self.connector.shutdown()
        except Exception:
            pass

    def _tick(self, scfg):
        self.state.balance = self.connector.account_balance()
        self.state.equity = self.connector.account_equity()
        positions = self.connector.open_positions(scfg.symbol)
        self.state.open_positions = len(positions)
        self.state.last_check = time.strftime("%Y-%m-%d %H:%M:%S")
        self.risk.on_new_day(self.state.balance)

        if self.state.paused:
            return

        # hanya cari entry jika tidak ada posisi & risiko mengizinkan
        can, reason = self.risk.can_trade(self.state.balance, self.state.open_positions)
        if not can:
            self.state.last_signal = reason
            return

        # ambil data semua timeframe
        h1 = self.connector.get_rates(scfg.symbol, scfg.tf_trend_major, scfg.h1_reg_period + 10)
        m30 = self.connector.get_rates(scfg.symbol, scfg.tf_trend, scfg.m30_reg_period + 10)
        m5 = self.connector.get_rates(scfg.symbol, scfg.tf_zone, scfg.m5_lookback + 10)
        m1 = self.connector.get_rates(scfg.symbol, scfg.tf_entry, 120)

        sig = generate_signal(scfg, h1, m30, m5, m1)
        if sig is None:
            self.state.last_signal = "Tidak ada setup (menunggu)"
            return

        lot = calc_lot_size(self.cfg.risk, self.state.balance, sig.entry, sig.stop_loss)
        msg = (
            f"🔔 SINYAL {sig.side.value}\n"
            f"{sig.reason}\n"
            f"Entry ~{sig.entry:.2f}  SL {sig.stop_loss:.2f}  TP {sig.take_profit:.2f}\n"
            f"Lot: {lot}  (risiko {self.cfg.risk.risk_per_trade_pct}%)"
        )
        self.state.last_signal = f"{sig.side.value} @ {sig.entry:.2f}"

        if self.cfg.dry_run:
            self.notify(msg + "\n(DRY RUN — order tidak dikirim)")
            return
        if lot <= 0:
            self.notify(msg + "\n⚠️ Lot = 0, order dibatalkan.")
            return

        result = self.connector.market_order(
            scfg.symbol, sig.side.value, lot, sig.stop_loss, sig.take_profit,
            self.cfg.mt5.deviation, self.cfg.mt5.magic_number,
        )
        retcode = getattr(result, "retcode", None)
        import MetaTrader5 as mt5  # aman: dry_run=False hanya di Windows
        if retcode == mt5.TRADE_RETCODE_DONE:
            self.risk.trades_today += 1
            self.notify(msg + "\n✅ Order terkirim.")
        else:
            self.notify(msg + f"\n❌ Order gagal: retcode={retcode}")
