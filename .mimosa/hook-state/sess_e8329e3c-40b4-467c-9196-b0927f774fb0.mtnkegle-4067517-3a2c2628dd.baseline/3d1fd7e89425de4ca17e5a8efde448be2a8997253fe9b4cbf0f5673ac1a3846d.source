use rust_decimal::Decimal;
use rust_decimal::prelude::Zero;
use std::collections::HashMap;
use crate::types::{RiskConfig, RiskResult, Signal};
use rust_decimal::prelude::ToPrimitive;

pub struct RiskManager {
    pub config: RiskConfig,
    peak_value: Decimal,
    initial_cash: Decimal,
    daily_trades: u32,
    last_reset_date: String,
    seen_trade_keys: std::collections::HashSet<String>,
}

impl RiskManager {
    pub fn new(config: Option<RiskConfig>) -> Self {
        Self {
            config: config.unwrap_or_default(),
            peak_value: Decimal::zero(),
            initial_cash: Decimal::zero(),
            daily_trades: 0,
            last_reset_date: String::new(),
            seen_trade_keys: std::collections::HashSet::new(),
        }
    }

    pub fn set_initial(&mut self, cash: Decimal) {
        self.initial_cash = cash;
        self.peak_value = cash;
    }

    pub fn update_peak(&mut self, portfolio_value: Decimal) {
        if portfolio_value > self.peak_value {
            self.peak_value = portfolio_value;
        }
    }

    pub fn check_circuit_breaker(&self, portfolio_value: Decimal) -> bool {
        if self.peak_value <= Decimal::zero() {
            return true;
        }
        let drawdown = (self.peak_value - portfolio_value) / self.peak_value;
        let ok = drawdown < self.config.portfolio_stop_pct;
        if !ok {
            eprintln!(
                "Circuit breaker tripped: drawdown {:.2}% exceeds {:.0}%",
                drawdown * Decimal::from(100),
                self.config.portfolio_stop_pct * Decimal::from(100)
            );
        }
        ok
    }

    pub fn circuit_breaker_price(prices: &[Decimal]) -> bool {
        if prices.len() < 5 {
            return false;
        }
        let first = prices[0];
        let last = prices[prices.len() - 1];
        if first.is_zero() {
            return false;
        }
        (first - last) / first > Decimal::new(5, 2) // 0.05
    }

    pub fn kelly_criterion(&self, win_prob: Option<Decimal>, win_loss_ratio: Option<Decimal>) -> Decimal {
        let p = win_prob.unwrap_or(self.config.default_win_prob);
        let b = win_loss_ratio.unwrap_or(self.config.default_wl_ratio);

        if b <= Decimal::zero() {
            return Decimal::zero();
        }
        let kelly = (p * b - (Decimal::ONE - p)) / b;
        let kelly = kelly.max(Decimal::zero());
        (kelly * self.config.kelly_fraction).round_dp(6)
    }

    pub fn check_correlation(
        &self,
        new_symbol: &str,
        existing_positions: &HashMap<String, Decimal>,
        price_history: &HashMap<String, Vec<Decimal>>,
    ) -> Decimal {
        let new_prices = match price_history.get(new_symbol) {
            Some(p) => p,
            None => return Decimal::zero(),
        };
        if new_prices.len() < 2 {
            return Decimal::zero();
        }

        let mut max_corr = Decimal::zero();
        for symbol in existing_positions.keys() {
            if symbol == new_symbol {
                continue;
            }
            let existing_prices = match price_history.get(symbol) {
                Some(p) => p,
                None => continue,
            };
            if existing_prices.len() < 2 {
                continue;
            }

            let n = new_prices.len().min(existing_prices.len());
            let x = &new_prices[new_prices.len() - n..];
            let y = &existing_prices[existing_prices.len() - n..];

            let mx = x.iter().sum::<Decimal>() / Decimal::from(n as u64);
            let my = y.iter().sum::<Decimal>() / Decimal::from(n as u64);

            let cov: Decimal = x.iter().zip(y.iter())
                .map(|(xi, yi)| (*xi - mx) * (*yi - my))
                .sum::<Decimal>() / Decimal::from(n as u64);

            let var_x = x.iter()
                .map(|xi| (*xi - mx) * (*xi - mx))
                .sum::<Decimal>() / Decimal::from(n as u64);
            let var_y = y.iter()
                .map(|yi| (*yi - my) * (*yi - my))
                .sum::<Decimal>() / Decimal::from(n as u64);

            let sx = Decimal::try_from(var_x.to_f64().unwrap_or(0.0).sqrt()).unwrap_or_default();
            let sy = Decimal::try_from(var_y.to_f64().unwrap_or(0.0).sqrt()).unwrap_or_default();

            if sx.is_zero() || sy.is_zero() {
                continue;
            }
            let corr = (cov / (sx * sy)).abs();
            if corr > max_corr {
                max_corr = corr;
            }
        }
        max_corr
    }

