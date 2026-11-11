@echo off
cd /d "%~dp0"
echo ========================================================
echo Building ArgonTranslator.exe (ONE-TIME HYBRID LAUNCHER)
echo ========================================================
if exist ".venv\Scripts\pyinstaller.exe" (
    .venv\Scripts\pyinstaller.exe --onefile --noconsole --name "ArgonTranslator" --add-data "argon_overlay_translator.py;." launcher.py
) else (
    pyinstaller --onefile --noconsole --name "ArgonTranslator" --add-data "argon_overlay_translator.py;." launcher.py
)

if exist "dist\ArgonTranslator.exe" (
    copy /Y "dist\ArgonTranslator.exe" ".\ArgonTranslator.exe" >nul
    echo.
    echo [SUCCESS] ArgonTranslator.exe has been copied to the current folder!
    echo From now on, whenever you push changes to argon_overlay_translator.py on GitHub,
    echo just click "Hot Update" inside the app (or restart ArgonTranslator.exe) — NO rebuild needed!
) else (
    echo.
    echo [ERROR] Build failed. Make sure Python and PyInstaller are installed.
)
pause
