@echo off
echo Building PDF Editor...
pyinstaller pdf-editor.spec --clean
if %ERRORLEVEL% EQU 0 (
    echo.
    echo Build successful! Output: dist\PDF Editor.exe
) else (
    echo.
    echo Build failed!
)
pause
