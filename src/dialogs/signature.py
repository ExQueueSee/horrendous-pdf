"""Signature dialog (draw or load signature images)."""

import os
import shutil
from datetime import datetime

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QSpinBox, QDialogButtonBox, QFileDialog,
    QGraphicsScene, QGraphicsView,
)
from PyQt5.QtGui import QPen, QBrush, QPainter, QPainterPath, QImage
from PyQt5.QtCore import Qt, QEvent

from .helpers import _get_signature_dir


class SignatureDialog(QDialog):
    """Dialog to manage and choose a signature image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Signature")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Your saved signatures:"))

        self._sig_list = QListWidget()
        self._refresh_signatures()
        layout.addWidget(self._sig_list)

        btn_row = QHBoxLayout()
        self._btn_import = QPushButton("Import Signature Image…")
        self._btn_import.clicked.connect(self._import_signature)
        btn_row.addWidget(self._btn_import)
        self._btn_draw = QPushButton("Draw Signature…")
        self._btn_draw.clicked.connect(self._draw_signature)
        btn_row.addWidget(self._btn_draw)
        self._btn_delete = QPushButton("Delete Selected")
        self._btn_delete.clicked.connect(self._delete_signature)
        btn_row.addWidget(self._btn_delete)
        layout.addLayout(btn_row)

        # Scale
        sh = QHBoxLayout()
        sh.addWidget(QLabel("Scale:"))
        self._scale_spin = QSpinBox()
        self._scale_spin.setRange(10, 500)
        self._scale_spin.setValue(100)
        self._scale_spin.setSuffix("%")
        sh.addWidget(self._scale_spin)
        layout.addLayout(sh)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _refresh_signatures(self):
        self._sig_list.clear()
        d = _get_signature_dir()
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".svg")):
                self._sig_list.addItem(f)

    def _import_signature(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Signature Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All (*)"
        )
        if path:
            dest = os.path.join(_get_signature_dir(), os.path.basename(path))
            shutil.copy2(path, dest)
            self._refresh_signatures()

    def _draw_signature(self):
        """Open a small white canvas dialog where the user draws a signature."""
        draw_dlg = _SignatureDrawDialog(self)
        if draw_dlg.exec_() == QDialog.Accepted:
            self._refresh_signatures()

    def _delete_signature(self):
        item = self._sig_list.currentItem()
        if not item:
            return
        path = os.path.join(_get_signature_dir(), item.text())
        if os.path.isfile(path):
            os.remove(path)
        self._refresh_signatures()

    def get_config(self):
        item = self._sig_list.currentItem()
        sig_file = os.path.join(_get_signature_dir(), item.text()) if item else None
        return {
            "signature_file": sig_file,
            "scale": self._scale_spin.value() / 100.0,
        }


class _SignatureDrawDialog(QDialog):
    """A small canvas for freehand signature drawing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Draw Signature")
        self.setFixedSize(500, 250)
        layout = QVBoxLayout(self)

        self._scene = QGraphicsScene(0, 0, 480, 180, self)
        self._scene.setBackgroundBrush(QBrush(Qt.white))
        self._gview = QGraphicsView(self._scene)
        self._gview.setRenderHint(QPainter.Antialiasing)
        layout.addWidget(self._gview)

        self._drawing = False
        self._path = None
        self._path_item = None
        self._pen = QPen(Qt.black, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

        self._gview.viewport().installEventFilter(self)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear)
        btn_row.addWidget(btn_clear)
        btn_save = QPushButton("Save Signature")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def eventFilter(self, obj, event):
        if obj == self._gview.viewport():
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                pos = self._gview.mapToScene(event.pos())
                self._drawing = True
                self._path = QPainterPath(pos)
                self._path_item = self._scene.addPath(self._path, self._pen)
                return True
            elif event.type() == QEvent.MouseMove and self._drawing:
                pos = self._gview.mapToScene(event.pos())
                self._path.lineTo(pos)
                self._path_item.setPath(self._path)
                return True
            elif event.type() == QEvent.MouseButtonRelease and self._drawing:
                self._drawing = False
                return True
        return super().eventFilter(obj, event)

    def _clear(self):
        self._scene.clear()
        self._scene.setBackgroundBrush(QBrush(Qt.white))

    def _save(self):
        """Render the scene to a transparent PNG and save."""
        name = f"signature_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(_get_signature_dir(), name)

        # Render to image with transparency
        self._scene.setBackgroundBrush(QBrush(Qt.transparent))
        img = QImage(480, 180, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        self._scene.render(painter)
        painter.end()
        img.save(path)
        self.accept()
