"""
GlobeTrotter Travel Assistant - Phase 1: The Monolith
A single Flask server handling all requests, with data stored in a JSON file.
"""

import io
import json
import os
import time
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

load_dotenv()  # charge automatiquement les variables definies dans un fichier .env

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "globetrotter-dev-secret")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=6)
jwt = JWTManager(app)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")

# ---------------------------------------------------------------------------
# Supabase Storage configuration
# Permet de conserver data.json ailleurs que sur le disque local de Render,
# qui n'est pas persistant sur le plan gratuit (les donnees sont perdues a
# chaque redeploiement / reveil apres mise en veille). Si ces variables ne
# sont pas definies, l'app continue de fonctionner uniquement avec le fichier
# local (comportement precedent), pour ne jamais bloquer le demarrage.
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "globetrotter-data")
SUPABASE_STORAGE_ENABLED = bool(SUPABASE_URL and SUPABASE_SECRET_KEY)
SUPABASE_OBJECT_PATH = "data.json"

# ---------------------------------------------------------------------------
# Google Sign-In configuration
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

# ---------------------------------------------------------------------------
# Image API configuration (Pexels — gratuit, cle sur https://www.pexels.com/api/)
# ---------------------------------------------------------------------------
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
_photo_cache = {}  # simple cache memoire : {query: url_or_None}

# ---------------------------------------------------------------------------
# Weather API configuration (Open-Meteo — gratuit, sans cle)
# ---------------------------------------------------------------------------
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_weather_cache = {}  # {"lat,lng": {"data": ..., "ts": ...}}
WEATHER_CACHE_TTL = 1800  # 30 minutes


# ---------------------------------------------------------------------------
# Data Access Layer (reads/writes the JSON "database")
# ---------------------------------------------------------------------------
def _supabase_object_url():
    return f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{SUPABASE_OBJECT_PATH}"


