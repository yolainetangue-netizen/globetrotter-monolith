// Shared helpers for all pages of the GlobeTrotter monolith frontend

function getToken() {
  return localStorage.getItem("gt_token");
}

function setToken(token) {
  localStorage.setItem("gt_token", token);
}

function clearToken() {
  localStorage.removeItem("gt_token");
}

function isLoggedIn() {
  return !!getToken();
}

async function apiRequest(path, { method = "GET", body = null, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : null,
  });

  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, data };
}

function showMessage(el, text, type) {
  el.textContent = text;
  el.className = `message ${type}`;
}

// Update nav login/logout link on every page
document.addEventListener("DOMContentLoaded", () => {
  const authLink = document.getElementById("auth-link");
  if (!authLink) return;

  if (isLoggedIn()) {
    authLink.textContent = "Logout";
    authLink.href = "#";
    authLink.addEventListener("click", (e) => {
      e.preventDefault();
      clearToken();
      window.location.href = "/login-page";
    });
  } else {
    authLink.textContent = "Login";
    authLink.href = "/login-page";
  }
});
