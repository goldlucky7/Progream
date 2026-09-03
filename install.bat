@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  필요한 프로그램을 설치합니다. (최초 1회만)
echo ================================================
python -m pip install -r requirements.txt
python -m playwright install chromium
echo.
echo 설치가 끝났습니다. 다음으로 login.bat 을 실행해 주세요.
pause