    pub fn var_calculation(&self, portfolio_value: Decimal, confidence: Option<Decimal>) -> Decimal {
        let z_scores: HashMap<&str, Decimal> = [
            ("0.99", Decimal::new(2326, 3)),  // 2.326
            ("0.95", Decimal::new(1645, 3)),  // 1.645
            ("0.90", Decimal::new(1282, 3)),  // 1.282
        ].into_iter().collect();

        let conf = confidence.unwrap_or(self.config.var_confidence);
        let z = z_scores
            .get(&conf.to_string().as_str())
            .copied()
            .unwrap_or(Decimal::new(1645, 3));

        let daily_vol = self.config.daily_vol_assumption;
        let sqrt_window = Decimal::try_from((self.config.var_window_days as f64).sqrt())
            .unwrap_or(Decimal::from(5));
        portfolio_value * daily_vol * sqrt_window * z
    }

    pub fn check(
        &mut self,
        signal: &Signal,
        portfolio_total_value: Decimal,
        portfolio_cash: Decimal,
        prices: &HashMap<String, Decimal>,
        current_positions: Option<&HashMap<String, Decimal>>,
    ) -> RiskResult {
        self.reset_daily();

        if signal.action.eq_ignore_ascii_case("HOLD") {
            return RiskResult {
                approved: true,
                reason: "HOLD".into(),
                adjusted_size: Decimal::zero(),
                adjusted_stop: None,
                adjusted_tp: None,
            };
        }

        let price = prices.get(&signal.symbol).copied().unwrap_or(Decimal::zero());
        if price <= Decimal::zero() {
            return RiskResult {
                approved: false,
                reason: format!("no price for {}", signal.symbol),
                adjusted_size: Decimal::zero(),
                adjusted_stop: None,
                adjusted_tp: None,
            };
        }

        if self.daily_trades >= self.config.max_daily_trades {
            return RiskResult {
                approved: false,
                reason: format!(
                    "daily trade limit ({}) reached",
                    self.config.max_daily_trades
                ),
                adjusted_size: Decimal::zero(),
                adjusted_stop: None,
                adjusted_tp: None,
            };
        }

        let mut size_pct = if signal.position_pct > Decimal::zero() {
            signal.position_pct
        } else {
            Decimal::new(5, 2)
        };
        size_pct = size_pct.min(self.config.max_position_pct);

        let mut proposed_value = portfolio_total_value * size_pct;
        if proposed_value > self.config.max_order_value {
            size_pct = self.config.max_order_value / portfolio_total_value.max(Decimal::ONE);
            proposed_value = portfolio_total_value * size_pct;
        }

        if signal.action.eq_ignore_ascii_case("BUY") {
            if proposed_value > portfolio_cash - self.config.min_cash_reserve {
                let available = portfolio_cash - self.config.min_cash_reserve;
                if available <= Decimal::zero() {
                    return RiskResult {
                        approved: false,
                        reason: "insufficient cash".into(),
                        adjusted_size: Decimal::zero(),
                        adjusted_stop: None,
                        adjusted_tp: None,
                    };
                }
                size_pct = available / portfolio_total_value;
            }

            let existing = match current_positions {
                Some(pos) => pos.values().filter(|q| **q > Decimal::zero()).count(),
                None => 0,
            } as u32;
            if existing >= self.config.max_positions {
                return RiskResult {
                    approved: false,
                    reason: format!(
                        "max positions ({}) reached",
                        self.config.max_positions
                    ),
                    adjusted_size: Decimal::zero(),
                    adjusted_stop: None,
                    adjusted_tp: None,
                };
            }

            let kelly = self.kelly_criterion(None, None);
            if size_pct > kelly {
                size_pct = kelly;
            }
        } else if signal.action.eq_ignore_ascii_case("SELL") {
            let pos_qty = match current_positions {
                Some(pos) => pos.get(&signal.symbol).copied().unwrap_or(Decimal::zero()),
                None => Decimal::zero(),
            };
            if pos_qty <= Decimal::zero() {
                return RiskResult {
                    approved: false,
                    reason: format!("no position in {}", signal.symbol),
                    adjusted_size: Decimal::zero(),
                    adjusted_stop: None,
                    adjusted_tp: None,
                };
            }
        }

        let stop_loss = match signal.stop_loss {
            Some(sl) if sl > Decimal::zero() => Some(sl),
            _ => {
                if signal.action.eq_ignore_ascii_case("BUY") {
                    Some(price * (Decimal::ONE - self.config.stop_loss_pct))
                } else {
                    Some(price * (Decimal::ONE + self.config.stop_loss_pct))
                }
            }
        };

        let take_profit = match signal.take_profit {
            Some(tp) if tp > Decimal::zero() => Some(tp),
            _ => {
                if signal.action.eq_ignore_ascii_case("BUY") {
                    Some(price * (Decimal::ONE + self.config.take_profit_pct))
                } else {
                    Some(price * (Decimal::ONE - self.config.take_profit_pct))
                }
            }
        };

        let trade_key = format!(
            "{}:{}:{:.4}",
            signal.symbol, signal.action, signal.position_pct
        );
        if !self.seen_trade_keys.contains(&trade_key) {
            self.seen_trade_keys.insert(trade_key);
            self.daily_trades += 1;
        }

        RiskResult {
            approved: true,
            reason: "ok".into(),
            adjusted_size: size_pct.round_dp(4),
            adjusted_stop: stop_loss.map(|s| s.round_dp(2)),
            adjusted_tp: take_profit.map(|s| s.round_dp(2)),
        }
    }

