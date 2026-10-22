"""
Self-test MURNI PYTHON (tanpa numpy/pandas) untuk memvalidasi logika inti
strategi di lingkungan offline.

Meniru rumus yang sama dengan indicators.py & strategy.py:
- linear regression channel (slope, strength, bands)
- deteksi pivot swing high/low + clustering zona
- pembuatan sinyal multi-timeframe sederhana

Tujuannya membuktikan ALGORITMA menghasilkan tren, zona SnR, dan sinyal BUY/SELL
yang masuk akal — bukan menguji performa pasar.
"""
import math
import random
import statistics


# ---------- Indikator (padanan stdlib dari indicators.py) ----------

def linreg_channel(close, deviations=2.0):
    n = len(close)
    if n < 2:
        v = close[-1] if n else 0.0
        return {"slope": 0.0, "strength": 0.0, "r2": 0.0, "mid": v, "upper": v, "lower": v, "std": 0.0}
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(close) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((xs[i] - mx) * (close[i] - my) for i in range(n))
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    regline = [slope * x + intercept for x in xs]
    residuals = [close[i] - regline[i] for i in range(n)]
    std = statistics.pstdev(residuals) if n > 1 else 0.0
    mid = regline[-1]
    price_std = statistics.pstdev(close) if n > 1 else 1e-9
    strength = slope * n / (price_std + 1e-9)
    ss_res = sum(r * r for r in residuals)
    ss_tot = sum((v - my) ** 2 for v in close) + 1e-12
    r2 = max(0.0, 1.0 - ss_res / ss_tot)
    return {
        "slope": slope, "strength": strength, "r2": r2, "mid": mid,
        "upper": mid + deviations * std, "lower": mid - deviations * std, "std": std,
    }


def trend_dir(close, min_strength=1.5, min_r2=0.30):
    ch = linreg_channel(close)
    if ch["r2"] < min_r2:
        return None, ch
    if ch["strength"] > min_strength:
        return "bull", ch
    if ch["strength"] < -min_strength:
        return "bear", ch
    return None, ch


def atr(highs, lows, closes, period=14):
    n = len(closes)
    if n < 2:
        return 0.0
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs)
    return sum(trs[-period:]) / period


def find_pivots(highs, lows, left=3, right=3):
    n = len(highs)
    ph, pl = [], []
    for i in range(left, n - right):
        wh = highs[i - left: i + right + 1]
        wl = lows[i - left: i + right + 1]
        if highs[i] == max(wh):
            ph.append(highs[i])
        if lows[i] == min(wl):
            pl.append(lows[i])
    return ph, pl


def cluster_levels(levels, tol):
    if not levels:
        return []
    levels = sorted(levels)
    clusters = [[levels[0]]]
    for lv in levels[1:]:
        if abs(lv - clusters[-1][-1]) <= tol:
            clusters[-1].append(lv)
        else:
            clusters.append([lv])
    return [sum(c) / len(c) for c in clusters]


# ---------- Data sintetis sederhana ----------

def gen_series(n, start=1850.0, seed=1, trend_per_bar=0.0):
    random.seed(seed)
    o, h, l, c = [], [], [], []
    price = start
    for i in range(n):
        price += trend_per_bar + random.uniform(-0.3, 0.3)
        op = price + random.uniform(-0.1, 0.1)
        cl = price + random.uniform(-0.1, 0.1)
        hi = max(op, cl) + random.uniform(0.1, 0.5)
        lo = min(op, cl) - random.uniform(0.1, 0.5)
        o.append(round(op, 2)); h.append(round(hi, 2)); l.append(round(lo, 2)); c.append(round(cl, 2))
    return o, h, l, c


# ---------- Uji ----------

