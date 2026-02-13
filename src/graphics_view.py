"""Custom QGraphicsView handling mouse interaction, tools, and text selection."""

import fitz
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsTextItem, QGraphicsPixmapItem, QGraphicsItem,
    QInputDialog, QFileDialog, QMessageBox,
)
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QPainterPath, QPixmap, QTransform,
)
from PyQt5.QtCore import (
    Qt, QRectF, QPointF, QSizeF, pyqtSignal,
)

from src.models.annotation import Annotation
from src.items.sticky_note import StickyNoteItem
from src.items.text_block import EditableTextBlockItem


class PDFGraphicsView(QGraphicsView):
    """Extends QGraphicsView with drawing / annotation / text-selection."""

    annotation_added = pyqtSignal(object)   # emits Annotation
    selection_changed = pyqtSignal(str)     # emits selected text string
    undo_redo_changed = pyqtSignal()        # emits when stacks change
    zoom_changed = pyqtSignal(float)        # emits new zoom factor
    link_clicked = pyqtSignal(dict)         # emits link dict when user clicks a PDF link

    TOOL_NONE = "none"
    TOOL_HIGHLIGHT = "highlight"
    TOOL_NOTE = "note"
    TOOL_PEN = "pen"
    TOOL_TEXT = "text"
    TOOL_RECT = "rectangle"
    TOOL_ERASER = "eraser"
    TOOL_SELECT_TEXT = "select_text"
    TOOL_EDIT_TEXT = "edit_text"
    TOOL_ADD_IMAGE = "add_image"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        self._tool = self.TOOL_NONE
        self._pen_color = QColor(255, 0, 0)
        self._pen_width = 3
        self._highlight_color = QColor(255, 255, 0, 80)
        self._drawing = False
        self._current_path = None
        self._current_path_item = None
        self._start_point = None
        self._temp_rect = None
        self._current_page = 0
        self._zoom = 1.0

        # -- undo / redo ----------------------------------------------------
        self._undo_stack = []
        self._redo_stack = []

        # -- text selection --------------------------------------------------
        self._word_data = []
        self._selecting_text = False
        self._selection_highlight_items = []
        self._selected_word_rects = []
        self._selected_text = ""

        # -- edit mode state --------------------------------------------------
        self._edit_mode = False
        self._edit_text_blocks = []
        self._edit_image_items = []
        self._edit_undo_stack = []
        self._edit_redo_stack = []
        self._edit_clipboard = None

        # -- continuous page layout ------------------------------------------
        self._page_offsets = []
        self._page_heights = []
        self._page_widths = []

    # -- tool setters -------------------------------------------------------
    def set_tool(self, tool):
        self._tool = tool
        if tool == self.TOOL_NONE:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        elif tool == self.TOOL_SELECT_TEXT:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.IBeamCursor)
        elif tool == self.TOOL_EDIT_TEXT:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.IBeamCursor)
        elif tool == self.TOOL_ADD_IMAGE:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            if tool == self.TOOL_PEN:
                self.setCursor(Qt.CrossCursor)
            elif tool == self.TOOL_ERASER:
                self.setCursor(Qt.PointingHandCursor)
            elif tool == self.TOOL_HIGHLIGHT:
                self.setCursor(Qt.CrossCursor)
            elif tool == self.TOOL_NOTE:
                self.setCursor(Qt.PointingHandCursor)
            elif tool == self.TOOL_TEXT:
                self.setCursor(Qt.IBeamCursor)
            elif tool == self.TOOL_RECT:
                self.setCursor(Qt.CrossCursor)
        if tool != self.TOOL_SELECT_TEXT:
            self._clear_text_selection()

    def set_pen_color(self, color):
        self._pen_color = color

    def set_pen_width(self, w):
        self._pen_width = w

    def set_highlight_color(self, color):
        self._highlight_color = color

    # -- page layout helpers ------------------------------------------------
    def set_page_layout(self, offsets, heights, widths):
        self._page_offsets = offsets
        self._page_heights = heights
        self._page_widths = widths

    def page_at_y(self, y):
        for i in range(len(self._page_offsets) - 1, -1, -1):
            if y >= self._page_offsets[i]:
                return i
        return 0

    def current_visible_page(self):
        center = self.mapToScene(self.viewport().rect().center())
        return self.page_at_y(center.y())

    def scroll_to_page(self, page_num):
        if 0 <= page_num < len(self._page_offsets):
            y = self._page_offsets[page_num]
            self.centerOn(QPointF(self.sceneRect().width() / 2, y + self.viewport().height() / (2 * self._zoom)))

    # -- zoom ---------------------------------------------------------------
    def zoom_in(self):
        self._zoom = min(self._zoom * 1.2, 5.0)
        self.setTransform(QTransform.fromScale(self._zoom, self._zoom))
        self.zoom_changed.emit(self._zoom)

    def zoom_out(self):
        self._zoom = max(self._zoom / 1.2, 0.5)
        self.setTransform(QTransform.fromScale(self._zoom, self._zoom))
        self.zoom_changed.emit(self._zoom)

    def zoom_reset(self):
        self._zoom = 1.0
        self.setTransform(QTransform())
        self.zoom_changed.emit(self._zoom)

    def set_zoom(self, factor):
        self._zoom = max(0.5, min(factor, 5.0))
        self.setTransform(QTransform.fromScale(self._zoom, self._zoom))
        self.zoom_changed.emit(self._zoom)

    # -- wheel zoom ---------------------------------------------------------
    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        else:
            super().wheelEvent(event)

    # ======================================================================
    # UNDO / REDO
    # ======================================================================
    def can_undo(self):
        return len(self._undo_stack) > 0

    def can_redo(self):
        return len(self._redo_stack) > 0

    def undo(self):
        if not self._undo_stack:
            return
        entry = self._undo_stack.pop()
        if entry["action"] == "add":
            for item in entry["items"]:
                if item.scene() is not None:
                    item.scene().removeItem(item)
            self._redo_stack.append(entry)
        elif entry["action"] == "remove":
            scene = self.scene()
            if scene:
                for item in entry["items"]:
                    scene.addItem(item)
            self._redo_stack.append(entry)
        self.undo_redo_changed.emit()

    def redo(self):
        if not self._redo_stack:
            return
        entry = self._redo_stack.pop()
        if entry["action"] == "add":
            scene = self.scene()
            if scene:
                for item in entry["items"]:
                    scene.addItem(item)
            self._undo_stack.append(entry)
        elif entry["action"] == "remove":
            for item in entry["items"]:
                if item.scene() is not None:
                    item.scene().removeItem(item)
            self._undo_stack.append(entry)
        self.undo_redo_changed.emit()

    def _push_undo(self, action, items):
        self._undo_stack.append({"action": action, "items": list(items)})
        self._redo_stack.clear()
        self.undo_redo_changed.emit()

    def clear_undo_redo(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.undo_redo_changed.emit()

    # ======================================================================
    # EDIT-MODE UNDO / REDO
    # ======================================================================
    def push_edit_undo(self, action, data):
        self._edit_undo_stack.append({"action": action, "data": data})
        self._edit_redo_stack.clear()
        if action == "copy":
            item = data.get("item")
            if isinstance(item, EditableTextBlockItem):
                self._edit_clipboard = item.clone_block()
            self._edit_undo_stack.pop()

    def edit_undo(self):
        if not self._edit_undo_stack:
            return
        entry = self._edit_undo_stack.pop()
        act = entry["action"]
        d = entry["data"]
        if act == "move":
            item = d["item"]
            item.setPos(d["old_pos"])
            entry["data"] = {"item": item, "old_pos": d["new_pos"], "new_pos": d["old_pos"]}
        elif act == "delete_text":
            item = d["item"]
            item._deleted = False
            item.set_current_text(d["old_text"])
        elif act == "restore":
            item = d["item"]
            if d["was_deleted"]:
                item.mark_deleted()
            else:
                item.set_current_text(d["old_text"])
                item.setPos(d["old_pos"])
        elif act == "paste":
            item = d["item"]
            if item.scene() is not None:
                item.scene().removeItem(item)
            if item in self._edit_text_blocks:
                self._edit_text_blocks.remove(item)
        elif act == "delete_key":
            item = d["item"]
            scene = self.scene()
            if scene and item.scene() is None:
                scene.addItem(item)
            if item not in self._edit_text_blocks:
                self._edit_text_blocks.append(item)
        self._edit_redo_stack.append(entry)

    def edit_redo(self):
        if not self._edit_redo_stack:
            return
        entry = self._edit_redo_stack.pop()
        act = entry["action"]
        d = entry["data"]
        if act == "move":
            item = d["item"]
            item.setPos(d["new_pos"])
            entry["data"] = {"item": item, "old_pos": d["old_pos"], "new_pos": d["new_pos"]}
        elif act == "delete_text":
            item = d["item"]
            item.mark_deleted()
        elif act == "restore":
            item = d["item"]
            item.restore_original()
        elif act == "paste":
            item = d["item"]
            scene = self.scene()
            if scene and item.scene() is None:
                scene.addItem(item)
            if item not in self._edit_text_blocks:
                self._edit_text_blocks.append(item)
        elif act == "delete_key":
            item = d["item"]
            if item.scene() is not None:
                item.scene().removeItem(item)
            if item in self._edit_text_blocks:
                self._edit_text_blocks.remove(item)
        self._edit_undo_stack.append(entry)

    def _clear_edit_undo(self):
        self._edit_undo_stack.clear()
        self._edit_redo_stack.clear()
        self._edit_clipboard = None

    # -- edit mode keyboard shortcuts -----------------------------------------
    def keyPressEvent(self, event):
        if self._edit_mode:
            mods = event.modifiers()
            key = event.key()

            if mods == Qt.ControlModifier and key == Qt.Key_Z:
                self.edit_undo()
                event.accept()
                return
            if (mods == Qt.ControlModifier and key == Qt.Key_Y) or \
               (mods == (Qt.ControlModifier | Qt.ShiftModifier) and key == Qt.Key_Z):
                self.edit_redo()
                event.accept()
                return

            editing_block = None
            for blk in self._edit_text_blocks:
                if blk._editing:
                    editing_block = blk
                    break

            if editing_block:
                super().keyPressEvent(event)
                return

            if mods == Qt.ControlModifier and key == Qt.Key_C:
                for item in self.scene().selectedItems():
                    if isinstance(item, EditableTextBlockItem):
                        self._edit_clipboard = item.clone_block()
                        break
                event.accept()
                return

            if mods == Qt.ControlModifier and key == Qt.Key_V:
                self._paste_block()
                event.accept()
                return

            if key in (Qt.Key_Delete, Qt.Key_Backspace):
                self._delete_selected_blocks()
                event.accept()
                return

        super().keyPressEvent(event)

    def _paste_block(self):
        if not self._edit_clipboard:
            return
        cb = self._edit_clipboard
        rx, ry, rw, rh = cb["rect"]
        offset = 20
        new_rect = QRectF(rx + offset, ry + offset, rw, rh)
        new_item = EditableTextBlockItem(
            cb["page_num"], new_rect, cb["text"],
            cb["font_size"], cb["font_name"],
            cb["color"], cb["y_offset"], cb["scale"]
        )
        scene = self.scene()
        if scene:
            scene.addItem(new_item)
            self._edit_text_blocks.append(new_item)
            self.push_edit_undo("paste", {"item": new_item})

    def _delete_selected_blocks(self):
        scene = self.scene()
        if not scene:
            return
        for item in list(scene.selectedItems()):
            if isinstance(item, EditableTextBlockItem):
                scene.removeItem(item)
                if item in self._edit_text_blocks:
                    self._edit_text_blocks.remove(item)
                self.push_edit_undo("delete_key", {"item": item})

    # ======================================================================
    # TEXT SELECTION
    # ======================================================================
    def set_word_data(self, word_data):
        self._word_data = sorted(
            word_data, key=lambda w: (w[8], w[5], w[6], w[7])
        )
        self._clear_text_selection()

    def _clear_text_selection(self):
        scene = self.scene()
        if scene:
            for item in self._selection_highlight_items:
                if item.scene() is not None:
                    scene.removeItem(item)
        self._selection_highlight_items.clear()
        self._selected_word_rects.clear()
        self._selected_text = ""
        self.selection_changed.emit("")

    def _nearest_word_index(self, pos):
        best_idx = 0
        best_dist = float('inf')
        px, py = pos.x(), pos.y()
        for i, wd in enumerate(self._word_data):
            cx = (wd[0] + wd[2]) / 2
            cy = (wd[1] + wd[3]) / 2
            d = (px - cx) ** 2 + (py - cy) ** 2
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx

    def _update_text_selection_linear(self, start_pos, current_pos):
        scene = self.scene()
        if not scene or not self._word_data:
            return

        for item in self._selection_highlight_items:
            if item.scene() is not None:
                scene.removeItem(item)
        self._selection_highlight_items.clear()
        self._selected_word_rects.clear()

        idx_a = self._nearest_word_index(start_pos)
        idx_b = self._nearest_word_index(current_pos)
        lo, hi = min(idx_a, idx_b), max(idx_a, idx_b)

        selection_color = QColor(51, 153, 255, 80)
        brush = QBrush(selection_color)
        pen = QPen(Qt.NoPen)

        words_text = []
        prev_line = None
        for i in range(lo, hi + 1):
            wd = self._word_data[i]
            x0, y0, x1, y1, word = wd[0], wd[1], wd[2], wd[3], wd[4]
            rect = QRectF(x0, y0, x1 - x0, y1 - y0)
            hi_item = scene.addRect(rect, pen, brush)
            hi_item.setZValue(5)
            hi_item.setData(0, "selection")
            self._selection_highlight_items.append(hi_item)
            self._selected_word_rects.append(rect)

            line_key = (wd[8], wd[5], wd[6])
            if prev_line is not None and prev_line != line_key:
                words_text.append("\n")
            words_text.append(word)
            prev_line = line_key

        self._selected_text = " ".join(words_text).replace(" \n ", "\n")
        self.selection_changed.emit(self._selected_text)

    def get_selected_text(self):
        return self._selected_text

    def get_selected_word_rects(self):
        return list(self._selected_word_rects)

    def highlight_selection(self):
        if not self._selected_word_rects:
            return False

        scene = self.scene()
        if not scene:
            return False

        merged = self._merge_rects_by_line()

        created_items = []
        highlight_brush = QBrush(self._highlight_color)
        for rect in merged:
            hi = scene.addRect(rect, QPen(Qt.NoPen), highlight_brush)
            hi.setZValue(2)
            hi.setData(0, "annotation")
            created_items.append(hi)

        if created_items:
            self._push_undo("add", created_items)
            first_rect = merged[0]
            page = self.page_at_y(first_rect.center().y())
            ann = Annotation(Annotation.HIGHLIGHT, page,
                             color=self._highlight_color.name(),
                             text=self._selected_text[:60])
            self.annotation_added.emit(ann)

        self._clear_text_selection()
        return True

    def _merge_rects_by_line(self):
        if not self._selected_word_rects:
            return []

        rects = sorted(self._selected_word_rects, key=lambda r: (r.top(), r.left()))
        avg_h = sum(r.height() for r in rects) / len(rects) if rects else 10
        tolerance = avg_h * 0.5

        lines = []
        current_line = [rects[0]]
        for r in rects[1:]:
            if abs(r.center().y() - current_line[0].center().y()) < tolerance:
                current_line.append(r)
            else:
                lines.append(current_line)
                current_line = [r]
        lines.append(current_line)

        merged = []
        for line_rects in lines:
            line_rects.sort(key=lambda r: r.left())
            x0 = min(r.left() for r in line_rects)
            y0 = min(r.top() for r in line_rects)
            x1 = max(r.right() for r in line_rects)
            y1 = max(r.bottom() for r in line_rects)
            merged.append(QRectF(x0, y0, x1 - x0, y1 - y0))

        return merged

    # ======================================================================
    # MOUSE EVENTS
    # ======================================================================
    def viewportEvent(self, event):
        from PyQt5.QtCore import QEvent
        if (event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
                and self._tool == self.TOOL_NONE):
            pos = self.mapToScene(event.pos())
            link = self._get_link_at(pos)
            if link:
                self.link_clicked.emit(link)
                event.accept()
                return True
        return super().viewportEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)

        if self._tool == self.TOOL_NONE:
            pos = self.mapToScene(event.pos())
            link = self._get_link_at(pos)
            if link:
                self.link_clicked.emit(link)
                event.accept()
                return
            return super().mousePressEvent(event)

        pos = self.mapToScene(event.pos())

        if self._tool == self.TOOL_SELECT_TEXT:
            self._selecting_text = True
            self._start_point = pos
            self._clear_text_selection()
            return

        if self._tool == self.TOOL_EDIT_TEXT:
            items = self.scene().items(pos)
            for it in items:
                if isinstance(it, EditableTextBlockItem):
                    return super().mousePressEvent(event)
            for blk in self._edit_text_blocks:
                blk._stop_editing()
                blk.setSelected(False)
            return

        if self._tool == self.TOOL_ADD_IMAGE:
            self._add_image_at(pos)
            return

        if self._tool == self.TOOL_PEN:
            self._drawing = True
            self._current_path = QPainterPath(pos)
            pen = QPen(self._pen_color, self._pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            self._current_path_item = self.scene().addPath(self._current_path, pen)
            self._current_path_item.setData(0, "annotation")

        elif self._tool == self.TOOL_HIGHLIGHT:
            self._drawing = True
            self._start_point = pos
            brush = QBrush(self._highlight_color)
            self._temp_rect = self.scene().addRect(QRectF(pos, QSizeF(0, 0)), QPen(Qt.NoPen), brush)
            self._temp_rect.setData(0, "annotation")

        elif self._tool == self.TOOL_RECT:
            self._drawing = True
            self._start_point = pos
            pen = QPen(self._pen_color, self._pen_width)
            self._temp_rect = self.scene().addRect(QRectF(pos, QSizeF(0, 0)), pen)
            self._temp_rect.setData(0, "annotation")

        elif self._tool == self.TOOL_NOTE:
            self._add_sticky_note(pos)

        elif self._tool == self.TOOL_TEXT:
            self._add_text_box(pos)

        elif self._tool == self.TOOL_ERASER:
            self._erase_at(pos)

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.pos())

        if self._tool == self.TOOL_NONE and not self._drawing:
            if not (event.buttons() & Qt.LeftButton):
                link = self._get_link_at(pos)
                if link:
                    self.viewport().setCursor(Qt.PointingHandCursor)
                else:
                    self.viewport().setCursor(Qt.OpenHandCursor)

        if self._selecting_text and self._tool == self.TOOL_SELECT_TEXT:
            self._update_text_selection_linear(self._start_point, pos)
            return

        if not self._drawing:
            return super().mouseMoveEvent(event)

        if self._tool == self.TOOL_PEN and self._current_path is not None:
            self._current_path.lineTo(pos)
            self._current_path_item.setPath(self._current_path)

        elif self._tool in (self.TOOL_HIGHLIGHT, self.TOOL_RECT) and self._temp_rect is not None:
            rect = QRectF(self._start_point, pos).normalized()
            self._temp_rect.setRect(rect)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)

        if self._selecting_text and self._tool == self.TOOL_SELECT_TEXT:
            self._selecting_text = False
            return

        if not self._drawing:
            return super().mouseReleaseEvent(event)

        self._drawing = False

        if self._tool == self.TOOL_PEN:
            self._push_undo("add", [self._current_path_item])
            page = self.current_visible_page()
            ann = Annotation(Annotation.FREEHAND, page,
                             color=self._pen_color.name(), width=self._pen_width)
            self.annotation_added.emit(ann)
            self._current_path = None
            self._current_path_item = None

        elif self._tool == self.TOOL_HIGHLIGHT:
            self._push_undo("add", [self._temp_rect])
            page = self.page_at_y(self._temp_rect.rect().center().y())
            ann = Annotation(Annotation.HIGHLIGHT, page,
                             color=self._highlight_color.name())
            self.annotation_added.emit(ann)
            self._temp_rect = None

        elif self._tool == self.TOOL_RECT:
            self._push_undo("add", [self._temp_rect])
            page = self.page_at_y(self._temp_rect.rect().center().y())
            ann = Annotation(Annotation.RECT, page,
                             color=self._pen_color.name(), width=self._pen_width)
            self.annotation_added.emit(ann)
            self._temp_rect = None

    # -- helpers ------------------------------------------------------------
    def _add_sticky_note(self, pos):
        # Late import to avoid circular dependency
        from src.main_window import PDFEditorWindow
        win = self.parent()
        if isinstance(win, PDFEditorWindow):
            t = win._theme()
        else:
            t = {"note_bg": QColor(255, 235, 59),
                 "note_border": QColor(200, 180, 0)}

        author = ""
        if isinstance(win, PDFEditorWindow):
            author = win._author_name

        text, ok = QInputDialog.getMultiLineText(self, "Add Note", "Enter note text:")
        if ok and text.strip():
            note = StickyNoteItem(
                text=text,
                author=author,
                fill_color=t["note_bg"],
                border_color=t["note_border"],
            )
            note.setPos(pos)
            self.scene().addItem(note)

            self._push_undo("add", [note])
            page = self.page_at_y(pos.y())
            ann = Annotation(Annotation.NOTE, page, text=text)
            self.annotation_added.emit(ann)

    def _add_text_box(self, pos):
        text, ok = QInputDialog.getText(self, "Add Text", "Enter text:")
        if ok and text.strip():
            item = QGraphicsTextItem(text)
            item.setDefaultTextColor(self._pen_color)
            item.setFont(QFont("Arial", 14))
            item.setPos(pos)
            item.setFlags(
                QGraphicsTextItem.ItemIsMovable | QGraphicsTextItem.ItemIsSelectable
            )
            item.setData(0, "annotation")
            self.scene().addItem(item)

            self._push_undo("add", [item])
            page = self.page_at_y(pos.y())
            ann = Annotation(Annotation.TEXT, page, text=text)
            self.annotation_added.emit(ann)

    def _erase_at(self, pos):
        items = self.scene().items(pos)
        for item in items:
            tag = item.data(0)
            if tag in ("annotation", "sticky_note", "edit_image"):
                self.scene().removeItem(item)
                self._push_undo("remove", [item])
                break

    def _add_image_at(self, pos):
        path, _ = QFileDialog.getOpenFileName(
            self, "Add Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.svg);;All Files (*)"
        )
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Error", "Could not load image.")
            return
        max_side = 400
        if pixmap.width() > max_side or pixmap.height() > max_side:
            pixmap = pixmap.scaled(max_side, max_side,
                                  Qt.KeepAspectRatio, Qt.SmoothTransformation)
        item = QGraphicsPixmapItem(pixmap)
        item.setPos(pos)
        item.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable
        )
        item.setData(0, "edit_image")
        item.setData(1, path)
        item.setZValue(10)
        self.scene().addItem(item)
        self._push_undo("add", [item])
        page = self.page_at_y(pos.y())
        ann = Annotation("image", page, path=path)
        self.annotation_added.emit(ann)

    # -- edit mode helpers --------------------------------------------------
    def enter_edit_mode(self, doc, page_offsets, page_heights, dpi):
        if self._edit_mode:
            return
        self._edit_mode = True
        scene = self.scene()
        if not scene or not doc:
            return

        scale = dpi / 72.0
        for page_num in range(len(doc)):
            page = doc[page_num]
            y_off = page_offsets[page_num]

            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            for blk in blocks:
                if blk.get("type") != 0:
                    continue
                lines = blk.get("lines", [])
                if not lines:
                    continue

                full_text = ""
                font_size = 11.0
                font_name = "helv"
                text_color = (0, 0, 0)
                for line in lines:
                    line_text = ""
                    for span in line.get("spans", []):
                        line_text += span.get("text", "")
                        if span.get("size"):
                            font_size = span["size"]
                        if span.get("font"):
                            font_name = span["font"]
                        if span.get("color") is not None:
                            c = span["color"]
                            text_color = (
                                ((c >> 16) & 0xFF) / 255.0,
                                ((c >> 8) & 0xFF) / 255.0,
                                (c & 0xFF) / 255.0,
                            )
                    full_text += line_text + "\n"
                full_text = full_text.rstrip("\n")
                if not full_text.strip():
                    continue

                bbox = blk["bbox"]
                sr = QRectF(
                    bbox[0] * scale, bbox[1] * scale + y_off,
                    (bbox[2] - bbox[0]) * scale, (bbox[3] - bbox[1]) * scale
                )

                block_item = EditableTextBlockItem(
                    page_num, sr, full_text, font_size, font_name,
                    text_color, y_off, scale
                )
                scene.addItem(block_item)
                self._edit_text_blocks.append(block_item)

    def exit_edit_mode(self):
        if not self._edit_mode:
            return
        self._edit_mode = False
        scene = self.scene()
        if scene:
            for item in self._edit_text_blocks:
                if item.scene() is not None:
                    scene.removeItem(item)
            for item in self._edit_image_items:
                if item.scene() is not None:
                    scene.removeItem(item)
        self._edit_text_blocks.clear()
        self._edit_image_items.clear()
        self._clear_edit_undo()

    def _get_link_at(self, scene_pos):
        if not self._page_offsets:
            return None
        page_num = self.page_at_y(scene_pos.y())
        if page_num < 0:
            return None
        mw = self.window()
        if hasattr(mw, '_doc') and mw._doc:
            doc = mw._doc
            if page_num >= len(doc):
                return None
            page = doc[page_num]
            y_off = self._page_offsets[page_num]
            dpi = getattr(mw, '_dpi', 150)
            scale = dpi / 72.0
            pdf_x = scene_pos.x() / scale
            pdf_y = (scene_pos.y() - y_off) / scale
            pdf_point = fitz.Point(pdf_x, pdf_y)
            for link in page.get_links():
                link_rect = link.get("from", fitz.Rect())
                if link_rect.contains(pdf_point):
                    link["_page_num"] = page_num
                    return link
        return None

    def get_text_edits(self):
        return [b for b in self._edit_text_blocks
                if b.is_modified() or b.is_deleted()]
