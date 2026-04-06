// Firebase config is set as window.FIREBASE_CONFIG by Hugo at build time (see head.html partial).
firebase.initializeApp(window.FIREBASE_CONFIG);

// Global sign-out
async function authSignOut() {
  await firebase.auth().signOut();
  window.location.href = "/";
}

// Sign in with Google popup
async function signInWithGoogle() {
  const provider = new firebase.auth.GoogleAuthProvider();
  try {
    await firebase.auth().signInWithPopup(provider);
    // onAuthStateChanged handles whitelist check and redirect
  } catch (e) {
    if (e.code !== 'auth/popup-closed-by-user') {
      showToast('Sign-in failed: ' + e.message, 'danger');
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
firebase.auth().onAuthStateChanged(user => {
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
