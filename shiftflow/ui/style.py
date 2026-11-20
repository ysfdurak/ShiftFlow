"""Uygulama görünümü: sade, Excel'e yakın, açık tema."""

STYLE = """
QMainWindow, QDialog { background: #f4f6f8; }
QToolBar { background: #ffffff; border: none; border-bottom: 1px solid #d9dee3; spacing: 2px; padding: 3px; }
QToolBar QToolButton { padding: 5px 10px; border-radius: 4px; color: #1f2a33; }
QToolBar QToolButton:hover { background: #e4eef6; }
QToolBar QToolButton:disabled { color: #a5adb4; }
QToolButton#buildButton { background: #1f6fb2; color: #ffffff; font-weight: 700; padding: 5px 14px; }
QToolButton#buildButton:hover { background: #185a91; }
QToolButton#buildButton:disabled { background: #b9c6d2; color: #eef2f5; }
QTabWidget#ribbon QTabBar::tab { padding: 4px 14px; }
QTabWidget#ribbon QTabBar::tab:selected { font-weight: 700; color: #1f6fb2; }
QToolBar#ribbonBar { border: none; }
QToolButton#paletteButton { border: 1px solid #c3ccd4; background: #f7f9fb; padding: 4px 12px; }
QDialog#palette { background: #ffffff; border: 1px solid #9fb3c6; border-radius: 6px; }
QDialog#palette QLineEdit { font-size: 15px; padding: 7px 9px; }
QDialog#palette QListWidget::item { padding: 6px 8px; }
QDockWidget { font-weight: 600; color: #33404b; }
QDockWidget::title { background: #e9edf1; padding: 5px 8px; }
QListWidget { background: #ffffff; border: 1px solid #d9dee3; border-radius: 4px; }
QListWidget::item { padding: 5px 6px; border-bottom: 1px solid #eef1f4; }
QListWidget::item:selected { background: #d6e6f5; color: #10202e; }
QTableView { background: #ffffff; gridline-color: #e1e5e9; border: 1px solid #cfd6dc;
             selection-background-color: #cde2f6; selection-color: #10202e; alternate-background-color: #fafbfc; }
QHeaderView::section { background: #eef1f4; color: #26323c; padding: 4px 6px; border: none;
                       border-right: 1px solid #d5dbe0; border-bottom: 1px solid #c9d0d6; font-weight: 600; }
QHeaderView::section:checked { background: #d6e6f5; }
QLabel#datasetTitle { font-size: 15px; padding: 2px 2px 4px 2px; color: #1f2a33; }
QLabel#banner { background: #fff4d6; border: 1px solid #ecd28c; border-radius: 4px; padding: 6px 8px; color: #5c4300; }
QLabel#messages { color: #3a4752; padding: 4px 2px; }
QLabel#emptyHint { color: #4a5864; font-size: 13px; }
QLabel#dialogHelp { color: #55626d; padding: 2px 0 6px 0; }
QLabel#dialogTarget { background: #e4eef6; border-radius: 4px; padding: 5px 8px; color: #173a5a; }
QLabel#dialogStatus { padding: 4px 0; }
QLabel#signature { color: #4a3a6b; background: #f3eef9; border-radius: 3px; padding: 3px 6px; }
QLabel#signature:!enabled { background: transparent; }
QPushButton { background: #ffffff; border: 1px solid #c3ccd4; border-radius: 4px; padding: 4px 10px; }
QPushButton:hover { background: #eaf2f9; }
QPushButton:disabled { color: #a5adb4; }
QDialogButtonBox QPushButton { min-width: 90px; padding: 6px 12px; }
QGroupBox { border: 1px solid #d5dbe0; border-radius: 4px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #33404b; }
QComboBox QAbstractItemView { background: #ffffff; color: #1f2a33; selection-background-color: #cde2f6;
                              selection-color: #10202e; outline: 0; }
QLineEdit, QComboBox, QPlainTextEdit { background: #ffffff; border: 1px solid #c3ccd4; border-radius: 3px; padding: 3px 5px; }
QStatusBar { background: #e9edf1; color: #33404b; }
"""
