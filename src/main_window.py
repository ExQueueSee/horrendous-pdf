"""
PDF Editor Application
- Open & view PDFs with zoom and page navigation
- Add sticky note annotations
- Highlight text (select text → highlight)
- Freehand drawing (pen tool)
- Add text boxes
- Rectangle annotations
- Undo / Redo (Ctrl+Z / Ctrl+Shift+Z)
- Text selection from PDF content
- Save annotated PDFs
"""

import sys
import os
import json
import math
import fitz  # PyMuPDF
from collections import OrderedDict
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QToolBar, QAction, QFileDialog, QStatusBar,
    QSpinBox, QLabel, QColorDialog, QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsLineItem, QGraphicsPathItem, QInputDialog, QMessageBox,
    QComboBox, QSlider, QWidget, QHBoxLayout, QVBoxLayout, QSizePolicy,
    QGraphicsEllipseItem, QDockWidget, QListWidget, QListWidgetItem,
    QMenu, QTextEdit, QDialog, QDialogButtonBox, QPushButton,
    QGraphicsItem, QToolTip, QGraphicsPolygonItem, QFontComboBox,
    QCheckBox, QGraphicsProxyWidget, QActionGroup, QFormLayout,
    QGroupBox, QRadioButton, QLineEdit,
    QTabBar, QStackedWidget, QFrame, QToolButton, QAbstractSpinBox,
    QScrollArea
)
from PyQt5.QtGui import (
    QPixmap, QImage, QPainter, QPen, QColor, QBrush, QFont,
    QIcon, QPainterPath, QCursor, QKeySequence, QTransform,
    QFontMetricsF, QTextCursor, QTextCharFormat, QTextBlockFormat
)
from PyQt5.QtCore import (
    Qt, QRectF, QPointF, QSizeF, pyqtSignal, QSize, QTimer, QByteArray,
    QPropertyAnimation, QEasingCurve
)
from PyQt5.QtWidgets import QGraphicsOpacityEffect
from PyQt5.QtGui import QPolygonF

# --- Project imports (extracted modules) ---
from src.models.annotation import Annotation
from src.items.sticky_note import StickyNoteItem
from src.items.text_block import EditableTextBlockItem
from src.graphics_view import PDFGraphicsView
from src.dialogs import (
    LinkDialog, StampDialog, SignatureDialog,
    PageNumberDialog, HeaderFooterDialog, WatermarkDialog,
    STAMP_PRESETS, _get_data_dir, _get_stamp_dir, _get_signature_dir,
)

