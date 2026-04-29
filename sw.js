const CACHE = 'market-v1';
const STATIC = ['./','./index.html','./manifest.json'];

self.addEventListener('install', e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)))
);

self.addEventListener('fetch', e => {
  const url = e.request.url;
  // data/latest.json → network first，失敗才用快取
  if (url.includes('latest.json')) {
    e.respondWith(
      fetch(e.request).then(r => {
        const clone = r.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return r;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  // 其他靜態資源 → cache first
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
