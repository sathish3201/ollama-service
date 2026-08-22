// Minimal service worker: caches the UI shell so the app installs and
// opens instantly, but never caches API responses — chat always needs a
// live backend, caching those would just show stale/wrong answers.
const SHELL_CACHE = "chat-shell-v1";
const SHELL_FILES = ["/", "/manifest.json", "/static/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Only serve the shell from cache; everything else (API calls) goes
  // straight to the network, always.
  if (SHELL_FILES.includes(url.pathname)) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
});
