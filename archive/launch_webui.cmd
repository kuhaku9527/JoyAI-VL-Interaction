@echo off
cd /d "D:\AI\workspace\JoyAI-VL-Interaction-main\services\webui"
"D:\AI\envs\joyai-main\python.exe" -u -m joy_interaction_webui.server 1>"D:\AI\workspace\JoyAI-VL-Interaction-main\services\.logs\webui.out.log" 2>"D:\AI\workspace\JoyAI-VL-Interaction-main\services\.logs\webui.err.log"
