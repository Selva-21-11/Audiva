# interview_agent.py
import os
import json
import logging
import asyncio
import aiohttp
from dotenv import load_dotenv

from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions, JobContext
from livekit.plugins import (
    google,            # <--- if you use Google Gemini realtime plugin
    deepgram,          # STT
    cartesia,          # TTS
    silero,            # VAD
    noise_cancellation,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("interview-agent")

# -------------------- CONFIG (edit these env vars) --------------------
LLM_EVAL_URL = os.environ.get("LLM_EVAL_URL")   # an HTTP proxy that returns JSON (silent eval)
LLM_EVAL_KEY = os.environ.get("LLM_EVAL_KEY")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
# ---------------------------------------------------------------------

async def call_llm_for_eval(prompt: str) -> str:
    """
    Silent structured evaluation call. Must return a JSON string like:
    {"scores": {"React": 4, "Testing": 3}, "rationale": "short note"}
    Replace with your LLM provider or internal proxy.
    """
    if not LLM_EVAL_URL:
        # demo fallback (no external call)
        return json.dumps({"scores": {}, "rationale": "LLM_EVAL_URL not configured (demo fallback)"})

    headers = {"Authorization": f"Bearer {LLM_EVAL_KEY}"} if LLM_EVAL_KEY else {}
    async with aiohttp.ClientSession() as session:
        async with session.post(LLM_EVAL_URL, json={"prompt": prompt}, headers=headers, timeout=30) as resp:
            text = await resp.text()
            return text

def _is_affirmative(text: str) -> bool:
    if not text: 
        return False
    t = text.lower()
    for a in ("yes", "yeah", "yup", "sure", "ok", "okay", "i agree", "go ahead", "fine", "yes please"):
        if a in t:
            return True
    return False

def _needs_example(user_text: str) -> bool:
    """
    Heuristic: if user uses 'know', 'familiar', 'used', or answer is very short,
    ask for a concrete example to dig deeper.
    """
    if not user_text:
        return True
    t = user_text.lower()
    short = len(t.split()) < 12
    braggy = any(p in t for p in ("i know", "i'm familiar", "i used to", "i learned"))
    return short or braggy

# -------------------- Strong interviewer persona (system prompt) --------------------
STRICT_INTERVIEWER_INSTRUCTIONS = (
    "You are a professional, strict interviewer. You MUST behave only as an interviewer. "
    "Never give personal opinions, never role-play anything other than an interviewer, and never summarize "
    "the candidate's answer aloud except in a brief final wrap-up. Speak in a neutral, concise, polite, "
    "and probing interviewer tone (1-3 sentences per spoken turn). "
    "Always ask open-ended questions that require examples, ask clarifying follow-ups when answers are short or vague, "
    "and wait for the candidate to finish speaking before you respond. "
    "Do not read back internal evaluations or JSON to the candidate. When evaluating, use an internal silent call (not spoken)."
)
# -------------------------------------------------------------------------------

class InterviewAgent(Agent):
    def __init__(self, metadata: dict):
        # Set a very explicit persona at agent construction too (redundant but helps)
        super().__init__(instructions=STRICT_INTERVIEWER_INSTRUCTIONS)
        self.meta = metadata or {}
        self.role = self.meta.get("role", "")
        self.jd = self.meta.get("jd", "")
        self.skills = self.meta.get("skills", [])
        self.backend_host = self.meta.get("backend_host")
        self.question_count = 0
        self.max_questions = 6         # internal limit (keeps interview finite)
        self.stage = "idle"            # idle -> awaiting_consent -> asking -> finished
        self.last_question_text = None

    async def on_enter(self) -> None:
        """
        Called once when the agent session starts in the room.
        Greet the candidate and ask for consent — then wait for their reply.
        """
        greet = (
            f"Hello — this is the interview for the position: {self.role}. "
            "I will ask a few questions about your experience. "
            "Is it okay if I record this interview for evaluation purposes? A simple yes or no will do."
        )
        self.stage = "awaiting_consent"
        # Use generate_reply to speak; the framework will wait for the user's turn afterwards.
        await self.session.generate_reply(instructions=greet)

    async def ask_one_question(self):
        """
        Ask one focused, open-ended question tailored to the role/skills.
        Keep the prompt explicit so the LLM generates *one* conversational question.
        """
        self.question_count += 1
        q_prompt = (
            f"As an interviewer for the role '{self.role}', ask exactly one clear, conversational, open-ended question "
            f"that targets these skills: {', '.join(self.skills) if self.skills else 'general experience'}. "
            "Keep the question natural and request a specific example or past experience."
        )
        await self.session.generate_reply(instructions=q_prompt)
        # Save last question prompt (we will store & evaluate later)
        self.last_question_text = q_prompt
        self.stage = "asking"

    async def on_user_turn_completed(self, turn_ctx, new_message):
        """
        Called after the user finishes speaking (turn ends).
        This is the *only* place we evaluate the user's speech and decide follow-ups or next question.
        """
        user_text = ""
        try:
            user_text = getattr(new_message, "text_content", "") or ""
        except Exception:
            user_text = ""

        logger.info("on_user_turn_completed (stage=%s) -> user: %s", self.stage, user_text[:200])

        # 1) Consent flow
        if self.stage == "awaiting_consent":
            if _is_affirmative(user_text):
                # permission granted → ask the first question
                self.stage = "asking"
                await asyncio.sleep(0.15)    # tiny breathing room
                await self.ask_one_question()
            else:
                # ask once more for a clear yes/no; be concise and neutral (remain interviewer)
                await self.session.generate_reply(instructions="Understood. Please answer yes or no — may I record this conversation for evaluation?")
            return

        # 2) Main Q/A flow
        if self.stage == "asking":
            # If candidate gave a short / vague answer, ask for a concrete example (stay in asking stage)
            if _needs_example(user_text) and self.question_count < self.max_questions:
                # Follow-up prompt — brief, specific request for example
                follow = (
                    "Could you provide a specific example or walk me through a recent situation where you used that skill?"
                )
                await self.session.generate_reply(instructions=follow)
                # remain in asking stage; next on_user_turn_completed will contain that example
                return

            # 3) Silent structured evaluation (do not speak this)
            eval_prompt = (
                f"Please evaluate the following candidate answer for role: {self.role}\n\n"
                f"Job description: {self.jd}\n\n"
                f"Question: {self.last_question_text}\n\n"
                f"Answer: {user_text}\n\n"
                "Return a JSON object ONLY with: {\"scores\": {<skill_name>:1-5,...}, \"rationale\":\"brief text\"}."
            )
            try:
                eval_text = await call_llm_for_eval(eval_prompt)
                eval_json = json.loads(eval_text)
            except Exception as e:
                logger.warning("eval parse failed, saving raw text: %s", e)
                eval_json = {"scores": {}, "rationale": eval_text}

            # persist evaluation to backend (silent)
            if self.backend_host:
                save_payload = {
                    "room": self.session.room.name if self.session.room else None,
                    "question_id": self.question_count,
                    "question_text": self.last_question_text,
                    "answer_text": user_text,
                    "scores": eval_json.get("scores", {}),
                    "rationale": eval_json.get("rationale", "")
                }
                try:
                    async with aiohttp.ClientSession() as s:
                        await s.post(f"{self.backend_host}/save_evaluation", json=save_payload, timeout=10)
                except Exception as e:
                    logger.exception("Failed to persist evaluation: %s", e)

            # 4) Decide next step: follow-up already handled earlier; otherwise proceed to next
            if self.question_count >= self.max_questions:
                # final spoken wrap-up (interviewer style, short)
                await self.session.generate_reply(instructions=(
                    "Thank you. That concludes our questions. Briefly: we appreciate your time — "
                    "we will review and be in touch about next steps. Goodbye."
                ))
                self.stage = "finished"
                await asyncio.sleep(0.3)
                try:
                    await self.session.close()
                except Exception:
                    pass
                return

            # Ask next primary question
            await asyncio.sleep(0.2)   # short pause to avoid overlap
            await self.ask_one_question()
            return

        # other stages: ignore
        logger.debug("Unhandled stage in on_user_turn_completed: %s", self.stage)

# -------------------- entrypoint --------------------
async def entrypoint(ctx: agents.JobContext):
    """
    Agent entrypoint called by workers. It:
      - connects the agent to the LiveKit room,
      - creates an AgentSession wired to your STT/LLM/TTS plugins,
      - starts the session; the agent's on_enter() will run and then on_user_turn_completed will control flow.
    """
    await ctx.connect()
    logger.info("Agent dispatched. Job metadata: %s", ctx.job.metadata)

    try:
        metadata = json.loads(ctx.job.metadata or "{}")
    except Exception:
        metadata = {}

    # -------------------- Configure the media/LLM plugins --------------------
    # IMPORTANT: Replace llm=... and tts=... with your actual plugin and credentials
    # Make the LLM *strict* by passing the strict persona in `instructions` and setting a low temperature.
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en-US", api_key=DEEPGRAM_API_KEY),
        llm=google.beta.realtime.RealtimeModel(
            model="gemini-2.0-flash-exp",
            voice="Puck",
            temperature=0.5,                     # lower temperature = less creative, more focused responses
            instructions=STRICT_INTERVIEWER_INSTRUCTIONS,
        ),
        tts=cartesia.TTS(model="sonic-2", voice="f786b574-daa5-4673-aa0c-cbe3e8534c02"),
        vad=silero.VAD.load(),
        turn_detection="vad",
        min_endpointing_delay=0.6,   # tune higher if agent interrupts candidate; increase if cutting off
    )
    # ---------------------------------------------------------------------------

    agent = InterviewAgent(metadata)
    await session.start(room=ctx.room, agent=agent,
                        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()))
    # on_enter will run; session will now handle the rest via callbacks (on_user_turn_completed etc.)

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="interview-agent"))
