"""
Logika strategi scalping multi-timeframe (padanan otomatis gaya "Bang Ran").

Alur keputusan bertingkat:
  H1  -> arah tren besar (filter utama)         [linear regression]
  M30 -> konfirmasi tren + channel              [linear regression channel]
  M5  -> zona Support/Resistance                [pivot swing + clustering]
  M1  -> trigger entry scalping di zona SnR     [sentuhan + konfirmasi candle]

Entry hanya diambil jika H1 dan M30 sepakat arahnya, DAN harga M1 menyentuh
zona SnR yang relevan dengan arah tren tersebut.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from config import StrategyConfig
from indicators import (
    atr,
    linear_regression_channel,
    support_resistance_zones,
)


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Signal:
    side: Side
    entry: float
    stop_loss: float
    take_profit: float
    reason: str
    zone: float          # level SnR yang memicu entry
    atr_entry: float     # ATR M1 saat sinyal (untuk info sizing)


def _trend_dir(close: pd.Series, period: int, deviations: float, min_strength: float, min_r2: float):
    """Tentukan arah tren: 'bull' / 'bear' / None.

    Butuh DUA syarat agar dianggap tren:
      1. |strength| > min_strength  (kemiringan cukup curam)
      2. r_squared  > min_r2        (harga mengikuti garis dengan rapi)
    Ini menyaring kondisi sideways/acak yang kemiringannya kebetulan besar.
    """
    seg = close.to_numpy(dtype=float)[-period:]
    if len(seg) < max(5, period // 2):
        return None, None
    ch = linear_regression_channel(seg, deviations)
    if ch.r_squared < min_r2:
        return None, ch
    if ch.strength > min_strength:
        return "bull", ch
    if ch.strength < -min_strength:
        return "bear", ch
    return None, ch


def _bullish_confirmation(candle: pd.Series) -> bool:
    """Candle M1 mengindikasikan penolakan ke atas (untuk BUY di support)."""
    body = candle["close"] - candle["open"]
    rng = candle["high"] - candle["low"] + 1e-9
    lower_wick = min(candle["open"], candle["close"]) - candle["low"]
    # bullish body ATAU pin bar dengan ekor bawah panjang (rejection)
    return body > 0 or (lower_wick / rng) > 0.5


def _bearish_confirmation(candle: pd.Series) -> bool:
    """Candle M1 mengindikasikan penolakan ke bawah (untuk SELL di resistance)."""
    body = candle["close"] - candle["open"]
    rng = candle["high"] - candle["low"] + 1e-9
    upper_wick = candle["high"] - max(candle["open"], candle["close"])
    return body < 0 or (upper_wick / rng) > 0.5


def generate_signal(
    cfg: StrategyConfig,
    h1: pd.DataFrame,
    m30: pd.DataFrame,
    m5: pd.DataFrame,
    m1: pd.DataFrame,
) -> Signal | None:
    """Evaluasi semua timeframe dan hasilkan Signal, atau None jika tidak ada setup.

    Setiap DataFrame harus berkolom: open, high, low, close (urut lama->baru).
    """
    if any(len(x) < 5 for x in (h1, m30, m5, m1)):
        return None

    # 1) Tren besar H1
    h1_dir, _ = _trend_dir(
        h1["close"], cfg.h1_reg_period, cfg.channel_deviations,
        cfg.min_slope_strength, cfg.min_trend_r2,
    )
    if h1_dir is None:
        return None

    # 2) Konfirmasi tren M30 (harus sepakat dengan H1)
    m30_dir, _ = _trend_dir(
        m30["close"], cfg.m30_reg_period, cfg.channel_deviations,
        cfg.min_slope_strength, cfg.min_trend_r2,
    )
    if m30_dir is None or m30_dir != h1_dir:
        return None

    # 3) Zona Support/Resistance dari M5
    m5_window = m5.tail(cfg.m5_lookback)
    atr_m5 = atr(m5_window, cfg.atr_period)
    tol = cfg.zone_merge_atr_mult * atr_m5
    supports, resistances = support_resistance_zones(
        m5_window, cfg.pivot_left, cfg.pivot_right, tol
    )
    if not supports and not resistances:
        return None

    # 4) Trigger entry di M1
    last = m1.iloc[-1]
    price = float(last["close"])
    atr_m1 = atr(m1.tail(max(cfg.atr_period * 2, 20)), cfg.atr_period)
    if atr_m1 <= 0:
        return None
    touch_dist = cfg.touch_atr_mult * atr_m1
    sl_buffer = cfg.sl_buffer_atr_mult * atr_m1

    if h1_dir == "bull" and supports:
        # cari support terdekat di bawah/dekat harga yang sedang disentuh
        near = [s for s in supports if abs(last["low"] - s) <= touch_dist and s <= price + touch_dist]
        if near:
            zone = max(near)  # support terdekat ke harga
            if not cfg.require_candle_confirm or _bullish_confirmation(last):
                stop = zone - sl_buffer
                risk = price - stop
                if risk > 0:
                    tp = price + cfg.risk_reward * risk
                    return Signal(
                        side=Side.BUY,
                        entry=price,
                        stop_loss=stop,
                        take_profit=tp,
                        reason=f"Uptrend H1+M30; harga menyentuh support {zone:.2f}",
                        zone=zone,
                        atr_entry=atr_m1,
                    )

    if h1_dir == "bear" and resistances:
        near = [r for r in resistances if abs(last["high"] - r) <= touch_dist and r >= price - touch_dist]
        if near:
            zone = min(near)
            if not cfg.require_candle_confirm or _bearish_confirmation(last):
                stop = zone + sl_buffer
                risk = stop - price
                if risk > 0:
                    tp = price - cfg.risk_reward * risk
                    return Signal(
                        side=Side.SELL,
                        entry=price,
                        stop_loss=stop,
                        take_profit=tp,
                        reason=f"Downtrend H1+M30; harga menyentuh resistance {zone:.2f}",
                        zone=zone,
                        atr_entry=atr_m1,
                    )

    return None
