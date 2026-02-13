"""Dialog for adding / updating page numbers."""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QGroupBox, QHBoxLayout,
    QComboBox, QSpinBox, QCheckBox, QLabel, QDialogButtonBox,
)


class PageNumberDialog(QDialog):
    """Dialog for adding / updating page numbers."""

    def __init__(self, total_pages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Page Numbers")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)

        # Format
        fmt_group = QGroupBox("Format")
        fl = QFormLayout(fmt_group)
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems([
            "{n}",                      # 1
            "Page {n}",                 # Page 1
            "Page {n} of {total}",      # Page 1 of 10
            "{n} / {total}",            # 1 / 10
            "- {n} -",                  # - 1 -
        ])
        fl.addRow("Format:", self._fmt_combo)

        self._start_num = QSpinBox()
        self._start_num.setRange(1, 9999)
        self._start_num.setValue(1)
        fl.addRow("Start Number:", self._start_num)

        self._font_size = QSpinBox()
        self._font_size.setRange(6, 36)
        self._font_size.setValue(10)
        fl.addRow("Font Size:", self._font_size)
        layout.addWidget(fmt_group)

        # Position
        pos_group = QGroupBox("Position")
        pl = QFormLayout(pos_group)
        self._pos_combo = QComboBox()
        self._pos_combo.addItems([
            "Bottom Center", "Bottom Left", "Bottom Right",
            "Top Center", "Top Left", "Top Right",
        ])
        pl.addRow("Position:", self._pos_combo)

        self._margin_spin = QSpinBox()
        self._margin_spin.setRange(10, 100)
        self._margin_spin.setValue(30)
        self._margin_spin.setSuffix(" pt")
        pl.addRow("Margin:", self._margin_spin)
        layout.addWidget(pos_group)

        # Page range
        pr_group = QGroupBox("Page Range")
        prl = QHBoxLayout(pr_group)
        self._all_cb = QCheckBox("All Pages")
        self._all_cb.setChecked(True)
        prl.addWidget(self._all_cb)
        prl.addWidget(QLabel("From:"))
        self._from_spin = QSpinBox()
        self._from_spin.setRange(1, total_pages)
        self._from_spin.setValue(1)
        self._from_spin.setEnabled(False)
        prl.addWidget(self._from_spin)
        prl.addWidget(QLabel("To:"))
        self._to_spin = QSpinBox()
        self._to_spin.setRange(1, total_pages)
        self._to_spin.setValue(total_pages)
        self._to_spin.setEnabled(False)
        prl.addWidget(self._to_spin)
        self._all_cb.toggled.connect(lambda c: self._from_spin.setEnabled(not c))
        self._all_cb.toggled.connect(lambda c: self._to_spin.setEnabled(not c))
        layout.addWidget(pr_group)

        # Skip first page
        self._skip_first = QCheckBox("Skip first page")
        layout.addWidget(self._skip_first)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_config(self):
        if self._all_cb.isChecked():
            pf, pt = None, None
        else:
            pf = self._from_spin.value() - 1
            pt = self._to_spin.value() - 1
        return {
            "format": self._fmt_combo.currentText(),
            "start_num": self._start_num.value(),
            "font_size": self._font_size.value(),
            "position": self._pos_combo.currentText(),
            "margin": self._margin_spin.value(),
            "page_from": pf,
            "page_to": pt,
            "skip_first": self._skip_first.isChecked(),
        }
