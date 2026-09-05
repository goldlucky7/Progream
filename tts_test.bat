@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  제미나이 TTS 목소리 테스트
echo ================================================
python tts_test.py
pause
