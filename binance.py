import logging
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pandas_ta as ta
import ccxt
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

NL = chr(10)

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
EXCHANGE_TARGET = os.getenv("EXCHANGE_TARGET", "binance").lower()

RAW_SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "DOGE/USDT,XRP/USDT").split(",")]

TIMEFRAME = os.getenv("TIMEFRAME", "1m")
HTF1_TIMEFRAME = os.getenv("HTF1_TIMEFRAME", "15m")
HTF2_TIMEFRAME = os.getenv("HTF2_TIMEFRAME", "30m")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 10))
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", 5))

SL_MULTIPLIER = float(os.getenv("SL_ATR_MULTIPLIER", 1.0))
TP_MULTIPLIER = float(os.getenv("TP_ATR_MULTIPLIER", 2.0))
MIN_RR_RATIO = float(os.getenv("MIN_RR_RATIO", 1.5))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", 55))
MIN_ADX = float(os.getenv("MIN_ADX", 15.0))
VOLUME_SPIKE_MULT = float(os.getenv("VOLUME_SPIKE_MULT", 1.2))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 15))
MAX_LOSS_STREAK = int(os.getenv("MAX_LOSS_STREAK", 3))
TRAIL_ACTIVATE_R = float(os.getenv("TRAIL_ACTIVATE_R", 1.0))
BREAKEVEN_R = float(os.getenv("BREAKEVEN_R", 0.5))

AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"
LEVERAGE = int(os.getenv("LEVERAGE", 5))
MARGIN_MODE = os.getenv("MARGIN_MODE", "isolated")
RISK_PER_TRADE_USD = float(os.getenv("RISK_PER_TRADE_USD", 1.0))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", 2))
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", 10.0))
SLIPPAGE_PERCENT = float(os.getenv("SLIPPAGE_PERCENT", 0.3))
MIN_NOTIONAL_USD = float(os.getenv("MIN_NOTIONAL_USD", 5.0))

USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"

STATE_FILE = Path("bot_state.json")
STATS_FILE = Path("bot_stats.json")
TRADE_LOG = Path("trades.log")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

exchange = ccxt.binance({
    "apiKey": os.getenv("BINANCE_API_KEY", ""),
    "secret": os.getenv("BINANCE_API_SECRET", ""),
    "enableRateLimit": True,
    "options": {"defaultType": "future", "adjustForTimeDifference": True}
})

if USE_TESTNET:
    log.warning("USE_TESTNET is deprecated by CCXT/Binance. Using REAL account instead.")
    log.warning("Set USE_TESTNET=false in .env to remove this warning.")

SYMBOLS = RAW_SYMBOLS

try:
    exchange.load_markets()
except Exception as e:
    log.warning(f"Load markets error: {e}")

is_scanning = False
active_signals = []
last_signal_time = {}
daily_stats = {"date": "", "wins": 0, "losses": 0, "loss_streak": 0, "pnl_r": 0.0, "pnl_usd": 0.0}
circuit_breaker_until = None

def load_state():
    global active_signals, last_signal_time
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            active_signals = data.get("active_signals", [])
            last_signal_time = {k: datetime.fromisoformat(v) for k, v in data.get("last_signal_time", {}).items()}
            log.info(f"State loaded: {len(active_signals)} active")
        except Exception as e:
            log.warning(f"Load state fail: {e}")

def save_state():
    try:
        STATE_FILE.write_text(json.dumps({
            "active_signals": active_signals,
            "last_signal_time": {k: v.isoformat() for k, v in last_signal_time.items()}
        }, indent=2))
    except Exception as e:
        log.warning(f"Save state fail: {e}")

def load_stats():
    global daily_stats
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if STATS_FILE.exists():
        try:
            data = json.loads(STATS_FILE.read_text())
            if data.get("date") == today:
                daily_stats = data
                return
        except Exception:
            pass
    daily_stats = {"date": today, "wins": 0, "losses": 0, "loss_streak": 0, "pnl_r": 0.0, "pnl_usd": 0.0}

def save_stats():
    try:
        STATS_FILE.write_text(json.dumps(daily_stats, indent=2))
    except Exception:
        pass

def log_trade(msg):
    ts = datetime.utcnow().isoformat()
    try:
        with TRADE_LOG.open("a") as f:
            f.write(f"{ts} | {msg}{NL}")
    except Exception:
        pass

