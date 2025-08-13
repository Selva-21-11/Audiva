# server.py
import os, json, uuid
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from livekit import api

load_dotenv()

LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "https://your-livekit-host")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
BACKEND_HOST = os.environ.get("BACKEND_HOST", "http://localhost:8000")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class StartInterviewReq(BaseModel):
    role: str
    jd: str
    skills: List[str]

class Evaluation(BaseModel):
    room: Optional[str]
    question_id: Optional[int]
    question_text: Optional[str]
    answer_text: Optional[str]
    scores: dict
    rationale: Optional[str]

# demo in-memory store (replace with DB in prod)
EVALUATIONS = []

@app.post("/start_interview")
async def start_interview(req: StartInterviewReq):
    try:
        # generate unique room & identity
        room = f"interview-{uuid.uuid4().hex[:8]}"
        identity = f"candidate-{uuid.uuid4().hex[:6]}"

        # create access token for candidate
        at = api.AccessToken(api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
        token = (
            at.with_identity(identity)
              .with_name(identity)
              .with_grants(api.VideoGrants(room_join=True, room=room))
              .to_jwt()
        )

        # prepare metadata (concise)
        metadata = {
            "role": req.role,
            "jd": req.jd,
            "skills": req.skills,
            "backend_host": BACKEND_HOST
        }

        # explicit dispatch to agent_name="interview-agent"
        lkapi = api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
        dispatch_req = api.CreateAgentDispatchRequest(
            agent_name="interview-agent",
            room=room,
            metadata=json.dumps(metadata),
        )
        await lkapi.agent_dispatch.create_dispatch(dispatch_req)

        return {"token": token, "url": LIVEKIT_URL, "room": room, "identity": identity}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/save_evaluation")
def save_evaluation(payload: Evaluation):
    entry = payload.dict()
    EVALUATIONS.append(entry)
    return {"status": "ok", "saved": entry}


@app.get("/evaluations")
def get_evaluations():
    return {"evaluations": EVALUATIONS}
