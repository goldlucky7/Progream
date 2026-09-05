@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  검토 프로그램에 필요한 부품만 설치합니다.
echo  (네이버 캡쳐까지 쓸 거라면 install.bat 을 실행하세요)
echo ================================================
python -m pip install Pillow openpyxl mutagen imageio-ffmpeg
echo.
echo 설치가 끝났습니다. 이제 review.bat 을 실행해 주세요.
pause
