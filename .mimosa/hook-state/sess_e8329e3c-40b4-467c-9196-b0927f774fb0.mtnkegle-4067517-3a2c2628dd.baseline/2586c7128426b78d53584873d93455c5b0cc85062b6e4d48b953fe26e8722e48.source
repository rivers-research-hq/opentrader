use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(tag = "method")]
pub enum Request {
    // Exchange
    #[serde(rename = "exchange.connect")]
    Connect {},
    #[serde(rename = "exchange.load_bars")]
    LoadBars { symbol: String, bars: Vec<serde_json::Value> },
    #[serde(rename = "exchange.push_bar")]
    PushBar { symbol: String, bar: serde_json::Value },
    #[serde(rename = "exchange.get_bars")]
    GetBars { symbol: String, limit: Option<usize> },
    #[serde(rename = "exchange.get_current_price")]
    GetCurrentPrice { symbol: String },
    #[serde(rename = "exchange.place_order")]
    PlaceOrder {
        symbol: String,
        side: String,
        quantity: f64,
        price: Option<f64>,
    },
    #[serde(rename = "exchange.get_balance")]
    GetBalance {},
    #[serde(rename = "exchange.reset")]
    Reset { initial_cash: Option<f64> },
    #[serde(rename = "exchange.discover_symbols")]
    DiscoverSymbols {},
    #[serde(rename = "exchange.get_state")]
    GetState {},
    #[serde(rename = "exchange.load_state")]
    LoadState {
        state: serde_json::Value,
        config: Option<serde_json::Value>,
    },
    #[serde(rename = "exchange.set_slippage")]
    SetSlippage { pct: f64 },
    #[serde(rename = "exchange.set_partial_fill")]
    SetPartialFill { prob: f64, ratio: Option<f64> },
    #[serde(rename = "exchange.get_fills")]
    GetFills {},

    // Risk
    #[serde(rename = "risk.check")]
    RiskCheck {
        signal: crate::types::Signal,
        portfolio_total_value: f64,
        portfolio_cash: f64,
        prices: std::collections::HashMap<String, f64>,
        #[serde(default)]
        current_positions: Option<std::collections::HashMap<String, f64>>,
    },
    #[serde(rename = "risk.pre_trade_check")]
    RiskPreTradeCheck {
        signal: crate::types::Signal,
        portfolio_total_value: f64,
        portfolio_cash: f64,
        prices: std::collections::HashMap<String, f64>,
        #[serde(default)]
        current_positions: Option<std::collections::HashMap<String, f64>>,
        #[serde(default)]
        price_history: Option<std::collections::HashMap<String, Vec<f64>>>,
    },
    #[serde(rename = "risk.set_initial")]
    RiskSetInitial { cash: f64 },
    #[serde(rename = "risk.update_peak")]
    RiskUpdatePeak { portfolio_value: f64 },
    #[serde(rename = "risk.check_circuit_breaker")]
    RiskCheckCircuitBreaker { portfolio_value: f64 },
    #[serde(rename = "risk.kelly_criterion")]
    RiskKelly {
        win_prob: Option<f64>,
        win_loss_ratio: Option<f64>,
    },
    #[serde(rename = "risk.var_calculation")]
    RiskVar {
        portfolio_value: f64,
        confidence: Option<f64>,
    },
    #[serde(rename = "risk.get_config")]
    RiskGetConfig {},
    #[serde(rename = "risk.set_config")]
    RiskSetConfig { config: crate::types::RiskConfig },
    #[serde(rename = "risk.check_correlation")]
    RiskCheckCorrelation {
        new_symbol: String,
        existing_positions: std::collections::HashMap<String, f64>,
        price_history: std::collections::HashMap<String, Vec<f64>>,
    },

    // Health
    #[serde(rename = "ping")]
    Ping {},
    #[serde(rename = "shutdown")]
    Shutdown {},
}

#[derive(Debug, Serialize)]
pub struct Response {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<u64>,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
}

impl Response {
    pub fn success(result: serde_json::Value) -> Self {
        Self { id: None, ok: true, error: None, result: Some(result) }
    }
    pub fn success_null() -> Self {
        Self { id: None, ok: true, error: None, result: None }
    }
    pub fn error(msg: &str) -> Self {
        Self { id: None, ok: false, error: Some(msg.into()), result: None }
    }
}