def _supabase_download_to_disk():
    """Telecharge data.json depuis Supabase Storage et l'ecrit sur le disque
    local. Retourne True si reussi. Ne leve jamais d'exception : en cas
    d'echec (reseau, fichier absent la 1ere fois...), on continue avec la
    copie locale existante (celle du zip deploye)."""
    try:
        resp = requests.get(
            _supabase_object_url(),
            headers={
                "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
                "apiKey": SUPABASE_SECRET_KEY,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            with open(DATA_FILE, "wb") as f:
                f.write(resp.content)
            return True
    except requests.RequestException:
        pass
    return False


def _supabase_upload_from_disk():
    """Envoie le data.json local vers Supabase Storage (upsert). Ne leve
    jamais d'exception : si Supabase est injoignable, l'ecriture locale reste
    valable pour la duree de vie du process, mais ne survivra pas a un
    redemarrage - on log simplement l'echec."""
    try:
        with open(DATA_FILE, "rb") as f:
            content = f.read()
        resp = requests.post(
            _supabase_object_url(),
            headers={
                "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
                "apiKey": SUPABASE_SECRET_KEY,
                "Content-Type": "application/json",
                "x-upsert": "true",
            },
            data=content,
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            print(f"[supabase] echec upload data.json: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"[supabase] erreur reseau upload data.json: {exc}")


# Au demarrage du process, on tente une seule fois de recuperer la derniere
# version connue depuis Supabase (qui peut contenir des utilisateurs/avis
# crees depuis le dernier deploiement). Si indisponible, on garde le
# data.json du zip deploye tel quel.
if SUPABASE_STORAGE_ENABLED:
    _supabase_download_to_disk()


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    if SUPABASE_STORAGE_ENABLED:
        _supabase_upload_from_disk()


def next_id(items):
    return max((item["id"] for item in items), default=0) + 1


def admin_required(fn):
    """Decorateur : verifie que l'utilisateur JWT courant a le role 'admin'.
    A utiliser en plus (et apres) de @jwt_required()."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = int(get_jwt_identity())
        data = load_data()
        user = next((u for u in data["users"] if u["id"] == user_id), None)
        if not user or user.get("role") != "admin":
            return jsonify({"error": "admin access required"}), 403
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Frontend routes (serve the HTML pages)
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register-page")
def register_page():
    # Meme page que la connexion, desormais fusionnees avec un bouton
    # de bascule (voir templates/login.html)
    return render_template("login.html", google_client_id=GOOGLE_CLIENT_ID)


@app.route("/login-page")
def login_page():
    return render_template("login.html", google_client_id=GOOGLE_CLIENT_ID)


@app.route("/destinations-page")
def destinations_page():
    return render_template("destinations.html")


@app.route("/itineraries-page")
def itineraries_page():
    return render_template("itineraries.html")


@app.route("/map-page")
def map_page():
    return render_template("map.html")


@app.route("/transport-page")
def transport_page():
    return render_template("transport.html")


@app.route("/kribi-page")
def kribi_page():
    return render_template("kribi.html")


@app.route("/category/<path:category_name>")
def category_page(category_name):
    return render_template("category.html", category_name=category_name)


@app.route("/events-page")
def events_page():
    return render_template("events.html")


@app.route("/services-page")
def services_page():
    return render_template("services.html")


@app.route("/favorites-page")
def favorites_page():
    return render_template("favorites.html")


@app.route("/profile-page")
def profile_page():
    # La verification de connexion se fait cote client (redirection si non
    # connecte), la route API /me exige elle un token JWT valide.
    return render_template("profile.html")


@app.route("/admin-page")
def admin_page():
    # La verification du role admin se fait cote client (redirection si non
    # admin) et surtout cote serveur sur la route API /admin/stats, qui est
    # la seule a exposer des donnees sensibles.
    return render_template("admin.html")


@app.route("/destination/<int:destination_id>")
def destination_detail_page(destination_id):
    return render_template("destination_detail.html", destination_id=destination_id)


# ---------------------------------------------------------------------------
# API Layer - Images
# Priorite 1 : Wikimedia Commons (gratuit, sans cle, souvent plus pertinent
#              pour des lieux precis - musees, monuments, sites touristiques).
# Priorite 2 : Pexels (banque generaliste, sert de repli si rien trouve).
# ---------------------------------------------------------------------------
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"


WIKIPEDIA_FR_API_URL = "https://fr.wikipedia.org/w/api.php"
WIKIPEDIA_EN_API_URL = "https://en.wikipedia.org/w/api.php"


def _search_wikipedia_pageimage(query, api_url):
    """Cherche l'article Wikipedia le plus pertinent pour la requete, et retourne
    l'image principale de cet article (celle de l'infobox en general). Cette
    approche est plus precise qu'une recherche de fichiers Commons "en vrac",
    car elle s'appuie sur le bon article plutot que sur un mot-cle isole."""
    try:
        search_resp = requests.get(
            api_url,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 1,
                "format": "json",
            },
            headers={"User-Agent": "GlobeTrotterApp/1.0 (student project)"},
            timeout=6,
        )
        search_resp.raise_for_status()
        results = search_resp.json().get("query", {}).get("search", [])
        if not results:
            return None
        page_title = results[0]["title"]

        image_resp = requests.get(
            api_url,
            params={
                "action": "query",
                "titles": page_title,
                "prop": "pageimages",
                "piprop": "original",
                "format": "json",
            },
            headers={"User-Agent": "GlobeTrotterApp/1.0 (student project)"},
            timeout=6,
        )
        image_resp.raise_for_status()
        pages = image_resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            original = page.get("original")
            if original:
                return original.get("source")
        return None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def _search_wikimedia_commons(query):
    """Cherche une image libre de droits sur Wikimedia Commons pour la requete.

    Retourne l'URL de l'image (thumbnail large) ou None si rien de pertinent.
    """
    try:
        # Etape 1 : rechercher des fichiers image correspondant a la requete
        search_resp = requests.get(
            WIKIMEDIA_API_URL,
            params={
                "action": "query",
                "list": "search",
                "srsearch": f"{query} filetype:bitmap",
                "srnamespace": 6,  # namespace "File:"
                "srlimit": 1,
                "format": "json",
            },
            headers={"User-Agent": "GlobeTrotterApp/1.0 (student project)"},
            timeout=6,
        )
        search_resp.raise_for_status()
        results = search_resp.json().get("query", {}).get("search", [])
        if not results:
            return None

        title = results[0]["title"]

        # Etape 2 : recuperer l'URL de l'image a partir de son titre
        info_resp = requests.get(
            WIKIMEDIA_API_URL,
            params={
                "action": "query",
                "titles": title,
                "prop": "imageinfo",
                "iiprop": "url",
                "iiurlwidth": 800,
                "format": "json",
            },
            headers={"User-Agent": "GlobeTrotterApp/1.0 (student project)"},
            timeout=6,
        )
        info_resp.raise_for_status()
        pages = info_resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            imageinfo = page.get("imageinfo")
            if imageinfo:
                return imageinfo[0].get("thumburl") or imageinfo[0].get("url")
        return None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def _search_pexels(query):
    """Cherche une photo libre de droits sur Pexels (banque generaliste)."""
    if not PEXELS_API_KEY:
        return None
    try:
        resp = requests.get(
            PEXELS_SEARCH_URL,
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=6,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        return photos[0]["src"]["large"] if photos else None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


@app.route("/api/photo", methods=["GET"])
def get_photo():
    """Retourne l'URL d'une photo libre de droits correspondant a la requete.

    Ordre de recherche, du plus precis au plus large :
      1. Image principale de l'article Wikipedia francophone correspondant
      2. Idem sur Wikipedia anglophone (au cas ou l'article FR n'existe pas)
      3. Recherche de fichier sur Wikimedia Commons (requete precise)
      4. Recherche de fichier sur Wikimedia Commons (requete generique de repli, ?fallback=)
    Pexels a ete volontairement exclu : les resultats etaient trop generiques
    et ne correspondaient pas toujours au lieu exact recherche. Si aucune
    source ne renvoie de resultat, url=None : le frontend affiche alors une
    vignette generique (icone de categorie) plutot qu'une photo non pertinente.
    """
    query = request.args.get("q", "").strip()
    fallback_query = request.args.get("fallback", "").strip()
    if not query:
        return jsonify({"url": None}), 200

    cache_key = f"{query}|{fallback_query}"
    if cache_key in _photo_cache:
        return jsonify({"url": _photo_cache[cache_key]}), 200

    url = _search_wikipedia_pageimage(query, WIKIPEDIA_FR_API_URL)
    source = "wikipedia-fr" if url else None

    if not url:
        url = _search_wikipedia_pageimage(query, WIKIPEDIA_EN_API_URL)
        source = "wikipedia-en" if url else None

    if not url:
        url = _search_wikimedia_commons(query)
        source = "wikimedia-commons" if url else None

    if not url and fallback_query:
        url = _search_wikimedia_commons(fallback_query)
        source = "wikimedia-commons-fallback" if url else None

    _photo_cache[cache_key] = url
    return jsonify({"url": url, "source": source}), 200


@app.route("/api/weather", methods=["GET"])
def get_weather():
    """Retourne la meteo actuelle + prevision 4 jours pour des coordonnees GPS.

    Utilise Open-Meteo (https://open-meteo.com), gratuit et sans cle API.
    Reponse mise en cache 30 minutes par coordonnees pour eviter les appels
    repetes.
    """
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    if not lat or not lng:
        return jsonify({"error": "parametres lat et lng requis"}), 400

    cache_key = f"{lat},{lng}"
    now = time.time()
    cached = _weather_cache.get(cache_key)
    if cached and (now - cached["ts"]) < WEATHER_CACHE_TTL:
        return jsonify(cached["data"]), 200

    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "current_weather": "true",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "auto",
                "forecast_days": 4,
            },
            timeout=6,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return jsonify({"error": "meteo indisponible pour le moment"}), 502

    _weather_cache[cache_key] = {"data": payload, "ts": now}
    return jsonify(payload), 200


# ---------------------------------------------------------------------------
# API Layer - Authentication
# ---------------------------------------------------------------------------
@app.route("/register", methods=["POST"])
def register():
    """Register a new user."""
    body = request.get_json(silent=True) or {}
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    preferences = body.get("preferences", [])

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    data = load_data()

    if any(u["username"] == username for u in data["users"]):
        return jsonify({"error": "username already exists"}), 409

    user = {
        "id": next_id(data["users"]),
        "username": username,
        "password": password,  # NOTE: plain text for the demo/monolith phase only
        "preferences": preferences,
    }
    data["users"].append(user)
    save_data(data)

    return jsonify({"message": "user registered", "user": {"id": user["id"], "username": username}}), 201


@app.route("/login", methods=["POST"])
def login():
    """Authenticate a user and return a JWT access token."""
    body = request.get_json(silent=True) or {}
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()

    data = load_data()
    user = next((u for u in data["users"] if u["username"] == username), None)

    if not user or user.get("password") is None or user["password"] != password:
        return jsonify({"error": "invalid username or password"}), 401

    token = create_access_token(identity=str(user["id"]))
    return jsonify({"access_token": token, "user": {"id": user["id"], "username": user["username"]}}), 200


@app.route("/auth/google", methods=["POST"])
def auth_google():
    """Connecte ou cree un utilisateur a partir d'un jeton d'identite Google.

    Le front-end recupere un "credential" (jeton signe) via Google Identity
    Services, puis l'envoie ici. On le verifie aupres de Google (signature,
    audience, expiration) avant de faire confiance a son contenu.
    """
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "Google sign-in is not configured on the server"}), 503

    body = request.get_json(silent=True) or {}
    credential = body.get("credential", "").strip()

    if not credential:
        return jsonify({"error": "missing Google credential"}), 400

    try:
        payload = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        return jsonify({"error": "invalid Google credential"}), 401

    google_sub = payload.get("sub")
    email = payload.get("email", "")
    name = payload.get("name") or (email.split("@")[0] if email else f"user{google_sub}")

    if not google_sub:
        return jsonify({"error": "invalid Google credential"}), 401

    data = load_data()

    # Un compte Google est retrouve via son identifiant Google unique (sub),
    # jamais via le mot de passe puisqu'il n'y en a pas pour ce type de compte.
    user = next((u for u in data["users"] if u.get("google_sub") == google_sub), None)

    if not user:
        # Evite les collisions avec un nom d'utilisateur "classique" existant.
        username = name
        suffix = 1
        existing_usernames = {u["username"] for u in data["users"]}
        while username in existing_usernames:
            suffix += 1
            username = f"{name}{suffix}"

        user = {
            "id": next_id(data["users"]),
            "username": username,
            "password": None,  # pas de mot de passe pour les comptes Google
            "preferences": [],
            "auth_provider": "google",
            "google_sub": google_sub,
            "email": email,
        }
        data["users"].append(user)
        save_data(data)

    token = create_access_token(identity=str(user["id"]))
    return jsonify({"access_token": token, "user": {"id": user["id"], "username": user["username"]}}), 200


