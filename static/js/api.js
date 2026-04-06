const BACKEND_URL = (document.body.dataset.backendUrl || "").replace(/\/$/, "");

/**
 * Authenticated fetch wrapper.
 * Attaches the current Firebase user's ID token as a Bearer token.
 */
async function api(method, path, body, _retry = true) {
  const user = firebase.auth().currentUser;
  if (!user) throw new Error("Not authenticated");

  const token = await user.getIdToken();
  const opts = {
    method,
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type":  "application/json",
    },
  };
  if (body) opts.body = JSON.stringify(body);

  const res = await fetch(`${BACKEND_URL}${path}`, opts);
  if (res.status === 401 && _retry) {
    await user.getIdToken(true);
    return api(method, path, body, false);
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.message || j.error || msg; } catch (_) {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}

// Convenience: build a query string from an object, omitting nulls/empty strings
function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") p.set(k, v);
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
