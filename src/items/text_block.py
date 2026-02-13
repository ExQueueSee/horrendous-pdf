"""Editable text-block overlay for Edit Text mode."""

import fitz
from PyQt5.QtWidgets import (
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsItem, QMenu,
)
from PyQt5.QtGui import QPen, QColor, QBrush, QFont
from PyQt5.QtCore import Qt, QPointF


class EditableTextBlockItem(QGraphicsRectItem):
    """In-place editable text overlay on a PDF text block.

    Click to start editing directly on the page — no popup dialog.
    Draggable, selectable, supports copy/paste/delete with undo.
    """

    def __init__(self, page_num, rect, original_text, font_size, font_name,
                 color, y_offset, scale, parent=None):
        super().__init__(rect, parent)
        self._page_num = page_num
        self._original_text = original_text
        self._font_size = font_size     # PDF points
        self._font_name = font_name     # PDF font name
        self._text_color = color        # (r, g, b) floats 0-1
        self._y_offset = y_offset       # scene Y offset of the page
        self._scale = scale             # dpi / 72
        self._deleted = False
        self._editing = False
        self._drag_start_pos = None     # for undo on move

        # Visual: white background overlay with dashed border
        self.setPen(QPen(QColor(70, 130, 230, 180), 1.2, Qt.DashLine))
        self.setBrush(QBrush(QColor(255, 255, 255, 200)))
        self.setZValue(20)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.SizeAllCursor)
        self.setFlags(
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemSendsGeometryChanges
        )

        self.setData(0, "edit_text_block")
        self.setToolTip("Click to edit • Drag to move • Right-click for options")

        # In-place editable text item (child)
        self._text_item = QGraphicsTextItem(self)
        self._text_item.setPlainText(original_text)

        # Match the PDF text appearance
        display_font_size = int(max(7, font_size * scale * 0.75))
        font_family = "Arial"
        raw = font_name.lower()
        if "times" in raw or "serif" in raw:
            font_family = "Times New Roman"
        elif "courier" in raw or "mono" in raw:
            font_family = "Courier New"
        fnt = QFont(font_family, display_font_size)
        self._text_item.setFont(fnt)

        # Text colour matching the PDF
        r8 = int(color[0] * 255)
        g8 = int(color[1] * 255)
        b8 = int(color[2] * 255)
        self._text_item.setDefaultTextColor(QColor(r8, g8, b8, 220))

        # Position the text item inside the rect
        self._text_item.setPos(rect.x() + 2, rect.y() + 1)
        self._text_item.setTextWidth(rect.width() - 4)

        # Not editable by default — becomes editable on double-click
        self._text_item.setTextInteractionFlags(Qt.NoTextInteraction)

    # -- public API ---------------------------------------------------------
    def page_num(self):
        return self._page_num

    def set_page_num(self, n):
        self._page_num = n

    def original_text(self):
        return self._original_text

    def current_text(self):
        if self._deleted:
            return ""
        return self._text_item.toPlainText()

    def is_modified(self):
        return self.current_text() != self._original_text or self.pos() != QPointF(0, 0)

    def is_deleted(self):
        return self._deleted

    def font_size_pts(self):
        return self._font_size

    def font_name(self):
        return self._font_name

    def text_color(self):
        return self._text_color

    def pdf_rect(self):
        """Return fitz.Rect in PDF points for this block (accounting for drag)."""
        r = self.rect()
        p = self.pos()  # offset from drag
        s = self._scale
        yo = self._y_offset
        return fitz.Rect(
            (r.x() + p.x()) / s, (r.y() + p.y() - yo) / s,
            (r.x() + p.x() + r.width()) / s, (r.y() + p.y() - yo + r.height()) / s
        )

    def set_current_text(self, text):
        self._text_item.setPlainText(text)
        self._deleted = False
        self._update_visual()

    def mark_deleted(self):
        self._deleted = True
        self._stop_editing()
        self._update_visual()

    def restore_original(self):
        self._deleted = False
        self._text_item.setPlainText(self._original_text)
        self.setPos(0, 0)
        self._update_visual()

    def clone_block(self):
        """Return a serializable dict for copy/paste."""
        return {
            "page_num": self._page_num,
            "rect": (self.rect().x(), self.rect().y(),
                     self.rect().width(), self.rect().height()),
            "text": self.current_text(),
            "font_size": self._font_size,
            "font_name": self._font_name,
            "color": self._text_color,
            "y_offset": self._y_offset,
            "scale": self._scale,
        }

    def _start_editing(self):
        """Enable in-place text editing."""
        if self._deleted or self._editing:
            return
        self._editing = True
        self._text_item.setTextInteractionFlags(Qt.TextEditorInteraction)
        self._text_item.setFocus()
        cursor = self._text_item.textCursor()
        cursor.movePosition(cursor.End)
        self._text_item.setTextCursor(cursor)
        self.setPen(QPen(QColor(50, 150, 250, 255), 2.0, Qt.SolidLine))
        self.setBrush(QBrush(QColor(255, 255, 240, 230)))
        self.setCursor(Qt.IBeamCursor)

    def _stop_editing(self):
        """Disable in-place text editing."""
        if not self._editing:
            return
        self._editing = False
        self._text_item.setTextInteractionFlags(Qt.NoTextInteraction)
        self._text_item.clearFocus()
        self.setCursor(Qt.SizeAllCursor)
        self._update_visual()

    def _update_visual(self):
        if self._deleted:
            self.setPen(QPen(QColor(230, 70, 70, 200), 1.5, Qt.DashLine))
            self.setBrush(QBrush(QColor(230, 70, 70, 40)))
            self._text_item.setPlainText("[DELETED]")
            self._text_item.setDefaultTextColor(QColor(200, 50, 50, 180))
        elif self.is_modified():
            self.setPen(QPen(QColor(50, 180, 50, 200), 1.5, Qt.DashLine))
            self.setBrush(QBrush(QColor(255, 255, 255, 200)))
            r8 = int(self._text_color[0] * 255)
            g8 = int(self._text_color[1] * 255)
            b8 = int(self._text_color[2] * 255)
            self._text_item.setDefaultTextColor(QColor(r8, g8, b8, 220))
        else:
            self.setPen(QPen(QColor(70, 130, 230, 180), 1.2, Qt.DashLine))
            self.setBrush(QBrush(QColor(255, 255, 255, 200)))
            r8 = int(self._text_color[0] * 255)
            g8 = int(self._text_color[1] * 255)
            b8 = int(self._text_color[2] * 255)
            self._text_item.setDefaultTextColor(QColor(r8, g8, b8, 220))
        self.setToolTip(self.current_text()[:200] if not self._deleted else "[Deleted]")

    # -- hover feedback -----------------------------------------------------
    def hoverEnterEvent(self, event):
        if not self._deleted and not self._editing:
            self.setBrush(QBrush(QColor(230, 240, 255, 220)))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if not self._editing:
            self._update_visual()
        super().hoverLeaveEvent(event)

    # -- mouse: single click = select/drag, double-click = edit text --------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._deleted:
            self._drag_start_pos = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_start_pos is not None:
            if self.pos() != self._drag_start_pos:
                # Push move to undo
                self._push_edit_undo("move", {
                    "item": self,
                    "old_pos": self._drag_start_pos,
                    "new_pos": QPointF(self.pos()),
                })
            self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and not self._deleted:
            # Stop editing on other blocks
            scene = self.scene()
            if scene:
                for item in scene.items():
                    if isinstance(item, EditableTextBlockItem) and item is not self:
                        item._stop_editing()
            self._start_editing()
        event.accept()

    def _push_edit_undo(self, action, data):
        """Find the PDFGraphicsView and push to the edit undo stack."""
        scene = self.scene()
        if scene:
            # Late import to avoid circular dependency
            from src.graphics_view import PDFGraphicsView
            for view in scene.views():
                if isinstance(view, PDFGraphicsView):
                    view.push_edit_undo(action, data)
                    return

    # -- context menu -------------------------------------------------------
    def contextMenuEvent(self, event):
        self._stop_editing()
        menu = QMenu()
        act_copy = menu.addAction("Copy")
        if not self._deleted:
            act_delete = menu.addAction("Delete")
        else:
            act_delete = None
        act_restore = menu.addAction("Restore Original")
        act_restore.setEnabled(self.is_modified() or self._deleted)
        chosen = menu.exec_(event.screenPos())
        if chosen == act_copy:
            self._push_edit_undo("copy", {"item": self})
        elif chosen == act_delete and act_delete is not None:
            old_text = self.current_text()
            self.mark_deleted()
            self._push_edit_undo("delete_text", {
                "item": self, "old_text": old_text,
            })
        elif chosen == act_restore:
            old_text = self.current_text()
            old_pos = QPointF(self.pos())
            was_deleted = self._deleted
            self.restore_original()
            self._push_edit_undo("restore", {
                "item": self, "old_text": old_text,
                "old_pos": old_pos, "was_deleted": was_deleted,
            })
        event.accept()
