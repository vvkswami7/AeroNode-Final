# AeroNode Command Center

> Real-time venue telemetry dashboard with AI-powered crowd-surge routing for large sporting events.

![System Status](https://img.shields.io/badge/status-online-brightgreen)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135.3-009688)
![Gemini](https://img.shields.io/badge/Gemini-2.0--flash-orange)
![Firebase](https://img.shields.io/badge/Firebase-Realtime%20DB-yellow)
![Google Cloud](https://img.shields.io/badge/Google%20Cloud-Logging-4285F4)

---

## Overview

AeroNode is an edge-computing telemetry platform that monitors crowd density and RF signal attenuation across a large sporting venue in real time. When sensors detect a potential crowd surge, an AI orchestrator powered by **Google Gemini 2.0 Flash** automatically generates operational routing commands to safely redirect foot traffic.

The system is composed of three components:

- **Edge Simulator** — 50 concurrent async nodes (gates, food stalls, bathrooms) that POST telemetry to the backend every 2–5 seconds
- **FastAPI Backend** — ingests telemetry, runs a proactive surge-detection loop, calls Gemini for AI routing commands, and syncs state to Firebase
- **Dashboard Frontend** — real-time command center that listens to Firebase Realtime Database for live updates, with HTTP polling fallback

---

## Architecture

```
Edge Nodes (50x)
    │
    │  POST /api/telemetry
    ▼
FastAPI Backend
    ├── Surge Detection Loop (every 10s)
    │       └── Gemini 2.0 Flash (AI routing commands)
    ├── Google Cloud Logging (structured audit trail)
    └── Firebase Realtime DB sync (/venue/state)
            │
            │  onValue() listener
            ▼
    Dashboard Frontend (index.html)
            ├── Firebase Realtime Database (primary)
            ├── Google Analytics 4 (usage tracking)
            ├── Google Fonts (Inter)
            └── HTTP Polling fallback (every 2s)
```

---

## Google Services Integration

| Service | Usage |
|---|---|
| **Gemini 2.0 Flash** | AI crowd-surge routing commands with structured JSON output |
| **Firebase Realtime Database** | Live state sync from backend to frontend via `onValue()` listener |
| **Firebase Admin SDK** | Server-side push to `/venue/state` on every state request |
| **Google Cloud Logging** | Structured audit logs for surge detections and AI commands |
| **Google Analytics 4** | Frontend usage tracking (`G-24CWEXEPTK`) |
| **Google Fonts** | Inter typeface loaded via `fonts.googleapis.com` |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn |
| AI | Google Gemini 2.0 Flash (`google-genai`) |
| Realtime DB | Firebase Realtime Database (`firebase-admin`) |
| Observability | Google Cloud Logging (`google-cloud-logging`) |
| Frontend | Vanilla JS, Tailwind CSS, Firebase JS SDK v12 |
| Edge Simulation | Python `asyncio`, `aiohttp` |
| Testing | pytest, pytest-asyncio, FastAPI TestClient |

---

## Project Structure

```
AeroNode/
├── backend.py          # FastAPI app — telemetry ingestion, AI orchestration
├── edge_simulator.py   # 50-node async telemetry simulator
├── index.html          # Real-time dashboard frontend
├── requirements.txt    # Python dependencies
├── start.sh            # Startup script (simulator + backend)
├── Dockerfile          # Container definition
├── conftest.py         # pytest configuration (ROS hook stub)
├── test_backend.py     # Integration tests
└── pytest.ini          # pytest settings
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- A `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com)
- (Optional) Firebase project with Realtime Database enabled
- (Optional) Google Cloud credentials for Cloud Logging

### Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd AeroNode

# Install dependencies
pip install -r requirements.txt

# Create environment file
cp .env.example .env
# Add your keys to .env
```

### Environment Variables

```env
GEMINI_API_KEY=your_gemini_api_key_here
FIREBASE_DATABASE_URL=https://your-project-default-rtdb.firebaseio.com
```

### Running Locally

```bash
# Start everything (simulator + backend)
bash start.sh

# Or run separately:
python edge_simulator.py &
uvicorn backend:app --host 0.0.0.0 --port 8080 --reload
```

Open your browser at `http://localhost:8080`

### Running with Docker

```bash
docker build -t aeronode .
docker run -p 8080:8080 --env-file .env aeronode
```

---

## API Reference

### `POST /api/telemetry`

Accepts telemetry from edge nodes.

```json
{
  "node_id": "gate_1",
  "node_type": "gate",
  "acoustic_density": 87,
  "rf_attenuation": 0.72,
  "timestamp": "2024-01-01T00:00:00+00:00"
}
```

**Validation rules:**
- `node_id` must match `^[a-zA-Z_][a-zA-Z0-9_]*$`
- `acoustic_density` must be an integer
- `rf_attenuation` must be a float

### `GET /api/state`

Returns current venue state and latest AI command.

```json
{
  "nodes": {
    "gate_1": { "acoustic_density": 87, "rf_attenuation": 0.72, ... }
  },
  "active_command": "ALERT: ... | ACTION: ... | DISPATCH: ..."
}
```

---

## Surge Detection Logic

A crowd surge is flagged when **both** conditions are met on a node:

```
acoustic_density > 90  AND  rf_attenuation > 0.85
```

When a surge is detected, the system:
1. Logs a `WARNING` entry to Google Cloud Logging
2. Calls Gemini 2.0 Flash with surging node IDs and total venue context
3. Validates the structured JSON response with Pydantic
4. Logs an `INFO` entry with the AI command to Google Cloud Logging
5. Stores the command in memory and syncs to Firebase Realtime DB

---

## Running Tests

```bash
pytest test_backend.py -v
```

Test coverage includes:
- `GET /api/state` — structure, defaults, empty state
- `POST /api/telemetry` — success path, persistence, node updates
- Input validation — missing fields, invalid node IDs, wrong data types

---

## Security

- Input validation on all telemetry fields via Pydantic
- `node_id` sanitized with strict regex to prevent injection
- HTTP security headers on all responses (`X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`)
- CORS configured via FastAPI middleware
- All Google service credentials loaded from environment variables, never hardcoded

---

## Graceful Degradation

All Google service integrations are wrapped in `try/except` blocks. The app runs fully on a free-tier unauthenticated server with no credentials — Google Cloud Logging and Firebase simply skip silently if credentials are absent. The frontend falls back to HTTP polling if the Firebase Realtime listener fails.

---

## License

MIT
