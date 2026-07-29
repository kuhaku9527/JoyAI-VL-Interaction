# Hybrid Wake Confirmation Spec (v3.17-v3.19, 2026-07-12)

## Problem Statement

`sherpa-onnx` KWS v4 with the tiny 6-token `bt-en` model achieves recall ~49% / FAR 2% in clean conditions. In real use (NVIDIA Broadcast VAD/EC, mic distance, casual speech), recall drops further. The wake word "BT" is fundamentally hard: 2 short syllables with a natural pause, easy to miss or be cut by VAD.

Previous attempts:

- **Microphone gain slider (v3.15)** — addresses input energy but does not fix the acoustic mismatch between KWS scoring and live mic.
- **Pure ASR text matching** — slow (waits for ASR final at 2s stale), high false positive rate (random `b` tokens in background speech).

GAIN cannot solve the recall ceiling: the KWS model needs acoustic features that the input does not deliver.

## Solution

Insert a new state `WAIT_ASR_CONFIRM` between KWS fire and `WAKE_DETECTED`. After KWS fires:

1. Drain any queued audio (existing v3.15 fix).
2. Transition to `WAIT_ASR_CONFIRM` and start ASR streaming on the wake phrase audio.
3. For up to `asr_confirm_timeout_s` (default 1.2 s), watch ASR partials/finals.
4. If ASR text contains any confirm pattern (default `bt` / `BT` / `B T` / `b t`) → promote to `WAKE_DETECTED`, play wake.wav, transition to `DIALOG_ACTIVE`.
5. If no pattern match within timeout → return to `KWS_LISTENING` (false alarm suppressed). No wake.wav, no LLM, no TTS.

Hybrid confirmation improves behavior after KWS fires: false alarms can be rejected before wake.wav/LLM/TTS. It does not recover cases where KWS never fires; KWS recall is handled by `doc/specs/kws-recall-optimization.md`.

## User Stories

1. As a Pilot, when I say "BT", I want Jarvis to wake reliably without me shouting or adjusting my speaking style.
2. As a Pilot, when ambient noise triggers KWS falsely, I do NOT want Jarvis to play wake.wav, talk, or interrupt me.
3. As a developer, I want the hybrid confirmation to log its decision (confirmed / rejected / timeout) so I can measure the recall lift.
4. As a developer, I want the `WAIT_ASR_CONFIRM` timeout to be env-tunable so I can A/B test latency vs recall.

## Implementation Decisions

- New `JarvisState.WAIT_ASR_CONFIRM` enum value.
- New config knobs `asr_confirm_timeout_s` (default 1.2, env `JARVIS_ASR_CONFIRM_TIMEOUT_S`) and `asr_confirm_patterns` (default list, no env override for now).
- Modify `_handle_kws` to call `await self._transition_to(JarvisState.WAIT_ASR_CONFIRM)` after KWS fire instead of `WAKE_DETECTED`.
- New `_handle_wait_asr_confirm(pcm)` method: feed ASR, check text against patterns, schedule timeout task.
- Timeout implementation: `asyncio.create_task(self._wait_asr_confirm_timeout())` started on entry; cancelled on promotion or rejection.
- v3.17/v3.18 reused the v3.15 `_drain_pending_audio`, but live tests showed that was wrong for confirm: it can discard the short wake phrase before ASR hears it.
- v3.17: ASR was initialised lazily inside `_handle_kws` after KWS fire — turned out the 1.2s sherpa-onnx cold load
  consumed the entire 1.2s confirm window, so every wake was rejected as a false alarm.
- v3.18 (current): ASR + KWS are prewarmed by `JarvisSession.start()` via `prewarm_engines()`. The executor
  loads both models (~3-4s one-shot cost when the user clicks Listen) before the bg loop starts, so KWS fire
  always hits a ready ASR stream. `_init_kws`/`_init_asr` remain safe idempotent no-ops.
- v3.19: `_handle_kws(pcm)` feeds the same wake-triggering PCM into ASR immediately. The post-wake pre-confirm drain is removed, and the `WAIT_ASR_CONFIRM` loop no longer sleeps 100 ms between chunks.
- `_reset_to_kws` must also cancel any in-flight `_wait_asr_confirm_timeout` task.

## Testing Decisions

- Unit-test the state machine transitions directly with `JarvisStateMachine.__new__` + a fake `_asr`.
- Test four outcomes:
  - KWS fire → enters WAIT_ASR_CONFIRM
  - WAIT_ASR_CONFIRM + ASR returns "bt" → DIALOG_ACTIVE
  - WAIT_ASR_CONFIRM + ASR returns unrelated text + timeout → KWS_LISTENING
  - WAIT_ASR_CONFIRM + ASR returns "no match" + timeout → KWS_LISTENING (no wake.wav)
- Lock timeout duration via config so tests can set it to 0.05s for speed.


## v3.18 Addendum — Prewarm

Real-mic capture `mic_captures/mic_1783844050536.wav` (15.36s, peak 0.4412) showed KWS firing 3 times but the hybrid path rejecting all 3. Logs proved the cause:

```
KWS fire @ T=0
_init_asr() blocks 1.2s   <-- entire confirm window
ASR ready @ T=1.2s
1.2s timeout @ T=2.4s -> reject
```

Fix: `JarvisSession.start()` now awaits `prewarm_engines()` before launching `run()`. Both models load in the default executor (CPU-bound, releases the GIL during ONNX init). Cost moved from per-wake to per-session. Tests: `test_session_prewarm.py` 3 cases; suite now 55 passed.

Trade-off accepted: clicking Listen waits ~3-4s before "KWS listening" chip lights up. Subsequent wakes confirm in <100ms.

## v3.19 Addendum — Inline ASR Tap

Live testing after prewarm showed a second timing bug: the audio chunk that made KWS fire was not guaranteed to be heard by ASR. The old drain removed queued wake-tail audio, then the confirm window waited on silence.

Fixes:

- Feed the same `pcm` that triggered KWS into `self._asr.feed_chunk(pcm)` immediately inside `_handle_kws`.
- Do not drain queued audio before the confirm window.
- Remove the 100 ms sleep inside the `WAIT_ASR_CONFIRM` run-loop branch.
- Log every confirm-window ASR partial at INFO level.

Tests: `test_hybrid_wake_no_pre_confirm_drain.py` pins inline tap, no pre-confirm drain, and no 100 ms confirm-loop sleep.

## Out of Scope

- Replacing the v4 KWS model or retraining v5.
- Changing the wake word to a longer phrase (deferred — see doc/subsystems/jarvis-mode.md §14.11 future work).
- Adding a second confirmation stage (LLM-side semantic confirmation). Only ASR text matching is in scope.

> **标注（审查组 2026-07-29）**：本 spec 无独立 ADR 链接，但前提仍有效——KWS = sherpa-onnx 进程内、本地部署（见 `决策/服务-语音栈.md` D-047 上下文）。按审计结论留档不改正文；如需追溯，配套决策为 `决策/服务-语音栈.md`。
