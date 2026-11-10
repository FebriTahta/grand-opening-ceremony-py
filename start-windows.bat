@echo off
rem Dobel-klik untuk menjalankan Grand Opening Ceremony di Windows.
cd /d "%~dp0"
where uv >nul 2>nul || (echo uv belum terpasang. Lihat README bagian Instalasi Windows. & pause & exit /b 1)
uv run ceremony %*
if errorlevel 1 pause
