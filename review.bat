@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  일본 영상 프로젝트 검토
echo ================================================
if "%~1"=="" (
    set /p DIR=검토할 프로젝트 폴더 경로를 붙여넣고 Enter를 눌러 주세요:
) else (
    set DIR=%~1
)
python japan_review.py "%DIR%"
pause
