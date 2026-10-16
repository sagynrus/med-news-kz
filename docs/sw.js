// Чтобы лента открывалась и без интернета: сама страница и иконки берутся из кэша,
// если сети нет. Новости страница хранит сама (localStorage), RSS и JSON здесь не трогаем.
const CACHE = "varis-v2";
const SHELL = ["./", "manifest.webmanifest", "icons/apple-touch-icon.png", "icons/icon-192.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  const shell = e.request.mode === "navigate" || url.pathname.includes("/icons/") || url.pathname.endsWith(".webmanifest");
  if(e.request.method !== "GET" || url.origin !== location.origin || !shell) return;
  // сначала сеть (чтобы обновления страницы приходили сразу), при ошибке — кэш
  e.respondWith(fetch(e.request).then(r => {
    if(r.ok && e.request.mode !== "navigate"){ const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)) }
    if(r.ok && url.pathname.endsWith("/")){ const copy = r.clone(); caches.open(CACHE).then(c => c.put("./", copy)) }
    return r;
  }).catch(() => caches.match(e.request, {ignoreSearch:true})
    .then(m => m || (e.request.mode === "navigate" ? caches.match("./") : undefined))));
});
