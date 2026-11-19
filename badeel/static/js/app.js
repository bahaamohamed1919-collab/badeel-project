// Badeel front-end script. No libraries. The site works without it too;
// it only adds: search suggestions, confirm dialogs, and the mobile menu.
(function () {
  "use strict";

  // ---- mobile menu
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

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
