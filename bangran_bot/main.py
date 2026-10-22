"""
Titik masuk: menjalankan bot live (MT5 + Telegram).

Jalankan di Windows dengan MT5 Exness terpasang & login.
    python main.py

Konfigurasi kredensial via environment variable (disarankan) atau edit config.py.
Env yang didukung:
    MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_SYMBOL
    TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS (dipisah koma)
    DRY_RUN=1  -> hanya kirim sinyal, tidak order sungguhan
"""
from __future__ import annotations

import os

from config import load_config
from engine import TradingEngine


def apply_env(cfg):
    if os.getenv("MT5_LOGIN"):
        cfg.mt5.login = int(os.getenv("MT5_LOGIN"))
    if os.getenv("MT5_PASSWORD"):
        cfg.mt5.password = os.getenv("MT5_PASSWORD")
    if os.getenv("MT5_SERVER"):
        cfg.mt5.server = os.getenv("MT5_SERVER")
    if os.getenv("MT5_SYMBOL"):
        cfg.strategy.symbol = os.getenv("MT5_SYMBOL")
    if os.getenv("TELEGRAM_TOKEN"):
        cfg.telegram.bot_token = os.getenv("TELEGRAM_TOKEN")
    if os.getenv("TELEGRAM_CHAT_IDS"):
        cfg.telegram.allowed_chat_ids = [
            int(x) for x in os.getenv("TELEGRAM_CHAT_IDS").split(",") if x.strip()
        ]
    if os.getenv("DRY_RUN") is not None:
        cfg.dry_run = os.getenv("DRY_RUN") not in ("0", "false", "False", "")
    return cfg


def main():
    cfg = apply_env(load_config())

    if not cfg.telegram.bot_token:
        raise SystemExit("TELEGRAM_TOKEN belum diisi. Set env atau edit config.py.")

    # import di sini agar backtest tak butuh MT5/telegram terpasang
    from mt5_connector import MT5Connector, MT5_AVAILABLE
    from telegram_bot import TelegramController

    if not MT5_AVAILABLE:
        raise SystemExit(
            "MetaTrader5 tidak tersedia. Jalankan di Windows dengan MT5 terpasang."
        )

    # pasang symbol ke konektor config
    cfg.mt5.symbol = cfg.strategy.symbol  # type: ignore[attr-defined]
    connector = MT5Connector(cfg.mt5)

    controller = None

    def notify(text: str):
        if controller is not None:
            controller.notify_sync(text)
        print(text)

    engine = TradingEngine(cfg, connector, notify=notify)
    controller = TelegramController(cfg, engine)

    mode = "DRY RUN (hanya sinyal)" if cfg.dry_run else "LIVE (order sungguhan)"
    print(f"Bot siap. Mode: {mode}. Buka Telegram & kirim /start untuk memulai.")
    controller.run()


if __name__ == "__main__":
    main()
