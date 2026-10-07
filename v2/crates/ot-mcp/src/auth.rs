//! API-key auth — the onboarding law (locked #334/#338): agents onboard as
//! customers of the hosted API via operator-issued keys.
//!
//! Laws:
//!   * keys are generated (`ot_<32 hex>`), shown ONCE; the ledger stores
//!     only SHA-256 hashes — never raw keys;
//!   * the ledger lives outside the repo (`~/.ot-mcp/keys.json`, mode
//!     700 best-effort) — the secrets law (never commit credentials);
//!   * limits are per-customer plan fields, enforced per session
//!     (stdio = one process per agent; counters reset on restart —
//!     documented, not hidden).

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::PathBuf;

pub fn key_hash(key: &str) -> String {
    let mut h = Sha256::new();
    h.update(key.as_bytes());
    format!("{:x}", h.finalize())
}

/// Generate a key: `ot_<32 hex>` from the OS CSPRNG.
pub fn generate_key() -> Result<String, String> {
    let mut bytes = [0u8; 16];
    getrandom::getrandom(&mut bytes).map_err(|e| format!("CSPRNG unavailable: {e}"))?;
    let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    Ok(format!("ot_{hex}"))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LedgerEntry {
    pub key_hash: String,
    pub customer: String,
    pub plan: String,
    /// per-session tool-call limit; None = unlimited
    pub max_calls: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Ledger {
    pub entries: Vec<LedgerEntry>,
}

impl Ledger {
    pub fn load(path: &PathBuf) -> Result<Ledger, String> {
        let text = std::fs::read_to_string(path)
            .map_err(|e| format!("ledger unreadable at {}: {e}", path.display()))?;
        serde_json::from_str(&text).map_err(|e| format!("ledger corrupt: {e}"))
    }

    /// Add an entry, persisting atomically (write-temp-rename).
    pub fn add(
        path: &PathBuf,
        customer: &str,
        plan: &str,
        max_calls: Option<u64>,
    ) -> Result<String, String> {
        let key = generate_key()?;
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut ledger = match Self::load(path) {
            Ok(l) => l,
            Err(_) => Ledger::default(),
        };
        ledger.entries.push(LedgerEntry {
            key_hash: key_hash(&key),
            customer: customer.to_string(),
            plan: plan.to_string(),
            max_calls,
        });
        let tmp = path.with_extension("tmp");
        std::fs::write(&tmp, serde_json::to_string_pretty(&ledger).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, path).map_err(|e| e.to_string())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
        }
        Ok(key)
    }

    /// Verify a presented key → the customer identity (hash lookup only —
    /// the raw key is never stored anywhere).
    pub fn verify(&self, key: &str) -> Option<Identity> {
        let h = key_hash(key);
        self.entries.iter().find(|e| e.key_hash == h).map(|e| Identity {
            customer: e.customer.clone(),
            plan: e.plan.clone(),
            max_calls: e.max_calls,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Identity {
    pub customer: String,
    pub plan: String,
    pub max_calls: Option<u64>,
}

pub fn default_ledger_path() -> PathBuf {
    if let Ok(p) = std::env::var("OT_MCP_LEDGER") {
        return PathBuf::from(p);
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
    PathBuf::from(home).join(".ot-mcp").join("keys.json")
}