def record_result(win, r_multiple, pnl_usd):
    global circuit_breaker_until
    load_stats()
    if win:
        daily_stats["wins"] += 1
        daily_stats["loss_streak"] = 0
    else:
        daily_stats["losses"] += 1
        daily_stats["loss_streak"] += 1
        if daily_stats["loss_streak"] >= MAX_LOSS_STREAK:
            circuit_breaker_until = datetime.utcnow() + timedelta(hours=4)
            log.warning(f"CIRCUIT BREAKER active until {circuit_breaker_until}")
    daily_stats["pnl_r"] += r_multiple
    daily_stats["pnl_usd"] += pnl_usd
    save_stats()

def get_market_data(symbol, timeframe=None, limit=300):
    if timeframe is None:
        timeframe = TIMEFRAME
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    return df

def parse_args(args, default_tf="1h"):
    if not args:
        return None, None
    symbol = args[0].upper()
    if "/" not in symbol:
        symbol = symbol + "/USDT"
    tf = args[1].lower() if len(args) > 1 else default_tf
    if tf not in ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]:
        tf = default_tf
    return symbol, tf

def detect_snd_zones(df, lookback=100):
    if "atr" not in df.columns:
        df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    df["body"] = abs(df["close"] - df["open"])
    demand_zone, supply_zone = None, None
    n = len(df)
    start = max(0, n - lookback)
    for i in range(start, n - 3):
        atr_val = df["atr"].iloc[i]
        if pd.isna(atr_val) or atr_val == 0:
            continue
        if df["body"].iloc[i] >= atr_val * 0.7:
            continue
        next_body = df["body"].iloc[i + 1]
        next_bull = df["close"].iloc[i + 1] > df["open"].iloc[i + 1]
        if next_body <= atr_val * 1.3:
            continue
        zone_low = df["low"].iloc[i]
        zone_high = df["high"].iloc[i]
        subsequent = df.iloc[i + 2:]
        if next_bull:
            if not (subsequent["low"] <= zone_high).any():
                demand_zone = (zone_low, zone_high)
        else:
            if not (subsequent["high"] >= zone_low).any():
                supply_zone = (zone_low, zone_high)
    return demand_zone, supply_zone

def detect_snr_levels(df, top_n=5, window=5):
    if len(df) < 30:
        return []
    swings = []
    for i in range(window, len(df) - window):
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]
        is_swing_high = True
        is_swing_low = True
        for j in range(1, window + 1):
            if df["high"].iloc[i - j] >= high or df["high"].iloc[i + j] >= high:
                is_swing_high = False
            if df["low"].iloc[i - j] <= low or df["low"].iloc[i + j] <= low:
                is_swing_low = False
            if not is_swing_high and not is_swing_low:
                break
        if is_swing_high:
            swings.append(high)
        if is_swing_low:
            swings.append(low)
    if not swings:
        return []
    swings.sort()
    atr_val = ta.atr(df["high"], df["low"], df["close"], length=14).iloc[-1]
    if pd.isna(atr_val) or atr_val == 0:
        return []
    cluster_dist = atr_val * 0.5
    clustered = []
    current_cluster = [swings[0]]
    for lvl in swings[1:]:
        if lvl - current_cluster[-1] <= cluster_dist:
            current_cluster.append(lvl)
        else:
            avg = sum(current_cluster) / len(current_cluster)
            clustered.append((avg, len(current_cluster)))
            current_cluster = [lvl]
    avg = sum(current_cluster) / len(current_cluster)
    clustered.append((avg, len(current_cluster)))
    clustered.sort(key=lambda x: -x[1])
    return [lvl for lvl, _ in clustered[:top_n]]

def find_nearest_snr(price, levels, atr, max_dist_atr=1.5):
    if not levels:
        return None, None, None
    best_lvl = None
    best_dist = float("inf")
    for lvl in levels:
        d = abs(price - lvl)
        if d < best_dist and d <= atr * max_dist_atr:
            best_dist = d
            best_lvl = lvl
    if best_lvl is None:
        return None, None, None
    zone_type = "resistance" if best_lvl > price else "support"
    return best_lvl, zone_type, best_dist

def is_bullish_engulfing(df):
    if len(df) < 2:
        return False
    p, c = df.iloc[-2], df.iloc[-1]
    return (p["close"] < p["open"]) and (c["close"] > c["open"]) and (c["close"] > p["open"]) and (c["open"] < p["close"])

def is_bearish_engulfing(df):
    if len(df) < 2:
        return False
    p, c = df.iloc[-2], df.iloc[-1]
    return (p["close"] > p["open"]) and (c["close"] < c["open"]) and (c["close"] < p["open"]) and (c["open"] > p["close"])

def is_bullish_pinbar(df):
    c = df.iloc[-1]
    body = abs(c["close"] - c["open"])
    lower = min(c["open"], c["close"]) - c["low"]
    upper = c["high"] - max(c["open"], c["close"])
    return body > 0 and lower > body * 2 and upper < body

