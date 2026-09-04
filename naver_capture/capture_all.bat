@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist links.txt (
  echo 여기에 캡쳐할 카페 글 주소를 붙여넣으세요. 한 줄에 하나씩, 몇 개든 됩니다.> links.txt
)
echo ================================================
echo  잠시 후 메모장이 열립니다.
echo.
echo  1. 캡쳐할 카페 글 주소들을 전부 붙여넣으세요
echo     (한 줄에 하나씩, 개수 제한 없음)
echo  2. 저장(Ctrl+S)하고 메모장을 닫으세요
echo  3. 닫는 순간 자동으로 전부 캡쳐됩니다
echo ================================================
notepad links.txt
python naver_capture.py --file links.txt
pause
