/* OpenTrader FX Monitor service worker.
   Shell: network-first (updates land on every load; cache is the offline
   fallback only). APIs: network-only (venue-authoritative, always fresh). */
"use strict";
const SHELL = "ot-shell-v2";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil((async () => {
  const keys = await caches.keys();
  await Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k)));
  await self.clients.claim();
})()));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return; // network-only
  e.respondWith((async () => {
    try {
      const r = await fetch(e.request);
      if (r && r.ok && r.type === "basic") {
        const cache = await caches.open(SHELL);
        cache.put(e.request, r.clone());
      }
      return r;
    } catch (err) {
      const cache = await caches.open(SHELL);
      return (await cache.match(e.request)) || Response.error();
    }
  })());
});
