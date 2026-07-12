# Event response audio files for BT-7274 Jarvis mode
# ===================================================
# wake.wav    = PLACEHOLDER (copy of "协议一，连线铁御.wav" until TTS-generated)
#              Final text: "铁御，我在" — TTS-generated once MiniMax plan active.
# goodbye.wav = PLACEHOLDER (copy of "协议二，坚守任务.wav" until TTS-generated)
#              Final text: "任务完成，断开神经链接" — TTS-generated once MiniMax plan active.
# error.wav   = "铁御，必须先建立神经链接才能继续" (copied from ref_audio/1.BT-7274/)
#
# To regenerate wake.wav + goodbye.wav with the real voice:
#   1. Buy a MiniMax plan and set MINIMAX_API_KEY + MINIMAX_GROUP_ID
#   2. Make sure voice_clone_api (port 8985) is up and connected to MiniMax
#   3. Run: python services/scripts/generate_event_audio.py --voice-id bt-7274
#      (registers ref audio as a MiniMax voice, then synthesizes both events)
