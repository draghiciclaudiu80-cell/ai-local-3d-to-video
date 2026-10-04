@echo off
rem AI Local (beta) - double-click to install or repair it in this folder (downloads ~8 GB, each file checked).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
