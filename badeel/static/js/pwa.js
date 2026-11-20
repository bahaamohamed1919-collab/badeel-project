// Installable app (PWA) and medicine-reminder notifications.
//  - registers the service worker (/sw.js) so Badeel can be added to the home
//    screen and receive notifications;
//  - "Turn on notifications" asks the browser, then sends the subscription to
//    the server, which sends reminders at the right time;
//  - while the dashboard is open, it also shows the next dose itself.
(function () {
  "use strict";
  if (!("serviceWorker" in navigator)) { return; }
  var ready = navigator.serviceWorker.register("/sw.js").then(function () { return navigator.serviceWorker.ready; });

  var bar = document.querySelector(".notify-bar");
  if (!bar) { return; }
  var on = bar.querySelector("[data-push-on]"), off = bar.querySelector("[data-push-off]");
  var state = bar.querySelector(".notify-state");
  var token = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  bar.hidden = false;
  function say(key) { state.textContent = key ? state.getAttribute("data-" + key) : ""; }

  var canPush = "PushManager" in window && "Notification" in window && bar.getAttribute("data-push-ready") === "1";
  if (!canPush) { on.hidden = true; say("unsupported"); return; }

  function b64ToBytes(b64) {
    var pad = "=".repeat((4 - b64.length % 4) % 4);
    var raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) { out[i] = raw.charCodeAt(i); }
    return out;
  }
  function post(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token }, body: JSON.stringify(body) });
  }
  function show(subscribed) {
    on.hidden = subscribed; off.hidden = !subscribed;
    say(subscribed ? "on" : (Notification.permission === "denied" ? "denied" : ""));
  }

  ready.then(function (reg) { return reg.pushManager.getSubscription(); }).then(function (sub) { show(!!sub); });

  on.addEventListener("click", function () {
    Notification.requestPermission().then(function (perm) {
      if (perm !== "granted") { show(false); return; }
      return fetch("/push/key", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (k) {
        if (!k.available) { on.hidden = true; say("unsupported"); return; }
        return ready.then(function (reg) {
          return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(k.key) });
        }).then(function (sub) { return post("/push/subscribe", sub.toJSON()).then(function () { show(true); }); });
      });
    }).catch(function () { say("unsupported"); });
  });

  off.addEventListener("click", function () {
    ready.then(function (reg) { return reg.pushManager.getSubscription(); }).then(function (sub) {
      if (!sub) { show(false); return; }
      return post("/push/unsubscribe", { endpoint: sub.endpoint }).then(function () { return sub.unsubscribe(); })
        .then(function () { show(false); });
    });
  });

  // While this page is open, show the next dose even without the server task.
  if (Notification.permission === "granted") {
    document.querySelectorAll("[data-next-dose]").forEach(function (el) {
      var wait = new Date(el.getAttribute("data-next-dose")).getTime() - Date.now();
      if (wait > 0 && wait < 12 * 3600 * 1000) {
        setTimeout(function () {
          ready.then(function (reg) {
            reg.showNotification("ميعاد " + el.getAttribute("data-name"), {
              body: "ده ميعاد الجرعة بتاعتك.", tag: "dose-local-" + el.getAttribute("data-name"),
              dir: "rtl", lang: "ar", icon: "/static/icons/icon-192.png", data: { url: "/me#reminders" } });
          });
        }, wait);
      }
    });
  }
})();
