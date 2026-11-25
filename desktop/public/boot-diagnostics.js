// Runs before the React bundle. A classic script, because the CSP (script-src 'self')
// forbids inline code. It keeps a tiny boot log and, if the app has not mounted after
// a few seconds or fails before it mounts, shows what it knows instead of a blank window.
// It never runs after React has mounted and it makes no network requests.
(function () {
  "use strict";
  var STALL_MS = 8000;
  var started = Date.now();
  var events = [];

  function mark(text) {
    if (events.length < 50) {
      events.push("+" + (Date.now() - started) + "ms " + text);
    }
  }

  function placeholder() {
    return document.querySelector("[data-boot-placeholder]");
  }

  function mounted() {
    return placeholder() === null;
  }

  function report(kind, message) {
    try {
      var internals = window.__TAURI_INTERNALS__;
      if (internals && typeof internals.invoke === "function") {
        var pending = internals.invoke("frontend_report", {
          kind: kind,
          message: String(message).slice(0, 2000),
        });
        if (pending && typeof pending.catch === "function") {
          pending.catch(function () {});
        }
      }
    } catch (ignored) {}
  }

  function snapshot() {
    return [
      "readyState=" + document.readyState,
      "tauriInternals=" + typeof window.__TAURI_INTERNALS__,
      "url=" + location.href,
      "events: " + (events.length ? events.join(" | ") : "none"),
    ].join("\n");
  }

  function show(headline, detail) {
    var box = placeholder();
    if (!box) {
      return;
    }
    box.hidden = false;
    box.querySelector("[data-boot-status]").textContent = headline;
    var pre = box.querySelector("[data-boot-detail]");
    pre.hidden = false;
    pre.textContent = detail;
  }

  function failed(kind, headline, detail) {
    if (mounted()) {
      return;
    }
    mark(kind + ": " + headline);
    show("ClamUI could not start: " + headline, detail + "\n\n" + snapshot());
    report("boot-error", kind + ": " + headline + " | " + detail + " | " + snapshot());
  }

  window.__clamuiBoot = { mark: mark, events: events };
  mark("boot script ran");

  // Capture phase so that a script or stylesheet that fails to load is seen too.
  window.addEventListener(
    "error",
    function (event) {
      var target = event.target;
      if (target && target !== window && (target.src || target.href)) {
        failed("resource", "could not load " + (target.src || target.href), "");
        return;
      }
      failed(
        "error",
        String(event.message || "script error"),
        (event.filename || "") + ":" + (event.lineno || 0) + ":" + (event.colno || 0),
      );
    },
    true,
  );
  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    failed("unhandled promise rejection", String((reason && reason.message) || reason), "");
  });
  document.addEventListener("securitypolicyviolation", function (event) {
    mark("CSP blocked " + event.violatedDirective + " " + event.blockedURI);
  });
  document.addEventListener("DOMContentLoaded", function () {
    mark("DOM ready");
  });

  setTimeout(function () {
    if (mounted()) {
      return;
    }
    mark("still not mounted");
    show(
      "ClamUI is still starting after " + STALL_MS / 1000 + " seconds",
      "The window opened but the interface has not appeared. See the troubleshooting guide " +
        "(Blank window) at https://clamui.com/docs/troubleshooting/ and include this text in a bug report.\n\n" +
        snapshot(),
    );
    report("boot-stalled", snapshot());
  }, STALL_MS);
})();
