// Firebase config is set as window.FIREBASE_CONFIG by Hugo at build time (see head.html partial).
// Validate that the config has actual values (empty when .env isn't sourced).
window._firebaseReady = false;
(function() {
  const cfg = window.FIREBASE_CONFIG || {};
  if (!cfg.apiKey || !cfg.projectId) {
    console.error('Firebase config is empty. Did you source .env before running hugo server?');
    console.error('Run: set -a && source .env && set +a && hugo server');
    return;
  }
  try {
    firebase.initializeApp(cfg);
    window._firebaseReady = true;
  } catch (e) {
    console.error('Firebase init failed:', e);
  }
})();

// Global sign-out
async function authSignOut() {
  await firebase.auth().signOut();
  window.location.href = "/";
}

// Sign in with Google popup
async function signInWithGoogle() {
  if (!window._firebaseReady) {
    const errEl = document.getElementById('auth-error');
    if (errEl) {
      errEl.textContent = 'Firebase not configured. Run: set -a && source .env && set +a && hugo server';
      errEl.classList.remove('d-none');
    }
    return;
  }
  const provider = new firebase.auth.GoogleAuthProvider();
  try {
    await firebase.auth().signInWithPopup(provider);
    // onAuthStateChanged handles whitelist check and redirect
  } catch (e) {
    if (e.code !== 'auth/popup-closed-by-user') {
      const msg = e.code === 'auth/unauthorized-domain'
        ? 'This domain is not authorized in Firebase. Add it to Authentication > Settings > Authorized domains.'
        : 'Sign-in failed: ' + (e.code || '') + ' — ' + e.message;
      showToast(msg, 'danger');
    }
  }
}

// Returns true if the email is in the allowed list (or if no list is configured).
// window.ALLOWED_EMAILS may arrive as a JSON array string (Hugo split|jsonify quirk) or a real array.
function isEmailAllowed(email) {
  let raw = window.ALLOWED_EMAILS || [];
  if (typeof raw === 'string') {
    try { raw = JSON.parse(raw); } catch (_) { raw = raw.split(','); }
  }
  const allowed = raw.map(e => e.trim().toLowerCase()).filter(Boolean);
  if (allowed.length === 0) return true; // no restriction configured
  return allowed.includes(email.toLowerCase());
}

// Navbar auth state + admin enforcement
if (!window._firebaseReady) {
  // Show login button even when Firebase is misconfigured, so the error is visible on click
  const loginBtn = document.getElementById("btn-login");
  if (loginBtn) loginBtn.classList.remove("d-none");
}
if (window._firebaseReady) firebase.auth().onAuthStateChanged(user => {
  const emailEl   = document.getElementById("nav-user-email");
  const logoutBtn = document.getElementById("btn-logout");
  const loginBtn  = document.getElementById("btn-login");
  const navLinks  = document.getElementById("nav-links");

  if (user) {
    const isAdmin = isEmailAllowed(user.email);
    window.currentUserIsAdmin = isAdmin;

    if (emailEl)   emailEl.textContent = user.email;
    if (logoutBtn) logoutBtn.classList.remove("d-none");
    if (loginBtn)  loginBtn.classList.add("d-none");
    if (navLinks)  navLinks.style.removeProperty("display");

    // Gray out admin-only nav links for non-admins
    document.querySelectorAll('.nav-admin-only').forEach(el => {
      el.classList.toggle('nav-admin-disabled', !isAdmin);
    });
  } else {
    window.currentUserIsAdmin = false;
    if (emailEl)   emailEl.textContent = "";
    if (logoutBtn) logoutBtn.classList.add("d-none");
    if (loginBtn)  loginBtn.classList.remove("d-none");
    if (navLinks)  navLinks.style.setProperty("display", "none", "important");
  }
});
