@echo off
REM ============================================
REM  WhatsApp Bot - Windows Build Script
REM  在 Windows 机器上运行此脚本进行打包
REM ============================================

echo === Step 1: Create Python virtual environment ===
python -m venv winenv
call winenv\Scripts\activate.bat

echo === Step 2: Install dependencies ===
pip install -r requirements.txt

echo === Step 3: Build Python backend with PyInstaller ===
pyinstaller backend.spec --distpath dist --workpath build --clean

echo === Step 4: Install Node.js dependencies ===
cd desktop
call npm install

echo === Step 5: Build Electron app (NSIS installer) ===
call npx electron-builder --win

echo === Done! ===
echo Output: desktop\dist\WhatsApp-机器人 Setup 1.0.0.exe
pause
