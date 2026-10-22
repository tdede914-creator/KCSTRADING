"""
Manajemen risiko: position sizing, batas kerugian harian, batas jumlah trade.

Ini komponen paling penting untuk melindungi modal. Bot TIDAK boleh entry
tanpa SL, dan harus berhenti otomatis saat batas loss harian tercapai.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from config import RiskConfig


def calc_lot_size(
    cfg: RiskConfig,
    balance: float,
    entry: float,
    stop_loss: float,
) -> float:
    """Hitung ukuran lot berdasarkan risiko % dan jarak SL.

    Untuk XAU/USD di MT5: nilai risiko = jarak_harga * contract_size * lot.
    lot = risiko_uang / (jarak_harga * contract_size)
    """
    sl_distance = abs(entry - stop_loss)
    if sl_distance <= 0:
        return 0.0
    risk_money = balance * (cfg.risk_per_trade_pct / 100.0)
    raw_lot = risk_money / (sl_distance * cfg.contract_size)
    # bulatkan ke kelipatan lot_step dan batasi min/max
    steps = round(raw_lot / cfg.lot_step)
    lot = steps * cfg.lot_step
    lot = max(cfg.min_lot, min(cfg.max_lot, lot))
    return round(lot, 2)


@dataclass
class RiskGuard:
    """Pelacak keadaan risiko harian. Reset otomatis saat ganti hari."""
    cfg: RiskConfig
    _day: date = field(default_factory=date.today)
    realized_pnl_today: float = 0.0
    trades_today: int = 0
    start_balance_today: float = 0.0

    def _rollover(self, balance: float):
        today = date.today()
        if today != self._day:
            self._day = today
            self.realized_pnl_today = 0.0
            self.trades_today = 0
            self.start_balance_today = balance

    def on_new_day(self, balance: float):
        if self.start_balance_today == 0.0:
            self.start_balance_today = balance
        self._rollover(balance)

    def register_trade_result(self, pnl: float):
        self.realized_pnl_today += pnl
        self.trades_today += 1

    def can_trade(self, balance: float, open_positions: int) -> tuple[bool, str]:
        """Boleh buka posisi baru? Kembalikan (boleh, alasan)."""
        self._rollover(balance)
        base = self.start_balance_today or balance
        if open_positions >= self.cfg.max_open_positions:
            return False, "Sudah ada posisi terbuka (maks tercapai)."
        if self.trades_today >= self.cfg.max_trades_per_day:
            return False, "Batas jumlah trade harian tercapai."
        max_loss = -base * (self.cfg.max_daily_loss_pct / 100.0)
        if self.realized_pnl_today <= max_loss:
            return False, (
                f"Batas rugi harian tercapai ({self.realized_pnl_today:.2f} "
                f"<= {max_loss:.2f}). Bot berhenti entry hari ini."
            )
        return True, "OK"
