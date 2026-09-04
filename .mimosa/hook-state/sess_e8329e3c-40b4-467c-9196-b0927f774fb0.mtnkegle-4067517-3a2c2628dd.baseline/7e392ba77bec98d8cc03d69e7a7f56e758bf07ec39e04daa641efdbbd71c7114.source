use std::collections::HashMap;
use chrono::Utc;
use rand::Rng;
use rust_decimal::Decimal;
use rust_decimal::prelude::Zero;
use serde_json::Value;
use crate::types::{Balance, Ohlcv, OrderResult};
use rust_decimal::prelude::ToPrimitive;

const MAX_BARS_PER_SYMBOL: usize = 10_000;

pub struct PaperExchange {
    pub cash: Decimal,
    pub positions: HashMap<String, Decimal>,
    pub cost_basis: HashMap<String, Decimal>,
    pub fills: Vec<Value>,
    pub prices: HashMap<String, Decimal>,
    pub bars: HashMap<String, Vec<Ohlcv>>,
    order_counter: u64,
    slippage_pct: Decimal,
    partial_fill_prob: Decimal,
    partial_fill_ratio: Decimal,
}

impl PaperExchange {
    pub fn new(config: Option<&Value>) -> Self {
        let initial_cash = config
            .and_then(|c| c.get("initial_cash"))
            .and_then(|v| v.as_f64())
            .map(|f| Decimal::try_from(f).ok())
            .flatten()
            .unwrap_or(Decimal::new(100_000, 0));

        let slippage_pct = config
            .and_then(|c| c.get("slippage_pct"))
            .and_then(|v| v.as_f64())
            .map(|f| Decimal::try_from(f).ok())
            .flatten()
            .unwrap_or(Decimal::zero());

        let partial_fill_prob = config
            .and_then(|c| c.get("partial_fill_prob"))
            .and_then(|v| v.as_f64())
            .map(|f| Decimal::try_from(f).ok())
            .flatten()
            .unwrap_or(Decimal::zero());

        let partial_fill_ratio = config
            .and_then(|c| c.get("partial_fill_ratio"))
            .and_then(|v| v.as_f64())
            .map(|f| Decimal::try_from(f).ok())
            .flatten()
            .unwrap_or(Decimal::new(7, 1)); // 0.7

        Self {
            cash: initial_cash,
            positions: HashMap::new(),
            cost_basis: HashMap::new(),
            fills: Vec::new(),
            prices: HashMap::new(),
            bars: HashMap::new(),
            order_counter: 1,
            slippage_pct,
            partial_fill_prob,
            partial_fill_ratio,
        }
    }

    pub fn load_bars(&mut self, symbol: &str, bars: &[Value]) {
        let ohlcvs: Vec<Ohlcv> = bars.iter().filter_map(Ohlcv::from_dict).collect();
        if let Some(last) = ohlcvs.last() {
            self.prices.insert(symbol.to_string(), last.close);
        }
        self.bars.insert(symbol.to_string(), ohlcvs);
    }

    pub fn push_bar(&mut self, symbol: &str, bar: &Value) {
        if let Some(ohlcv) = Ohlcv::from_dict(bar) {
            let close = ohlcv.close;
            let entry = self.bars.entry(symbol.to_string()).or_default();
            entry.push(ohlcv);
            if entry.len() > MAX_BARS_PER_SYMBOL {
                let start = entry.len() - MAX_BARS_PER_SYMBOL;
                *entry = entry.drain(start..).collect();
            }
            self.prices.insert(symbol.to_string(), close);
        }
    }

    pub fn get_bars(&self, symbol: &str, limit: usize) -> Vec<Ohlcv> {
        let bars = self.bars.get(symbol);
        match bars {
            Some(b) if b.len() > limit => b[b.len() - limit..].to_vec(),
            Some(b) => b.clone(),
            None => vec![],
        }
    }

    pub fn get_current_price(&self, symbol: &str) -> Option<Decimal> {
        self.prices.get(symbol).copied()
    }