@app.route("/me", methods=["GET"])
@jwt_required()
def get_me():
    """Retourne le profil complet de l'utilisateur actuellement connecte
    (utilise par l'onglet Profil et pour savoir si le lien admin doit
    s'afficher dans la navigation)."""
    user_id = int(get_jwt_identity())
    data = load_data()

    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "user not found"}), 404

    # Ne jamais renvoyer le mot de passe, meme hashe/absent.
    safe_user = {
        "id": user["id"],
        "username": user["username"],
        "preferences": user.get("preferences", []),
        "role": user.get("role", "user"),
        "auth_provider": user.get("auth_provider", "password"),
        "email": user.get("email"),
    }
    return jsonify(safe_user), 200


# ---------------------------------------------------------------------------
# API Layer - Destinations
# ---------------------------------------------------------------------------
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "static", "images")
LOCAL_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def get_local_image_url(image_id, prefix=""):
    """Si une image a ete fournie manuellement (fichier nomme d'apres son id,
    eventuellement prefixe pour les evenements/services), retourne son URL.
    Sinon retourne None (le frontend se rabattra alors sur Wikimedia/Pexels)."""
    for ext in LOCAL_IMAGE_EXTENSIONS:
        filename = f"{prefix}{image_id}{ext}"
        if os.path.isfile(os.path.join(IMAGES_DIR, filename)):
            return f"/static/images/{filename}"
    return None