def is_bearish_pinbar(df):
    c = df.iloc[-1]
    body = abs(c["close"] - c["open"])
    upper = c["high"] - max(c["open"], c["close"])
    lower = min(c["open"], c["close"]) - c["low"]
    return body > 0 and upper > body * 2 and lower < body

def get_htf_bias(symbol, htf):
    try:
        df = get_market_data(symbol, htf, 250)
        if df is None:
            return "NEUTRAL"
        df["ema50"] = ta.ema(df["close"], length=50)
        df["ema200"] = ta.ema(df["close"], length=200)
        last = df.iloc[-1]
        if pd.isna(last["ema200"]):
            return "NEUTRAL"
        if last["close"] > last["ema200"] and last["ema50"] > last["ema200"]:
            return "BULL"
        if last["close"] < last["ema200"] and last["ema50"] < last["ema200"]:
            return "BEAR"
        return "NEUTRAL"
    except Exception:
        return "NEUTRAL"

def score_signal(checks):
    weights = {
        "confluence": 25, "zone": 15, "snr": 15,
        "htf1": 10, "htf2": 10, "ema_trend": 8,
        "macd": 8, "volume": 5, "adx": 5, "rsi": 3, "candle": 10
    }
    return sum(w for k, w in weights.items() if checks.get(k))

def get_balance_usdt():
    try:
        bal = exchange.fetch_balance()
        return float(bal.get("USDT", {}).get("free", 0))
    except Exception as e:
        log.warning(f"Balance fail: {e}")
        return 0.0

def set_leverage_for(symbol):
    try:
        exchange.set_leverage(LEVERAGE, symbol)
        return True
    except Exception as e:
        log.warning(f"Leverage fail {symbol}: {e}")
        return False

def set_margin_mode_for(symbol):
    try:
        exchange.set_margin_mode(MARGIN_MODE.upper(), symbol)
    except Exception as e:
        if "no need to change" not in str(e).lower():
            log.warning(f"Margin mode: {e}")

def calc_position_size(entry, sl, risk_usd):
    price_risk = abs(entry - sl)
    if price_risk == 0:
        return 0
    return risk_usd / price_risk

def pre_trade_checks(symbol, entry, current_price):
    if not AUTO_TRADE:
        return False, "AUTO_TRADE=false"
    if circuit_breaker_until and datetime.utcnow() < circuit_breaker_until:
        return False, "Circuit breaker active"
    if len(active_signals) >= MAX_POSITIONS:
        return False, f"Max positions ({MAX_POSITIONS})"
    if daily_stats["pnl_usd"] <= -MAX_DAILY_LOSS_USD:
        return False, f"Daily loss ${MAX_DAILY_LOSS_USD}"
    slip = abs(current_price - entry) / entry * 100
    if slip > SLIPPAGE_PERCENT:
        return False, f"Slippage {slip:.2f}% > {SLIPPAGE_PERCENT}%"
    bal = get_balance_usdt()
    if bal < 2:
        return False, f"Balance low: ${bal:.2f}"
    return True, "OK"

def execute_trade(symbol, direction, entry, sl, tp):
    try:
        set_margin_mode_for(symbol)
        set_leverage_for(symbol)

        size = calc_position_size(entry, sl, RISK_PER_TRADE_USD)
        size = float(exchange.amount_to_precision(symbol, size))
        if size <= 0:
            return None, "Size = 0"
        notional = size * entry
        if notional < MIN_NOTIONAL_USD:
            size = float(exchange.amount_to_precision(symbol, MIN_NOTIONAL_USD / entry))

        ticker = exchange.fetch_ticker(symbol)
        current_price = float(ticker["last"])
        ok, reason = pre_trade_checks(symbol, entry, current_price)
        if not ok:
            return None, reason

        side = "buy" if direction == "LONG" else "sell"
        opp_side = "sell" if direction == "LONG" else "buy"

        entry_order = exchange.create_order(symbol, "market", side, size)
        sl_order = exchange.create_order(
            symbol, "STOP_MARKET", opp_side, size, None,
            params={"stopPrice": exchange.price_to_precision(symbol, sl), "reduceOnly": True, "workingType": "MARK_PRICE"}
        )
        tp_order = exchange.create_order(
            symbol, "TAKE_PROFIT_MARKET", opp_side, size, None,
            params={"stopPrice": exchange.price_to_precision(symbol, tp), "reduceOnly": True, "workingType": "MARK_PRICE"}
        )

        fill_price = float(entry_order.get("average") or entry_order.get("price") or current_price)
        log_trade(f"OPEN {direction} {symbol} size={size} fill={fill_price} sl={sl} tp={tp}")

        return {
            "entry_order_id": entry_order.get("id"),
            "sl_order_id": sl_order.get("id"),
            "tp_order_id": tp_order.get("id"),
            "fill_price": fill_price,
            "size": size
        }, None
    except Exception as e:
        log.exception(f"Execute fail: {e}")
        return None, str(e)

