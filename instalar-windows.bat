@echo off
setlocal
title Instalar Presentador Fotos NAS v2.4

where py >nul 2>nul || (
  echo No se encontro Python. Instalalo desde https://www.python.org/downloads/windows/
  echo Marca la opcion "Add Python to PATH" durante la instalacion.
  pause
  exit /b 1
)

py -m pip install --user --upgrade Pillow pillow-heif || exit /b 1
set "APPDIR=%LOCALAPPDATA%\PresentadorFotosNAS"
if not exist "%APPDIR%" mkdir "%APPDIR%"
copy /Y "%~dp0presentador_fotos_windows.pyw" "%APPDIR%\presentador_fotos_windows.pyw" >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Presentador Fotos NAS.lnk');$s.TargetPath='%APPDIR%\presentador_fotos_windows.pyw';$s.WorkingDirectory='%APPDIR%';$s.Save()"

echo.
echo Presentador Fotos NAS v2.4 instalado correctamente.
echo Se ha creado un acceso directo en el Escritorio.
pause
