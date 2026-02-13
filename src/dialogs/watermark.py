"""Watermark configuration dialog."""

import os

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QGroupBox,
    QCheckBox, QComboBox, QSpinBox, QSlider, QLabel, QPushButton,
    QDialogButtonBox, QColorDialog, QFileDialog, QLineEdit,
)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt


class WatermarkDialog(QDialog):
    """Dialog for configuring a text or image watermark."""

    def __init__(self, total_pages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Watermark")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        # --- Type selector ---
        type_group = QGroupBox("Watermark Type")
        type_layout = QHBoxLayout(type_group)
        self._rb_text = QCheckBox("Text")
        self._rb_text.setChecked(True)
        self._rb_image = QCheckBox("Image")
        self._rb_text.toggled.connect(lambda c: self._rb_image.setChecked(not c) if c else None)
        self._rb_image.toggled.connect(lambda c: self._rb_text.setChecked(not c) if c else None)
        type_layout.addWidget(self._rb_text)
        type_layout.addWidget(self._rb_image)
        layout.addWidget(type_group)

        # --- Text options ---
        self._text_group = QGroupBox("Text Options")
        tl = QFormLayout(self._text_group)
        self._txt_input = QLineEdit("CONFIDENTIAL")
        tl.addRow("Text:", self._txt_input)

        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 200)
        self._font_size_spin.setValue(60)
        tl.addRow("Font Size:", self._font_size_spin)

        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(5, 100)
        self._opacity_slider.setValue(30)
        self._opacity_label = QLabel("30%")
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_label.setText(f"{v}%")
        )
        oh = QHBoxLayout()
        oh.addWidget(self._opacity_slider)
        oh.addWidget(self._opacity_label)
        tl.addRow("Opacity:", oh)

        self._rotation_spin = QSpinBox()
        self._rotation_spin.setRange(-90, 90)
        self._rotation_spin.setValue(-45)
        self._rotation_spin.setSuffix("°")
        tl.addRow("Rotation:", self._rotation_spin)

        self._color_btn = QPushButton("Gray")
        self._color_btn.setStyleSheet("background:#888; color:#fff; padding:4px 12px;")
        self._wm_color = QColor(128, 128, 128)
        self._color_btn.clicked.connect(self._pick_color)
        tl.addRow("Color:", self._color_btn)
        layout.addWidget(self._text_group)

        # --- Image options ---
        self._img_group = QGroupBox("Image Options")
        il = QFormLayout(self._img_group)
        self._img_path_label = QLabel("(none selected)")
        self._img_btn = QPushButton("Choose Image…")
        self._img_btn.clicked.connect(self._pick_image)
        ih = QHBoxLayout()
        ih.addWidget(self._img_path_label)
        ih.addWidget(self._img_btn)
        il.addRow("Image:", ih)

        self._img_opacity = QSlider(Qt.Horizontal)
        self._img_opacity.setRange(5, 100)
        self._img_opacity.setValue(30)
        self._img_opacity_label = QLabel("30%")
        self._img_opacity.valueChanged.connect(
            lambda v: self._img_opacity_label.setText(f"{v}%")
        )
        ioh = QHBoxLayout()
        ioh.addWidget(self._img_opacity)
        ioh.addWidget(self._img_opacity_label)
        il.addRow("Opacity:", ioh)

        self._img_scale_spin = QSpinBox()
        self._img_scale_spin.setRange(10, 300)
        self._img_scale_spin.setValue(100)
        self._img_scale_spin.setSuffix("%")
        il.addRow("Scale:", self._img_scale_spin)
        layout.addWidget(self._img_group)
        self._img_group.setVisible(False)
        self._img_path = None

        self._rb_text.toggled.connect(lambda c: self._text_group.setVisible(c))
        self._rb_text.toggled.connect(lambda c: self._img_group.setVisible(not c))

        # --- Page range ---
        pr_group = QGroupBox("Page Range")
        prl = QHBoxLayout(pr_group)
        self._all_pages_cb = QCheckBox("All Pages")
        self._all_pages_cb.setChecked(True)
        prl.addWidget(self._all_pages_cb)
        prl.addWidget(QLabel("From:"))
        self._from_spin = QSpinBox()
        self._from_spin.setRange(1, total_pages)
        self._from_spin.setValue(1)
        prl.addWidget(self._from_spin)
        prl.addWidget(QLabel("To:"))
        self._to_spin = QSpinBox()
        self._to_spin.setRange(1, total_pages)
        self._to_spin.setValue(total_pages)
        prl.addWidget(self._to_spin)
        self._all_pages_cb.toggled.connect(lambda c: self._from_spin.setEnabled(not c))
        self._all_pages_cb.toggled.connect(lambda c: self._to_spin.setEnabled(not c))
        self._from_spin.setEnabled(False)
        self._to_spin.setEnabled(False)
        layout.addWidget(pr_group)

        # --- Position ---
        pos_group = QGroupBox("Position")
        pl = QHBoxLayout(pos_group)
        self._pos_combo = QComboBox()
        self._pos_combo.addItems(["Center", "Top Left", "Top Right",
                                  "Bottom Left", "Bottom Right"])
        pl.addWidget(QLabel("Position:"))
        pl.addWidget(self._pos_combo)
        layout.addWidget(pos_group)

        # --- Buttons ---
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _pick_color(self):
        color = QColorDialog.getColor(self._wm_color, self, "Watermark Color")
        if color.isValid():
            self._wm_color = color
            self._color_btn.setText(color.name())
            self._color_btn.setStyleSheet(
                f"background:{color.name()}; color:#fff; padding:4px 12px;"
            )

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Watermark Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.svg);;All (*)"
        )
        if path:
            self._img_path = path
            self._img_path_label.setText(os.path.basename(path))

    def get_config(self):
        """Return a dict with all watermark settings."""
        is_text = self._rb_text.isChecked()
        if self._all_pages_cb.isChecked():
            page_from, page_to = None, None
        else:
            page_from = self._from_spin.value() - 1  # 0-based
            page_to = self._to_spin.value() - 1
        return {
            "type": "text" if is_text else "image",
            "text": self._txt_input.text() if is_text else "",
            "font_size": self._font_size_spin.value(),
            "opacity": self._opacity_slider.value() / 100.0 if is_text else self._img_opacity.value() / 100.0,
            "rotation": self._rotation_spin.value(),
            "color": (self._wm_color.redF(), self._wm_color.greenF(), self._wm_color.blueF()),
            "image_path": self._img_path,
            "image_scale": self._img_scale_spin.value() / 100.0,
            "page_from": page_from,
            "page_to": page_to,
            "position": self._pos_combo.currentText(),
        }
