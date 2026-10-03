"""Web backend server for the LiveKit Voice AI Demo.

Provides:
- Secure, short-lived LiveKit access token generation (/api/token)
- Automatic room creation and agent dispatch routing
- Explicit session termination and resource cleanup (/api/session/end)
- Health check and environment verification (/api/health)
- Static file serving for the standalone browser demo interface
"""

from __future__ import annotations

import logging
import base64
import io
import json as _json
import os
import uuid
import wave
from datetime import timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from livekit.api import (
    AccessToken,
    CreateAgentDispatchRequest,
    DeleteRoomRequest,
    LiveKitAPI,
    RoomAgentDispatch,
    RoomConfiguration,
    VideoGrants,
)

from config import (
    AGENT_NAME,
    AUDIO_SAMPLE_RATE,
    DEFAULT_DEMO_VOICE,
    DEFAULT_LANGUAGE,
    DEMO_BCP47,
    GROQ_API_KEY,
    GROQ_LLM_MODEL,
    GROQ_TEMPERATURE,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_URL,
    MAX_TOKENS,
    OPENAI_API_KEY,
    OPENAI_LLM_MODEL,
    OPENAI_TEMPERATURE,
    SARVAM_API_KEY,
    SARVAM_STT_MODEL,
    SARVAM_TTS_MODEL,
    VOICE_MAP,
    WEB_SERVER_HOST,
    WEB_SERVER_PORT,
)
from prompts import build_demo_prompt, get_demo_greeting

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voice-demo-server")

app = FastAPI(
    title="LiveKit Voice AI Demo Server",
    description="Backend API and web host for browser-based LiveKit voice AI demo",
    version="1.0.0",
)

# Enable CORS so the demo endpoint can be called from website embeddings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"


# --- Request/Response Models -------------------------------------------------
class TokenRequest(BaseModel):
    room_name: Optional[str] = None
    participant_name: Optional[str] = None
    participant_identity: Optional[str] = None


class TokenResponse(BaseModel):
    serverUrl: str
    roomName: str
    participantToken: str
    participantIdentity: str
    participantName: str
    agentName: str


class EndSessionRequest(BaseModel):
    room_name: str


class EndSessionResponse(BaseModel):
    status: str
    room_name: str


# --- Helper Functions --------------------------------------------------------
def _check_credentials() -> tuple[bool, str]:
    """Verify if LiveKit credentials are configured."""
    if not LIVEKIT_URL or "your-project" in LIVEKIT_URL:
        return False, "LIVEKIT_URL is not set or using default placeholder."
    if not LIVEKIT_API_KEY or "YOUR_" in LIVEKIT_API_KEY:
        return False, "LIVEKIT_API_KEY is not set or using default placeholder."
    if not LIVEKIT_API_SECRET or "YOUR_" in LIVEKIT_API_SECRET:
        return False, "LIVEKIT_API_SECRET is not set or using default placeholder."
    return True, "OK"


# --- API Routes --------------------------------------------------------------
@app.get("/api/health")
async def health_check():
    """Health check endpoint indicating server and configuration status."""
    configured, msg = _check_credentials()
    return {
        "status": "healthy",
        "livekit_configured": configured,
        "livekit_url": LIVEKIT_URL,
        "agent_name": AGENT_NAME,
        "default_language": DEFAULT_LANGUAGE,
        "audio_sample_rate": AUDIO_SAMPLE_RATE,
        "message": msg,
    }


@app.post("/api/token", response_model=TokenResponse)
async def create_token(req: TokenRequest = TokenRequest()):
    """Generate a scoped, short-lived LiveKit access token and dispatch agent."""
    configured, msg = _check_credentials()
    if not configured:
        log.warning("Token request rejected: %s", msg)
        raise HTTPException(
            status_code=500,
            detail=f"LiveKit credentials not configured in .env: {msg}",
        )

    # Generate isolated session IDs
    room_name = req.room_name or f"web-demo-{uuid.uuid4().hex[:8]}"
    participant_identity = req.participant_identity or f"user-{uuid.uuid4().hex[:8]}"
    participant_name = req.participant_name or "Web Visitor"

    log.info(
        "Creating token for room=%s identity=%s name=%s",
        room_name,
        participant_identity,
        participant_name,
    )

    try:
        # Build short-lived token with permissions strictly for microphone & audio playback
        token = (
            AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity(participant_identity)
            .with_name(participant_name)
            .with_grants(
                VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .with_room_config(
                RoomConfiguration(
                    agents=[RoomAgentDispatch(agent_name=AGENT_NAME)]
                )
            )
            .with_ttl(timedelta(minutes=15))
            .to_jwt()
        )

        # Proactively trigger agent dispatch via LiveKit API (best effort for server setups)
        try:
            lkapi = LiveKitAPI(
                url=LIVEKIT_URL,
                api_key=LIVEKIT_API_KEY,
                api_secret=LIVEKIT_API_SECRET,
            )
            try:
                await lkapi.agent_dispatch.create_dispatch(
                    CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room_name)
                )
                log.info("Agent dispatch requested for room %s", room_name)
            finally:
                await lkapi.aclose()
        except Exception as dispatch_err:
            # Token embedded RoomConfiguration handles dispatch on room creation;
            # API dispatch is a best-effort proactive complement.
            log.info(
                "Direct API agent dispatch notice: %s (room_config in token will handle dispatch)",
                dispatch_err,
            )

        return TokenResponse(
            serverUrl=LIVEKIT_URL,
            roomName=room_name,
            participantToken=token,
            participantIdentity=participant_identity,
            participantName=participant_name,
            agentName=AGENT_NAME,
        )
    except Exception as e:
        log.exception("Failed to generate token")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate access token: {str(e)}"
        )


