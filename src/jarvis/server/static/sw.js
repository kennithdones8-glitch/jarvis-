"use strict";
// JARVIS service worker: shows notifications only. Payloads are generic ("JARVIS needs a decision") —
// your content is never in a notification. No offline caching (the app always shows live state).
self.addEventListener("push", (event) => {
  let data = { title: "JARVIS", body: "JARVIS has an update", tag: "jarvis" };
  try { data = { ...data, ...event.data.json() }; } catch (e) { /* keep the generic text */ }
  const url = typeof data.url === "string" && data.url.startsWith("/") && !data.url.startsWith("//") ? data.url : "/";
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, tag: data.tag, renotify: true, icon: "/static/icon-192.png", badge: "/static/icon-192.png",
    data: { url },
  }));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(self.clients.matchAll({ type: "window" }).then((wins) => {
    for (const w of wins) if ("focus" in w) { if ("navigate" in w) w.navigate(url); return w.focus(); }
    return self.clients.openWindow(url);
  }));
});
