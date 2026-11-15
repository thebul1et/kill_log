@echo off
cd /d "%~dp0"
echo === Rob Run Death Log: building the Windows app ===
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail
python -m PyInstaller --noconfirm --clean --windowed --name RobRunDeathLog --collect-all rapidocr_onnxruntime --hidden-import pystray._win32 --add-data "config.json;." --add-data "killlog.html;." app.py
if errorlevel 1 goto fail
echo.
echo The app is built: dist\RobRunDeathLog\RobRunDeathLog.exe
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto noinno
"%ISCC%" installer.iss
echo.
echo Installer ready: installer\RobRunDeathLog-Setup.exe
goto done
:noinno
echo Inno Setup was not found, so no Setup.exe was made. Install it from jrsoftware.org
echo and run this again. You can still run dist\RobRunDeathLog\RobRunDeathLog.exe directly.
:done
pause
exit /b 0
:fail
echo.
echo Something failed. Scroll up for the red error text and send it to whoever is helping you.
pause
exit /b 1
