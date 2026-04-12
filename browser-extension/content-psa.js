// Runs on https://www.psacard.com/cert/*
// After the user clears any Cloudflare challenge, this script:
//   1. Extracts cert-info fields from the page's Next.js RSC payload
//   2. Downloads front/back scan images (same-origin, user's cookies)
//   3. POSTs everything to the Slab Cracker backend using the Firebase token
//      that was synced into chrome.storage by content-admin.js.

(async function scrapePSA() {
  const m = location.pathname.match(/^\/cert\/(\d+)/);
  if (!m) return;
  const certNumber = m[1];

  // Give the page a moment in case it's still hydrating.
  await new Promise((r) => setTimeout(r, 1500));

  const { slabCrackerToken, slabCrackerBackend } = await chrome.storage.local.get([
    "slabCrackerToken",
    "slabCrackerBackend",
  ]);

  if (!slabCrackerToken || !slabCrackerBackend) {
    toast("Slab Cracker: not signed in — open the admin site and sign in first");
    return;
  }

  const html = document.documentElement.outerHTML;

  const fields = parseCertFields(html);
  if (Object.keys(fields).length === 0) {
    toast("Slab Cracker: no cert data found on page — is the WAF challenge clear?");
    return;
  }

  const scanURLs = parseScanURLs(html).slice(0, 2);
  toast(`Slab Cracker: scraping ${certNumber} (${scanURLs.length} scans)…`);

  const scans = [];
  for (const url of scanURLs) {
    try {
      const blob = await fetch(url, { credentials: "include" }).then((r) => r.blob());
      scans.push({
        url,
        data: await blobToBase64(blob),
        content_type: blob.type || "image/jpeg",
      });
    } catch (e) {
      console.warn("[SlabCracker] scan fetch failed:", url, e);
    }
  }

  const payload = {
    cert_number: certNumber,
    fields,
    scans,
  };

  try {
    const res = await fetch(`${slabCrackerBackend}/certs/scraped-submit`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${slabCrackerToken}`,
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.text();
      toast(`Slab Cracker: submit failed (${res.status}): ${body.slice(0, 120)}`);
      return;
    }
    const json = await res.json();
    toast(`Slab Cracker: cert ${certNumber} submitted ✓ (${json.card_name || ""})`);
  } catch (e) {
    toast(`Slab Cracker: network error — ${e.message}`);
  }
})();

function parseCertFields(html) {
  // Matches PSA's Next.js RSC payload fragments like:
  //   "cert-info-0" ... "children":"Category" ... "children":"TCG Cards"
  const re = /cert-info-(\d+).*?\\?"children\\?":\\?"([^"\\]+)\\?".*?\\?"children\\?":\\?"([^"\\]*?)\\?"/g;
  const fields = {};
  let m;
  while ((m = re.exec(html)) !== null) {
    const label = m[2];
    const value = m[3].replace(/\\u0026/g, "&").replace(/\\u0027/g, "'").replace(/&#x27;/g, "'");
    fields[label] = value;
  }
  return fields;
}

function parseScanURLs(html) {
  const re = /\\?"originalPath\\?":\\?"(https:\/\/d1htnxwo4o0jhw\.cloudfront\.net\/cert\/\d+\/[a-zA-Z0-9_-]+\.jpg)\\?"/g;
  const seen = new Set();
  const urls = [];
  let m;
  while ((m = re.exec(html)) !== null) {
    if (!seen.has(m[1])) {
      seen.add(m[1]);
      urls.push(m[1]);
    }
  }
  return urls;
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const s = reader.result;
      resolve(s.substring(s.indexOf(",") + 1));
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

function toast(msg) {
  console.log("[SlabCracker]", msg);
  let el = document.getElementById("__slab-cracker-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "__slab-cracker-toast";
    el.style.cssText =
      "position:fixed;bottom:20px;right:20px;z-index:999999;background:#111;color:#fff;" +
      "padding:12px 16px;border-radius:8px;font:14px system-ui;max-width:340px;box-shadow:0 4px 16px rgba(0,0,0,.3)";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.display = "block";
  clearTimeout(el.__hideTimer);
  el.__hideTimer = setTimeout(() => (el.style.display = "none"), 6000);
}
