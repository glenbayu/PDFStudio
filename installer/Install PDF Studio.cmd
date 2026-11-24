@echo off
title PDF Studio - Setup
echo.
echo  ============================================
echo   PDF Studio - Pemasangan
echo  ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Pemasangan gagal. Jalankan install.ps1 lewat PowerShell untuk detail.
  pause
)
