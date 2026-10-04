@echo off
rem Builds "Local AI.exe" (the starter with the app icon) into the app folder, with the C# compiler that is part of
rem Windows (.NET Framework 4). Nothing to install; the .exe runs on any Windows 10 or 11.
set ROOT=%~dp0..\..
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
"%CSC%" /nologo /target:winexe /optimize+ /win32icon:"%ROOT%\icon.ico" /r:System.Windows.Forms.dll /out:"%ROOT%\Local AI.exe" "%~dp0Launcher.cs"
