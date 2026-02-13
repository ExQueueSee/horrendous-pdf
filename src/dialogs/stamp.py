"""Stamp dialog (preset text stamps + custom image stamps)."""

import os
import shutil

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QGroupBox,
    QListWidget, QSpinBox, QLabel, QPushButton, QDialogButtonBox,
    QFileDialog,
)

from .helpers import STAMP_PRESETS, _get_stamp_dir


class StampDialog(QDialog):
    """Dialog to choose a preset or custom image stamp."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Stamp")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        # Tabs: Preset | Custom
        self._rb_preset = QCheckBox("Preset Stamp")
        self._rb_preset.setChecked(True)
        self._rb_custom = QCheckBox("Custom Image Stamp")
        self._rb_preset.toggled.connect(lambda c: self._rb_custom.setChecked(not c) if c else None)
        self._rb_custom.toggled.connect(lambda c: self._rb_preset.setChecked(not c) if c else None)
        th = QHBoxLayout()
        th.addWidget(self._rb_preset)
        th.addWidget(self._rb_custom)
        layout.addLayout(th)

        # Preset list
        self._preset_group = QGroupBox("Preset Stamps")
        pg_layout = QVBoxLayout(self._preset_group)
        self._preset_list = QListWidget()
        for p in STAMP_PRESETS:
            self._preset_list.addItem(p["text"])
        self._preset_list.setCurrentRow(0)
        pg_layout.addWidget(self._preset_list)

        self._stamp_size = QSpinBox()
        self._stamp_size.setRange(20, 120)
        self._stamp_size.setValue(40)
        self._stamp_size.setPrefix("Font Size: ")
        pg_layout.addWidget(self._stamp_size)

        self._rotation_spin = QSpinBox()
        self._rotation_spin.setRange(-90, 90)
        self._rotation_spin.setValue(-20)
        self._rotation_spin.setSuffix("°")
        rh = QHBoxLayout()
        rh.addWidget(QLabel("Rotation:"))
        rh.addWidget(self._rotation_spin)
        pg_layout.addLayout(rh)

        layout.addWidget(self._preset_group)

        # Custom stamp area
        self._custom_group = QGroupBox("Custom Image Stamp")
        cl = QVBoxLayout(self._custom_group)
        self._custom_list = QListWidget()
        self._refresh_custom_stamps()
        cl.addWidget(self._custom_list)

        btn_row = QHBoxLayout()
        self._btn_import = QPushButton("Import Stamp Image…")
        self._btn_import.clicked.connect(self._import_stamp)
        btn_row.addWidget(self._btn_import)
        self._btn_delete = QPushButton("Delete Selected")
        self._btn_delete.clicked.connect(self._delete_stamp)
        btn_row.addWidget(self._btn_delete)
        cl.addLayout(btn_row)

        self._custom_scale = QSpinBox()
        self._custom_scale.setRange(10, 500)
        self._custom_scale.setValue(100)
        self._custom_scale.setSuffix("%")
        sh = QHBoxLayout()
        sh.addWidget(QLabel("Scale:"))
        sh.addWidget(self._custom_scale)
        cl.addLayout(sh)

        layout.addWidget(self._custom_group)
        self._custom_group.setVisible(False)

        self._rb_preset.toggled.connect(lambda c: self._preset_group.setVisible(c))
        self._rb_preset.toggled.connect(lambda c: self._custom_group.setVisible(not c))

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _refresh_custom_stamps(self):
        self._custom_list.clear()
        d = _get_stamp_dir()
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".svg")):
                self._custom_list.addItem(f)

    def _import_stamp(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Stamp Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.svg);;All (*)"
        )
        if path:
            dest = os.path.join(_get_stamp_dir(), os.path.basename(path))
            shutil.copy2(path, dest)
            self._refresh_custom_stamps()

    def _delete_stamp(self):
        item = self._custom_list.currentItem()
        if not item:
            return
        path = os.path.join(_get_stamp_dir(), item.text())
        if os.path.isfile(path):
            os.remove(path)
        self._refresh_custom_stamps()

    def get_config(self):
        is_preset = self._rb_preset.isChecked()
        preset_idx = self._preset_list.currentRow() if is_preset else -1
        custom_name = self._custom_list.currentItem().text() if (
            not is_preset and self._custom_list.currentItem()) else None
        return {
            "type": "preset" if is_preset else "custom",
            "preset_index": preset_idx,
            "font_size": self._stamp_size.value(),
            "rotation": self._rotation_spin.value(),
            "custom_file": os.path.join(_get_stamp_dir(), custom_name) if custom_name else None,
            "custom_scale": self._custom_scale.value() / 100.0,
        }