def attach_local_image(destination):
    destination = dict(destination)
    destination["local_image"] = get_local_image_url(destination["id"])
    return destination


def attach_event_image(event):
    event = dict(event)
    event["local_image"] = get_local_image_url(event["id"], prefix="event-")
    return event


@app.route("/destinations", methods=["GET"])
def get_destinations():
    """Search destinations, optionally filtered by name, country, tag, category or city."""
    data = load_data()
    destinations = data["destinations"]

    query = request.args.get("q", "").strip().lower()
    tag = request.args.get("tag", "").strip().lower()
    category = request.args.get("category", "").strip().lower()
    city = request.args.get("city", "").strip().lower()

    if query:
        destinations = [
            d for d in destinations
            if query in d["name"].lower() or query in d["country"].lower()
        ]

    if tag:
        destinations = [d for d in destinations if tag in [t.lower() for t in d["tags"]]]

    if category:
        destinations = [d for d in destinations if d.get("category", "").lower() == category]

    if city:
        destinations = [d for d in destinations if d.get("city", "").lower() == city]

    return jsonify([attach_local_image(d) for d in destinations]), 200


@app.route("/destinations/<int:destination_id>", methods=["GET"])
def get_destination_by_id(destination_id):
    """Return a single destination's full details."""
    data = load_data()
    destination = next((d for d in data["destinations"] if d["id"] == destination_id), None)
    if not destination:
        return jsonify({"error": "destination not found"}), 404

    # Compteur de vues, utilise ensuite par le tableau de bord admin
    # pour identifier les lieux les plus consultes.
    destination["views"] = destination.get("views", 0) + 1
    save_data(data)

    return jsonify(attach_local_image(destination)), 200


