import json
import os
from typing import List, Optional
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Ha-Meem AI Surveillance API")

LOG_FILE = "logs/events.jsonl"

class SurveillanceEvent(BaseModel):
    timestamp: str
    camera_id: str
    track_id: int
    identity: Optional[str] = None
    score: float
    event: str
    snapshot: Optional[str] = None

def read_events(limit: int = 200, last_n: Optional[int] = None) -> List[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    
    events = []
    try:
        with open(LOG_FILE, "r") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
    except Exception as e:
        print(f"Error reading log file: {e}")
        return []

    # If last_n is specified, take from the end
    if last_n:
        return events[-last_n:]
    
    # Otherwise return up to limit
    return events[:limit]

@app.get("/")
def root():
    return {
        "message": "Welcome to Ha-Meem AI Surveillance API",
        "endpoints": {
            "health": "/health",
            "latest_events": "/events/latest",
            "all_events": "/events",
            "documentation": "/docs"
        }
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/events/latest", response_model=List[SurveillanceEvent])
def get_latest_events():
    """Returns the last 20 surveillance events."""
    return read_events(last_n=20)

@app.get("/events", response_model=List[SurveillanceEvent])
def get_all_events(limit: int = 200):
    """Returns all events, capped at the provided limit (default 200)."""
    return read_events(limit=limit)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
