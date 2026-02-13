"""Dialog to create a URL or internal-page link annotation."""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QRadioButton, QGroupBox, QLineEdit,
    QSpinBox, QLabel, QPushButton, QDialogButtonBox, QColorDialog,
)
from PyQt5.QtGui import QColor


class LinkDialog(QDialog):
    """Dialog to create a URL or internal-page link annotation."""

    def __init__(self, total_pages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Link")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)

        # Type
        self._rb_url = QRadioButton("URL (external link)")
        self._rb_url.setChecked(True)
        self._rb_page = QRadioButton("Go to page (internal link)")
        layout.addWidget(self._rb_url)
        layout.addWidget(self._rb_page)

        # URL input
        self._url_group = QGroupBox("URL")
        ug = QVBoxLayout(self._url_group)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://example.com")
        ug.addWidget(self._url_edit)
        layout.addWidget(self._url_group)

        # Page target
        self._page_group = QGroupBox("Target Page")
        pg = QVBoxLayout(self._page_group)
        self._page_spin = QSpinBox()
        self._page_spin.setRange(1, max(total_pages, 1))
        self._page_spin.setValue(1)
        pg.addWidget(self._page_spin)
        layout.addWidget(self._page_group)
        self._page_group.setVisible(False)

        self._rb_url.toggled.connect(lambda c: self._url_group.setVisible(c))
        self._rb_url.toggled.connect(lambda c: self._page_group.setVisible(not c))

        # Display text / appearance
        layout.addWidget(QLabel(
            "After clicking OK, drag a rectangle on the page\n"
            "to define the clickable link area."
        ))

        # Border color
        self._border_color_btn = QPushButton("Border Color: Blue")
        self._border_color = QColor(0, 0, 200)
        self._border_color_btn.clicked.connect(self._pick_color)
        layout.addWidget(self._border_color_btn)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _pick_color(self):
        c = QColorDialog.getColor(self._border_color, self, "Link Border Color")
        if c.isValid():
            self._border_color = c
            self._border_color_btn.setText(f"Border Color: {c.name()}")

    def get_config(self):
        return {
            "type": "url" if self._rb_url.isChecked() else "page",
            "url": self._url_edit.text().strip(),
            "target_page": self._page_spin.value() - 1,  # 0-based
            "border_color": (
                self._border_color.redF(),
                self._border_color.greenF(),
                self._border_color.blueF(),
            ),
        }
