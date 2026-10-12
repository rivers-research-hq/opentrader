//! The egui terminal — alpha UI over the view-model (`model.rs`).
//! Layout: chart panel (candles + study overlay + volume), watchlist
//! sidebar, account/positions strip with market-order buttons.

use crate::model::{BarsStore, PaperBroker, PaperSide, ScanTab, SimFeed, StudyOverlay};
use eframe::egui;
use egui_plot::{BoxElem, BoxPlot, BoxSpread, Legend, Line, Plot, PlotPoints};

/// Terminal tabs (W4a, ticket #388): Chart is the alpha panel; Scan rides
/// ot-script::scan (the W2f engine — no second scanner path).
#[derive(PartialEq, Eq, Clone, Copy, Debug)]
pub enum Tab {
	Chart,
	Scan,
	Analyze,
}

struct AnalyzeOut {
    legs: Vec<ot_core::whatif::WhatifLeg>,
    curve: Vec<f64>,
    swept_sym: String,
    lo: f64,
    hi: f64,
}

struct AnalyzeState {
    positions: Vec<ot_core::whatif::WhatifPosition>,
    sweep_pct: f64,
    steps: usize,
    result: Option<AnalyzeOut>,
    error: Option<String>,
    add_sym: String,
    add_side: PaperSide,
    add_qty: f64,
    add_entry: Option<f64>,
    sweep_sym: String,
}

impl AnalyzeState {
    fn new() -> Self {
        Self {
            positions: Vec::new(),
            sweep_pct: 10.0,
            steps: 21,
            result: None,
            error: None,
            add_sym: SYMBOLS[0].to_string(),
            add_side: PaperSide::Long,
            add_qty: 10.0,
            add_entry: None,
            sweep_sym: SYMBOLS[0].to_string(),
        }
    }
}


pub struct TerminalApp {
    pub tab: Tab,
    pub scan_tab: ScanTab,
    pub store: BarsStore,
    pub feeds: Vec<SimFeed>,
    pub broker: PaperBroker,
    pub selected: usize,
    pub study: Option<StudyOverlay>,
    pub study_source: String,
    pub study_error: Option<String>,
    pub qty_input: f64,
    pub sim_running: bool,	pub analyze: AnalyzeState,
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
        let tab = Tab::Chart;
        let mut scan_tab = ScanTab::new();
        scan_tab.source = "def up = close > close[1];".to_string();
        scan_tab.filter = "up".to_string();
        let study_source = "def fast = Average(close, 9);\ndef slow = Average(close, 20);\nplot sig = fast - slow;".to_string();
        let study = StudyOverlay::compile(&study_source).ok();
        TerminalApp {
            tab,
            scan_tab,
            store,
            feeds,
            broker,
            selected,
            study,
            study_source,
            study_error: None,
            qty_input: 10.0,
            sim_running: true,
			analyze: AnalyzeState::new(),
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
                ui.separator();
                ui.selectable_value(&mut self.tab, Tab::Chart, "Chart");
                ui.selectable_value(&mut self.tab, Tab::Scan, "Scan");
				ui.selectable_value(&mut self.tab, Tab::Analyze, "Analyze");
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
            match self.tab {
                Tab::Chart => self.ui_chart(ui),
                Tab::Scan => self.ui_scan(ui),
				Tab::Analyze => self.ui_analyze(ui),
            }
        });

        // keep ticking while running (alpha cadence: ~2 fps)
        if self.sim_running {
            ctx.request_repaint_after(std::time::Duration::from_millis(500));
        }
    }

}

impl TerminalApp {
    /// The scan tab (W4a): editor + ranked results, riding ot-script::scan.
    fn ui_scan(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.heading("Scanner (v2script)");
            ui.separator();
            if ui.button("run scan").clicked() {
                let symbols: Vec<&str> = SYMBOLS.to_vec();
                self.scan_tab.run(&self.store, &symbols);
            }
        });
        ui.add(
            egui::TextEdit::multiline(&mut self.scan_tab.source)
                .code_editor()
                .desired_rows(6)
                .desired_width(f32::INFINITY),
        );
        ui.horizontal(|ui| {
            ui.label("filter binding:");
            ui.add(
                egui::TextEdit::singleline(&mut self.scan_tab.filter)
                    .hint_text("bool binding name")
                    .desired_width(120.0),
            );
            ui.label("sort binding:");
            ui.add(
                egui::TextEdit::singleline(&mut self.scan_tab.sort)
                    .hint_text("float binding (blank = symbol order)")
                    .desired_width(160.0),
            );
            ui.label("limit:");
            ui.add(
                egui::DragValue::new(&mut self.scan_tab.limit)
                    .range(1..=1000)
                    .speed(1),
            );
        });
        if let Some(err) = &self.scan_tab.error {
            ui.colored_label(egui::Color32::RED, err);
        }
        if let Some(result) = &self.scan_tab.result {
            ui.separator();
            egui::Grid::new("scan_results")
                .striped(true)
                .show(ui, |ui| {
                    ui.strong("Symbol");
                    ui.strong("Filter");
                    ui.strong("Sort");
                    ui.strong("Last close");
                    ui.end_row();
                    for hit in &result.hits {
                        ui.label(&hit.symbol);
                        ui.label(format!("{}", hit.filter));
                        ui.label(format!("{:.4}", hit.sort));
                        ui.label(format!("{:.5}", hit.last_close));
                        ui.end_row();
                    }
                });
            ui.label(format!(
                "scanned {} · ranked pool {} · skipped warmup {}",
                result.scanned, result.ranked_pool, result.skipped_warmup
            ));
            for (sym, err) in &result.errors {
                ui.colored_label(egui::Color32::RED, format!("{sym}: {err}"));
            }
        }
    }

    fn ui_chart(&mut self, ui: &mut egui::Ui) {
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

    }
}

