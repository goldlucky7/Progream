@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  일본 영상 검토 프로그램
echo.
echo  검토할 자료를 폴더 하나에 모아 두세요:
echo   - 영상(mp4), 이미지들, 대본(txt),
echo   - 자막(srt, Vrew에서 내보내기), 매칭표
echo ================================================
set /p FOLDER=그 폴더를 이 창에 드래그해서 놓고 Enter:
set FOLDER=%FOLDER:"=%
python jp_review.py "%FOLDER%"
echo.
echo 폴더 안의 "검토보고서.html" 을 더블클릭하면 결과를 볼 수 있습니다.
pause
