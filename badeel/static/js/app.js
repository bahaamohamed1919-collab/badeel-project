// Badeel front-end script. No libraries. The site works without it too;
// it only adds: the light/dark toggle, closing menus, search suggestions and confirm dialogs.
(function () {
  "use strict";

  // ---- light / dark mode (the choice is remembered in this browser)
  var root = document.documentElement;
  var themeButton = document.querySelector(".theme-toggle");
  function currentTheme() {
    var set = root.getAttribute("data-theme");
    if (set) { return set; }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  if (themeButton) {
    themeButton.setAttribute("aria-pressed", currentTheme() === "light" ? "true" : "false");
    themeButton.addEventListener("click", function () {
      var next = currentTheme() === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      themeButton.setAttribute("aria-pressed", next === "light" ? "true" : "false");
      try { window.localStorage.setItem("badeel-theme", next); } catch (e) { /* storage blocked */ }
    });
  }

  // ---- dropdown menus (<details>): close on outside click, Escape, or opening another
  var dropdowns = document.querySelectorAll("details.dropdown");
  dropdowns.forEach(function (d) {
    d.addEventListener("toggle", function () {
      if (!d.open) { return; }
      dropdowns.forEach(function (other) { if (other !== d) { other.open = false; } });
    });
  });
  document.addEventListener("click", function (event) {
    dropdowns.forEach(function (d) { if (d.open && !d.contains(event.target)) { d.open = false; } });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") { return; }
    dropdowns.forEach(function (d) {
      if (d.open) { d.open = false; d.querySelector("summary").focus(); }
    });
  });

  // ---- "are you sure?" on dangerous forms (data-confirm="message")
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var condition = form.getAttribute("data-confirm-if");   // e.g. "mode=replace"
      if (condition) {
        var parts = condition.split("=");
        var field = form.querySelector('[name="' + parts[0] + '"]:checked');
        if (!field || field.value !== parts[1]) { return; }
      }
      if (!window.confirm(form.getAttribute("data-confirm"))) { event.preventDefault(); }
    });
  });

  // ---- search by voice (Web Speech API, built into Chrome, Edge and Safari)
  // Egyptian Arabic (ar-EG) or English (en-US); the choice is remembered.
  (function () {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var mic = document.querySelector("[data-voice]");
    var langBtn = document.querySelector("[data-voice-lang]");
    var field = document.getElementById("q");
    var status = document.querySelector(".voice-status");
    if (!SR || !mic || !field) { return; }          // not supported: the buttons stay hidden
    var lang;
    try { lang = window.localStorage.getItem("badeel-voice-lang"); } catch (e) { lang = null; }
    if (lang !== "ar-EG" && lang !== "en-US") { lang = document.documentElement.lang === "ar" ? "ar-EG" : "en-US"; }
    function showLang() {
      langBtn.textContent = lang === "ar-EG" ? "ع" : "EN";
      langBtn.title = lang === "ar-EG" ? "الصوت: عربي مصري (اضغط للإنجليزي)" : "Voice: English (tap for Egyptian Arabic)";
    }
    function say(text) { if (status) { status.textContent = text; status.hidden = !text; } }
    mic.hidden = false;
    if (langBtn) {
      langBtn.hidden = false;
      showLang();
      langBtn.addEventListener("click", function () {
        lang = lang === "ar-EG" ? "en-US" : "ar-EG";
        try { window.localStorage.setItem("badeel-voice-lang", lang); } catch (e) { /* blocked */ }
        showLang();
      });
    }
    var rec = null;
    mic.addEventListener("click", function () {
      if (rec) { rec.stop(); return; }
      rec = new SR();
      rec.lang = lang;
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      var heard = "";
      rec.onstart = function () { mic.classList.add("listening"); mic.setAttribute("aria-pressed", "true"); say(mic.getAttribute("data-label-listen")); };
      rec.onresult = function (event) {
        heard = "";
        for (var i = 0; i < event.results.length; i++) { heard += event.results[i][0].transcript; }
        field.value = heard.trim();
      };
      rec.onerror = function (event) {
        say(mic.getAttribute(event.error === "not-allowed" || event.error === "service-not-allowed"
          ? "data-label-denied" : "data-label-error"));
      };
      rec.onend = function () {
        mic.classList.remove("listening");
        mic.setAttribute("aria-pressed", "false");
        rec = null;
        if (heard.trim()) {
          say("");
          if (field.form.requestSubmit) { field.form.requestSubmit(); } else { field.form.submit(); }
        }
      };
      try { rec.start(); } catch (e) { rec = null; say(mic.getAttribute("data-label-error")); }
    });
  })();

  // ---- search by photo: send the photo as soon as it is chosen or taken
  (function () {
    var photo = document.getElementById("photo-input");
    var form = document.getElementById("photo-form");
    if (!photo || !form) { return; }
    photo.addEventListener("change", function () {
      if (!photo.files || !photo.files.length) { return; }
      var note = form.querySelector(".photo-status");
      if (note) { note.hidden = false; }
      form.submit();
    });
  })();

  // ---- search suggestions
  var input = document.querySelector("input[data-suggest]");
  var list = document.getElementById("suggest");
  if (!input || !list) { return; }
  var timer = null, active = -1, lastQuery = "";

  function close() { list.hidden = true; list.innerHTML = ""; active = -1; }

  function render(items) {
    list.innerHTML = "";
    items.forEach(function (item) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = item.url;
      // textContent (not innerHTML): drug names can never inject HTML.
      a.textContent = item.name + (item.name_ar ? "  " + item.name_ar : "");
      var small = document.createElement("small");
      small.textContent = item.detail;
      small.dir = "ltr";
      a.appendChild(small);
      li.appendChild(a);
      list.appendChild(li);
    });
    list.hidden = items.length === 0;
    active = -1;
  }

  input.addEventListener("input", function () {
    var q = input.value.trim();
    clearTimeout(timer);
    if (q.length < 2) { close(); return; }
    timer = setTimeout(function () {             // wait until typing pauses
      lastQuery = q;
      fetch(input.getAttribute("data-suggest") + "?q=" + encodeURIComponent(q))
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (items) { if (q === lastQuery) { render(items); } })
        .catch(close);
    }, 180);
  });

  input.addEventListener("keydown", function (event) {
    var links = list.querySelectorAll("a");
    if (list.hidden || !links.length) { return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + links.length) % links.length;
      links.forEach(function (a, i) { a.classList.toggle("on", i === active); });
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      window.location.href = links[active].href;
    } else if (event.key === "Escape") {
      close();
    }
  });

  document.addEventListener("click", function (event) {
    if (!list.contains(event.target) && event.target !== input) { close(); }
  });
})();
