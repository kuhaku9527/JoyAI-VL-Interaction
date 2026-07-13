"""Jarvis Mode State Machine.

Wake word (KWS) → streaming ASR → LLM → TTS → exit words → goodbye.

Usage (in server.py or background task):
    from jarvis_mode import JarvisStateMachine

    jarvis = JarvisStateMachine(...)
    asyncio.create_task(jarvis.run())

    # Feed audio from WebRTC callback
    async for pcm_chunk in mic_frames:
        await jarvis.feed_audio(pcm_chunk)
"""
from __future__ import annotations

import asyncio
import os
import json
import logging
import math
import time
import wave
from array import array
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import AsyncIterator, Callable, NoReturn, Optional

logger = logging.getLogger("joyai.jarvis")


# ============================================================================
# Configuration
# ============================================================================

EXIT_WORDS = {"行", "明白", "了解", "ok", "好的", "知道了", "谢谢", "感谢"}
"""Words that signal "I’m done talking" — treated as end-of-conversation signal."""

_GARBAGE_PUNCT_ONLY = {
    "\u3002", "\u3001", "\uff01", "\uff1f", "\uff1a", "\uff1b",
    "\u00b7", "\u2026", "\u2014", "\uff5e",
    "`", "~", "!", "?", ",", ".", ":", ";", "'", "-", "/", "\\",
    "(", ")", "[", "]", "{", "}", "<", ">",
    "\u0022", "\u0027", "*", "&", "#", "%", "@", "^", "_", "+", "=",
    " ",
}

def _is_garbage_text(text):
    """True when an ASR utterance is too noisy to forward to the LLM."""
    if not text:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    if "\ufffd" in stripped:
        return True
    if any(ord(c) < 0x20 for c in stripped):
        return True
    if len(stripped) <= 1:
        return True
    if all(c in _GARBAGE_PUNCT_ONLY for c in stripped):
        return True
    return False







def _load_default_llm_system_prompt() -> str:
    """Read the BT-7274 persona from prompts/bt-7274.txt.

    Falls back to a minimal "stay in character" reminder if the file is
    missing or unreadable so the runtime never hard-fails.
    """
    repo_root = Path(__file__).resolve().parents[4]
    candidate = repo_root / "prompts" / "bt-7274.txt"
    try:
        text = candidate.read_text(encoding="utf-8").strip()
    except Exception:
        text = ""
    if text:
        return text
    return (
        "You are BT-7274, a Pilot's tactical AI assistant. "
        "Stay in character at all times."
    )


