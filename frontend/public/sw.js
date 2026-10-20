const CACHE='personal-options-trader-shell-v1';
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(['/','/manifest.webmanifest','/icon.svg']))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))));
self.addEventListener('fetch',event=>{const request=event.request;if(request.method!=='GET'||new URL(request.url).pathname.startsWith('/api/'))return;event.respondWith(fetch(request).then(response=>{if(response.ok&&new URL(request.url).origin===location.origin){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(request,copy))}return response}).catch(()=>caches.match(request).then(cached=>cached||caches.match('/'))))});
