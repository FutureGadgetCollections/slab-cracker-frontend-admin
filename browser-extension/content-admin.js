// Runs on the Slab Cracker admin site. Content scripts live in an isolated
// JS world, so we can't read `window.firebase` directly — the admin page
// posts its Firebase ID token to us via window.postMessage, and we forward
// it into chrome.storage.local where content-psa.js can pick it up.

window.addEventListener("message", (ev) => {
  if (ev.source !== window) return;
  const msg = ev.data;
  if (!msg || typeof msg !== "object") return;

  if (msg.type === "SLAB_CRACKER_AUTH") {
    if (!msg.token) {
      chrome.storage.local.remove([
        "slabCrackerToken",
        "slabCrackerBackend",
        "slabCrackerEmail",
        "slabCrackerTokenAt",
      ]);
      return;
    }
    chrome.storage.local.set({
      slabCrackerToken: msg.token,
      slabCrackerBackend: msg.backend || "",
      slabCrackerEmail: msg.email || "",
      slabCrackerTokenAt: Date.now(),
    });
    console.log("[SlabCracker] Auth synced to extension:", msg.email);
    return;
  }

  if (msg.type === "SLAB_CRACKER_REQUEST_CERT" && msg.cert_number) {
    chrome.runtime.sendMessage({
      type: "requestCert",
      cert_number: msg.cert_number,
    });
  }
});
