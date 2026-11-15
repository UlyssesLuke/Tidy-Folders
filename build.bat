@echo off
rem Builds "dist\Tidy Folders.exe". Double-click this file, or run build.bat in a terminal.
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo Creating build environment in .venv ...
    python -m venv .venv || goto :error
)
echo Checking build tools ...
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || goto :error

rem The app icon is made from the logo (tidy_folders\assets\logo\24.png), so redraw it each build.
"%PY%" packaging\make_icon.py || goto :error

echo Building the .exe ...
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN ^
    --onefile --windowed ^
    --name "Tidy Folders" ^
    --hidden-import pystray._win32 ^
    --icon "%~dp0tidy_folders\assets\icon.ico" ^
    --add-data "%~dp0tidy_folders\assets;tidy_folders\assets" ^
    --version-file "%~dp0packaging\version_info.txt" ^
    --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0build" ^
    "%~dp0Tidy Folders.pyw" || goto :error

rem Tell open File Explorer windows to redraw the .exe's icon (otherwise they can show an old one).
"%PY%" packaging\refresh_icon.py "%~dp0dist\Tidy Folders.exe"

echo.
echo Done: dist\Tidy Folders.exe
exit /b 0

:error
echo.
echo Build failed. See the messages above.
exit /b 1
