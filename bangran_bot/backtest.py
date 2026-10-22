"""
Backtester sederhana untuk menguji strategi di data historis M1.

Berjalan di lingkungan mana pun (tidak butuh MT5). Di tiap bar M1, konteks
timeframe lebih besar (H1/M30/M5) dibangun HANYA dari data sampai bar tersebut
(tanpa melihat masa depan / no lookahead), lalu strategi dievaluasi.

Manajemen posisi: maksimum 1 posisi, keluar saat SL atau TP tersentuh.

CATATAN: Secara default memakai DATA SINTETIS untuk membuktikan pipeline
berfungsi. Hasil P/L di sini TIDAK mencerminkan performa pasar nyata.
Ganti dengan data historis asli (load_m1_csv) untuk evaluasi bermakna.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd

from config import load_config
from data_utils import generate_synthetic_m1, load_m1_csv, resample_ohlc
from risk import RiskConfig, calc_lot_size
from strategy import Side, generate_signal


@dataclass
class Trade:
    side: Side
    entry_time: pd.Timestamp
    entry: float
    stop_loss: float
    take_profit: float
    lot: float
    exit_time: pd.Timestamp | None = None
    exit: float | None = None
    pnl: float | None = None
    result: str | None = None  # "TP" / "SL"


def run_backtest(m1: pd.DataFrame, start_balance: float = 1000.0, warmup: int = 60 * 50):
    cfg = load_config()
    scfg = cfg.strategy
    rcfg: RiskConfig = cfg.risk

    # Pra-resample seluruh data sekali; saat loop kita iris sampai waktu berjalan.
    h1_all = resample_ohlc(m1, scfg.tf_trend_major)
    m30_all = resample_ohlc(m1, scfg.tf_trend)
    m5_all = resample_ohlc(m1, scfg.tf_zone)

    balance = start_balance
    equity_curve = []
    trades: list[Trade] = []
    open_trade: Trade | None = None

    times = m1.index
    # evaluasi tiap 1 menit, mulai setelah warmup agar TF besar punya cukup data
    for i in range(warmup, len(m1)):
        now = times[i]
        bar = m1.iloc[i]

        # --- kelola posisi terbuka: cek SL/TP tersentuh dalam bar ini ---
        if open_trade is not None:
            hit = None
            if open_trade.side == Side.BUY:
                if bar["low"] <= open_trade.stop_loss:
                    hit = ("SL", open_trade.stop_loss)
                elif bar["high"] >= open_trade.take_profit:
                    hit = ("TP", open_trade.take_profit)
            else:  # SELL
                if bar["high"] >= open_trade.stop_loss:
                    hit = ("SL", open_trade.stop_loss)
                elif bar["low"] <= open_trade.take_profit:
                    hit = ("TP", open_trade.take_profit)
            if hit is not None:
                result, px = hit
                direction = 1 if open_trade.side == Side.BUY else -1
                pnl = (px - open_trade.entry) * direction * open_trade.lot * rcfg.contract_size
                open_trade.exit_time = now
                open_trade.exit = px
                open_trade.pnl = pnl
                open_trade.result = result
                balance += pnl
                trades.append(open_trade)
                open_trade = None

        # --- cari sinyal baru jika tidak ada posisi ---
        if open_trade is None:
            h1 = h1_all[h1_all.index <= now]
            m30 = m30_all[m30_all.index <= now]
            m5 = m5_all[m5_all.index <= now]
            m1_slice = m1.iloc[max(0, i - 120): i + 1]
            sig = generate_signal(scfg, h1, m30, m5, m1_slice)
            if sig is not None:
                lot = calc_lot_size(rcfg, balance, sig.entry, sig.stop_loss)
                if lot > 0:
                    open_trade = Trade(
                        side=sig.side,
                        entry_time=now,
                        entry=sig.entry,
                        stop_loss=sig.stop_loss,
                        take_profit=sig.take_profit,
                        lot=lot,
                    )

        equity_curve.append((now, balance))

    return _report(trades, equity_curve, start_balance, balance)


def _report(trades, equity_curve, start_balance, end_balance):
    n = len(trades)
    wins = [t for t in trades if t.result == "TP"]
    losses = [t for t in trades if t.result == "SL"]
    win_rate = (len(wins) / n * 100) if n else 0.0
    gross_win = sum(t.pnl for t in wins)
    gross_loss = sum(t.pnl for t in losses)
    pf = (gross_win / abs(gross_loss)) if gross_loss else float("inf")

    eq = pd.DataFrame(equity_curve, columns=["time", "balance"]).set_index("time")
    peak = eq["balance"].cummax()
    dd = (eq["balance"] - peak)
    max_dd = float(dd.min()) if len(dd) else 0.0

    print("=" * 56)
    print("            HASIL BACKTEST (DATA SINTETIS)")
    print("=" * 56)
    print(f"Saldo awal      : {start_balance:,.2f}")
    print(f"Saldo akhir     : {end_balance:,.2f}")
    print(f"Net P/L         : {end_balance - start_balance:,.2f} "
          f"({(end_balance/start_balance-1)*100:.2f}%)")
    print(f"Jumlah trade    : {n}")
    print(f"Menang / Kalah  : {len(wins)} / {len(losses)}")
    print(f"Win rate        : {win_rate:.1f}%")
    print(f"Profit factor   : {pf:.2f}")
    print(f"Max drawdown    : {max_dd:,.2f}")
    print("=" * 56)
    print("\nCATATAN: ini DATA SINTETIS, bukan pasar nyata. Angka di atas hanya")
    print("membuktikan pipeline strategi berjalan. Gunakan data historis asli")
    print("(CSV dari MT5) untuk evaluasi yang bermakna.")
    return {
        "trades": trades,
        "equity": eq,
        "win_rate": win_rate,
        "profit_factor": pf,
        "net_pnl": end_balance - start_balance,
        "max_drawdown": max_dd,
    }


def main():
    ap = argparse.ArgumentParser(description="Backtest strategi scalping XAUUSD")
    ap.add_argument("--csv", help="path data M1 CSV (opsional). Jika kosong, pakai data sintetis.")
    ap.add_argument("--balance", type=float, default=1000.0, help="saldo awal")
    args = ap.parse_args()

    if args.csv:
        m1 = load_m1_csv(args.csv)
        warmup = min(len(m1) // 3, 60 * 50)
    else:
        m1 = generate_synthetic_m1()
        warmup = 60 * 50
    run_backtest(m1, start_balance=args.balance, warmup=warmup)


if __name__ == "__main__":
    main()
