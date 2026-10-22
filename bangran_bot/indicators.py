"""
Indikator teknikal murni (tanpa ketergantungan MT5), bisa jalan di mana saja.

Berisi padanan otomatis dari alat manual yang dipakai di strategi:
- Linear Regression Channel  -> pengganti channel diagonal (garis atas/bawah/tengah)
- Deteksi pivot swing high/low -> pengganti garis Support/Resistance manual
- ATR                         -> ukuran volatilitas untuk jarak SL & toleransi "sentuh"
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Channel:
    slope: float        # kemiringan garis regresi (per bar)
    strength: float     # kemiringan dinormalisasi terhadap volatilitas segmen
    r_squared: float    # kualitas tren (0..1): seberapa rapi harga mengikuti garis
    mid: float          # nilai garis tengah di bar terakhir
    upper: float        # band atas di bar terakhir
    lower: float        # band bawah di bar terakhir
    std: float          # deviasi standar residual


def linear_regression_channel(close: np.ndarray, deviations: float = 2.0) -> Channel:
    """Hitung linear regression channel untuk segmen harga penutupan.

    Ini padanan matematis dari channel diagonal yang digambar manual:
    garis tengah = garis regresi, band atas/bawah = garis sejajar sejauh
    `deviations` kali deviasi standar residual.

    r_squared dipakai sebagai filter kualitas: tren asli mengikuti garis
    dengan rapi (R^2 tinggi), sedangkan harga acak/sideways R^2-nya rendah.
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    if n < 2:
        v = float(close[-1]) if n else 0.0
        return Channel(0.0, 0.0, 0.0, v, v, v, 0.0)

    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, close, 1)
    regline = slope * x + intercept
    residuals = close - regline
    std = float(residuals.std())
    mid = float(regline[-1])
    # kekuatan tren: total perubahan garis regresi dibanding sebaran harga
    denom = close.std() + 1e-9
    strength = float(slope * n / denom)
    # R^2 = 1 - SS_res / SS_tot
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((close - close.mean()) ** 2)) + 1e-12
    r_squared = max(0.0, 1.0 - ss_res / ss_tot)
    return Channel(
        slope=float(slope),
        strength=strength,
        r_squared=r_squared,
        mid=mid,
        upper=mid + deviations * std,
        lower=mid - deviations * std,
        std=std,
    )


def atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range dari DataFrame OHLC. Mengembalikan nilai ATR terakhir."""
    if len(df) < 2:
        return 0.0
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    if len(tr) < period:
        return float(tr.mean())
    # Wilder's smoothing sederhana via rolling mean
    return float(pd.Series(tr).rolling(period).mean().iloc[-1])


def find_pivots(df: pd.DataFrame, left: int = 3, right: int = 3):
    """Cari swing high & swing low (pivot) terkonfirmasi.

    Sebuah bar jadi pivot high jika high-nya tertinggi di antara `left` bar
    sebelumnya dan `right` bar sesudahnya. Begitu pula pivot low untuk terendah.
    Mengembalikan (list harga pivot_high, list harga pivot_low).
    """
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(high)
    pivot_highs, pivot_lows = [], []
    for i in range(left, n - right):
        window_h = high[i - left: i + right + 1]
        window_l = low[i - left: i + right + 1]
        if high[i] == window_h.max():
            pivot_highs.append(high[i])
        if low[i] == window_l.min():
            pivot_lows.append(low[i])
    return pivot_highs, pivot_lows


def cluster_levels(levels: list[float], tolerance: float) -> list[float]:
    """Gabungkan level-level yang berdekatan (< tolerance) jadi satu zona (rata-rata)."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters = [[levels[0]]]
    for lv in levels[1:]:
        if abs(lv - clusters[-1][-1]) <= tolerance:
            clusters[-1].append(lv)
        else:
            clusters.append([lv])
    return [float(np.mean(c)) for c in clusters]


def support_resistance_zones(df: pd.DataFrame, left: int, right: int, tolerance: float):
    """Hasilkan daftar zona support & resistance dari pivot yang dikelompokkan.

    Mengembalikan (supports, resistances) berupa list harga, diurutkan.
    """
    highs, lows = find_pivots(df, left, right)
    resistances = cluster_levels(highs, tolerance)
    supports = cluster_levels(lows, tolerance)
    return supports, resistances