impl TerminalApp {
    pub fn run_analyze(&mut self) -> () {
        let mut all_positions: Vec<ot_core::whatif::WhatifPosition> = self
            .broker
            .positions()
            .iter()
            .map(|p| {
                let side = match p.side {
                    PaperSide::Long => ot_core::engine::Side::Long,
                    PaperSide::Short => ot_core::engine::Side::Short,
                };
                ot_core::whatif::WhatifPosition {
                    sym: p.symbol.clone(),
                    side,
                    qty: p.qty,
                    entry: p.entry,
                    entry_fee: self.broker.fee_per_side,
                }
            })
            .chain(self.analyze.positions.clone())
            .collect();

        if all_positions.is_empty() {
            self.analyze.error = Some("add a position or place a paper trade first".into());
            self.analyze.result = None;
            return;
        }

        let swept_sym = self.analyze.sweep_sym.clone();
        let base_price = self
            .store
            .last_close(&swept_sym)
            .or_else(|| {
                all_positions
                    .iter()
                    .find(|p| p.sym == swept_sym)
                    .map(|p| p.entry)
            });

        let base_price = match base_price {
            Some(p) => p,
            None => {
                self.analyze.error = Some(format!("no data for symbol {}", swept_sym));
                self.analyze.result = None;
                return;
            }
        };

        let lo = base_price * (1.0 - self.analyze.sweep_pct / 100.0);
        let hi = base_price * (1.0 + self.analyze.sweep_pct / 100.0);
        let steps = self.analyze.steps.clamp(2, 201);
                           // Since PaperBroker has fee_per_side, and whatif_sweep takes fee_pct, 
                           // we need a reasonable default or derive it. 
                           // or just 0.0. The prompt says "fee_pct: f64" in signature. 
        
        let fee_pct = 0.0; // broker charges a flat per-side fee
        let legs = ot_core::whatif::whatif_sweep(
            &all_positions,
            &swept_sym,
            lo,
            hi,
            steps,
            fee_pct,
            self.broker.fee_per_side,
        );
        let curve = ot_core::whatif::portfolio_curve(
            &all_positions,
            &swept_sym,
            lo,
            hi,
            steps,
            fee_pct,
            self.broker.fee_per_side,
        );

        self.analyze.result = Some(AnalyzeOut {
            legs,
            curve,
            swept_sym,
            lo,
            hi,
        });
        self.analyze.error = None;
    }

