@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  제미나이 TTS + 캡컷 자동배치
echo ================================================
if "%~1"=="" (
    set /p DIR=프로젝트 폴더 경로를 붙여넣고 Enter를 눌러 주세요:
) else (
    set DIR=%~1
)
python video_builder.py "%DIR%"
pause