# ---------------------------------------------------------------------------
# API Layer - Avis / Reviews
# ---------------------------------------------------------------------------
@app.route("/destinations/<int:destination_id>/reviews", methods=["GET"])
def get_reviews(destination_id):
    """Retourne les avis d'une destination, triés du plus récent au plus ancien,
    ainsi que la note moyenne."""
    data = load_data()
    if not any(d["id"] == destination_id for d in data["destinations"]):
        return jsonify({"error": "destination not found"}), 404

    reviews = [r for r in data.get("reviews", []) if r["destination_id"] == destination_id]
    reviews.sort(key=lambda r: r["date"], reverse=True)
    average = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else None

    return jsonify({"reviews": reviews, "average": average, "count": len(reviews)}), 200


@app.route("/destinations/<int:destination_id>/reviews", methods=["POST"])
def create_review(destination_id):
    """Ajoute un avis (note + commentaire) sur une destination. Ouvert a tous,
    connecte ou non (un pseudonyme facultatif peut etre fourni)."""
    data = load_data()
    if not any(d["id"] == destination_id for d in data["destinations"]):
        return jsonify({"error": "destination not found"}), 404

    body = request.get_json(silent=True) or {}
    author = (body.get("author") or "").strip() or "Visiteur anonyme"
    comment = (body.get("comment") or "").strip()
    rating = body.get("rating")

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({"error": "rating must be an integer between 1 and 5"}), 400

    if rating < 1 or rating > 5:
        return jsonify({"error": "rating must be between 1 and 5"}), 400
    if not comment:
        return jsonify({"error": "comment is required"}), 400

    review = {
        "id": next_id(data.get("reviews", [])),
        "destination_id": destination_id,
        "author": author[:60],
        "rating": rating,
        "comment": comment[:1000],
        "date": datetime.utcnow().isoformat() + "Z",
    }
    data.setdefault("reviews", []).append(review)
    save_data(data)

    return jsonify({"message": "review added", "review": review}), 201


# ---------------------------------------------------------------------------
# API Layer - Evenements & Services utiles
# ---------------------------------------------------------------------------
KRIBI_CENTER = (2.9464, 9.9074)


