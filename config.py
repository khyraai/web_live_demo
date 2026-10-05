"""Central configuration for the voice-agent-starter-kit.

Everything the agent pipeline needs is read from environment variables here and
exposed as plain, typed module-level constants. Import from this module instead
of calling os.getenv() all over the codebase, so there is exactly one place that
maps env -> value and one place to change a default.

Defaults mirror `.env.example`. No secrets live in this file; missing secrets
simply fall back to obvious placeholders so the module still imports.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Load a local .env if present. In production the values come from the systemd
# EnvironmentFile instead, so this is a no-op there.
load_dotenv()


# --- LiveKit -----------------------------------------------------------------
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://your-project.livekit.cloud")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "YOUR_LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "YOUR_LIVEKIT_API_SECRET")
SIP_URI = os.getenv("SIP_URI", "<your-project-id>.sip.livekit.cloud:5060")


# --- Sarvam AI (STT + TTS) ---------------------------------------------------
# The plugin reads SARVAM_API_KEY from the environment itself; we surface it here
# only so a missing key fails loudly and early rather than deep in the audio loop.
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "YOUR_SARVAM_API_KEY")
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v3")
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
# Sarvam's TTS constructor calls this the "speaker"; the env var is *_VOICE.
SARVAM_TTS_VOICE = os.getenv("SARVAM_TTS_VOICE", "simran")


# --- LLM Provider (Groq / OpenAI) -------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "llama-3.1-8b-instant")
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.3"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4.1-mini")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))

# Hard cap on reply length. Short replies = lower TTS/LLM latency.
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "140"))


# --- Agent behaviour ---------------------------------------------------------
AGENT_NAME = os.getenv("AGENT_NAME", "maya")
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")
# Silero VAD minimum silence before end-of-utterance. Stored as ms in the env
# (matching .env.example) and converted to seconds for the plugin.
VAD_MIN_SILENCE_MS = int(os.getenv("VAD_MIN_SILENCE_MS", "150"))
VAD_MIN_SILENCE_S = VAD_MIN_SILENCE_MS / 1000.0

# Endpointing window (how long to wait for the user to resume before treating
# the turn as finished). Tuned tight for snappy turns.
MIN_ENDPOINTING_DELAY = float(os.getenv("MIN_ENDPOINTING_DELAY", "0.15"))
MAX_ENDPOINTING_DELAY = float(os.getenv("MAX_ENDPOINTING_DELAY", "1.0"))

# Audio sample rate. WebRTC defaults to wideband 16 kHz for crisp microphone audio.
# Can be set to 8000 for legacy telephony if needed.
AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))


# --- Web Demo Server ---------------------------------------------------------
WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", "8080"))


# --- Telephony / transfer ----------------------------------------------------
DEFAULT_TRANSFER_NUMBER = os.getenv("DEFAULT_TRANSFER_NUMBER", "+91XXXXXXXXXX")


# --- Language map ------------------------------------------------------------
# Every supported language -> its BCP-47 tag. Both Sarvam STT (`language`) and
# Sarvam TTS (`target_language_code`) are locked to one of these per call.
BCP47: dict[str, str] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
}
SUPPORTED_LANGUAGES: list[str] = list(BCP47.keys())


# --- Demo WebSocket Config (Website Live Demo) --------------------------------
DEMO_WS_PORT = int(os.getenv("DEMO_WS_PORT", "8000"))

# Map frontend voice_id values to actual Sarvam TTS (bulbul:v3) speaker names.
# Available speakers: meera, pavithra, maitreyi, simran, arvind, amol, karthik,
# abhishek, arjun, amartya.
VOICE_MAP: dict[str, str] = {
    "voice_1": "meera",       # Professional Female
    "voice_2": "simran",      # Warm Female
    "voice_3": "pavithra",    # Direct Female
    "voice_4": "maitreyi",    # Balanced Female
    "voice_5": "amartya",     # Calm Female (fallback)
    "voice_6": "arvind",      # Executive Male
    "voice_7": "amol",        # Warm Male
    "voice_8": "karthik",     # Neutral Male
    "voice_9": "abhishek",    # Authoritative Male
    "voice_10": "arjun",      # Conversational Male
}
DEFAULT_DEMO_VOICE = "simran"

# Display names for each demo voice
VOICE_NAMES: dict[str, str] = {
    "voice_1": "Priya",
    "voice_2": "Kavya",
    "voice_3": "Neha",
    "voice_4": "Simran",
    "voice_5": "Pooja",
    "voice_6": "Rahul",
    "voice_7": "Rohan",
    "voice_8": "Aditya",
    "voice_9": "Amit",
    "voice_10": "Ratan",
}


def get_voice_name(voice_id: str) -> str:
    """Return the display persona name for a voice ID (e.g. voice_2 -> Kavya)."""
    if voice_id in VOICE_NAMES:
        return VOICE_NAMES[voice_id]
    for v_id, name in VOICE_NAMES.items():
        if voice_id.strip().lower() == name.lower():
            return name
    return "Kavya"

# BCP-47 language codes for the demo. Supports codes with or without -IN suffix.
DEMO_BCP47: dict[str, str] = {
    "en": "en-IN",
    "en-IN": "en-IN",
    "en-US": "en-IN",
    "en-GB": "en-IN",
    "hi": "hi-IN",
    "hi-IN": "hi-IN",
    "kn": "kn-IN",
    "kn-IN": "kn-IN",
    "ta": "ta-IN",
    "ta-IN": "ta-IN",
    "te": "te-IN",
    "te-IN": "te-IN",
    "ml": "ml-IN",
    "ml-IN": "ml-IN",
    "bn": "bn-IN",
    "bn-IN": "bn-IN",
    "gu": "gu-IN",
    "gu-IN": "gu-IN",
    "mr": "mr-IN",
    "mr-IN": "mr-IN",
    "pa": "pa-IN",
    "pa-IN": "pa-IN",
    "od": "od-IN",
    "od-IN": "od-IN",
}

