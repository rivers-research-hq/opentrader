//! The egui terminal — alpha UI over the view-model (`model.rs`).
//! Layout: chart panel (candles + study overlay + volume), watchlist
//! sidebar, account/positions strip with market-order buttons.

use crate::model::{BarsStore, PaperBroker, PaperSide, SimFeed, StudyOverlay};
use eframe::egui;
use egui_plot::{BoxElem, BoxPlot, BoxSpread, Legend, Line, Plot, PlotPoints};

pub struct TerminalApp {
    pub store: BarsStore,
    pub feeds: Vec<SimFeed>,
    pub broker: PaperBroker,
    pub selected: usize,
    pub study: Option<StudyOverlay>,
    pub study_source: String,
    pub study_error: Option<String>,
    pub qty_input: f64,
    pub sim_running: bool,
}

pub const SYMBOLS: [&str; 6] = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "SIM_SPX"];

impl TerminalApp {
    pub fn new() -> Self {
        let mut feeds: Vec<SimFeed> = Vec::new();
        let mut store = BarsStore::default();
        let starts = [1.085, 1.265, 155.0, 0.655, 1.365, 520.0];
        for (i, sym) in SYMBOLS.iter().enumerate() {
            let mut feed = SimFeed::new(sym, 0xBEEF + i as u64 * 77, starts[i]);
            // pre-warm 120 bars per symbol
            for _ in 0..120 {
                let bar = feed.advance();
                store.append(sym, bar);
            }
            feeds.push(feed);
        }
        let broker = PaperBroker::new(100_000.0, 0.35);
        let selected = 0;
        let study_source = "def fast = Average(close, 9);\ndef slow = Average(close, 20);\nplot sig = fast - slow;".to_string();
        let study = StudyOverlay::compile(&study_source).ok();
        TerminalApp {
            store,
            feeds,
            broker,
            selected,
            study,
            study_source,
            study_error: None,
            qty_input: 10.0,
            sim_running: true,
        }
    }

    /// Advance the SIM feed one bar for every symbol; fills pendings.
    pub fn tick(&mut self) {
        for f in &mut self.feeds {
            let bar = f.advance();
            let sym = f.symbol.clone();
            self.broker.on_bar(&sym, &bar);
            self.store.append(&sym, bar);
        }
    }

    pub fn selected_symbol(&self) -> &'static str {
        SYMBOLS[self.selected]
    }
}

impl Default for TerminalApp {
    fn default() -> Self {
        Self::new()
    }
}

