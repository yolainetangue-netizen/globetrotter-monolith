# GlobeTrotter Travel Assistant — Phase 1: The Monolith

A single Flask server handling all requests, with data stored in a JSON file
(`data.json`). This is the monolithic baseline for the GlobeTrotter capstone
project — no database, no microservices, single point of failure by design.

## Architecture

```
Client (HTML/CSS/JS) --> Flask API Layer --> Business Logic --> data.json
```

- **API Layer**: REST endpoints for registration, login, destination search,
  itinerary management (see below).
- **Business Logic**: recommendation matching based on user preferences.
- **Data Access**: `load_data()` / `save_data()` read and write `data.json`.
- **Authentication**: JWT via Flask-JWT-Extended.

## Endpoints

| Method | Path              | Auth | Description                          |
|--------|-------------------|------|---------------------------------------|
| POST   | `/register`       | No   | Register a new user                   |
| POST   | `/login`          | No   | Authenticate, returns a JWT token     |
| GET    | `/destinations`   | No   | Search destinations (`?q=` `&tag=`)   |
| GET    | `/recommendations`| Yes  | Personalized recommendations          |
| POST   | `/itineraries`    | Yes  | Create a new itinerary                |
| GET    | `/itineraries`    | Yes  | List the current user's itineraries   |

## Running locally

```bash
cd globetrotter-monolith
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

Demo account: username `demo`, password `demo123`.

## Testing the API directly (optional, e.g. with curl or Postman)

```bash
# Register
curl -X POST http://127.0.0.1:5000/register \
  -H "Content-Type: application/json" \
  -d '{"username":"sheilla","password":"pass123","preferences":["beach"]}'

# Login
curl -X POST http://127.0.0.1:5000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"sheilla","password":"pass123"}'
# -> copy the "access_token" from the response

# Recommendations (replace TOKEN)
curl http://127.0.0.1:5000/recommendations \
  -H "Authorization: Bearer TOKEN"
```

## Deploying to Render (free tier)

1. Push this folder to a GitHub repository.
2. Go to https://render.com, sign in with GitHub.
3. Click **New +** → **Web Service**, select your repo.
4. Configure:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
5. Add an environment variable `JWT_SECRET_KEY` with any secret value.
6. Click **Create Web Service**. Render will build and deploy automatically,
   giving you a public URL like `https://globetrotter-monolith.onrender.com`.

Note: Render's free tier uses an ephemeral filesystem — `data.json` resets
whenever the service restarts/redeploys. That's fine for a Phase 1 demo, but
mention it explicitly during your defense as one of the "Challenges of the
Monolith" (Data Storage row in the course slides).

## Known limitations (by design — this is Phase 1)

- No real database (matches the "Data Storage" challenge in the slides).
- Single server, no horizontal scaling.
- Any bug can crash the whole app (no service isolation).
- Passwords are stored in plain text in `data.json` — acceptable only for
  this teaching exercise, never in production.