    pub fn ui_analyze(&mut self, ui: &mut egui::Ui) {
        ui.heading("Analyze — what-if P&L");

        // Section 1: Broker Positions
        ui.collapsing("Broker Positions", |ui| {
            let positions = self.broker.positions();
            if positions.is_empty() {
                ui.label("No broker positions.");
            } else {
                for p in positions {
                    ui.label(format!(
                        "{} {:?} {} @ {:.2}",
                        p.symbol, p.side, p.qty, p.entry
                    ));
                }
            }
        });

        // Section 2: Add Hypothetical
        ui.collapsing("Add Hypothetical Position", |ui| {
            egui::Grid::new("add_pos_grid").num_columns(2).striped(true).show(ui, |ui| {
                ui.label("Symbol");
                egui::ComboBox::from_id_salt("add_sym_cb")
                    .selected_text(self.analyze.add_sym.clone())
                    .show_ui(ui, |ui| {
                        for sym in SYMBOLS {
                            ui.selectable_value(
                                &mut self.analyze.add_sym,
                                sym.to_string(),
                                sym,
                            );
                        }
                    });
                ui.end_row();

                ui.label("Side");
                ui.horizontal(|ui| {
                    ui.selectable_value(
                        &mut self.analyze.add_side,
                        PaperSide::Long,
                        "Long",
                    );
                    ui.selectable_value(
                        &mut self.analyze.add_side,
                        PaperSide::Short,
                        "Short",
                    );
                });
                ui.end_row();

                ui.label("Qty");
                ui.add(egui::DragValue::new(&mut self.analyze.add_qty).clamp_range(0.0..=1_000_000.0));
                ui.end_row();

                ui.label("Entry");
                let mut use_last_close = self.analyze.add_entry.is_none();
                ui.checkbox(&mut use_last_close, "Use Last Close");
                if use_last_close {
                    self.analyze.add_entry = None;
                } else {
                    if self.analyze.add_entry.is_none() {
                        self.analyze.add_entry = self.store.last_close(&self.analyze.add_sym);
                    }
                }
                ui.add_enabled_ui(!use_last_close, |ui| {
                    ui.add(egui::DragValue::new(
                        self.analyze.add_entry.get_or_insert(0.0),
                    ));
                });
                ui.end_row();

                ui.label("");
                ui.horizontal(|ui| {
                    if ui.button("Add").clicked() {
                        let entry = match self.analyze.add_entry {
                            Some(e) => e,
                            None => self.store.last_close(&self.analyze.add_sym).unwrap_or(0.0),
                        };
                        let side = match self.analyze.add_side {
                            PaperSide::Long => ot_core::engine::Side::Long,
                            PaperSide::Short => ot_core::engine::Side::Short,
                        };
                        self.analyze.positions.push(ot_core::whatif::WhatifPosition {
                            sym: self.analyze.add_sym.clone(),
                            side,
                            qty: self.analyze.add_qty,
                            entry,
                            entry_fee: 0.0,
                        });
                    }
                });
                ui.end_row();
            });

            // List added hypotheticals with remove
            if !self.analyze.positions.is_empty() {
                ui.separator();
                ui.label("Hypothetical Positions:");
                let to_remove: Vec<usize> = (0..self.analyze.positions.len())
                    .filter(|i| {
                        ui.horizontal(|ui| {
                            ui.label(format!(
                                "{} {} {} @ {:.2}",
                                self.analyze.positions[*i].sym,
                                if self.analyze.positions[*i].side == ot_core::engine::Side::Long {
                                    "Long"
                                } else {
                                    "Short"
                                },
                                self.analyze.positions[*i].qty,
                                self.analyze.positions[*i].entry
                            ));
                            ui.button("✕").clicked()
                        })
                        .inner
                    })
                    .collect();
                for i in to_remove.into_iter().rev() {
                    self.analyze.positions.remove(i);
                }
            }
        });

        // Section 3: Sweep Controls
        ui.collapsing("Sweep Controls", |ui| {
            egui::Grid::new("sweep_grid").num_columns(2).striped(true).show(ui, |ui| {
                ui.label("Symbol");
                egui::ComboBox::from_id_salt("sweep_sym_cb")
                    .selected_text(self.analyze.sweep_sym.clone())
                    .show_ui(ui, |ui| {
                        for sym in SYMBOLS {
                            ui.selectable_value(
                                &mut self.analyze.sweep_sym,
                                sym.to_string(),
                                sym,
                            );
                        }
                    });
                ui.end_row();

                ui.label("Sweep %");
                ui.add(egui::DragValue::new(&mut self.analyze.sweep_pct).clamp_range(0.0..=100.0));
                ui.end_row();

                ui.label("Steps");
                ui.add(egui::DragValue::new(&mut self.analyze.steps).clamp_range(2..=201));
                ui.end_row();

                ui.label("");
                ui.horizontal(|ui| {
                    if ui.button("Compute").clicked() {
                        self.run_analyze();
                    }
                });
                ui.end_row();
            });
        });

        // Section 4: Results
        if let Some(err) = &self.analyze.error {
            ui.label(egui::RichText::new(err).color(egui::Color32::RED));
        }

        if let Some(r) = &self.analyze.result {
            if !r.curve.is_empty() {
                ui.label("Portfolio Curve:");
                let plot = egui_plot::Plot::new("analyze_curve")
                    .width(ui.available_width())
                    .height(200.0);
                plot.show(ui, |plot_ui| {
                    let points: Vec<[f64; 2]> = r
                        .curve
                        .iter()
                        .enumerate()
                        .map(|(i, &v)| [i as f64, v])
                        .collect();
                    plot_ui.line(egui_plot::Line::new("analyze".to_string(), egui_plot::PlotPoints::from(points)));
                });
            }

            ui.label("Sweep Legs:");
            egui::Grid::new("legs_grid")
                .num_columns(3)
                .striped(true)
                .show(ui, |ui| {
                    ui.strong("Symbol");
                    ui.strong("Price");
                    ui.strong("P&L");
                    ui.end_row();
                    for leg in &r.legs {
                        ui.label(&leg.sym);
                        ui.label(format!("{:.2}", leg.price));
                        let color = if leg.pnl < 0.0 {
                            egui::Color32::RED
                        } else {
                            egui::Color32::GREEN
                        };
                        ui.label(
                            egui::RichText::new(format!("{:.2}", leg.pnl)).color(color),
                        );
                        ui.end_row();
                    }
                });
        }
    }
}