def cancel_order_safe(symbol, order_id):
    if not order_id:
        return
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception as e:
        log.warning(f"Cancel {order_id}: {e}")

def modify_sl(trade, new_sl):
    symbol = trade["symbol"]
    size = trade["size"]
    opp_side = "sell" if trade["type"] == "LONG" else "buy"
    try:
        cancel_order_safe(symbol, trade.get("sl_order_id"))
        new_order = exchange.create_order(
            symbol, "STOP_MARKET", opp_side, size, None,
            params={"stopPrice": exchange.price_to_precision(symbol, new_sl), "reduceOnly": True, "workingType": "MARK_PRICE"}
        )
        trade["sl_order_id"] = new_order.get("id")
        trade["sl"] = new_sl
        return True
    except Exception as e:
        log.warning(f"Modify SL fail: {e}")
        return False

def close_position_market(symbol):
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            contracts = float(pos.get("contracts") or 0)
            if contracts == 0:
                continue
            side_close = "sell" if pos["side"] == "long" else "buy"
            exchange.create_order(symbol, "market", side_close, contracts, params={"reduceOnly": True})
    except Exception as e:
        log.warning(f"Close fail: {e}")

async def cmd_start(update, context):
    auto = "ON" if AUTO_TRADE else "OFF"
    net = "TESTNET" if USE_TESTNET else "REAL"
    pesan = f"""*Bot Crypto Scalping v4.0* [BINANCE {net}]

Timeframe: `{TIMEFRAME}` | HTF: `{HTF1_TIMEFRAME}` + `{HTF2_TIMEFRAME}`
Strategy: SnD + SnR Confluence (Bang Ran Style)
AutoTrade: *{auto}* | Leverage: `{LEVERAGE}x`
Risk/Trade: `${RISK_PER_TRADE_USD}` | Max Pos: `{MAX_POSITIONS}`
Symbols: {', '.join(SYMBOLS)}

*Radar:*
`/scan` - Activate
`/stop` - Deactivate
`/autotrade on|off` - Toggle execution

*Management:*
`/balance` `/positions` `/stats` `/panic`

*Analysis:*
`/market <coin> <tf>`
`/trend <coin> <tf>`"""
    await update.message.reply_text(pesan, parse_mode="Markdown")

async def cmd_autotrade(update, context):
    global AUTO_TRADE
    if not context.args:
        await update.message.reply_text(f"AUTO_TRADE: *{'ON' if AUTO_TRADE else 'OFF'}*", parse_mode="Markdown")
        return
    val = context.args[0].lower()
    if val in ("on", "true", "1"):
        AUTO_TRADE = True
        await update.message.reply_text("*AUTO TRADE = ON*", parse_mode="Markdown")
    elif val in ("off", "false", "0"):
        AUTO_TRADE = False
        await update.message.reply_text("*AUTO TRADE = OFF*", parse_mode="Markdown")

