# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for WhatsApp Bot backend.
"""
import sys
from pathlib import Path

# Add src to sys.path so PyInstaller finds our modules
sys.path.insert(0, str(Path.cwd() / 'src'))

block_cipher = None

# Collect all our source modules
src_dir = Path.cwd() / 'src'
our_modules = []
for pyfile in src_dir.glob('*.py'):
    if pyfile.name != '__init__.py':
        # Module name without .py
        mod = pyfile.stem
        our_modules.append((str(pyfile), mod))

a = Analysis(
    ['src/backend_launcher.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('src/static', 'static'),
        ('config.yaml', '.'),
    ]
    + (
        # Bundle rapidocr ONNX models (portable path resolution)
        lambda rpath: [
            (str(rpath / 'models'), 'rapidocr/models'),
            (str(rpath / 'config.yaml'), 'rapidocr'),
            (str(rpath / 'default_models.yaml'), 'rapidocr'),
        ]
    )(Path(__import__('rapidocr').__file__).parent)
    + (
        # product_specs.txt is optional (user data, may not exist in CI)
        [('product_specs.txt', '.')] if Path.cwd().joinpath('product_specs.txt').exists() else []
    ),
    hiddenimports=[
        'config',
        'database',
        'admin_api',
        'api_server',
        'bot_state',
        'qr_state',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'apscheduler',
        'python_multipart',
        'openpyxl',
        'PyPDF2',
        'docx',
        'Crypto',
        'xlrd',
        'rapidocr',
        'fitz',
        'cv2',
        'numpy',
        'onnxruntime',
        'country_utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='whatsapp-bot-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='whatsapp-bot-backend',
)
