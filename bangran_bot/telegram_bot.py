"""
Kontrol bot via Telegram (python-telegram-bot v20+, async).

Perintah:
  /start     - mulai bot trading
  /stop      - hentikan bot
  /pause     - jeda (tidak entry baru, posisi berjalan tetap)
  /resume    - lanjutkan
  /status    - lihat status & P/L hari ini
  /balance   - lihat balance & equity
  /positions - daftar posisi terbuka

Hanya chat ID di allowed_chat_ids yang boleh mengontrol (keamanan).
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from config import AppConfig
from engine import TradingEngine


class TelegramController:
    def __init__(self, cfg: AppConfig, engine: TradingEngine):
        self.cfg = cfg
        self.engine = engine
        self.app = Application.builder().token(cfg.telegram.bot_token).build()
        self._register()

    def _register(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("stop", self.cmd_stop))
        self.app.add_handler(CommandHandler("pause", self.cmd_pause))
        self.app.add_handler(CommandHandler("resume", self.cmd_resume))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("balance", self.cmd_balance))
        self.app.add_handler(CommandHandler("positions", self.cmd_positions))

    def _authorized(self, update: Update) -> bool:
        allowed = self.cfg.telegram.allowed_chat_ids
        if not allowed:
            return True  # kalau belum diset, izinkan (disarankan diisi!)
        return update.effective_chat.id in allowed

    async def _guard(self, update: Update) -> bool:
        if not self._authorized(update):
            await update.message.reply_text("⛔ Anda tidak diizinkan mengontrol bot ini.")
            return False
        return True

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._guard(update):
            return
        await update.message.reply_text(self.engine.start())

    async def cmd_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._guard(update):
            return
        await update.message.reply_text(self.engine.stop())

    async def cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._guard(update):
            return
        await update.message.reply_text(self.engine.pause())

    async def cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._guard(update):
            return
        await update.message.reply_text(self.engine.resume())

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._guard(update):
            return
        await update.message.reply_text(self.engine.status_text())

    async def cmd_balance(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._guard(update):
            return
        s = self.engine.state
        await update.message.reply_text(f"💰 Balance: {s.balance:,.2f}\nEquity: {s.equity:,.2f}")

    async def cmd_positions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._guard(update):
            return
        try:
            pos = self.engine.connector.open_positions(self.cfg.strategy.symbol)
        except Exception as e:
            await update.message.reply_text(f"⚠️ {e}")
            return
        if not pos:
            await update.message.reply_text("Tidak ada posisi terbuka.")
            return
        lines = []
        for p in pos:
            side = "BUY" if p.type == 0 else "SELL"
            lines.append(f"{side} {p.volume} @ {p.price_open:.2f} | P/L {p.profit:.2f}")
        await update.message.reply_text("📂 Posisi:\n" + "\n".join(lines))

    def notify_sync(self, text: str):
        """Kirim notifikasi ke semua allowed chat (dipanggil dari thread engine)."""
        import asyncio
        chat_ids = self.cfg.telegram.allowed_chat_ids
        if not chat_ids:
            return
        async def _send():
            for cid in chat_ids:
                try:
                    await self.app.bot.send_message(chat_id=cid, text=text)
                except Exception:
                    pass
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(_send(), loop)
            else:
                loop.run_until_complete(_send())
        except RuntimeError:
            asyncio.run(_send())

    def run(self):
        """Blocking: jalankan polling Telegram."""
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)
