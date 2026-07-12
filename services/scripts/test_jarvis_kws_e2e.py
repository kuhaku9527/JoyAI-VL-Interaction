"""End-to-end test for Jarvis KWS integration.

Loads the trained v4 BT KWS model via JarvisKWS, feeds positive + negative wavs,
and reports:
  - Recall (% of positive wavs with at least one detection)
  - FAR    (% of negative wavs with at least one detection)
  - Hit distribution

Run: python services/scripts/test_jarvis_kws_e2e.py
"""
import sys
import time
import wave
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))            # for "services.asr.jarvis.kws" import
sys.path.insert(0, str(REPO / "services" / "asr"))

from services.asr.jarvis.kws import JarvisKWS  # noqa: E402

# === Config (mirrors JarvisConfig defaults) ===
KWS_MODEL_DIR = "D:/AI/models/sherpa-onnx/models/kws/bt-en"
WAKE_WORD = "bt"
KW_SCORE = 10.0
KW_THRESHOLD = 0.25
NUM_THREADS = 1

POS_DIR = Path("D:/AI/data/kws/bt-en/positive/bt_segments")
NEG_DIR = Path("D:/AI/data/kws/bt-en/negative")
TEST_WAV = Path("D:/AI/data/kws/bt-en/test_bt.wav")  # 114s 全长录音 (10 遍 BT)


def feed_wav(kws, wav_path):
    """Feed a 16kHz mono int16 wav to KWS, return hit count."""
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 1, f"{wav_path}: mono only"
        assert wf.getsampwidth() == 2, f"{wav_path}: int16 only"
        assert wf.getframerate() == 16000, f"{wav_path}: 16kHz only"
        chunk_size = 1600
        n_hits = 0
        while True:
            data = wf.readframes(chunk_size // 2)
            if not data:
                break
            if kws.feed_audio(data):
                n_hits += 1
        return n_hits


def eval_dir(kws, wav_dir, label):
    wavs = sorted(wav_dir.glob("*.wav"))
    n_total = len(wavs)
    n_hit_wavs = 0
    hits_per_wav = []
    for w in wavs:
        kws.start()
        h = feed_wav(kws, w)
        hits_per_wav.append((w.name, h))
        if h > 0:
            n_hit_wavs += 1
    rate = n_hit_wavs / n_total if n_total else 0
    total_hits = sum(h for _, h in hits_per_wav)
    avg = total_hits / n_total if n_total else 0
    print(f"\n=== {label} ===")
    print(f"  总数={n_total}  触发 wav={n_hit_wavs} ({rate:.2%})  总命中={total_hits}  均值={avg:.2f} 次/wav")
    cnt = Counter(h for _, h in hits_per_wav)
    print(f"  命中数分布: {dict(sorted(cnt.items()))}")
    top = sorted([(n, h) for n, h in hits_per_wav if h > 0], key=lambda x: -x[1])[:5]
    if top:
        print(f"  触发 top5:")
        for name, h in top:
            print(f"    {h:3d} hits : {name}")


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("test_kws_e2e")

    print("=" * 60)
    print("KWS 端到端测试 — v4 trained model (bt-en)")
    print(f"  model_dir  = {KWS_MODEL_DIR}")
    print(f"  wake_word  = {WAKE_WORD!r}")
    print(f"  score      = {KW_SCORE} (sweet spot for v4)")
    print(f"  threshold  = {KW_THRESHOLD}")
    print("=" * 60)

    print("\n[1/3] 加载 JarvisKWS ...")
    t0 = time.time()
    kws = JarvisKWS(
        model_dir=KWS_MODEL_DIR,
        wake_word=WAKE_WORD,
        num_threads=NUM_THREADS,
        keywords_score=KW_SCORE,
        keywords_threshold=KW_THRESHOLD,
    )
    kws.start()
    print(f"  [OK] 加载成功 ({time.time()-t0:.2f}s)")

    if TEST_WAV.exists():
        print(f"\n[2/3] 全长 BT 测试录音: {TEST_WAV.name}")
        kws.start()
        n = feed_wav(kws, TEST_WAV)
        print(f"  共 {n} 次命中 ({n/114.05:.2f} 次/秒, 期望 ~5-10 命中)")

    if POS_DIR.exists():
        print(f"\n[3/3] 批量评估")
        eval_dir(kws, POS_DIR, f"正样本 (recall) — {POS_DIR.name}")
    if NEG_DIR.exists():
        eval_dir(kws, NEG_DIR, f"负样本 (FAR) — {NEG_DIR.name}")


if __name__ == "__main__":
    main()
