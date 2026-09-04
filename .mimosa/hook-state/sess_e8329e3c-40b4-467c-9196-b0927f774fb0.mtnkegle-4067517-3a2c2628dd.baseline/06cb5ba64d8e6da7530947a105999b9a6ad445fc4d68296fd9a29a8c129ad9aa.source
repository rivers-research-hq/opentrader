use std::collections::HashMap;
use std::io::{self, BufRead, Write};
use rust_decimal::Decimal;
use exchange_engine::exchange::PaperExchange;
use exchange_engine::protocol::{Request, Response};
use exchange_engine::risk::RiskManager;

fn main() {
    let mut exchange = PaperExchange::new(None);
    let mut risk = RiskManager::new(None);

    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let line = line.trim().to_string();
        if line.is_empty() {
            continue;
        }

        let req: Request = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(e) => {
                let resp = Response::error(&format!("parse error: {e}"));
                let _ = writeln!(out, "{}", serde_json::to_string(&resp).unwrap());
                let _ = out.flush();
                continue;
            }
        };

        let resp = handle_request(&req, &mut exchange, &mut risk);
        let _ = writeln!(out, "{}", serde_json::to_string(&resp).unwrap());
        let _ = out.flush();

        if matches!(req, Request::Shutdown {}) {
            break;
        }
    }
}

