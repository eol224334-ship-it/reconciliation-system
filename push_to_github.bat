@echo off
chcp 65001 >nul

echo ============================================
echo   Push to GitHub
echo   After push, Render will auto-redeploy
echo ============================================
echo.
echo   Script version: 2026-07-13-v2
echo.

set "GIT=C:\Users\ZhuanZ1\.workbuddy\vendor\PortableGit\mingw64\bin\git.exe"
set "PROJECT=C:\Users\ZhuanZ1\WorkBuddy\2026-07-06-16-48-34\reconciliation-system"

cd /d "%PROJECT%"
if %ERRORLEVEL% neq 0 (
  echo ERROR: project dir not found: %PROJECT%
  pause
  exit /b 1
)

echo Detecting system proxy...
set "PROXY="
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable 2^>nul') do set "PE=%%b"
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2^>nul') do set "PS=%%b"

if /I "%PE%"=="0x1" if defined PS (
  echo %PS%|findstr ":" >nul
  if %ERRORLEVEL% equ 0 (
    echo %PS%|findstr "=" >nul
    if %ERRORLEVEL% equ 1 (
      set "PROXY=http://%PS%"
      echo Detected Windows proxy: %PROXY%
    )
  )
)

if not defined PROXY if not "%http_proxy%"=="" set "PROXY=%http_proxy%"
if not defined PROXY if not "%https_proxy%"=="" set "PROXY=%https_proxy%"

if defined PROXY (
  echo Applying proxy: %PROXY%
  set "http_proxy=%PROXY%"
  set "https_proxy=%PROXY%"
)

echo.
echo Running: git push origin main
echo.

"%GIT%" push origin main

if %ERRORLEVEL% neq 0 (
  echo.
  echo ============================================
  echo   PUSH FAILED
  echo   Reason: unable to reach GitHub
  echo.
  echo   Solutions:
  echo   1. Connect to a mobile hotspot and retry
  echo   2. Start a proxy/VPN tool (Clash, v2rayN, etc.) and retry
  echo   3. If you know your proxy address, set http_proxy/https_proxy
  echo      environment variables and retry
  echo ============================================
  pause
  exit /b %ERRORLEVEL%
)

echo.
echo ============================================
echo   PUSH SUCCESS!
echo   Wait 1-2 minutes, then refresh:
echo   https://reconciliation-system-edl7.onrender.com/
echo ============================================
echo.
pause