async def cmd_balance(update, context):
    try:
        bal = exchange.fetch_balance()
        free = float(bal.get("USDT", {}).get("free", 0))
        total = float(bal.get("USDT", {}).get("total", 0))
        used = total - free
        net = "TESTNET" if USE_TESTNET else "REAL"
        pesan = f"""*BALANCE ({net})*

Free: `${free:.2f}`
Used: `${used:.2f}`
Total: `${total:.2f}`"""
        await update.message.reply_text(pesan, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def cmd_positions(update, context):
    try:
        positions = exchange.fetch_positions()
        active = [p for p in positions if float(p.get("contracts") or 0) > 0]
        if not active:
            await update.message.reply_text("No open positions.")
            return
        lines = ["*OPEN POSITIONS*", ""]
        for p in active:
            pnl = float(p.get("unrealizedPnl") or 0)
            sign = "+" if pnl >= 0 else ""
            sym = p["symbol"]
            entry_px = p.get("entryPrice", 0) or 0
            pct = p.get("percentage", 0) or 0
            lines.append(f"`{sym}` [{p['side'].upper()}]")
            lines.append(f"  Size: {p['contracts']} | Entry: {entry_px}")
            lines.append(f"  PnL: `{sign}${pnl:.2f}` ({pct:+.2f}%)")
            lines.append("")
        await update.message.reply_text(NL.join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def cmd_panic(update, context):
    global is_scanning, AUTO_TRADE
    is_scanning = False
    AUTO_TRADE = False
    closed = 0
    for trade in active_signals[:]:
        try:
            cancel_order_safe(trade["symbol"], trade.get("sl_order_id"))
            cancel_order_safe(trade["symbol"], trade.get("tp_order_id"))
            close_position_market(trade["symbol"])
            active_signals.remove(trade)
            closed += 1
        except Exception as e:
            log.warning(f"Panic close: {e}")
    save_state()
    pesan = f"""*PANIC MODE!*
Radar OFF, AutoTrade OFF
{closed} positions closed."""
    await update.message.reply_text(pesan, parse_mode="Markdown")

async def cmd_stats(update, context):
    load_stats()
    total = daily_stats["wins"] + daily_stats["losses"]
    wr = (daily_stats["wins"] / total * 100) if total else 0
    cb = "ACTIVE" if (circuit_breaker_until and datetime.utcnow() < circuit_breaker_until) else "Normal"
    pesan = f"""*STATS {daily_stats['date']}*

Wins: *{daily_stats['wins']}* | Losses: *{daily_stats['losses']}*
Win Rate: *{wr:.1f}%*
PnL: `${daily_stats['pnl_usd']:+.2f}` (*{daily_stats['pnl_r']:+.2f}R*)
Loss Streak: *{daily_stats['loss_streak']}*
Breaker: {cb}
Active: *{len(active_signals)}* | AutoTrade: *{'ON' if AUTO_TRADE else 'OFF'}*"""
    await update.message.reply_text(pesan, parse_mode="Markdown")

async def cmd_market(update, context):
    symbol, tf = parse_args(context.args, TIMEFRAME)
    if not symbol:
        await update.message.reply_text(f"Format: `/market DOGE/USDT {TIMEFRAME}`", parse_mode="Markdown")
        return
    try:
        df = get_market_data(symbol, tf, 300)
        df["rsi"] = ta.rsi(df["close"], length=14)
        df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
        macd = ta.macd(df["close"])
        df = pd.concat([df, macd], axis=1)
        df.dropna(inplace=True)
        last = df.iloc[-1]
        macd_col = next((c for c in df.columns if "MACDh" in c), None)
        ms = "Bullish" if (macd_col and last[macd_col] > 0) else "Bearish"
        d, s = detect_snd_zones(df)
        snr = detect_snr_levels(df, top_n=3)
        zone_txt = "No zone active"
        if d and d[0] <= last["close"] <= d[1]:
            zone_txt = f"IN DEMAND [{d[0]:.5f}-{d[1]:.5f}]"
        elif s and s[0] <= last["close"] <= s[1]:
            zone_txt = f"IN SUPPLY [{s[0]:.5f}-{s[1]:.5f}]"
        snr_txt = ", ".join([f"{lvl:.5f}" for lvl in snr[:3]])
        pesan = f"""*{symbol} ({tf})*

Price: `{last['close']:.5f}`
RSI: {last['rsi']:.1f} | MACD: {ms}
ATR: {last['atr']:.5f}

{zone_txt}
SnR: {snr_txt}"""
        await update.message.reply_text(pesan, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def cmd_trend(update, context):
    symbol, tf = parse_args(context.args, "4h")
    if not symbol:
        await update.message.reply_text("Format: `/trend BTC/USDT 1h`", parse_mode="Markdown")
        return
    try:
        df = get_market_data(symbol, tf, 300)
        df["ema50"] = ta.ema(df["close"], length=50)
        df["ema200"] = ta.ema(df["close"], length=200)
        adx = ta.adx(df["high"], df["low"], df["close"], length=14)
        df = pd.concat([df, adx], axis=1)
        df.dropna(inplace=True)
        last = df.iloc[-1]
        ac = next((c for c in df.columns if c.startswith("ADX")), None)
        av = last[ac] if ac else 0
        trend = "Sideways"
        if last["close"] > last["ema200"] and last["ema50"] > last["ema200"]:
            trend = "BULLISH"
        elif last["close"] < last["ema200"] and last["ema50"] < last["ema200"]:
            trend = "BEARISH"
        strength = "STRONG" if av > 25 else "Weak"
        pesan = f"""*{symbol} ({tf})*

Trend: *{trend}*
ADX: *{strength}* ({av:.1f})
Price: `{last['close']:.5f}` | EMA200: `{last['ema200']:.5f}`"""
        await update.message.reply_text(pesan, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def cmd_scan(update, context):
    global is_scanning
    if is_scanning:
        await update.message.reply_text("Radar already active.")
        return
    is_scanning = True
    net = "TESTNET" if USE_TESTNET else "REAL"
    pesan = f"""*Radar {TIMEFRAME} ACTIVE!* [{net}]
Scan: {SCAN_INTERVAL}s | AutoTrade: *{'ON' if AUTO_TRADE else 'OFF'}*
Strategy: SnD + SnR Confluence
Symbols: {', '.join(SYMBOLS)}"""
    await update.message.reply_text(pesan, parse_mode="Markdown")

async def cmd_stop(update, context):
    global is_scanning
    is_scanning = False
    save_state()
    await update.message.reply_text("Radar off. State saved.")

async def scan_new_signals(context):
    global circuit_breaker_until
    if circuit_breaker_until and datetime.utcnow() < circuit_breaker_until:
        return
    now = datetime.utcnow()
    for symbol in SYMBOLS:
        try:
            if symbol in [t["symbol"] for t in active_signals]:
                continue
            last_t = last_signal_time.get(symbol)
            if last_t and (now - last_t) < timedelta(minutes=COOLDOWN_MINUTES):
                continue

            df = get_market_data(symbol, TIMEFRAME, 300)
            df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
            df["ema50"] = ta.ema(df["close"], length=50)
            df["ema200"] = ta.ema(df["close"], length=200)
            df["rsi"] = ta.rsi(df["close"], length=14)
            df["vol_ma"] = df["volume"].rolling(20).mean()
            macd = ta.macd(df["close"])
            df = pd.concat([df, macd], axis=1)
            adx = ta.adx(df["high"], df["low"], df["close"], length=14)
            df = pd.concat([df, adx], axis=1)
            df.dropna(inplace=True)
            if len(df) < 50:
                continue

            demand_zone, supply_zone = detect_snd_zones(df)
            last = df.iloc[-1]
            price = last["close"]
            macd_col = next((c for c in df.columns if "MACDh" in c), None)
            adx_col = next((c for c in df.columns if c.startswith("ADX")), None)
            adx_val = last[adx_col] if adx_col else 0
            if adx_val < MIN_ADX:
                continue

            df_htf = get_market_data(symbol, HTF1_TIMEFRAME, 300)
            if df_htf is not None and len(df_htf) > 30:
                snr_levels = detect_snr_levels(df_htf, top_n=5)
                atr_htf = ta.atr(df_htf["high"], df_htf["low"], df_htf["close"], length=14).iloc[-1]
                if pd.isna(atr_htf):
                    atr_htf = last["atr"]
            else:
                snr_levels = []
                atr_htf = last["atr"]

            snr_level, snr_type, snr_dist = find_nearest_snr(price, snr_levels, atr_htf, max_dist_atr=1.0)

            htf1 = get_htf_bias(symbol, HTF1_TIMEFRAME)
            htf2 = get_htf_bias(symbol, HTF2_TIMEFRAME)

            in_demand = demand_zone and demand_zone[0] <= price <= demand_zone[1]
            in_supply = supply_zone and supply_zone[0] <= price <= supply_zone[1]
            near_support = snr_level and snr_type == "support"
            near_resistance = snr_level and snr_type == "resistance"

            direction = None
            zone = None
            setup_type = None
            is_confluence = False

            if in_demand and near_support:
                direction = "LONG"
                zone = demand_zone
                setup_type = "CONFLUENCE_LONG"
                is_confluence = True
            elif in_supply and near_resistance:
                direction = "SHORT"
                zone = supply_zone
                setup_type = "CONFLUENCE_SHORT"
                is_confluence = True
            elif in_demand:
                direction = "LONG"
                zone = demand_zone
                setup_type = "DEMAND_ONLY"
            elif in_supply:
                direction = "SHORT"
                zone = supply_zone
                setup_type = "SUPPLY_ONLY"
            elif near_support and abs(price - snr_level) <= atr_htf * 0.3:
                direction = "LONG"
                zone = (snr_level - atr_htf * 0.3, snr_level + atr_htf * 0.3)
                setup_type = "SNR_SUPPORT"
            elif near_resistance and abs(price - snr_level) <= atr_htf * 0.3:
                direction = "SHORT"
                zone = (snr_level - atr_htf * 0.3, snr_level + atr_htf * 0.3)
                setup_type = "SNR_RESISTANCE"

            if not direction:
                continue

            checks = {"adx": adx_val >= 20, "rsi": 25 < last["rsi"] < 75}
            if is_confluence:
                checks["confluence"] = True
            if zone:
                checks["zone"] = True
            if snr_level:
                checks["snr"] = True

            if direction == "LONG":
                checks["htf1"] = htf1 in ("BULL", "NEUTRAL")
                checks["htf2"] = htf2 in ("BULL", "NEUTRAL")
                checks["ema_trend"] = price > last["ema200"]
                checks["macd"] = bool(macd_col) and last[macd_col] > 0
                checks["volume"] = last["volume"] > last["vol_ma"] * VOLUME_SPIKE_MULT
                checks["candle"] = is_bullish_engulfing(df) or is_bullish_pinbar(df)
                entry_price = price
                sl = zone[0] - (last["atr"] * 0.3)
                risk = entry_price - sl
                if snr_levels:
                    higher_snr = [lvl for lvl in snr_levels if lvl > price]
                    if higher_snr:
                        tp = min(higher_snr) - atr_htf * 0.1
                    else:
                        tp = entry_price + risk * MIN_RR_RATIO
                else:
                    tp = entry_price + risk * MIN_RR_RATIO
                atr_tp = entry_price + last["atr"] * TP_MULTIPLIER
                if atr_tp > tp:
                    tp = atr_tp
            else:
                checks["htf1"] = htf1 in ("BEAR", "NEUTRAL")
                checks["htf2"] = htf2 in ("BEAR", "NEUTRAL")
                checks["ema_trend"] = price < last["ema200"]
                checks["macd"] = bool(macd_col) and last[macd_col] < 0
                checks["volume"] = last["volume"] > last["vol_ma"] * VOLUME_SPIKE_MULT
                checks["candle"] = is_bearish_engulfing(df) or is_bearish_pinbar(df)
                entry_price = price
                sl = zone[1] + (last["atr"] * 0.3)
                risk = sl - entry_price
                if snr_levels:
                    lower_snr = [lvl for lvl in snr_levels if lvl < price]
                    if lower_snr:
                        tp = max(lower_snr) + atr_htf * 0.1
                    else:
                        tp = entry_price - risk * MIN_RR_RATIO
                else:
                    tp = entry_price - risk * MIN_RR_RATIO
                atr_tp = entry_price - last["atr"] * TP_MULTIPLIER
                if atr_tp < tp:
                    tp = atr_tp

            score = score_signal(checks)
            rr = abs(tp - entry_price) / abs(entry_price - sl) if entry_price != sl else 0
            if score < MIN_CONFIDENCE or rr < MIN_RR_RATIO:
                continue

            trade = {
                "symbol": symbol, "type": direction,
                "entry": entry_price, "tp": tp, "sl": sl,
                "initial_risk": abs(entry_price - sl),
                "score": score, "setup_type": setup_type,
                "opened_at": now.isoformat(),
                "size": 0, "entry_order_id": None,
                "sl_order_id": None, "tp_order_id": None,
                "executed": False, "be_moved": False
            }

            if AUTO_TRADE:
                result, err = execute_trade(symbol, direction, entry_price, sl, tp)
                if err:
                    await context.bot.send_message(chat_id=CHAT_ID, text=f"*SKIPPED* `{symbol}` - {err}", parse_mode="Markdown")
                    continue
                trade.update(result)
                trade["executed"] = True
                trade["entry"] = result["fill_price"]
                trade["initial_risk"] = abs(result["fill_price"] - sl)

            active_signals.append(trade)
            last_signal_time[symbol] = now
            save_state()
            await send_signal_alert(context, trade, checks, htf1, htf2, rr, setup_type)
        except Exception as e:
            log.warning(f"Scan error {symbol}: {e}")

async def send_signal_alert(context, trade, checks, htf1, htf2, rr, setup_type):
    status = "EXECUTED" if trade["executed"] else "SIGNAL"
    reasons = []
    if checks.get("confluence"):
        reasons.append("SnD+SnR CONFLUENCE")
    else:
        if checks.get("zone"):
            reasons.append("SnD zone")
        if checks.get("snr"):
            reasons.append("SnR level")
    if checks.get("htf1"):
        reasons.append(f"HTF{HTF1_TIMEFRAME}")
    if checks.get("htf2"):
        reasons.append(f"HTF{HTF2_TIMEFRAME}")
    if checks.get("ema_trend"):
        reasons.append("EMA200")
    if checks.get("macd"):
        reasons.append("MACD")
    if checks.get("volume"):
        reasons.append("Volume")
    if checks.get("candle"):
        reasons.append("Candle pattern")

    exec_info = ""
    if trade["executed"]:
        exec_info = f"""

*Execution:*
Fill: `{trade['entry']:.5f}`
Size: `{trade['size']}`
Leverage: `{LEVERAGE}x`
Risk: `${RISK_PER_TRADE_USD}`"""

    reasons_txt = ", ".join(reasons)
    pesan = f"""*{trade['type']}* - {status} (Score: {trade['score']}/100)
`{trade['symbol']}` [{TIMEFRAME}]
Setup: *{setup_type}*

Entry: `{trade['entry']:.5f}`
SL: `{trade['sl']:.5f}`
TP: `{trade['tp']:.5f}`
R:R: *1:{rr:.2f}*

*Confirm:* {reasons_txt}{exec_info}"""
    await context.bot.send_message(chat_id=CHAT_ID, text=pesan, parse_mode="Markdown")

async def monitor_positions(context):
    if not active_signals:
        return
    for trade in active_signals[:]:
        try:
            symbol = trade["symbol"]
            ticker = exchange.fetch_ticker(symbol)
            price = float(ticker["last"])
            entry = trade["entry"]
            initial_risk = trade["initial_risk"]
            direction = trade["type"]

            if direction == "LONG":
                current_r = (price - entry) / initial_risk if initial_risk else 0
            else:
                current_r = (entry - price) / initial_risk if initial_risk else 0

            if not trade.get("be_moved") and current_r >= BREAKEVEN_R:
                if trade["executed"]:
                    if modify_sl(trade, entry):
                        trade["be_moved"] = True
                        await context.bot.send_message(chat_id=CHAT_ID, text=f"*BE* `{symbol}` SL->entry (+{BREAKEVEN_R}R)", parse_mode="Markdown")
                else:
                    trade["sl"] = entry
                    trade["be_moved"] = True

            if current_r >= TRAIL_ACTIVATE_R:
                if direction == "LONG":
                    new_sl = price - initial_risk
                    if new_sl > trade["sl"]:
                        if trade["executed"]:
                            modify_sl(trade, new_sl)
                        else:
                            trade["sl"] = new_sl
                else:
                    new_sl = price + initial_risk
                    if new_sl < trade["sl"]:
                        if trade["executed"]:
                            modify_sl(trade, new_sl)
                        else:
                            trade["sl"] = new_sl

            hit = None
            if direction == "LONG":
                if price >= trade["tp"]:
                    hit = ("TP", True)
                elif price <= trade["sl"]:
                    hit = ("SL", False)
            else:
                if price <= trade["tp"]:
                    hit = ("TP", True)
                elif price >= trade["sl"]:
                    hit = ("SL", False)

            if trade["executed"]:
                try:
                    positions = exchange.fetch_positions([symbol])
                    still_open = any(float(p.get("contracts") or 0) > 0 for p in positions)
                    if not still_open and not hit:
                        hit = ("TP", current_r > 0) if current_r > 0 else ("SL", False)
                except Exception:
                    pass

            if hit:
                label, is_win = hit
                if direction == "LONG":
                    r_val = (price - entry) / initial_risk if initial_risk else 0
                else:
                    r_val = (entry - price) / initial_risk if initial_risk else 0
                pnl_usd = r_val * RISK_PER_TRADE_USD if trade["executed"] else 0
                if trade["executed"]:
                    cancel_order_safe(symbol, trade.get("sl_order_id"))
                    cancel_order_safe(symbol, trade.get("tp_order_id"))
                pnl_txt = f" | PnL: `${pnl_usd:+.2f}`" if trade["executed"] else ""
                pesan = f"""*HIT {label}* `{symbol}` {direction}
Price: `{price:.5f}` | *{r_val:+.2f}R*{pnl_txt}"""
                await context.bot.send_message(chat_id=CHAT_ID, text=pesan, parse_mode="Markdown")
                log_trade(f"CLOSE {direction} {symbol} @ {price} r={r_val:.2f} pnl={pnl_usd:.2f}")
                record_result(is_win, r_val, pnl_usd)
                active_signals.remove(trade)
                save_state()
        except Exception as e:
            log.warning(f"Monitor error: {e}")

async def radar_job(context):
    if not is_scanning:
        return
    await scan_new_signals(context)

async def monitor_job(context):
    await monitor_positions(context)

if __name__ == "__main__":
    load_state()
    load_stats()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("market", cmd_market))
    app.add_handler(CommandHandler("trend", cmd_trend))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("autotrade", cmd_autotrade))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("panic", cmd_panic))

    app.job_queue.run_repeating(radar_job, interval=SCAN_INTERVAL, first=5)
    app.job_queue.run_repeating(monitor_job, interval=MONITOR_INTERVAL, first=8)

    log.info(f"Bot v4.0 Scalping Ready! TF={TIMEFRAME} AutoTrade={AUTO_TRADE} Testnet={USE_TESTNET}")
    app.run_polling()
