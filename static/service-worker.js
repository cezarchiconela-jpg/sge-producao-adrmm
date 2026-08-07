const CACHE_NAME = 'sge-asm-v2';
const APP_SHELL = [
  '/offline',
  '/instalar',
  '/static/theme_sge.css',
  '/static/leituras.css',
  '/static/sge_ui.js',
  '/static/pwa-install.js',
  '/static/adrmm_logo.png',
  '/static/icons/sge-192.png',
  '/static/icons/sge-512.png'
];

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // Uma falha transitória num recurso não pode impedir a instalação inteira
    // do service worker. Os recursos válidos são guardados individualmente.
    await Promise.allSettled(APP_SHELL.map(async url => {
      const response = await fetch(url, { cache: 'reload' });
      if (!response.ok) throw new Error(`Falha ao preparar ${url}: ${response.status}`);
      await cache.put(url, response);
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/offline')));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => cached || fetch(request).then(response => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
        }
        return response;
      }))
    );
  }
});
