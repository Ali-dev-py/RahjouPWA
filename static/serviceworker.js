"use strict";

const CACHE_NAME = "rahjou-shell-v8";
const CORE_ASSETS = [
    "/",
    "/?source=pwa",
    "/login/",
    "/offline/",
    "/manifest.webmanifest",
    "/static/css/app.css",
    "/static/js/app.js",
    "/static/manifest.json",
    "/static/images/logo.png",
    "/static/icons/apple-touch-icon.png",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
    "/static/icons/icon-maskable-192.png",
    "/static/icons/icon-maskable-512.png",
    "/static/screenshots/dashboard.png",
];
const OPTIONAL_EXTERNAL_ASSETS = [
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.rtl.min.css",
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js",
    "https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700&display=swap",
    "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200",
];
const CACHEABLE_EXTERNAL_HOSTS = new Set([
    "cdn.jsdelivr.net",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
]);

self.addEventListener("install", (event) => {
    event.waitUntil(
        (async () => {
            const cache = await caches.open(CACHE_NAME);
            await cache.addAll(CORE_ASSETS);
            await Promise.allSettled(
                OPTIONAL_EXTERNAL_ASSETS.map(async (asset) => {
                    const response = await fetch(asset, { mode: "no-cors" });
                    await cache.put(asset, response);
                }),
            );
            await self.skipWaiting();
        })(),
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        (async () => {
            const cacheNames = await caches.keys();
            await Promise.all(
                cacheNames
                    .filter((cacheName) => cacheName !== CACHE_NAME)
                    .map((cacheName) => caches.delete(cacheName)),
            );
            await self.clients.claim();
        })(),
    );
});

async function networkFirstNavigation(request) {
    const cache = await caches.open(CACHE_NAME);
    try {
        const response = await fetch(request);
        if (response.ok) {
            await cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        return (await cache.match(request)) || (await cache.match("/offline/"));
    }
}

async function staleWhileRevalidate(request) {
    const cache = await caches.open(CACHE_NAME);
    const cachedResponse = await cache.match(request);
    const networkResponse = fetch(request)
        .then(async (response) => {
            if (response.ok || response.type === "opaque") {
                await cache.put(request, response.clone());
            }
            return response;
        })
        .catch(() => cachedResponse);

    return cachedResponse || networkResponse;
}

self.addEventListener("fetch", (event) => {
    const { request } = event;
    if (request.method !== "GET") {
        return;
    }

    const url = new URL(request.url);
    if (!url.protocol.startsWith("http")) {
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith(networkFirstNavigation(request));
        return;
    }

    const isLocalStaticAsset =
        url.origin === self.location.origin && url.pathname.startsWith("/static/");
    const isCacheableExternalAsset = CACHEABLE_EXTERNAL_HOSTS.has(url.hostname);

    if (isLocalStaticAsset || isCacheableExternalAsset) {
        event.respondWith(staleWhileRevalidate(request));
    }
});
