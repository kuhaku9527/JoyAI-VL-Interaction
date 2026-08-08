"""Smart Turn v3.2 semantic end-of-turn detection adapter.

A semantic end-of-turn layer on top of the backend-agnostic acoustic endpoint
(silence) detection; independent of the ASR backend (cloud vLLM/SiliconFlow or
local sherpa-onnx).
Wraps the ``pipecat-ai/smart-turn-v3`` ONNX model (CPU, int8-quantized,
~8.6MB) and decides whether the user has actually finished speaking, catching
cases acoustic endpoint detection misses (e.g. "嗯……那个" trailing thought, or
"行谢谢" with no pause getting merged).

Design constraints (from spec `smart-turn-end-of-turn` + 约法三章):
  * In-process ONNX inference, NO new service process.
  * **Fail-open**: when the model asset is absent, onnxruntime is
    unavailable, or the Whisper feature extractor cannot be loaded,
    ``is_end_of_turn`` returns ``(False, 0.0)`` and logs a single warning. It
    never raises, never silently fakes a result, and never blocks the ASR
    pipeline — the acoustic endpoint detection stays the source of truth.
  * Must NOT replace EXIT_WORDS (those gate "explicit end"); Smart Turn only
    judges "did the user finish this turn".

Verified model contract (pipecat-ai/smart-turn inference.py):
  * Audio input: 16kHz mono float32 in [-1, 1].
  * Preprocessing: ``WhisperFeatureExtractor(chunk_length=8)`` with
    ``sampling_rate=16000, return_tensors="np", padding="max_length",
    max_length=8*16000, truncation=True, do_normalize=True`` →
    ``input_features`` shape [80, 800] (n_mels=80, 800 frames), then
    ``np.expand_dims(..., 0)`` → [1, 80, 800].
  * ONNX input tensor name: ``input_features`` (shape [1, 80, 800]).
  * ONNX output: ``outputs[0][0]`` is already a sigmoid probability in [0, 1];
    ``> 0.5`` means "end of turn". No extra sigmoid needed.
  * The model is **audio-native**: it does NOT consume a transcript input, so
    the ``transcript`` argument below is ignored (kept only for API stability).

Model asset:
  Path resolved from ``SMART_TURN_MODEL_PATH`` env, else
  ``<JOYAI_MODELS_ROOT>/smart-turn/smart-turn-v3.2-cpu.onnx``
  (``JOYAI_MODELS_ROOT`` defaults to ``D:/AI/models``).
  Must be fetched from HuggingFace (``pipecat-ai/smart-turn-v3``) before e2e
  golden tests run. The golden test auto-skips when the asset is absent,
  mirroring the memory-store bge-m3 local-weight convention.

Whisper feature-extractor config:
  Prefer the vendored config dir ``<MODEL_DIR>/whisper_feature_extractor/``
  (holding ``openai/whisper-small``'s ``preprocessor_config.json``). Fall back
  to ``WhisperFeatureExtractor.from_pretrained("openai/whisper-small")`` only
  when that dir is absent.
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

# Vendored Whisper feature-extractor config dir (openai/whisper-small
# preprocessor_config.json). Checked first; falls back to HF otherwise.
WHISPER_EXTRACTOR_DIR = MODEL_DIR / "whisper_feature_extractor"

_SAMPLES_PER_CHUNK = 8 * 16000  # 8s @ 16kHz; max_length for the extractor


class SmartTurnAdapter:
    """Thin, fail-open wrapper around the Smart Turn ONNX model."""

    def __init__(self, model_path: str | None = None):
        self.model_path = Path(
            model_path
            or os.environ.get("SMART_TURN_MODEL_PATH", "")
            or (MODEL_DIR / MODEL_FILENAME)
        )
        self._session = None
        self._extractor = None
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
            logger.warning("[smart-turn] onnxruntime unavailable; adapter in fail-open mode")
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

    def _get_extractor(self):
        """Lazily load the Whisper feature extractor (cached).

        Prefers the vendored ``WHISPER_EXTRACTOR_DIR``; falls back to
        ``openai/whisper-small`` from HF. Returns ``None`` (and stays
        fail-open) on any load failure.
        """
        if self._extractor is not None:
            return self._extractor
        try:
            from transformers import WhisperFeatureExtractor
        except ImportError:
            logger.warning(
                "[smart-turn] transformers unavailable; adapter in fail-open mode "
                "(cannot build log-mel features)"
            )
            self._extractor = None
            return None
        try:
            if (WHISPER_EXTRACTOR_DIR / "preprocessor_config.json").exists():
                self._extractor = WhisperFeatureExtractor.from_pretrained(
                    str(WHISPER_EXTRACTOR_DIR), chunk_length=8
                )
                logger.info(
                    "[smart-turn] loaded WhisperFeatureExtractor from vendored %s",
                    WHISPER_EXTRACTOR_DIR,
                )
            else:
                self._extractor = WhisperFeatureExtractor.from_pretrained(
                    "openai/whisper-small", chunk_length=8
                )
                logger.info(
                    "[smart-turn] loaded WhisperFeatureExtractor from openai/whisper-small "
                    "(vendored config absent)"
                )
        except Exception as exc:  # noqa: BLE001 - fail-open on extractor load error
            logger.warning(
                "[smart-turn] failed to load WhisperFeatureExtractor (%s); "
                "adapter in fail-open mode",
                exc,
            )
            self._extractor = None
        return self._extractor

    def is_end_of_turn(self, audio_context: bytes, transcript: str) -> tuple[bool, float]:
        """Return ``(complete, probability)``.

        ``audio_context`` is 16kHz mono int16 PCM bytes (the format
        jarvis_mode's ``_recent_audio`` keeps). It is converted to float32 in
        [-1, 1] and turned into a Whisper log-mel spectrogram.

        The model is **audio-native**: it ignores ``transcript`` (kept only
        for API stability). Do not feed transcript into the graph.

        Fail-open: when the model/extractor is unavailable, returns
        ``(False, 0.0)`` so a caller using ``available`` as a gate will treat
        the acoustic endpoint as the decision and keep DIALOG_ACTIVE.
        """
        if not self._available or self._session is None:
            return (False, 0.0)
        try:
            import numpy as np  # local; present wherever onnxruntime runs

            samples = np.frombuffer(audio_context, dtype=np.int16).astype(np.float32) / 32768.0
            if samples.shape[0] > _SAMPLES_PER_CHUNK:
                # Keep only the most recent 8s (model window).
                samples = samples[-_SAMPLES_PER_CHUNK:]

            extractor = self._get_extractor()
            if extractor is None:
                return (False, 0.0)

            feats = extractor(
                samples,
                sampling_rate=16000,
                return_tensors="np",
                padding="max_length",
                max_length=_SAMPLES_PER_CHUNK,
                truncation=True,
                do_normalize=True,
            )
            input_features = feats["input_features"]
            if input_features.ndim == 2:
                input_features = np.expand_dims(input_features, axis=0)

            outputs = self._session.run(None, {"input_features": input_features})
            # outputs[0][0] is already a sigmoid probability in [0, 1].
            prob = float(outputs[0].reshape(-1)[0])
            complete = prob > END_OF_TURN_THRESHOLD
            logger.debug("[smart-turn] p=%.3f complete=%s", prob, complete)
            return (complete, prob)
        except Exception as exc:  # noqa: BLE001 - fail-open on any inference error
            logger.warning(
                "[smart-turn] inference failed (%s); fail-open (not end-of-turn)",
                exc,
            )
            return (False, 0.0)


# Placeholder golden set: (label, transcript, expected_complete). NOTE: the
# model is audio-native and ignores transcript, so these transcript-based
# labels cannot be asserted against the real model without a real-audio
# calibration set (recorded utterances paired with ground-truth end-of-turn
# judgments). Kept so the structural smoke test ``test_golden_cases_defined``
# still holds; replace with audio-indexed cases once a recording corpus exists.
GOLDEN_CASES = [
    ("trailing_thought", "嗯……那个", False),
    ("explicit_end", "行谢谢", True),
    ("normal_sentence", "把屏幕亮度调低一点", True),
]
