"""
Konfigurasi bot scalping XAU/USD multi-timeframe.

Semua parameter strategi, risiko, dan koneksi ada di sini supaya mudah diubah
tanpa menyentuh kode logika.
"""
from dataclasses import dataclass, field


@dataclass
class StrategyConfig:
    # --- Instrumen & timeframe ---
    symbol: str = "XAUUSD"          # sesuaikan dengan nama simbol di broker (Exness kadang "XAUUSDm")
    tf_trend_major: str = "H1"      # arah tren besar
    tf_trend: str = "M30"           # konfirmasi tren (channel regresi)
    tf_zone: str = "M5"             # penentuan zona Support/Resistance
    tf_entry: str = "M1"            # trigger entry (scalping)

    # --- Linear Regression Channel (pengganti channel diagonal manual) ---
    h1_reg_period: int = 50         # jumlah candle H1 untuk hitung tren besar
    m30_reg_period: int = 60        # jumlah candle M30 untuk channel + tren
    channel_deviations: float = 2.0 # lebar band channel (± n deviasi standar)
    min_slope_strength: float = 1.5   # ambang kekuatan kemiringan agar dianggap tren
    min_trend_r2: float = 0.30        # ambang R^2: harga harus mengikuti garis cukup rapi

    # --- Deteksi Support/Resistance (M5) ---
    m5_lookback: int = 120          # jumlah candle M5 yang dipindai untuk cari SnR
    pivot_left: int = 3             # bar kiri untuk konfirmasi swing
    pivot_right: int = 3            # bar kanan untuk konfirmasi swing
    zone_merge_atr_mult: float = 0.5  # gabungkan level SnR yang berdekatan (dalam kelipatan ATR)

    # --- Entry (M1) ---
    touch_atr_mult: float = 0.6     # harga dianggap "menyentuh" zona jika jarak < n * ATR(M1)
    require_candle_confirm: bool = True  # butuh candle rejection/searah sebelum entry
    atr_period: int = 14

    # --- Risk / Reward ---
    risk_reward: float = 2.0        # TP = risk_reward * jarak SL (1:2)
    sl_buffer_atr_mult: float = 0.5 # jarak tambahan SL di luar zona (dalam kelipatan ATR)


@dataclass
class RiskConfig:
    account_currency: str = "USD"
    risk_per_trade_pct: float = 1.0   # risiko maksimum per posisi (% dari balance)
    max_daily_loss_pct: float = 5.0   # bot stop otomatis jika rugi harian capai %
    max_open_positions: int = 1       # scalping: fokus 1 posisi
    max_trades_per_day: int = 20
    # Spesifik XAU/USD di MT5: 1 lot = 100 oz, 1 poin (0.01) ~ $1 per lot.
    # Nilai per 1.0 pergerakan harga per 1.0 lot (gold = 100).
    contract_size: float = 100.0
    min_lot: float = 0.01
    max_lot: float = 1.0
    lot_step: float = 0.01


@dataclass
class MT5Config:
    # Isi dari akun Exness Anda. JANGAN commit kredensial asli ke git.
    login: int = 0
    password: str = ""
    server: str = "Exness-MT5Trial"   # contoh; sesuaikan server Exness Anda
    terminal_path: str = ""           # opsional: path ke terminal64.exe
    magic_number: int = 20260921      # ID unik order dari bot ini
    deviation: int = 20               # slippage maksimum (poin)


@dataclass
class TelegramConfig:
    bot_token: str = ""               # dari @BotFather
    allowed_chat_ids: list = field(default_factory=list)  # hanya chat ID ini yang boleh kontrol


@dataclass
class AppConfig:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    mt5: MT5Config = field(default_factory=MT5Config)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    poll_seconds: int = 5             # jeda loop cek sinyal (detik)
    dry_run: bool = True              # True = hanya sinyal/log, tidak kirim order sungguhan


def load_config() -> AppConfig:
    """Muat konfigurasi. Bisa dikembangkan untuk baca dari file .env / JSON."""
    return AppConfig()
