//! Opentrader V2 terminal — alpha (SIM feed; venue streams land with the
//! W1 tails). Run: cargo run -p ot-terminal
fn main() -> eframe::Result<()> {
    let opts = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_inner_size([1280.0, 800.0])
            .with_title("Opentrader V2 — terminal alpha (SIM)"),
        ..Default::default()
    };
    eframe::run_native(
        "Opentrader V2",
        opts,
        Box::new(|_cc| Ok(Box::new(ot_terminal::app::TerminalApp::new()))),
    )
}
