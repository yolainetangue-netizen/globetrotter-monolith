"""
GlobeTrotter Travel Assistant - Phase 1: The Monolith
A single Flask server handling all requests, with data stored in a JSON file.
"""

import json
import os
from datetime import timedelta

from flask import Flask, jsonify, render_template, request
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "globetrotter-dev-secret")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=6)
jwt = JWTManager(app)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")


# ---------------------------------------------------------------------------
# Data Access Layer (reads/writes the JSON "database")
# ---------------------------------------------------------------------------
def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def next_id(items):
    return max((item["id"] for item in items), default=0) + 1


# ---------------------------------------------------------------------------
# Frontend routes (serve the HTML pages)
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register-page")
def register_page():
    return render_template("register.html")


@app.route("/login-page")
def login_page():
    return render_template("login.html")


@app.route("/destinations-page")
def destinations_page():
    return render_template("destinations.html")


@app.route("/itineraries-page")
def itineraries_page():
    return render_template("itineraries.html")


@app.route("/map-page")
def map_page():
    return render_template("map.html")


@app.route("/destination/<int:destination_id>")
def destination_detail_page(destination_id):
    return render_template("destination_detail.html", destination_id=destination_id)


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

    if not user or user["password"] != password:
        return jsonify({"error": "invalid username or password"}), 401

    token = create_access_token(identity=str(user["id"]))
    return jsonify({"access_token": token, "user": {"id": user["id"], "username": user["username"]}}), 200


# ---------------------------------------------------------------------------
# API Layer - Destinations
# ---------------------------------------------------------------------------
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

    return jsonify(destinations), 200


@app.route("/destinations/<int:destination_id>", methods=["GET"])
def get_destination_by_id(destination_id):
    """Return a single destination's full details."""
    data = load_data()
    destination = next((d for d in data["destinations"] if d["id"] == destination_id), None)
    if not destination:
        return jsonify({"error": "destination not found"}), 404
    return jsonify(destination), 200


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

    return jsonify(recommended), 200


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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
