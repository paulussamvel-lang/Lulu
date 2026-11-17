"""Native text selection plus one-click sentence picking, including UTF-16 text."""
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTextEdit

from ..core.content_workbench import sentence_spans
from . import theme as T


class SentenceEditor(QPlainTextEdit):
    sentence_picked = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spans = []
        self._picked = set()
        self._hover = None
        self._press = None
        self.setReadOnly(True)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setToolTip('点击一句加入右侧新文案；拖动可选择任意文字。键盘移动后按回车选句。')

    def setPlainText(self, text):
        super().setPlainText(text)
        self._spans = sentence_spans(text)
        self._hover = None
        self._highlight()

    def set_picked(self, spans):
        self._picked = set(spans)
        self._highlight()

    def _at(self, position):
        text = self.toPlainText()
        # QTextCursor offsets count UTF-16 code units, Python offsets count
        # Unicode code points. Emoji must not shift sentence provenance.
        index = len(text.encode('utf-16-le')[:position*2].decode('utf-16-le', errors='ignore'))
        return next((span for span in self._spans if span[0] <= index < span[1]), None)

    def _under_mouse(self, point):
        cursor = self.cursorForPosition(point)
        if abs(point.y() - self.cursorRect(cursor).center().y()) > self.fontMetrics().height():
            return None
        return self._at(cursor.position())

    def mousePressEvent(self, event):
        self._press = event.position().toPoint() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        point = event.position().toPoint()
        if (event.button() == Qt.LeftButton and event.modifiers() == Qt.NoModifier
                and self._press is not None
                and (point - self._press).manhattanLength() < QApplication.startDragDistance()
                and not self.textCursor().hasSelection()):
            span = self._under_mouse(point)
            if span is not None:
                self.sentence_picked.emit(*span)
        self._press = None

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        span = self._under_mouse(event.position().toPoint())
        if span != self._hover:
            self._hover = span
            self.viewport().setCursor(Qt.PointingHandCursor if span else Qt.IBeamCursor)
            self._highlight()

    def leaveEvent(self, event):
        self._hover = None
        self._highlight()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() == Qt.NoModifier:
            span = self._at(self.textCursor().position())
            if span is not None:
                self.sentence_picked.emit(*span)
                event.accept()
                return
        super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.PaletteChange) and hasattr(self, '_spans'):
            self._highlight()

    def _highlight(self):
        text = self.toPlainText()
        selections = []
        for span in self._picked | ({self._hover} if self._hover else set()):
            if span not in self._spans: continue
            selection = QTextEdit.ExtraSelection()
            cursor = QTextCursor(self.document())
            cursor.setPosition(len(text[:span[0]].encode('utf-16-le')) // 2)
            cursor.setPosition(len(text[:span[1]].encode('utf-16-le')) // 2, QTextCursor.KeepAnchor)
            selection.cursor = cursor
            selection.format.setBackground(QColor(T.TERRA_WASH if span == self._hover else T.BG_DEEP))
            selection.format.setForeground(QColor(T.INK))
            if span in self._picked:
                selection.format.setFontUnderline(True)
                selection.format.setUnderlineColor(QColor(T.TERRA))
            selections.append(selection)
        self.setExtraSelections(selections)
