"""Jarvis Session Manager — bridges state machine into webui server.

Provides per-session Jarvis state management that hooks into:
- server.py: session creation, state broadcast
- asr.py: audio routing, wake/exit word detection
- tts.py: TTS gating

Usage in server.py:
    from jarvis_session import JarvisSessionManager

    manager = JarvisSessionManager()
    jarvis = await manager.create_session(session_id)
    await jarvis.feed_audio(pcm_chunk)
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from .jarvis_mode import (
    AsrPartial,
    EXIT_WORDS,
    JarvisConfig,
    JarvisState,
    JarvisStateMachine,
)

logger = logging.getLogger("joyai.jarvis.session")

# ============================================================================
# Per-session wrapper
# ============================================================================


@dataclass
class JarvisSession:
    """A single Jarvis session attached to a webui session."""

    session_id: str
    state_machine: JarvisStateMachine
    state: JarvisState = JarvisState.KWS_LISTENING
    _feed_task: Optional[asyncio.Task] = None
    _bg_task: Optional[asyncio.Task] = None

    async def start(self):
        """Prewarm engines and launch the background state machine loop.

        ``prewarm_engines`` loads the KWS and ASR models in an executor
        *before* the bg loop starts. Without this, the first KWS wake
        fires against a cold ASR instance whose ~1.2s model load is eaten
        by the same-length confirm window, so every wake is rejected as
        a false alarm. See ``prewarm_engines`` docstring for details.
        """
        await self.state_machine.prewarm_engines()
        self._bg_task = asyncio.create_task(self.state_machine.run())

    async def stop(self):
        """Stop the session, cancelling both bg loop and any in-flight feed."""
        if self._bg_task:
            self._bg_task.cancel()
        # Cancel any in-flight diagnostic feed so it cannot keep pushing audio
        # after the session is being torn down.
        if self._feed_task and not self._feed_task.done():
            self._feed_task.cancel()
        # Wait for both tasks to actually finish so cancellation is observable.
        if self._bg_task:
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        if self._feed_task:
            try:
                await self._feed_task
            except asyncio.CancelledError:
                pass

    def attach_feed_task(self, task: asyncio.Task) -> None:
        """Track a background feed task so it can be cancelled on stop().

        If a previous feed task is still running it is cancelled first, so a
        new /api/jarvis/feed_wav call always supersedes the previous one.
        """
        if self._feed_task and not self._feed_task.done():
            self._feed_task.cancel()
        self._feed_task = task

    async def feed_audio(self, pcm: bytes):
        """Route mic audio to the state machine."""
        await self.state_machine.feed_audio(pcm)

    def check_exit_words(self, text: str) -> bool:
        """Check if an ASR partial/final text contains an exit word.

        Call from asr.py's forward_asr_results before forwarding to browser.
        """
        stripped = text.strip().lower()
        return any(stripped.endswith(w) for w in EXIT_WORDS)

    def should_synthesize(self) -> bool:
        """Should TTS be allowed? Blocks TTS when in KWS_LISTENING state."""
        return self.state_machine.state in (
            JarvisState.DIALOG_ACTIVE,
            JarvisState.TTS_PAUSED,
            JarvisState.WAKE_DETECTED,
        )

    def should_analyze_frame(self) -> bool:
        """Should VLM process video frames?

        In KWS_LISTENING, skip detailed analysis to save GPU.
        In DIALOG_ACTIVE, allow full analysis.
        """
        return self.state_machine.state != JarvisState.KWS_LISTENING

    def get_state_for_browser(self) -> dict:
        """Return a JSON-safe state snapshot for the browser UI."""
        return {
            "jarvis_state": self.state_machine.state.name,
            "wake_word": self.state_machine.config.wake_word,
        }

    def attach_audio_output(self, audio_output) -> None:
        """Bind an audio output callback (e.g. SpeakerAudioTrack.push_pcm)."""
        self.state_machine.audio_output = audio_output

    @property
    def is_awake(self) -> bool:
        """Is Jarvis currently awake / in conversation?"""
        return self.state_machine.state in (
            JarvisState.WAKE_DETECTED,
            JarvisState.DIALOG_ACTIVE,
            JarvisState.TTS_PAUSED,
        )


# ============================================================================
# Session Manager
# ============================================================================


class JarvisSessionManager:
    """Manages multiple Jarvis sessions (one per webui session)."""

    def __init__(self, config: Optional[JarvisConfig] = None):
        self.config = config or JarvisConfig()
        self._sessions: dict[str, JarvisSession] = {}

    async def create_session(
        self,
        session_id: str,
        audio_output = None,
    ) -> JarvisSession:
        """Create a new Jarvis session for the given webui session.

        If a session for session_id already exists, attach the new
        audio_output callback (e.g. SpeakerAudioTrack.push_pcm) and
        return the existing one instead of creating a duplicate.
        """
        if session_id in self._sessions:
            existing = self._sessions[session_id]
            if audio_output is not None:
                existing.attach_audio_output(audio_output)
            return existing

        sm = JarvisStateMachine(
            config=self.config,
            on_wake=lambda: logger.info("Session %s: wake detected", session_id),
            on_goodbye=lambda: logger.info("Session %s: goodbye", session_id),
            on_asr_partial=self._make_asr_callback(session_id),
            on_user_utterance=self._make_user_utterance_callback(session_id),
            on_llm_response=self._make_llm_callback(session_id),
            audio_output=audio_output,
        )

        session = JarvisSession(session_id=session_id, state_machine=sm)
        await session.start()
        self._sessions[session_id] = session
        logger.info("Jarvis session created: %s", session_id)
        return session

    def _make_asr_callback(self, session_id: str):
        """Build a callback that pushes ASR partial/final updates to the browser.

        The browser uses this to show what ASR is currently thinking in real
        time (replaces / supplements the on-screen typed text from the user)
        and to commit the final text when the endpoint is reached. Without
        this broadcast, ASR is a black box -- the only signal we have is the
        final pilot_utterance that fires after the user stops speaking.
        """
        def cb(partial: AsrPartial):
            try:
                from .server import notify_session_asr_partial
                notify_session_asr_partial(
                    session_id,
                    partial.text or "",
                    is_final=bool(getattr(partial, "is_final", False)),
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "ASR partial broadcast failed for %s: %s", session_id, exc
                )
        return cb

    def _make_user_utterance_callback(self, session_id: str):
        """Build a callback that pushes final ASR text to the browser."""
        def cb(text: str):
            try:
                from .server import notify_session_pilot_utterance
                notify_session_pilot_utterance(session_id, text, source="asr")
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Pilot utterance broadcast failed for %s: %s",
                    session_id, exc,
                )
        return cb

    def _make_llm_callback(self, session_id: str):
        """Build a callback that pushes LLM replies to the browser.

        The state machine invokes this from ``_send_to_llm`` once
        the LLM has produced its response. The server-level
        ``notify_session_llm_reply`` helper is imported lazily to
        avoid a circular import (server.py imports this module).
        """
        def cb(text: str):
            try:
                from .server import notify_session_llm_reply
                notify_session_llm_reply(session_id, text, source="jarvis")
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "LLM reply broadcast failed for %s: %s",
                    session_id, exc,
                )
        return cb


    def get_session(self, session_id: str) -> Optional[JarvisSession]:
        """Get an existing session, or None."""
        return self._sessions.get(session_id)

    async def remove_session(self, session_id: str):
        """Stop and remove a session."""
        session = self._sessions.pop(session_id, None)
        if session:
            await session.stop()
            logger.info("Jarvis session removed: %s", session_id)


# ============================================================================
# Singleton (optional)
# ============================================================================

_global_manager: Optional[JarvisSessionManager] = None


def get_global_manager() -> JarvisSessionManager:
    """Get or create the global Jarvis session manager singleton."""
    global _global_manager
    if _global_manager is None:
        _global_manager = JarvisSessionManager()
    return _global_manager