fn handle_request(
    req: &Request,
    ex: &mut PaperExchange,
    risk: &mut RiskManager,
) -> Response {
    match req {
        // ── Exchange ──
        Request::Connect {} => {
            ex.prices.get(""); // no-op; paper always connected
            Response::success(serde_json::json!(true))
        }
        Request::LoadBars { symbol, bars } => {
            ex.load_bars(symbol, bars);
            Response::success_null()
        }
        Request::PushBar { symbol, bar } => {
            ex.push_bar(symbol, bar);
            Response::success_null()
        }
        Request::GetBars { symbol, limit } => {
            let bars = ex.get_bars(symbol, limit.unwrap_or(100));
            Response::success(serde_json::to_value(bars).unwrap_or_default())
        }
        Request::GetCurrentPrice { symbol } => {
            let price = ex.get_current_price(symbol);
            Response::success(serde_json::to_value(price).unwrap_or_default())
        }
        Request::PlaceOrder { symbol, side, quantity, price } => {
            let qty = Decimal::try_from(*quantity).unwrap_or_default();
            let prc = price.map(|p| Decimal::try_from(p).unwrap_or_default());
            let result = ex.place_order(symbol, side, qty, prc);
            Response::success(serde_json::to_value(result).unwrap_or_default())
        }
        Request::GetBalance {} => {
            let balance = ex.get_balance();
            Response::success(serde_json::to_value(balance).unwrap_or_default())
        }
        Request::Reset { initial_cash } => {
            let cash = initial_cash.map(|c| Decimal::try_from(c).unwrap_or(Decimal::new(100_000, 0)))
                .unwrap_or(Decimal::new(100_000, 0));
            ex.reset(cash);
            Response::success_null()
        }
        Request::DiscoverSymbols {} => {
            let syms = ex.discover_symbols();
            Response::success(serde_json::to_value(syms).unwrap_or_default())
        }
        Request::GetState {} => {
            let state = ex.to_state();
            Response::success(state)
        }
        Request::LoadState { state, config } => {
            *ex = PaperExchange::from_state(state, config.as_ref());
            Response::success_null()
        }
        Request::SetSlippage { pct } => {
            let d = Decimal::try_from(*pct).unwrap_or_default();
            exchange_engine::exchange::set_slippage(ex, d);
            Response::success_null()
        }
        Request::SetPartialFill { prob, ratio } => {
            let p = Decimal::try_from(*prob).unwrap_or_default();
            let r = ratio.map(|r| Decimal::try_from(r).unwrap_or_default());
            exchange_engine::exchange::set_partial_fill(ex, p, r);
            Response::success_null()
        }
        Request::GetFills {} => {
            Response::success(serde_json::to_value(&ex.fills).unwrap_or_default())
        }

        // ── Risk ──
        Request::RiskCheck {
            signal,
            portfolio_total_value,
            portfolio_cash,
            prices,
            current_positions,
        } => {
            let tv = Decimal::try_from(*portfolio_total_value).unwrap_or_default();
            let cash = Decimal::try_from(*portfolio_cash).unwrap_or_default();
            let price_map: HashMap<String, Decimal> = prices
                .iter()
                .map(|(k, v)| (k.clone(), Decimal::try_from(*v).unwrap_or_default()))
                .collect();
            let pos_map = current_positions.as_ref().map(|p| {
                p.iter()
                    .map(|(k, v)| (k.clone(), Decimal::try_from(*v).unwrap_or_default()))
                    .collect::<HashMap<String, Decimal>>()
            });

            let result = risk.check(signal, tv, cash, &price_map, pos_map.as_ref());
            Response::success(serde_json::to_value(result).unwrap_or_default())
        }
        Request::RiskPreTradeCheck {
            signal,
            portfolio_total_value,
            portfolio_cash,
            prices,
            current_positions,
            price_history,
        } => {
            let tv = Decimal::try_from(*portfolio_total_value).unwrap_or_default();
            let cash = Decimal::try_from(*portfolio_cash).unwrap_or_default();
            let price_map: HashMap<String, Decimal> = prices
                .iter()
                .map(|(k, v)| (k.clone(), Decimal::try_from(*v).unwrap_or_default()))
                .collect();
            let pos_map = current_positions.as_ref().map(|p| {
                p.iter()
                    .map(|(k, v)| (k.clone(), Decimal::try_from(*v).unwrap_or_default()))
                    .collect::<HashMap<String, Decimal>>()
            });
            let hist_map = price_history.as_ref().map(|h| {
                h.iter()
                    .map(|(k, v)| {
                        (
                            k.clone(),
                            v.iter()
                                .map(|f| Decimal::try_from(*f).unwrap_or_default())
                                .collect::<Vec<Decimal>>(),
                        )
                    })
                    .collect::<HashMap<String, Vec<Decimal>>>()
            });

            let (approved, reason) = risk.pre_trade_check(
                signal,
                tv,
                cash,
                &price_map,
                pos_map.as_ref(),
                hist_map.as_ref(),
            );
            Response::success(serde_json::json!({"approved": approved, "reason": reason}))
        }
        Request::RiskSetInitial { cash } => {
            let c = Decimal::try_from(*cash).unwrap_or_default();
            risk.set_initial(c);
            Response::success_null()
        }
        Request::RiskUpdatePeak { portfolio_value } => {
            let pv = Decimal::try_from(*portfolio_value).unwrap_or_default();
            risk.update_peak(pv);
            Response::success_null()
        }
        Request::RiskCheckCircuitBreaker { portfolio_value } => {
            let pv = Decimal::try_from(*portfolio_value).unwrap_or_default();
            let ok = risk.check_circuit_breaker(pv);
            Response::success(serde_json::json!(ok))
        }
        Request::RiskKelly { win_prob, win_loss_ratio } => {
            let wp = win_prob.map(|p| Decimal::try_from(p).unwrap_or_default());
            let wlr = win_loss_ratio.map(|r| Decimal::try_from(r).unwrap_or_default());
            let kelly = risk.kelly_criterion(wp, wlr);
            Response::success(serde_json::to_value(kelly).unwrap_or_default())
        }
        Request::RiskVar { portfolio_value, confidence } => {
            let pv = Decimal::try_from(*portfolio_value).unwrap_or_default();
            let conf = confidence.map(|c| Decimal::try_from(c).unwrap_or_default());
            let var = risk.var_calculation(pv, conf);
            Response::success(serde_json::to_value(var).unwrap_or_default())
        }
        Request::RiskGetConfig {} => {
            Response::success(serde_json::to_value(&risk.config).unwrap_or_default())
        }
        Request::RiskSetConfig { config } => {
            risk.config = config.clone();
            Response::success_null()
        }
        Request::RiskCheckCorrelation {
            new_symbol,
            existing_positions,
            price_history,
        } => {
            let ep: HashMap<String, Decimal> = existing_positions
                .iter()
                .map(|(k, v)| (k.clone(), Decimal::try_from(*v).unwrap_or_default()))
                .collect();
            let ph: HashMap<String, Vec<Decimal>> = price_history
                .iter()
                .map(|(k, v)| {
                    (
                        k.clone(),
                        v.iter()
                            .map(|f| Decimal::try_from(*f).unwrap_or_default())
                            .collect(),
                    )
                })
                .collect();
            let corr = risk.check_correlation(new_symbol, &ep, &ph);
            Response::success(serde_json::to_value(corr).unwrap_or_default())
        }

        // ── Health ──
        Request::Ping {} => Response::success(serde_json::json!("pong")),
        Request::Shutdown {} => Response::success(serde_json::json!("bye")),
    }
}
