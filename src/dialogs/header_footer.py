"""Header / Footer configuration dialog."""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QGroupBox, QHBoxLayout,
    QSpinBox, QCheckBox, QLabel, QDialogButtonBox, QLineEdit,
)


class HeaderFooterDialog(QDialog):
    """Dialog for adding / updating header and footer text."""

    def __init__(self, total_pages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Header / Footer")
        self.setMinimumWidth(450)
        layout = QVBoxLayout(self)

        # Header
        hdr_group = QGroupBox("Header")
        hl = QFormLayout(hdr_group)
        self._hdr_left = QLineEdit()
        self._hdr_left.setPlaceholderText("Left header text")
        hl.addRow("Left:", self._hdr_left)
        self._hdr_center = QLineEdit()
        self._hdr_center.setPlaceholderText("Center header text")
        hl.addRow("Center:", self._hdr_center)
        self._hdr_right = QLineEdit()
        self._hdr_right.setPlaceholderText("Right header text")
        hl.addRow("Right:", self._hdr_right)
        layout.addWidget(hdr_group)

        # Footer
        ftr_group = QGroupBox("Footer")
        ftl = QFormLayout(ftr_group)
        self._ftr_left = QLineEdit()
        self._ftr_left.setPlaceholderText("Left footer text")
        ftl.addRow("Left:", self._ftr_left)
        self._ftr_center = QLineEdit()
        self._ftr_center.setPlaceholderText("Center footer text")
        ftl.addRow("Center:", self._ftr_center)
        self._ftr_right = QLineEdit()
        self._ftr_right.setPlaceholderText("Right footer text")
        ftl.addRow("Right:", self._ftr_right)
        layout.addWidget(ftr_group)

        # Variables hint
        layout.addWidget(QLabel(
            "<i>Variables: {page} = page number, {total} = total pages, "
            "{date} = today's date</i>"
        ))

        # Options
        opt_group = QGroupBox("Options")
        ol = QFormLayout(opt_group)
        self._font_size = QSpinBox()
        self._font_size.setRange(6, 24)
        self._font_size.setValue(9)
        ol.addRow("Font Size:", self._font_size)
        self._margin_spin = QSpinBox()
        self._margin_spin.setRange(10, 80)
        self._margin_spin.setValue(25)
        self._margin_spin.setSuffix(" pt")
        ol.addRow("Margin:", self._margin_spin)
        layout.addWidget(opt_group)

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
            "header_left": self._hdr_left.text(),
            "header_center": self._hdr_center.text(),
            "header_right": self._hdr_right.text(),
            "footer_left": self._ftr_left.text(),
            "footer_center": self._ftr_center.text(),
            "footer_right": self._ftr_right.text(),
            "font_size": self._font_size.value(),
            "margin": self._margin_spin.value(),
            "page_from": pf,
            "page_to": pt,
            "skip_first": self._skip_first.isChecked(),
        }