def haversine_km(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, sqrt, atan2
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


@app.route("/events", methods=["GET"])
def get_events():
    """List upcoming/all events, sorted by date. ?upcoming=true filters out past events."""
    data = load_data()
    events = data.get("events", [])
    if request.args.get("upcoming", "").lower() == "true":
        today = datetime.utcnow().strftime("%Y-%m-%d")
        events = [e for e in events if (e.get("end_date") or e.get("date")) >= today]
    events = sorted(events, key=lambda e: e["date"])
    return jsonify([attach_event_image(e) for e in events]), 200


@app.route("/services", methods=["GET"])
def get_services():
    """List useful services (hospitals, pharmacies, banks...), sorted by distance
    from the Kribi city center. ?type= filters by service type."""
    data = load_data()
    services = data.get("services", [])

    service_type = request.args.get("type", "").strip().lower()
    if service_type:
        services = [s for s in services if s.get("type", "").lower() == service_type]

    enriched = []
    for s in services:
        item = dict(s)
        item["distance_km"] = round(
            haversine_km(KRIBI_CENTER[0], KRIBI_CENTER[1], s["lat"], s["lng"]), 2
        )
        enriched.append(item)

    enriched.sort(key=lambda s: s["distance_km"])
    return jsonify(enriched), 200


# ---------------------------------------------------------------------------
# API Layer - Recommendations
# ---------------------------------------------------------------------------
@app.route("/recommendations", methods=["GET"])
@jwt_required()
def get_recommendations():
    """Return destinations matching the current user's preferences."""
    user_id = int(get_jwt_identity())
    data = load_data()

    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "user not found"}), 404

    preferences = set(p.lower() for p in user.get("preferences", []))

    if not preferences:
        # No preferences set -> return everything
        recommended = data["destinations"]
    else:
        recommended = [
            d for d in data["destinations"]
            if preferences.intersection(t.lower() for t in d["tags"])
        ]

    return jsonify([attach_local_image(d) for d in recommended]), 200


# ---------------------------------------------------------------------------
# API Layer - Itineraries
# ---------------------------------------------------------------------------
@app.route("/itineraries", methods=["POST"])
@jwt_required()
def create_itinerary():
    """Create a new itinerary for the current user."""
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}

    title = body.get("title", "").strip()
    destination_id = body.get("destination_id")
    start_date = body.get("start_date", "")
    end_date = body.get("end_date", "")
    notes = body.get("notes", "")

    if not title or destination_id is None:
        return jsonify({"error": "title and destination_id are required"}), 400

    data = load_data()

    if not any(d["id"] == destination_id for d in data["destinations"]):
        return jsonify({"error": "destination_id does not exist"}), 400

    itinerary = {
        "id": next_id(data["itineraries"]),
        "user_id": user_id,
        "title": title,
        "destination_id": destination_id,
        "start_date": start_date,
        "end_date": end_date,
        "notes": notes,
    }
    data["itineraries"].append(itinerary)
    save_data(data)

    return jsonify({"message": "itinerary created", "itinerary": itinerary}), 201


@app.route("/itineraries", methods=["GET"])
@jwt_required()
def get_itineraries():
    """Return all itineraries belonging to the current user."""
    user_id = int(get_jwt_identity())
    data = load_data()

    user_itineraries = [it for it in data["itineraries"] if it["user_id"] == user_id]
    return jsonify(user_itineraries), 200


