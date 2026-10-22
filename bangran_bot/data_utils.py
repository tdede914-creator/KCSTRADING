"""
Utilitas data: resample timeframe & generator data sintetis untuk backtest.

Di produksi, data M1 diambil dari MT5. Untuk pengujian logika di lingkungan
mana pun (tanpa MT5), kita bisa membuat data sintetis mirip emas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# aturan resample pandas untuk tiap timeframe
_TF_RULE = {
    "M1": "1min",
    "M5": "5min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
}


def resample_ohlc(m1: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample DataFrame OHLC M1 (index datetime) ke timeframe lebih besar."""
    rule = _TF_RULE[timeframe]
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    out = m1.resample(rule, label="right", closed="right").agg(agg).dropna()
    return out


def generate_synthetic_m1(
    n_minutes: int = 60 * 24 * 10,  # ~10 hari data M1
    start_price: float = 1850.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Buat data M1 OHLC sintetis mirip XAU/USD dengan tren bergelombang.

    Bukan data pasar nyata — hanya untuk memverifikasi pipeline strategi &
    backtest berjalan. Untuk hasil bermakna, ganti dengan data historis asli.
    """
    rng = np.random.default_rng(seed)
    # komponen tren (gelombang lambat) + noise
    t = np.arange(n_minutes)
    trend = (
        20 * np.sin(2 * np.pi * t / (60 * 24 * 3))     # siklus ~3 hari
        + 8 * np.sin(2 * np.pi * t / (60 * 6))          # intraday
    )
    noise = np.cumsum(rng.normal(0, 0.15, n_minutes))
    mid = start_price + trend + noise

    # bangun OHLC dari mid-price
    spread = rng.uniform(0.1, 0.6, n_minutes)
    open_ = mid + rng.normal(0, 0.1, n_minutes)
    close = mid + rng.normal(0, 0.1, n_minutes)
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread

    idx = pd.date_range("2026-01-01", periods=n_minutes, freq="1min")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close}, index=idx
    )
    return df.round(2)


def load_m1_csv(path: str) -> pd.DataFrame:
    """Muat data M1 dari CSV. Wajib ada kolom: time, open, high, low, close.

    'time' bisa string tanggal atau epoch detik.
    """
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    tcol = cols.get("time") or cols.get("date") or cols.get("datetime")
    if tcol is None:
        raise ValueError("CSV harus punya kolom waktu: time/date/datetime")
    if np.issubdtype(df[tcol].dtype, np.number):
        df.index = pd.to_datetime(df[tcol], unit="s")
    else:
        df.index = pd.to_datetime(df[tcol])
    df = df.rename(columns={cols.get(k, k): k for k in ["open", "high", "low", "close"]})
    return df[["open", "high", "low", "close"]].sort_index()
