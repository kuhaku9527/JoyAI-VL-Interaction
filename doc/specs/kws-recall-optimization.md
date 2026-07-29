# KWS Recall Optimization Spec (v3.20, 2026-07-12)

## Problem Statement

The Pilot says "BT" but the always-on listener often does not wake. The current KWS v4 model has measured recall of 49.06% on the existing positive set. Hybrid KWS + ASR confirmation only runs after KWS fires, so it reduces false wakes but cannot recover cases where KWS never triggers.

The system also lacked evidence for misses: when KWS did not fire, the backend did not record what the microphone heard, whether ASR could hear "BT", or which live samples should be used for retraining.

## Solution

Keep KWS as the production wake owner and add diagnostic observability around missed wakes:

1. Save rolling live KWS input windows as 16 kHz mono PCM WAV files when speech-like energy is detected.
2. Run ASR shadow during `KWS_LISTENING` for diagnostics only. It logs partial text when KWS misses but does not wake Jarvis.
3. Keep the current KWS default parameters because full sweep showed no better recall/FAR tradeoff.
4. Use captured live samples to build the KWS v5 dataset: positives, hard negatives, and Broadcast/WebRTC-domain examples.

## User Stories

1. As the Pilot, I want the system to show evidence when "BT" does not wake, so that I am not guessing whether the mic, KWS, or ASR failed.
2. As the Pilot, I want missed wake samples saved automatically, so that retraining uses my real microphone path.
3. As a developer, I want ASR shadow logs during listening, so that I can tell whether KWS missed a phrase ASR could understand.
4. As a developer, I want ASR shadow to stay diagnostic-only, so that pure text matching does not reintroduce false wakes.
5. As a developer, I want KWS parameter decisions based on sweep results, so that we do not degrade false alarm rate by guessing.

## Implementation Decisions

- `JarvisStateMachine` now records rolling PCM while in `KWS_LISTENING`.
- Speech-like windows are written to `D:/AI/data/kws/mic_captures/kws_live_*.wav` with peak/RMS in the filename.
- `JARVIS_KWS_SHADOW_ASR=true` enables ASR shadow in listening mode. The shadow path logs text and explicit `KWS MISS` lines when ASR sees a wake pattern but KWS did not fire.
- ASR shadow never transitions to `WAKE_DETECTED` or `DIALOG_ACTIVE`.
- `JARVIS_KWS_CAPTURE_*` env knobs control capture directory, window, interval, and peak threshold.
- Full KWS sweep remains the gate for changing `JARVIS_KWS_SCORE` or `JARVIS_KWS_THRESHOLD` defaults.
- `services/scripts/analyze_kws_captures.py` batches saved WAVs through the current KWS and ASR models and prints `file / kws_hit / asr_text / duration_s`.
- v3.21 adds fresh-window KWS probing: when the long-running live KWS stream misses, the state machine periodically re-runs KWS over recent rolling PCM using a clean stream. This directly addresses the observed case where `kws_live_1783848515550_0002...wav` woke offline but not live.

Current sweep result:

| score | threshold | recall | FAR | decision |
| - | - | -: | -: | - |
| 10.0 | 0.25 | 49.06% | 2.00% | keep default |
| 10.0 | 0.20 | 49.06% | 2.00% | no recall gain |
| 8.0 | 0.25 | 49.06% | 9.00% | reject |
| 12.0 | 0.25 | 13.21% | 1.50% | reject |

## Testing Decisions

- Unit-test the state machine directly: KWS miss + ASR shadow `bt` must log the miss while staying in `KWS_LISTENING`.
- Unit-test diagnostic WAV output: saved files must be 16 kHz mono PCM16.
- Unit-test fresh-window recovery: live stream `feed_audio` can miss while `detect_in_pcm` hits, and that path must wake for recall testing.
- Config tests cover the new diagnostic env vars.
- Static WebUI tests pin the visible `WAIT_ASR_CONFIRM` badge and status wrapping, because these are debugging affordances during live wake tests.

## Out of Scope

- Promoting ASR shadow to wake fallback automatically.
- Changing the wake word.
- Retraining KWS v5 in this patch. This patch creates the data capture and evidence needed for v5.
- Replacing sherpa-onnx KWS with a different wake-word engine.

## Further Notes

NVIDIA Broadcast can help by lowering background noise, but it can also reshape short consonants and trailing silence. That makes live-domain samples mandatory. The next useful manual test is 10-20 "BT" attempts while listening is active, then reviewing `webui.err.log` and the saved `kws_live_*.wav` captures.

> **标注（审查组 2026-07-29）**：本 spec 无独立 ADR 链接，但前提仍有效——KWS = sherpa-onnx 进程内、本地部署（见 `决策/服务-语音栈.md` D-047 上下文）。按审计结论留档不改正文；如需追溯，配套决策为 `决策/服务-语音栈.md`。
