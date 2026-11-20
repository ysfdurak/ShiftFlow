"""Excel COM nesnelerini taklit eden sahte sınıflar.

Gerçek Excel'in döndürdüğü yapılar taklit edilir: Range.Value iç içe
demet (tek hücrede düz değer), Workbook.Path kaydedilmemişse boş metin,
tarihler datetime. Bu sayede ComExcelProvider'ın Windows'a özgü
olmayan tüm kodu Linux'ta da test edilir.
"""

from datetime import datetime


class _Count:
    def __init__(self, n):
        self.Count = n


class FakeRange:
    def __init__(self, rows):
        self.rows = rows
        self.Rows = _Count(len(rows))
        self.Columns = _Count(max((len(r) for r in rows), default=0))

    @property
    def Value(self):
        if not self.rows:
            return None
        if len(self.rows) == 1 and len(self.rows[0]) == 1:
            return self.rows[0][0]
        w = self.Columns.Count
        return tuple(tuple(list(r) + [None] * (w - len(r))) for r in self.rows)

    def Resize(self, nr, nc):
        return FakeRange([r[:nc] for r in self.rows[:nr]])


class FakeSheet:
    def __init__(self, name, rows):
        self.Name = name
        self.UsedRange = FakeRange(rows)


class FakeWorkbook:
    def __init__(self, name, sheets: dict, path=""):
        self.Name = name
        self.Path = path
        self.FullName = (path + "\\" + name) if path else name
        self._sheets = [FakeSheet(n, r) for n, r in sheets.items()]

    @property
    def Worksheets(self):
        wb = self

        class _WS(list):
            def __call__(self, name):
                for s in wb._sheets:
                    if s.Name == name:
                        return s
                raise Exception("sayfa yok")
        return _WS(self._sheets)


class FakeApp:
    def __init__(self, workbooks):
        self.Workbooks = workbooks
        self.Hwnd = id(self)


def df_rows(df, title_rows=()):
    """DataFrame'i Excel'in Value dönüşü gibi satırlara çevirir; üste başlık satırları ekler."""
    rows = [list(t) for t in title_rows]
    rows.append(list(df.columns))
    for r in df.itertuples(index=False):
        rows.append([v.to_pydatetime() if hasattr(v, "to_pydatetime") else
                     (None if v != v else (float(v) if isinstance(v, int) else v)) for v in r])
    return rows


def wms_title():
    return [["TOPLAMA PERFORMANS RAPORU"], ["Rapor tarihi:", datetime(2026, 11, 10)], []]
