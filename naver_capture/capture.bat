@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  네이버 카페 글 캡쳐
echo ================================================
set /p URL=캡쳐할 카페 글 주소를 붙여넣고 Enter를 눌러 주세요:
python naver_capture.py "%URL%"
pause