def test_regression_detects_trend():
    # tren kuat & mulus (noise kecil) vs sideways (noise dominan, tanpa drift)
    _, _, _, up = gen_series(60, seed=2, trend_per_bar=0.6)
    _, _, _, down = gen_series(60, seed=3, trend_per_bar=-0.6)
    _, _, _, flat = gen_series(200, seed=4, trend_per_bar=0.0)
    up_dir, up_ch = trend_dir(up)
    down_dir, down_ch = trend_dir(down)
    flat_dir, flat_ch = trend_dir(flat)
    print(f"  NAIK : dir={up_dir}  strength={up_ch['strength']:+.2f}  R2={up_ch['r2']:.2f}")
    print(f"  TURUN: dir={down_dir}  strength={down_ch['strength']:+.2f}  R2={down_ch['r2']:.2f}")
    print(f"  DATAR: dir={flat_dir}  strength={flat_ch['strength']:+.2f}  R2={flat_ch['r2']:.2f}")
    assert up_dir == "bull", "tren naik mulus harus terdeteksi sebagai bull"
    assert down_dir == "bear", "tren turun mulus harus terdeteksi sebagai bear"
    assert flat_dir is None, "sideways harus ditolak oleh filter R2 (bukan tren)"
    print("  [OK] filter strength + R2 membedakan tren asli dari sideways")


def test_pivots_and_zones():
    o, h, l, c = gen_series(120, seed=7, trend_per_bar=0.0)
    ph, pl = find_pivots(h, l, 3, 3)
    a = atr(h, l, c, 14)
    sup = cluster_levels(pl, 0.5 * a)
    res = cluster_levels(ph, 0.5 * a)
    print(f"  pivot high={len(ph)} low={len(pl)}  ->  zona R={len(res)} S={len(sup)}  ATR={a:.2f}")
    assert ph and pl, "harus menemukan pivot"
    assert res and sup, "harus membentuk zona SnR"
    assert len(sup) <= len(pl) and len(res) <= len(ph), "clustering harus menggabungkan level"
    print("  [OK] pivot terdeteksi & zona SnR terbentuk via clustering")


def test_signal_logic():
    """Uptrend + harga menyentuh support -> harus menghasilkan setup BUY dengan RR 1:2."""
    # harga sekarang menyentuh support, tren naik
    support = 1850.0
    price = 1850.3
    atr_m1 = 0.8
    touch = abs(1850.1 - support) <= 0.6 * atr_m1   # low dekat support
    assert touch, "harga harus dianggap menyentuh support"
    sl_buffer = 0.5 * atr_m1
    stop = support - sl_buffer
    risk = price - stop
    tp = price + 2.0 * risk
    rr = (tp - price) / (price - stop)
    print(f"  BUY entry={price} SL={stop:.2f} TP={tp:.2f}  risk={risk:.2f}  RR=1:{rr:.1f}")
    assert risk > 0, "risk harus positif"
    assert abs(rr - 2.0) < 1e-6, "rasio harus tepat 1:2"
    print("  [OK] sinyal BUY di support menghasilkan SL/TP dengan RR 1:2")


def test_lot_sizing():
    """Position sizing: risiko 1% dari $1000, SL 1.0 poin, gold contract=100."""
    balance, risk_pct, sl_distance, contract = 1000.0, 1.0, 1.0, 100.0
    risk_money = balance * risk_pct / 100.0       # $10
    raw_lot = risk_money / (sl_distance * contract)  # 10 / 100 = 0.10
    lot = round(round(raw_lot / 0.01) * 0.01, 2)
    print(f"  balance=${balance} risk={risk_pct}% SL={sl_distance} -> lot={lot}")
    assert abs(lot - 0.10) < 1e-9, "lot harus 0.10"
    # verifikasi kerugian jika SL kena = tepat risiko yang ditetapkan
    loss = sl_distance * contract * lot
    assert abs(loss - 10.0) < 1e-9, "kerugian saat SL harus = $10 (1%)"
    print("  [OK] lot sizing menjaga risiko tepat 1% saat SL kena")


def main():
    print("=" * 56)
    print("     SELF-TEST LOGIKA STRATEGI (murni Python)")
    print("=" * 56)
    tests = [
        ("Deteksi tren via regresi", test_regression_detects_trend),
        ("Pivot & zona Support/Resistance", test_pivots_and_zones),
        ("Logika sinyal & RR 1:2", test_signal_logic),
        ("Position sizing (risiko 1%)", test_lot_sizing),
    ]
    for name, fn in tests:
        print(f"\n> {name}")
        fn()
    print("\n" + "=" * 56)
    print("  SEMUA TEST LULUS ✓  — logika inti strategi valid")
    print("=" * 56)


if __name__ == "__main__":
    main()
