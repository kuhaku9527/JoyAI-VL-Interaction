"""Smart Turn v3.2 semantic end-of-turn threshold calibration harness.

Scans a decision threshold over two *public* eval sets and recommends a value
for the already-landed adapter
(``joy_interaction_webui.smart_turn_adapter.SmartTurnAdapter``).

Datasets
--------
1. ``pipecat-ai/smart-turn-data-v3.2-test``  (official benchmark, 31.5k rows)
   - the ONNX model's own official test set; most faithful for repro.
   - columns: ``audio`` (HF Audio, sample rate NOT guaranteed 16k),
     ``endpoint_bool`` (True = user finished = POSITIVE), ``language`` (23
     langs incl. eng/zho), ``audioduration``.
2. ``ASLP-lab/Easy-Turn-Testset``  (Apache-2.0, ~804 WAVs)
   - raw WAV repo (NOT a HF ``datasets`` parquet): ``testset/{complete,
     incomplete,wait,backchannel}/*.wav``.
   - label mapping: complete -> POSITIVE (1); incomplete -> NEGATIVE (0);
     wait / backchannel -> merged into NEGATIVE (0). Choice documented in the
     report. CN-heavy, small, clean labels -> secondary + Chinese baseline.

Why a custom audio path
-----------------------
``datasets>=4`` decodes audio via ``torchcodec`` (needs torch), which we must
NOT install. We therefore load audio with ``decode=False`` (or read the raw
WAV repo) and decode the bytes / files ourselves with ``soundfile``.

The adapter's contract is **16kHz mono int16 PCM bytes**; its internal Whisper
feature extractor is hard-wired to 16k and emits garbage for other rates.
Every clip is therefore resampled to 16kHz mono int16 before being passed in.
The model is audio-native and ignores ``transcript`` (passed as "").

Usage
-----
    python calibrate_smart_turn.py --max-pipecat 300
    python calibrate_smart_turn.py --max-pipecat 300 --out report.md
    python calibrate_smart_turn.py --max-pipecat 300 --no-easy-turn
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path

import numpy as np

# --- path setup -----------------------------------------------------------
# Insert webui/src so we can ``import joy_interaction_webui.smart_turn_adapter``.
SCRIPT_DIR = Path(__file__).resolve().parent
WEBUI_SRC = SCRIPT_DIR / "src"
if str(WEBUI_SRC) not in sys.path:
    sys.path.insert(0, str(WEBUI_SRC))

# CRITICAL: the repo root contains a local *namespace* package named
# ``datasets/`` (the project's own eval data dir). That shadows the real
# HuggingFace ``datasets`` library. Drop repo root from sys.path so the real
# library is imported. (The real one is also a regular package, which beats a
# namespace package regardless, but we remove the shadow defensively.)
REPO_ROOT = SCRIPT_DIR.parent.parent
sys.path = [p for p in sys.path if Path(p).resolve() != REPO_ROOT.resolve()]

import soundfile as sf  # noqa: E402  (soundfile decodes audio without torch)
from datasets import Audio, load_dataset  # noqa: E402

from joy_interaction_webui.smart_turn_adapter import (  # noqa: E402
    END_OF_TURN_THRESHOLD,
    SmartTurnAdapter,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("calibrate_smart_turn")
# Quiet the noisy huggingface/datasets/httpx housekeeping logs.
logging.getLogger("datasets").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TARGET_SR = 16000
MAX_SAMPLES = 8 * TARGET_SR  # model window = 8s @ 16k
THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]


# --- audio helpers --------------------------------------------------------
def resample_to_16k_int16(array: np.ndarray, sr: int) -> bytes | None:
    """Resample a float32 audio array to 16kHz mono int16 PCM bytes.

    Handles mono or multi-channel (channels averaged to mono). Linear-
    interpolation resample (no torchaudio / scipy dependency). The adapter
    internally truncates to the most-recent 8s; we do the same here so the
    int16 buffer stays bounded for very long clips.
    """
    try:
        audio = np.asarray(array, dtype=np.float32)
        if audio.ndim > 1:  # (samples, channels) -> mono
            audio = audio.mean(axis=1)
        audio = audio.reshape(-1)
    except Exception:  # noqa: BLE001 - defensive; skip bad samples
        return None
    if audio.size == 0:
        return None
    if sr != TARGET_SR and sr > 0:
        n_target = round(audio.shape[0] * TARGET_SR / float(sr))
        if n_target > 0:
            idx = np.linspace(0.0, audio.shape[0] - 1, n_target)
            audio = np.interp(idx, np.arange(audio.shape[0]), audio).astype(np.float32)
    audio = np.clip(audio, -1.0, 1.0)
    if audio.shape[0] > MAX_SAMPLES:
        audio = audio[-MAX_SAMPLES:]
    pcm = np.clip(audio * 32768.0, -32768.0, 32767.0).astype(np.int16)
    return pcm.tobytes()


def decode_audio_bytes(data: bytes) -> tuple[np.ndarray, int] | None:
    """Decode raw audio bytes to (float32 array, sample_rate) without torch.

    Primary path: ``soundfile``. Fallback: ``ffmpeg`` (covers codecs libsndfile
    lacks, e.g. MP3/Opus). Returns None on total failure.
    """
    # soundfile
    try:
        arr, sr = sf.read(BytesIO(data))
        return np.asarray(arr, dtype=np.float32), int(sr)
    except Exception as exc:  # noqa: BLE001
        logger.debug("soundfile decode failed; falling back to ffmpeg: %s", exc)
    # ffmpeg fallback -> raw float32 mono @ 16k, then we resample if needed
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        return None
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-i",
                "pipe:0",
                "-ac",
                "1",
                "-ar",
                str(TARGET_SR),
                "-f",
                "f32le",
                "-nostdin",
                "-loglevel",
                "error",
                "pipe:1",
            ],
            input=data,
            capture_output=True,
            check=True,
        )
        arr = np.frombuffer(proc.stdout, dtype=np.float32)
        return arr, TARGET_SR
    except Exception:  # noqa: BLE001
        return None


def audio_field_to_pcm(audio_field) -> bytes | None:
    """Turn an HF Audio cell into 16kHz mono int16 PCM bytes.

    Handles both:
      * decode=False dict -> {'bytes': ..., 'path': ...}
      * a decoded object/dict with {'array': ..., 'sampling_rate': ...}
    """
    if audio_field is None:
        return None
    if isinstance(audio_field, dict):
        raw = audio_field.get("bytes")
        sr = audio_field.get("sampling_rate")
        arr = audio_field.get("array")
        if raw is not None:
            decoded = decode_audio_bytes(raw)
            if decoded is None:
                return None
            arr, sr = decoded
        if arr is None:
            # path-based; only if a local file exists (rare for hub data)
            p = audio_field.get("path")
            if p and Path(p).exists():
                try:
                    arr, sr = sf.read(p)
                except Exception:  # noqa: BLE001
                    return None
        if arr is None or sr is None:
            return None
        return resample_to_16k_int16(np.asarray(arr), int(sr))
    # decoded Audio object
    try:
        arr = audio_field.array
        sr = audio_field.sampling_rate
        return resample_to_16k_int16(np.asarray(arr), int(sr))
    except Exception:  # noqa: BLE001
        return None


# --- dataset loaders ------------------------------------------------------
def _load_pipecat_once(max_n: int, zho_target: int):
    """Single attempt to stream the official test set; keep diversity."""
    ds = load_dataset("pipecat-ai/smart-turn-data-v3.2-test", split="train", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))

    # Global budget: reserve zho_target slots for Chinese, the rest for every
    # other language combined (NOT per-language — that would over-collect).
    non_zho_target = max_n - zho_target
    samples: list[tuple[int, bytes, str]] = []
    langs: Counter = Counter()
    skipped = 0
    scanned = 0
    zho_count = 0
    non_zho_count = 0
    max_scan = max(4000, max_n * 8)  # scan ahead so rare langs (e.g. zho) get a chance
    for s in ds:
        scanned += 1
        lang = s.get("language") or "unknown"
        if lang == "zho":
            if zho_count >= zho_target:
                continue
        else:
            if non_zho_count >= non_zho_target:
                continue
        pcm = audio_field_to_pcm(s.get("audio"))
        if pcm is None:
            skipped += 1
            continue
        label = 1 if bool(s.get("endpoint_bool")) else 0
        samples.append((label, pcm, lang))
        langs[lang] += 1
        if lang == "zho":
            zho_count += 1
        else:
            non_zho_count += 1
        if len(samples) >= max_n and zho_count >= zho_target:
            break
        if scanned > max_scan:
            break
    return samples, langs, skipped, scanned


def load_pipecat(max_n: int, zho_target: int, attempts: int = 4):
    """Stream the official test set with retry on transient network errors.

    HF's Xet CDN occasionally closes the httpx client mid-stream
    ("Cannot send a request, as the client has been closed"); recreating the
    dataset object in a fresh attempt recovers.
    """
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            logger.info(
                "Loading pipecat-ai/smart-turn-data-v3.2-test (streaming, attempt %d/%d)...",
                attempt,
                attempts,
            )
            samples, langs, skipped, scanned = _load_pipecat_once(max_n, zho_target)
            if samples:
                logger.info(
                    "pipecat: collected=%d skipped=%d scanned=%d langs=%s",
                    len(samples),
                    skipped,
                    scanned,
                    dict(langs),
                )
                return samples, langs, skipped
            last_err = RuntimeError("pipecat stream yielded 0 samples")
        except Exception as exc:  # noqa: BLE001 - transient network; retry
            last_err = exc
            logger.warning("pipecat load attempt %d failed: %s", attempt, exc)
    raise RuntimeError(f"pipecat loading failed after {attempts} attempts: {last_err}")


def load_easy_turn():
    """Load the raw-WAV Easy-Turn-Testset via the Xet-aware HfFileSystem.

    NOTE: ``snapshot_download`` leaves 0-byte Xet placeholders for this repo
    (the blobs only materialize when read through the Xet-aware filesystem),
    so we enumerate the repo's ``testset/**/*.wav`` paths and fetch each
    file's bytes through ``HfFileSystem``, then decode locally.
    """
    from huggingface_hub import HfFileSystem, list_repo_files

    repo = "ASLP-lab/Easy-Turn-Testset"
    logger.info("Enumerating %s WAV paths ...", repo)
    try:
        wav_paths = [
            f
            for f in list_repo_files(repo, repo_type="dataset")
            if f.startswith("testset/") and f.endswith(".wav")
        ]
    except Exception as exc:
        raise RuntimeError(f"Failed to list {repo}: {exc}") from exc
    logger.info("Found %d WAV paths", len(wav_paths))

    cat_to_label = {
        "complete": 1,
        "incomplete": 0,
        "wait": 0,
        "backchannel": 0,
    }
    fs = HfFileSystem()

    def _worker(rel: str):
        parts = rel.split("/")
        if "testset" not in parts:
            return None
        cat = parts[parts.index("testset") + 1]
        label = cat_to_label.get(cat)
        if label is None:
            return None
        try:
            with fs.open(f"datasets/{repo}/{rel}") as fh:
                data = fh.read()
            decoded = decode_audio_bytes(data)
            if decoded is None:
                return ("skip", rel)
            arr, sr = decoded
            pcm = resample_to_16k_int16(arr, int(sr))
            if pcm is None:
                return ("skip", rel)
            return ("ok", (label, pcm, cat))
        except Exception as exc:  # noqa: BLE001
            return ("skip", f"{rel}: {exc}")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    samples: list[tuple[int, bytes, str]] = []
    cat_counts: Counter = Counter()
    skipped = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_worker, rel): rel for rel in sorted(wav_paths)}
        for fut in as_completed(futs):
            res = fut.result()
            if res is None:
                continue
            kind = res[0]
            if kind == "ok":
                label, pcm, cat = res[1]
                samples.append((label, pcm, cat))
                cat_counts[cat] += 1
            else:
                skipped += 1
    logger.info(
        "easy-turn: collected=%d skipped=%d cats=%s", len(samples), skipped, dict(cat_counts)
    )
    return samples, cat_counts, skipped


# --- metrics --------------------------------------------------------------
def compute_metrics(pairs, threshold: float) -> dict:
    tp = fp = tn = fn = 0
    for label, _pcm, _meta, prob in pairs:
        pred = 1 if prob >= threshold else 0
        if pred == 1 and label == 1:
            tp += 1
        elif pred == 1 and label == 0:
            fp += 1
        elif pred == 0 and label == 0:
            tn += 1
        else:
            fn += 1
    n = tp + fp + tn + fn
    acc = (tp + tn) / n if n else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "threshold": threshold,
        "acc": acc,
        "prec": prec,
        "rec": rec,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "n": n,
    }


def recommend(rows: list[dict], default_threshold: float = END_OF_TURN_THRESHOLD) -> dict:
    """Pick the threshold with the highest F1 (precision tie-break, then
    closeness to 0.5).

    Plateau guard: if the best threshold's F1 is within ~0.02 of the *deployed*
    default, prefer the default. A flat curve means there is no reason to change
    the shipped value, and we must not nudge operators toward an arbitrary
    threshold (e.g. 0.80) when 0.5 is essentially as good.
    """
    default_row = next((r for r in rows if abs(r["threshold"] - default_threshold) < 1e-9), None)
    best = None
    for r in rows:
        if best is None:
            best = r
            continue
        if r["f1"] > best["f1"] + 1e-9:
            best = r
        elif abs(r["f1"] - best["f1"]) <= 1e-9:
            if r["prec"] > best["prec"] + 1e-9:
                best = r
            elif abs(r["prec"] - best["prec"]) <= 1e-9 and abs(r["threshold"] - 0.5) < abs(
                best["threshold"] - 0.5
            ):
                best = r
    if default_row is not None and best is not None and best["f1"] - default_row["f1"] < 0.02:
        return default_row
    return best


# --- reporting ------------------------------------------------------------
def _md_table(rows: list[dict]) -> str:
    header = "| threshold | acc | precision | recall | F1 | TP | FP | TN | FN |"
    sep = "|---|---|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"| {r['threshold']:.2f} | {r['acc']:.3f} | {r['prec']:.3f} | "
            f"{r['rec']:.3f} | {r['f1']:.3f} | {r['tp']} | {r['fp']} | "
            f"{r['tn']} | {r['fn']} |"
        )
    return "\n".join(lines)


def run_dataset(name: str, samples, adapter: SmartTurnAdapter):
    """Infer over samples, compute threshold sweep, return (report_md, metrics_rows, default_metrics)."""
    pairs = []  # (label, pcm, meta, prob)
    fail_open = 0
    for label, pcm, meta in samples:
        complete, prob = adapter.is_end_of_turn(pcm, "")
        if prob == 0.0 and complete is False and not adapter.available:
            fail_open += 1
        pairs.append((label, pcm, meta, prob))

    n_pos = sum(1 for lab, *_ in pairs if lab == 1)
    n_neg = len(pairs) - n_pos
    rows = [compute_metrics(pairs, t) for t in THRESHOLDS]
    rec = recommend(rows)
    default = compute_metrics(pairs, END_OF_TURN_THRESHOLD)

    md = [f"## {name}", ""]
    md.append(
        f"- Samples (after skip): **{len(pairs)}**  |  POSITIVE (complete): **{n_pos}**  |  NEGATIVE: **{n_neg}**"
    )
    md.append(f"- Fail-open predictions (prob==0.0 while unavailable): {fail_open}")
    md.append("")
    md.append("### Threshold sweep (positive class = end-of-turn / complete)")
    md.append("")
    md.append(_md_table(rows))
    md.append("")
    md.append(
        f"### Recommended threshold: **{rec['threshold']:.2f}** "
        f"(F1={rec['f1']:.3f}, prec={rec['prec']:.3f}, rec={rec['rec']:.3f}, acc={rec['acc']:.3f})"
    )
    md.append("")
    md.append(f"### Default threshold {END_OF_TURN_THRESHOLD:.2f} (deployed)")
    md.append(
        f"- accuracy={default['acc']:.3f}  precision={default['prec']:.3f}  "
        f"recall={default['rec']:.3f}  F1={default['f1']:.3f}"
    )
    md.append("")
    md.append("### Confusion matrix @ default 0.5 (rows=actual, cols=pred)")
    md.append("")
    md.append("| | pred NEG | pred POS |")
    md.append("|---|---|---|")
    md.append(f"| actual NEG | TN={default['tn']} | FP={default['fp']} |")
    md.append(f"| actual POS | FN={default['fn']} | TP={default['tp']} |")
    md.append("")

    # console summary
    print(f"\n===== {name} =====")
    print(f"samples={len(pairs)} pos={n_pos} neg={n_neg} fail_open={fail_open}")
    print(f"{'thr':>5} {'acc':>6} {'prec':>6} {'rec':>6} {'f1':>6}")
    for r in rows:
        print(
            f"{r['threshold']:>5.2f} {r['acc']:>6.3f} {r['prec']:>6.3f} {r['rec']:>6.3f} {r['f1']:>6.3f}"
        )
    print(f"RECOMMENDED: {rec['threshold']:.2f} (F1={rec['f1']:.3f})")
    print(
        f"DEFAULT 0.5: acc={default['acc']:.3f} prec={default['prec']:.3f} "
        f"rec={default['rec']:.3f} F1={default['f1']:.3f}"
    )

    return "\n".join(md), rows, default


# --- main -----------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Smart Turn threshold calibration harness")
    ap.add_argument("--max-pipecat", type=int, default=300, help="max pipecat samples to calibrate")
    ap.add_argument(
        "--zho-target",
        type=int,
        default=None,
        help="reserved zho slots in pipecat sample (default max_pipecat//5)",
    )
    ap.add_argument(
        "--easy-turn",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="include ASLP-lab/Easy-Turn-Testset (default: on)",
    )
    ap.add_argument("--out", type=str, default=None, help="write markdown report to this path")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    args = ap.parse_args()

    if args.verbose:
        logging.getLogger("calibrate_smart_turn").setLevel(logging.DEBUG)

    # model readiness gate
    adapter = SmartTurnAdapter()
    if not adapter.available:
        logger.error(
            "SmartTurnAdapter NOT available (model missing or onnxruntime/"
            "transformers failed). Install/verify the model at %s and re-run.",
            adapter.model_path,
        )
        return 2

    zho_target = args.zho_target if args.zho_target else max(1, args.max_pipecat // 5)

    report_parts = [
        "# Smart Turn v3.2 — Threshold Calibration Report",
        "",
        f"- Adapter model: `{adapter.model_path}`",
        f"- Deployed default threshold: `{END_OF_TURN_THRESHOLD}`",
        f"- Scanned thresholds: {THRESHOLDS}",
        "- Preprocessing: every clip resampled to 16kHz mono int16 PCM before "
        "`is_end_of_turn` (adapter's Whisper extractor is hard-wired to 16k).",
        "- Decision rule in this harness: `prob >= threshold` (positive = "
        "end-of-turn/complete). Note: the adapter's *internal* decision uses "
        "`prob > 0.5`; the harness re-derives decisions from the returned "
        "probability at each threshold, so the sweep is independent of that.",
        "",
    ]

    if args.max_pipecat > 0:
        try:
            samples, langs, skipped = load_pipecat(args.max_pipecat, zho_target)
            md, _rows, _def = run_dataset(
                f"pipecat-ai/smart-turn-data-v3.2-test (n={len(samples)}, skipped={skipped})",
                samples,
                adapter,
            )
            report_parts.append(md)
            report_parts.append(f"- Language coverage: {dict(langs)}")
            report_parts.append("")
        except Exception as exc:  # noqa: BLE001
            logger.error("pipecat loading failed: %s", exc)
            report_parts.append(f"## pipecat-ai/smart-turn-data-v3.2-test — FAILED: {exc}")
            report_parts.append("")

    if args.easy_turn:
        try:
            samples, cats, skipped = load_easy_turn()
            md, _rows, _def = run_dataset(
                f"ASLP-lab/Easy-Turn-Testset (n={len(samples)}, skipped={skipped})",
                samples,
                adapter,
            )
            report_parts.append(md)
            report_parts.append(
                "- Label map: complete->POSITIVE(1); incomplete->NEGATIVE(0); "
                "wait & backchannel -> merged into NEGATIVE(0). Category counts: "
                f"{dict(cats)}."
            )
            report_parts.append("")
        except Exception as exc:  # noqa: BLE001
            logger.error("Easy-Turn loading failed: %s", exc)
            report_parts.append(f"## ASLP-lab/Easy-Turn-Testset — FAILED: {exc}")
            report_parts.append("")

    report_parts.append("---")
    report_parts.append(
        "Repro note: if a dataset's default-0.5 accuracy is < 0.7, suspect a "
        "preprocessing bug (audio not actually resampled, int16 scaling wrong, "
        "or wrong feature-extractor params) rather than a model issue."
    )

    full_report = "\n".join(report_parts)
    print("\n" + "=" * 60)
    print(full_report)
    print("=" * 60)

    if args.out:
        Path(args.out).write_text(full_report, encoding="utf-8")
        logger.info("report written to %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