impl eframe::App for TerminalApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        if self.sim_running {
            self.tick();
        }

        egui::TopBottomPanel::top("top").show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.heading("Opentrader V2 — terminal alpha");
                ui.separator();
                ui.label(egui::RichText::new("SIM FEED").color(egui::Color32::ORANGE));
                ui.toggle_value(&mut self.sim_running, "▶ / ⏸");
                if ui.button("step ▸").clicked() {
                    self.tick();
                }
                ui.separator();
                let eq = self.broker.equity(|s| self.store.last_close(s));
                ui.label(format!("equity (marked): ${eq:.2}"));
            });
        });

        egui::SidePanel::right("watchlist").show(ctx, |ui| {
            ui.heading("Watchlist");
            for (i, sym) in SYMBOLS.iter().enumerate() {
                let last = self.store.last_close(sym).unwrap_or(0.0);
                ui.selectable_value(&mut self.selected, i, format!("{sym}  {last:.5}"));
            }
            ui.separator();
            ui.heading("Study (v2script)");
            let resp = ui.add(
                egui::TextEdit::multiline(&mut self.study_source)
                    .desired_width(240.0)
                    .font(egui::TextStyle::Monospace),
            );
            if resp.changed() || ui.button("compile").clicked() {
                match StudyOverlay::compile(&self.study_source) {
                    Ok(s) => {
                        self.study = Some(s);
                        self.study_error = None;
                    }
                    Err(e) => {
                        self.study_error = Some(e);
                    }
                }
            }
            if let Some(err) = &self.study_error {
                ui.colored_label(egui::Color32::RED, err);
            }
        });

        egui::TopBottomPanel::bottom("account").show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.heading("Account");
                ui.label(format!("cash ${:.2}", self.broker.cash));
                ui.separator();
                let sym = self.selected_symbol();
                ui.label(format!("market order on {sym}:"));
                ui.add(egui::DragValue::new(&mut self.qty_input).speed(1.0));
                if ui.button("BUY").clicked() {
                    self.broker.market(sym, PaperSide::Long, self.qty_input);
                }
                if ui.button("SELL").clicked() {
                    self.broker.market(sym, PaperSide::Short, self.qty_input);
                }
            });
            ui.separator();
            let marks: Vec<(String, Option<f64>)> = SYMBOLS
                .iter()
                .map(|s| (s.to_string(), self.store.last_close(s)))
                .collect();
            let mark = |s: &str| marks.iter().find(|(k, _)| k == s).and_then(|(_, v)| *v);
            let mut close_idx: Option<usize> = None;
            ui.horizontal(|ui| {
                for (i, p) in self.broker.positions().iter().enumerate() {
                    let m = mark(&p.symbol).unwrap_or(p.entry);
                    let upnl = match p.side {
                        PaperSide::Long => p.qty * (m - p.entry),
                        PaperSide::Short => p.qty * (p.entry - m),
                    };
                    ui.label(format!(
                        "{} {:?} qty={} @ {:.5} uPnL {upnl:.2}",
                        p.symbol, p.side, p.qty, p.entry
                    ));
                    if ui.button("✕").clicked() {
                        close_idx = Some(i);
                    }
                }
            });
            if let Some(i) = close_idx {
                if let Some(m) = mark(self.broker.positions()[i].symbol.as_str()) {
                    self.broker.close(i, m);
                }
            }
        });

        egui::CentralPanel::default().show(ctx, |ui| {
            let sym = self.selected_symbol();
            let Some(frame) = self.store.frame(sym).map(|f| f.to_vec()) else {
                return;
            };
            // candlesticks: BoxElem spreads map OHLC → (whisker low, q1=open,
            // median, q3=close, whisker high)
            let mut candles_up = Vec::new();
            let mut candles_dn = Vec::new();
            for (i, b) in frame.iter().enumerate() {
                let elem = BoxElem {
                    name: format!("{sym}@{}", b.ts),
                    orientation: egui_plot::Orientation::Vertical,
                    argument: i as f64,
                    spread: BoxSpread::new(b.low, b.open.min(b.close), (b.open + b.close) / 2.0, b.open.max(b.close), b.high),
                    box_width: 0.6,
                    whisker_width: 0.25,
                    stroke: egui::Stroke::new(1.0_f32, egui::Color32::GRAY),
                    fill: if b.close >= b.open {
                        egui::Color32::from_rgb(38, 166, 91)
                    } else {
                        egui::Color32::from_rgb(217, 74, 74)
                    },
                };
                if b.close >= b.open {
                    candles_up.push(elem);
                } else {
                    candles_dn.push(elem);
                }
            }
            let plot = Plot::new("chart")
                .legend(Legend::default())
                .allow_drag(true)
                .x_axis_label("bar")
                .y_axis_label("price");
            plot.show(ui, |ui| {
                if !candles_up.is_empty() {
                    ui.box_plot(BoxPlot::new("up".to_string(), candles_up));
                }
                if !candles_dn.is_empty() {
                    ui.box_plot(BoxPlot::new("down".to_string(), candles_dn));
                }
                if let Some(study) = &self.study {
                    if let Ok(values) = study.evaluate(&frame, sym) {
                        let line: Vec<[f64; 2]> = values
                            .iter()
                            .enumerate()
                            .filter(|(_, v)| !v.is_nan())
                            .map(|(i, v)| [i as f64, *v])
                            .collect();
                        if !line.is_empty() {
                            ui.line(Line::new("study".to_string(), PlotPoints::from(line)));
                        }
                    }
                }
            });
            // volume pane
            let vol_line: Vec<[f64; 2]> = frame
                .iter()
                .enumerate()
                .map(|(i, b)| [i as f64, b.volume])
                .collect();
            Plot::new("volume")
                .height(80.0)
                .show(ui, |ui| {
                    ui.line(
                        Line::new("volume".to_string(), PlotPoints::from(vol_line))
                            .color(egui::Color32::from_rgb(80, 120, 200)),
                    );
                });
        });

        // keep ticking while running (alpha cadence: ~2 fps)
        if self.sim_running {
            ctx.request_repaint_after(std::time::Duration::from_millis(500));
        }
    }
}
