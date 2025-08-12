# server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from livekit import api
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "https://your-livekit-host")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # your React app origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TokenRequest(BaseModel):
    room: str
    identity: str  # participant identity

@app.post("/session")
def create_session(req: TokenRequest):
    try:
        at = api.AccessToken(api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
        token = (
            at.with_identity(req.identity)
              .with_name(req.identity)
              .with_grants(api.VideoGrants(room_join=True, room=req.room))
              .to_jwt()
        )
        return {"token": token, "url": LIVEKIT_URL}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
