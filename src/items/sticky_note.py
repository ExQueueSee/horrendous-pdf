"""Sticky-note icon item (standard PDF 'Text' annotation icon)."""

from PyQt5.QtWidgets import (
    QGraphicsPolygonItem, QGraphicsLineItem, QGraphicsItem,
    QMenu, QDialog, QVBoxLayout, QLabel, QTextEdit, QDialogButtonBox,
)
from PyQt5.QtGui import QPen, QColor, QBrush, QPolygonF
from PyQt5.QtCore import Qt, QPointF


class StickyNoteItem(QGraphicsPolygonItem):
    """A small speech-bubble icon representing a PDF Text (sticky-note) annotation.

    Behaviour mirrors classic PDF editors:
    * Click to place a small coloured icon on the page.
    * Hover to see the note text as a tooltip.
    * Double-click to edit the note text.
    * Saved as a standard PDF Text annotation (interoperable with Acrobat
      / PDFgear / Foxit / etc.).
    """

    ICON_SIZE = 22  # px side-length of the icon

    def __init__(self, text="", author="", parent=None,
                 fill_color=None, border_color=None):
        # Build a small "folded-corner page" polygon
        s = self.ICON_SIZE
        fold = s * 0.3
        poly = QPolygonF([
            QPointF(0, 0),
            QPointF(s - fold, 0),
            QPointF(s, fold),
            QPointF(s, s),
            QPointF(0, s),
        ])
        super().__init__(poly, parent)

        self._note_text = text
        self._author = author

        fill = fill_color or QColor(255, 235, 59)       # Material Yellow-500
        border = border_color or QColor(200, 180, 0)
        self.setPen(QPen(border, 1.2))
        self.setBrush(QBrush(fill))

        # Fold-line (child, moves with parent)
        fold_line = QGraphicsLineItem(s - fold, 0, s - fold, fold, self)
        fold_line.setPen(QPen(border, 0.8))
        fold_top = QGraphicsLineItem(s - fold, fold, s, fold, self)
        fold_top.setPen(QPen(border, 0.8))

        self.setZValue(15)
        self.setAcceptHoverEvents(True)
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemIsFocusable
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setData(0, "sticky_note")   # tag for save logic
        self.setData(1, text)            # store note text

        self.setToolTip(self._build_tooltip())

    # -- public API ---------------------------------------------------------
    def note_text(self):
        return self._note_text

    def set_note_text(self, text):
        self._note_text = text
        self.setData(1, text)
        self.setToolTip(self._build_tooltip())

    def author(self):
        return self._author

    def set_author(self, author):
        self._author = author
        self.setToolTip(self._build_tooltip())

    def update_theme(self, fill_color, border_color):
        """Re-colour the icon to match the active theme."""
        self.setPen(QPen(border_color, 1.2))
        self.setBrush(QBrush(fill_color))
        # Update fold lines (children)
        for child in self.childItems():
            if isinstance(child, QGraphicsLineItem):
                child.setPen(QPen(border_color, 0.8))

    # -- tooltip ------------------------------------------------------------
    def _build_tooltip(self):
        parts = []
        if self._author:
            parts.append(f"<b>{self._author}</b>")
        if self._note_text:
            escaped = self._note_text.replace("&", "&amp;").replace("<", "&lt;")
            escaped = escaped.replace("\n", "<br>")
            parts.append(escaped)
        return "<br>".join(parts) if parts else "(empty note)"

    # -- double-click = edit ------------------------------------------------
    def mouseDoubleClickEvent(self, event):
        self._open_edit_dialog()
        event.accept()

    # -- right-click = context menu with Edit / Delete ----------------------
    def contextMenuEvent(self, event):
        menu = QMenu()
        act_edit = menu.addAction("Edit Note")
        act_delete = menu.addAction("Delete Note")
        chosen = menu.exec_(event.screenPos())
        if chosen == act_edit:
            self._open_edit_dialog()
        elif chosen == act_delete:
            self._delete_self()
        event.accept()

    # -- Delete key ---------------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_self()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _open_edit_dialog(self):
        dlg = QDialog()
        dlg.setWindowTitle("Edit Note")
        layout = QVBoxLayout(dlg)
        edit = QTextEdit()
        edit.setPlainText(self._note_text)
        layout.addWidget(QLabel("Note text:"))
        layout.addWidget(edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.resize(350, 200)
        if dlg.exec_() == QDialog.Accepted:
            self.set_note_text(edit.toPlainText())

    def _delete_self(self):
        """Remove this note from the scene, registering an undoable action."""
        scene = self.scene()
        if scene is None:
            return
        # Late import to avoid circular dependency
        from src.graphics_view import PDFGraphicsView
        for view in scene.views():
            if isinstance(view, PDFGraphicsView):
                scene.removeItem(self)
                view._push_undo("remove", [self])
                return
        # Fallback: no view found, just remove
        scene.removeItem(self)