    pub fn place_order(
        &mut self,
        symbol: &str,
        side: &str,
        quantity: Decimal,
        price: Option<Decimal>,
    ) -> OrderResult {
        let mut rng = rand::thread_rng();
        let now = Utc::now().to_rfc3339();

        let base_price = match price {
            Some(p) if p > Decimal::zero() => p,
            _ => match self.prices.get(symbol) {
                Some(p) => *p,
                None => {
                    return OrderResult {
                        order_id: String::new(),
                        symbol: symbol.to_string(),
                        side: side.to_string(),
                        quantity,
                        price: Decimal::zero(),
                        status: "rejected".into(),
                        timestamp: now,
                        raw: [("error".into(), Value::String("no price data".into()))]
                            .into_iter()
                            .collect(),
                    };
                }
            },
        };

        let slippage = self.slippage_pct;
        let fill_price = if side.eq_ignore_ascii_case("BUY") {
            base_price * (Decimal::ONE + slippage)
        } else {
            base_price * (Decimal::ONE - slippage)
        };

        let mut effective_qty = quantity;
        let mut fill_pct = Decimal::ONE;

        if self.partial_fill_prob > Decimal::zero()
            && rng.gen::<f64>() < self.partial_fill_prob.to_f64().unwrap_or(0.0)
        {
            let fr = self.partial_fill_ratio.to_f64().unwrap_or(0.7);
            let ratio = Decimal::try_from(fr + rng.gen::<f64>() * (1.0 - fr)).unwrap_or(Decimal::ONE);
            effective_qty *= ratio;
            fill_pct = ratio;
        }

        let mut cost = fill_price * effective_qty;

        if side.eq_ignore_ascii_case("BUY") {
            if cost > self.cash {
                let affordable_qty = self.cash / fill_price;
                if affordable_qty <= Decimal::zero() {
                    return OrderResult {
                        order_id: format!("paper_{}", self.order_counter),
                        symbol: symbol.to_string(),
                        side: side.to_string(),
                        quantity: effective_qty,
                        price: fill_price,
                        status: "rejected".into(),
                        timestamp: now,
                        raw: [("error".into(), Value::String("insufficient cash".into()))]
                            .into_iter()
                            .collect(),
                    };
                }
                effective_qty = affordable_qty;
                fill_pct = effective_qty / if quantity.is_zero() { Decimal::ONE } else { quantity };
                cost = fill_price * effective_qty;
            }
            self.cash -= cost;
            *self.positions.entry(symbol.to_string()).or_insert(Decimal::zero()) +=
                effective_qty;
            *self.cost_basis.entry(symbol.to_string()).or_insert(Decimal::zero()) += cost;
        } else if side.eq_ignore_ascii_case("SELL") {
            let pos = self.positions.get(symbol).copied().unwrap_or(Decimal::zero());
            if pos <= Decimal::zero() {
                return OrderResult {
                    order_id: format!("paper_{}", self.order_counter),
                    symbol: symbol.to_string(),
                    side: side.to_string(),
                    quantity: effective_qty,
                    price: fill_price,
                    status: "rejected".into(),
                    timestamp: now,
                    raw: [("error".into(), Value::String("no position".into()))]
                        .into_iter()
                        .collect(),
                };
            }
            effective_qty = effective_qty.min(pos);
            fill_pct = effective_qty / if quantity.is_zero() { Decimal::ONE } else { quantity };
            self.cash += fill_price * effective_qty;
            *self.positions.get_mut(symbol).unwrap() -= effective_qty;
            if self.positions[symbol] <= Decimal::zero() {
                self.positions.remove(symbol);
                self.cost_basis.remove(symbol);
            }
        }

        let order_id = format!("paper_{}", self.order_counter);
        self.order_counter += 1;

        let cash_after = round_d2(self.cash);
        let qty_rounded = round_d8(effective_qty);
        let price_rounded = round_d2(fill_price);
        let cost_rounded = round_d2(cost);

        let fill: Value = serde_json::json!({
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": qty_rounded,
            "price": price_rounded,
            "cost": cost_rounded,
            "cash_after": cash_after,
            "fill_pct": fill_pct,
            "timestamp": now,
        });
        self.fills.push(fill.clone());

        OrderResult {
            order_id,
            symbol: symbol.to_string(),
            side: side.to_string(),
            quantity: qty_rounded,
            price: price_rounded,
            status: "filled".into(),
            timestamp: now,
            raw: fill.as_object().unwrap().clone().into_iter().collect(),
        }
    }

