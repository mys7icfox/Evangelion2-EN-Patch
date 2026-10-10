@echo off
rem Drag your Japanese Evangelion 2 .iso onto this file, or double-click and type the path.
setlocal
set ISO=%~1
if "%ISO%"=="" set /p ISO=Path to your Japanese Evangelion 2 ISO: 
python "%~dp0apply_patch.py" "%ISO%" "%~dp0EVA2_EN_beta.patch"
pause
