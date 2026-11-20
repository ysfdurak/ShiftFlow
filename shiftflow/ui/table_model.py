"""Büyük tablolar için sanal tablo modeli.

QTableView yalnızca ekranda görünen hücreleri ister; model de değeri o
anda biçimlendirir. Bu sayede 1 milyon satırlık tablo da açılır, çünkü
hiçbir zaman tüm hücreler için nesne oluşturulmaz.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from ..engine.values import type_label


def format_value(v) -> str:
    if v is None or v is pd.NA or v is pd.NaT:
        return ""
    if isinstance(v, (float, np.floating)):
        if math.isnan(v):
            return ""
        if float(v).is_integer() and abs(v) < 1e15:
            return f"{int(v):,}".replace(",", ".")
        s = f"{v:,.4f}".rstrip("0").rstrip(".")
        return s.replace(",", "§").replace(".", ",").replace("§", ".")
    if isinstance(v, (int, np.integer)) and not isinstance(v, bool):
        return f"{int(v):,}".replace(",", ".")
    if isinstance(v, (pd.Timestamp, datetime, np.datetime64)):
        ts = pd.Timestamp(v)
        if pd.isna(ts):
            return ""
        if ts.hour or ts.minute or ts.second:
            return ts.strftime("%d.%m.%Y %H:%M")
        return ts.strftime("%d.%m.%Y")
    if isinstance(v, (bool, np.bool_)):
        return "Evet" if v else "Hayır"
    return str(v)


def copy_value(v) -> str:
    """Panoya kopyalanacak değer: Excel'in Türkçe ayarında doğru okunur."""
    if isinstance(v, (float, np.floating)) and not math.isnan(v):
        return (str(int(v)) if float(v).is_integer() else repr(float(v))).replace(".", ",")
    if isinstance(v, (int, np.integer)) and not isinstance(v, bool):
        return str(int(v))
    return format_value(v)


class DataFrameModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._df = pd.DataFrame()
        self._cols: list[np.ndarray] = []
        self._numeric: list[bool] = []
        self._types: list[str] = []
        self._muted = QBrush(QColor("#9aa4ad"))
        self._hcolors: dict[str, QColor] = {}  # formülde kullanılan sütunların rengi
        self._icons: dict[str, object] = {}

    def set_header_colors(self, colors: dict):
        """Formülde kullanılan sütunları başlıkta renkli gösterir (Excel'deki renkli başvurular gibi)."""
        from PySide6.QtGui import QIcon, QPixmap
        self._hcolors = {str(k): QColor(v) for k, v in (colors or {}).items()}
        self._icons = {}
        for k, c in self._hcolors.items():
            pm = QPixmap(10, 10)
            pm.fill(c)
            self._icons[k] = QIcon(pm)
        if self._df.shape[1]:
            self.headerDataChanged.emit(Qt.Horizontal, 0, self._df.shape[1] - 1)

    def set_frame(self, df: pd.DataFrame | None):
        self.beginResetModel()
        self._df = df if df is not None else pd.DataFrame()
        self._cols = [self._df.iloc[:, i].to_numpy() for i in range(self._df.shape[1])]
        self._numeric = [
            pd.api.types.is_numeric_dtype(self._df.iloc[:, i]) and not pd.api.types.is_bool_dtype(self._df.iloc[:, i])
            for i in range(self._df.shape[1])
        ]
        self._types = [type_label(self._df.iloc[:, i]) for i in range(self._df.shape[1])]
        self.endResetModel()

    def frame(self) -> pd.DataFrame:
        return self._df

    def raw_value(self, row: int, col: int):
        return self._cols[col][row]

    def is_numeric(self, col: int) -> bool:
        return self._numeric[col]

    # Qt arayüzü --------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._df.shape[1]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return format_value(self._cols[index.column()][index.row()])
        if role == Qt.TextAlignmentRole:
            if self._numeric[index.column()]:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if section >= self._df.shape[1]:
                return None
            if role == Qt.DisplayRole:
                return str(self._df.columns[section])
            if role == Qt.ToolTipRole:
                return f"{self._df.columns[section]}\nTip: {self._types[section]}\nSağ tık: işlemler"
            name = str(self._df.columns[section])
            if name in self._hcolors:
                if role == Qt.ForegroundRole:
                    return QBrush(self._hcolors[name])
                if role == Qt.DecorationRole:
                    return self._icons.get(name)
                if role == Qt.FontRole:
                    from PySide6.QtGui import QFont
                    f = QFont()
                    f.setBold(True)
                    return f
        else:
            if role == Qt.DisplayRole:
                return str(section + 1)
            if role == Qt.ForegroundRole:
                return self._muted
        return None

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable
