// Minimal service worker: app-shell cache so the PWA opens offline.
const CACHE = "suma-v4";
const SHELL = ["/", "/styles.css", "/app.js", "/manifest.webmanifest",
               "/locales/es.json", "/locales/en.json", "/icon.svg", "/wordmark.svg"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
});
self.addEventListener("activate", e => {
  // Drop stale shells — caches.match searches every cache, old ones included.
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
});
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET" || e.request.url.includes("/api/")) return;
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
});
