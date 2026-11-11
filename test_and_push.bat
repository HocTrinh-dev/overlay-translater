@echo off
cd /d "%~dp0"
echo ========================================================
echo [STEP 1/2] Running Automated Verification Suite (test_argon.py)
echo ========================================================
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m unittest test_argon.py -v
) else (
    py -m unittest test_argon.py -v
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ABORTED] Tests failed! Fix errors before pushing to GitHub.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo [STEP 2/2] All Tests Passed! Pushing to GitHub...
echo ========================================================
set /p COMMIT_MSG="Enter commit message (default: Update Argon Translator): "
if "%COMMIT_MSG%"=="" set COMMIT_MSG=Update Argon Translator

git add argon_overlay_translator.py launcher.py requirements.txt test_argon.py build_launcher_once.bat test_and_push.bat .gitignore AGENT_HANDOVER.md
git commit -m "%COMMIT_MSG%"
git push -u origin main
pause
