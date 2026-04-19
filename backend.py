import asyncio
import re
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

# Google Cloud Logging
try:
    from google.cloud import logging as cloud_logging
    CLOUD_LOGGING_AVAILABLE = True
except ImportError:
    CLOUD_LOGGING_AVAILABLE = False
    print("WARNING: google-cloud-logging not installed or credentials unavailable.")

# Firebase Admin SDK
try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("WARNING: firebase-admin not installed or credentials unavailable.")

# Ensure environment variables are loaded securely
load_dotenv()

# Configure the Gemini API client
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("WARNING: GEMINI_API_KEY not found in environment or .env file.")

# Initialise the client once at module load (None if key is missing)
gemini_client = genai.Client(api_key=api_key) if api_key else None

# Google Cloud Logging client (initialized in lifespan)
cloud_logging_client = None
cloud_logger = None

# Firebase Admin SDK (initialized in lifespan)
firebase_initialized = False

# Global in-memory state
venue_state = {}
latest_ai_command = None


# --- Pydantic schema matching Gemini's required structured output ---
class AICommand(BaseModel):
    alert: str
    action: str
    dispatch: str


class TelemetryPayload(BaseModel):
    node_id: str
    node_type: str
    acoustic_density: int
    rf_attenuation: float
    timestamp: str

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, v: str) -> str:
        """Enforce safe node IDs: letters/underscores only, no injection risk."""
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", v):
            raise ValueError(
                "node_id must start with a letter or underscore and contain "
                "only alphanumeric characters and underscores."
            )
        return v


async def venue_monitor_task():
    """Background task to run every 10 seconds and check for surges."""
    global latest_ai_command
    while True:
        await asyncio.sleep(10)

        # Guard: skip if Gemini client is not initialised
        if not gemini_client:
            print("Skipping AI orchestration: GEMINI_API_KEY is not configured.")
            continue

        surge_detected = False
        surging_nodes = []

        # Scan all connected nodes
        for node_id, data in venue_state.items():
            if data["acoustic_density"] > 90 and data["rf_attenuation"] > 0.85:
                surge_detected = True
                surging_nodes.append(node_id)

        if surge_detected:
            print(f"Surge detected at nodes: {surging_nodes}. Contacting AI Orchestrator...")
            
            # Log surge detection to Google Cloud Logging
            if cloud_logger:
                try:
                    log_entry = {
                        "severity": "WARNING",
                        "message": "Surge detected in venue",
                        "node_ids": surging_nodes,
                        "total_active_nodes": len(venue_state),
                        "timestamp": str(asyncio.get_event_loop().time()),
                    }
                    cloud_logger.log_struct(log_entry)
                except Exception as e:
                    print(f"Failed to log surge to Cloud Logging: {e}")
            
            try:
                # Use the new google-genai SDK with typed structured output
                response = await gemini_client.aio.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=(
                        f"Nodes experiencing a severe surge: {surging_nodes}. "
                        f"Total active nodes in venue: {len(venue_state)}. "
                        f"Please provide your JSON routing command immediately."
                    ),
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "You are a Venue Traffic Controller for a massive sporting event. "
                            "Analyze the given venue telemetry. Determine the best operational "
                            "routing command to resolve crowd surges. Output strictly valid JSON "
                            "with exactly three keys: 'alert', 'action', and 'dispatch'."
                        ),
                        response_mime_type="application/json",
                        response_schema=AICommand,
                    ),
                )

                try:
                    # Validate with Pydantic — ensures the schema is always correct
                    ai_response = AICommand.model_validate_json(response.text)
                    latest_ai_command = ai_response.model_dump()
                    print(f"AI Orchestrator Command issued: alert={ai_response.alert!r}")
                    
                    # Log AI command to Google Cloud Logging
                    if cloud_logger:
                        try:
                            log_entry = {
                                "severity": "INFO",
                                "message": "AI command issued for surge response",
                                "node_ids": surging_nodes,
                                "command": latest_ai_command,
                                "timestamp": str(asyncio.get_event_loop().time()),
                            }
                            cloud_logger.log_struct(log_entry)
                        except Exception as e:
                            print(f"Failed to log AI command to Cloud Logging: {e}")
                except Exception:
                    print("Failed to validate AI response schema:", response.text)

            except Exception as e:
                print(f"Error calling Gemini API: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize Google Cloud Logging if available
    global cloud_logging_client, cloud_logger
    if CLOUD_LOGGING_AVAILABLE:
        try:
            cloud_logging_client = cloud_logging.Client()
            cloud_logger = cloud_logging_client.logger("aeronode-app")
            print("Google Cloud Logging initialized successfully.")
        except Exception as e:
            print(f"WARNING: Could not initialize Google Cloud Logging: {e}")
            print("Continuing without Cloud Logging.")
            cloud_logging_client = None
            cloud_logger = None
    
    # Startup: initialize Firebase Admin SDK if available
    global firebase_initialized
    if FIREBASE_AVAILABLE:
        try:
            firebase_admin.initialize_app(
                options={
                    "databaseURL": os.getenv(
                        "FIREBASE_DATABASE_URL",
                        "https://aeronode-default-rtdb.firebaseio.com"
                    )
                }
            )
            firebase_initialized = True
            print("Firebase Admin SDK initialized successfully.")
        except Exception as e:
            print(f"WARNING: Could not initialize Firebase Admin SDK: {e}")
            print("Continuing without Firebase Realtime Database sync.")
            firebase_initialized = False
    
    # Startup: start the proactive monitoring task
    task = asyncio.create_task(venue_monitor_task())
    yield
    # Shutdown: cancel the task cleanly
    task.cancel()


app = FastAPI(lifespan=lifespan)

# --- Security: CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --- Security: HTTP Security Headers Middleware ---
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


@app.post("/api/telemetry")
async def receive_telemetry(payload: TelemetryPayload):
    """Endpoint for edge physical hardware simulators to POST telemetry metrics."""
    venue_state[payload.node_id] = payload.model_dump()
    return {"status": "success"}


@app.get("/api/state")
async def get_state():
    """Endpoint to return the full global backend state."""
    active_command_str = None
    if latest_ai_command:
        active_command_str = (
            f"ALERT: {latest_ai_command.get('alert', 'N/A')} | "
            f"ACTION: {latest_ai_command.get('action', 'N/A')} | "
            f"DISPATCH: {latest_ai_command.get('dispatch', 'N/A')}"
        )

    state_response = {
        "nodes": venue_state,
        "active_command": active_command_str,
    }
    
    # Sync state snapshot to Firebase Realtime Database if initialized
    if firebase_initialized:
        try:
            firebase_db.reference("/venue/state").set(state_response)
        except Exception as e:
            # Silently continue on Firebase sync failure
            pass
    
    return state_response


@app.get("/")
async def serve_dashboard():
    """Serve the telemetry dashboard."""
    return FileResponse("index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