# Keep backward-compatible alias for the stamps list
_STAMP_PRESETS = STAMP_PRESETS


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------
class PDFEditorWindow(QMainWindow):
    PAGE_GAP = 20  # pixels between pages in continuous scroll
    TILE_PIXELS = 512  # each rendered tile is always ≤512×512 output px

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Editor")
        self.resize(1200, 800)

        self._doc = None
        self._current_page = 0
        self._total_pages = 0
        self._file_path = None
        self._dpi = 150
        self._annotations = []
        self._scene = None           # single continuous scene
        self._page_offsets = []      # Y position of each page in the scene
        self._page_heights = []      # rendered pixel height per page
        self._page_widths = []       # rendered pixel width per page
        self._page_placeholders = {} # page_num -> QGraphicsRectItem (placeholder)
        self._tile_items = {}        # (page, row, col) -> QGraphicsPixmapItem
        self._tile_cache = OrderedDict()  # (page, row, col, ts_key) -> QPixmap
        self._tile_cache_max = 200   # max tiles in LRU cache
        self._current_tile_ss = 0.0  # tile scene-size of currently rendered tiles
        self._tile_generation = 0    # incremented on zoom for cancellation
        self._updating_spinner = False  # guard against recursive spin signals
        self._page_border_items = {}   # page_num -> QGraphicsRectItem (border)
        self._page_shadow_items = {}   # page_num -> QGraphicsRectItem (shadow)
        self._separator_items = []     # list of QGraphicsLineItem separators

        # -- theme / dark mode -----------------------------------------------
        # "system" = follow OS, "dark" = always dark, "light" = always light
        self._theme_mode = "system"
        self._dark_mode = self._is_system_dark()  # resolved boolean
        self._themes = {
            "light": { 
                "scene_bg": QColor(150, 150, 150),
                "page_border": QColor(80, 80, 80),
                "page_shadow": QColor(0, 0, 0, 50),
                "placeholder_bg": QColor(255, 255, 255),
                "placeholder_border": QColor(200, 200, 200),
                "separator": QColor(120, 120, 120),
                "note_bg": QColor(255, 235, 59),
                "note_border": QColor(200, 180, 0),
                "note_text": QColor(0, 0, 0),
            },
            "dark": {
                "scene_bg": QColor(45, 45, 45),
                "page_border": QColor(90, 90, 90),
                "page_shadow": QColor(0, 0, 0, 100),
                "placeholder_bg": QColor(60, 60, 60),
                "placeholder_border": QColor(80, 80, 80),
                "separator": QColor(70, 70, 70),
                "note_bg": QColor(200, 180, 40),
                "note_border": QColor(160, 140, 0),
                "note_text": QColor(220, 220, 220),
            },
        }

        # -- persisted settings (loaded from JSON) ---------------------------
        # When running as a PyInstaller exe, __file__ points to a temp dir.
        # Use the exe's real location so settings survive between launches.
        if getattr(sys, 'frozen', False):
            _app_dir = os.path.dirname(sys.executable)
        else:
            # __file__ is now src/main_window.py → go up one level to project root
            _app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._settings_path = os.path.join(_app_dir, "settings.json")
        self._author_name = ""
        self._recent_files = []  # most-recent first, max 10
        self._max_recent = 10

        # -- document-level undo (full PDF snapshots) -----------------------
        self._doc_undo_stack = []   # list of (label, bytes)
        self._doc_redo_stack = []   # list of (label, bytes)
        self._doc_undo_limit = 10   # max snapshots kept

        self._setup_ui()
        self._create_actions()
        self._create_ribbon()
        self._create_statusbar()
        self._create_sidebar()
        self._update_ui_state()

        # Load persisted settings (must happen AFTER UI is built)
        self._load_settings()

    # -- UI setup -----------------------------------------------------------
    def _setup_ui(self):
        # -- Main container --------------------------------------------------
        container = QWidget()
        main_vbox = QVBoxLayout(container)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(0)

        # Ribbon tab bar
        self._ribbon_tabbar = QTabBar()
        self._ribbon_tabbar.setObjectName("ribbonTabBar")
        self._ribbon_tabbar.setExpanding(False)
        self._ribbon_tabbar.setDrawBase(False)
        main_vbox.addWidget(self._ribbon_tabbar)

        # Ribbon content (stacked pages)
        self._ribbon_stack = QStackedWidget()
        self._ribbon_stack.setObjectName("ribbonStack")
        self._ribbon_stack.setFixedHeight(80)
        self._ribbon_tabbar.currentChanged.connect(self._ribbon_stack.setCurrentIndex)
        self._ribbon_tabbar.currentChanged.connect(self._on_ribbon_tab_changed)
        main_vbox.addWidget(self._ribbon_stack)

        # Thin separator below ribbon
        ribbon_line = QFrame()
        ribbon_line.setFrameShape(QFrame.HLine)
        ribbon_line.setObjectName("ribbonBottomLine")
        ribbon_line.setFixedHeight(1)
        main_vbox.addWidget(ribbon_line)

        # Content area: left sidebar + PDF view
        content = QWidget()
        content_hbox = QHBoxLayout(content)
        content_hbox.setContentsMargins(0, 0, 0, 0)
        content_hbox.setSpacing(0)

        # Left sidebar strip
        self._left_sidebar = QWidget()
        self._left_sidebar.setObjectName("leftSidebar")
        self._left_sidebar.setFixedWidth(38)
        sb_lay = QVBoxLayout(self._left_sidebar)
        sb_lay.setContentsMargins(4, 8, 4, 8)
        sb_lay.setSpacing(6)
        sb_lay.setAlignment(Qt.AlignTop)
        content_hbox.addWidget(self._left_sidebar)

        # PDF view
        self._view = PDFGraphicsView(self)
        self._view.link_clicked.connect(self._handle_link_click)
        self._view.annotation_added.connect(self._on_annotation_added)
        self._view.selection_changed.connect(self._on_selection_changed)
        self._view.undo_redo_changed.connect(self._update_undo_redo_state)
        self._view.zoom_changed.connect(self._on_zoom_changed)
        self._view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._view.horizontalScrollBar().valueChanged.connect(self._on_scroll)
        content_hbox.addWidget(self._view, 1)

        main_vbox.addWidget(content, 1)
        self.setCentralWidget(container)

        # Debounce timer for re-rendering after zoom
        self._zoom_render_timer = QTimer(self)
        self._zoom_render_timer.setSingleShot(True)
        self._zoom_render_timer.setInterval(250)  # ms
        self._zoom_render_timer.timeout.connect(self._rerender_for_zoom)

    # -- theme / dark-mode ---------------------------------------------------
    @staticmethod
    def _is_system_dark():
        """Detect whether the OS is using a dark colour scheme."""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return val == 0  # 0 means dark
        except Exception:
            return False  # default to light if detection fails

    def _resolve_dark_mode(self):
        """Set self._dark_mode based on self._theme_mode."""
        if self._theme_mode == "dark":
            self._dark_mode = True
        elif self._theme_mode == "light":
            self._dark_mode = False
        else:  # "system"
            self._dark_mode = self._is_system_dark()

    def _theme(self):
        """Return the current theme colour dict."""
        return self._themes["dark" if self._dark_mode else "light"]

    def _build_qss(self):
        """Build a QSS stylesheet for the current theme.

        Both light and dark modes use the *same* structural rules (padding,
        border-width, border-radius, spacing, margins) so that switching
        between modes never changes the geometry of any widget.  Only the
        colour values differ.
        """
        if self._dark_mode:
            c = {
                "win_bg":       "#1E1E2E",
                "tb_bg":        "#2A2A3C",
                "tb_border":    "#3A3A50",
                "tb_sep":       "#4A4A60",
                "btn_fg":       "#CDD6F4",
                "btn_bg":       "#313244",
                "btn_border":   "#45475A",
                "btn_hover":    "#3E3E58",
                "btn_hover_bdr":"#6C6CFF",
                "btn_checked":  "#3B3B5C",
                "btn_chk_bdr":  "#7C7CFF",
                "btn_chk_fg":   "#B4BEFE",
                "btn_disabled": "#585B70",
                "btn_pressed":  "#494970",
                "label_fg":     "#CDD6F4",
                "accent":       "#7C7CFF",
                "accent_soft":  "#5B5B9A",
                "spin_bg":      "#313244",
                "spin_fg":      "#CDD6F4",
                "spin_border":  "#45475A",
                "spin_arrow":   "#A6ADC8",
                "spin_arr_hov": "#CDD6F4",
                "spin_btn_hov": "#3E3E58",
                "slider_groove":"#45475A",
                "slider_fill":  "#7C7CFF",
                "slider_handle":"#A6ADC8",
                "slider_hnd_hv":"#CDD6F4",
                "sb_bg":        "#1E1E2E",
                "sb_fg":        "#CDD6F4",
                "sb_border":    "#313244",
                "dock_fg":      "#CDD6F4",
                "dock_title_bg":"#2A2A3C",
                "dock_btn_hov": "#3E3E58",
                "list_bg":      "#1E1E2E",
                "list_fg":      "#CDD6F4",
                "list_border":  "#313244",
                "list_sel":     "#3B3B5C",
                "list_sel_fg":  "#B4BEFE",
                "scroll_bg":    "#1E1E2E",
                "scroll_handle":"#45475A",
                "scroll_hnd_hv":"#585B70",
                "scroll_arrow": "#585B70",
                "menu_bg":      "#2A2A3C",
                "menu_fg":      "#CDD6F4",
                "menu_border":  "#3A3A50",
                "menu_sel":     "#3B3B5C",
                "menu_sel_fg":  "#B4BEFE",
                "dialog_bg":    "#1E1E2E",
                "dialog_fg":    "#CDD6F4",
                "dlg_btn_bg":   "#313244",
                "dlg_btn_fg":   "#CDD6F4",
                "dlg_btn_bdr":  "#45475A",
                "dlg_btn_hov":  "#3E3E58",
                "dlg_input_bg": "#313244",
                "dlg_input_fg": "#CDD6F4",
                "dlg_input_bdr":"#45475A",
                "dlg_input_foc":"#7C7CFF",
                "flat_btn_fg":  "#B4BEFE",
                "flat_btn_hov": "#3E3E58",
                "rib_tab_bg":  "#1A1A2A",
                "rib_tab_fg":  "#A6ADC8",
                "rib_tab_sel":  "#2A2A3C",
                "rib_tab_sel_fg":"#CDD6F4",
                "rib_tab_hov":  "#252538",
                "rib_tab_ind":  "#7C7CFF",
                "rib_bg":       "#2A2A3C",
                "rib_border":   "#3A3A50",
                "rib_grp_lbl":  "#585B70",
                "rib_sep":      "#3A3A50",
                "sidebar_bg":   "#1E1E2E",
                "sidebar_btn":  "#313244",
                "sidebar_btn_hv":"#3E3E58",
                "sidebar_btn_ck":"#3B3B5C",
            }
        else:
            c = {
                "win_bg":       "#F5F5FA",
                "tb_bg":        "#FFFFFF",
                "tb_border":    "#E0E0EA",
                "tb_sep":       "#D0D0DA",
                "btn_fg":       "#1A1A2E",
                "btn_bg":       "#FFFFFF",
                "btn_border":   "#C8C8D8",
                "btn_hover":    "#EEEEF8",
                "btn_hover_bdr":"#6C6CFF",
                "btn_checked":  "#E8E8F8",
                "btn_chk_bdr":  "#5555CC",
                "btn_chk_fg":   "#3A3A8C",
                "btn_disabled": "#A0A0B0",
                "btn_pressed":  "#D8D8F0",
                "label_fg":     "#1A1A2E",
                "accent":       "#5555CC",
                "accent_soft":  "#8888DD",
                "spin_bg":      "#FFFFFF",
                "spin_fg":      "#1A1A2E",
                "spin_border":  "#C8C8D8",
                "spin_arrow":   "#666680",
                "spin_arr_hov": "#1A1A2E",
                "spin_btn_hov": "#EEEEF8",
                "slider_groove":"#D0D0DA",
                "slider_fill":  "#5555CC",
                "slider_handle":"#888898",
                "slider_hnd_hv":"#5555CC",
                "sb_bg":        "#F5F5FA",
                "sb_fg":        "#1A1A2E",
                "sb_border":    "#E0E0EA",
                "dock_fg":      "#1A1A2E",
                "dock_title_bg":"#EEEEF8",
                "dock_btn_hov": "#D8D8F0",
                "list_bg":      "#FFFFFF",
                "list_fg":      "#1A1A2E",
                "list_border":  "#D0D0DA",
                "list_sel":     "#E8E8F8",
                "list_sel_fg":  "#3A3A8C",
                "scroll_bg":    "#F5F5FA",
                "scroll_handle":"#C0C0D0",
                "scroll_hnd_hv":"#A0A0B8",
                "scroll_arrow": "#888898",
                "menu_bg":      "#FFFFFF",
                "menu_fg":      "#1A1A2E",
                "menu_border":  "#D0D0DA",
                "menu_sel":     "#E8E8F8",
                "menu_sel_fg":  "#3A3A8C",
                "dialog_bg":    "#F5F5FA",
                "dialog_fg":    "#1A1A2E",
                "dlg_btn_bg":   "#FFFFFF",
                "dlg_btn_fg":   "#1A1A2E",
                "dlg_btn_bdr":  "#C8C8D8",
                "dlg_btn_hov":  "#EEEEF8",
                "dlg_input_bg": "#FFFFFF",
                "dlg_input_fg": "#1A1A2E",
                "dlg_input_bdr":"#C8C8D8",
                "dlg_input_foc":"#5555CC",
                "flat_btn_fg":  "#5555CC",
                "flat_btn_hov": "#EEEEF8",
                "rib_tab_bg":  "#2B2B3D",
                "rib_tab_fg":  "#B0B0C0",
                "rib_tab_sel":  "#FFFFFF",
                "rib_tab_sel_fg":"#1A1A2E",
                "rib_tab_hov":  "#3A3A50",
                "rib_tab_ind":  "#5555CC",
                "rib_bg":       "#FFFFFF",
                "rib_border":   "#E0E0EA",
                "rib_grp_lbl":  "#888898",
                "rib_sep":      "#D0D0DA",
                "sidebar_bg":   "#F0F0F8",
                "sidebar_btn":  "#E0E0EA",
                "sidebar_btn_hv":"#D0D0E0",
                "sidebar_btn_ck":"#C8C8E8",
            }

        return f"""
            /* ---- Main window ---- */
            QMainWindow {{ background: {c["win_bg"]}; }}

            /* ---- Ribbon tab bar ---- */
            #ribbonTabBar {{
                background: {c["rib_tab_bg"]};
                border: none;
                padding: 0;
            }}
            #ribbonTabBar::tab {{
                background: {c["rib_tab_bg"]};
                color: {c["rib_tab_fg"]};
                padding: 8px 28px;
                min-width: 60px;
                margin: 0;
                border: none;
                border-bottom: 2px solid transparent;
                font-size: 13px;
                font-weight: 600;
            }}
            #ribbonTabBar::tab:hover {{
                background: {c["rib_tab_hov"]};
                color: {c["rib_tab_sel_fg"]};
            }}
            #ribbonTabBar::tab:selected {{
                background: {c["rib_tab_sel"]};
                color: {c["rib_tab_sel_fg"]};
                border-bottom: 2px solid {c["rib_tab_ind"]};
            }}

            /* ---- Ribbon scroll area ---- */
            #ribbonScroll {{
                background: {c["rib_bg"]};
                border: none;
            }}
            #ribbonScroll QScrollBar:horizontal {{
                height: 4px;
                background: transparent;
            }}
            #ribbonScroll QScrollBar::handle:horizontal {{
                background: {c["scroll_handle"]};
                border-radius: 2px;
                min-width: 20px;
            }}
            #ribbonScroll QScrollBar::add-line:horizontal,
            #ribbonScroll QScrollBar::sub-line:horizontal {{
                width: 0; background: none;
            }}
            #ribbonScroll QScrollBar::add-page:horizontal,
            #ribbonScroll QScrollBar::sub-page:horizontal {{
                background: none;
            }}

            /* ---- Ribbon content area ---- */
            #ribbonStack {{
                background: {c["rib_bg"]};
                border: none;
            }}
            #ribbonPage {{
                background: {c["rib_bg"]};
            }}
            #ribbonBottomLine {{
                background: {c["rib_border"]};
                border: none;
            }}

            /* ---- Ribbon group ---- */
            #ribbonGroup {{
                background: transparent;
            }}
            QLabel#ribbonGroupLabel {{
                color: {c["rib_grp_lbl"]};
                font-size: 9px;
                font-weight: 600;
                padding: 0;
                background: transparent;
            }}
            QFrame#ribbonSep {{
                background: {c["rib_sep"]};
                border: none;
            }}

            /* ---- Ribbon buttons (QToolButton) ---- */
            QToolButton#ribbonBtn {{
                color: {c["btn_fg"]};
                background: {c["btn_bg"]};
                border: 1px solid {c["btn_border"]};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }}
            QToolButton#ribbonBtn:hover {{
                background: {c["btn_hover"]};
                border-color: {c["btn_hover_bdr"]};
            }}
            QToolButton#ribbonBtn:pressed {{
                background: {c["btn_pressed"]};
            }}
            QToolButton#ribbonBtn:checked {{
                background: {c["btn_checked"]};
                border: 1.5px solid {c["btn_chk_bdr"]};
                color: {c["btn_chk_fg"]};
                font-weight: bold;
            }}
            QToolButton#ribbonBtn:disabled {{
                color: {c["btn_disabled"]};
                border-color: transparent;
            }}

            /* ---- Flat drop-down buttons (Recent, Theme) ---- */
            QPushButton#recentBtn, QPushButton#themeBtn {{
                color: {c["flat_btn_fg"]};
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#recentBtn:hover, QPushButton#themeBtn:hover {{
                background: {c["flat_btn_hov"]};
                border-color: {c["btn_hover_bdr"]};
            }}
            QPushButton#recentBtn::menu-indicator, QPushButton#themeBtn::menu-indicator {{
                image: none;
                width: 0; height: 0;
            }}

            /* ---- Left sidebar ---- */
            #leftSidebar {{
                background: {c["sidebar_bg"]};
                border-right: 1px solid {c["rib_border"]};
            }}
            QPushButton#sidebarBtn {{
                background: {c["sidebar_btn"]};
                border: 1px solid transparent;
                border-radius: 4px;
                font-size: 14px;
                padding: 2px;
            }}
            QPushButton#sidebarBtn:hover {{
                background: {c["sidebar_btn_hv"]};
                border-color: {c["btn_hover_bdr"]};
            }}
            QPushButton#sidebarBtn:checked {{
                background: {c["sidebar_btn_ck"]};
                border-color: {c["accent"]};
            }}

            /* ---- Labels ---- */
            QLabel {{
                color: {c["label_fg"]};
                font-size: 12px;
            }}

            /* ---- SpinBoxes ---- */
            QSpinBox {{
                background: {c["spin_bg"]};
                color: {c["spin_fg"]};
                border: 1px solid {c["spin_border"]};
                border-radius: 5px;
                padding: 3px 6px;
                font-size: 12px;
            }}
            QSpinBox:focus {{
                border-color: {c["accent"]};
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background: {c["spin_bg"]};
                border: 1px solid {c["spin_border"]};
                width: 18px;
                border-radius: 2px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background: {c["spin_btn_hov"]};
            }}
            QSpinBox::up-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 5px solid {c["spin_arrow"]};
                width: 0; height: 0;
            }}
            QSpinBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {c["spin_arrow"]};
                width: 0; height: 0;
            }}
            QSpinBox::up-arrow:hover {{ border-bottom-color: {c["spin_arr_hov"]}; }}
            QSpinBox::down-arrow:hover {{ border-top-color: {c["spin_arr_hov"]}; }}

            /* ---- Status bar page spin (no buttons) ---- */
            QSpinBox#sbPageSpin {{
                background: {c["spin_bg"]};
                color: {c["spin_fg"]};
                border: 1px solid {c["spin_border"]};
                border-radius: 3px;
                padding: 1px 4px;
                font-size: 11px;
            }}
            QSpinBox#sbPageSpin::up-button, QSpinBox#sbPageSpin::down-button {{
                width: 0; height: 0; border: none;
            }}

            /* ---- Sliders ---- */
            QSlider::groove:horizontal {{
                background: {c["slider_groove"]};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {c["slider_fill"]};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {c["slider_handle"]};
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {c["slider_hnd_hv"]};
            }}

            /* ---- Bottom bar (custom status bar) ---- */
            #bottomBar {{
                background: {c["sb_bg"]};
                border-top: 1px solid {c["sb_border"]};
            }}
            #bottomBar QWidget {{
                background: transparent;
            }}
            QLabel#sbMessage {{
                color: {c["sb_fg"]};
                font-size: 11px;
            }}
            QToolButton#sbNavBtn {{
                color: {c["btn_fg"]};
                background: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 11px;
            }}
            QToolButton#sbNavBtn:hover {{
                background: {c["btn_hover"]};
                border-color: {c["btn_hover_bdr"]};
            }}
            QToolButton#sbZoomBtn {{
                color: {c["btn_fg"]};
                background: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 11px;
            }}
            QToolButton#sbZoomBtn:hover {{
                background: {c["btn_hover"]};
                border-color: {c["btn_hover_bdr"]};
            }}
            QLabel#sbPageLabel {{
                color: {c["sb_fg"]};
                font-size: 11px;
            }}
            QLabel#sbZoomPct {{
                color: {c["sb_fg"]};
                font-size: 11px;
                font-weight: 600;
            }}

            /* ---- Dock widget ---- */
            QDockWidget {{
                color: {c["dock_fg"]};
                font-weight: 600;
            }}
            QDockWidget::title {{
                background: {c["dock_title_bg"]};
                padding: 7px 10px;
                border-bottom: 1px solid {c["rib_border"]};
            }}
            QDockWidget::close-button, QDockWidget::float-button {{
                background: transparent;
                border: none;
                padding: 3px;
                border-radius: 3px;
            }}
            QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
                background: {c["dock_btn_hov"]};
            }}

            /* ---- List widget ---- */
            QListWidget {{
                background: {c["list_bg"]};
                color: {c["list_fg"]};
                border: 1px solid {c["list_border"]};
                border-radius: 5px;
                font-size: 12px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 4px 6px;
                border-radius: 3px;
            }}
            QListWidget::item:selected {{
                background: {c["list_sel"]};
                color: {c["list_sel_fg"]};
            }}
            QListWidget::item:hover {{
                background: {c["btn_hover"]};
            }}

            /* ---- Scrollbars ---- */
            QScrollBar:vertical {{
                background: {c["scroll_bg"]};
                width: 12px;
                margin: 0;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {c["scroll_handle"]};
                min-height: 24px;
                border-radius: 4px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {c["scroll_hnd_hv"]};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                background: {c["scroll_bg"]};
                height: 12px;
                margin: 0;
                border-radius: 6px;
            }}
            QScrollBar::handle:horizontal {{
                background: {c["scroll_handle"]};
                min-width: 24px;
                border-radius: 4px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {c["scroll_hnd_hv"]};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0;
                background: none;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}

            /* ---- Context menus ---- */
            QMenu {{
                background: {c["menu_bg"]};
                color: {c["menu_fg"]};
                border: 1px solid {c["menu_border"]};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 28px 6px 12px;
                border-radius: 4px;
                margin: 1px 4px;
            }}
            QMenu::item:selected {{
                background: {c["menu_sel"]};
                color: {c["menu_sel_fg"]};
            }}
            QMenu::separator {{
                height: 1px;
                background: {c["rib_sep"]};
                margin: 4px 8px;
            }}

            /* ---- Tooltips ---- */
            QToolTip {{
                background: {c["menu_bg"]};
                color: {c["menu_fg"]};
                border: 1px solid {c["menu_border"]};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }}

            /* ---- Dialogs ---- */
            QDialog {{
                background: {c["dialog_bg"]};
                color: {c["dialog_fg"]};
            }}
            QDialog QLabel {{
                color: {c["dialog_fg"]};
            }}
            QDialog QTextEdit, QDialog QLineEdit, QDialog QPlainTextEdit {{
                background: {c["dlg_input_bg"]};
                color: {c["dlg_input_fg"]};
                border: 1px solid {c["dlg_input_bdr"]};
                border-radius: 5px;
                padding: 4px 6px;
                font-size: 12px;
            }}
            QDialog QTextEdit:focus, QDialog QLineEdit:focus, QDialog QPlainTextEdit:focus {{
                border-color: {c["dlg_input_foc"]};
            }}
            QDialog QPushButton {{
                background: {c["dlg_btn_bg"]};
                color: {c["dlg_btn_fg"]};
                border: 1px solid {c["dlg_btn_bdr"]};
                border-radius: 5px;
                padding: 5px 20px;
                font-size: 12px;
            }}
            QDialog QPushButton:hover {{
                background: {c["dlg_btn_hov"]};
                border-color: {c["btn_hover_bdr"]};
            }}
            QDialog QCheckBox, QDialog QRadioButton {{
                color: {c["dialog_fg"]};
                spacing: 6px;
            }}
            QDialog QGroupBox {{
                color: {c["dialog_fg"]};
                border: 1px solid {c["dlg_input_bdr"]};
                border-radius: 5px;
                margin-top: 12px;
                padding-top: 8px;
                font-weight: 600;
            }}
            QDialog QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
            QDialog QComboBox {{
                background: {c["dlg_input_bg"]};
                color: {c["dlg_input_fg"]};
                border: 1px solid {c["dlg_input_bdr"]};
                border-radius: 5px;
                padding: 4px 8px;
            }}
            QDialog QSpinBox {{
                background: {c["dlg_input_bg"]};
                color: {c["dlg_input_fg"]};
                border: 1px solid {c["dlg_input_bdr"]};
                border-radius: 5px;
                padding: 3px 6px;
            }}
            QDialog QSpinBox:focus, QDialog QComboBox:focus {{
                border-color: {c["dlg_input_foc"]};
            }}

            QMessageBox {{
                background: {c["dialog_bg"]};
                color: {c["dialog_fg"]};
            }}
            QMessageBox QLabel {{
                color: {c["dialog_fg"]};
            }}
            QMessageBox QPushButton {{
                background: {c["dlg_btn_bg"]};
                color: {c["dlg_btn_fg"]};
                border: 1px solid {c["dlg_btn_bdr"]};
                border-radius: 5px;
                padding: 5px 20px;
            }}
            QMessageBox QPushButton:hover {{
                background: {c["dlg_btn_hov"]};
                border-color: {c["btn_hover_bdr"]};
            }}
        """

    def _apply_theme(self):
        """Apply QSS stylesheet and update scene background for current mode."""
        t = self._theme()

        # Scene background
        if self._scene:
            self._scene.setBackgroundBrush(QBrush(t["scene_bg"]))

        # View background (visible when no scene is loaded)
        self._view.setBackgroundBrush(QBrush(t["scene_bg"]))

        self.setStyleSheet(self._build_qss())

        # Update existing scene items if a document is loaded
        self._update_scene_theme()

    def _update_scene_theme(self):
        """Update colours of existing scene items (borders, shadows, placeholders, separators)."""
        if not self._scene:
            return

        t = self._theme()
        self._scene.setBackgroundBrush(QBrush(t["scene_bg"]))

        for pn, item in self._page_placeholders.items():
            item.setPen(QPen(t["placeholder_border"]))
            item.setBrush(QBrush(t["placeholder_bg"]))

        for pn, item in self._page_border_items.items():
            item.setPen(QPen(t["page_border"], 1.5))

        for pn, item in self._page_shadow_items.items():
            item.setBrush(QBrush(t["page_shadow"]))

        for item in self._separator_items:
            item.setPen(QPen(t["separator"], 1))

        # Update sticky-note icons in the scene
        if self._scene:
            for item in self._scene.items():
                if isinstance(item, StickyNoteItem):
                    item.update_theme(t["note_bg"], t["note_border"])

    def _set_theme_mode(self, mode):
        """Set the theme to 'system', 'dark', or 'light'."""
        self._theme_mode = mode
        self._resolve_dark_mode()
        self._apply_theme()
        # Update radio-check marks
        self._act_theme_system.setChecked(mode == "system")
        self._act_theme_light.setChecked(mode == "light")
        self._act_theme_dark.setChecked(mode == "dark")
        labels = {"system": "System Default", "dark": "Dark", "light": "Light"}
        self._statusbar.showMessage(f"Theme set to {labels.get(mode, mode)}")

    # -- watermark ----------------------------------------------------------
    def _add_watermark(self):
        """Open watermark dialog and burn watermark into the PDF pages."""
        if not self._doc:
            return
        dlg = WatermarkDialog(self._total_pages, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cfg = dlg.get_config()

        self._push_doc_snapshot("Add Watermark")
        try:
            pf = cfg["page_from"]
            pt = cfg["page_to"]
            pages = list(range(pf, pt + 1)) if pf is not None else list(range(self._total_pages))

            for pn in pages:
                page = self._doc[pn]
                rect = page.rect
                w, h = rect.width, rect.height

                if cfg["type"] == "text":
                    text = cfg["text"]
                    if not text.strip():
                        continue
                    fontsize = cfg["font_size"]
                    opacity = cfg["opacity"]
                    rotation = cfg["rotation"]
                    cr, cg, cb = cfg["color"]

                    # Calculate position
                    pos = cfg["position"]
                    if pos == "Center":
                        cx, cy = w / 2, h / 2
                    elif pos == "Top Left":
                        cx, cy = w * 0.25, h * 0.2
                    elif pos == "Top Right":
                        cx, cy = w * 0.75, h * 0.2
                    elif pos == "Bottom Left":
                        cx, cy = w * 0.25, h * 0.8
                    else:  # Bottom Right
                        cx, cy = w * 0.75, h * 0.8

                    # Use text writer for proper positioning
                    tw = fitz.TextWriter(rect)
                    font = fitz.Font("helv")
                    # Measure text width to center it
                    text_length = font.text_length(text, fontsize=fontsize)
                    x = cx - text_length / 2
                    y = cy + fontsize / 3

                    tw.append((x, y), text, font=font, fontsize=fontsize)
                    tw.write_text(page, color=(cr, cg, cb),
                                  opacity=opacity, morph=(fitz.Point(cx, cy),
                                  fitz.Matrix(1, 0, 0, 1, 0, 0).prerotate(rotation)))

                elif cfg["type"] == "image":
                    img_path = cfg["image_path"]
                    if not img_path or not os.path.isfile(img_path):
                        QMessageBox.warning(self, "Watermark", "No valid image selected.")
                        return
                    opacity = cfg["opacity"]
                    scale = cfg["image_scale"]
                    pos = cfg["position"]

                    # Get image dimensions
                    img_rect_ref = fitz.Rect(0, 0, w * scale, h * scale)
                    # Try to load to get real aspect
                    try:
                        pix_img = fitz.Pixmap(img_path)
                        iw = pix_img.width * scale
                        ih = pix_img.height * scale
                        # Limit to page size
                        if iw > w * 0.9:
                            ratio = (w * 0.9) / iw
                            iw *= ratio
                            ih *= ratio
                        if ih > h * 0.9:
                            ratio = (h * 0.9) / ih
                            iw *= ratio
                            ih *= ratio
                    except Exception:
                        iw, ih = w * 0.5 * scale, h * 0.5 * scale

                    if pos == "Center":
                        ix = (w - iw) / 2
                        iy = (h - ih) / 2
                    elif pos == "Top Left":
                        ix, iy = w * 0.05, h * 0.05
                    elif pos == "Top Right":
                        ix = w - iw - w * 0.05
                        iy = h * 0.05
                    elif pos == "Bottom Left":
                        ix = w * 0.05
                        iy = h - ih - h * 0.05
                    else:  # Bottom Right
                        ix = w - iw - w * 0.05
                        iy = h - ih - h * 0.05

                    img_rect = fitz.Rect(ix, iy, ix + iw, iy + ih)
                    page.insert_image(img_rect, filename=img_path,
                                      overlay=True, keep_proportion=True)
                    # Apply opacity via a stamp annotation if < 1
                    if opacity < 0.99:
                        # Re-render uses the base opacity built into the image
                        pass  # PyMuPDF doesn't directly support image opacity on insert

            # Refresh display
            self._tile_generation += 1
            self._remove_all_tile_items()
            self._tile_cache.clear()
            self._current_tile_ss = 0.0
            self._ensure_visible_tiles()

            self._statusbar.showMessage(
                f"Watermark added to {len(pages)} page(s). Save to persist."
            )
        except Exception as e:
            QMessageBox.critical(self, "Watermark Error", f"Failed to add watermark:\n{e}")

    def _remove_watermark(self):
        """Attempt to remove watermark by cleaning the last-drawn content.

        Since watermarks are burned into the page content, true removal
        is limited — this uses page.clean_contents() and offers to undo
        via reload if the user saved before adding the watermark.
        """
        if not self._doc:
            return
        reply = QMessageBox.question(
            self, "Remove Watermark",
            "Watermark removal works best if you haven't saved since adding it.\n\n"
            "This will attempt to reload the PDF from disk, discarding all\n"
            "unsaved changes (including the watermark).\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        if self._file_path and os.path.isfile(self._file_path):
            self._push_doc_snapshot("Remove Watermark")
            self._load_pdf(self._file_path)
            self._statusbar.showMessage("Reloaded PDF from disk (watermark removed if unsaved).")
        else:
            QMessageBox.warning(self, "Remove Watermark",
                                "No saved file to reload from.")

    # -- page numbers -------------------------------------------------------
    def _add_page_numbers(self):
        """Add page numbers to every page of the PDF."""
        if not self._doc:
            return
        dlg = PageNumberDialog(self._total_pages, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cfg = dlg.get_config()

        self._push_doc_snapshot("Add Page Numbers")
        try:
            pf = cfg["page_from"]
            pt = cfg["page_to"]
            pages = list(range(pf, pt + 1)) if pf is not None else list(range(self._total_pages))
            fmt = cfg["format"]
            start = cfg["start_num"]
            fs = cfg["font_size"]
            margin = cfg["margin"]
            pos = cfg["position"]

            font = fitz.Font("helv")
            for i, pn in enumerate(pages):
                if cfg["skip_first"] and i == 0:
                    continue
                page = self._doc[pn]
                w, h = page.rect.width, page.rect.height
                num = start + i
                text = fmt.replace("{n}", str(num)).replace("{total}", str(len(pages) + start - 1))
                text_len = font.text_length(text, fontsize=fs)

                if "Bottom" in pos:
                    y = h - margin
                else:
                    y = margin + fs

                if "Center" in pos:
                    x = (w - text_len) / 2
                elif "Right" in pos:
                    x = w - margin - text_len
                else:
                    x = margin

                tw = fitz.TextWriter(page.rect)
                tw.append((x, y), text, font=font, fontsize=fs)
                tw.write_text(page, color=(0.3, 0.3, 0.3))

            self._tile_generation += 1
            self._remove_all_tile_items()
            self._tile_cache.clear()
            self._current_tile_ss = 0.0
            self._ensure_visible_tiles()
            self._statusbar.showMessage(f"Page numbers added to {len(pages)} page(s). Save to persist.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add page numbers:\n{e}")

    def _remove_page_numbers(self):
        """Remove page numbers by reloading from disk."""
        if not self._doc:
            return
        reply = QMessageBox.question(
            self, "Remove Page Numbers",
            "Page numbers are burned into the PDF content.\n"
            "This will reload the file from disk, discarding unsaved changes.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes and self._file_path and os.path.isfile(self._file_path):
            self._push_doc_snapshot("Remove Page Numbers")
            self._load_pdf(self._file_path)
            self._statusbar.showMessage("Reloaded PDF from disk.")

    # -- header / footer ----------------------------------------------------
    def _add_header_footer(self):
        """Add header and/or footer text to PDF pages."""
        if not self._doc:
            return
        dlg = HeaderFooterDialog(self._total_pages, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cfg = dlg.get_config()

        # Check if anything was entered
        texts = [cfg["header_left"], cfg["header_center"], cfg["header_right"],
                 cfg["footer_left"], cfg["footer_center"], cfg["footer_right"]]
        if not any(t.strip() for t in texts):
            QMessageBox.information(self, "Header/Footer", "No text entered.")
            return

        self._push_doc_snapshot("Add Header/Footer")
        try:
            from datetime import date
            today = date.today().strftime("%Y-%m-%d")
            pf = cfg["page_from"]
            pt = cfg["page_to"]
            pages = list(range(pf, pt + 1)) if pf is not None else list(range(self._total_pages))
            fs = cfg["font_size"]
            margin = cfg["margin"]

            font = fitz.Font("helv")
            for i, pn in enumerate(pages):
                if cfg["skip_first"] and i == 0:
                    continue
                page = self._doc[pn]
                w, h = page.rect.width, page.rect.height
                page_num = pn + 1
                total = self._total_pages

                def _sub(txt):
                    return txt.replace("{page}", str(page_num)) \
                              .replace("{total}", str(total)) \
                              .replace("{date}", today)

                # Header (three slots)
                header_y = margin + fs
                for txt, align in [(cfg["header_left"], "left"),
                                   (cfg["header_center"], "center"),
                                   (cfg["header_right"], "right")]:
                    txt = _sub(txt)
                    if not txt.strip():
                        continue
                    tl = font.text_length(txt, fontsize=fs)
                    if align == "left":
                        x = margin
                    elif align == "center":
                        x = (w - tl) / 2
                    else:
                        x = w - margin - tl
                    tw = fitz.TextWriter(page.rect)
                    tw.append((x, header_y), txt, font=font, fontsize=fs)
                    tw.write_text(page, color=(0.3, 0.3, 0.3))

                # Footer (three slots)
                footer_y = h - margin
                for txt, align in [(cfg["footer_left"], "left"),
                                   (cfg["footer_center"], "center"),
                                   (cfg["footer_right"], "right")]:
                    txt = _sub(txt)
                    if not txt.strip():
                        continue
                    tl = font.text_length(txt, fontsize=fs)
                    if align == "left":
                        x = margin
                    elif align == "center":
                        x = (w - tl) / 2
                    else:
                        x = w - margin - tl
                    tw = fitz.TextWriter(page.rect)
                    tw.append((x, footer_y), txt, font=font, fontsize=fs)
                    tw.write_text(page, color=(0.3, 0.3, 0.3))

            self._tile_generation += 1
            self._remove_all_tile_items()
            self._tile_cache.clear()
            self._current_tile_ss = 0.0
            self._ensure_visible_tiles()
            self._statusbar.showMessage(f"Header/footer added to {len(pages)} page(s). Save to persist.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add header/footer:\n{e}")

    def _remove_header_footer(self):
        """Remove header/footer by reloading from disk."""
        if not self._doc:
            return
        reply = QMessageBox.question(
            self, "Remove Header/Footer",
            "Headers/footers are burned into the PDF content.\n"
            "This will reload the file from disk, discarding unsaved changes.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes and self._file_path and os.path.isfile(self._file_path):
            self._push_doc_snapshot("Remove Header/Footer")
            self._load_pdf(self._file_path)
            self._statusbar.showMessage("Reloaded PDF from disk.")

    # -- stamps -------------------------------------------------------------
    def _add_stamp(self):
        """Open stamp dialog then place the stamp on the current page."""
        if not self._doc:
            return
        dlg = StampDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cfg = dlg.get_config()

        self._push_doc_snapshot("Add Stamp")
        try:
            page_num = self._current_page
            page = self._doc[page_num]
            w, h = page.rect.width, page.rect.height

            if cfg["type"] == "preset":
                idx = cfg["preset_index"]
                if idx < 0 or idx >= len(_STAMP_PRESETS):
                    return
                preset = _STAMP_PRESETS[idx]
                text = preset["text"]
                color = preset["color"]
                border_c = preset["border"]
                fontsize = cfg["font_size"]
                rotation = cfg["rotation"]

                font = fitz.Font("helv")
                text_len = font.text_length(text, fontsize=fontsize)
                cx, cy = w / 2, h / 2
                x = cx - text_len / 2
                y = cy + fontsize / 3

                # Draw border rectangle
                rect_pad = 8
                stamp_rect = fitz.Rect(
                    x - rect_pad, cy - fontsize * 0.7 - rect_pad,
                    x + text_len + rect_pad, cy + fontsize * 0.4 + rect_pad
                )
                shape = page.new_shape()
                shape.draw_rect(stamp_rect)
                shape.finish(color=border_c, width=2.5,
                             morph=(fitz.Point(cx, cy),
                                    fitz.Matrix(1, 0, 0, 1, 0, 0).prerotate(rotation)))
                shape.commit(overlay=True)

                # Draw text
                tw = fitz.TextWriter(page.rect)
                tw.append((x, y), text, font=font, fontsize=fontsize)
                tw.write_text(page, color=color, opacity=0.85,
                              morph=(fitz.Point(cx, cy),
                                     fitz.Matrix(1, 0, 0, 1, 0, 0).prerotate(rotation)))

            elif cfg["type"] == "custom":
                img_path = cfg["custom_file"]
                if not img_path or not os.path.isfile(img_path):
                    QMessageBox.warning(self, "Stamp", "No custom stamp image selected.")
                    return
                scale = cfg["custom_scale"]
                try:
                    pix_img = fitz.Pixmap(img_path)
                    iw = pix_img.width * scale
                    ih = pix_img.height * scale
                except Exception:
                    iw, ih = 150 * scale, 60 * scale
                ix = (w - iw) / 2
                iy = (h - ih) / 2
                img_rect = fitz.Rect(ix, iy, ix + iw, iy + ih)
                page.insert_image(img_rect, filename=img_path,
                                  overlay=True, keep_proportion=True)

            # Refresh tiles
            self._tile_generation += 1
            self._remove_all_tile_items()
            self._tile_cache.clear()
            self._current_tile_ss = 0.0
            self._ensure_visible_tiles()
            self._statusbar.showMessage(f"Stamp placed on page {page_num + 1}. Save to persist.")
        except Exception as e:
            QMessageBox.critical(self, "Stamp Error", f"Failed to add stamp:\n{e}")

    # -- signature ----------------------------------------------------------
    def _add_signature(self):
        """Open signature dialog then place signature on the current page."""
        if not self._doc:
            return
        dlg = SignatureDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cfg = dlg.get_config()

        sig_path = cfg["signature_file"]
        if not sig_path or not os.path.isfile(sig_path):
            QMessageBox.warning(self, "Signature", "No signature image selected.")
            return

        self._push_doc_snapshot("Add Signature")
        try:
            scale = cfg["scale"]
            page_num = self._current_page
            page = self._doc[page_num]
            w, h = page.rect.width, page.rect.height

            try:
                pix_img = fitz.Pixmap(sig_path)
                iw = pix_img.width * scale * 0.5  # signatures usually rendered at 0.5x
                ih = pix_img.height * scale * 0.5
            except Exception:
                iw, ih = 200 * scale, 80 * scale

            # Place at bottom-right area by default
            ix = w * 0.6
            iy = h * 0.8
            img_rect = fitz.Rect(ix, iy, ix + iw, iy + ih)
            page.insert_image(img_rect, filename=sig_path,
                              overlay=True, keep_proportion=True)

            # Refresh tiles
            self._tile_generation += 1
            self._remove_all_tile_items()
            self._tile_cache.clear()
            self._current_tile_ss = 0.0
            self._ensure_visible_tiles()
            self._statusbar.showMessage(f"Signature placed on page {page_num + 1}. Save to persist.")
        except Exception as e:
            QMessageBox.critical(self, "Signature Error", f"Failed to add signature:\n{e}")

    # -- links --------------------------------------------------------------
    def _add_link(self):
        """Show link dialog, then let user drag-draw a link rect on the page."""
        if not self._doc:
            return
        total = len(self._doc)
        dlg = LinkDialog(total, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cfg = dlg.get_config()

        if cfg["type"] == "url" and not cfg["url"]:
            QMessageBox.warning(self, "Link", "Please enter a URL.")
            return

        # Store config and switch to a temporary link-draw mode
        self._pending_link_cfg = cfg
        self._link_drawing = True
        self._link_start = None
        self._link_rect_item = None
        self._statusbar.showMessage(
            "Click and drag on the page to define the link area. Press Esc to cancel."
        )
        # Temporarily disable ScrollHandDrag so CrossCursor is visible
        self._view.setDragMode(QGraphicsView.NoDrag)
        self._view.viewport().setCursor(Qt.CrossCursor)
        # Install event filter on the viewport for drag-rect
        self._view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        """Handle link rectangle drawing on the graphics view viewport
        and Delete key in the annotation list."""
        from PyQt5.QtCore import QEvent

        # Delete key in annotation list
        if obj is self._ann_list and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                list_item = self._ann_list.currentItem()
                if list_item is not None:
                    scene_item = list_item.data(Qt.UserRole)
                    if scene_item is not None and scene_item.scene() is not None:
                        self._delete_scene_item(scene_item)
                return True

        if not getattr(self, "_link_drawing", False):
            return super().eventFilter(obj, event)

        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._link_start = self._view.mapToScene(event.pos())
            pen = QPen(QColor(0, 0, 200), 1.5, Qt.DashLine)
            self._link_rect_item = self._view.scene().addRect(
                QRectF(self._link_start, self._link_start), pen,
                QBrush(QColor(0, 0, 200, 30))
            )
            return True
        elif event.type() == QEvent.MouseMove and self._link_start is not None:
            pos = self._view.mapToScene(event.pos())
            self._link_rect_item.setRect(QRectF(self._link_start, pos).normalized())
            return True
        elif event.type() == QEvent.MouseButtonRelease and self._link_start is not None:
            pos = self._view.mapToScene(event.pos())
            scene_rect = QRectF(self._link_start, pos).normalized()
            # Cleanup visual rect
            if self._link_rect_item:
                self._view.scene().removeItem(self._link_rect_item)
                self._link_rect_item = None
            self._link_drawing = False
            self._link_start = None
            self._view.viewport().removeEventFilter(self)
            self._view.set_tool(self._view._tool)  # restore cursor & drag mode
            self._finish_add_link(scene_rect)
            return True
        elif event.type() == QEvent.KeyPress:
            from PyQt5.QtCore import Qt as QtK
            if event.key() == QtK.Key_Escape:
                if self._link_rect_item:
                    self._view.scene().removeItem(self._link_rect_item)
                    self._link_rect_item = None
                self._link_drawing = False
                self._link_start = None
                self._view.viewport().removeEventFilter(self)
                self._view.set_tool(self._view._tool)  # restore cursor & drag mode
                self._statusbar.showMessage("Link cancelled.")
                return True
        return super().eventFilter(obj, event)

    def _finish_add_link(self, scene_rect):
        """Create the actual PDF link annotation from the drawn scene rect."""
        cfg = getattr(self, "_pending_link_cfg", None)
        if not cfg or not self._doc:
            return
        self._push_doc_snapshot("Add Link")
        try:
            # Determine which page the rect is on
            mid_y = scene_rect.center().y()
            page_num = None
            for i, off in enumerate(self._page_offsets):
                page_bottom = off + self._page_heights[i]
                if mid_y <= page_bottom:
                    page_num = i
                    break
            if page_num is None:
                page_num = len(self._doc) - 1

            page = self._doc[page_num]
            offset = self._page_offsets[page_num]
            scale = self._dpi / 72.0

            # Convert scene coords to PDF coords
            x0 = scene_rect.left() / scale
            y0 = (scene_rect.top() - offset) / scale
            x1 = scene_rect.right() / scale
            y1 = (scene_rect.bottom() - offset) / scale
            pdf_rect = fitz.Rect(x0, y0, x1, y1)

            if pdf_rect.width < 5 or pdf_rect.height < 5:
                self._statusbar.showMessage("Link area too small, cancelled.")
                return

            bc = cfg["border_color"]
            link_dict = {"kind": fitz.LINK_URI, "from": pdf_rect}

            if cfg["type"] == "url":
                link_dict["kind"] = fitz.LINK_URI
                link_dict["uri"] = cfg["url"]
            else:
                link_dict["kind"] = fitz.LINK_GOTO
                link_dict["page"] = cfg["target_page"]
                link_dict["to"] = fitz.Point(0, 0)

            page.insert_link(link_dict)

            # Add a visible border as a Square annotation (removable, not burned in)
            border_annot = page.add_rect_annot(pdf_rect)
            border_annot.set_border(width=0.8, dashes=[3, 2])
            border_annot.set_colors(stroke=bc)
            border_annot.set_opacity(0.7)
            border_annot.set_info(title="link_border")
            border_annot.update()

            # Refresh
            self._tile_generation += 1
            self._remove_all_tile_items()
            self._tile_cache.clear()
            self._current_tile_ss = 0.0
            self._ensure_visible_tiles()
            self._statusbar.showMessage(
                f"Link added on page {page_num + 1}. Save to persist."
            )
        except Exception as e:
            QMessageBox.critical(self, "Link Error", f"Failed to add link:\n{e}")
        finally:
            self._pending_link_cfg = None

    def _remove_links_on_page(self):
        """Remove all link annotations from the current page."""
        if not self._doc:
            return
        page = self._doc[self._current_page]
        links = list(page.get_links())
        if not links:
            QMessageBox.information(self, "Links", "No links found on this page.")
            return
        reply = QMessageBox.question(
            self, "Remove Links",
            f"Remove all {len(links)} link(s) from page {self._current_page + 1}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._push_doc_snapshot("Remove Links")
        for lnk in links:
            page.delete_link(lnk)
        # Also remove link border annotations (Square annots with title "link_border")
        annots_to_remove = []
        for annot in page.annots():
            if annot.type[0] == fitz.PDF_ANNOT_SQUARE and annot.info.get("title") == "link_border":
                annots_to_remove.append(annot)
        for annot in annots_to_remove:
            page.delete_annot(annot)
        # Refresh
        self._tile_generation += 1
        self._remove_all_tile_items()
        self._tile_cache.clear()
        self._current_tile_ss = 0.0
        self._ensure_visible_tiles()
        self._statusbar.showMessage(
            f"Removed {len(links)} link(s) from page {self._current_page + 1}."
        )

    # -- edit mode ----------------------------------------------------------
    def _enter_edit_mode(self):
        """Enter edit mode (called when switching to the Edit tab)."""
        if not self._doc:
            return
        if self._act_edit_mode.isChecked():
            return  # already in edit mode
        self._act_edit_mode.setChecked(True)
        self._view.enter_edit_mode(
            self._doc, self._page_offsets, self._page_heights, self._dpi
        )
        for a in self._edit_tool_actions:
            a.setEnabled(True)
        self._set_tool(PDFGraphicsView.TOOL_EDIT_TEXT)
        self._statusbar.showMessage(
            "Edit Mode ON — Click text blocks to edit in-place. "
            "Right-click → Delete/Restore."
        )

    def _exit_edit_mode(self):
        """Exit edit mode (called when switching away from the Edit tab)."""
        if not self._act_edit_mode.isChecked():
            return  # not in edit mode
        self._act_edit_mode.setChecked(False)
        self._auto_apply_and_exit()

    def _on_ribbon_tab_changed(self, index):
        """Handle ribbon tab switches — auto-enter/exit edit mode."""
        # Edit tab is at index 2 (Home=0, Comment=1, Edit=2, View=3)
        if index == 2:
            self._enter_edit_mode()
        else:
            self._exit_edit_mode()

    def _delete_selected_text_block(self):
        """Mark selected edit-text blocks as deleted."""
        if not self._view._edit_mode:
            return
        scene = self._view.scene()
        if not scene:
            return
        deleted = 0
        for item in scene.selectedItems():
            if isinstance(item, EditableTextBlockItem):
                item.mark_deleted()
                deleted += 1
        if deleted:
            self._statusbar.showMessage(f"Marked {deleted} text block(s) for deletion")
        else:
            self._statusbar.showMessage("Select text blocks first (click them in Edit Mode)")

    def _auto_apply_and_exit(self):
        """Automatically apply all text edits and images, then exit edit mode."""
        if not self._doc or not self._view._edit_mode:
            return

        # Stop any in-progress editing
        for item in self._view._edit_text_blocks:
            item._stop_editing()

        edits = self._view.get_text_edits()
        image_items = [item for item in self._view.scene().items()
                       if item.data(0) == "edit_image"]

        if not edits and not image_items:
            # Nothing changed — just exit
            self._view.exit_edit_mode()
            for a in self._edit_tool_actions:
                a.setEnabled(False)
            self._set_tool(PDFGraphicsView.TOOL_NONE)
            self._statusbar.showMessage("Edit Mode OFF — no changes made.")
            return

        self._push_doc_snapshot("Apply Text Edits")
        try:
            for block in edits:
                page = self._doc[block.page_num()]
                pdf_rect = block.pdf_rect()

                if block.is_deleted():
                    page.add_redact_annot(pdf_rect)
                    page.apply_redactions()
                elif block.is_modified():
                    page.add_redact_annot(pdf_rect)
                    page.apply_redactions()

                    new_text = block.current_text()
                    font_size = block.font_size_pts()
                    tc = block.text_color()
                    color = (tc[0], tc[1], tc[2])

                    font_name = "helv"
                    raw_font = block.font_name().lower()
                    if "times" in raw_font or "serif" in raw_font:
                        font_name = "tiro"
                    elif "courier" in raw_font or "mono" in raw_font:
                        font_name = "cobo"

                    rc = page.insert_textbox(
                        pdf_rect, new_text,
                        fontsize=font_size,
                        fontname=font_name,
                        color=color,
                        align=fitz.TEXT_ALIGN_LEFT,
                    )
                    if rc < 0:
                        page.insert_textbox(
                            pdf_rect, new_text,
                            fontsize=max(6, font_size - 2),
                            fontname=font_name,
                            color=color,
                            align=fitz.TEXT_ALIGN_LEFT,
                        )

            # Apply images
            for item in image_items:
                if not isinstance(item, QGraphicsPixmapItem):
                    continue
                img_path = item.data(1)
                if not img_path or not os.path.isfile(img_path):
                    continue
                pos = item.pos()
                page_num = self._view.page_at_y(pos.y())
                y_off = self._page_offsets[page_num]
                page = self._doc[page_num]
                scale = self._dpi / 72.0
                px = pos.x() / scale
                py = (pos.y() - y_off) / scale
                pw = item.pixmap().width() / scale
                ph = item.pixmap().height() / scale
                img_rect = fitz.Rect(px, py, px + pw, py + ph)
                page.insert_image(img_rect, filename=img_path)

            # Exit edit mode
            self._view.exit_edit_mode()
            for a in self._edit_tool_actions:
                a.setEnabled(False)

            # Remove image overlay items
            scene = self._view.scene()
            for item in image_items:
                if item.scene() is not None:
                    scene.removeItem(item)

            # Re-render
            self._tile_generation += 1
            self._remove_all_tile_items()
            self._tile_cache.clear()
            self._current_tile_ss = 0.0
            self._ensure_visible_tiles()
            self._load_all_word_data()

            self._set_tool(PDFGraphicsView.TOOL_NONE)
            self._statusbar.showMessage(
                f"Applied {len(edits)} text edit(s) and {len(image_items)} image(s). "
                "Save to persist changes."
            )
        except Exception as e:
            QMessageBox.critical(self, "Edit Error", f"Failed to apply edits:\n{e}")

    def _set_author_name(self):
        """Prompt the user to set their author name for annotations."""
        name, ok = QInputDialog.getText(
            self, "Set Author Name",
            "Enter your name (shown on notes in other PDF viewers):",
            text=self._author_name,
        )
        if ok:
            self._author_name = name.strip()
            if self._author_name:
                self._statusbar.showMessage(f"Author name set to: {self._author_name}")
            else:
                self._statusbar.showMessage("Author name cleared")

    def _on_scroll(self):
        """Update current page based on viewport scroll position."""
        if self._doc is None:
            return
        page = self._view.current_visible_page()
        if page != self._current_page:
            self._current_page = page
            self._updating_spinner = True
            self._page_spin.setValue(page + 1)
            self._updating_spinner = False
            self._update_ui_state()
        self._ensure_visible_tiles()

    def _create_actions(self):
        self._act_open = QAction("📂 Open PDF", self)
        self._act_open.setShortcut(QKeySequence.Open)
        self._act_open.triggered.connect(self._open_file)

        self._act_save = QAction("💾 Save", self)
        self._act_save.setShortcut(QKeySequence.Save)
        self._act_save.triggered.connect(self._save_file)

        self._act_save_as = QAction("💾 Save As…", self)
        self._act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._act_save_as.triggered.connect(self._save_file_as)

        # -- undo / redo ----
        self._act_undo = QAction("↩ Undo", self)
        self._act_undo.setShortcut(QKeySequence.Undo)
        self._act_undo.triggered.connect(self._undo)
        self._act_undo.setEnabled(False)

        self._act_redo = QAction("↪ Redo", self)
        self._act_redo.setShortcut(QKeySequence.Redo)
        self._act_redo.triggered.connect(self._redo)
        self._act_redo.setEnabled(False)

        # Register undo/redo at the window level so shortcuts work on every tab
        self.addAction(self._act_undo)
        self.addAction(self._act_redo)

        # -- navigation ----
        self._act_prev = QAction("◀ Prev", self)
        self._act_prev.setShortcut(QKeySequence("Left"))
        self._act_prev.triggered.connect(self._prev_page)

        self._act_next = QAction("Next ▶", self)
        self._act_next.setShortcut(QKeySequence("Right"))
        self._act_next.triggered.connect(self._next_page)

        self._act_zoom_in = QAction("🔍+ Zoom In", self)
        self._act_zoom_in.setShortcut(QKeySequence.ZoomIn)
        self._act_zoom_in.triggered.connect(self._view.zoom_in)

        self._act_zoom_out = QAction("🔍− Zoom Out", self)
        self._act_zoom_out.setShortcut(QKeySequence.ZoomOut)
        self._act_zoom_out.triggered.connect(self._view.zoom_out)

        self._act_zoom_reset = QAction("🔍 1:1", self)
        self._act_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        self._act_zoom_reset.triggered.connect(self._view.zoom_reset)

        # -- tool actions (checkable) ----
        self._act_select = QAction("🖐 Hand", self)
        self._act_select.setCheckable(True)
        self._act_select.setChecked(True)
        self._act_select.triggered.connect(lambda: self._set_tool(PDFGraphicsView.TOOL_NONE))

        self._act_select_text = QAction("🔤 Select Text", self)
        self._act_select_text.setCheckable(True)
        self._act_select_text.triggered.connect(lambda: self._set_tool(PDFGraphicsView.TOOL_SELECT_TEXT))

        self._act_highlight = QAction("🖍 Highlight", self)
        self._act_highlight.setCheckable(True)
        self._act_highlight.triggered.connect(lambda: self._set_tool(PDFGraphicsView.TOOL_HIGHLIGHT))

        self._act_pen = QAction("✏ Pen", self)
        self._act_pen.setCheckable(True)
        self._act_pen.triggered.connect(lambda: self._set_tool(PDFGraphicsView.TOOL_PEN))

        self._act_note = QAction("📌 Note", self)
        self._act_note.setCheckable(True)
        self._act_note.triggered.connect(lambda: self._set_tool(PDFGraphicsView.TOOL_NOTE))

        self._act_text = QAction("🅰 Text", self)
        self._act_text.setCheckable(True)
        self._act_text.triggered.connect(lambda: self._set_tool(PDFGraphicsView.TOOL_TEXT))

        self._act_rect = QAction("▭ Rectangle", self)
        self._act_rect.setCheckable(True)
        self._act_rect.triggered.connect(lambda: self._set_tool(PDFGraphicsView.TOOL_RECT))

        self._act_eraser = QAction("🧹 Eraser", self)
        self._act_eraser.setCheckable(True)
        self._act_eraser.triggered.connect(lambda: self._set_tool(PDFGraphicsView.TOOL_ERASER))

        # -- highlight selected text ----
        self._act_highlight_sel = QAction("🖍 Highlight Selection", self)
        self._act_highlight_sel.setShortcut(QKeySequence("Ctrl+H"))
        self._act_highlight_sel.triggered.connect(self._highlight_selection)
        self._act_highlight_sel.setEnabled(False)

        # -- copy selected text ----
        self._act_pen_color = QAction("🎨 Pen Color", self)
        self._act_pen_color.triggered.connect(self._pick_pen_color)

        self._act_hl_color = QAction("🎨 Highlight Color", self)
        self._act_hl_color.triggered.connect(self._pick_highlight_color)

        self._tool_actions = [
            self._act_select, self._act_select_text, self._act_highlight,
            self._act_pen, self._act_note, self._act_text, self._act_rect,
            self._act_eraser
        ]

        # -- edit mode (internal state, no button — auto-activated by Edit tab) ----
        self._act_edit_mode = QAction("⚡ Edit Mode", self)
        self._act_edit_mode.setCheckable(True)

        self._act_add_image = QAction("🖼 Add Image", self)
        self._act_add_image.setCheckable(True)
        self._act_add_image.triggered.connect(self._toggle_add_image)

        self._act_delete_text = QAction("🗑 Delete Selected", self)
        self._act_delete_text.triggered.connect(self._delete_selected_text_block)

        self._act_add_watermark = QAction("💧 Watermark", self)
        self._act_add_watermark.triggered.connect(self._add_watermark)

        self._act_remove_watermark = QAction("💧✕ Remove WM", self)
        self._act_remove_watermark.triggered.connect(self._remove_watermark)

        self._act_page_numbers = QAction("#️⃣ Page Numbers", self)
        self._act_page_numbers.triggered.connect(self._add_page_numbers)

        self._act_remove_page_numbers = QAction("#️⃣✕ Remove Pg#", self)
        self._act_remove_page_numbers.triggered.connect(self._remove_page_numbers)

        self._act_header_footer = QAction("📄 Header/Footer", self)
        self._act_header_footer.triggered.connect(self._add_header_footer)

        self._act_remove_hf = QAction("📄✕ Remove H/F", self)
        self._act_remove_hf.triggered.connect(self._remove_header_footer)

        self._act_add_stamp = QAction("🔖 Stamp", self)
        self._act_add_stamp.triggered.connect(self._add_stamp)

        self._act_add_signature = QAction("✍ Signature", self)
        self._act_add_signature.triggered.connect(self._add_signature)

        self._act_add_link = QAction("🔗 Add Link", self)
        self._act_add_link.triggered.connect(self._add_link)
        self._act_remove_links = QAction("🔗✕ Remove Links", self)
        self._act_remove_links.triggered.connect(self._remove_links_on_page)

        self._edit_tool_actions = [
            self._act_add_image,
            self._act_delete_text,
            self._act_add_watermark, self._act_remove_watermark,
            self._act_page_numbers, self._act_remove_page_numbers,
            self._act_header_footer, self._act_remove_hf,
            self._act_add_stamp, self._act_add_signature,
            self._act_add_link, self._act_remove_links,
        ]

        # -- author name ----
        self._act_set_author = QAction("👤 Author Name", self)
        self._act_set_author.triggered.connect(self._set_author_name)

        # -- theme mode (System Default / Light / Dark) ----
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)

        self._act_theme_system = QAction("🖥 System Default", self)
        self._act_theme_system.setCheckable(True)
        self._act_theme_system.setChecked(True)
        self._act_theme_system.triggered.connect(lambda: self._set_theme_mode("system"))
        theme_group.addAction(self._act_theme_system)

        self._act_theme_light = QAction("☀ Light", self)
        self._act_theme_light.setCheckable(True)
        self._act_theme_light.triggered.connect(lambda: self._set_theme_mode("light"))
        theme_group.addAction(self._act_theme_light)

        self._act_theme_dark = QAction("🌙 Dark", self)
        self._act_theme_dark.setCheckable(True)
        self._act_theme_dark.setShortcut(QKeySequence("Ctrl+D"))
        self._act_theme_dark.triggered.connect(lambda: self._set_theme_mode("dark"))
        theme_group.addAction(self._act_theme_dark)

        # -- annotations panel toggle ----
        self._act_toggle_annotations = QAction("📋 Annotations", self)
        self._act_toggle_annotations.setCheckable(True)
        self._act_toggle_annotations.setChecked(True)

    # -- helpers for ribbon groups ------------------------------------------
    @staticmethod
    def _ribbon_make_btn(action):
        """Create a QToolButton for a ribbon action."""
        btn = QToolButton()
        btn.setDefaultAction(action)
        btn.setObjectName("ribbonBtn")
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        return btn

    @staticmethod
    def _ribbon_make_group(title, widgets):
        """Create a labeled ribbon section with a bottom title."""
        group = QWidget()
        group.setObjectName("ribbonGroup")
        lay = QVBoxLayout(group)
        lay.setContentsMargins(8, 2, 8, 0)
        lay.setSpacing(1)

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(3)
        for w in widgets:
            if isinstance(w, QAction):
                btn = QToolButton()
                btn.setDefaultAction(w)
                btn.setObjectName("ribbonBtn")
                btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
                h.addWidget(btn)
            else:
                h.addWidget(w)
        lay.addWidget(row, 1)

        lbl = QLabel(title)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setObjectName("ribbonGroupLabel")
        lbl.setFixedHeight(14)
        lay.addWidget(lbl)
        return group

    @staticmethod
    def _ribbon_make_sep():
        """Create a vertical separator for the ribbon."""
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setObjectName("ribbonSep")
        sep.setFixedWidth(1)
        return sep

    @staticmethod
    def _ribbon_make_page(groups):
        """Create a ribbon page from a list of groups with separators.
        Wrapped in a QScrollArea so it adapts to narrow windows."""
        inner = QWidget()
        inner.setObjectName("ribbonPage")
        h = QHBoxLayout(inner)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(0)
        for i, g in enumerate(groups):
            h.addWidget(g)
            if i < len(groups) - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.VLine)
                sep.setObjectName("ribbonSep")
                sep.setFixedWidth(1)
                h.addWidget(sep)
        h.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("ribbonScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return scroll

    def _create_ribbon(self):
        """Build PDFGear-style ribbon with tabbed section panels."""
        mg = self._ribbon_make_group
        mp = self._ribbon_make_page

        # ── HOME TAB ──────────────────────────────────────────────────────
        self._recent_menu = QMenu("Recent Files", self)
        recent_btn = QPushButton("🕐 Recent ▾")
        recent_btn.setFlat(True)
        recent_btn.setObjectName("recentBtn")
        recent_btn.setMenu(self._recent_menu)

        home_file = mg("File", [self._act_open, recent_btn,
                                self._act_save, self._act_save_as])
        home_undo = mg("History", [self._act_undo, self._act_redo])

        # Zoom controls (slider + percentage live in status bar)
        home_zoom = mg("Zoom", [self._act_zoom_out, self._act_zoom_reset,
                                self._act_zoom_in])

        home_page = mp([home_file, home_undo, home_zoom])

        # ── COMMENT TAB ───────────────────────────────────────────────────
        comment_tools = mg("Tools", list(self._tool_actions))
        comment_sel = mg("Selection", [self._act_highlight_sel])
        comment_colors = mg("Colors", [self._act_pen_color, self._act_hl_color])

        self._pen_width_spin = QSpinBox()
        self._pen_width_spin.setRange(1, 20)
        self._pen_width_spin.setValue(3)
        self._pen_width_spin.setPrefix("Width: ")
        self._pen_width_spin.valueChanged.connect(self._view.set_pen_width)

        comment_width = mg("Pen Width", [self._pen_width_spin])

        comment_page = mp([comment_tools, comment_sel, comment_colors,
                           comment_width])

        # ── EDIT TAB ──────────────────────────────────────────────────────
        edit_content = mg("Content", [self._act_add_image,
                                      self._act_delete_text])
        edit_wm = mg("Watermark", [self._act_add_watermark,
                                   self._act_remove_watermark])
        edit_pn = mg("Page Numbers", [self._act_page_numbers,
                                      self._act_remove_page_numbers])
        edit_hf = mg("Header / Footer", [self._act_header_footer,
                                         self._act_remove_hf])
        edit_stamps = mg("Stamps", [self._act_add_stamp,
                                    self._act_add_signature])
        edit_links = mg("Links", [self._act_add_link,
                                  self._act_remove_links])

        edit_page = mp([edit_content, edit_wm, edit_pn,
                        edit_hf, edit_stamps, edit_links])

        # Initially disable edit tools until edit mode is on
        for a in self._edit_tool_actions:
            a.setEnabled(False)

        # ── VIEW TAB ─────────────────────────────────────────────────────
        self._theme_menu = QMenu("Theme", self)
        self._theme_menu.addAction(self._act_theme_system)
        self._theme_menu.addAction(self._act_theme_light)
        self._theme_menu.addAction(self._act_theme_dark)
        theme_btn = QPushButton("🎨 Theme ▾")
        theme_btn.setFlat(True)
        theme_btn.setObjectName("themeBtn")
        theme_btn.setMenu(self._theme_menu)

        view_theme = mg("Theme", [theme_btn])
        view_info = mg("Info", [self._act_set_author])
        view_panels = mg("Panels", [self._act_toggle_annotations])

        view_page = mp([view_theme, view_info, view_panels])

        # ── Register tabs ─────────────────────────────────────────────────
        for label in ("Home", "Comment", "Edit", "View"):
            self._ribbon_tabbar.addTab(label)
        for page in (home_page, comment_page, edit_page, view_page):
            self._ribbon_stack.addWidget(page)

    def _create_statusbar(self):
        # Replace the default QStatusBar with a custom bottom bar
        # to avoid overlapping between nav, message, and zoom sections.
        sb_container = QWidget()
        sb_container.setObjectName("bottomBar")
        sb_container.setFixedHeight(30)
        sb_lay = QHBoxLayout(sb_container)
        sb_lay.setContentsMargins(6, 0, 6, 0)
        sb_lay.setSpacing(0)

        # ── Left: page navigation ─────────────────────────────────────────
        nav_w = QWidget()
        nav_w.setObjectName("sbNav")
        nav_lay = QHBoxLayout(nav_w)
        nav_lay.setContentsMargins(0, 0, 0, 0)
        nav_lay.setSpacing(4)

        btn_first = QToolButton()
        btn_first.setText("⏮")
        btn_first.setObjectName("sbNavBtn")
        btn_first.setToolTip("First Page")
        btn_first.clicked.connect(lambda: self._go_to_page(1))
        nav_lay.addWidget(btn_first)

        btn_prev = QToolButton()
        btn_prev.setDefaultAction(self._act_prev)
        btn_prev.setObjectName("sbNavBtn")
        btn_prev.setToolButtonStyle(Qt.ToolButtonTextOnly)
        nav_lay.addWidget(btn_prev)

        self._page_spin = QSpinBox()
        self._page_spin.setMinimum(1)
        self._page_spin.setAlignment(Qt.AlignCenter)
        self._page_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._page_spin.setFixedWidth(55)
        self._page_spin.setObjectName("sbPageSpin")
        self._page_spin.valueChanged.connect(self._go_to_page)
        nav_lay.addWidget(self._page_spin)

        self._page_label = QLabel(" / 0")
        self._page_label.setObjectName("sbPageLabel")
        nav_lay.addWidget(self._page_label)

        btn_next = QToolButton()
        btn_next.setDefaultAction(self._act_next)
        btn_next.setObjectName("sbNavBtn")
        btn_next.setToolButtonStyle(Qt.ToolButtonTextOnly)
        nav_lay.addWidget(btn_next)

        btn_last = QToolButton()
        btn_last.setText("⏭")
        btn_last.setObjectName("sbNavBtn")
        btn_last.setToolTip("Last Page")
        btn_last.clicked.connect(lambda: self._go_to_page(self._total_pages) if self._total_pages else None)
        nav_lay.addWidget(btn_last)

        sb_lay.addWidget(nav_w)

        # ── Centre: status messages ───────────────────────────────────────
        self._status_label = QLabel("Ready – Open a PDF to get started")
        self._status_label.setObjectName("sbMessage")
        self._status_label.setAlignment(Qt.AlignCenter)
        sb_lay.addWidget(self._status_label, 1)  # stretch=1 takes remaining

        # ── Right: zoom controls ──────────────────────────────────────────
        zoom_w = QWidget()
        zoom_w.setObjectName("sbZoom")
        zoom_lay = QHBoxLayout(zoom_w)
        zoom_lay.setContentsMargins(0, 0, 0, 0)
        zoom_lay.setSpacing(4)

        btn_zout = QToolButton()
        btn_zout.setDefaultAction(self._act_zoom_out)
        btn_zout.setObjectName("sbZoomBtn")
        btn_zout.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn_zout.setText("−")
        zoom_lay.addWidget(btn_zout)

        self._zoom_slider = QSlider(Qt.Horizontal)
        self._zoom_slider.setRange(50, 500)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(120)
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        zoom_lay.addWidget(self._zoom_slider)

        btn_zin = QToolButton()
        btn_zin.setDefaultAction(self._act_zoom_in)
        btn_zin.setObjectName("sbZoomBtn")
        btn_zin.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn_zin.setText("+")
        zoom_lay.addWidget(btn_zin)

        self._zoom_pct_label = QLabel("100%")
        self._zoom_pct_label.setObjectName("sbZoomPct")
        self._zoom_pct_label.setFixedWidth(48)
        self._zoom_pct_label.setAlignment(Qt.AlignCenter)
        zoom_lay.addWidget(self._zoom_pct_label)

        sb_lay.addWidget(zoom_w)

        # Install custom bottom bar into the main layout
        # (right before the content widget)
        central = self.centralWidget()
        main_lay = central.layout()
        main_lay.addWidget(sb_container)

        # Keep a thin QStatusBar for compatibility but hide it visually
        self._statusbar = QStatusBar()
        self._statusbar.setFixedHeight(0)
        self._statusbar.setVisible(False)
        self.setStatusBar(self._statusbar)

        # ── Subtle opacity-pulse on new messages ──────────────────────────
        self._sb_opacity = QGraphicsOpacityEffect(self._status_label)
        self._sb_opacity.setOpacity(1.0)
        self._status_label.setGraphicsEffect(self._sb_opacity)
        self._sb_anim = QPropertyAnimation(self._sb_opacity, b"opacity")
        self._sb_anim.setDuration(350)
        self._sb_anim.setEasingCurve(QEasingCurve.OutCubic)
        # Intercept showMessage via messageChanged signal
        self._statusbar.messageChanged.connect(self._on_status_msg)
        self._statusbar.showMessage("Ready – Open a PDF to get started")

    def _on_status_msg(self, msg):
        """Forward messages from the hidden QStatusBar to our custom label,
        and briefly pulse opacity when a new message appears."""
        if msg:
            self._status_label.setText(msg)
            self._sb_anim.stop()
            self._sb_anim.setStartValue(0.3)
            self._sb_anim.setEndValue(1.0)
            self._sb_anim.start()

    def _create_sidebar(self):
        # Right-side annotations dock
        self._ann_dock = QDockWidget("Annotations", self)
        self._ann_dock.setObjectName("ann_dock")
        self._ann_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._ann_list = QListWidget()
        self._ann_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._ann_list.customContextMenuRequested.connect(self._ann_list_context_menu)
        self._ann_list.itemClicked.connect(self._ann_list_item_clicked)
        self._ann_list.installEventFilter(self)
        self._ann_dock.setWidget(self._ann_list)
        self.addDockWidget(Qt.RightDockWidgetArea, self._ann_dock)

        # Connect toggle action (created in _create_actions)
        self._act_toggle_annotations.toggled.connect(self._ann_dock.setVisible)
        self._ann_dock.visibilityChanged.connect(self._act_toggle_annotations.setChecked)

        # Left sidebar icon buttons
        ann_btn = QPushButton("📋")
        ann_btn.setObjectName("sidebarBtn")
        ann_btn.setFixedSize(30, 30)
        ann_btn.setToolTip("Annotations")
        ann_btn.setCheckable(True)
        ann_btn.setChecked(True)
        ann_btn.toggled.connect(self._act_toggle_annotations.setChecked)
        self._ann_dock.visibilityChanged.connect(ann_btn.setChecked)

        sb_lay = self._left_sidebar.layout()
        sb_lay.addWidget(ann_btn)

    # -- settings persistence (JSON) ----------------------------------------
    def _settings_defaults(self):
        """Return default settings dict."""
        return {
            "window_geometry": None,
            "window_state": None,
            "theme_mode": "system",
            "author_name": "",
            "pen_color": [255, 0, 0, 255],
            "pen_width": 3,
            "highlight_color": [255, 255, 0, 80],
            "zoom_percent": 100,
            "recent_files": [],
            "last_file": None,
        }

    def _save_settings(self):
        """Persist all user preferences to settings.json."""
        pc = self._view._pen_color
        hc = self._view._highlight_color
        data = {
            "window_geometry": self.saveGeometry().toBase64().data().decode("ascii"),
            "window_state": self.saveState().toBase64().data().decode("ascii"),
            "theme_mode": self._theme_mode,
            "author_name": self._author_name,
            "pen_color": [pc.red(), pc.green(), pc.blue(), pc.alpha()],
            "pen_width": self._view._pen_width,
            "highlight_color": [hc.red(), hc.green(), hc.blue(), hc.alpha()],
            "zoom_percent": int(self._view._zoom * 100),
            "recent_files": self._recent_files[:self._max_recent],
            "last_file": self._file_path,
        }
        try:
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass  # silently ignore write failures

    def _load_settings(self):
        """Restore user preferences from settings.json."""
        defaults = self._settings_defaults()
        data = dict(defaults)
        try:
            with open(self._settings_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update(saved)
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            pass  # first run or corrupted file — use defaults

        # Window geometry & toolbar/dock layout
        if data.get("window_geometry"):
            try:
                geom = QByteArray.fromBase64(data["window_geometry"].encode("ascii"))
                self.restoreGeometry(geom)
            except Exception:
                pass
        if data.get("window_state"):
            try:
                state = QByteArray.fromBase64(data["window_state"].encode("ascii"))
                self.restoreState(state)
            except Exception:
                pass

        # Theme mode (system / dark / light)
        saved_mode = data.get("theme_mode")
        # Backwards compat: old "dark_mode" bool
        if saved_mode is None and data.get("dark_mode"):
            saved_mode = "dark"
        if saved_mode in ("system", "dark", "light"):
            self._set_theme_mode(saved_mode)
        else:
            self._set_theme_mode("system")

        # Author name
        self._author_name = data.get("author_name", "")

        # Pen colour
        pc = data.get("pen_color", defaults["pen_color"])
        if isinstance(pc, list) and len(pc) >= 3:
            self._view._pen_color = QColor(pc[0], pc[1], pc[2], pc[3] if len(pc) > 3 else 255)

        # Pen width
        pw = data.get("pen_width", defaults["pen_width"])
        self._view._pen_width = int(pw)
        self._pen_width_spin.setValue(int(pw))

        # Highlight colour
        hc = data.get("highlight_color", defaults["highlight_color"])
        if isinstance(hc, list) and len(hc) >= 3:
            self._view._highlight_color = QColor(hc[0], hc[1], hc[2], hc[3] if len(hc) > 3 else 80)

        # Zoom
        zp = data.get("zoom_percent", 100)
        if zp != 100:
            factor = zp / 100.0
            self._view.set_zoom(factor)
            self._zoom_slider.setValue(int(zp))

        # Recent files
        self._recent_files = data.get("recent_files", [])
        # Filter out files that no longer exist
        self._recent_files = [f for f in self._recent_files if os.path.isfile(f)]
        self._rebuild_recent_menu()

        # Last file — optionally re-open
        last = data.get("last_file")
        if last and os.path.isfile(last):
            self._load_pdf(last)

        # Final theme application — must happen after restoreState() and all
        # widget creation so the stylesheet covers everything reliably.
        self._apply_theme()

    def _add_to_recent(self, path):
        """Add a file path to the recent files list (most-recent first)."""
        path = os.path.normpath(path)
        # Remove if already present (to re-insert at top)
        self._recent_files = [f for f in self._recent_files if os.path.normpath(f) != path]
        self._recent_files.insert(0, path)
        self._recent_files = self._recent_files[:self._max_recent]
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        """Rebuild the Recent Files submenu."""
        if not hasattr(self, "_recent_menu"):
            return
        self._recent_menu.clear()
        if not self._recent_files:
            act = self._recent_menu.addAction("(No recent files)")
            act.setEnabled(False)
            return
        for path in self._recent_files:
            display = os.path.basename(path)
            act = self._recent_menu.addAction(display)
            act.setToolTip(path)
            act.setData(path)
            act.triggered.connect(lambda checked, p=path: self._load_pdf(p))
        self._recent_menu.addSeparator()
        clear_act = self._recent_menu.addAction("Clear Recent Files")
        clear_act.triggered.connect(self._clear_recent_files)

    def _clear_recent_files(self):
        """Clear the recent files list."""
        self._recent_files.clear()
        self._rebuild_recent_menu()

    # -- state helpers ------------------------------------------------------
    def _update_ui_state(self):
        has_doc = self._doc is not None
        self._act_save.setEnabled(has_doc)
        self._act_save_as.setEnabled(has_doc)
        self._act_prev.setEnabled(has_doc and self._current_page > 0)
        self._act_next.setEnabled(has_doc and self._current_page < self._total_pages - 1)
        for a in self._tool_actions:
            if a not in self._edit_tool_actions:
                a.setEnabled(has_doc)
        # Edit tools only when edit mode is on (auto-managed by tab switch)
        edit_on = has_doc and self._act_edit_mode.isChecked()
        for a in self._edit_tool_actions:
            a.setEnabled(edit_on)
        self._act_undo.setEnabled(has_doc and (self._view.can_undo() or bool(self._doc_undo_stack)))
        self._act_redo.setEnabled(has_doc and (self._view.can_redo() or bool(self._doc_redo_stack)))

    def _update_undo_redo_state(self):
        can_u = self._view.can_undo() or bool(self._doc_undo_stack)
        can_r = self._view.can_redo() or bool(self._doc_redo_stack)
        self._act_undo.setEnabled(can_u)
        self._act_redo.setEnabled(can_r)
        self._rebuild_annotation_list()

    def _toggle_add_image(self):
        """Toggle Add Image tool on/off."""
        if self._view._tool == PDFGraphicsView.TOOL_ADD_IMAGE:
            # Already active — switch back to edit-text tool
            self._set_tool(PDFGraphicsView.TOOL_EDIT_TEXT)
        else:
            self._set_tool(PDFGraphicsView.TOOL_ADD_IMAGE)

    def _set_tool(self, tool):
        self._view.set_tool(tool)
        for a in self._tool_actions:
            a.setChecked(False)
        # Also uncheck the Add Image button (lives in edit_tool_actions)
        self._act_add_image.setChecked(False)
        mapping = {
            PDFGraphicsView.TOOL_NONE: self._act_select,
            PDFGraphicsView.TOOL_SELECT_TEXT: self._act_select_text,
            PDFGraphicsView.TOOL_HIGHLIGHT: self._act_highlight,
            PDFGraphicsView.TOOL_PEN: self._act_pen,
            PDFGraphicsView.TOOL_NOTE: self._act_note,
            PDFGraphicsView.TOOL_TEXT: self._act_text,
            PDFGraphicsView.TOOL_RECT: self._act_rect,
            PDFGraphicsView.TOOL_ERASER: self._act_eraser,
            PDFGraphicsView.TOOL_ADD_IMAGE: self._act_add_image,
        }
        if tool in mapping:
            mapping[tool].setChecked(True)
        # Disable highlight-selection when leaving select-text mode
        if tool != PDFGraphicsView.TOOL_SELECT_TEXT:
            self._act_highlight_sel.setEnabled(False)
        self._statusbar.showMessage(f"Tool: {tool.replace('_', ' ').title()}")

    # -- undo / redo -------------------------------------------------------
    def _undo(self):
        if self._view.can_undo():
            self._view.undo()
            self._statusbar.showMessage("Undo")
        elif self._doc_undo_stack:
            self._doc_undo()
        self._update_undo_redo_state()

    def _redo(self):
        if self._view.can_redo():
            self._view.redo()
            self._statusbar.showMessage("Redo")
        elif self._doc_redo_stack:
            self._doc_redo()
        self._update_undo_redo_state()

    # -- document-level snapshot undo/redo ----------------------------------
    def _push_doc_snapshot(self, label=""):
        """Save current PDF bytes so the operation can be undone."""
        if not self._doc:
            return
        data = self._doc.tobytes(deflate=True, garbage=0)
        self._doc_undo_stack.append((label, data))
        if len(self._doc_undo_stack) > self._doc_undo_limit:
            self._doc_undo_stack.pop(0)
        self._doc_redo_stack.clear()
        self._update_undo_redo_state()

    def _doc_undo(self):
        """Restore the PDF to the previous snapshot."""
        if not self._doc_undo_stack:
            return
        label, old_bytes = self._doc_undo_stack.pop()
        # Save current state to redo stack
        cur_bytes = self._doc.tobytes(deflate=True, garbage=0)
        self._doc_redo_stack.append((label, cur_bytes))
        self._restore_doc_from_bytes(old_bytes)
        self._statusbar.showMessage(f"Undo: {label}")
        self._update_undo_redo_state()

    def _doc_redo(self):
        """Re-apply a previously undone document operation."""
        if not self._doc_redo_stack:
            return
        label, redo_bytes = self._doc_redo_stack.pop()
        # Save current state to undo stack
        cur_bytes = self._doc.tobytes(deflate=True, garbage=0)
        self._doc_undo_stack.append((label, cur_bytes))
        self._restore_doc_from_bytes(redo_bytes)
        self._statusbar.showMessage(f"Redo: {label}")
        self._update_undo_redo_state()

    def _restore_doc_from_bytes(self, pdf_bytes):
        """Replace the current document with one loaded from bytes and refresh."""
        if self._view._edit_mode:
            self._view.exit_edit_mode()
            self._act_edit_mode.setChecked(False)
        self._doc.close()
        self._doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        self._total_pages = len(self._doc)
        # Refresh tiles
        self._tile_generation += 1
        self._remove_all_tile_items()
        self._tile_cache.clear()
        self._current_tile_ss = 0.0
        self._ensure_visible_tiles()
        self._load_all_word_data()
        self._update_ui_state()

    # -- text selection actions ---------------------------------------------
    def _on_selection_changed(self, text):
        has_sel = bool(text.strip())
        self._act_highlight_sel.setEnabled(has_sel)
        if has_sel:
            preview = text[:80].replace("\n", " ")
            if len(text) > 80:
                self._statusbar.showMessage(f'Selected: "{preview}…"')
            else:
                self._statusbar.showMessage(f'Selected: "{preview}"')

    def _highlight_selection(self):
        if self._view.highlight_selection():
            self._statusbar.showMessage("Highlighted selected text")

    # -- file operations ----------------------------------------------------
    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf);;All Files (*)"
        )
        if not path:
            return
        self._load_pdf(path)

    def _load_pdf(self, path):
        try:
            doc = fitz.open(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot open PDF:\n{e}")
            return

        # Exit edit mode if active
        if self._view._edit_mode:
            self._view.exit_edit_mode()
            self._act_edit_mode.setChecked(False)

        self._doc = doc
        self._file_path = path
        self._total_pages = len(doc)
        self._current_page = 0
        self._annotations.clear()
        self._ann_list.clear()
        self._view.clear_undo_redo()
        self._doc_undo_stack.clear()
        self._doc_redo_stack.clear()

        # Track in recent files
        self._add_to_recent(path)

        self._updating_spinner = True
        self._page_spin.setMaximum(self._total_pages)
        self._page_spin.setValue(1)
        self._updating_spinner = False
        self._page_label.setText(f" / {self._total_pages}")

        self._build_page_layout()
        self._update_ui_state()
        self.setWindowTitle(f"PDF Editor – {os.path.basename(path)}")
        self._statusbar.showMessage(f"Opened: {path}  ({self._total_pages} pages)")

    def _build_page_layout(self):
        """Calculate the layout (offsets/sizes) for all pages WITHOUT rendering.

        Uses PDF page dimensions scaled to the target DPI to determine
        pixel sizes, then places lightweight grey placeholder rectangles
        in the scene.  Actual tile rendering is deferred to
        _ensure_visible_tiles().
        """
        if self._doc is None:
            return

        t = self._theme()
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QBrush(t["scene_bg"]))
        self._page_offsets = []
        self._page_heights = []
        self._page_widths = []
        self._page_placeholders = {}
        self._page_border_items = {}
        self._page_shadow_items = {}
        self._separator_items = []
        self._tile_items.clear()
        self._tile_cache.clear()
        self._current_tile_ss = 0.0
        self._tile_generation += 1

        scale = self._dpi / 72.0
        y_offset = 0
        max_width = 0
        shadow_offset = 4  # pixels for drop-shadow effect

        for page_num in range(self._total_pages):
            page = self._doc[page_num]
            rect = page.rect                      # fitz.Rect in points
            pw = int(rect.width * scale)
            ph = int(rect.height * scale)

            self._page_offsets.append(y_offset)
            self._page_heights.append(ph)
            self._page_widths.append(pw)
            max_width = max(max_width, pw)

            # Drop shadow (slightly offset behind the page)
            shadow = self._scene.addRect(
                QRectF(shadow_offset, y_offset + shadow_offset, pw, ph),
                QPen(Qt.NoPen),
                QBrush(t["page_shadow"])
            )
            shadow.setZValue(-3)
            self._page_shadow_items[page_num] = shadow

            # Page border (visible frame around the page area)
            border = self._scene.addRect(
                QRectF(-1, y_offset - 1, pw + 2, ph + 2),
                QPen(t["page_border"], 1.5),
                QBrush(Qt.NoBrush)
            )
            border.setZValue(0.5)  # above pixmap, below annotations
            self._page_border_items[page_num] = border

            # Placeholder rect (cheap to keep in memory)
            placeholder = self._scene.addRect(
                QRectF(0, y_offset, pw, ph),
                QPen(t["placeholder_border"]),
                QBrush(t["placeholder_bg"])
            )
            placeholder.setZValue(-2)
            self._page_placeholders[page_num] = placeholder

            # Separator line between pages
            if page_num < self._total_pages - 1:
                sep_y = y_offset + ph + self.PAGE_GAP / 2
                sep = self._scene.addLine(
                    0, sep_y, max(max_width, pw), sep_y,
                    QPen(t["separator"], 1)
                )
                self._separator_items.append(sep)

            y_offset += ph + self.PAGE_GAP

        total_height = y_offset - self.PAGE_GAP if self._total_pages > 0 else 0
        self._scene.setSceneRect(QRectF(-10, -10, max_width + 20, total_height + 20))
        self._view.setScene(self._scene)
        self._view.set_page_layout(self._page_offsets, self._page_heights, self._page_widths)

        # Load word data for all pages (lightweight – just coordinates)
        self._load_all_word_data()

        # Load existing PDF annotations (Text notes, highlights, etc.)
        self._load_existing_annotations()

        # Render the tiles that are initially visible
        self._ensure_visible_tiles()

    # -- tile-based page rendering ------------------------------------------

    def _tile_scene_size(self):
        """Scene-coordinate extent of one tile at the current zoom.

        Each tile produces at most TILE_PIXELS×TILE_PIXELS rendered
        pixels regardless of zoom.  At higher zoom the tile simply
        covers a smaller region of the page, so PyMuPDF re-renders
        less PDF area at higher fidelity.  Text is always re-rasterised
        from vectors → no quality cap, constant RAM per tile.
        """
        return self.TILE_PIXELS / max(self._view._zoom, 0.1)

    def _visible_tiles(self):
        """Return set of (page, row, col) for tiles in/near the viewport.

        Tile row/col are computed from the zoom-dependent grid.
        Only the range visible on screen (+ 1.5-tile buffer) is returned,
        so this is O(visible_tiles), not O(total_tiles_per_page).
        """
        ts = self._tile_scene_size()
        vp = self._view.viewport().rect()
        top = self._view.mapToScene(vp.topLeft())
        bot = self._view.mapToScene(vp.bottomRight())

        buf = ts * 1.5
        vis_x0 = top.x() - buf
        vis_y0 = top.y() - buf
        vis_x1 = bot.x() + buf
        vis_y1 = bot.y() + buf

        tiles = set()
        for pn in range(self._total_pages):
            y_off = self._page_offsets[pn]
            pw = self._page_widths[pn]
            ph = self._page_heights[pn]
            if y_off + ph < vis_y0 or y_off > vis_y1:
                continue
            # Compute visible row/col range directly (O(1) per page)
            local_y0 = max(0.0, vis_y0 - y_off)
            local_y1 = min(float(ph), vis_y1 - y_off)
            local_x0 = max(0.0, vis_x0)
            local_x1 = min(float(pw), vis_x1)
            r_start = max(0, int(local_y0 / ts))
            r_end = int(math.ceil(ph / ts)) - 1
            r_end = min(r_end, int(local_y1 / ts))
            c_start = max(0, int(local_x0 / ts))
            c_end = int(math.ceil(pw / ts)) - 1
            c_end = min(c_end, int(local_x1 / ts))
            for r in range(r_start, r_end + 1):
                for c in range(c_start, c_end + 1):
                    tiles.add((pn, r, c))
        return tiles

    def _load_existing_annotations(self):
        """Read existing PDF annotations and add scene items for them.

        Handles:
        - 'Text' (sticky-note icons)
        - 'Highlight' (translucent highlight rectangles)
        """
        if self._doc is None or self._scene is None:
            return

        scale = self._dpi / 72.0
        t = self._theme()

        for page_num in range(self._total_pages):
            page = self._doc[page_num]
            y_off = self._page_offsets[page_num]

            for annot in page.annots():
                if annot.type[0] == fitz.PDF_ANNOT_TEXT:  # sticky note
                    info = annot.info
                    text = info.get("content", "") or annot.get_text()
                    author = info.get("title", "")
                    # annot.rect top-left in points → pixel coordinates
                    rect = annot.rect
                    px = rect.x0 * scale
                    py = rect.y0 * scale + y_off

                    icon = StickyNoteItem(
                        text=text,
                        author=author,
                        fill_color=t["note_bg"],
                        border_color=t["note_border"],
                    )
                    icon.setPos(px, py)
                    icon.setData(2, "from_pdf")  # mark as pre-existing
                    self._scene.addItem(icon)

                    # Register in annotations model
                    ann = Annotation(Annotation.NOTE, page_num, text=text)
                    self._annotations.append(ann)

                elif annot.type[0] == fitz.PDF_ANNOT_HIGHLIGHT:
                    # Reconstruct highlight colour from the annotation
                    colors = annot.colors
                    stroke = colors.get("stroke") or colors.get("fill")
                    opacity = annot.opacity if annot.opacity is not None else 0.3
                    if stroke:
                        qc = QColor(
                            int(stroke[0] * 255),
                            int(stroke[1] * 255),
                            int(stroke[2] * 255),
                            int(opacity * 255),
                        )
                    else:
                        qc = QColor(255, 255, 0, 80)  # default yellow

                    brush = QBrush(qc)
                    pen = QPen(Qt.NoPen)

                    # Highlight annots store quad-points (4 corners per quad)
                    vertices = annot.vertices
                    if vertices and len(vertices) >= 4:
                        for qi in range(0, len(vertices) - 3, 4):
                            quad = vertices[qi : qi + 4]
                            xs = [p[0] * scale for p in quad]
                            ys = [p[1] * scale + y_off for p in quad]
                            x0, x1 = min(xs), max(xs)
                            y0, y1 = min(ys), max(ys)
                            r = QRectF(x0, y0, x1 - x0, y1 - y0)
                            hi = self._scene.addRect(r, pen, brush)
                            hi.setZValue(2)
                            hi.setData(0, "annotation")
                            hi.setData(2, "from_pdf")
                    else:
                        # Fallback: use the annotation bounding rect
                        rect = annot.rect
                        r = QRectF(
                            rect.x0 * scale,
                            rect.y0 * scale + y_off,
                            (rect.x1 - rect.x0) * scale,
                            (rect.y1 - rect.y0) * scale,
                        )
                        hi = self._scene.addRect(r, pen, brush)
                        hi.setZValue(2)
                        hi.setData(0, "annotation")
                        hi.setData(2, "from_pdf")

                    # Register in sidebar
                    ann = Annotation(Annotation.HIGHLIGHT, page_num,
                                     color=qc.name())
                    self._annotations.append(ann)

        # Rebuild the list with proper scene-item references
        self._rebuild_annotation_list()

    def _ensure_visible_tiles(self):
        """Add tiles for the visible viewport region; remove far-away ones."""
        if self._doc is None or self._scene is None:
            return

        ts = self._tile_scene_size()
        generation = self._tile_generation
        ts_key = round(ts, 1)

        # If the tile grid changed, clear scene tiles (grid depends on zoom)
        if abs(ts - self._current_tile_ss) > 0.05:
            self._remove_all_tile_items()
            self._current_tile_ss = ts

        visible = self._visible_tiles()
        current = set(self._tile_items.keys())

        # Render missing tiles
        for key in visible - current:
            if self._tile_generation != generation:
                return  # zoom changed while rendering – abort
            page, row, col = key
            cache_key = (page, row, col, ts_key)
            if cache_key in self._tile_cache:
                self._tile_cache.move_to_end(cache_key)
                self._add_tile_to_scene(page, row, col,
                                        self._tile_cache[cache_key])
            else:
                self._render_tile(page, row, col)
                

        # Remove tiles far from the viewport
        for key in current - visible:
            self._remove_tile_from_scene(key)

        # Trim LRU cache
        self._trim_tile_cache(visible)

    def _render_tile(self, page_num, row, col):
        """Render one tile from the PDF and add it to the scene + cache.

        Each tile produces at most TILE_PIXELS×TILE_PIXELS rendered
        pixels.  The fitz clip ensures we only decode/rasterise the
        small PDF region that this tile covers.
        """
        ts = self._tile_scene_size()
        scale_base = self._dpi / 72.0

        pw = self._page_widths[page_num]
        ph = self._page_heights[page_num]

        # Tile bounds in scene (base-DPI) coordinates
        tx = col * ts
        ty = row * ts
        tw = min(ts, pw - tx)
        th = min(ts, ph - ty)
        if tw <= 0 or th <= 0:
            return

        # Convert scene coords to PDF points for the clip rectangle
        x0_pts = tx / scale_base
        y0_pts = ty / scale_base
        x1_pts = (tx + tw) / scale_base
        y1_pts = (ty + th) / scale_base

        clip = fitz.Rect(x0_pts, y0_pts, x1_pts, y1_pts)

        # Matrix that maps full-tile scene width → TILE_PIXELS rendered px
        mat_scale = self.TILE_PIXELS * scale_base / ts
        mat = fitz.Matrix(mat_scale, mat_scale)

        page = self._doc[page_num]
        # annots=False suppresses built-in annotation icons from the raster;
        # we draw annotations as separate scene items instead.
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False, annots=False)
        img = QImage(pix.samples, pix.width, pix.height,
                     pix.stride, QImage.Format_RGB888)
        qpixmap = QPixmap.fromImage(img)

        # Store in LRU cache
        ts_key = round(ts, 1)
        cache_key = (page_num, row, col, ts_key)
        self._tile_cache[cache_key] = qpixmap
        self._tile_cache.move_to_end(cache_key)

        self._add_tile_to_scene(page_num, row, col, qpixmap)

    def _add_tile_to_scene(self, page_num, row, col, qpixmap):
        """Place a tile QPixmap in the scene at the correct position."""
        ts = self._tile_scene_size()
        y_off = self._page_offsets[page_num]
        pw = self._page_widths[page_num]
        ph = self._page_heights[page_num]

        tx = col * ts
        ty = row * ts
        tw = min(ts, pw - tx)
        th = min(ts, ph - ty)

        item = self._scene.addPixmap(qpixmap)
        item.setPos(tx, y_off + ty)
        # Scale to exactly cover the tile's scene rectangle (avoids gaps)
        sx = tw / qpixmap.width() if qpixmap.width() > 0 else 1.0
        sy = th / qpixmap.height() if qpixmap.height() > 0 else 1.0
        item.setTransform(QTransform.fromScale(sx, sy))
        item.setZValue(-1)
        item.setData(0, "tile")
        self._tile_items[(page_num, row, col)] = item

    def _remove_tile_from_scene(self, key):
        """Remove a single tile's scene item (keeps LRU cache entry)."""
        item = self._tile_items.pop(key, None)
        if item and item.scene() is not None:
            self._scene.removeItem(item)

    def _remove_all_tile_items(self):
        """Remove every tile pixmap item from the scene."""
        for key in list(self._tile_items):
            item = self._tile_items.pop(key, None)
            if item and item.scene() is not None:
                self._scene.removeItem(item)

    def _trim_tile_cache(self, visible_keys=None):
        """Evict oldest LRU entries that are off-screen, respecting the cap."""
        if visible_keys is None:
            visible_keys = set()
        ts_key = round(self._tile_scene_size(), 1)
        visible_cache = {(p, r, c, ts_key) for (p, r, c) in visible_keys}
        while len(self._tile_cache) > self._tile_cache_max:
            oldest_key = next(iter(self._tile_cache))
            if oldest_key in visible_cache:
                break  # don't evict visible tiles
            self._tile_cache.pop(oldest_key)

    def _load_all_word_data(self):
        """Extract word boxes from ALL pages, offset to scene coordinates."""
        scale = self._dpi / 72.0
        all_words = []
        for page_num in range(self._total_pages):
            page = self._doc[page_num]
            y_off = self._page_offsets[page_num]
            raw_words = page.get_text("words")
            for w in raw_words:
                all_words.append((
                    w[0] * scale,
                    w[1] * scale + y_off,
                    w[2] * scale,
                    w[3] * scale + y_off,
                    w[4], w[5], w[6], w[7],
                    page_num,
                ))
        self._view.set_word_data(all_words)

    # -- navigation ---------------------------------------------------------
    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._view.scroll_to_page(self._current_page)
            self._updating_spinner = True
            self._page_spin.setValue(self._current_page + 1)
            self._updating_spinner = False
            self._update_ui_state()

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._view.scroll_to_page(self._current_page)
            self._updating_spinner = True
            self._page_spin.setValue(self._current_page + 1)
            self._updating_spinner = False
            self._update_ui_state()

    def _go_to_page(self, val):
        if self._updating_spinner:
            return
        page = val - 1
        if 0 <= page < self._total_pages and page != self._current_page:
            self._current_page = page
            self._view.scroll_to_page(page)
            self._update_ui_state()

    # -- zoom slider --------------------------------------------------------
    def _on_zoom_slider(self, val):
        factor = val / 100.0
        self._view.set_zoom(factor)
        self._zoom_pct_label.setText(f"{val}%")

    def _on_zoom_changed(self, new_zoom):
        """Called when zoom factor changes; schedule a hi-res re-render."""
        # Update slider to reflect new zoom
        pct = int(new_zoom * 100)
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(max(50, min(500, pct)))
        self._zoom_slider.blockSignals(False)
        self._zoom_pct_label.setText(f"{pct}%")

        # Debounce: restart timer so rapid zoom steps don't each trigger a re-render
        self._zoom_render_timer.start()

    def _rerender_for_zoom(self):
        """Re-render visible tiles if the tile grid changed due to zoom."""
        if self._doc is None or self._scene is None:
            return
        ts = self._tile_scene_size()
        if abs(ts - self._current_tile_ss) < 0.05:
            return
        # Grid changed – bump generation, clear scene tiles, re-render
        self._tile_generation += 1
        self._remove_all_tile_items()
        self._current_tile_ss = ts
        self._ensure_visible_tiles()

    # -- color pickers ------------------------------------------------------
    def _pick_pen_color(self):
        color = QColorDialog.getColor(self._view._pen_color, self, "Pen Color")
        if color.isValid():
            self._view.set_pen_color(color)

    def _pick_highlight_color(self):
        color = QColorDialog.getColor(
            self._view._highlight_color, self, "Highlight Color",
            QColorDialog.ShowAlphaChannel
        )
        if color.isValid():
            self._view.set_highlight_color(color)

    # -- link click handler -------------------------------------------------
    def _handle_link_click(self, link):
        """Handle a PDF link click — open URL or navigate to page."""
        import webbrowser
        kind = link.get("kind", -1)
        if kind == fitz.LINK_URI:
            uri = link.get("uri", "")
            if uri:
                if uri.startswith(("http://", "https://", "mailto:", "ftp://")):
                    webbrowser.open(uri)
                else:
                    # Let the OS/browser figure out the protocol
                    os.startfile(uri)
                self._statusbar.showMessage(f"Opened: {uri}")
        elif kind == fitz.LINK_GOTO:
            target_page = link.get("page", 0)
            if 0 <= target_page < self._total_pages:
                self._go_to_page(target_page)
                self._statusbar.showMessage(f"Jumped to page {target_page + 1}")

    # -- annotations --------------------------------------------------------
    def _on_annotation_added(self, ann):
        self._annotations.append(ann)
        self._rebuild_annotation_list()
        self._statusbar.showMessage(f"Added {ann.kind} annotation on page {ann.page + 1}")

    def _rebuild_annotation_list(self):
        """Rebuild the sidebar list from items actually present in the scene.
        Each QListWidgetItem stores the scene graphics item in Qt.UserRole."""
        self._ann_list.clear()
        if not self._scene:
            return
        for item in self._scene.items():
            tag = item.data(0)
            list_item = None
            if tag == "sticky_note" and isinstance(item, StickyNoteItem):
                page = self._view.page_at_y(item.pos().y())
                text = item.note_text()
                label = f"[P{page + 1}] note"
                if text:
                    label += f": {text[:30]}"
                list_item = QListWidgetItem(label)
            elif tag == "annotation":
                if isinstance(item, QGraphicsPathItem):
                    page = self._view.page_at_y(item.boundingRect().center().y())
                    list_item = QListWidgetItem(f"[P{page + 1}] freehand")
                elif isinstance(item, QGraphicsRectItem):
                    page = self._view.page_at_y(item.rect().center().y())
                    brush = item.brush()
                    if brush.style() != Qt.NoBrush and brush.color().alpha() > 0 and brush.color().alpha() < 255:
                        list_item = QListWidgetItem(f"[P{page + 1}] highlight")
                    else:
                        list_item = QListWidgetItem(f"[P{page + 1}] rectangle")
                elif isinstance(item, QGraphicsTextItem):
                    page = self._view.page_at_y(item.pos().y())
                    text = item.toPlainText()
                    label = f"[P{page + 1}] text"
                    if text:
                        label += f": {text[:30]}"
                    list_item = QListWidgetItem(label)
            elif tag == "edit_image" and isinstance(item, QGraphicsPixmapItem):
                page = self._view.page_at_y(item.pos().y())
                src = item.data(1) or "image"
                name = os.path.basename(src) if src else "image"
                list_item = QListWidgetItem(f"[P{page + 1}] image: {name[:30]}")

            if list_item is not None:
                list_item.setData(Qt.UserRole, item)
                self._ann_list.addItem(list_item)

    # -- annotation list interactions ---------------------------------------
    def _ann_list_item_clicked(self, list_item):
        """Navigate to the annotation's page and flash-highlight it."""
        scene_item = list_item.data(Qt.UserRole)
        if scene_item is None or scene_item.scene() is None:
            return
        # Get bounding rect in scene coordinates
        rect = scene_item.sceneBoundingRect()
        page = self._view.page_at_y(rect.center().y())

        # Navigate to the page
        if 0 <= page < self._total_pages:
            self._current_page = page
            self._updating_spinner = True
            self._page_spin.setValue(page + 1)
            self._updating_spinner = False
            self._update_ui_state()

        # Scroll to center the item and flash it
        self._view.centerOn(rect.center())
        self._flash_scene_item(rect)

    def _flash_scene_item(self, rect):
        """Draw a brief pulsing rectangle around the given scene rect."""
        # Remove previous flash if any
        if hasattr(self, '_flash_rect') and self._flash_rect and self._flash_rect.scene():
            self._scene.removeItem(self._flash_rect)
        # Create a highlight overlay slightly larger than the item
        margin = 6
        flash_rect = QRectF(
            rect.x() - margin, rect.y() - margin,
            rect.width() + 2 * margin, rect.height() + 2 * margin
        )
        pen = QPen(QColor(0, 120, 255), 3)
        brush = QBrush(QColor(0, 120, 255, 40))
        self._flash_rect = self._scene.addRect(flash_rect, pen, brush)
        self._flash_rect.setZValue(9999)

        # Fade out and remove after 800ms
        effect = QGraphicsOpacityEffect(self)
        self._flash_rect.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(800)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        flash_ref = self._flash_rect  # prevent GC
        anim.finished.connect(lambda: (
            self._scene.removeItem(flash_ref)
            if flash_ref.scene() is not None else None
        ))
        self._flash_anim = anim  # prevent GC
        anim.start()

    def _ann_list_context_menu(self, pos):
        """Show context menu for the annotation list."""
        list_item = self._ann_list.itemAt(pos)
        if list_item is None:
            return
        scene_item = list_item.data(Qt.UserRole)
        if scene_item is None or scene_item.scene() is None:
            return

        menu = QMenu(self)
        is_note = isinstance(scene_item, StickyNoteItem)
        is_text = (scene_item.data(0) == "annotation"
                   and isinstance(scene_item, QGraphicsTextItem))

        if is_note:
            act_edit = menu.addAction("✏ Edit Note")
        elif is_text:
            act_edit = menu.addAction("✏ Edit Text")
        else:
            act_edit = None

        act_delete = menu.addAction("🗑 Delete")

        chosen = menu.exec_(self._ann_list.mapToGlobal(pos))
        if chosen is None:
            return

        if chosen == act_delete:
            self._delete_scene_item(scene_item)
        elif chosen == act_edit:
            if is_note:
                scene_item._open_edit_dialog()
                self._rebuild_annotation_list()
            elif is_text:
                self._edit_text_annotation(scene_item)

    def _edit_text_annotation(self, text_item):
        """Open a dialog to edit a QGraphicsTextItem annotation."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Text")
        layout = QVBoxLayout(dlg)
        edit = QTextEdit()
        edit.setPlainText(text_item.toPlainText())
        layout.addWidget(QLabel("Text:"))
        layout.addWidget(edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.resize(350, 200)
        if dlg.exec_() == QDialog.Accepted:
            new_text = edit.toPlainText()
            if new_text != text_item.toPlainText():
                text_item.setPlainText(new_text)
                self._rebuild_annotation_list()
                self._statusbar.showMessage("Text annotation updated.")

    def _delete_scene_item(self, scene_item):
        """Remove a scene annotation item with undo support."""
        scene = scene_item.scene()
        if scene is None:
            return
        scene.removeItem(scene_item)
        self._view._push_undo("remove", [scene_item])
        self._rebuild_annotation_list()
        self._statusbar.showMessage("Annotation deleted.")
    # -- save ---------------------------------------------------------------
    def _save_file(self):
        if not self._file_path:
            self._save_file_as()
            return
        self._do_save(self._file_path)

    def _save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF As", "", "PDF Files (*.pdf);;All Files (*)"
        )
        if path:
            self._do_save(path)

    def _item_page_and_offset(self, item):
        """Return (page_num, y_offset) for a scene item based on its position."""
        if isinstance(item, StickyNoteItem):
            y = item.pos().y()
        elif isinstance(item, QGraphicsRectItem):
            y = item.rect().center().y()
        elif isinstance(item, QGraphicsPathItem):
            y = item.boundingRect().center().y()
        elif isinstance(item, QGraphicsTextItem):
            y = item.pos().y()
        else:
            y = 0
        page = self._view.page_at_y(y)
        return page, self._page_offsets[page] if page < len(self._page_offsets) else 0

    def _do_save(self, path):
        """Burn annotations into the PDF and save."""
        if self._doc is None:
            return

        scene = self._view.scene()
        if scene is None:
            return

        try:
            mat = fitz.Matrix(self._dpi / 72, self._dpi / 72)
            inv_mat = ~mat

            # Remove all pre-existing annotations from the PDF so we can
            # re-write them from the scene items without duplication.
            for pn in range(self._total_pages):
                pg = self._doc[pn]
                # Collect first, then delete (avoids iterator invalidation)
                annots_to_delete = list(pg.annots())
                for a in annots_to_delete:
                    pg.delete_annot(a)

            for item in scene.items():
                tag = item.data(0)
                if tag not in ("annotation", "sticky_note"):
                    continue

                page_num, y_off = self._item_page_and_offset(item)
                page = self._doc[page_num]

                if isinstance(item, QGraphicsPathItem):
                    path_obj = item.path()
                    points = []
                    for i in range(path_obj.elementCount()):
                        e = path_obj.elementAt(i)
                        pt = fitz.Point(e.x, e.y - y_off) * inv_mat
                        points.append(pt)
                    if len(points) >= 2:
                        annot = page.add_ink_annot([points])
                        color_str = item.pen().color().name()
                        r, g, b = self._hex_to_rgb(color_str)
                        annot.set_colors(stroke=(r, g, b))
                        annot.set_border(width=item.pen().widthF() / (self._dpi / 72))
                        annot.update()

                elif isinstance(item, QGraphicsRectItem):
                    rect = item.rect()
                    fitz_rect = fitz.Rect(
                        rect.x(), rect.y() - y_off,
                        rect.x() + rect.width(),
                        rect.y() - y_off + rect.height()
                    ) * inv_mat

                    brush = item.brush()
                    if brush.style() != Qt.NoBrush and brush.color().alpha() > 0:
                        annot = page.add_highlight_annot(fitz_rect)
                        c = brush.color()
                        annot.set_colors(stroke=(c.redF(), c.greenF(), c.blueF()))
                        annot.set_opacity(c.alphaF())
                        annot.update()
                    else:
                        annot = page.add_rect_annot(fitz_rect)
                        color_str = item.pen().color().name()
                        r, g, b = self._hex_to_rgb(color_str)
                        annot.set_colors(stroke=(r, g, b))
                        annot.set_border(width=item.pen().widthF() / (self._dpi / 72))
                        annot.update()

                elif isinstance(item, StickyNoteItem):
                    # --- Sticky note → standard PDF Text annotation -----
                    text = item.note_text()
                    pos = item.pos()
                    fitz_point = fitz.Point(pos.x(), pos.y() - y_off) * inv_mat
                    annot = page.add_text_annot(fitz_point, text)
                    # Write author: use the note's own author if set,
                    # otherwise fall back to the app-level author name.
                    author = item.author() or self._author_name
                    if author:
                        annot.set_info(title=author)
                    annot.set_colors(stroke=(1, 0.92, 0.23))  # yellow icon
                    annot.update()

                elif isinstance(item, QGraphicsTextItem):
                    text = item.toPlainText()
                    pos = item.pos()
                    fitz_point = fitz.Point(pos.x(), pos.y() - y_off) * inv_mat
                    rect_w = item.boundingRect().width()
                    rect_h = item.boundingRect().height()
                    fitz_rect = fitz.Rect(
                        fitz_point.x, fitz_point.y,
                        fitz_point.x + rect_w / (self._dpi / 72),
                        fitz_point.y + rect_h / (self._dpi / 72)
                    )
                    annot = page.add_freetext_annot(fitz_rect, text, fontsize=11)
                    annot.update()

            if path == self._file_path:
                # After mass delete + re-add, incremental save is unreliable.
                # Save to a temp file, close, and reopen.
                import tempfile
                tmp_dir = os.path.dirname(path)
                fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
                os.close(fd)
                self._doc.save(tmp_path, garbage=4, deflate=True)
                self._doc.close()
                # Replace original with temp
                os.replace(tmp_path, path)
                # Reopen the saved file
                self._doc = fitz.open(path)
                self._total_pages = len(self._doc)
            else:
                self._doc.save(path, garbage=4, deflate=True)

            self._statusbar.showMessage(f"Saved: {path}")
            QMessageBox.information(self, "Saved", f"PDF saved to:\n{path}")

        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save PDF:\n{e}")

    @staticmethod
    def _hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))

    # -- show event (fade-in animation) ------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_did_startup_anim', False):
            self._did_startup_anim = True
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b"windowOpacity")
            anim.setDuration(350)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            # prevent garbage-collection
            self._startup_anim = anim

    # -- close event --------------------------------------------------------
    def closeEvent(self, event):
        if self._doc is not None:
            reply = QMessageBox.question(
                self, "Quit",
                "Any unsaved annotations will be lost.\nDo you want to quit?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            self._doc.close()
        # Persist all settings before exit
        self._save_settings()
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
