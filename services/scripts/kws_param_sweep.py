"""KWS parameter sweep — find optimum keywords_score by measuring recall + FAR.

Compares (score, threshold) combinations against v4 KWS model.
Reads from /v4 positive + negative sets.

Usage: python services/scripts/kws_param_sweep.py [--quick]
  --quick: only sweep 2 scores (fast sanity check)
"""
import argparse
import sys
import time
import wave
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "asr"))

from services.asr.jarvis.kws import JarvisKWS

KWS_MODEL_DIR = "D:/AI/models/sherpa-onnx/models/kws/bt-en"
POS_DIR = Path("D:/AI/data/kws/bt-en/positive/bt_segments")
NEG_DIR = Path("D:/AI/data/kws/bt-en/negative")


def feed_wav(kws, wav_path):
    with wave.open(str(wav_path), "rb") as wf:
        chunk_size = 1600  # 100ms @ 16kHz int16
        n_hits = 0
        while True:
            data = wf.readframes(chunk_size // 2)
            if not data:
                break
            if kws.feed_audio(data):
                n_hits += 1
        return n_hits


def eval_dir(kws, dir_path, label):
    wavs = sorted(dir_path.glob("*.wav"))
    n = len(wavs)
    hits = 0
    for wav_path in wavs:
        # Each file is an independent utterance/noise sample. Reusing the
        # previous stream makes recall/FAR depend on corpus order.
        kws.start()
        if feed_wav(kws, wav_path) > 0:
            hits += 1
    pct = hits / n * 100 if n else 0
    print(f"  {label}: n={n} hit_wavs={hits} ({pct:.2f}%)")
    return n, hits, pct


def sweep_score(score, threshold):
    print(f"\n=== score={score} th={threshold} ===")
    kws = JarvisKWS(
        model_dir=KWS_MODEL_DIR,
        wake_word="bt",
        keywords_score=score,
        keywords_threshold=threshold,
    )
    n_p, hit_p, rec = eval_dir(kws, POS_DIR, "positive")
    kws.stop()
    del kws
    import gc; gc.collect()

    kws2 = JarvisKWS(
        model_dir=KWS_MODEL_DIR,
        wake_word="bt",
        keywords_score=score,
        keywords_threshold=threshold,
    )
    n_n, hit_n, far = eval_dir(kws2, NEG_DIR, "negative")
    kws2.stop()
    return {"score": score, "th": threshold, "recall_pct": rec, "far_pct": far,
            "pos_n": n_p, "neg_n": n_n, "pos_hit": hit_p, "neg_hit": hit_n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="only 2 scores")
    args = ap.parse_args()

    # Sweep baseline plus recall/FAR tradeoffs around the current clean-mic range.
    configs = [(10.0, 0.25)]
    if not args.quick:
        configs.extend([
            (10.0, 0.20),
            (8.0, 0.25),
            (8.0, 0.20),
            (8.0, 0.30),
            (12.0, 0.20),
            (12.0, 0.25),
        ])
    else:
        configs.extend([(10.0, 0.20)])


    results = [sweep_score(s, t) for s, t in configs]

    print("\n=== KWS Sweep Summary ===")
    print(f"{'score':>6} {'th':>6} {'recall%':>9} {'FAR%':>7} {'rec*(1-FAR)':>12}")
    for r in results:
        combined = r["recall_pct"] * (1 - r["far_pct"] / 100)
        print(f"{r['score']:>6.1f} {r['th']:>6.2f} {r['recall_pct']:>9.2f} {r['far_pct']:>7.2f} {combined:>12.2f}")

    best = max(results, key=lambda r: r["recall_pct"] * (1 - r["far_pct"] / 100))
    print(f"\nBest: score={best['score']}, th={best['th']}, recall={best['recall_pct']:.2f}%, FAR={best['far_pct']:.2f}%")


if __name__ == "__main__":
    main()