    pub fn get_balance(&self) -> Balance {
        let mut portfolio_value = self.cash;
        for (sym, qty) in &self.positions {
            let price = self.prices.get(sym).copied().unwrap_or(Decimal::zero());
            portfolio_value += price * qty;
        }
        Balance {
            cash: round_d2(self.cash),
            total_value: round_d2(portfolio_value),
            positions: self
                .positions
                .iter()
                .map(|(k, v)| (k.clone(), round_d8(*v)))
                .collect(),
        }
    }

    pub fn reset(&mut self, initial_cash: Decimal) {
        self.cash = initial_cash;
        self.positions.clear();
        self.cost_basis.clear();
        self.fills.clear();
        self.bars.clear();
        self.prices.clear();
        self.order_counter = 1;
    }

    pub fn discover_symbols(&self) -> Vec<String> {
        if self.bars.is_empty() {
            self.prices.keys().cloned().collect()
        } else {
            self.bars.keys().cloned().collect()
        }
    }

    pub fn to_state(&self) -> Value {
        serde_json::json!({
            "cash": self.cash,
            "positions": self.positions,
            "cost_basis": self.cost_basis,
            "fills": self.fills,
            "prices": self.prices,
            "order_counter": self.order_counter,
            "slippage_pct": self.slippage_pct,
            "partial_fill_prob": self.partial_fill_prob,
            "partial_fill_ratio": self.partial_fill_ratio,
        })
    }

    pub fn from_state(state: &Value, config: Option<&Value>) -> Self {
        let mut ex = Self::new(config);
        if let Some(c) = state.get("cash").and_then(|v| v.as_f64()) {
            ex.cash = Decimal::try_from(c).unwrap_or(Decimal::new(100_000, 0));
        }
        if let Some(pos) = state.get("positions").and_then(|v| v.as_object()) {
            ex.positions = pos
                .iter()
                .filter_map(|(k, v)| {
                    v.as_f64().map(|f| (k.clone(), Decimal::try_from(f).unwrap_or_default()))
                })
                .collect();
        }
        if let Some(cb) = state.get("cost_basis").and_then(|v| v.as_object()) {
            ex.cost_basis = cb
                .iter()
                .filter_map(|(k, v)| {
                    v.as_f64().map(|f| (k.clone(), Decimal::try_from(f).unwrap_or_default()))
                })
                .collect();
        }
        if let Some(fills) = state.get("fills").and_then(|v| v.as_array()) {
            ex.fills = fills.clone();
        }
        if let Some(prices) = state.get("prices").and_then(|v| v.as_object()) {
            ex.prices = prices
                .iter()
                .filter_map(|(k, v)| {
                    v.as_f64().map(|f| (k.clone(), Decimal::try_from(f).unwrap_or_default()))
                })
                .collect();
        }
        if let Some(oc) = state.get("order_counter").and_then(|v| v.as_u64()) {
            ex.order_counter = oc;
        }
        if let Some(sp) = state.get("slippage_pct").and_then(|v| v.as_f64()) {
            ex.slippage_pct = Decimal::try_from(sp).unwrap_or_default();
        }
        if let Some(pf) = state.get("partial_fill_prob").and_then(|v| v.as_f64()) {
            ex.partial_fill_prob = Decimal::try_from(pf).unwrap_or_default();
        }
        if let Some(fr) = state.get("partial_fill_ratio").and_then(|v| v.as_f64()) {
            ex.partial_fill_ratio = Decimal::try_from(fr).unwrap_or(Decimal::new(7, 1));
        }
        ex
    }
}

pub fn set_slippage(ex: &mut PaperExchange, pct: Decimal) {
    ex.slippage_pct = pct;
}

pub fn set_partial_fill(ex: &mut PaperExchange, prob: Decimal, ratio: Option<Decimal>) {
    ex.partial_fill_prob = prob;
    if let Some(r) = ratio {
        ex.partial_fill_ratio = r;
    }
}

fn round_d2(d: Decimal) -> Decimal {
    d.round_dp(2)
}

fn round_d8(d: Decimal) -> Decimal {
    d.round_dp(8)
}
