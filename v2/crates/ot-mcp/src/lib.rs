//! ot-mcp — the MCP tool surface. W0: the seam shapes the tools; the
//! protocol implementation is W1+ (behind the same seam as the egui
//! terminal — the human's locked ToC #352 decision).

/// The tool surface the MCP server exposes. Every tool resolves behind
/// `ot_venues::VenueAdapter` — no tool ever talks to a broker cache.
pub mod tools {
    /// Catalog of MCP tools (name → seam call). Implemented in W1+.
    pub const TOOLS: &[(&str, &str)] = &[
        ("account", "adapter.account()"),
        ("quote", "adapter.quote(sym)"),
        ("place_order", "adapter.place_order(req)"),
        ("cancel_order", "adapter.cancel_order(id)"),
        ("positions", "adapter.positions()"),
        ("history", "adapter.history(sym, from, to, gran)"),
    ];
}