def build_itinerary_pdf(itinerary, destination):
    """Genere un PDF autonome (consultable hors-ligne, imprimable) pour un
    itineraire, avec les infos pratiques de la destination associee."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "GTTitle", parent=styles["Title"], fontSize=22, textColor=colors.HexColor("#0e3a5c"),
    )
    heading_style = ParagraphStyle(
        "GTHeading", parent=styles["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6,
        textColor=colors.HexColor("#0e3a5c"),
    )
    normal_style = ParagraphStyle("GTNormal", parent=styles["Normal"], fontSize=10.5, leading=15)
    muted_style = ParagraphStyle("GTMuted", parent=styles["Normal"], fontSize=9, textColor=colors.grey)

    story = []
    story.append(Paragraph("GlobeTrotter-Kribi", muted_style))
    story.append(Paragraph(itinerary.get("title") or "Mon itineraire", title_style))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#0e3a5c"), thickness=1))
    story.append(Spacer(1, 10))

    dest_name = destination["name"] if destination else f"Destination #{itinerary.get('destination_id')}"
    dest_category = destination.get("category", "") if destination else ""

    story.append(Paragraph("Destination", heading_style))
    story.append(Paragraph(f"<b>{dest_name}</b>" + (f" &nbsp;&nbsp;<font color='grey'>({dest_category})</font>" if dest_category else ""), normal_style))
    if destination and destination.get("description"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(destination["description"], normal_style))

    story.append(Paragraph("Dates du sejour", heading_style))
    date_rows = [
        ["Depart", itinerary.get("start_date") or "Non precise"],
        ["Retour", itinerary.get("end_date") or "Non precise"],
    ]
    date_table = Table(date_rows, colWidths=[4 * cm, 10 * cm])
    date_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#0e3a5c")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(date_table)

    if itinerary.get("notes"):
        story.append(Paragraph("Notes personnelles", heading_style))
        story.append(Paragraph(itinerary["notes"], normal_style))

    if destination:
        if destination.get("budget"):
            story.append(Paragraph("Budget indicatif", heading_style))
            story.append(Paragraph(destination["budget"], normal_style))

        transport = destination.get("transport")
        if transport:
            story.append(Paragraph("Transport", heading_style))
            if isinstance(transport, dict):
                if transport.get("taxi"):
                    story.append(Paragraph(f"<b>Taxi :</b> {transport['taxi']}", normal_style))
                if transport.get("moto"):
                    story.append(Paragraph(f"<b>Moto-taxi :</b> {transport['moto']}", normal_style))
                if transport.get("note"):
                    story.append(Paragraph(f"<i>{transport['note']}</i>", muted_style))
            else:
                story.append(Paragraph(str(transport), normal_style))

        if destination.get("contact"):
            story.append(Paragraph("Contact", heading_style))
            story.append(Paragraph(destination["contact"], normal_style))

        practical = destination.get("practical_info") or {}
        if practical:
            story.append(Paragraph("Informations pratiques", heading_style))
            for label, key in [("Horaires", "hours"), ("Meilleure periode", "best_time"), ("Acces", "access")]:
                if practical.get(key):
                    story.append(Paragraph(f"<b>{label} :</b> {practical[key]}", normal_style))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#cccccc"), thickness=0.5))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"Genere le {datetime.utcnow().strftime('%d/%m/%Y')} depuis GlobeTrotter-Kribi. "
        "Document telechargeable, consultable sans connexion internet.",
        muted_style,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer


@app.route("/itineraries/<int:itinerary_id>/download", methods=["GET"])
@jwt_required()
def download_itinerary(itinerary_id):
    """Genere et renvoie un PDF telechargeable de l'itineraire, pour une
    consultation hors-ligne (utile la ou le reseau est absent)."""
    user_id = int(get_jwt_identity())
    data = load_data()

    itinerary = next((it for it in data["itineraries"] if it["id"] == itinerary_id), None)
    if not itinerary:
        return jsonify({"error": "itinerary not found"}), 404
    if itinerary["user_id"] != user_id:
        return jsonify({"error": "not authorized to access this itinerary"}), 403

    destination = next((d for d in data["destinations"] if d["id"] == itinerary["destination_id"]), None)

    pdf_buffer = build_itinerary_pdf(itinerary, destination)
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in (itinerary.get("title") or "itineraire")).strip() or "itineraire"
    filename = f"{safe_title}.pdf"

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


# ---------------------------------------------------------------------------
# API Layer - Reservations (hotels et restaurants uniquement)
# ---------------------------------------------------------------------------
RESERVABLE_CATEGORIES = {"Hôtels", "Restaurants"}


@app.route("/reservations", methods=["POST"])
def create_reservation():
    """Cree une reservation pour un hotel ou restaurant. Ne necessite pas
    d'etre connecte (formulaire accessible a tout visiteur), mais si un
    jeton JWT valide est fourni, la reservation est rattachee au compte."""
    body = request.get_json(silent=True) or {}

    destination_id = body.get("destination_id")
    guest_name = body.get("guest_name", "").strip()
    date = body.get("date", "").strip()
    time = body.get("time", "").strip()
    party_size = body.get("party_size")
    note = body.get("note", "").strip()

    if not destination_id or not guest_name or not date or not time or not party_size:
        return jsonify({"error": "destination_id, guest_name, date, time et party_size sont requis"}), 400

    try:
        party_size = int(party_size)
        if party_size < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "party_size doit etre un nombre entier positif"}), 400

    data = load_data()
    destination = next((d for d in data["destinations"] if d["id"] == destination_id), None)

    if not destination:
        return jsonify({"error": "destination not found"}), 404
    if destination.get("category") not in RESERVABLE_CATEGORIES:
        return jsonify({"error": "les reservations ne sont disponibles que pour les hotels et restaurants"}), 400

    # Rattache la reservation au compte connecte si un jeton valide est present,
    # sans exiger de connexion (visiteur de passage accepte aussi).
    user_id = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            user_id = int(identity)
    except Exception:
        user_id = None

    reservation = {
        "id": next_id(data["reservations"]),
        "destination_id": destination_id,
        "destination_name": destination["name"],
        "user_id": user_id,
        "guest_name": guest_name,
        "date": date,
        "time": time,
        "party_size": party_size,
        "note": note,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data["reservations"].append(reservation)
    save_data(data)

    return jsonify(reservation), 201


@app.route("/reservations", methods=["GET"])
@jwt_required()
def get_my_reservations():
    """Retourne les reservations de l'utilisateur connecte."""
    user_id = int(get_jwt_identity())
    data = load_data()
    my_reservations = [r for r in data["reservations"] if r.get("user_id") == user_id]
    my_reservations.sort(key=lambda r: r["created_at"], reverse=True)
    return jsonify(my_reservations), 200



