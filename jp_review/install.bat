@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  [일본 영상 검토] 설치 (최초 1회만)
echo ================================================
python -m pip install -r requirements.txt
echo.
echo 설치가 끝났습니다. 이제 review.bat 을 실행하면 됩니다.
pause