@dataclass
class JarvisConfig:
    """Runtime knobs for the Jarvis state machine."""

    # KWS — 默认用自训 v4 模型 (bt-en, 53 段正样本, 200 段负样本)

    # 甜蜜点参数: score=10, th=0.25; trailing_blanks=1; max_active_paths=10

    # sherpa-onnx 直跑: FAR 15.5% / recall 75.5%; JarvisKWS 包装层(100ms chunk): FAR 2.0% / recall 49.0%

    # (详见 services/scripts/test_jarvis_kws_e2e.py, 2026-07-10 实测)
    wake_word: str = "bt"
    kws_model_dir: str = "D:/AI/models/sherpa-onnx/models/kws/bt-en"
    kws_num_threads: int = 1
    kws_keywords_score: float = 10.0
    """Boost score per keyword token (sherpa-onnx KeywordSpotter 调优).
    社区默认 1.0 不够; v4 训练后 joiner 信号被 blank 压制, 需要强 boost."""
    kws_keywords_threshold: float = 0.25
    """Acoustic probability threshold to fire keyword."""
    kws_num_trailing_blanks: int = 1
    """Trailing blank frames required after keyword match."""
    kws_max_active_paths: int = 10
    """Beam search width (community default 4 不够, 用 10 提高 recall)."""

    # ASR
    asr_model_dir: str = "D:/AI/models/sherpa-onnx/models/asr/streaming-paraformer-bilingual-zh-en"
    asr_num_threads: int = 2

    # Event audio
    # Resolved at runtime in __post_init__ to an absolute path based on
    # this file's location (so the webui does not depend on cwd).
    events_dir: str = ""
    wake_wav: str = "wake.wav"
    goodbye_wav: str = "goodbye.wav"

    # Hybrid wake confirmation: KWS fires cheaply, ASR confirms within timeout
    asr_confirm_timeout_s: float = 1.2
    """Max seconds to wait in WAIT_ASR_CONFIRM for ASR text containing a confirm pattern."""
    asr_confirm_patterns: tuple = ("bt", "BT", "B T", "b t")
    """Lower-case / case-sensitive tokens that, if seen in ASR text, promote the wake."""

    # KWS diagnostics. These do not wake Jarvis; they make KWS misses observable.
    kws_shadow_asr_enabled: bool = True
    """Run ASR in KWS_LISTENING for diagnostics only; logs text when KWS misses."""
    kws_shadow_log_interval_s: float = 0.75
    kws_capture_enabled: bool = True
    kws_capture_dir: str = "D:/AI/data/kws/mic_captures"
    kws_capture_window_s: float = 3.0
    kws_capture_min_interval_s: float = 4.0
    kws_capture_peak_threshold: float = 0.035
    """Save rolling mic windows above this peak so missed BT samples can retrain KWS."""
    kws_fresh_window_probe_enabled: bool = True
    """On live KWS miss, re-run KWS over a clean rolling PCM window."""
    kws_fresh_window_probe_interval_s: float = 0.5
    kws_fresh_window_min_s: float = 1.0
    kws_fresh_window_direct_wake: bool = True
    """Trust fresh-window KWS hits for wake during recall testing."""
    error_wav: str = "error.wav"

    # Timing
    silence_before_kws_reset_s: float = 5.0
    """Seconds of silence before resetting KWS state (avoids false re-triggers)."""

    # Audio format
    sample_rate: int = 16000

    # TTS (HTTP) — text -> PCM16 via voice_clone_api
    tts_api_url: str = "http://127.0.0.1:8985/v1/synthesize"  # voice_clone_api FastAPI
    tts_voice_id: str = "minimax_man_33333"  # dashboard-cloned BT-7274 voice (2026-07-11); override via JARVIS_TTS_VOICE_ID env
    
    # LLM (OpenAI-compatible HTTP) — llama-server 7060
    # v3.37 single-LLM-gateway: voice path goes through webinfer, NOT
    # directly to llama-server. Default base is the OpenAI-compatible
    # adapter; per-media-type sub-paths are kept explicit so callers
    # can swap a different gateway without code changes.
    llm_api_url: str = "http://127.0.0.1:8070/v1"
    llm_text_path: str = "/text/chat"
    llm_multimodal_path: str = "/chat/completions"
    llm_model: str = "joyai-vl-interaction-preview-iq4_nl-imat.gguf"
    llm_system_prompt: str = ""  # populated by __post_init__ from prompts/bt-7274.txt

    @classmethod
    def from_env(cls) -> "JarvisConfig":
        """Build a JarvisConfig with env overrides on the KWS / LLM / TTS paths.

        Env overrides (see doc/adr/0002-kws-config-env.md):
          JARVIS_KWS_MODEL_DIR         (str)   default: bt-en folder
          JARVIS_KWS_SCORE             (float) default 10.0  (FAR/recall balance)
          JARVIS_KWS_THRESHOLD         (float) default 0.25
          JARVIS_KWS_TRAILING_BLANKS   (int)   default 1
          JARVIS_KWS_MAX_ACTIVE_PATHS  (int)   default 10
          JARVIS_LLM_API_URL           (str)
          JARVIS_LLM_MODEL             (str)
          JARVIS_TTS_API_URL           (str)
          JARVIS_TTS_VOICE_ID          (str)
          JARVIS_EVENTS_DIR            (str)
          JARVIS_KWS_SHADOW_ASR        (bool)  default true (diagnostic only)
          JARVIS_KWS_CAPTURE           (bool)  default true
          JARVIS_KWS_CAPTURE_DIR       (str)
          JARVIS_KWS_CAPTURE_WINDOW_S  (float)
          JARVIS_KWS_CAPTURE_INTERVAL_S(float)
          JARVIS_KWS_CAPTURE_PEAK      (float)
          JARVIS_KWS_FRESH_PROBE       (bool)
          JARVIS_KWS_FRESH_PROBE_INTERVAL_S (float)
          JARVIS_KWS_FRESH_PROBE_MIN_S (float)
          JARVIS_KWS_FRESH_DIRECT_WAKE (bool)
        Invalid float/int values fall back to defaults and log a WARNING so
        config typos surface instead of crashing the webui at boot.
        """

        def _get_str(name: str, default: str) -> str:
            v = os.environ.get(name)
            return v if v and v.strip() else default

        def _get_float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None or not raw.strip():
                return default
            try:
                return float(raw)
            except ValueError:
                logger.warning(
                    "%s=%r is not a float; falling back to default %s",
                    name, raw, default,
                )
                return default

        def _get_int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None or not raw.strip():
                return default
            try:
                return int(raw)
            except ValueError:
                logger.warning(
                    "%s=%r is not an int; falling back to default %s",
                    name, raw, default,
                )
                return default

        def _get_bool(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None or not raw.strip():
                return default
            value = raw.strip().lower()
            if value in {"1", "true", "yes", "on"}:
                return True
            if value in {"0", "false", "no", "off"}:
                return False
            logger.warning(
                "%s=%r is not a bool; falling back to default %s",
                name, raw, default,
            )
            return default

        return cls(
            kws_model_dir=_get_str("JARVIS_KWS_MODEL_DIR", cls.kws_model_dir),
            kws_keywords_score=_get_float("JARVIS_KWS_SCORE", cls.kws_keywords_score),
            kws_keywords_threshold=_get_float("JARVIS_KWS_THRESHOLD", cls.kws_keywords_threshold),
            kws_num_trailing_blanks=_get_int("JARVIS_KWS_TRAILING_BLANKS", cls.kws_num_trailing_blanks),
            kws_max_active_paths=_get_int("JARVIS_KWS_MAX_ACTIVE_PATHS", cls.kws_max_active_paths),
            kws_shadow_asr_enabled=_get_bool("JARVIS_KWS_SHADOW_ASR", cls.kws_shadow_asr_enabled),
            kws_capture_enabled=_get_bool("JARVIS_KWS_CAPTURE", cls.kws_capture_enabled),
            kws_capture_dir=_get_str("JARVIS_KWS_CAPTURE_DIR", cls.kws_capture_dir),
            kws_capture_window_s=_get_float("JARVIS_KWS_CAPTURE_WINDOW_S", cls.kws_capture_window_s),
            kws_capture_min_interval_s=_get_float("JARVIS_KWS_CAPTURE_INTERVAL_S", cls.kws_capture_min_interval_s),
            kws_capture_peak_threshold=_get_float("JARVIS_KWS_CAPTURE_PEAK", cls.kws_capture_peak_threshold),
            kws_fresh_window_probe_enabled=_get_bool("JARVIS_KWS_FRESH_PROBE", cls.kws_fresh_window_probe_enabled),
            kws_fresh_window_probe_interval_s=_get_float("JARVIS_KWS_FRESH_PROBE_INTERVAL_S", cls.kws_fresh_window_probe_interval_s),
            kws_fresh_window_min_s=_get_float("JARVIS_KWS_FRESH_PROBE_MIN_S", cls.kws_fresh_window_min_s),
            kws_fresh_window_direct_wake=_get_bool("JARVIS_KWS_FRESH_DIRECT_WAKE", cls.kws_fresh_window_direct_wake),
            llm_api_url=_get_str("JARVIS_LLM_API_URL", cls.llm_api_url),
            llm_model=_get_str("JARVIS_LLM_MODEL", cls.llm_model),
            llm_text_path=_get_str("JARVIS_LLM_TEXT_PATH", cls.llm_text_path),
            llm_multimodal_path=_get_str(
                "JARVIS_LLM_MULTIMODAL_PATH", cls.llm_multimodal_path
            ),
            tts_api_url=_get_str("JARVIS_TTS_API_URL", cls.tts_api_url),
            tts_voice_id=_get_str("JARVIS_TTS_VOICE_ID", cls.tts_voice_id),
            events_dir=_get_str("JARVIS_EVENTS_DIR", cls.events_dir),
        )
    def __post_init__(self) -> None:
        # (a) Lazy-load the BT-7274 persona prompt from prompts/bt-7274.txt
        #     unless the caller already supplied one explicitly.
        if not self.llm_system_prompt:
            self.llm_system_prompt = _load_default_llm_system_prompt()
        # (b) Resolve `events_dir` to an absolute path based on this
        #     file's location so the webui (which may have a different
        #     cwd) can still find prompts/bt/events/*.wav.
        if not self.events_dir:
            here = Path(__file__).resolve()
            # .../services/webui/src/joy_interaction_webui/jarvis_mode.py
            # repo_root = parents[4]
            repo_root = here.parents[4]
            self.events_dir = str(repo_root / "prompts" / "bt" / "events")


# ============================================================================
# State Machine
# ============================================================================

class JarvisState(Enum):
    KWS_LISTENING = auto()    # Waiting for wake word, KWS running
    WAKE_DETECTED = auto()    # Wake word heard, playing wake.wav
    DIALOG_ACTIVE = auto()    # Full duplex: ASR streaming + TTS
    TTS_PAUSED = auto()       # Interrupt: user started speaking during TTS
    EXIT_DETECTED = auto()    # Exit word detected, playing goodbye.wav
    ERROR = auto()            # Unrecoverable error, log only
    WAIT_ASR_CONFIRM = auto()  # KWS fired; waiting for ASR to confirm wake pattern before playing wake.wav


@dataclass
class AsrPartial:
    """A partial or final ASR result."""
    text: str
    is_final: bool = False
    timestamp_ms: float = 0.0


class JarvisStateMachine:
    """Core state machine for BT-7274 Jarvis interaction.

    Lifecycle:
        KWS_LISTENING → WAKE_DETECTED → DIALOG_ACTIVE ⇄ TTS_PAUSED
              ↑                                              ↓
              └────────── EXIT_DETECTED ←────────────────────┘
    """

    def __init__(
        self,
        config: Optional[JarvisConfig] = None,
        *,
        on_wake: Optional[Callable[[], None]] = None,
        on_goodbye: Optional[Callable[[], None]] = None,
        on_asr_partial: Optional[Callable[[AsrPartial], None]] = None,
        on_user_utterance: Optional[Callable[[str], None]] = None,
        on_llm_response: Optional[Callable[[str, str], None]] = None,
        audio_output: Optional[Callable[[bytes, int], "asyncio.Future"]] = None,
    ):
        """
        audio_output: async callable(pcm_bytes, sample_rate) to play PCM
        via webui WebRTC audio output track. If None, falls back to
        local simpleaudio/sounddevice (if available) or sleep+log.
        """
        self.config = config or JarvisConfig()
        self.state = JarvisState.KWS_LISTENING

        # Callbacks
        self.on_wake = on_wake
        self.on_goodbye = on_goodbye
        self.on_asr_partial = on_asr_partial
        self.on_user_utterance = on_user_utterance
        self.on_llm_response = on_llm_response
        self.audio_output = audio_output  # async (pcm, sr) -> None

        # Engines (lazy init)
        self._kws = None
        self._asr = None
        self._asr_stream_active = False

        # State
        self._last_speech_time: float = 0.0
        self._current_asr_text: str = ""
        self._tts_task: Optional[asyncio.Task] = None
        # v3.37: when webinfer returns decision="delegation", route the
        # delegated question to BackgroundModelService.handle_foreground_response
        # so the same sub-agent fires for voice requests as for video.
        # Set by JarvisSessionManager.create_session; kept off the class
        # signature so tests can patch it without re-imports.
        self._background_service: Optional[object] = None
        self._consume_task: Optional[asyncio.Task] = None
        self._audio_queue: "asyncio.Queue[bytes]" = asyncio.Queue(maxsize=1024)
        self._tts_done = asyncio.Event()
        self._confirm_task: Optional[asyncio.Task] = None
        self._last_asr_match: str = ""

        # v3.24 conversation history for LLM context.
        # Bounded FIFO of (role, content) tuples; trimmed to max_turns.
        self._conv_history: deque[tuple[str, str]] = deque(maxlen=20)
        self._max_history_turns: int = 10

        # KWS diagnostics: rolling audio capture + ASR shadow text.  These are
        # deliberately diagnostic-only; they do not promote to wake by themselves.
        self._kws_capture_chunks: deque[bytes] = deque()
        self._kws_capture_bytes = 0
        self._last_kws_capture_at = 0.0
        self._kws_capture_seq = 0
        self._kws_shadow_asr_active = False
        self._kws_shadow_last_text = ""
        self._kws_shadow_last_log_at = 0.0
        self._kws_shadow_last_speech_at = 0.0
        self._last_kws_fresh_probe_at = 0.0

    # ------------------------------------------------------------------
    # Engine helpers
    # ------------------------------------------------------------------

    def _init_kws(self):
        if self._kws is not None:
            return
        from services.asr.jarvis.kws import JarvisKWS
        self._kws = JarvisKWS(
            model_dir=self.config.kws_model_dir,
            wake_word=self.config.wake_word,
            num_threads=self.config.kws_num_threads,
            keywords_score=self.config.kws_keywords_score,
            keywords_threshold=self.config.kws_keywords_threshold,
            num_trailing_blanks=self.config.kws_num_trailing_blanks,
            max_active_paths=self.config.kws_max_active_paths,
        )
        self._kws.start()

    def _init_asr(self):
        if self._asr is not None:
            return
        from services.asr.jarvis.asr import JarvisASR
        self._asr = JarvisASR(
            model_dir=self.config.asr_model_dir,
            num_threads=self.config.asr_num_threads,
        )

    async def prewarm_engines(self) -> None:
        """Load KWS and ASR models off the event loop.

        Critical for the hybrid wake path: ``_handle_kws`` runs in the
        same event-loop turn as ``_init_asr``. The ASR sherpa-onnx model
        takes ~1.2s to load on first use, which is the exact length of the
        ``asr_confirm_timeout_s`` confirm window — so any wake fired on a
        cold ASR instance is rejected before the engine can process a
        single audio chunk. Prewarming both engines at session start lets
        the post-wake confirm window do its real job.

        Both loads are blocking CPU-bound work, so we dispatch them
        through the default executor so the asyncio loop stays
        responsive to WebRTC and WebSocket traffic.
        """
        loop = asyncio.get_running_loop()

        def _load_kws() -> None:
            self._init_kws()

        def _load_asr() -> None:
            self._init_asr()

        logger.info(
            "Prewarming Jarvis engines (kws=%s asr=%s) — first load may take a few seconds",
            self.config.kws_model_dir, self.config.asr_model_dir,
        )
        # KWS is small (~10MB) and ASR is the heavy one (~200MB).
        # Run them sequentially in the executor; we cannot easily overlap
        # them without spinning up a second executor. In practice the
        # combined ~3-4s is acceptable as a one-shot cost when the user
        # clicks Listen.
        await loop.run_in_executor(None, _load_kws)
        await loop.run_in_executor(None, _load_asr)
        logger.info("Jarvis engines ready (kws=%s asr=%s)", self.config.wake_word, self.config.asr_model_dir)

    # ------------------------------------------------------------------
    # Audio feed loop (caller-driven)
    # ------------------------------------------------------------------

    async def feed_audio(self, pcm: bytes):
        """Main audio feed — drive the state machine from mic frames.

        Called from WebRTC audio callback (ideally every 100ms chunk).
        """
        await self._audio_queue.put(pcm)

    # ------------------------------------------------------------------
    # State machine runner
    # ------------------------------------------------------------------

    async def run(self):
        """Main state machine loop (asyncio background task)."""
        logger.info("Jarvis state machine started (state=KWS_LISTENING)")
        try:
            while True:
                pcm = await self._audio_queue.get()

                if self.state == JarvisState.KWS_LISTENING:
                    await self._handle_kws(pcm)

                elif self.state == JarvisState.WAKE_DETECTED:
                    # Block on wake.wav playback (transition handled internally)
                    logger.debug("WAKE_DETECTED: waiting for wake.wav")

                elif self.state == JarvisState.WAIT_ASR_CONFIRM:
                    await self._handle_wait_asr_confirm(pcm)

                elif self.state == JarvisState.DIALOG_ACTIVE:
                    await self._handle_dialog(pcm)

                elif self.state == JarvisState.TTS_PAUSED:
                    await self._handle_dialog(pcm)

                elif self.state == JarvisState.EXIT_DETECTED:
                    # Block on goodbye.wav playback
                    logger.debug("EXIT_DETECTED: waiting for goodbye.wav")
                    await asyncio.sleep(0.1)

                elif self.state == JarvisState.ERROR:
                    await asyncio.sleep(1.0)  # Don't busy-loop

        except asyncio.CancelledError:
            self._cleanup()
            raise

    # ------------------------------------------------------------------
    # Per-state handlers
    # ------------------------------------------------------------------

    async def _handle_kws(self, pcm: bytes):
        """KWS_LISTENING: feed KWS, check for wake word.

        On hit, drain stale audio and transition to WAIT_ASR_CONFIRM.
        The ASR will run for up to ``asr_confirm_timeout_s`` seconds; if its
        text matches one of ``asr_confirm_patterns`` we promote to
        WAKE_DETECTED and continue as before.  Otherwise the wake is
        treated as a false alarm and the session returns to KWS_LISTENING.
        """
        self._init_kws()
        peak, rms = self._observe_kws_diagnostics(pcm)

        if not self._kws.feed_audio(pcm):
            if await self._probe_kws_fresh_window(peak=peak, rms=rms):
                return
            self._feed_kws_shadow_asr(pcm, peak=peak, rms=rms)
            return

        # v3.19: do NOT drain. ASR needs to see (and re-transcribe) the wake
        # phrase itself to confirm. Drain+post-wake-audio-only was the v3.17
        # mistake — if the user only says "BT" and stops, the post-wake
        # queue is silence and ASR can never match. Instead: tap the wake
        # chunk inline to ASR so it has acoustic material immediately, and
        # let the bg loop's next iteration feed the queued wake-phrase tail.
        self._kws_shadow_asr_active = False
        self._kws_shadow_last_text = ""
        logger.info(
            "Wake word detected: '%s' (peak=%.3f rms=%.3f)",
            self.config.wake_word,
            peak,
            rms,
        )
        self._last_wake_peak = peak
        self._last_wake_rms = rms
        await self._transition_to(JarvisState.WAIT_ASR_CONFIRM)
        self._init_asr()
        self._asr.start()
        # Tap: feed the wake chunk to ASR *before* the queue consumer runs,
        # so ASR has the trailing syllable of the wake phrase to work with
        # even if the user stopped talking immediately after "BT".
        tap_text = ""
        try:
            tap_text = self._asr.feed_chunk(pcm) or ""
        except Exception as exc:
            logger.warning("ASR tap of wake chunk failed: %s", exc)
        self._asr_stream_active = True
        self._current_asr_text = tap_text
        self._last_asr_match = ""
        self._last_speech_time = time.time()
        # Schedule the confirm timeout (cancelled on promotion/rejection).
        self._confirm_task = asyncio.create_task(self._wait_asr_confirm_timeout())
        if self.on_wake:
            self.on_wake()
        # Fast-path: if the tap alone produced a confirm pattern, promote
        # without waiting for more audio. Otherwise let the bg loop drive.
        if tap_text and self._asr_confirm_match(tap_text):
            self._last_asr_match = tap_text
            logger.info("ASR confirmed wake via tap: %r", tap_text)
            await self._promote_from_confirm(matched_pattern=tap_text)

    def _pcm_stats(self, pcm: bytes) -> tuple[float, float]:
        """Return (peak, rms) for int16 mono PCM in the 0..1 range."""
        if not pcm:
            return 0.0, 0.0
        if len(pcm) % 2:
            pcm = pcm[:-1]
        samples = array("h")
        samples.frombytes(pcm)
        if not samples:
            return 0.0, 0.0
        peak = max(abs(s) for s in samples) / 32768.0
        square_sum = sum(float(s) * float(s) for s in samples)
        rms = math.sqrt(square_sum / len(samples)) / 32768.0
        return min(1.0, peak), min(1.0, rms)

    def _ensure_kws_diagnostic_state(self) -> None:
        """Initialize diagnostic fields for tests that construct via __new__."""
        if not hasattr(self, "_kws_capture_chunks"):
            self._kws_capture_chunks = deque()
        if not hasattr(self, "_kws_capture_bytes"):
            self._kws_capture_bytes = 0
        if not hasattr(self, "_last_kws_capture_at"):
            self._last_kws_capture_at = 0.0
        if not hasattr(self, "_kws_capture_seq"):
            self._kws_capture_seq = 0
        if not hasattr(self, "_kws_shadow_asr_active"):
            self._kws_shadow_asr_active = False
        if not hasattr(self, "_kws_shadow_last_text"):
            self._kws_shadow_last_text = ""
        if not hasattr(self, "_kws_shadow_last_log_at"):
            self._kws_shadow_last_log_at = 0.0
        if not hasattr(self, "_kws_shadow_last_speech_at"):
            self._kws_shadow_last_speech_at = 0.0
        if not hasattr(self, "_last_wake_peak"):
            self._last_wake_peak = 0.0
        if not hasattr(self, "_last_wake_rms"):
            self._last_wake_rms = 0.0
        if not hasattr(self, "_last_kws_fresh_probe_at"):
            self._last_kws_fresh_probe_at = 0.0

    def _observe_kws_diagnostics(self, pcm: bytes) -> tuple[float, float]:
        """Track live KWS input and save speech-like windows for analysis."""
        self._ensure_kws_diagnostic_state()
        peak, rms = self._pcm_stats(pcm)
        self._remember_kws_pcm(pcm)
        if not getattr(self.config, "kws_capture_enabled", True):
            return peak, rms
        if peak < max(0.0, self.config.kws_capture_peak_threshold):
            return peak, rms
        now = time.time()
        if (now - self._last_kws_capture_at) < max(0.5, self.config.kws_capture_min_interval_s):
            return peak, rms
        self._last_kws_capture_at = now
        self._write_kws_capture(peak=peak, rms=rms, ts=now)
        return peak, rms

    def _remember_kws_pcm(self, pcm: bytes) -> None:
        if not pcm:
            return
        max_bytes = int(max(0.2, self.config.kws_capture_window_s) * self.config.sample_rate * 2)
        self._kws_capture_chunks.append(bytes(pcm))
        self._kws_capture_bytes += len(pcm)
        while self._kws_capture_bytes > max_bytes and self._kws_capture_chunks:
            old = self._kws_capture_chunks.popleft()
            self._kws_capture_bytes -= len(old)

    def _write_kws_capture(self, *, peak: float, rms: float, ts: float) -> None:
        if not self._kws_capture_chunks:
            return
        try:
            out_dir = Path(self.config.kws_capture_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            self._kws_capture_seq += 1
            name = (
                f"kws_live_{int(ts * 1000)}_{self._kws_capture_seq:04d}"
                f"_peak{int(peak * 1000):03d}_rms{int(rms * 1000):03d}.wav"
            )
            out_path = out_dir / name
            pcm = b"".join(self._kws_capture_chunks)
            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.config.sample_rate)
                wf.writeframes(pcm)
            logger.info(
                "KWS diagnostic capture saved: %s (%.2fs peak=%.3f rms=%.3f)",
                out_path,
                len(pcm) / (self.config.sample_rate * 2),
                peak,
                rms,
            )
        except Exception as exc:
            logger.warning("KWS diagnostic capture failed: %s", exc)

    async def _probe_kws_fresh_window(self, *, peak: float, rms: float, bypass_min_s: bool = False) -> bool:
        """Fallback KWS probe using a clean stream over recent PCM.

        Real logs showed a rolling 3s capture could wake offline while the
        long-running live stream missed. This probe keeps the primary stream
        untouched and gives short wake words a clean stream boundary.
        """
        if not getattr(self.config, "kws_fresh_window_probe_enabled", True):
            return False
        now = time.time()
        interval = max(0.0, self.config.kws_fresh_window_probe_interval_s)
        if interval and (now - self._last_kws_fresh_probe_at) < interval:
            return False
        min_s = 0.1 if bypass_min_s else max(0.1, self.config.kws_fresh_window_min_s)
        if self._kws_capture_bytes < int(min_s * self.config.sample_rate * 2):
            return False
        self._last_kws_fresh_probe_at = now
        pcm = b"".join(self._kws_capture_chunks)
        try:
            hit = bool(self._kws.detect_in_pcm(pcm))
        except Exception as exc:
            logger.warning("Fresh-window KWS probe failed: %s", exc)
            return False
        if not hit:
            return False
        logger.info(
            "Wake word detected by fresh-window KWS probe (%.2fs peak=%.3f rms=%.3f)",
            len(pcm) / (self.config.sample_rate * 2),
            peak,
            rms,
        )
        if not getattr(self.config, "kws_fresh_window_direct_wake", True):
            return False
        await self._direct_wake_from_kws(source="fresh-window-kws")
        return True

    async def _direct_wake_from_kws(self, *, source: str) -> None:
        """Promote a trusted KWS hit without ASR confirm.

        Used only for fresh-window KWS recovery during recall testing. The
        normal streaming KWS path still goes through WAIT_ASR_CONFIRM.
        """
        self._kws_shadow_asr_active = False
        self._kws_shadow_last_text = ""
        await self._transition_to(JarvisState.WAKE_DETECTED)
        if self.on_wake:
            self.on_wake()
        logger.info("Direct wake from %s", source)
        await self._play_wake_wav()
        self._init_asr()
        self._asr.start()
        self._asr_stream_active = True
        self._current_asr_text = ""
        self._last_speech_time = time.time()
        await self._transition_to(JarvisState.DIALOG_ACTIVE)

    def _feed_kws_shadow_asr(self, pcm: bytes, *, peak: float, rms: float) -> None:
        """Run ASR in listening state so KWS misses have text evidence.

        This path logs only.  It intentionally does not wake Jarvis because the
        current production contract is still KWS-first; ASR promotion can be
        enabled later once live false-positive data is understood.
        """
        self._ensure_kws_diagnostic_state()
        if not getattr(self.config, "kws_shadow_asr_enabled", True):
            return
        now = time.time()
        speechy = peak >= max(0.0, self.config.kws_capture_peak_threshold * 0.7)
        if not speechy and not self._kws_shadow_asr_active:
            return
        try:
            self._init_asr()
            if not self._kws_shadow_asr_active:
                self._asr.start()
                self._kws_shadow_asr_active = True
                self._kws_shadow_last_text = ""
                logger.info("KWS shadow ASR started (diagnostic only, no wake promotion)")
            text = self._asr.feed_chunk(pcm) or ""
        except Exception as exc:
            logger.warning("KWS shadow ASR failed: %s", exc)
            self._kws_shadow_asr_active = False
            return

        if speechy:
            self._kws_shadow_last_speech_at = now
        if text and text != self._kws_shadow_last_text:
            if (now - self._kws_shadow_last_log_at) >= max(0.1, self.config.kws_shadow_log_interval_s):
                logger.info(
                    "KWS shadow ASR partial without KWS hit: %r (peak=%.3f rms=%.3f)",
                    text,
                    peak,
                    rms,
                )
                if self._asr_confirm_match(text):
                    logger.info(
                        "KWS MISS: shadow ASR saw wake pattern %r, but KWS did not fire",
                        text,
                    )
                self._kws_shadow_last_log_at = now
            self._kws_shadow_last_text = text

        if self._kws_shadow_asr_active and (now - self._kws_shadow_last_speech_at) > 2.0:
            if self._kws_shadow_last_text:
                logger.info("KWS shadow ASR segment ended: %r", self._kws_shadow_last_text)
            self._asr.stop()
            self._kws_shadow_asr_active = False
            self._kws_shadow_last_text = ""

    async def _wait_asr_confirm_timeout(self):
        """Reject the wake if ASR does not match within the configured timeout.

        v3.23: Before giving up, run a fresh-window KWS probe over the captured
        PCM as a recovery path. If a clean-stream KWS hit arrives here, it
        bypasses ASR confirm (which the streaming-paraformer model often fails
        on the two-syllable "bt" wake phrase). This recovers the wake when
        the live KWS fired but ASR partials never spelled "bt" within 1.2s.
        """
        try:
            await asyncio.sleep(self.config.asr_confirm_timeout_s)
        except asyncio.CancelledError:
            return
        if self.state != JarvisState.WAIT_ASR_CONFIRM:
            return  # already promoted or otherwise moved on
        # Recovery probe: fresh-stream KWS over captured audio.
        # Use peak/rms captured at wake time (more accurate) and bypass
        # the 1s min_s gate since we already have a trusted live KWS hit.
        peak = getattr(self, "_last_wake_peak", 0.0)
        rms = getattr(self, "_last_wake_rms", 0.0)
        if peak <= 0:
            byte_count = sum(len(c) for c in getattr(self, "_kws_capture_chunks", []))
            peak = 0.5 if byte_count > 0 else 0.0
            rms = peak
        if await self._probe_kws_fresh_window(peak=peak, rms=rms, bypass_min_s=True):
            logger.info(
                "WAIT_ASR_CONFIRM recovered via fresh-window KWS probe; "
                "direct wake without ASR confirm"
            )
            return
        logger.info(
            "WAIT_ASR_CONFIRM timeout (%.2fs) without ASR match; returning to KWS_LISTENING",
            self.config.asr_confirm_timeout_s,
        )
        await self._reset_to_kws()

    async def _promote_from_confirm(self, matched_pattern: str) -> None:
        """WAIT_ASR_CONFIRM -> WAKE_DETECTED -> DIALOG_ACTIVE after ASR match."""
        # Cancel timeout task so it does not race with promotion.
        if self._confirm_task and not self._confirm_task.done():
            self._confirm_task.cancel()
            try:
                await self._confirm_task
            except asyncio.CancelledError:
                pass
        await self._transition_to(JarvisState.WAKE_DETECTED)
        await self._play_wake_wav()
        # Drain audio accumulated during wake.wav so ASR starts clean.
        await self._drain_pending_audio(reason="post-wake-wav")
        await self._transition_to(JarvisState.DIALOG_ACTIVE)
        if self.on_wake:
            self.on_wake()

    def _asr_confirm_match(self, text: str) -> bool:
        """Return True if ASR text contains any of the confirm patterns.

        Lowercase substring match catches "bt" inside "hey bt" or
        "okay BT-7274".  The pattern list comes from config or defaults.
        """
        if not text:
            return False
        lowered = text.lower()
        patterns = getattr(getattr(self, "config", None), "asr_confirm_patterns", None) or ("bt", "BT", "B T", "b t")
        return any(p.lower() in lowered for p in patterns)

    async def _handle_wait_asr_confirm(self, pcm: bytes):
        """WAIT_ASR_CONFIRM: feed ASR, check each partial/final for confirm pattern."""
        if not self._asr_stream_active:
            return
        try:
            text = self._asr.feed_chunk(pcm)
        except Exception as exc:
            logger.warning("ASR feed_chunk failed during confirm: %s", exc)
            return
        # v3.19: log every ASR partial at info so production logs show
        # exactly what the model heard during the confirm window.
        # Costs ~6 lines per wake event; indispensable for diagnosing
        # false alarms vs miss-fires.
        logger.info("WAIT_ASR_CONFIRM ASR partial: %r", text)
        if not text:
            return
        self._current_asr_text = text
        if not self._asr_confirm_match(text):
            return
        self._last_asr_match = text
        logger.info("ASR confirmed wake via pattern match: %r", text)
        await self._promote_from_confirm(matched_pattern=text)

    async def _handle_dialog(self, pcm: bytes):
        """DIALOG_ACTIVE / TTS_PAUSED: stream ASR, check exit words, manage TTS."""
        if not self._asr_stream_active:
            return

        try:
            text = self._asr.feed_chunk(pcm)
        except Exception as e:
            logger.exception("ASR feed_chunk failed: %s", e)
            return
        now = time.time()

        if text and text != self._current_asr_text:
            # New speech (partial grew) — update accumulator and timer.
            # Log every change so an operator can see ASR's current
            # hypothesis evolving in out.log (no need to be black-box).
            logger.info("ASR partial: %r", text)
            self._current_asr_text = text
            self._last_speech_time = now
        # Stale path: text equal to _current_asr_text means ASR holds the last
        # partial on silence; timer stays untouched so the endpoint below fires.

        if text:
            # Emit partial
            partial = AsrPartial(text=text, is_final=False, timestamp_ms=now * 1000)
            if self.on_asr_partial:

                self.on_asr_partial(partial)

            # Check EXIT_WORDS on partial text (not waiting for final)
            stripped = text.strip().lower()
            if any(stripped.endswith(w) for w in EXIT_WORDS):
                logger.info("Exit word detected: %s", text)
                await self._transition_to(JarvisState.EXIT_DETECTED)
                await self._stop_tts()
                await self._play_goodbye_wav()
                await self._reset_to_kws()
                return

            # Interrupt TTS if user started speaking while TTS is playing
            if self.state == JarvisState.DIALOG_ACTIVE and self._tts_task and not self._tts_task.done():
                await self._pause_tts()
                await self._transition_to(JarvisState.TTS_PAUSED)
                logger.debug("TTS paused")
        # Endpoint detection: Paraformer streaming ASR holds the last partial
        # on silence frames (stale). The `if text` block above only updates
        # _last_speech_time when partial grew, so this fires after ~2s of stale.
        if (self._current_asr_text
                and (time.time() - self._last_speech_time) > 2.0):
            utterance = self._current_asr_text
            self._current_asr_text = ""

            # Reset the streaming ASR session so the next chunk starts
            # fresh; otherwise Paraformer keeps returning the stale partial
            # and we loop the same junk text into the LLM.
            if self._asr is not None:
                try:
                    self._asr.start()
                except Exception as exc:
                    logger.warning("ASR stream reset failed: %s", exc)

            if _is_garbage_text(utterance):
                logger.info(
                    "ASR endpoint reached, dropping garbage: %r",
                    utterance,
                )
            else:
                logger.info(
                    "ASR endpoint reached, sending to LLM: '%s'",
                    utterance,
                )
                if self.on_user_utterance:
                    self.on_user_utterance(utterance)
                # stream_tts=False: backend does NOT push PCM via WebRTC
                # SpeakerAudioTrack. The browser plays TTS through
                # <audio> via `playLlmReplyAudio` on llm_reply. Setting
                # this back to True would replay every reply twice (once
                # from the browser, once from the WebRTC speaker).
                await self._send_to_llm(utterance, stream_tts=False)

                # Resume TTS if paused (LLM response will trigger new TTS)
                if self.state == JarvisState.TTS_PAUSED and self._tts_task:
                    # Cancel old TTS and restart with new LLM response
                    self._tts_task.cancel()
                    self._tts_task = None
            await self._transition_to(JarvisState.DIALOG_ACTIVE)

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------

    async def _drain_pending_audio(self, reason: str = "") -> int:
        """Drop all PCM chunks currently buffered in the audio queue.

        Used right after wake detection so that ASR does not see the wake
        phrase itself or the mic input that piled up during wake.wav
        playback (~4.6s).  Returns the number of chunks dropped.
        """
        dropped = 0
        while True:
            try:
                self._audio_queue.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        if dropped:
            logger.info("Drained %d queued audio chunks (%s)", dropped, reason)
        return dropped

    async def _transition_to(self, new_state: JarvisState):
        old = self.state
        self.state = new_state
        logger.debug("State: %s → %s", old.name, new_state.name)

    async def _reset_to_kws(self):
        """Clean up dialog state and return to KWS_LISTENING."""
        self._asr_stream_active = False
        if self._confirm_task and not self._confirm_task.done():
            self._confirm_task.cancel()
            try:
                await self._confirm_task
            except asyncio.CancelledError:
                pass
            self._confirm_task = None
        if self._asr:
            self._asr.stop()
        self._kws_shadow_asr_active = False
        self._kws_shadow_last_text = ""
        self._current_asr_text = ""
        self._tts_task = None
        await self._transition_to(JarvisState.KWS_LISTENING)
        if self._kws:
            self._kws.start()  # fresh KWS stream
        logger.info("Jarvis reset to KWS_LISTENING")

    # ------------------------------------------------------------------
    # Event audio playback
    # ------------------------------------------------------------------

    async def _play_event_wav(self, filename: str):
        """Play a pre-generated event WAV file.

        Reads the WAV (any sample rate; mono PCM16, or downmix from stereo),
        pushes PCM to audio_output callback (webui WebRTC track),
        or falls back to log+sleep if no callback is registered.
        Never raises — log only on errors.
        """
        path = Path(self.config.events_dir) / filename
        if not path.exists():
            logger.warning("Event audio not found: %s (skipping)", path)
            return

        try:
            import wave
            import numpy as _np
            with wave.open(str(path), "rb") as wf:
                sample_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                raw = wf.readframes(wf.getnframes())
            if sampwidth != 2:
                logger.warning(
                    "Event audio %s has sampwidth=%d (expected 2); playback may distort",
                    filename, sampwidth,
                )
            samples = _np.frombuffer(raw, dtype=_np.int16)
            if n_channels > 1:
                # Downmix interleaved channels by averaging. Keeps duration
                # honest and stops SpeakerAudioTrack._resample_pcm16 from
                # treating L/R as consecutive mono samples (pitch shift bug).
                frames = samples.reshape(-1, n_channels)
                samples = frames.mean(axis=1).astype(_np.int16)
                pcm = samples.tobytes()
            else:
                pcm = raw
            duration = samples.size / sample_rate
            logger.info(
                "Playing event: %s (%.1fs, %dHz, %dch, %d bytes)",
                filename, duration, sample_rate, n_channels, len(pcm),
            )
            if self.audio_output:
                try:
                    await self.audio_output(pcm, sample_rate)
                except Exception as exc:
                    logger.error("audio_output for %s failed: %s", filename, exc)
                    await asyncio.sleep(duration)
            else:
                # No audio_output callback: log + sleep (silent fail)
                logger.debug("No audio_output registered; sleeping %.1fs", duration)
                await asyncio.sleep(duration)
        except Exception as exc:
            logger.error("Failed to play %s: %s", filename, exc)
            await asyncio.sleep(1.5)  # fallback

    async def _play_wake_wav(self):
        await self._play_event_wav(self.config.wake_wav)

    async def _play_goodbye_wav(self):
        if self.on_goodbye:
            self.on_goodbye()
        await self._play_event_wav(self.config.goodbye_wav)

    # ------------------------------------------------------------------
    # TTS control
    # ------------------------------------------------------------------

    async def _stop_tts(self):
        """Stop TTS immediately (user interrupted with exit word)."""
        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
            self._tts_task = None
            logger.debug("TTS stopped")

    async def _pause_tts(self):
        """Pause TTS (user started speaking while TTS was playing)."""
        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
            self._tts_task = None
            logger.debug("TTS paused")

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    async def _send_to_llm(self, text: str, *, stream_tts: bool = True, image_b64: Optional[str] = None):
        """Send user's ASR text to the LLM (llama-server 7060) and stream TTS.

        Calls POST {llm_api_url}/chat/completions with system prompt + history,
        then optionally triggers _stream_tts with the response text.

        v3.35: when ``image_b64`` is provided (paper-plane multimodal send)
        the final user message is shaped as a content array of
        ``[text, image_url]`` so llama.cpp's mmproj path can ground the
        answer in the captured frame. Otherwise we send plain text.
        """
        # v3.24: prepend bounded conversation history so BT-7274 retains
        # short-term context across turns without persisting anything.
        messages = [{"role": "system", "content": self.config.llm_system_prompt}]
        # Snapshot history before we mutate it
        history_snapshot = list(self._conv_history)[-self._max_history_turns * 2:]
        for role, content in history_snapshot:
            messages.append({"role": role, "content": content})
        if image_b64:
            # Multimodal: text + image_url (OpenAI-compatible). Requires
            # llama-server to be loaded with --mmproj (which our default
            # install does; see install/windows/start-llama-server.ps1).
            user_content = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": text})

        logger.info(
            "LLM input: '%s' (history_turns=%d)",
            text,
            len(history_snapshot) // 2,
        )
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # v3.37 single-LLM-gateway: route by media type.
                # text-only path -> /v1/text/chat (orchestration: prompt
                # composition, token guard, decision-token parsing).
                # multimodal path -> /v1/chat/completions (existing).
                endpoint_path = (
                    self.config.llm_multimodal_path
                    if image_b64
                    else self.config.llm_text_path
                )
                endpoint_url = f"{self.config.llm_api_url}{endpoint_path}"
                resp = await client.post(
                    endpoint_url,
                    json={
                        "model": self.config.llm_model,
                        "messages": messages,
                        "max_tokens": 200,
                        "temperature": 0.7,
                    },
                )
                resp.raise_for_status()
                response_payload = resp.json()
                choice = (response_payload.get("choices") or [{}])[0]
                response = (choice.get("message") or {}).get("content") or ""
                response = response.strip() if isinstance(response, str) else ""
                harness = response_payload.get("streamingharness") or {}
                decision = harness.get("decision") or (
                    "response" if response else "silence"
                )
                delegation_question = harness.get("delegation_question")
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            response = f"[LLM error: {exc}]"
            decision = "silence"
            delegation_question = None

        logger.info("LLM response (decision=%s): '%s'", decision, response)

        # v3.37: when the model opted to delegate, fire BackgroundModelService
        # with the assistant's reply + the user's original ask as the
        # delegated question (webinfer extracts it from </delegation> Q).
        if decision == "delegation":
            try:
                bg = self._background_service
                if bg is not None and getattr(bg, "enabled", True) and not getattr(bg, "_closed", False):
                    payload_text = (response or "").strip() or text
                    if delegation_question:
                        payload_text = (
                            f"{payload_text}\n\n</delegation> {delegation_question}"
                        )
                    metrics = {"user_prompt": text, "delegation_question": delegation_question}
                    bg.handle_foreground_response(payload_text, metrics=metrics)
            except Exception as exc:  # noqa: BLE001
                logger.warning("delegation routing failed: %s", exc)
            # Skip TTS for delegated replies; the foreground line is empty
            # and the background agent will surface the real answer.
            stream_tts = False

        # v3.24: append to conversation history (turn-by-turn)
        self._conv_history.append(("user", text))
        self._conv_history.append(("assistant", response))

        # Tag the broadcast with whether the back-end also streamed TTS to the
        # WebRTC audio_output track, so the front-end can avoid double-playing.
        reply_source = "jarvis_voice" if stream_tts else "jarvis_text"
        if self.on_llm_response:
            self.on_llm_response(response, source=reply_source)

        # Stream TTS for true voice mode. Silence + delegation suppress TTS.
        if stream_tts and decision != "silence":
            self._tts_task = asyncio.create_task(self._stream_tts(response))

    async def _stream_tts(self, text: str):
        """Stream TTS audio via voice_clone_api /v1/synthesize.

        Returns PCM16 bytes (24kHz mono) and pushes them to audio_output.
        voice_id is bt-7274 (uploaded reference).
        """
        import httpx
        logger.debug("TTS streaming: '%s'", text[:60])
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self.config.tts_api_url,
                    json={
                        "text": text,
                        "voice_id": self.config.tts_voice_id,
                        "streaming": False,
                        "sample_rate": 24000,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                # voice_clone_api returns pcm16_base64 or audio (base64)
                import base64
                audio_b64 = payload.get("pcm16_base64") or payload.get("audio")
                if not audio_b64:
                    logger.error("TTS response missing audio: %s", payload)
                    return
                pcm = base64.b64decode(audio_b64)
        except Exception as exc:
            logger.error("TTS failed: %s", exc)
            return

        # Push to audio output (WebRTC track or local fallback)
        if self.audio_output:
            try:
                await self.audio_output(pcm, 24000)
            except Exception as exc:
                logger.error("audio_output failed: %s", exc)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self):
        if self._kws:
            self._kws.stop()
        if self._asr:
            self._asr.stop()
        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
        logger.info("Jarvis state machine cleaned up")


# ============================================================================
# Standalone test
# ============================================================================

async def _test_main():
    """Quick smoke test (requires sherpa-onnx models)."""
    import wave

    test_wav = Path("prompts/bt/events/wake.wav")  # or any 16kHz mono wav
    if not test_wav.exists():
        print(f"Test WAV not found: {test_wav}")
        return

    jarvis = JarvisStateMachine()
    bg = asyncio.create_task(jarvis.run())

    with wave.open(str(test_wav), "rb") as wf:
        assert wf.getframerate() == 16000, "16kHz only"
        chunk_size = 1600  # 100ms
        while True:
            data = wf.readframes(chunk_size // 2)
            if not data:
                break
            await jarvis.feed_audio(data)
            await asyncio.sleep(0.1)

    await asyncio.sleep(2)
    bg.cancel()
    print("Test done.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_test_main())








