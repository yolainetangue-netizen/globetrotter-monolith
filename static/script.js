// Shared helpers for all pages of the GlobeTrotter monolith frontend

// "Se souvenir de moi" coche -> localStorage (persiste apres fermeture du navigateur)
// decoche -> sessionStorage (efface a la fermeture de l'onglet/navigateur)
function getToken() {
  return localStorage.getItem("gt_token") || sessionStorage.getItem("gt_token");
}

function setToken(token, remember = true) {
  if (remember) {
    localStorage.setItem("gt_token", token);
    sessionStorage.removeItem("gt_token");
  } else {
    sessionStorage.setItem("gt_token", token);
    localStorage.removeItem("gt_token");
  }
}

function clearToken() {
  localStorage.removeItem("gt_token");
  sessionStorage.removeItem("gt_token");
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

// ---------------------------------------------------------------------------
// Photos dynamiques (API d'images) avec cache local
// ---------------------------------------------------------------------------
const PHOTO_CACHE_PREFIX = "gt_photo_";

async function fetchPhoto(query, fallbackQuery = "") {
  const cacheKey = PHOTO_CACHE_PREFIX + query + "|" + fallbackQuery;
  const cached = localStorage.getItem(cacheKey);
  if (cached !== null) return cached === "null" ? null : cached;

  try {
    const params = new URLSearchParams({ q: query });
    if (fallbackQuery) params.append("fallback", fallbackQuery);
    const res = await fetch(`/api/photo?${params.toString()}`);
    const data = await res.json();
    localStorage.setItem(cacheKey, data.url || "null");
    return data.url || null;
  } catch {
    return null;
  }
}

// Recherche tous les elements [data-photo-query] dans `root` et remplace
// leur fond par la photo trouvee (sans rien casser si l'API n'est pas configuree).
function hydratePhotos(root = document) {
  root.querySelectorAll("[data-photo-query]").forEach(async (el) => {
    const query = el.dataset.photoQuery;
    const fallbackQuery = el.dataset.photoFallback || "";
    if (!query || el.dataset.photoDone) return;
    el.dataset.photoDone = "1";
    const url = await fetchPhoto(query, fallbackQuery);
    if (url) {
      el.style.backgroundImage = `url('${url}')`;
      el.classList.add("photo-loaded");
    }
  });
}

// Update nav login/logout link on every page
document.addEventListener("DOMContentLoaded", () => {
  const authLink = document.getElementById("auth-link");
  if (!authLink) return;

  if (isLoggedIn()) {
    authLink.textContent = "Déconnexion";
    authLink.href = "#";
    authLink.addEventListener("click", (e) => {
      e.preventDefault();
      clearToken();
      window.location.href = "/login-page";
    });
  } else {
    authLink.textContent = "Connexion";
    authLink.href = "/login-page";
  }
});
