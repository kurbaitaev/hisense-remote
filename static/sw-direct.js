const CACHE = "roku-direct-v1";
const ASSETS = [
  "/direct",
  "/static/direct.html",
  "/static/direct.js",
  "/static/direct-app.js",
  "/static/style.css",
  "/static/icons/icon-192.svg",
  "/static/manifest-direct.webmanifest",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith("/static") && url.pathname !== "/direct") return;

  e.respondWith(
    caches.match(e.request).then((cached) =>
      cached
        || fetch(e.request).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return res;
        }),
    ),
  );
});
