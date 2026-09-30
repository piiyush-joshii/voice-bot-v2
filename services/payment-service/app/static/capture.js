// Hosted capture page logic. Card fields stay inside this origin. The parent frame
// only ever receives {type: "payment_status", status}.
(function () {
  "use strict";

  var body = document.body;
  var sessionId = body.getAttribute("data-session-id");
  var parentOrigin = body.getAttribute("data-parent-origin");
  var form = document.getElementById("card-form");
  var pan = document.getElementById("pan");
  var expiry = document.getElementById("expiry");
  var cvv = document.getElementById("cvv");
  var errorEl = document.getElementById("error");
  var resultEl = document.getElementById("result");
  var countdown = document.getElementById("countdown");
  var payBtn = document.getElementById("pay");
  var cancelBtn = document.getElementById("cancel");
  var lastFocused = pan;
  var finished = false;
  var TERMINAL = { succeeded: 1, failed: 1, cancelled: 1, expired: 1 };
  var MESSAGES = {
    invalid_card: "That card number is not valid. Please check and try again.",
    invalid_expiry: "The expiry date is not valid or is in the past.",
    invalid_cvv: "The CVV must be 3 or 4 digits."
  };

  function clearFields() {
    pan.value = "";
    expiry.value = "";
    cvv.value = "";
  }

  function notifyParent(status) {
    if (window.parent && window.parent !== window && parentOrigin) {
      window.parent.postMessage({ type: "payment_status", status: status }, parentOrigin);
    }
  }

  function finish(status) {
    if (finished) return;
    finished = true;
    clearFields();
    form.hidden = true;
    var text = {
      succeeded: "Payment approved. You can return to the conversation.",
      failed: "Payment was not completed.",
      cancelled: "Payment cancelled.",
      expired: "This secure session has expired."
    }[status] || status;
    resultEl.textContent = text;
    resultEl.className = "result " + (status === "succeeded" ? "ok" : "fail");
    resultEl.hidden = false;
    notifyParent(status);
  }

  function formatPan(value) {
    return value.replace(/\D/g, "").slice(0, 19).replace(/(\d{4})(?=\d)/g, "$1 ");
  }

  pan.addEventListener("input", function () { pan.value = formatPan(pan.value); });
  expiry.addEventListener("input", function () {
    var digits = expiry.value.replace(/\D/g, "").slice(0, 4);
    expiry.value = digits.length > 2 ? digits.slice(0, 2) + "/" + digits.slice(2) : digits;
  });
  cvv.addEventListener("input", function () { cvv.value = cvv.value.replace(/\D/g, "").slice(0, 4); });
  [pan, expiry, cvv].forEach(function (el) {
    el.addEventListener("focus", function () { lastFocused = el; });
  });

  document.getElementById("keypad").addEventListener("click", function (e) {
    var key = e.target && e.target.getAttribute("data-key");
    if (!key) return;
    var el = lastFocused;
    if (key === "back") el.value = el.value.slice(0, -1);
    else el.value += key;
    el.dispatchEvent(new Event("input"));
    el.focus();
  });

  function postJson(path, payload) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload ? JSON.stringify(payload) : "{}",
      credentials: "same-origin",
      cache: "no-store"
    }).then(function (r) { return r.json(); });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (finished) return;
    errorEl.textContent = "";
    payBtn.disabled = true;
    var payload = { pan: pan.value, expiry: expiry.value, cvv: cvv.value };
    postJson("/capture/" + encodeURIComponent(sessionId) + "/submit", payload)
      .then(function (res) {
        payload = null;
        if (TERMINAL[res.status]) return finish(res.status);
        cvv.value = "";
        var msg = MESSAGES[res.error] || "Please check your details.";
        if (typeof res.attempts_left === "number") msg += " Attempts left: " + res.attempts_left + ".";
        errorEl.textContent = msg;
      })
      .catch(function () { errorEl.textContent = "Could not reach the payment service. Please try again."; })
      .then(function () { payBtn.disabled = false; });
  });

  cancelBtn.addEventListener("click", function () {
    postJson("/capture/" + encodeURIComponent(sessionId) + "/cancel").then(function (res) { finish(res.status); });
  });

  function poll() {
    if (finished) return;
    fetch("/capture/" + encodeURIComponent(sessionId) + "/state", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (TERMINAL[s.status]) return finish(s.status);
        countdown.textContent = "Session expires in " + s.seconds_left + " s";
        setTimeout(poll, 1000);
      })
      .catch(function () { setTimeout(poll, 2000); });
  }

  poll();
  pan.focus();
})();