@app.post("/api/session/end", response_model=EndSessionResponse)
async def end_session(req: EndSessionRequest):
    """End a voice session and clean up room resources."""
    configured, _ = _check_credentials()
    if not configured:
        return EndSessionResponse(status="ended_locally", room_name=req.room_name)

    log.info("Ending session for room: %s", req.room_name)
    try:
        lkapi = LiveKitAPI(
            url=LIVEKIT_URL,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
        )
        try:
            await lkapi.room.delete_room(DeleteRoomRequest(room=req.room_name))
            log.info("Deleted LiveKit room: %s", req.room_name)
        finally:
            await lkapi.aclose()
        return EndSessionResponse(status="ended", room_name=req.room_name)
    except Exception as e:
        log.warning("Could not delete room %s on LiveKit server: %s", req.room_name, e)
        return EndSessionResponse(status="ended_with_warning", room_name=req.room_name)


# --- Static Files / Frontend Hosting -----------------------------------------
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    """Serve the demo frontend."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Voice AI Demo Server running. Static files directory not found."}


# --- WebSocket Demo Endpoint (Website Live Demo) ----------------------------
# Direct STT → LLM → TTS pipeline over WebSocket.  No LiveKit room needed.
# The frontend (React, on a separate domain) connects here.

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

# ~250 ms of PCM Int16 mono @ 16 kHz = 8000 bytes per chunk
_DEMO_CHUNK_SIZE = 8000
# Minimum audio length to bother with STT (~100 ms)
_DEMO_MIN_AUDIO_BYTES = 3200


def _pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap raw PCM Int16 data in a standard RIFF WAV header."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _wav_to_pcm(wav_data: bytes) -> bytes:
    """Strip the WAV header and return raw PCM frames."""
    buf = io.BytesIO(wav_data)
    with wave.open(buf, "rb") as wf:
        return wf.readframes(wf.getnframes())


async def _demo_stt(audio_pcm: bytes, language: str) -> str:
    """Call Sarvam STT (saaras:v3) with raw PCM audio and return the transcript."""
    wav_data = _pcm_to_wav(audio_pcm)
    bcp47 = DEMO_BCP47.get(language, "en-IN")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": SARVAM_API_KEY},
            data={
                "language_code": bcp47,
                "model": SARVAM_STT_MODEL,
                "with_timestamps": "false",
            },
            files={"file": ("audio.wav", wav_data, "audio/wav")},
        )
        resp.raise_for_status()
        return resp.json().get("transcript", "")


async def _demo_llm(system_prompt: str, conversation: list[dict]) -> str:
    """Call the LLM (Groq or OpenAI) and return the assistant reply."""
    messages = [{"role": "system", "content": system_prompt}] + conversation

    if GROQ_API_KEY and GROQ_API_KEY not in ("YOUR_GROQ_API_KEY", ""):
        base_url = "https://api.groq.com/openai/v1"
        api_key = GROQ_API_KEY
        model = GROQ_LLM_MODEL
        temperature = GROQ_TEMPERATURE
    else:
        base_url = "https://api.openai.com/v1"
        api_key = OPENAI_API_KEY
        model = OPENAI_LLM_MODEL
        temperature = OPENAI_TEMPERATURE

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": MAX_TOKENS,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _demo_tts(text: str, voice: str, language: str) -> bytes:
    """Call Sarvam TTS (bulbul:v3) and return raw PCM Int16 @ 16 kHz."""
    bcp47 = DEMO_BCP47.get(language, "en-IN")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            SARVAM_TTS_URL,
            headers={
                "api-subscription-key": SARVAM_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "inputs": [text],
                "target_language_code": bcp47,
                "speaker": voice,
                "model": SARVAM_TTS_MODEL,
                "enable_preprocessing": True,
            },
        )
        resp.raise_for_status()
        audio_b64 = resp.json()["audios"][0]
        wav_bytes = base64.b64decode(audio_b64)
        return _wav_to_pcm(wav_bytes)


async def _send_audio_response(
    ws: WebSocket,
    text: str,
    voice: str,
    language: str,
) -> None:
    """Generate TTS for *text* and stream it back over the WebSocket."""
    await ws.send_text(_json.dumps({"type": "response_text", "text": text}))
    try:
        tts_pcm = await _demo_tts(text, voice, language)
        for i in range(0, len(tts_pcm), _DEMO_CHUNK_SIZE):
            await ws.send_bytes(tts_pcm[i : i + _DEMO_CHUNK_SIZE])
    except Exception as tts_err:
        log.warning("TTS generation failed: %s", tts_err)
    await ws.send_text(_json.dumps({"type": "audio_end"}))


@app.websocket("/ws")
async def websocket_demo(ws: WebSocket):
    """WebSocket endpoint for the Khyra website Live Demo.

    Protocol:
        Frontend → Backend:
            {"type": "init", "role": "...", "domain": "...", "language": "...", "voice_id": "..."}
            Binary PCM Int16 frames (16 kHz mono)
            {"type": "audio_end"}

        Backend → Frontend:
            {"type": "ready"}
            {"type": "response_text", "text": "..."}
            Binary PCM Int16 frames (16 kHz mono)
            {"type": "audio_end"}
            {"type": "error", "message": "..."}
    """
    await ws.accept()
    log.info("WebSocket demo client connected")

    try:
        # ---- 1. Wait for init message ----------------------------------------
        init_raw = await ws.receive_text()
        init_data = _json.loads(init_raw)
        if init_data.get("type") != "init":
            await ws.send_text(
                _json.dumps({"type": "error", "message": "Expected init message"})
            )
            await ws.close()
            return

        role = init_data.get("role", "front_desk")
        domain = init_data.get("domain", "dental_clinic")
        language = init_data.get("language", "en")
        voice_id = init_data.get("voice_id", "voice_2")

        # ---- 2. Build session config -----------------------------------------
        system_prompt = build_demo_prompt(role, domain)
        voice = VOICE_MAP.get(voice_id, DEFAULT_DEMO_VOICE)
        greeting_text = get_demo_greeting(role, domain)

        log.info(
            "Demo session: role=%s domain=%s lang=%s voice=%s(%s)",
            role, domain, language, voice_id, voice,
        )

        # ---- 3. Send ready ---------------------------------------------------
        await ws.send_text(_json.dumps({"type": "ready"}))

        # ---- 4. Send opening greeting ----------------------------------------
        conversation: list[dict] = []
        await _send_audio_response(ws, greeting_text, voice, language)
        conversation.append({"role": "assistant", "content": greeting_text})

        # ---- 5. Main conversation loop ---------------------------------------
        audio_buffer = bytearray()

        while True:
            msg = await ws.receive()

            if msg["type"] == "websocket.disconnect":
                break

            # Binary audio frame
            if "bytes" in msg and msg["bytes"]:
                audio_buffer.extend(msg["bytes"])
                continue

            # JSON text message
            if "text" in msg and msg["text"]:
                data = _json.loads(msg["text"])

                if data.get("type") != "audio_end":
                    continue

                # --- Process buffered audio -----------------------------------
                if len(audio_buffer) < _DEMO_MIN_AUDIO_BYTES:
                    audio_buffer.clear()
                    continue

                pcm_data = bytes(audio_buffer)
                audio_buffer.clear()

                try:
                    # STT
                    transcript = await _demo_stt(pcm_data, language)
                    if not transcript or not transcript.strip():
                        log.info("Empty STT transcript, skipping")
                        await ws.send_text(_json.dumps({"type": "audio_end"}))
                        continue

                    log.info("STT transcript: %s", transcript)
                    conversation.append({"role": "user", "content": transcript})

                    # LLM
                    reply = await _demo_llm(system_prompt, conversation)
                    log.info("LLM reply: %s", reply)
                    conversation.append({"role": "assistant", "content": reply})

                    # TTS → stream back
                    await _send_audio_response(ws, reply, voice, language)

                    # Keep conversation history manageable (last 20 turns)
                    if len(conversation) > 20:
                        conversation = conversation[-20:]

                except Exception as pipeline_err:
                    log.exception("Demo pipeline error")
                    await ws.send_text(
                        _json.dumps({"type": "error", "message": str(pipeline_err)})
                    )

    except WebSocketDisconnect:
        log.info("WebSocket demo client disconnected")
    except Exception:
        log.exception("WebSocket demo error")
        try:
            await ws.send_text(
                _json.dumps({"type": "error", "message": "Internal server error"})
            )
        except Exception:
            pass
    finally:
        log.info("WebSocket demo session ended")


if __name__ == "__main__":
    import uvicorn

    log.info("Starting Web Demo Server on %s:%d", WEB_SERVER_HOST, WEB_SERVER_PORT)
    uvicorn.run("server:app", host=WEB_SERVER_HOST, port=WEB_SERVER_PORT, reload=False)
