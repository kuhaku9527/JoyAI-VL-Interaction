"""Smart Turn v3.2 semantic end-of-turn detection adapter.

Adds a *semantic* layer on top of sherpa-onnx acoustic endpoint detection.
Wraps the ``pipecat-ai/smart-turn-v3.2`` ONNX model (CPU, ~50MB) and decides
whether the user has actually finished speaking, catching cases acoustic
endpoint detection misses (e.g. "嗯……那个" trailing thought, or "行谢谢"
with no pause getting merged).

Design constraints (from spec `smart-turn-end-of-turn` + 约法三章):
  * In-process ONNX inference, NO new service process.
  * **Fail-open**: when the model asset is absent or onnxruntime is
    unavailable, ``is_end_of_turn`` returns ``(False, 0.0)`` and logs a single
    warning. It never raises, never silently fakes a result, and never blocks
    the ASR pipeline — the acoustic endpoint detection stays the source of
    truth.
  * Must NOT replace EXIT_WORDS (those gate "explicit end"); Smart Turn only
    judges "did the user finish this turn".

Model asset:
  Path resolved from ``SMART_TURN_MODEL_PATH`` env, else
  ``<JOYAI_MODELS_ROOT>/smart-turn/smart-turn-v3.2-cpu.onnx``
  (``JOYAI_MODELS_ROOT`` defaults to ``D:/AI/models``).
  Must be fetched from HuggingFace (``pipecat-ai/smart-turn-v3.2``) before e2e
  golden tests run. The golden test auto-skips when the asset is absent,
  mirroring the memory-store bge-m3 local-weight convention.

NOTE on input contract:
  The exact input tensor names / shapes / preprocessing must be verified
  against the fetched model card. Until then, inference runs only when the
  asset is present (the golden test gates it); without the asset the adapter
  stays in fail-open and the path below is never exercised in CI.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("joyai.webui.smart_turn")

DEFAULT_MODELS_ROOT = Path(os.environ.get("JOYAI_MODELS_ROOT", "D:/AI/models"))
MODEL_DIR = DEFAULT_MODELS_ROOT / "smart-turn"
MODEL_FILENAME = "smart-turn-v3.2-cpu.onnx"
END_OF_TURN_THRESHOLD = 0.5


class SmartTurnAdapter:
    """Thin, fail-open wrapper around the Smart Turn ONNX model."""

    def __init__(self, model_path: str | None = None):
        self.model_path = Path(
            model_path
            or os.environ.get("SMART_TURN_MODEL_PATH", "")
            or (MODEL_DIR / MODEL_FILENAME)
        )
        self._session = None
        self._available = False
        self._load()

    def _load(self) -> None:
        if not self.model_path or not self.model_path.exists():
            logger.warning(
                "[smart-turn] model asset not found at %s; adapter in fail-open "
                "mode (acoustic endpoint detection unchanged)",
                self.model_path,
            )
            self._available = False
            return
        try:
            import onnxruntime as ort
        except ImportError:
            logger.warning(
                "[smart-turn] onnxruntime unavailable; adapter in fail-open mode"
            )
            self._available = False
            return
        try:
            self._session = ort.InferenceSession(
                str(self.model_path), providers=["CPUExecutionProvider"]
            )
            self._available = True
            logger.info("[smart-turn] loaded ONNX from %s", self.model_path)
        except Exception as exc:  # noqa: BLE001 - fail-open, never crash pipeline
            logger.warning(
                "[smart-turn] failed to load ONNX (%s); adapter in fail-open mode",
                exc,
            )
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def is_end_of_turn(self, audio_context: bytes, transcript: str) -> tuple[bool, float]:
        """Return ``(complete, probability)``.

        Fail-open: when the model is unavailable, returns ``(False, 0.0)`` so a
        caller using ``available`` as a gate will treat the acoustic endpoint
        as the decision and keep DIALOG_ACTIVE.
        """
        if not self._available or self._session is None:
            return (False, 0.0)
        try:
            import numpy as np  # local; present wherever onnxruntime runs

            # TODO(smart-turn): confirm input tensor names/shapes/normalization
            # against the fetched model card before e2e use. The golden test
            # (skipped without the asset) is the gate that catches mismatches.
            inputs = {
                "audio": np.frombuffer(audio_context, dtype=np.int16)
                .astype(np.float32)
                .reshape(1, -1)
                / 32768.0,
                "transcript": np.array([transcript], dtype=object),
            }
            outputs = self._session.run(None, inputs)
            prob = float(outputs[0].reshape(-1)[0])
            complete = prob >= END_OF_TURN_THRESHOLD
            logger.debug("[smart-turn] p=%.3f complete=%s", prob, complete)
            return (complete, prob)
        except Exception as exc:  # noqa: BLE001 - fail-open on any inference error
            logger.warning(
                "[smart-turn] inference failed (%s); fail-open (not end-of-turn)",
                exc,
            )
            return (False, 0.0)


# Golden test set: (label, transcript, expected_complete) used by the pytest
# harness. The model must be fetched before these assert; without it the test
# skips.
GOLDEN_CASES = [
    ("trailing_thought", "嗯……那个", False),
    ("explicit_end", "行谢谢", True),
    ("normal_sentence", "把屏幕亮度调低一点", True),
]
