@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  [네이버 카페 캡쳐] 설치 (최초 1회만)
echo ================================================
python -m pip install -r requirements.txt
python -m playwright install chromium
echo.
echo 설치가 끝났습니다. 다음으로 login.bat 을 실행해 주세요.
pause
