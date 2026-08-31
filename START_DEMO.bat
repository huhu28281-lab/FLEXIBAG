@echo off
setlocal
cd /d "%~dp0"

echo 실시간 메일 수신 서버를 시작합니다...
if exist "FlexibagMailServer.exe" (
    start "FLEXIBAG Live Mail Server" /min "FlexibagMailServer.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python이 설치되어 있지 않고 FlexibagMailServer.exe도 없습니다.
        echo https://www.python.org/downloads/ 에서 Python 설치 후 다시 실행해주세요.
        pause
        exit /b 1
    )
    start "FLEXIBAG Live Mail Server" /min cmd /c "python scripts\live_email_dashboard.py"
)

echo 서버가 준비될 때까지 잠시 기다립니다...
timeout /t 3 /nobreak >nul

echo 화면을 엽니다...
start "" "flexibag-inventory-ai-ocr.html"

echo.
echo 데모 화면이 열렸습니다. 이 창은 닫아도 되지만,
echo 방금 뜬 "FLEXIBAG Live Mail Server" 창은 데모가 끝날 때까지 닫지 마세요.
pause
