const CACHE='toonshelf-mobile-3.7.0';
const ASSETS=['./','./index.html','./app.js','./model.js','./storage.js','./style.css','./zip-worker.js','./desktop-features.js','./native.js','./folder-model.js','./vendor/fflate.js','./vendor/capacitor.js','./manifest.webmanifest','./icon-192.png','./icon-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('toonshelf-mobile-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('message',event=>{if(event.data==='activate')self.skipWaiting()});
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin||event.request.headers.has('authorization')||!ASSETS.some(a=>new URL(a,self.registration.scope).href===url.href))return;
 event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request)));
});
