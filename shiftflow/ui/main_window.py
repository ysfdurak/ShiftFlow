"""Ana pencere: veri kümeleri, adımlar, tablo ve sütun bilgisi."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..engine import Session
from ..engine import io as sio
from ..engine import operations as ops
from ..engine.errors import JoinConfirmationRequired, ShiftFlowError
from ..engine.values import is_empty, type_label
from . import help as help_ui
from . import worker
from . import dialogs as dlg
from .common import DataTable, ask, busy, fmt_n, info, show_error
from ..engine import mailer
from ..engine.recovery import Recovery
from ..engine.archive import Archive
from ..engine.autorun import ReportBuilder, mail_draft
from ..engine.excel_live import default_provider
from ..engine.library import ReportLibrary
from . import report_dialogs as rdlg
from . import stage_dialogs as sdlg
from .palette import Command, CommandPalette
from .source_dialogs import BindSourcesDialog, ExportDialog, ImportDialog, ask_text, pick_file

AUTOSAVE_MS = 5000  # kaydedilmemiş değişiklikler en geç bu sürede yedeklenir
ORIGIN_TAGS = {"source": "Kaynak", "join": "Birleştirme", "append": "Alt alta", "group": "Özet",
               "pivot": "Pivot", "copy": "Kopya"}


class MainWindow(QMainWindow):
    def __init__(self, session: Session | None = None, library: ReportLibrary | None = None, provider=None,
                 archive: Archive | None = None, outlook: mailer.OutlookMailer | None = None,
                 recovery: Recovery | None = None):
        super().__init__()
        self.session = session or Session()
        if library is None:
            try:
                library = ReportLibrary()
            except ShiftFlowError:
                library = None  # kütüphane açılamazsa uygulama yine çalışır; rapor tanıma kapalı olur
        self.library = library
        self.session.library = library
        if archive is None:
            try:
                archive = Archive()
            except ShiftFlowError:
                archive = None
        self.archive = archive
        self.session.archive = archive
        self.outlook = outlook or mailer.OutlookMailer()
        self.provider = provider or default_provider()
        self.settings = QSettings("ShiftFlow", "DataStudio")
        self.workflow_path: str | None = None
        self.current: str | None = None
        self.view_step: int | None = None  # None = son adım
        self.resize(1400, 860)
        self.setAcceptDrops(True)
        self._build()
        self.recovery = recovery or Recovery()
        self._autosave = QTimer(self)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self.autosave)
        self._autosave.start()
        self.refresh_all()

    # ================================================================ arayüz
    def _build(self):
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(6, 6, 6, 6)
        self.title = QLabel()
        self.title.setObjectName("datasetTitle")
        v.addWidget(self.title)
        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        v.addWidget(self.banner)
        # Ctrl+F: tabloda bul
        self.find_bar = QWidget()
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(0, 0, 0, 0)
        fb.addWidget(QLabel("Bul:"))
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Tabloda ara (Enter: sonraki, Shift+Enter: önceki, Esc: kapat)")
        self.find_edit.textChanged.connect(lambda _: self.find_next(0))
        self.find_edit.returnPressed.connect(lambda: self.find_next(1))
        fb.addWidget(self.find_edit, 1)
        self.find_info = QLabel()
        fb.addWidget(self.find_info)
        for txt, d in (("▲", -1), ("▼", 1)):
            b = QPushButton(txt)
            b.setFixedWidth(30)
            b.clicked.connect(lambda _=False, d=d: self.find_next(d))
            fb.addWidget(b)
        b_close = QPushButton("✕")
        b_close.setFixedWidth(30)
        b_close.clicked.connect(self.close_find)
        fb.addWidget(b_close)
        from PySide6.QtGui import QKeySequence, QShortcut
        esc = QShortcut(QKeySequence("Escape"), self.find_bar, self.close_find)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        self.find_bar.hide()
        self._find_hits: list = []
        self._find_pos = -1
        v.addWidget(self.find_bar)
        self.table = DataTable()
        self.table.horizontalHeader().arrowClicked.connect(self._header_arrow)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.header_menu)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.cell_menu)
        self.table.selectionStats.connect(lambda t: self.sel_label.setText(t))
        v.addWidget(self.table, 1)
        self.messages = QLabel()
        self.messages.setObjectName("messages")
        self.messages.setWordWrap(True)
        self.messages.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.messages)
        self.empty_hint = QLabel(
            "<h2>ShiftFlow Data Studio</h2>"
            "<p>Başlamak için <b>Dosya aç</b> ile bir Excel/CSV raporu seçin, Excel'den kopyaladığınız "
            "tabloyu <b>Ctrl+V</b> ile yapıştırın veya dosyayı pencereye sürükleyin.</p>"
            "<p>Kayıtlı bir iş akışınız varsa <b>Akış aç</b> ile açıp yeni raporlarla çalıştırabilirsiniz.</p>"
            "<p style='color:#6b7680'>Yardım: <b>F1</b> · İşlem ara: <b>Ctrl+K</b></p>"
        )
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setObjectName("emptyHint")
        v.addWidget(self.empty_hint, 1)
        self.setCentralWidget(central)

        # Veri kümeleri paneli
        dsw = QWidget()
        dl = QVBoxLayout(dsw)
        dl.setContentsMargins(4, 4, 4, 4)
        self.ds_list = QListWidget()
        self.ds_list.setWordWrap(True)
        self.ds_list.currentItemChanged.connect(self._ds_changed)
        self.ds_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ds_list.customContextMenuRequested.connect(self.ds_menu)
        dl.addWidget(self.ds_list)
        dock = QDockWidget("Veri kümeleri", self)
        dock.setObjectName("dock_datasets")
        dock.setWidget(dsw)
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        # Adımlar paneli
        stw = QWidget()
        sl = QVBoxLayout(stw)
        sl.setContentsMargins(4, 4, 4, 4)
        self.step_list = QListWidget()
        self.step_list.setWordWrap(True)
        self.step_list.currentRowChanged.connect(self._step_changed)
        self.step_list.itemDoubleClicked.connect(lambda *_: self.edit_step())
        self.step_list.itemChanged.connect(self._step_toggled)
        self.step_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.step_list.customContextMenuRequested.connect(self.step_menu)
        self.step_list.setToolTip("Onay kutusu: adımı geçici olarak kapat/aç. Sağ tık: not, kopyala, sil.")
        sl.addWidget(self.step_list)
        row = QHBoxLayout()
        self.b_edit = QPushButton("Düzenle")
        self.b_del = QPushButton("Sil")
        self.b_up = QPushButton("▲")
        self.b_down = QPushButton("▼")
        self.b_up.setToolTip("Adımı yukarı taşı")
        self.b_down.setToolTip("Adımı aşağı taşı")
        for b, fn in ((self.b_edit, self.edit_step), (self.b_del, self.delete_step),
                      (self.b_up, lambda: self.move_step(-1)), (self.b_down, lambda: self.move_step(1))):
            b.clicked.connect(fn)
            row.addWidget(b)
        sl.addLayout(row)
        dock2 = QDockWidget("İşlem adımları", self)
        dock2.setObjectName("dock_steps")
        dock2.setWidget(stw)
        dock2.setFeatures(QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock2)

        # Sütun bilgisi paneli
        self.col_info = QTableWidget(0, 4)
        self.col_info.setToolTip("Çift tıklayın: sütunun değer dağılımı")
        self.col_info.cellDoubleClicked.connect(
            lambda r, _c: self.value_distribution(self.col_info.item(r, 0).text()) if self.col_info.item(r, 0) else None)
        self.col_info.setHorizontalHeaderLabels(["Sütun", "Tip", "Boş", "Farklı"])
        self.col_info.verticalHeader().setVisible(False)
        ch = self.col_info.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            ch.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.col_info.verticalHeader().setDefaultSectionSize(22)
        self.col_info.setEditTriggers(QTableWidget.NoEditTriggers)
        self.col_info.cellClicked.connect(lambda r, c: self.table.selectColumn(r))
        dock3 = QDockWidget("Sütun bilgisi", self)
        dock3.setObjectName("dock_columns")
        dock3.setWidget(self.col_info)
        dock3.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.RightDockWidgetArea, dock3)
        self.resizeDocks([dock, dock3], [330, 300], Qt.Horizontal)
        self.resizeDocks([dock, dock2], [260, 420], Qt.Vertical)
        dock3.setMinimumWidth(250)
        self.col_dock = dock3

        self._actions()
        self.session.set_period(self.period_bar.period())
        self.size_label = QLabel()
        self.sel_label = QLabel()
        self.statusBar().addWidget(self.size_label)
        self.statusBar().addPermanentWidget(self.sel_label)

    def _act(self, text, fn, shortcut=None, tip=None):
        a = QAction(text, self)
        a.triggered.connect(fn)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        return a

    def _actions(self):
        A = self._act
        self.a_open = A("Dosya aç", self.open_file, "Ctrl+O", "Excel veya CSV raporu ekle")
        self.a_folder = A("Klasörden…", self.open_folder, None,
                          "Klasördeki tüm günlük dosyaları alt alta tek kaynak olarak al")
        self.a_open_excel = A("Açık Excel'den al", self.open_from_excel, "Ctrl+Shift+E",
                              "Açık (kaydedilmemiş dahil) Excel kitaplarından rapor al")
        self.a_build = A("▶ Rapor oluştur", self.build_report, "F9",
                         "Açık raporları bul, iş akışını çalıştır ve Excel çıktısını oluştur")
        self.a_reports = A("Rapor tanımları", self.open_report_library, None,
                           "Raporları bir kez tanımlayın; ShiftFlow onları açık kitaplar arasında bulur")
        self.a_run_settings = A("Rapor ayarları…", self.edit_run_settings, None,
                                "Çıktı klasörü, dosya adı, arşiv, şablon ve mail ayarları")
        self.a_refs = A("Referans tablolar", self.open_references, None,
                        "Bir kez alınan sabit tablolar (lokasyon-bölge, ürün-kategori…)")
        self.a_dashboard = A("Gösterge paneli", self.open_dashboard, None,
                             "Veri kümelerinden sayı ve grafik kutucukları (arşivle eğilim)")
        self.a_wms_probe = A("WMS ekranını incele…", self.open_wms_probe, None,
                             "WMS penceresinin ekran otomasyonuna uygun olup olmadığını ölç (tıklamaz, yalnız okur)")
        self.a_schedule = A("Zamanlanmış görev…", self.open_schedule, None,
                            "Rapor paketini Windows Görev Zamanlayıcı ile vardiya sonlarında çalıştır")
        self.a_trash = A("Çöp kutusu", self.open_trash, None,
                         "Silinen rapor tanımları, referans tablolar ve arşiv dönemleri (30 gün)")
        self.a_package = A("Rapor paketleri…", self.open_packages, None,
                           "Birden çok iş akışını aynı dönem için sırayla çalıştır")
        self.a_archive = A("Arşiv", self.open_archive, None, "Rapor arşivi; geçmiş dönemleri kaynak olarak ekle")
        self.a_shifts = A("Vardiyalar…", self.edit_shifts, None, "Vardiya saatlerini tanımla")
        self.a_palette = A("🔍 İşlem ara", self.open_palette, "Ctrl+K",
                           "Yapılabilecek tüm işlemleri arayarak bulun (Ctrl+K)")
        self.a_xl_columns = A("Excel'deki formüllü sütunları al…", self.formula_columns_from_excel, None,
                              "Raporun yanına Excel'de eklenen formüllü sütunları tek seferde adımlara çevir")
        self.a_xl_formula = A("Excel formülünden sütun…", self.formula_from_excel, None,
                              "Excel'deki formülü yapıştırıp ShiftFlow sütununa çevirin")
        self.a_paste = A("Yapıştır", self.paste, "Ctrl+V", "Excel'den kopyalanan tabloyu yeni kaynak olarak ekle")
        self.a_bind = A("Yeni verilerle çalıştır", self.bind_sources, "F5",
                        "Aynı işlemleri yeni tarihli raporlarla tekrar çalıştır")
        self.a_export = A("Excel'e aktar", self.export, "Ctrl+E", "Sonuçları çok sayfalı Excel dosyasına yaz")
        self.a_open_in_excel = A("Excel'de aç", self.open_in_excel, "Ctrl+Shift+X",
                                 "Seçili tabloyu kaydetmeden Excel'de aç (geçici dosya)")
        self.a_wf_save = A("Akışı kaydet", self.save_workflow, "Ctrl+S", "İş akışını JSON olarak kaydet")
        self.a_wf_save_as = A("Akışı farklı kaydet…", lambda: self.save_workflow(True), "Ctrl+Shift+S")
        self.a_wf_open = A("Akış aç", self.open_workflow, "Ctrl+Shift+O", "Kayıtlı iş akışını aç")
        self.a_new = A("Yeni çalışma", self.new_session, "Ctrl+N")
        self.a_undo = A("Geri al", self.undo, "Ctrl+Z")
        self.a_redo = A("Yinele", self.redo, "Ctrl+Y")
        step_acts = [
            ("Filtre", "filter", "Ctrl+Shift+L"), ("Sırala", "sort", None), ("Hesapla", "calc", None),
            ("Koşullu", "conditional", None), ("Sütunlar", "select", None), ("Ad değiştir", "rename", None),
            ("Tip", "convert", None), ("Metin temizle", "text_clean", None), ("Bul/Değiştir", "replace", "Ctrl+H"),
            ("Tekrarlar", "dedupe", None), ("Eşleştir (DÜŞEYARA)", "lookup", None), ("Kurallar", "rules", None),
            ("Dönem filtresi", "period_filter", None),
        ]
        self.a_unify = A("Yazımı birleştir (boşluk/harf)", lambda: self.add_step("unify"), None,
                         "Aynı değerin farklı yazılışlarını birleştir")
        self.a_find = A("Tabloda bul", self.open_find, "Ctrl+F", "Tabloda değer ara")
        self.a_params = A("Parametreler…", self.open_parameters, None,
                          "Formüllerde {Ad} ile kullanılan sabitler (hedef oranı vb.)")
        self.extra_step_actions = {
            "validate": A("Doğrula", lambda: self.add_step("validate"), None,
                          "Rapor dağıtılmadan önce kontrol: boş, tekrar, aralık, satır sayısı, formül"),
            "drop_empty_rows": A("Boş satırları kaldır", lambda: self.add_step("drop_empty_rows"), None,
                                 "Tamamen boş (veya yalnız formül içeren) satırları at"),
            "fill_down": A("Aşağı doldur", lambda: self.add_step("fill_down"), None, "Boş hücreye üstteki değer"),
            "fill_empty": A("Boşları doldur", lambda: self.add_step("fill_empty"), None, "Boşlara sabit değer"),
            "split": A("Sütunlara böl", lambda: self.add_step("split"), None, "Metni parçalara ayır"),
            "unpivot": A("Sütunları satırlara çevir", lambda: self.add_step("unpivot"), None,
                         "Yan yana sütunları satırlara indir"),
        }
        self.step_actions = {}
        for text, key, sc in step_acts:
            self.step_actions[key] = A(text, lambda _=False, k=key: self.add_step(k), sc, ops.get(key).label)
        self.a_join = A("Birleştir", self.add_join, None, "İki veri kümesini ortak anahtarla birleştir")
        self.a_append = A("Alt alta ekle", self.add_append, None, "Veri kümelerini alt alta ekle")
        self.a_group = A("Grupla", lambda: self.add_derived("group"), None, "Grupla ve özetle")
        self.a_pivot = A("Pivot", lambda: self.add_derived("pivot"), None, "Pivot tablo oluştur")

        # Üst şerit: her zaman görünen işler (dar ekranda da sığar)
        tb = QToolBar("Ana")
        tb.setObjectName("tb_main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        tb.addAction(self.a_build)
        tb.widgetForAction(self.a_build).setObjectName("buildButton")
        self.period_bar = sdlg.PeriodBar(lambda: self.session.shifts, lambda: self.session.auto_period(), self)
        self.period_bar.changed.connect(self._period_changed)
        tb.addWidget(self.period_bar)
        tb.addSeparator()
        tb.addAction(self.a_palette)
        tb.widgetForAction(self.a_palette).setObjectName("paletteButton")
        tb.addSeparator()
        for a in (self.a_undo, self.a_redo):
            tb.addAction(a)
        self.addToolBar(tb)
        self.addToolBarBreak()
        # Sekmeli şerit (Excel gibi): her sekmede bir grup işlem
        sa = self.step_actions
        ex = self.extra_step_actions
        groups = [
            ("Giriş", [self.a_open_excel, self.a_open, self.a_folder, self.a_paste, None, self.a_wf_open, self.a_wf_save, None,
                       self.a_export, self.a_open_in_excel, self.a_bind]),
            ("Dönüştür", [sa["filter"], sa["sort"], sa["period_filter"], None, sa["select"], sa["rename"],
                          sa["convert"], None, ex["split"], ex["unpivot"]]),
            ("Temizle", [sa["text_clean"], self.a_unify, sa["replace"], None, sa["dedupe"], ex["drop_empty_rows"],
                         None, ex["fill_down"], ex["fill_empty"]]),
            ("Formül", [sa["calc"], sa["conditional"], sa["rules"], sa["lookup"], None, self.a_xl_formula,
                        self.a_xl_columns, None, self.a_params]),
            ("Özet ve birleştir", [self.a_group, self.a_pivot, None, self.a_join, self.a_append]),
            ("Otomasyon", [self.a_package, self.a_schedule, None, self.a_wms_probe]),
            ("Rapor", [ex["validate"], self.a_dashboard, None, self.a_package, self.a_reports, self.a_run_settings, self.a_refs, self.a_archive,
                       self.a_shifts, self.a_trash]),
        ]
        self.ribbon = QTabWidget()
        self.ribbon.setObjectName("ribbon")
        self.ribbon.setDocumentMode(True)
        self.ribbon_bars = {}
        for title, acts in groups:
            bar = QToolBar(title)
            bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
            bar.setObjectName("ribbonBar")
            for a in acts:
                bar.addSeparator() if a is None else bar.addAction(a)
            self.ribbon.addTab(bar, title)
            self.ribbon_bars[title] = bar
        self.ribbon.setCurrentIndex(int(self.settings.value("ribbon_tab", 1) or 1))
        self.ribbon.currentChanged.connect(lambda i: self.settings.setValue("ribbon_tab", i))
        self.ribbon.setFixedHeight(self.ribbon.tabBar().sizeHint().height() + 40)
        rib_tb = QToolBar("Şerit")
        rib_tb.setObjectName("tb_ribbon")
        rib_tb.setMovable(False)
        rib_tb.addWidget(self.ribbon)
        self.addToolBar(rib_tb)

        m = self.menuBar()
        f = m.addMenu("&Dosya")
        for a in (self.a_new, self.a_open_excel, self.a_open, self.a_folder, self.a_paste, None, self.a_wf_open, self.a_wf_save,
                  self.a_wf_save_as, None, self.a_build, self.a_run_settings, self.a_bind, self.a_export,
                  None, self.a_package, self.a_reports, self.a_refs, self.a_archive, self.a_shifts, self.a_params,
                  None):
            f.addSeparator() if a is None else f.addAction(a)
        f.addAction(A("Çıkış", self.close, "Ctrl+Q"))
        e = m.addMenu("Dü&zen")
        e.addAction(self.a_undo)
        e.addAction(self.a_redo)
        e.addSeparator()
        e.addAction(A("Seçimi kopyala", lambda: self.table.copy_selection(), None))
        e.addAction(A("Başlıklarla kopyala", lambda: self.table.copy_selection(True), "Ctrl+Shift+C"))
        e.addSeparator()
        e.addAction(self.a_find)
        o = m.addMenu("&İşlemler")
        for a in self.step_actions.values():
            o.addAction(a)
        o.addAction(A("Sütun kaldır", lambda: self.add_step("remove"), None))
        o.addAction(self.a_unify)
        dm = o.addMenu("Biçim dönüştür")
        for a in self.extra_step_actions.values():
            dm.addAction(a)
        o.addAction(self.a_xl_formula)
        o.addAction(self.a_xl_columns)
        o.addSeparator()
        o.addAction(self.a_palette)
        o.addSeparator()
        for a in (self.a_join, self.a_append, self.a_group, self.a_pivot):
            o.addAction(a)
        vm = m.addMenu("&Görünüm")
        vm.addAction(self.col_dock.toggleViewAction())
        h = m.addMenu("&Yardım")
        h.addAction(A("Kullanım kılavuzu", lambda: help_ui.show_help(self), "F1"))
        h.addAction(A("Hoş geldiniz rehberi", lambda: help_ui.WelcomeDialog(self).exec()))
        h.addSeparator()
        h.addAction(A("Hakkında", self.about))
        self.data_actions = list(self.step_actions.values()) + [self.a_join, self.a_append, self.a_group,
                                                                 self.a_pivot, self.a_export, self.a_open_in_excel, self.a_xl_formula, self.a_unify,
                                                                 self.a_xl_columns] + list(self.extra_step_actions.values())

    # ================================================================ yenileme
    def refresh_all(self, focus: str | None = None):
        wf = self.session.workflow
        if focus:
            self.current = focus
        if self.current not in wf.datasets:
            self.current = next(iter(wf.datasets), None)
            self.view_step = None
        self.ds_list.blockSignals(True)
        self.ds_list.clear()
        order = wf.topo_order() if wf.datasets else []
        for name in order:
            ds = wf.datasets[name]
            try:
                n = len(self.session.result(name))
                tag = ORIGIN_TAGS.get(ds.origin.type, ds.origin.type)
                if ds.origin.type == "source":
                    spec = wf.sources[ds.origin.source]
                    if spec.report_id:
                        tag = "Rapor: " + self._report_name(spec.report_id)
                    elif spec.reference_id:
                        meta = self.library.reference_meta(spec.reference_id) if self.library else None
                        tag = "Referans: " + (meta["name"] if meta else "(yok)")
                    elif spec.archive:
                        from ..engine.archive import describe_range
                        tag = "Arşiv: " + describe_range(spec.archive.get("range"))
                    elif sio.is_pattern(spec.path):
                        tag = "Klasör: " + os.path.basename(spec.path)
                text = f"{name}\n   {tag} · {fmt_n(n)} satır"
                if ds.steps:
                    text += f" · {len(ds.steps)} adım"
                err = False
            except ShiftFlowError:
                text = f"{name}\n   ✖ hata var"
                err = True
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, name)
            if err:
                it.setForeground(QColor("#a32020"))
            if ds.origin.inputs:
                it.setToolTip("Girdi: " + ", ".join(ds.origin.inputs))
            self.ds_list.addItem(it)
            if name == self.current:
                self.ds_list.setCurrentItem(it)
        self.ds_list.blockSignals(False)
        self.refresh_steps()
        self.refresh_view()
        self._update_actions()

    def refresh_steps(self):
        self.step_list.blockSignals(True)
        self.step_list.clear()
        if not self.current:
            self.step_list.blockSignals(False)
            return
        statuses = self.session.step_statuses(self.current)
        steps = self.session.workflow.dataset(self.current).steps
        for i, st in enumerate(statuses):
            step = steps[i - 1] if 0 < i <= len(steps) else None
            prefix = "▸ " if i == 0 else f"{i}. "
            text = prefix + st.label
            if step is not None and not step.enabled:
                text += "\n   kapalı — veri değişmeden geçer"
            elif st.error:
                text += "\n   ✖ " + st.error.message[:140]
            elif st.rows_after is not None:
                if st.rows_before is not None and st.rows_before != st.rows_after:
                    text += f"\n   {fmt_n(st.rows_before)} → {fmt_n(st.rows_after)} satır"
                else:
                    text += f"\n   {fmt_n(st.rows_after)} satır"
                if st.warnings:
                    text += "  ⚠"
            if step is not None and step.note:
                text += "\n   📝 " + step.note.splitlines()[0][:120]
            it = QListWidgetItem(text)
            it.setToolTip("\n".join([st.label] + ([f"Not: {step.note}"] if step is not None and step.note else [])
                                    + st.messages + ["⚠ " + w for w in st.warnings]
                                    + ([st.error.message] if st.error else [])))
            if step is not None:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if step.enabled else Qt.Unchecked)
            if step is not None and not step.enabled:
                it.setForeground(QColor("#8a8f98"))
            elif st.error:
                it.setForeground(QColor("#a32020"))
            elif st.warnings:
                it.setForeground(QColor("#8a5a00"))
            self.step_list.addItem(it)
        last = len(statuses) - 1
        sel = last if self.view_step is None else min(self.view_step + 1, last)
        self.step_list.setCurrentRow(sel)
        self.step_list.blockSignals(False)

    def refresh_view(self):
        has = self.current is not None
        self.table.setVisible(has)
        self.empty_hint.setVisible(not has)
        self.messages.setVisible(has)
        if not has:
            self.title.setText("")
            self.banner.hide()
            self.table.set_frame(None)
            self.size_label.setText("")
            self._fill_col_info(None)
            self._title()
            return
        ds = self.session.workflow.dataset(self.current)
        n_steps = len(ds.steps)
        upto = None if self.view_step is None or self.view_step >= n_steps - 1 else self.view_step
        statuses = self.session.step_statuses(self.current)
        try:
            df = self.task(lambda: self.session.result(self.current, upto))
        except ShiftFlowError as exc:
            df = None
            self.messages.setText(f"<span style='color:#a32020'>✖ {exc.message}</span>")
        self.table.set_frame(df)
        self._apply_hidden()
        if self.table.frozen_count():
            self.table.freeze(self.table.frozen_count())
        self._find_hits = []
        tag = ORIGIN_TAGS.get(ds.origin.type, "")
        self.title.setText(f"<b>{self.current}</b> <span style='color:#6b7680'>· {tag}"
                           + (f" · girdi: {', '.join(ds.origin.inputs)}" if ds.origin.inputs else "") + "</span>")
        if upto is not None:
            label = "başlangıç" if upto < 0 else f"{upto + 1}. adım"
            self.banner.setText(f"Ara sonuç görüntüleniyor: {label} ({n_steps} adımdan). "
                                "Yeni işlemler bu adımın hemen sonrasına eklenir. Son sonuca dönmek için listede son adımı seçin.")
            self.banner.show()
        else:
            self.banner.hide()
        if df is not None:
            idx = (upto + 1) if upto is not None else len(statuses) - 1
            st = statuses[idx] if 0 <= idx < len(statuses) else None
            parts = []
            if st:
                import re as _re
                # boyut bilgisi zaten durum çubuğunda: tekrar yazma
                parts += [m for m in st.messages if not _re.fullmatch(r"[\d.]+ satır × \d+ sütun", m)]
                parts += [f"<span style='color:#8a5a00'>⚠ {w}</span>" for w in st.warnings]
                if st.error:
                    parts.append(f"<span style='color:#a32020'>✖ {st.error.message}</span>")
            later_err = next((s for s in statuses if s.error), None)
            if later_err and upto is None:
                parts.append(f"<span style='color:#a32020'>✖ {later_err.error.message}</span>")
            self.messages.setText("<br>".join(parts))
            self.size_label.setText(f"{fmt_n(len(df))} satır × {fmt_n(df.shape[1])} sütun")
        else:
            self.size_label.setText("")
        self._fill_col_info(df)
        self._title()

    def _fill_col_info(self, df):
        self.col_info.setRowCount(0)
        if df is None:
            return
        self.col_info.setRowCount(df.shape[1])
        big = len(df) > 300_000
        for i, c in enumerate(df.columns):
            s = df[c]
            empty = int(is_empty(s).sum())
            uniq = "…" if big else fmt_n(s.nunique(dropna=True))
            vals = [str(c), type_label(s), fmt_n(empty), uniq]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 2 and empty:
                    it.setForeground(QColor("#8a5a00"))
                self.col_info.setItem(i, j, it)

    def _title(self):
        name = os.path.basename(self.workflow_path) if self.workflow_path else "Kaydedilmemiş iş akışı"
        self.setWindowTitle(f"{APP_NAME} — {name}{' *' if self.session.dirty else ''}")

    def _update_actions(self):
        has = self.current is not None
        for a in self.data_actions:
            a.setEnabled(has)
        self.a_join.setEnabled(len(self.session.workflow.datasets) >= 2)
        self.a_append.setEnabled(len(self.session.workflow.datasets) >= 2)
        self.a_undo.setEnabled(self.session.can_undo())
        self.a_redo.setEnabled(self.session.can_redo())
        self.a_bind.setEnabled(bool(self.session.workflow.sources))
        self.a_build.setEnabled(bool(self.session.workflow.sources))
        self.a_reports.setEnabled(self.library is not None)
        n = self.step_list.currentRow()
        is_step = has and n >= 1
        is_origin_derived = has and n == 0 and self.session.workflow.dataset(self.current).origin.type != "source"
        self.b_edit.setEnabled(is_step or is_origin_derived)
        self.b_del.setEnabled(is_step)
        self.b_up.setEnabled(is_step and n > 1)
        self.b_down.setEnabled(is_step and n < self.step_list.count() - 1)

    def _ds_changed(self, cur, _prev):
        if cur is None:
            return
        self.current = cur.data(Qt.UserRole)
        self.view_step = None
        self.refresh_steps()
        self.refresh_view()
        self._update_actions()

    def _step_changed(self, row):
        if row < 0 or not self.current:
            return
        n_steps = len(self.session.workflow.dataset(self.current).steps)
        self.view_step = None if row >= n_steps else row - 1
        self.refresh_view()
        self._update_actions()

    # ================================================================ yardımcılar
    def current_frame(self):
        """Yeni adımın uygulanacağı tablo (ara sonuç seçiliyse o adım)."""
        upto = self.view_step
        return self.session.result(self.current, upto)

    def insert_position(self):
        return None if self.view_step is None else self.view_step + 1

    def task(self, fn, text="Hesaplanıyor…"):
        """Motor işini arka planda çalıştırır; pencere donmaz, uzun sürerse İptal edilebilir."""
        return worker.run_task(self, fn, text, session=self.session)

    def _apply(self, fn, focus=None, background=False):
        """Motor değişikliğini uygular; hata olursa gösterir.

        background=True: arka planda çalışır (pencere donmaz, İptal edilebilir). Yalnız fn içinde
        hiçbir arayüz nesnesine dokunulmuyorsa kullanılır — değerler önceden okunmuş olmalı."""
        try:
            if background:
                self.task(fn)
            else:
                with busy():
                    fn()
        except ShiftFlowError as exc:
            show_error(self, exc)
            return False
        except Exception as exc:  # pragma: no cover - beklenmeyen hata
            show_error(self, exc)
            return False
        self.refresh_all(focus)
        return True

    # ================================================================ veri alma
    def open_file(self, path=None):
        path = path or pick_file(self, self.settings)
        if not path:
            return
        d = ImportDialog(self, path=path)
        if d.exec() == QDialog.Accepted and d.df is not None:
            name = d.name.text().strip() or "Veri"
            if d.selected_sheet() and len(sio.list_sheets(path)) > 1 and name == os.path.splitext(os.path.basename(path))[0]:
                name = f"{name} - {d.selected_sheet()}"
            holder = {}
            df, sheet, header = d.df, d.selected_sheet(), d.header.isChecked()
            if self._apply(lambda: holder.setdefault("n", self.session.add_source(
                    name, df, kind="file", path=path, sheet=sheet, header=header)), background=True):
                self.refresh_all(holder["n"])

    def open_folder(self):
        from .source_dialogs import FolderImportDialog
        d = FolderImportDialog(self, folder=self.settings.value("folder_dir", ""))
        if d.exec() == QDialog.Accepted and d.df is not None:
            self.settings.setValue("folder_dir", d.folder.text())
            name, df, pat = d.source_name(), d.df, d.full_pattern()
            sheet, header = d.sheet.text().strip() or None, d.header.isChecked()
            holder = {}
            if self._apply(lambda: holder.setdefault("n", self.session.add_source(
                    name, df, kind="folder", path=pat, sheet=sheet, header=header)), background=True):
                self.refresh_all(holder["n"])

    def paste(self):
        text = QGuiApplication.clipboard().text()
        if not text.strip():
            info(self, "Panoda tablo bulunamadı. Excel'de hücreleri seçip Ctrl+C ile kopyalayın.")
            return
        d = ImportDialog(self, text=text)
        if d.exec() == QDialog.Accepted and d.df is not None:
            holder = {}
            name, df, header = d.name.text().strip() or "Yapıştırılan veri", d.df, d.header.isChecked()
            if self._apply(lambda: holder.setdefault("n", self.session.add_source(
                    name, df, kind="paste", header=header)), background=True):
                self.refresh_all(holder["n"])

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".json"):
                self.open_workflow(p)
            elif p:
                self.open_file(p)

    # ================================================================ adımlar
    def add_step(self, key, preset=None, params=None):
        if not self.current:
            return
        try:
            df = self.current_frame()
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        cls = dlg.STEP_DIALOGS.get(key)
        if cls is None:
            return
        if preset is None and params is None:
            # Şeritten açılan adım, tabloda seçili sütunla başlar (önceden sütun boş geliyordu).
            idx = self.table.currentIndex()
            if idx.isValid() and 0 <= idx.column() < df.shape[1]:
                preset = str(df.columns[idx.column()])
        if key == "lookup" and len(self.session.workflow.datasets) < 2:
            info(self, "Eşleştirme için önce arama tablosunu ekleyin: Referans tablolar, Dosya aç veya Açık Excel'den al.")
            return
        d = cls(df, params=params, preset=preset, parent=self, dataset_label=self.current, session=self.session,
                dataset=self.current, context=self.session.context)
        if d.exec() != QDialog.Accepted:
            return
        p = d.params()
        pos = self.insert_position()
        if self._apply(lambda: self.session.add_step(self.current, key, p, pos), background=True):
            if pos is not None:
                self.view_step = pos
                self.refresh_all()
            self.offer_variant_fix(self.current, self._added_index(pos))

    def quick_step(self, key, params):
        pos = self.insert_position()
        if self._apply(lambda: self.session.add_step(self.current, key, params, pos), background=True):
            self.offer_variant_fix(self.current, self._added_index(pos))

    def _added_index(self, pos):
        return pos if pos is not None else len(self.session.workflow.dataset(self.current).steps) - 1

    def offer_variant_fix(self, dataset, index):
        """Adım farklı yazılmış aynı değerler bulduysa kullanıcıya düzeltmeyi sorar."""
        from ..engine import variants
        found = self.session.variants_at(dataset, index)
        if not found:
            return
        choice = self.ask_variant_fix(variants.describe(found), index < 0)
        if choice == "fix":
            if self._apply(lambda: self.session.fix_variants(dataset, index, list(found)), focus=dataset, background=True):
                if index >= 0 and self.view_step is not None:
                    self.view_step += 1
                    self.refresh_all()
                self.statusBar().showMessage("Farklı yazılışlar birleştirildi.", 6000)
        elif choice == "never":
            self._apply(lambda: self.session.ignore_variants(dataset, index), focus=dataset)

    def ask_variant_fix(self, lines, at_input):
        """'fix' / 'later' / 'never' döndürür (testlerde değiştirilebilir)."""
        where = "girdi tablosunun sonuna" if at_input else "bu adımın önüne"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Aynı değer farklı yazılmış")
        box.setText("\n\n".join(lines) + "\n\nDüzeltilsin mi?")
        box.setInformativeText(f"Düzelt: {where} \"Yazımı birleştir\" adımı eklenir; her farklı yazılış en sık "
                               "kullanılan yazılışa çevrilir. Kaynak dosya değişmez; adım her yeni raporda da uygulanır.")
        b_fix = box.addButton("Düzelt", QMessageBox.AcceptRole)
        box.addButton("Şimdi değil", QMessageBox.RejectRole)
        b_never = box.addButton("Bu adım için bir daha sorma", QMessageBox.DestructiveRole)
        box.setDefaultButton(b_fix)
        box.exec()
        if box.clickedButton() is b_fix:
            return "fix"
        return "never" if box.clickedButton() is b_never else "later"

    def edit_step(self):
        row = self.step_list.currentRow()
        if not self.current or row < 0:
            return
        ds = self.session.workflow.dataset(self.current)
        if row == 0:
            return self.edit_origin()
        idx = row - 1
        step = ds.steps[idx]
        try:
            df = self.session.result(self.current, idx - 1)
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        cls = dlg.STEP_DIALOGS.get(step.op)
        if cls is None:
            if step.op == "excel_formula":
                info(self, f"Bu sütun çıktıya Excel formülü olarak yazılır:\n\n{step.params.get('name')} = "
                           f"{step.params.get('template')}\n\nExcel'deki özgün formül: {step.params.get('excel', '')}"
                           "\n\nDeğiştirmek için adımı silip 'Excel formülünden sütun' ile yeniden ekleyin.")
            return
        d = cls(df, params=step.params, parent=self, dataset_label=f"{self.current} (adım {idx + 1})",
                session=self.session, dataset=self.current, context=self.session.context)
        if d.exec() == QDialog.Accepted:
            p = d.params()
            if self._apply(lambda: self.session.edit_step(self.current, idx, p), background=True):
                self.offer_variant_fix(self.current, idx)

    def edit_origin(self):
        ds = self.session.workflow.dataset(self.current)
        o = ds.origin
        if o.type == "source":
            return
        if o.type == "join":
            self.add_join(edit=True)
        elif o.type == "append":
            self.add_append(edit=True)
        elif o.type in dlg.DERIVED_DIALOGS:
            self.add_derived(o.type, edit=True)

    def _step_toggled(self, item):
        row = self.step_list.row(item)
        if row < 1 or not self.current:
            return
        steps = self.session.workflow.dataset(self.current).steps
        if row - 1 >= len(steps):
            return
        on = item.checkState() == Qt.Checked
        if on == steps[row - 1].enabled:
            return
        if not self._apply(lambda: self.session.set_step_enabled(self.current, row - 1, on), background=True):
            self.refresh_all()
        else:
            self.statusBar().showMessage(f"{row}. adım {'açıldı' if on else 'kapatıldı'}.", 4000)

    def step_note(self, row=None):
        row = self.step_list.currentRow() if row is None else row
        if row < 1 or not self.current:
            return
        from PySide6.QtWidgets import QInputDialog
        step = self.session.workflow.dataset(self.current).steps[row - 1]
        text, ok = QInputDialog.getMultiLineText(self, "Adım notu",
                                                 "Bu adım neden var? (ör. 'WMS iptal satırlarını çıkarır')",
                                                 step.note)
        if ok and text.strip() != step.note:
            self._apply(lambda: self.session.set_step_note(self.current, row - 1, text))

    def duplicate_step(self, row=None):
        row = self.step_list.currentRow() if row is None else row
        if row < 1 or not self.current:
            return
        holder = {}
        if self._apply(lambda: holder.setdefault("n", self.session.duplicate_step(self.current, row - 1)), background=True):
            self.view_step = holder["n"]
            self.refresh_all()

    def step_menu(self, pos):
        it = self.step_list.itemAt(pos)
        if it is None:
            return
        row = self.step_list.row(it)
        self.step_list.setCurrentRow(row)
        m = QMenu(self)
        m.addAction("Düzenle…", self.edit_step)
        if row >= 1:
            step = self.session.workflow.dataset(self.current).steps[row - 1]
            m.addAction("Adımı kapat" if step.enabled else "Adımı aç",
                        lambda: it.setCheckState(Qt.Unchecked if step.enabled else Qt.Checked))
            m.addAction("Not ekle/düzenle…", lambda: self.step_note(row))
            m.addAction("Kopyasını ekle", lambda: self.duplicate_step(row))
            m.addSeparator()
            m.addAction("Yukarı taşı", lambda: self.move_step(-1))
            m.addAction("Aşağı taşı", lambda: self.move_step(1))
            m.addSeparator()
            m.addAction("Sil", self.delete_step)
        m.exec(self.step_list.viewport().mapToGlobal(pos))

    def delete_step(self):
        row = self.step_list.currentRow()
        if row < 1:
            return
        label = self.step_list.item(row).text().split("\n")[0]
        if ask(self, f"Bu adım silinsin mi?\n\n{label}"):
            self.view_step = None
            self._apply(lambda: self.session.delete_step(self.current, row - 1), background=True)

    def move_step(self, d):
        row = self.step_list.currentRow()
        if row < 1:
            return
        holder = {}
        ok = self._apply(lambda: holder.setdefault("n", self.session.move_step(self.current, row - 1, d)), background=True)
        if ok:
            self.view_step = holder["n"]
            self.refresh_all()
            if self.view_step >= len(self.session.workflow.dataset(self.current).steps) - 1:
                self.view_step = None

    # ================================================================ yeni veri kümeleri
    def add_join(self, edit=False):
        o = self.session.workflow.dataset(self.current).origin if edit else None
        if edit:
            d = dlg.JoinDialog(self.session, params=o.params, parent=self, name=self.current, inputs=o.inputs)
            d.name_edit.setEnabled(False)
        else:
            names = list(self.session.workflow.datasets)
            others = [n for n in names if n != self.current]
            d = dlg.JoinDialog(self.session, left=self.current, right=others[0] if others else None, parent=self)
        if d.exec() != QDialog.Accepted:
            return
        p, inputs, name = d.params(), d.inputs(), d.dataset_name()
        while True:
            try:
                if edit:
                    self.task(lambda: self.session.edit_origin(self.current, p, inputs))
                    new = self.current
                else:
                    new = self.task(lambda: self.session.add_derived(name, "join", inputs, p))
                break
            except JoinConfirmationRequired as exc:
                text = exc.message + "\n\n" + "\n".join(ops.diagnostics_text(exc.diagnostics)) + \
                    "\n\nYine de birleştirmek istiyor musunuz?"
                if not ask(self, text, "Çoktan-çoğa birleştirme"):
                    return
                p["allow_many_to_many"] = True
            except ShiftFlowError as exc:
                show_error(self, exc)
                return
        self.refresh_all(new)

    def add_append(self, edit=False):
        if edit:
            o = self.session.workflow.dataset(self.current).origin
            d = dlg.AppendDialog(self.session, params=o.params, parent=self, name=self.current, inputs=o.inputs)
            d.name_edit.setEnabled(False)
        else:
            d = dlg.AppendDialog(self.session, current=self.current, parent=self)
        if d.exec() != QDialog.Accepted:
            return
        p, inputs, name = d.params(), d.inputs(), d.dataset_name()
        holder = {}
        if edit:
            self._apply(lambda: self.session.edit_origin(self.current, p, inputs), background=True)
        elif self._apply(lambda: holder.setdefault("n", self.session.add_derived(name, "append", inputs, p)), background=True):
            self.refresh_all(holder["n"])

    def add_derived(self, key, edit=False, preset=None):
        if not self.current:
            return
        cls = dlg.DERIVED_DIALOGS[key]
        if edit:
            o = self.session.workflow.dataset(self.current).origin
            src = o.inputs[0]
            d = cls(self.session.result(src), params=o.params, parent=self, dataset_label=src, name=self.current)
            d.name_edit.setEnabled(False)
        else:
            src = self.current
            try:
                df = self.session.result(src)
            except ShiftFlowError as exc:
                show_error(self, exc)
                return
            if self.view_step is not None:
                info(self, "Pivot ve gruplama, veri kümesinin son sonucunu kullanır (ara sonucu değil).")
            d = cls(df, preset=preset, parent=self, dataset_label=src, name=f"{src} - {cls.default_name}")
        if d.exec() != QDialog.Accepted:
            return
        p, name = d.params(), d.dataset_name()
        holder = {}
        if edit:
            if self._apply(lambda: self.session.edit_origin(self.current, p), background=True):
                self.offer_variant_fix(self.current, -1)
        elif self._apply(lambda: holder.setdefault("n", self.session.add_derived(name, key, [src], p)), background=True):
            self.refresh_all(holder["n"])
            self.offer_variant_fix(holder["n"], -1)

    # ================================================================ menüler
    # ---------------------------------------------------------------- bul (Ctrl+F) ve görünüm
    def open_find(self):
        if not self.current:
            return
        self.find_bar.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self.find_next(0)

    def close_find(self):
        self.find_bar.hide()
        self.find_info.setText("")
        self._find_hits = []
        self.table.setFocus()

    def _find_compute(self):
        from ..engine.values import tr_lower
        from .table_model import format_value
        q = tr_lower(self.find_edit.text().strip())
        df = self.table.model_.frame()
        hits = []
        if q:
            for j, c in enumerate(df.columns):
                if self.table.isColumnHidden(j):
                    continue
                col = df[c]
                texts = col.map(lambda v: tr_lower(format_value(v) or ""))
                for i in texts.index[texts.str.contains(q, regex=False)].tolist()[:20000]:
                    hits.append((df.index.get_loc(i), j))
                if len(hits) > 20000:
                    break
        hits.sort()
        return hits

    def find_next(self, direction=1):
        """direction: 0 = metin değişti (ilk eşleşme), 1 sonraki, -1 önceki."""
        from PySide6.QtWidgets import QApplication
        if direction == 1 and QApplication.keyboardModifiers() & Qt.ShiftModifier:
            direction = -1
        if direction == 0 or not self._find_hits:
            self._find_hits = self._find_compute()
            self._find_pos = -1 if direction != -1 else 0
        if not self._find_hits:
            self.find_info.setText("bulunamadı" if self.find_edit.text().strip() else "")
            return
        step = 1 if direction >= 0 else -1
        self._find_pos = (self._find_pos + step) % len(self._find_hits)
        r, c = self._find_hits[self._find_pos]
        idx = self.table.model_.index(r, c)
        self.table.setCurrentIndex(idx)
        self.table.scrollTo(idx)
        more = "+" if len(self._find_hits) >= 20000 else ""
        self.find_info.setText(f"{self._find_pos + 1} / {fmt_n(len(self._find_hits))}{more}")

    def _hidden_for(self):
        if not hasattr(self, "_hidden_cols"):
            self._hidden_cols = {}
        return self._hidden_cols.setdefault(self.current, set())

    def hide_column(self, col):
        """Yalnız görünümde gizler; iş akışına adım eklenmez, çıktıyı etkilemez."""
        self._hidden_for().add(col)
        self._apply_hidden()

    def show_all_columns(self):
        self._hidden_for().clear()
        self._apply_hidden()

    def _apply_hidden(self):
        if not self.current:
            return
        hidden = self._hidden_for()
        for j, c in enumerate(self.table.model_.frame().columns):
            self.table.setColumnHidden(j, str(c) in hidden)
        n = sum(1 for c in self.table.model_.frame().columns if str(c) in hidden)
        if n:
            self.statusBar().showMessage(f"{n} sütun görünümde gizli (çıktıya yazılır). Başlığa sağ tık → "
                                         "Gizli sütunları göster.", 6000)

    def _header_arrow(self, col_i):
        df = self.table.model_.frame()
        if 0 <= col_i < df.shape[1]:
            self.add_step("filter", preset=str(df.columns[col_i]))

    def header_menu(self, pos):
        col_i = self.table.header_column_at(pos)
        df = self.table.model_.frame()
        if col_i < 0 or col_i >= df.shape[1]:
            return
        col = str(df.columns[col_i])
        m = QMenu(self)
        m.addAction(f"A → Z sırala", lambda: self.quick_step("sort", {"keys": [{"column": col, "ascending": True}]}))
        m.addAction(f"Z → A sırala", lambda: self.quick_step("sort", {"keys": [{"column": col, "ascending": False}]}))
        m.addSeparator()
        m.addAction("Filtrele…", lambda: self.add_step("filter", preset=col))
        m.addAction("Boş olanları çıkar", lambda: self.quick_step(
            "filter", {"conditions": [{"column": col, "op": "not_empty"}], "mode": "and"}))
        m.addSeparator()
        m.addAction("Yeniden adlandır…", lambda: self._rename_col(col))
        m.addAction("Sütunu kaldır", lambda: self.quick_step("remove", {"columns": [col]}))
        m.addAction("Tip dönüştür…", lambda: self.add_step("convert", preset=col))
        m.addAction("Metin temizle…", lambda: self.add_step("text_clean", preset=col))
        m.addAction("Yazımı birleştir (boşluk/harf)…", lambda: self.add_step("unify", preset=col))
        m.addAction("Aşağı doldur…", lambda: self.add_step("fill_down", preset=col))
        m.addAction("Boşları doldur…", lambda: self.add_step("fill_empty", preset=col))
        m.addAction("Sütunlara böl…", lambda: self.add_step("split", preset=col))
        m.addAction("Bul ve değiştir…", lambda: self.add_step("replace", preset=col))
        m.addAction("Bu sütuna göre tekrarları kaldır", lambda: self.quick_step("dedupe", {"columns": [col], "keep": "first"}))
        m.addSeparator()
        m.addAction("Bu sütunla hesapla…", lambda: self.add_step("calc", preset=col))
        m.addAction("Bu sütuna göre grupla…", lambda: self.add_derived("group", preset=col))
        m.addAction("Bu sütunla pivot…", lambda: self.add_derived("pivot", preset=col))
        m.addSeparator()
        v = m.addMenu("Görünüm (çıktıyı etkilemez)")
        v.addAction("Bu sütunu görünümde gizle", lambda: self.hide_column(col))
        n_hidden = len(self._hidden_for())
        a = v.addAction(f"Gizli sütunları göster ({n_hidden})", self.show_all_columns)
        a.setEnabled(bool(n_hidden))
        v.addAction(f"Sütunları buraya kadar dondur ({col_i + 1} sütun)", lambda: self.table.freeze(col_i + 1))
        a2 = v.addAction("Dondurmayı kaldır", lambda: self.table.freeze(0))
        a2.setEnabled(bool(self.table.frozen_count()))
        v.addAction("Tabloda bul… (Ctrl+F)", self.open_find)
        m.addAction("Değer dağılımı…", lambda: self.value_distribution(col))
        m.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def _rename_col(self, col):
        new = ask_text(self, "Yeniden adlandır", f"'{col}' için yeni ad:", col)
        if new and new != col:
            self.quick_step("rename", {"mapping": {col: new}})

    def cell_menu(self, pos):
        idx = self.table.indexAt(pos)
        m = QMenu(self)
        m.addAction("Kopyala", lambda: self.table.copy_selection())
        m.addAction("Başlıklarla kopyala", lambda: self.table.copy_selection(True))
        if idx.isValid():
            df = self.table.model_.frame()
            col = str(df.columns[idx.column()])
            from ..engine.values import normalize_key
            key = normalize_key(df.iloc[[idx.row()], idx.column()]).iloc[0]
            val = ops.EMPTY_LABEL if key is None else key
            m.addSeparator()
            short = val if len(str(val)) < 30 else str(val)[:27] + "…"
            m.addAction(f"Yalnız '{short}' olanları göster", lambda: self.quick_step(
                "filter", {"conditions": [{"column": col, "op": "in_list", "value": [val]}], "mode": "and"}))
            m.addAction(f"'{short}' olanları çıkar", lambda: self._exclude_value(col, val))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def value_distribution(self, col):
        from ..engine.values import normalize_key
        df = self.table.model_.frame()
        if col not in map(str, df.columns):
            return

        def only(v):
            import pandas as pd
            key = ops.EMPTY_LABEL if v == "(Boş)" else normalize_key(pd.Series([v])).iloc[0]
            self.quick_step("filter", {"conditions": [{"column": col, "op": "in_list", "value": [key]}],
                                       "mode": "and"})
        sdlg.ValueDistributionDialog(df, col, self, on_filter=only).exec()

    def _exclude_value(self, col, val):
        if val == ops.EMPTY_LABEL:
            cond = {"column": col, "op": "not_empty"}
        else:
            cond = {"column": col, "op": "ne", "value": val}
        self.quick_step("filter", {"conditions": [cond], "mode": "and"})

    def ds_menu(self, pos):
        it = self.ds_list.itemAt(pos)
        if not it:
            return
        name = it.data(Qt.UserRole)
        m = QMenu(self)
        ds = self.session.workflow.dataset(name)
        if ds.origin.type == "source" and self.library is not None:
            src = ds.origin.source
            m.addAction("Rapor tanımına bağla…", lambda: self.link_source(src))
            m.addAction("Bu kaynaktan rapor tanımı oluştur…", lambda: self.define_from_source(src))
            if self.session.workflow.sources[src].report_id:
                m.addAction("Rapor bağını kaldır", lambda: self._apply(lambda: self.session.link_report(src, None)))
            if not self.session.workflow.sources[src].reference_id and not self.session.workflow.sources[src].archive:
                m.addAction("Referans tablo olarak kaydet…", lambda: self.save_as_reference(src))
            m.addSeparator()
        m.addAction("Yeniden adlandır…", lambda: self._rename_ds(name))
        m.addAction("Kopyasını oluştur (paralel kol)", lambda: self._copy_ds(name))
        m.addSeparator()
        m.addAction("Sil", lambda: self._delete_ds(name))
        m.exec(self.ds_list.viewport().mapToGlobal(pos))

    def _rename_ds(self, name):
        new = ask_text(self, "Yeniden adlandır", "Yeni ad:", name)
        if new and new != name:
            self._apply(lambda: self.session.rename_dataset(name, new), focus=None)
            self.refresh_all(new if new in self.session.workflow.datasets else None)

    def _copy_ds(self, name):
        holder = {}
        if self._apply(lambda: holder.setdefault("n", self.session.add_derived(f"{name} kopya", "copy", [name], {})), background=True):
            self.refresh_all(holder["n"])

    def _delete_ds(self, name):
        if ask(self, f"'{name}' veri kümesi ve adımları silinsin mi? (Kaynak dosya etkilenmez.)"):
            self._apply(lambda: self.session.delete_dataset(name), background=True)

    # ================================================================ iş akışı
    def undo(self):
        self.session.undo()
        self.view_step = None
        self.refresh_all()

    def redo(self):
        self.session.redo()
        self.view_step = None
        self.refresh_all()

    def save_workflow(self, save_as=False):
        if not self.session.workflow.datasets:
            info(self, "Kaydedilecek bir iş akışı yok.")
            return
        path = self.workflow_path
        if save_as or not path:
            start = self.settings.value("wf_dir", os.path.expanduser("~"))
            path, _ = QFileDialog.getSaveFileName(self, "İş akışını kaydet", os.path.join(start, "is_akisi.json"),
                                                  "ShiftFlow iş akışı (*.json)")
            if not path:
                return
            if not path.lower().endswith(".json"):
                path += ".json"
            self.settings.setValue("wf_dir", os.path.dirname(path))
        self.session.workflow.name = os.path.splitext(os.path.basename(path))[0]
        try:
            self.session.save_workflow(path)
        except OSError as exc:
            show_error(self, ShiftFlowError("İş akışı kaydedilemedi.", detail=str(exc)))
            return
        self.workflow_path = path
        self.recovery.clear()
        self.statusBar().showMessage(f"İş akışı kaydedildi: {path}", 5000)
        self._title()

    # ================================================================ otomatik kayıt
    def autosave(self):
        """Kaydedilmemiş değişiklik varsa kurtarma klasörüne yazar (arka plan görevi sürerken beklenir)."""
        if worker.active() or not self.isVisible():
            return
        try:
            if self.session.dirty and self.session.workflow.datasets:
                if self.recovery.save(self.session, self.workflow_path):
                    self.statusBar().showMessage("Otomatik yedek alındı.", 2500)
            elif not self.session.dirty:
                self.recovery.clear()
        except Exception as exc:  # noqa: BLE001 - yedek alınamaması çalışmayı durdurmasın
            import logging
            logging.warning("Otomatik yedek alınamadı: %s", type(exc).__name__)

    def first_run(self):
        """İlk açılışta kısa rehber (bir kez)."""
        if self.settings.value("welcome_shown", False) in (True, "true"):
            return
        self.settings.setValue("welcome_shown", True)
        help_ui.WelcomeDialog(self).exec()

    def offer_recovery(self) -> bool:
        """Açılışta: önceki oturumdan kalan kaydedilmemiş iş akışını geri yüklemeyi önerir."""
        meta = self.recovery.pending()
        if not meta:
            return False
        when = meta.get("saved_at", "").replace("T", " ")
        name = meta.get("workflow_path") and os.path.basename(meta["workflow_path"]) or "Kaydedilmemiş iş akışı"
        r = QMessageBox.question(
            self, "Kurtarılmış iş akışı",
            f"ShiftFlow son kez düzgün kapatılmamış. Kaydedilmemiş bir iş akışı bulundu:\n\n"
            f"{name} · {meta.get('datasets')} veri kümesi · son yedek {when}\n\nGeri yüklensin mi?",
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            if ask(self, "Yedek silinsin mi? (Hayır derseniz bir sonraki açılışta yeniden sorulur.)"):
                self.recovery.clear()
            return False
        try:
            missing = self.recovery.restore(self.session)
        except Exception as exc:  # noqa: BLE001
            show_error(self, ShiftFlowError("Yedek geri yüklenemedi.", detail=str(exc)))
            return False
        self.workflow_path = meta.get("workflow_path")
        self.current, self.view_step = None, None
        self.period_bar.reload_shifts()
        self.refresh_all()
        msg = "İş akışı geri yüklendi. Kaydetmeyi unutmayın."
        if missing:
            msg += "\n\nVerisi yüklenemeyen kaynaklar: " + ", ".join(missing) + ". 'Kaynakları bağla' ile seçin."
        info(self, msg)
        return True

    def _confirm_discard(self) -> bool:
        if not self.session.dirty or not self.session.workflow.datasets:
            return True
        r = QMessageBox.question(self, "Kaydedilmemiş değişiklikler",
                                 "İş akışında kaydedilmemiş değişiklikler var. Kaydetmek ister misiniz?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            self.save_workflow()
            return not self.session.dirty
        return r == QMessageBox.Discard

    def open_workflow(self, path=None):
        if not self._confirm_discard():
            return
        if not path:
            start = self.settings.value("wf_dir", os.path.expanduser("~"))
            path, _ = QFileDialog.getOpenFileName(self, "İş akışı aç", start, "ShiftFlow iş akışı (*.json)")
            if not path:
                return
        try:
            self.session.load_workflow(path)
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        self.workflow_path = path
        self.current, self.view_step = None, None
        self.session.archive = self.archive
        self.period_bar.reload_shifts()
        self.period_bar.set_auto()
        self.refresh_all()
        if any(s.report_id for s in self.session.workflow.sources.values()):
            self.load_from_open_reports()
        else:
            self.bind_sources()

    def bind_sources(self):
        d = BindSourcesDialog(self.session, self.settings, self)
        if d.exec() == QDialog.Accepted:
            self.run_all()
        else:
            self.refresh_all()

    def run_all(self):
        missing = self.session.unbound_sources()
        try:
            errors = self.task(self.session.run_all, "İş akışı çalıştırılıyor…")
        except ShiftFlowError as exc:
            show_error(self, exc)
            self.refresh_all()
            return
        self.refresh_all()
        if missing:
            info(self, "Verisi yüklenmemiş kaynaklar var: " + ", ".join(missing))
        elif errors:
            lines = [f"• {k}: {v.message}" for k, v in errors.items()]
            QMessageBox.warning(self, "Çalıştırma tamamlandı — hatalar var",
                                "Aşağıdaki veri kümeleri hesaplanamadı:\n\n" + "\n".join(lines[:15]))
        else:
            n = len(self.session.workflow.datasets)
            self.statusBar().showMessage(f"İş akışı çalıştırıldı: {n} veri kümesi hatasız hesaplandı.", 8000)
            if self.session.workflow.outputs and ask(
                    self, "İş akışı hatasız çalıştı. Kayıtlı çıktıyı şimdi Excel'e aktarmak ister misiniz?"):
                self.export()

    def export(self):
        if not self.session.workflow.datasets:
            return
        d = ExportDialog(self.session, self)
        if d.exec() != QDialog.Accepted:
            return
        items = d.items()
        if not items:
            info(self, "Aktarılacak veri kümesi seçilmedi.")
            return
        start = self.settings.value("out_dir", os.path.expanduser("~"))
        default = (self.session.workflow.name or "rapor").replace(" ", "_") + ".xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Excel dosyasını kaydet", os.path.join(start, default),
                                              "Excel (*.xlsx)")
        if not path:
            return
        self.settings.setValue("out_dir", os.path.dirname(path))
        if d.remember.isChecked():
            try:
                self.session.set_outputs([{"dataset": a, "sheet": b, **o} for a, b, o in items])
            except ShiftFlowError:
                pass
        try:
            sheets = self.task(lambda: self.session.export(path, items), "Excel dosyası yazılıyor…")
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        self._title()
        info(self, f"Excel dosyası oluşturuldu:\n{os.path.normpath(path)}\n\nSayfalar: {', '.join(sheets)}")

    # ================================================================ açık raporlar
    def _report_name(self, rid):
        d = self.library.get(rid) if self.library else None
        if d is None and rid in self.session.workflow.reports:
            return self.session.workflow.reports[rid].get("name", "?")
        return d.name if d else "(tanım yok)"

    def open_from_excel(self):
        d = rdlg.OpenReportsDialog(self.provider, self.library, self, settings=self.settings)
        if d.exec() != QDialog.Accepted or d.result_df is None:
            return
        wb, sh = d.result_ref
        rid = d.result_report.id if d.result_report else None
        holder = {}
        if self._apply(lambda: holder.setdefault("n", self.session.add_source(
                d.result_name, d.result_df, kind="report" if rid else ("file" if wb.saved else "paste"),
                path=wb.path if wb.saved else "", sheet=sh.name, report_id=rid))):
            self.refresh_all(holder["n"])

    def open_report_library(self):
        if self.library is None:
            info(self, "Rapor kütüphanesi açılamadı.")
            return
        rdlg.ReportLibraryDialog(self.library, self.provider, self, settings=self.settings).exec()
        self.refresh_all()

    def link_source(self, source):
        defs = self.library.list()
        if not defs:
            if ask(self, "Henüz rapor tanımı yok. Bu kaynağın sütunlarından bir tanım oluşturulsun mu?"):
                self.define_from_source(source)
            return
        from PySide6.QtWidgets import QInputDialog
        names = [d.name for d in defs]
        choice, ok = QInputDialog.getItem(self, "Rapor tanımına bağla", f"'{source}' kaynağı hangi rapor?", names, 0, False)
        if ok:
            d = defs[names.index(choice)]
            exp = {c["name"] for c in self.session.workflow.sources[source].expected_columns}
            miss = [k for k in d.key_columns if k not in exp]
            if miss and not ask(self, "Seçilen tanımın şu sütunları bu kaynakta yok: " + ", ".join(miss[:8])
                                + "\n\nYine de bağlansın mı?"):
                return
            self._apply(lambda: self.session.link_report(source, d.id))

    def define_from_source(self, source):
        df = self.session.data.get(source)
        if df is None:
            info(self, "Bu kaynağın verisi yüklü değil; önce veriyi yükleyin.")
            return
        spec = self.session.workflow.sources[source]
        dlg = rdlg.DefineReportDialog(df, os.path.basename(spec.path) or source, spec.sheet or "", self.library, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._apply(lambda: self.session.link_report(source, dlg.definition.id))

    def edit_run_settings(self) -> bool:
        d = sdlg.ReportSettingsDialog(self.session.workflow, self, shifts=self.session.shifts)
        if d.exec() != QDialog.Accepted:
            return False
        self._apply(lambda: self.session.set_run_settings(d.settings_dict()))
        return True

    # ================================================================ dönem, referans, arşiv
    def _period_changed(self, period):
        self.session.set_period(period)
        if self.current:
            self.refresh_all()

    def edit_shifts(self):
        if self.library is None:
            return
        if sdlg.ShiftSettingsDialog(self.library, self).exec() == QDialog.Accepted:
            self.period_bar.reload_shifts()
            self.period_bar.set_auto()

    def _ref_frame(self, default_name=""):
        """Referans tablo için veri al: dosyadan, panodan veya açık Excel'den."""
        from PySide6.QtWidgets import QInputDialog
        choices = ["Dosyadan…", "Panodan (Excel'den kopyalanan)", "Açık Excel'den…"]
        choice, ok = QInputDialog.getItem(self, "Referans tablo", "Veri nereden alınsın?", choices, 0, False)
        if not ok:
            return None
        df, name = None, default_name
        if choice == choices[0]:
            path = pick_file(self, self.settings)
            if not path:
                return None
            d = ImportDialog(self, path=path, name=default_name or None or "")
            if d.exec() != QDialog.Accepted or d.df is None:
                return None
            df, name = d.df, default_name or d.name.text().strip()
        elif choice == choices[1]:
            d = ImportDialog(self, text=QGuiApplication.clipboard().text(), name=default_name or "Referans")
            if d.exec() != QDialog.Accepted or d.df is None:
                return None
            df, name = d.df, default_name or d.name.text().strip()
        else:
            d = rdlg.OpenReportsDialog(self.provider, None, self, settings=self.settings)
            if d.exec() != QDialog.Accepted or d.result_df is None:
                return None
            df, name = d.result_df, default_name or d.result_name
        if not default_name:
            new = ask_text(self, "Referans tablo", "Tablonun adı:", name)
            if not new:
                return None
            name = new
        return name, df, ""

    def open_references(self):
        if self.library is None:
            return
        d = sdlg.ReferenceTablesDialog(self.library, self, get_frame=self._ref_frame)
        if d.exec() == QDialog.Accepted and d.chosen:
            m = d.chosen
            holder = {}
            if self._apply(lambda: holder.setdefault("n", self.session.add_source(
                    m["name"], self.library.reference_df(m["id"]), kind="reference", reference_id=m["id"]))):
                self.refresh_all(holder["n"])
        else:
            self.session.refresh_references()
            self.refresh_all()

    def save_as_reference(self, source):
        df = self.session.data.get(source)
        if df is None or self.library is None:
            return
        name = ask_text(self, "Referans tablo olarak kaydet", "Referans tablonun adı:", source)
        if not name:
            return
        try:
            m = self.library.save_reference(name, df, "İş akışından kaydedildi")
        except ShiftFlowError as exc:
            show_error(self, exc)
            return

        def mut():
            def f(wf):
                sp = wf.sources[source]
                sp.reference_id, sp.kind, sp.report_id = m["id"], "reference", None
            self.session._commit(f, check=[])
            self.session._ref_versions[source] = m["updated"]
        self._apply(mut)
        info(self, f"'{name}' referans tablo olarak kaydedildi. Bu kaynak artık her çalıştırmada kütüphaneden okunur; "
                   "içeriği 'Referans tablolar' bölümünden yenileyebilirsiniz.")

    def open_archive(self):
        if self.archive is None:
            info(self, "Rapor arşivi açılamadı.")
            return
        d = sdlg.ArchiveDialog(self.archive, self, period=self.period_bar.period(), shifts=self.session.shifts)
        if d.exec() == QDialog.Accepted and d.source_spec:
            spec = d.source_spec
            from ..engine.archive import describe_range
            name = f"{spec['set'].split(' / ')[-1]} ({describe_range(spec['range'])})"
            try:
                df, _ = self.archive.resolve(spec, self.period_bar.period(), self.session.shifts)
            except ShiftFlowError as exc:
                show_error(self, exc)
                return
            holder = {}
            if self._apply(lambda: holder.setdefault("n", self.session.add_source(
                    name, df, kind="archive", archive=spec)), background=True):
                self.refresh_all(holder["n"])

    def _builder(self):
        return ReportBuilder(self.session, self.library, self.provider, self.archive, self.period_bar.period())

    def load_from_open_reports(self):
        """İş akışı açılınca: açık raporları bul ve hazır olanları yükle (çıktı yazmaz)."""
        b = self._builder()
        try:
            with busy():
                plans = b.plan()
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        for p in plans:
            if not p.blocking and p.df is not None:
                self.session.bind_source(p.source, p.df, column_map=p.column_map)
        with busy():
            self.session.run_all()
        self.refresh_all()
        waiting = [p.source for p in plans if p.blocking]
        msg = "Açık raporlardan çalıştırmak için ▶ Rapor oluştur (F9)."
        if waiting:
            msg = f"Hazır olmayan kaynaklar: {', '.join(waiting)}. " + msg
        self.statusBar().showMessage(msg, 15000)

    def build_report(self):
        if not self.session.workflow.sources:
            info(self, "Önce bir rapor veya dosya ekleyin, işlemleri tanımlayın ve iş akışını kaydedin.")
            return
        if not self.session.workflow.run_settings.get("output_dir"):
            if not self.edit_run_settings():
                return
        b = self._builder()
        try:
            with busy():
                plans = b.plan()
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        if any(p.blocking for p in plans):
            d = rdlg.RunPlanDialog(b, plans, self, settings=self.settings)
            if d.exec() != QDialog.Accepted:
                self.refresh_all()
                return
            plans = d.plans
        write_archive = True
        conflicts = b.archive_conflicts()
        if conflicts:
            r = QMessageBox.question(
                self, "Bu dönem daha önce oluşturulmuş",
                f"{b.period.label} dönemi arşivde zaten var:\n" + "\n".join(conflicts)
                + "\n\nYeniden oluşturulursa arşivdeki kayıt bu sonuçla değiştirilecek. Devam edilsin mi?\n"
                  "(Hayır: rapor oluşturulur ama arşive yazılmaz)",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return
            write_archive = r == QMessageBox.Yes
        try:
            res = self.task(lambda: b.build(plans, archive=write_archive), "Rapor oluşturuluyor…")
        except ShiftFlowError as exc:
            show_error(self, exc)
            self.refresh_all()
            return
        self.refresh_all()
        if not res.ok:
            lines = [f"• {k}: {v.message}" for k, v in res.errors.items()]
            QMessageBox.warning(self, "Rapor oluşturulamadı",
                                "\n".join(res.notes) + "\n\nHatalı veri kümeleri:\n" + "\n".join(lines[:15]))
            return
        text = f"Rapor oluşturuldu:\n{os.path.normpath(res.path)}\n\nSayfalar: {', '.join(res.sheets)}\n\n" + "\n".join(res.notes[:20])
        if self.session.dirty and self.workflow_path:
            text += "\n\nİş akışında kaydedilmemiş değişiklikler var (örn. yeni sütun eşlemesi). Kaydetmeyi unutmayın."
        elif not self.workflow_path:
            text += "\n\nİpucu: İş akışını kaydedin (Ctrl+S); yarın açıp yalnızca ▶ Rapor oluştur demeniz yeterli."
        draft = None
        try:
            draft = mail_draft(b, res)
        except ShiftFlowError as exc:
            show_error(self, exc, "Mail hazırlanamadı")
        if draft is None:
            info(self, text, "Rapor oluşturuldu")
        self.statusBar().showMessage(f"Rapor oluşturuldu: {os.path.normpath(res.path)}", 15000)
        if self.session.workflow.run_settings.get("open_after", True) and hasattr(os, "startfile"):
            try:
                os.startfile(res.path)  # type: ignore[attr-defined]
            except OSError:
                pass
        if draft is not None:
            md = sdlg.MailPreviewDialog(draft, self.outlook, self)
            md.setWindowTitle(f"Rapor oluşturuldu — mail önizleme ({os.path.basename(res.path)})")
            md.exec()
            done = {"draft": "Mail Outlook'ta taslak olarak açıldı.", "sent": "Mail gönderildi.",
                    "eml": "Mail taslağı .eml olarak açıldı."}.get(md.result_action)
            if done:
                self.statusBar().showMessage(done, 10000)

    # ================================================================ işlem arama ve Excel formülü
    def selected_column(self) -> str | None:
        df = self.table.model_.frame()
        if df is None or not df.shape[1]:
            return None
        cols = self.table.selectionModel().selectedColumns()
        if cols:
            return str(df.columns[cols[0].column()])
        idx = self.table.currentIndex()
        if idx.isValid() and self.table.selectionModel().hasSelection():
            return str(df.columns[idx.column()])
        return None

    def formula_from_excel(self, text=""):
        if not self.current:
            return
        try:
            df = self.current_frame()
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        from .formula_dialogs import FormulaImportDialog
        d = FormulaImportDialog(self.session, self.current, df, self, mode="step", text=text or "")
        if d.exec() == QDialog.Accepted and d.params:
            p, op = d.params, d.op
            pos = self.insert_position()
            if self._apply(lambda: self.session.add_step(self.current, op, p, pos), background=True) \
                    and op == "excel_formula":
                info(self, f"'{p['name']}' sütunu çıktı dosyasına Excel formülü olarak yazılacak:\n{p['template']}\n\n"
                           "ShiftFlow'da bu sütun boş görünür; değeri Excel dosyası açılınca hesaplanır."
                           + ("\n\n" + "\n".join("⚠ " + w for w in d.excel_warnings) if d.excel_warnings else ""))

    # ---------------------------------------------------------------- Excel'deki formüllü sütunlar
    def _workbook_choices(self, spec):
        """(sağlayıcı, [(kitap, sayfa)]) — açık Excel kitapları + kaynağın kayıtlı dosyası."""
        from ..engine.excel_live import FileWorkbookProvider, MultiProvider
        provs = [self.provider]
        if spec is not None and spec.path and os.path.splitext(spec.path)[1].lower() in (".xlsx", ".xlsm") \
                and os.path.exists(spec.path):
            provs.append(FileWorkbookProvider([spec.path]))
        prov = MultiProvider(provs)
        books = prov.list_workbooks()
        return prov, [(wb, sh) for wb in books for sh in wb.sheets]

    def formula_columns_from_excel(self):
        if not self.current:
            return
        wf = self.session.workflow
        ds = wf.dataset(self.current)
        spec = wf.sources.get(ds.origin.source) if ds.origin.type == "source" else None
        if spec is None:
            info(self, "Bu işlem rapordan alınan (kaynak) tablolarda çalışır. Soldan kaynak tabloyu seçin.")
            return
        try:
            with busy():
                prov, pairs = self._workbook_choices(spec)
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        if not pairs:
            info(self, "Açık Excel kitabı bulunamadı. Raporu Excel'de açın (veya kaynağın dosyası .xlsx olsun).")
            return
        norm = lambda x: os.path.normcase(os.path.abspath(x)) if x else ""  # noqa: E731
        match = [(wb, sh) for wb, sh in pairs if spec.path and norm(wb.path) == norm(spec.path)
                 and (not spec.sheet or sh.name == spec.sheet)]
        excel_first = sorted(match, key=lambda x: x[0].origin != "excel")  # açık kitap dosyadan önce
        if excel_first:
            wb, sh = excel_first[0]
        else:
            from PySide6.QtWidgets import QInputDialog
            labels = [f"{wb.name} › {sh.name}" + ("" if wb.origin == "excel" else " (dosya)") for wb, sh in pairs]
            choice, ok = QInputDialog.getItem(self, "Excel'deki formüllü sütunlar",
                                              f"'{self.current}' tablosu Excel'de hangi sayfada?", labels, 0, False)
            if not ok:
                return
            wb, sh = pairs[labels.index(choice)]
        from .formula_dialogs import FormulaColumnsDialog
        try:
            d = FormulaColumnsDialog(self.session, self.current, prov, wb.id, sh.name, self,
                                     load_sheet=lambda name, ref: self._load_workbook_sheet(prov, wb, name, ref))
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        if d.exec() == QDialog.Accepted and d.steps:
            steps, target = d.steps, self.current
            if self._apply(lambda: self.session.add_formula_steps(target, steps), background=True):
                self.statusBar().showMessage(f"{len(steps)} formüllü sütun adım olarak eklendi.", 6000)
        else:
            self.refresh_all()

    def open_in_excel(self):
        """Seçili tabloyu geçici bir dosyaya yazıp Excel'de açar (adlandırma/kaydetme sorulmaz)."""
        if not self.current:
            return
        import tempfile
        from datetime import datetime
        folder = os.path.join(tempfile.gettempdir(), "ShiftFlow")
        os.makedirs(folder, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in self.current)[:60]
        path = os.path.join(folder, f"{safe} {datetime.now():%H%M%S}.xlsx")
        name = self.current
        try:
            self.task(lambda: self.session.export(path, [(name, name)]), "Excel'e yazılıyor…")
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        if hasattr(os, "startfile"):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
                self.statusBar().showMessage(f"Excel'de açıldı (geçici dosya): {path}", 8000)
                return
            except OSError:
                pass
        info(self, f"Geçici dosya oluşturuldu:\n{os.path.normpath(path)}\n\nBu bilgisayarda dosya otomatik açılamadı.")

    def open_wms_probe(self):
        from .automation_dialogs import WmsProbeDialog
        WmsProbeDialog(self).exec()

    def open_schedule(self):
        from .automation_dialogs import ScheduleDialog
        ScheduleDialog(self, self.settings).exec()

    def open_trash(self):
        sdlg.TrashDialog(self.library, self.archive, self).exec()
        self.session.refresh_references()
        self.refresh_all()

    def open_dashboard(self):
        if not self.session.workflow.datasets:
            info(self, "Önce veri ekleyin.")
            return
        from .dashboard_ui import DashboardDialog
        DashboardDialog(self).exec()

    def open_packages(self):
        from .package_dialogs import PackageDialog
        last = self.settings.value("last_package", "")
        PackageDialog(self, self.settings, last if last and os.path.exists(last) else None).exec()

    def open_parameters(self):
        from ..engine import expression
        usage = {}
        for ds in self.session.workflow.datasets.values():
            for i, st in enumerate(ds.steps, start=1):
                texts = [str(v) for k, v in st.params.items() if isinstance(v, str)]
                for r in st.params.get("rules", []) or []:
                    texts.append(str(r.get("value", "")))
                for t in texts:
                    for name in expression.referenced_params(t):
                        key = next((k for k in self.session.parameters if k.lower() == name.lower()), name)
                        usage.setdefault(key, set()).add(f"{ds.name} › {i}. adım")
        d = sdlg.ParametersDialog(self.session.parameters, self, {k: ", ".join(sorted(v)) for k, v in usage.items()})
        if d.exec() == QDialog.Accepted:
            vals = d.values()
            if self._apply(lambda: self.session.set_parameters(vals), background=True):
                self.statusBar().showMessage("Parametreler kaydedildi; formüller yeniden hesaplandı.", 5000)

    def _load_workbook_sheet(self, prov, wb, sheet, as_reference):
        """Formülün kullandığı sayfayı aynı kitaptan yükler (referans tablo veya kaynak olarak)."""
        from ..engine import reports as rp
        rows = prov.read(wb.id, sheet)
        if not rows:
            raise ShiftFlowError(f"'{sheet}' sayfası boş.")
        df = sio.frame_from_rows(rows, rp.guess_header_row(rows))
        if as_reference and self.library is not None:
            m = self.library.save_reference(sheet, df, f"{wb.name} kitabından")
            return self.session.add_source(sheet, df, kind="reference", reference_id=m["id"])
        kind = "file" if wb.saved else "paste"
        return self.session.add_source(sheet, df, kind=kind, path=wb.path if wb.saved else "", sheet=sheet)

    def palette_commands(self) -> list[Command]:
        from ..engine.values import type_kind
        cmds: list[Command] = []
        has = self.current is not None
        col = self.selected_column() if has else None
        kind = None
        if col:
            try:
                kind = type_kind(self.table.model_.frame()[col])
            except Exception:
                kind = None
        kw = {
            "filter": "süz ayıkla filtrele koşul where eleme", "sort": "sırala order artan azalan büyükten küçükten",
            "calc": "formül hesap hesapla sütun ekle formula işlem çarp böl topla",
            "conditional": "eğer if koşullu sütun", "select": "sütun seç sırala gizle kaldır düzen",
            "rename": "ad değiştir isim başlık yeniden adlandır", "convert": "tip dönüştür sayıya tarihe metne çevir",
            "text_clean": "boşluk kırp trim büyük küçük harf temizle düzelt", "replace": "bul değiştir yerine koy",
            "dedupe": "tekrar mükerrer çift kayıt benzersiz unique", "lookup": "düşeyara vlookup çaprazara xlookup "
            "eşleştir getir ara bağla başka tablodan", "rules": "kural tablosu sınıflandır kategori etiket çok koşul",
            "period_filter": "vardiya dönem saat filtre tarih aralığı gece gündüz", "remove": "sütun sil kaldır",
            "unify": "boşluk harf farklı yazım aynı değer birleştir düzelt standart tutarlı",
            "fill_down": "aşağı doldur birleştirilmiş hücre boş üstteki değer tekrarla ffill",
            "drop_empty_rows": "boş satır sil kaldır at temizle dolu satır formül aşağı çekilmiş",
            "validate": "doğrula kontrol denetle kalite boş tekrar aralık satır sayısı durdur hata",
            "fill_empty": "boş doldur sıfır yaz eksik değer varsayılan",
            "split": "böl ayır parçala metni sütunlara dönüştür lokasyon tire ayırıcı",
            "unpivot": "satırlara çevir özet dışı bırak unpivot melt yan yana sütun vardiya gün",
        }
        for key, cls in dlg.STEP_DIALOGS.items():
            op = ops.get(key)
            desc = (cls.help_text or op.label).split(". ")[0].rstrip(".")
            boost = 0
            if col and key in ("filter", "sort", "convert", "replace", "text_clean", "dedupe", "rename", "split",
                               "fill_down"):
                boost = 20
            if kind == "date" and key == "period_filter":
                boost = 60
            if kind == "text" and key in ("text_clean", "lookup", "unify"):
                boost = 40
            cmds.append(Command(op.label + (f": {col}" if col else ""), desc,
                                lambda k=key: self.add_step(k, preset=col), "Adım", kw.get(key, ""), boost, has))
        cmds.append(Command("Sütun kaldır" + (f": {col}" if col else ""), "Seçili sütunları kaldırır",
                            lambda: self.add_step("remove", preset=col), "Adım", kw["remove"], 10 if col else 0, has))
        two = len(self.session.workflow.datasets) >= 2
        for title, desc, fn, k, en in (
                ("Birleştir (iki tablo)", "Ortak anahtarla iki tabloyu yan yana birleştirir", self.add_join,
                 "join merge birleştir eşleştir sol iç tam", two),
                ("Alt alta ekle", "Aynı biçimdeki tabloları tek listede toplar", self.add_append,
                 "append union alt alta birleştir liste", two),
                ("Grupla ve özetle", "Toplam, adet, ortalama…", lambda: self.add_derived("group", preset=col),
                 "grupla özet sum count topla say", has),
                ("Pivot tablo", "Satır/sütun alanlarıyla özet tablo", lambda: self.add_derived("pivot", preset=col),
                 "pivot özet çapraz tablo", has)):
            cmds.append(Command(title, desc, fn, "Yeni tablo", k, 0, en))
        cmds.append(Command("Excel formülünden sütun", "Excel'deki formülü yapıştır, ShiftFlow'a çevir",
                            self.formula_from_excel, "Formül",
                            "excel formül yapıştır çevir eğersay etopla indis kaçıncı", 0, has))
        cmds.append(Command("Parametreler", "Formüllerde {Ad} ile kullanılan sabitler (hedef oranı, mola süresi)",
                            self.open_parameters, "Ayarlar", "parametre sabit hedef oran $h$1 sabit hücre değişken",
                            0, True))
        cmds.append(Command("Excel'deki formüllü sütunları al", "Raporun yanına eklenen formüllü sütunları tek "
                            "seferde adımlara çevir", self.formula_columns_from_excel, "Formül",
                            "excel formül sütun hepsi otomatik açık kitap yanındaki sütunlar düşeyara", 0, has))
        if col:
            q = '"' + col.replace('"', '""') + '"'
            c = f"[{col}]"
            others = [n for n in self.session.workflow.datasets if n != self.current]
            tbl = '"' + (others[0] if others else "Tablo") + '"'
            temps = [
                ("A → Z sırala", "Seçili sütuna göre artan", lambda: self.quick_step(
                    "sort", {"keys": [{"column": col, "ascending": True}]}), "sırala artan", "Hızlı"),
                ("Z → A sırala", "Seçili sütuna göre azalan", lambda: self.quick_step(
                    "sort", {"keys": [{"column": col, "ascending": False}]}), "sırala azalan", "Hızlı"),
                ("Boş olanları çıkar", "Bu sütunu boş satırları eler", lambda: self.quick_step(
                    "filter", {"conditions": [{"column": col, "op": "not_empty"}], "mode": "and"}), "boş filtre", "Hızlı"),
                ("Bu sütuna göre tekrarları kaldır", "Aynı değerden yalnızca biri kalır", lambda: self.quick_step(
                    "dedupe", {"columns": [col], "keep": "first"}), "tekrar mükerrer", "Hızlı"),
            ]
            formulas = [
                ("Tekrar sayısı", f'EĞERSAY("BU"; {q}; {c})', "eğersay countif kaç kez tekrar sayı"),
                ("Başka tablodan getir (DÜŞEYARA)", f"DÜŞEYARA({c}; {tbl}; 2; 0)", "düşeyara vlookup getir"),
                ("Boşsa değer ver", f'EĞER(EBOŞSA({c}); "Yok"; {c})', "boş eğer ebosşa"),
            ]
            if kind == "number":
                formulas += [
                    ("Yuvarla", f"YUVARLA({c}; 1)", "yuvarla round"),
                    ("Toplam içindeki pay %", f'YUVARLA({c} / TABLOTOPLA("BU"; {q}) * 100; 1)', "pay yüzde oran toplam"),
                    ("Ortalamanın üstünde mi", f'EĞER({c} > TABLOORT("BU"; {q}); "Üstünde"; "Altında")',
                     "ortalama üst alt karşılaştır"),
                    ("Hata/boşsa 0", f"EĞERHATA({c}; 0)", "eğerhata hata sıfır"),
                ]
            elif kind == "date":
                formulas += [
                    ("Saat", f"SAAT({c})", "saat hour"), ("Haftanın günü", f"HAFTANINGÜNÜ({c}; 2)", "gün hafta"),
                    ("Tarih metni", f'METNEÇEVİR({c}; "gg.aa.yyyy")', "tarih metin biçim"),
                ]
            else:
                formulas += [
                    ("İlk 3 karakter", f"SOLDAN({c}; 3)", "soldan left parça"),
                    ("Boşlukları temizle", f"KIRP({c})", "kırp trim boşluk"),
                    ("Büyük harf", f"BÜYÜKHARF({c})", "büyük harf upper"),
                    ("Başka sütunla birleştir", f'{c} & "-" & {c}', "birleştir concat metin"),
                ]
            for t, d, fn, k, g in temps:
                cmds.append(Command(f"{t}: {col}", d, fn, g, k, 50, has))
            for t, f, k in formulas:
                cmds.append(Command(f"{t}: {col}", f, lambda f=f, t=t: self.add_step(
                    "calc", params={"name": f"{col} - {t}", "formula": f}), "Formül", k, 25, has))
        for t, d, a, k in (
                ("Rapor oluştur", "Açık raporları bul, çalıştır, Excel çıktısını oluştur", self.a_build, "rapor oluştur çalıştır f9"),
                ("Excel'e aktar", "Seçili tabloları Excel dosyasına yaz", self.a_export, "dışa aktar export kaydet excel"),
                ("Excel'de aç", "Seçili tabloyu kaydetmeden Excel'de aç", self.a_open_in_excel,
                 "excel aç gönder hızlı bak geçici"),
                ("Açık Excel'den al", "Açık kitaplardan rapor al", self.a_open_excel, "açık excel kitap rapor al"),
                ("Dosya aç", "Excel/CSV dosyası ekle", self.a_open, "dosya aç ekle import"),
                ("Klasörden dosyalar", "Klasördeki tüm günlük dosyaları alt alta al", self.a_folder,
                 "klasör çoklu dosya birleştir alt alta günlük toplu"),
                ("Yapıştır", "Panodaki tabloyu yeni kaynak yap", self.a_paste, "yapıştır pano kopyala"),
                ("Referans tablolar", "Sabit tablolar (lokasyon, ürün, personel)", self.a_refs, "referans sabit ana veri"),
                ("Arşiv", "Geçmiş dönemler, önceki vardiya", self.a_archive, "arşiv geçmiş önceki vardiya dün"),
                ("Vardiyalar", "Vardiya saatlerini tanımla", self.a_shifts, "vardiya saat tanım"),
                ("Rapor ayarları", "Çıktı, arşiv, şablon, mail", self.a_run_settings, "ayar mail şablon klasör"),
                ("Rapor tanımları", "Raporları bir kez tanımla", self.a_reports, "rapor tanım tanıma"),
                ("WMS ekranını incele", "WMS penceresi ekran otomasyonuna uygun mu?", self.a_wms_probe,
                 "wms otomasyon rpa teşhis incele pywinauto ekran"),
                ("Zamanlanmış görev", "Paketi vardiya sonlarında otomatik çalıştır", self.a_schedule,
                 "zamanla görev zamanlayıcı otomatik saat vardiya sonu komut satırı"),
                ("Çöp kutusu", "Silineni geri getir (rapor tanımı, referans tablo, arşiv)", self.a_trash,
                 "çöp geri al geri yükle silinen kurtar sildim"),
                ("Gösterge paneli", "Sayı ve grafik kutucukları; arşivle eğilim", self.a_dashboard,
                 "dashboard gösterge panel grafik kpi eğilim trend özet ekran"),
                ("Rapor paketleri", "Birden çok iş akışını sırayla çalıştır", self.a_package,
                 "paket toplu hepsi birden çok akış sırayla vardiya sonu tüm raporlar"),
                ("Akışı kaydet", "İş akışını JSON olarak kaydet", self.a_wf_save, "kaydet save akış"),
                ("Akış aç", "Kayıtlı iş akışını aç", self.a_wf_open, "aç akış senaryo"),
                ("Geri al", "Son değişikliği geri al", self.a_undo, "geri al undo"),
                ("Yinele", "Geri alınanı yinele", self.a_redo, "yinele redo")):
            cmds.append(Command(t, d, a.trigger, "Uygulama", k, 0, a.isEnabled()))
        return cmds

    def open_palette(self):
        col = self.selected_column() if self.current else None
        ctx = f"Tablo: {self.current}" + (f" · Seçili sütun: {col}" if col else " · (Bir sütun seçerseniz ona uygun işlemler öne çıkar)") \
            if self.current else "Henüz veri yok: Dosya aç, Yapıştır veya Açık Excel'den al ile başlayın."
        d = CommandPalette(self.palette_commands(), self, ctx)
        g = self.geometry()
        d.move(g.x() + (g.width() - d.width()) // 2, g.y() + 90)
        if d.exec() == QDialog.Accepted and d.chosen:
            d.chosen.run()

    def new_session(self):
        if not self._confirm_discard():
            return
        self.session = Session()
        self.session.library = self.library
        self.session.archive = self.archive
        self.workflow_path = None
        self.current, self.view_step = None, None
        self.refresh_all()

    def about(self):
        info(self, f"{APP_NAME} {__version__}\n\nTekrarlanabilir Excel rapor iş akışları.\n"
                   f"Excel okuma motoru: {sio.excel_engine()}\nVeriler yalnızca bu bilgisayarda işlenir.")

    def closeEvent(self, e):
        if self._confirm_discard():
            self._autosave.stop()
            self.recovery.clear()
            e.accept()
        else:
            e.ignore()