@app.route("/admin/stats", methods=["GET"])
@jwt_required()
@admin_required
def admin_stats():
    """Tableau de bord admin : vue d'ensemble de l'activite de l'application."""
    data = load_data()

    destinations = data.get("destinations", [])
    reviews = data.get("reviews", [])
    users = data.get("users", [])
    itineraries = data.get("itineraries", [])
    events = data.get("events", [])
    services = data.get("services", [])

    # Endroits les plus consultes (compteur de vues incremente a chaque
    # ouverture de fiche detail, voir /destinations/<id>)
    most_viewed = sorted(destinations, key=lambda d: d.get("views", 0), reverse=True)[:10]
    most_viewed_list = [
        {
            "id": d["id"],
            "name": d["name"],
            "category": d.get("category"),
            "views": d.get("views", 0),
        }
        for d in most_viewed
        if d.get("views", 0) > 0
    ]

    # Note moyenne globale et repartition des notes
    ratings = [r["rating"] for r in reviews]
    average_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    # Avis les plus recents, avec le nom de la destination concernee pour lisibilite
    dest_by_id = {d["id"]: d["name"] for d in destinations}
    recent_reviews = sorted(reviews, key=lambda r: r["date"], reverse=True)[:10]
    recent_reviews_list = [
        {
            "id": r["id"],
            "destination_id": r["destination_id"],
            "destination_name": dest_by_id.get(r["destination_id"], "?"),
            "author": r["author"],
            "rating": r["rating"],
            "comment": r["comment"],
            "date": r["date"],
        }
        for r in recent_reviews
    ]

    # Repartition des destinations par categorie (utile pour voir la couverture du catalogue)
    by_category = {}
    for d in destinations:
        cat = d.get("category", "Autres")
        by_category[cat] = by_category.get(cat, 0) + 1

    # Reservations les plus recentes (hotels/restaurants), toutes confondues
    reservations = data.get("reservations", [])
    recent_reservations = sorted(reservations, key=lambda r: r["created_at"], reverse=True)[:20]

    stats = {
        "totals": {
            "users": len(users),
            "destinations": len(destinations),
            "reviews": len(reviews),
            "itineraries": len(itineraries),
            "events": len(events),
            "services": len(services),
            "total_views": sum(d.get("views", 0) for d in destinations),
            "reservations": len(reservations),
        },
        "average_rating": average_rating,
        "most_viewed_destinations": most_viewed_list,
        "recent_reviews": recent_reviews_list,
        "destinations_by_category": by_category,
        "recent_reservations": recent_reservations,
    }

    return jsonify(stats), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
