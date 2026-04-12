(async function () {
  const { slabCrackerToken, slabCrackerEmail, slabCrackerBackend, slabCrackerTokenAt } =
    await chrome.storage.local.get([
      "slabCrackerToken",
      "slabCrackerEmail",
      "slabCrackerBackend",
      "slabCrackerTokenAt",
    ]);

  const el = document.getElementById("auth-status");
  if (slabCrackerToken && slabCrackerEmail) {
    const ageMin = Math.floor((Date.now() - (slabCrackerTokenAt || 0)) / 60000);
    el.innerHTML = `<span class="ok">Signed in as ${slabCrackerEmail}</span><div class="muted">Backend: ${slabCrackerBackend || "(not set)"} · token age: ${ageMin}m</div>`;
  } else {
    el.innerHTML = `<span class="err">Not signed in</span><div class="muted">Open the Slab Cracker admin site and sign in with Google.</div>`;
  }

  document.getElementById("open-btn").addEventListener("click", () => {
    const cert = document.getElementById("cert").value.trim();
    if (!/^\d{8,9}$/.test(cert)) {
      alert("Enter a valid 8-9 digit cert number");
      return;
    }
    chrome.tabs.create({ url: `https://www.psacard.com/cert/${cert}` });
  });
})();
