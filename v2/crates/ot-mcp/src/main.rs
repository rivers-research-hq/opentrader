//! ot-mcp binary — the MCP server agents launch via their client config.
//!
//! Modes:
//!   (default)          serve MCP over stdio; auth required unless --no-auth
//!   --generate-key <customer> [--plan <plan>] [--max-calls <n>]
//!                      add a customer to the ledger; prints the key ONCE
//!                      (stdout); only the SHA-256 hash is stored
//!   --no-auth          local dev: skip auth (explicit flag, not default)
//!   --ledger <path>    override the ledger path (~/.ot-mcp/keys.json)

use ot_mcp::{auth, serve_lines, ServerState};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut ledger_path = auth::default_ledger_path();
    let mut no_auth = false;
    let mut positional: Vec<String> = Vec::new();
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--ledger" => {
                i += 1;
                ledger_path = args.get(i).cloned().map(std::path::PathBuf::from).unwrap_or(ledger_path);
            }
            "--no-auth" => no_auth = true,
            other => positional.push(other.to_string()),
        }
        i += 1;
    }

    match positional.first().map(String::as_str) {
        Some("--generate-key") | Some("generate-key") => {
            let Some(customer) = positional.get(1) else {
                eprintln!("usage: ot-mcp --generate-key <customer> [--plan <plan>] [--max-calls <n>]");
                std::process::exit(2);
            };
            let mut plan = "alpha".to_string();
            let mut max_calls = None;
            let mut j = 2;
            while j < positional.len() {
                match positional[j].as_str() {
                    "--plan" => {
                        j += 1;
                        plan = positional.get(j).cloned().unwrap_or(plan);
                    }
                    "--max-calls" => {
                        j += 1;
                        max_calls = positional.get(j).and_then(|v| v.parse().ok());
                    }
                    _ => {}
                }
                j += 1;
            }
            match auth::Ledger::add(&ledger_path, customer, &plan, max_calls) {
                Ok(key) => {
                    // the key is printed ONCE; only its hash is stored
                    println!("{key}");
                }
                Err(e) => {
                    eprintln!("ledger error: {e}");
                    std::process::exit(1);
                }
            }
        }
        Some("--help") | Some("-h") | Some("help") => {
            eprintln!("usage: ot-mcp [--no-auth] [--ledger <path>] [--generate-key <customer> ...]");
        }
        _ => {
            // serve
            let mut state = ServerState {
                skip_auth: no_auth,
                ledger_path: ledger_path.clone(),
                ..Default::default()
            };
            use std::io::BufRead;
            let stdin = std::io::stdin();
            let lines = stdin.lock().lines().map_while(Result::ok);
            let stdout = std::io::stdout();
            let mut out_lock = stdout.lock();
            serve_lines(
                lines,
                &mut |resp| {
                    use std::io::Write;
                    let _ = writeln!(out_lock, "{resp}");
                    let _ = out_lock.flush();
                },
                &mut state,
            );
        }
    }
}
