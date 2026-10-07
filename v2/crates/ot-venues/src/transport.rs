//! Transport seam — the ONLY path to the network. Encodes the guard law
//! (V1 `security/guards.py`) as construction rules: HTTPS-only to the
//! allowlisted OANDA hosts, credentials never logged, bounded bodies.

use serde_json::Value;

/// One response. V1's `_request` returns `{}` on transport failure and
/// `{"_error":..., "_status": code}` on HTTP errors — callers treat those
/// as "venue said no" (never "assume it worked").
#[derive(Debug, Clone)]
pub struct Resp {
    pub status: u16,
    pub body: String,
}

impl Resp {
    pub fn json(&self) -> Option<Value> {
        serde_json::from_str(&self.body).ok()
    }
}

/// The network seam. Implementations: `UreqTransport` (live) and
/// `FakeTransport` (tests — the venue is never touched by test code).
pub trait Transport: Send + Sync {
    fn request(
        &self,
        method: &str,
        url: &str,
        body: Option<&str>,
        headers: &[(String, String)],
    ) -> Result<Resp, String>;

    /// Open a streaming GET (the pricing stream). Returns a line iterator;
    /// the adapter owns framing (OANDA: JSON objects terminated by `\n`).
    fn stream(
        &self,
        url: &str,
        headers: &[(String, String)],
    ) -> Result<Box<dyn Iterator<Item = String> + Send>, String>;
}

/// Allowlist — the guard law: only these hosts may be contacted.
pub const ALLOWED_HOSTS: &[&str] = &[
    "api-fxpractice.oanda.com",
    "api-fxtrade.oanda.com",
    "stream-fxpractice.oanda.com",
    "stream-fxtrade.oanda.com",
];

pub fn validate_url(url: &str) -> Result<(), String> {
    let rest = url
        .strip_prefix("https://")
        .ok_or_else(|| format!("guard: not HTTPS: {url}"))?;
    let host = rest.split('/').next().unwrap_or("");
    if ALLOWED_HOSTS.contains(&host) {
        Ok(())
    } else {
        Err(format!("guard: host not allowlisted: {host}"))
    }
}

/// Live transport (ureq, rustls). Timeouts bounded; no redirects; the
/// bearer token rides in a header and is never logged (errors carry URLs
/// without query strings where credentials could appear — OANDA uses the
/// Authorization header, so URLs are credential-free).
pub struct UreqTransport {
    agent: ureq::Agent,
}

impl UreqTransport {
    pub fn new() -> Self {
        let agent = ureq::AgentBuilder::new()
            .timeout_connect(std::time::Duration::from_secs(15))
            .timeout(std::time::Duration::from_secs(30))
            .redirects(0)
            .build();
        UreqTransport { agent }
    }
}

impl Default for UreqTransport {
    fn default() -> Self {
        Self::new()
    }
}

impl Transport for UreqTransport {
    fn request(
        &self,
        method: &str,
        url: &str,
        body: Option<&str>,
        headers: &[(String, String)],
    ) -> Result<Resp, String> {
        validate_url(url)?;
        let mut req = match method {
            "GET" => self.agent.get(url),
            "POST" => self.agent.post(url),
            "PUT" => self.agent.put(url),
            _ => return Err(format!("unsupported method {method}")),
        };
        for (k, v) in headers {
            req = req.set(k, v);
        }
        let resp = match body {
            Some(b) => req.send_string(b),
            None => req.call(),
        };
        match resp {
            Ok(r) => {
                let status = r.status();
                let text = r.into_string().map_err(|e| e.to_string())?;
                Ok(Resp { status, body: text })
            }
            Err(ureq::Error::Status(code, r)) => {
                // HTTP error → the V1 `_error` shape lands in the adapter.
                let text = r.into_string().unwrap_or_default();
                Ok(Resp {
                    status: code,
                    body: text,
                })
            }
            Err(e) => Err(e.to_string()),
        }
    }

    fn stream(
        &self,
        url: &str,
        headers: &[(String, String)],
    ) -> Result<Box<dyn Iterator<Item = String> + Send>, String> {
        validate_url(url)?;
        let mut req = self.agent.get(url);
        req = req.set("Connection", "keep-alive");
        for (k, v) in headers {
            req = req.set(k, v);
        }
        use std::io::BufRead;
        let reader = req.call().map_err(|e| e.to_string())?;
        let reader = reader.into_reader();
        let buf = std::io::BufReader::new(reader);
        let lines: Vec<String> = buf
            .lines()
            .map_while(Result::ok)
            .collect();
        Ok(Box::new(lines.into_iter()))
    }
}
