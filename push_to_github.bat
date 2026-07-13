@echo off
chcp 65001 >nul
echo ============================================
echo   Reconciliation System - Push to GitHub
echo   After push, Render will auto-redeploy
echo ============================================
echo.

set GIT="C:\Users\ZhuanZ1\.workbuddy\vendor\PortableGit\mingw64\bin\git.exe"
set PROJECT="C:\Users\ZhuanZ1\WorkBuddy\2026-07-06-16-48-34\reconciliation-system"

echo [1/2] Entering project dir...
cd /d %PROJECT%
if errorlevel 1 (
  echo ERROR: project dir not found: %PROJECT%
  pause
  exit /b 1
)

echo [2/2] Running: git push origin main
echo.
%GIT% push origin main

echo.
if errorlevel 1 (
  echo ============================================
  echo   PUSH FAILED. Possible reasons:
  echo   1. Network cannot reach GitHub (corp/school firewall)
  echo   2. Proxy required to access external network
  echo   Please check network and retry, or contact admin.
  echo ============================================
) else (
  echo ============================================
  echo   PUSH SUCCESS! Wait 1-2 min, then refresh:
  echo   https://reconciliation-system-edl7.onrender.com/
  echo ============================================
)
echo.
pause
