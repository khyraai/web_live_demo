"""Maya -- the Acme Realty inbound voice agent (LiveKit Agents worker).

Run it:
    python agent.py start          # register with LiveKit and take calls
    python agent.py console         # talk to Maya in your terminal (no phone)

Pipeline (cascade), tuned for ~700 ms-1.2 s perceived turn latency on one India VPS:
    Silero VAD -> Sarvam Saaras STT (codemix, 8 kHz) -> OpenAI gpt-4.1-mini
    -> Sarvam Bulbul TTS.

Language flow: a GreeterAgent greets in English and detects the caller's
language, then hands off to a per-language LangAgent that locks STT + TTS to
that language. See GreeterAgent.set_language for the (important) silent-swap fix.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

# --- TLS / cert guard (optional) --------------------------------------------
# On some minimal VPS images the system CA bundle is missing and Sarvam/OpenAI
# TLS handshakes fail. Pointing at certifi's bundle avoids that. Best-effort.
try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:  # pragma: no cover - purely defensive
    pass

from dotenv import load_dotenv

load_dotenv()

from livekit import agents
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    MetricsCollectedEvent,
    RunContext,
    WorkerOptions,
    function_tool,
    metrics,
)
from livekit.plugins import openai, sarvam, silero

from config import (
    AGENT_NAME,
    AUDIO_SAMPLE_RATE,
    BCP47,
    DEFAULT_DEMO_VOICE,
    DEFAULT_LANGUAGE,
    MAX_ENDPOINTING_DELAY,
    MAX_TOKENS,
    MIN_ENDPOINTING_DELAY,
    GROQ_LLM_MODEL,
    GROQ_TEMPERATURE,
    GROQ_API_KEY,
    OPENAI_API_KEY,
    OPENAI_LLM_MODEL,
    OPENAI_TEMPERATURE,
    SARVAM_API_KEY,
    SARVAM_STT_MODEL,
    SARVAM_TTS_MODEL,
    SARVAM_TTS_VOICE,
    SUPPORTED_LANGUAGES,
    VAD_MIN_SILENCE_S,
    VOICE_MAP,
    get_voice_name,
)
from prompts import (
    GREETINGS,
    HOT_PERSONA,
    STYLE_NOTES,
    build_demo_prompt,
    build_instructions,
    get_demo_greeting,
)
from tools import AppointmentTools

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voice-agent")

# Per-stage latency lands here as JSONL, one row per metric. The dashboard
# (dashboard/build_dashboard.py) reads this to colour-code each call.
METRICS_LOG = Path(__file__).parent / "logs" / "metrics.jsonl"

# Confirmation phrase spoken the moment we switch language, IN that language.
# These MUST exist for every supported language -- see set_language for why.
CONFIRMATIONS: dict[str, str] = {
    "en": "Perfect, we'll continue in English.",
    "hi": "ठीक है, अब हम हिंदी में बात करेंगे।",
    "ta": "சரி, இனி நாம் தமிழில் பேசுவோம்.",
    "te": "సరే, ఇప్పటి నుండి మనం తెలుగులో మాట్లాడుకుందాం.",
    "kn": "ಸರಿ, ಇನ್ನು ನಾವು ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡೋಣ.",
    "ml": "ശരി, ഇനി നമുക്ക് മലയാളത്തിൽ സംസാരിക്കാം.",
}


# --- pipeline wiring ---------------------------------------------------------
def _build_llm() -> openai.LLM:
    """Build the LLM instance using Groq if configured, otherwise standard OpenAI."""
    if GROQ_API_KEY and GROQ_API_KEY not in ("YOUR_GROQ_API_KEY", ""):
        return openai.LLM(
            model=GROQ_LLM_MODEL,
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            temperature=GROQ_TEMPERATURE,
            max_completion_tokens=MAX_TOKENS,
        )
    key = OPENAI_API_KEY if (OPENAI_API_KEY and OPENAI_API_KEY != "YOUR_OPENAI_API_KEY") else "placeholder-key"
    return openai.LLM(
        model=OPENAI_LLM_MODEL,
        api_key=key,
        temperature=OPENAI_TEMPERATURE,
        max_completion_tokens=MAX_TOKENS,
    )


def _build_session(language: str, voice: str = SARVAM_TTS_VOICE) -> AgentSession:
    """Wire the whole cascade for a starting language and return the session.

    Silero VAD + Sarvam STT/TTS locked to `language`, OpenAI/Groq LLM, Maya's tools,
    and tight endpointing. The session owns the tools and default pipeline;
    each LangAgent later overrides only STT + TTS to relock the language.
    """
    bcp47 = BCP47.get(language, "en-IN")
    return AgentSession(
        vad=silero.VAD.load(
            min_silence_duration=VAD_MIN_SILENCE_S,
            sample_rate=AUDIO_SAMPLE_RATE,
        ),
        stt=sarvam.STT(
            model=SARVAM_STT_MODEL,       # saaras:v3
            mode="codemix",               # keep English words spoken mid-sentence
            language=bcp47,
            sample_rate=AUDIO_SAMPLE_RATE,  # 16 kHz WebRTC / 8 kHz telephony
            api_key=SARVAM_API_KEY,
        ),
        llm=_build_llm(),
        tts=sarvam.TTS(
            model=SARVAM_TTS_MODEL,        # bulbul:v3
            target_language_code=bcp47,
            speaker=voice,
            api_key=SARVAM_API_KEY,
        ),
        tools=[],  # Disabled tools as requested
        min_endpointing_delay=MIN_ENDPOINTING_DELAY,  # 0.15 s
        max_endpointing_delay=MAX_ENDPOINTING_DELAY,  # 1.0 s
    )


# --- agents ------------------------------------------------------------------
GREETER_INSTRUCTIONS = (
    HOT_PERSONA
    + "\n\nYou are greeting the caller in English. Listen for the language they "
    "speak or ask for. The moment you know it, call the set_language tool with the "
    "code (en, hi, ta, te, kn, ml). Do not dive into property questions before the "
    "language is set."
)


class GreeterAgent(Agent):
    """Greets the caller in English and detects their language."""

    def __init__(self) -> None:
        super().__init__(instructions=GREETER_INSTRUCTIONS)

    @function_tool
    async def set_language(self, context: RunContext, language: str) -> None:
        """Switch the whole conversation to the caller's preferred language.

        Args:
            language: one of en, hi, ta, te, kn, ml.
        """
        code = language.strip().lower()
        if code not in SUPPORTED_LANGUAGES:
            # Don't swap on an unknown code -- tell the LLM so it can re-ask.
            return f"Language '{language}' is not supported. Supported: {', '.join(SUPPORTED_LANGUAGES)}."

        # ---------------------------------------------------------------------
        # WHY we speak BEFORE swapping (do NOT reorder):
        # session.update_agent() swaps the active agent SILENTLY -- the new
        # agent does NOT automatically say anything. If we swap first and expect
        # the new LangAgent to greet, the call goes to DEAD AIR. That was a real,
        # painful production bug. So we emit the confirmation on the CURRENT
        # session first, THEN swap.
        # ---------------------------------------------------------------------
        await context.session.say(CONFIRMATIONS[code])
        context.session.update_agent(LangAgent(code))
        # We already voiced the confirmation, so return nothing (no extra reply).
        return None


class LangAgent(Agent):
    """One agent parameterised by language code; STT + TTS locked to it."""

    def __init__(self, code: str) -> None:
        bcp47 = BCP47[code]
        super().__init__(
            instructions=build_instructions(code, STYLE_NOTES[code]),
            # Override the session's STT/TTS to relock the language for this agent.
            stt=sarvam.STT(
                model=SARVAM_STT_MODEL,
                mode="codemix",
                language=bcp47,
                sample_rate=AUDIO_SAMPLE_RATE,
                api_key=SARVAM_API_KEY,
            ),
            tts=sarvam.TTS(
                model=SARVAM_TTS_MODEL,
                target_language_code=bcp47,
                speaker=SARVAM_TTS_VOICE,
                api_key=SARVAM_API_KEY,
            ),
        )
        self.code = code


class DemoAgent(Agent):
    """Dynamic demo agent parameterised by system prompt, language code, and voice."""

    def __init__(self, instructions: str, code: str, voice: str) -> None:
        bcp47 = BCP47.get(code, "en-IN")
        super().__init__(
            instructions=instructions,
            stt=sarvam.STT(
                model=SARVAM_STT_MODEL,
                mode="codemix",
                language=bcp47,
                sample_rate=AUDIO_SAMPLE_RATE,
                api_key=SARVAM_API_KEY,
            ),
            tts=sarvam.TTS(
                model=SARVAM_TTS_MODEL,
                target_language_code=bcp47,
                speaker=voice,
                api_key=SARVAM_API_KEY,
            ),
        )
        self.code = code
        self.voice = voice


# --- metrics -> JSONL --------------------------------------------------------
def _make_metrics_handler(call_id: str):
    """Build a metrics_collected handler that logs per-stage latency as JSONL."""

    def _on_metrics(ev: MetricsCollectedEvent) -> None:
        m = ev.metrics
        # Pull the one latency number that matters per stage.
        if isinstance(m, metrics.EOUMetrics):
            row = {"stage": "eou", "seconds": m.end_of_utterance_delay, "speech_id": m.speech_id}
        elif isinstance(m, metrics.STTMetrics):
            row = {"stage": "stt", "seconds": m.duration}
        elif isinstance(m, metrics.LLMMetrics):
            row = {"stage": "llm_ttft", "seconds": m.ttft, "speech_id": m.speech_id}
        elif isinstance(m, metrics.TTSMetrics):
            row = {"stage": "tts_ttfb", "seconds": m.ttfb, "speech_id": m.speech_id}
        else:
            return

        row["call_id"] = call_id
        row["ts"] = time.time()
        try:
            METRICS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with METRICS_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:  # never let metrics logging break a live call
            log.exception("failed to write metrics row")
        metrics.log_metrics(m)  # also to the console log

    return _on_metrics


# --- entrypoint --------------------------------------------------------------
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    participant = None
    # In browser WebRTC sessions, wait for the participant to connect before speaking greeting
    if not ctx.is_fake_job:
        log.info("Agent connected to room %s. Waiting for participant...", ctx.room.name)
        participant = await ctx.wait_for_participant()
        log.info("Participant connected: identity=%s name=%s", participant.identity, participant.name)

    # Read configuration from metadata
    meta_str = ""
    # 1. Local session file (direct process communication)
    session_file = Path(__file__).parent / "data" / "sessions" / f"{ctx.room.name}.json"
    if session_file.exists():
        try:
            meta_str = session_file.read_text(encoding="utf-8")
            log.info("Loaded session configuration from local file %s: %s", session_file.name, meta_str)
        except Exception as file_err:
            log.warning("Could not read local session file %s: %s", session_file.name, file_err)

    # 2. LiveKit Job metadata
    if not meta_str and hasattr(ctx, "job") and getattr(ctx.job, "metadata", None):
        meta_str = ctx.job.metadata
        log.info("Loaded session configuration from job.metadata: %s", meta_str)

    # 3. LiveKit Participant metadata
    if not meta_str and participant and getattr(participant, "metadata", None):
        meta_str = participant.metadata
        log.info("Loaded session configuration from participant.metadata: %s", meta_str)

    # 4. LiveKit Room metadata
    if not meta_str and hasattr(ctx, "room") and getattr(ctx.room, "metadata", None):
        meta_str = ctx.room.metadata
        log.info("Loaded session configuration from room.metadata: %s", meta_str)

    role = "front_desk"
    domain = "dental_clinic"
    language = DEFAULT_LANGUAGE
    voice_id = "voice_4"

    if meta_str:
        try:
            m = json.loads(meta_str)
            role = m.get("role") or role
            domain = m.get("domain") or domain
            language = m.get("language") or language
            voice_id = m.get("voice_id") or voice_id
            log.info("Parsed configuration successfully: role=%s, domain=%s, language=%s, voice=%s", role, domain, language, voice_id)
        except Exception as parse_err:
            log.warning("Could not parse metadata '%s': %s", meta_str, parse_err)
    else:
        log.warning("No metadata found for room %s. Using default (%s/%s)", ctx.room.name, role, domain)

    lang_code = language.split("-")[0] if "-" in language else language
    if lang_code not in SUPPORTED_LANGUAGES:
        lang_code = "en"

    voice_speaker = VOICE_MAP.get(voice_id, DEFAULT_DEMO_VOICE)
    system_prompt = build_demo_prompt(role, domain)
    greeting = get_demo_greeting(role, domain)

    log.info(
        "Starting demo agent for room=%s: role=%s domain=%s lang=%s voice=%s(%s)",
        ctx.room.name, role, domain, lang_code, voice_id, voice_speaker,
    )

    session = _build_session(lang_code, voice=voice_speaker)
    session.on("metrics_collected", _make_metrics_handler(ctx.room.name))

    await session.start(agent=DemoAgent(system_prompt, lang_code, voice_speaker), room=ctx.room)
    await session.say(greeting)


if __name__ == "__main__":
    agents.cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.getenv("AGENT_NAME", "maya"),
        )
    )
