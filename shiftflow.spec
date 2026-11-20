# PyInstaller paket tanımı. Kullanım: pyinstaller --noconfirm shiftflow.spec
# Tek klasör (onedir) seçildi: tek dosyaya göre çok daha hızlı açılır ve
# antivirüs yazılımlarınca daha az yanlış alarm verir.

block_cipher = None

a = Analysis(
    ["shiftflow_main.py"],
    pathex=["."],
    binaries=[],
    datas=[("docs/KULLANIM_KILAVUZU.md", "docs"), ("docs/ekran", "docs/ekran")],
    hiddenimports=["python_calamine", "openpyxl.cell._writer", "win32com", "win32com.client", "pythoncom", "pywintypes",
                   "pywinauto", "pywinauto.controls.uiawrapper", "comtypes", "comtypes.client"],
    # pandas'ın isteğe bağlı bağımlılıkları pakete girmesin (boyut).
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "scipy", "PIL", "lxml", "bs4", "sqlalchemy",
              "pyarrow", "numexpr", "bottleneck", "tables", "jinja2", "xlsxwriter", "PySide6.QtWebEngineCore",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="ShiftFlow",
    console=False, debug=False, strip=False, upx=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="ShiftFlow")