    pub fn pre_trade_check(
        &mut self,
        signal: &Signal,
        portfolio_total_value: Decimal,
        portfolio_cash: Decimal,
        prices: &HashMap<String, Decimal>,
        current_positions: Option<&HashMap<String, Decimal>>,
        price_history: Option<&HashMap<String, Vec<Decimal>>>,
    ) -> (bool, String) {
        if !self.check_circuit_breaker(portfolio_total_value) {
            return (false, "CIRCUIT BREAKER: drawdown exceeded".into());
        }

        let result = self.check(signal, portfolio_total_value, portfolio_cash, prices, current_positions);
        if !result.approved {
            return (false, result.reason);
        }

        if let (Some(history), Some(positions)) = (price_history, current_positions) {
            let corr = self.check_correlation(&signal.symbol, positions, history);
            if corr > self.config.max_correlation {
                return (
                    false,
                    format!(
                        "Correlation {:.2} > {:.2}",
                        corr, self.config.max_correlation
                    ),
                );
            }
        }

        (true, "approved".into())
    }

    fn reset_daily(&mut self) {
        let today = chrono::Utc::now().format("%Y-%m-%d").to_string();
        if today != self.last_reset_date {
            self.daily_trades = 0;
            self.last_reset_date = today;
            self.seen_trade_keys.clear();
        }
    }
}
