use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Ohlcv {
    pub timestamp: i64,
    pub open: Decimal,
    pub high: Decimal,
    pub low: Decimal,
    pub close: Decimal,
    pub volume: Decimal,
}

impl Ohlcv {
    pub fn from_dict(d: &serde_json::Value) -> Option<Self> {
        Some(Self {
            timestamp: d.get("timestamp")
                .or_else(|| d.get("time"))
                .and_then(|v| v.as_i64())
                .unwrap_or(0),
            open: parse_decimal(d, "open")?,
            high: parse_decimal(d, "high")?,
            low: parse_decimal(d, "low")?,
            close: parse_decimal(d, "close")?,
            volume: parse_decimal(d, "volume")?,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderResult {
    pub order_id: String,
    pub symbol: String,
    pub side: String,
    pub quantity: Decimal,
    pub price: Decimal,
    pub status: String,
    pub timestamp: String,
    #[serde(default)]
    pub raw: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Balance {
    pub cash: Decimal,
    pub total_value: Decimal,
    #[serde(default)]
    pub positions: HashMap<String, Decimal>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Signal {
    pub action: String,
    pub symbol: String,
    #[serde(default)]
    pub confidence: Decimal,
    #[serde(default)]
    pub reason: String,
    #[serde(default)]
    pub position_pct: Decimal,
    pub stop_loss: Option<Decimal>,
    pub take_profit: Option<Decimal>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskConfig {
    #[serde(default = "default_max_position_pct")]
    pub max_position_pct: Decimal,
    #[serde(default = "default_max_total_exposure")]
    pub max_total_exposure: Decimal,
    #[serde(default = "default_max_positions")]
    pub max_positions: u32,
    #[serde(default = "default_max_order_value")]
    pub max_order_value: Decimal,
    #[serde(default = "default_stop_loss_pct")]
    pub stop_loss_pct: Decimal,
    #[serde(default = "default_take_profit_pct")]
    pub take_profit_pct: Decimal,
    #[serde(default = "default_portfolio_stop_pct")]
    pub portfolio_stop_pct: Decimal,
    #[serde(default = "default_min_cash_reserve")]
    pub min_cash_reserve: Decimal,
    #[serde(default = "default_max_daily_trades")]
    pub max_daily_trades: u32,
    #[serde(default = "default_max_correlation")]
    pub max_correlation: Decimal,
    #[serde(default = "default_kelly_fraction")]
    pub kelly_fraction: Decimal,
    #[serde(default = "default_default_win_prob")]
    pub default_win_prob: Decimal,
    #[serde(default = "default_default_wl_ratio")]
    pub default_wl_ratio: Decimal,
    #[serde(default = "default_var_confidence")]
    pub var_confidence: Decimal,
    #[serde(default = "default_var_window_days")]
    pub var_window_days: u32,
    #[serde(default = "default_daily_vol_assumption")]
    pub daily_vol_assumption: Decimal,
}

impl Default for RiskConfig {
    fn default() -> Self {
        Self {
            max_position_pct: Decimal::new(20, 2),   // 0.20
            max_total_exposure: Decimal::new(60, 2),  // 0.60
            max_positions: 5,
            max_order_value: Decimal::new(50000, 0),
            stop_loss_pct: Decimal::new(4, 2),        // 0.04
            take_profit_pct: Decimal::new(8, 2),      // 0.08
            portfolio_stop_pct: Decimal::new(15, 2),  // 0.15
            min_cash_reserve: Decimal::new(5, 0),
            max_daily_trades: 500,
            max_correlation: Decimal::new(80, 2),     // 0.80
            kelly_fraction: Decimal::new(35, 2),      // 0.35
            default_win_prob: Decimal::new(55, 2),    // 0.55
            default_wl_ratio: Decimal::new(15, 1),    // 1.5
            var_confidence: Decimal::new(95, 2),      // 0.95
            var_window_days: 30,
            daily_vol_assumption: Decimal::new(2, 2), // 0.02
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskResult {
    pub approved: bool,
    #[serde(default)]
    pub reason: String,
    #[serde(default)]
    pub adjusted_size: Decimal,
    pub adjusted_stop: Option<Decimal>,
    pub adjusted_tp: Option<Decimal>,
}

fn parse_decimal(d: &serde_json::Value, key: &str) -> Option<Decimal> {
    d.get(key).and_then(|v| {
        if let Some(n) = v.as_f64() {
            Decimal::try_from(n).ok()
        } else if let Some(s) = v.as_str() {
            s.parse().ok()
        } else {
            None
        }
    })
}

fn default_max_position_pct() -> Decimal { Decimal::new(20, 2) }
fn default_max_total_exposure() -> Decimal { Decimal::new(60, 2) }
fn default_max_positions() -> u32 { 5 }
fn default_max_order_value() -> Decimal { Decimal::new(50000, 0) }
fn default_stop_loss_pct() -> Decimal { Decimal::new(4, 2) }
fn default_take_profit_pct() -> Decimal { Decimal::new(8, 2) }
fn default_portfolio_stop_pct() -> Decimal { Decimal::new(15, 2) }
fn default_min_cash_reserve() -> Decimal { Decimal::new(5, 0) }
fn default_max_daily_trades() -> u32 { 500 }
fn default_max_correlation() -> Decimal { Decimal::new(80, 2) }
fn default_kelly_fraction() -> Decimal { Decimal::new(35, 2) }
fn default_default_win_prob() -> Decimal { Decimal::new(55, 2) }
fn default_default_wl_ratio() -> Decimal { Decimal::new(15, 1) }
fn default_var_confidence() -> Decimal { Decimal::new(95, 2) }
fn default_var_window_days() -> u32 { 30 }
fn default_daily_vol_assumption() -> Decimal { Decimal::new(2, 2) }
