// Чтобы приложение открывалось и без интернета: сама страница и иконки берутся из кэша,
// если сети нет. Новости приложение хранит само (localStorage), их здесь не кэшируем.
const CACHE = "varis-v1";
const SHELL = ["./", "manifest.webmanifest", "apple-touch-icon.png", "icon-192.png"];

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
  if(e.request.method !== "GET" || !url.pathname.includes("/app/")) return;
  // сначала сеть (чтобы обновления страницы приходили сразу), при ошибке — кэш
  e.respondWith(fetch(e.request).then(r => {
    if(r.ok){ const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)) }
    return r;
  }).catch(() => caches.match(e.request, {ignoreSearch:true})));
});
