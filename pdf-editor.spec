# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'src',
        'src.main_window',
        'src.graphics_view',
        'src.models',
        'src.models.annotation',
        'src.items',
        'src.items.sticky_note',
        'src.items.text_block',
        'src.dialogs',
        'src.dialogs.helpers',
        'src.dialogs.link',
        'src.dialogs.stamp',
        'src.dialogs.signature',
        'src.dialogs.page_number',
        'src.dialogs.header_footer',
        'src.dialogs.watermark',
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
    a.binaries,
    a.datas,
    [],
    name='PDF Editor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path here: icon='assets/icon.ico'
)
