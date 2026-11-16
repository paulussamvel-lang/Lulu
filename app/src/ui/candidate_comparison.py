"""Simultaneous, selectable candidate copies for the editorial workspace."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .control_foundation import adopt_button, adopt_text_area


class CandidatePane(QWidget):
    edit_requested = Signal(str)
    clip_requested = Signal(str, str)

    def __init__(self, candidate_id, parent=None):
        super().__init__(parent)
        self.candidate_id = candidate_id
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName('sectionTitle')
        self.title.setWordWrap(True)
        self.title.setFixedHeight(48)
        layout.addWidget(self.title)
        self.source = QLabel()
        self.source.setObjectName('muted')
        self.source.setWordWrap(True)
        self.source.setFixedHeight(36)
        layout.addWidget(self.source)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        adopt_text_area(self.body)
        layout.addWidget(self.body, 1)
        self.score = QLabel()
        self.score.setObjectName('muted')
        layout.addWidget(self.score)
        actions = QHBoxLayout()
        self.clip_button = QPushButton('选段加入精选')
        adopt_button(self.clip_button)
        self.clip_button.setEnabled(False)
        self.clip_button.clicked.connect(self._clip)
        self.body.copyAvailable.connect(self.clip_button.setEnabled)
        actions.addWidget(self.clip_button)
        self.edit_button = QPushButton('编辑这篇')
        adopt_button(self.edit_button)
        self.edit_button.clicked.connect(lambda: self.edit_requested.emit(self.candidate_id))
        actions.addWidget(self.edit_button)
        layout.addLayout(actions)

    def update_candidate(self, candidate, review=None, *, stale=False):
        title = candidate['title'] or '未命名文案'
        self.title.setText(title)
        self.title.setToolTip(title)
        source = candidate.get('source') or '手动输入'
        self.source.setText('来源：' + source)
        self.source.setToolTip(source)
        self.body.setAccessibleName('对比正文 · ' + title)
        self.clip_button.setAccessibleName('选段加入精选 · ' + title)
        self.edit_button.setAccessibleName('编辑这篇 · ' + title)
        # Do not reset an unchanged document: preserve the reader's selection
        # and independent scroll position when another candidate changes.
        if self.body.toPlainText() != candidate['text']:
            scroll = self.body.verticalScrollBar().value()
            self.body.setPlainText(candidate['text'])
            self.body.verticalScrollBar().setValue(scroll)
        result = next((r for r in (review or {}).get('documents', [])
                       if r['id'] == self.candidate_id), None)
        text = f'整体分：{result["score"]}/100' if result else '未评分'
        if result and stale:
            text += ' · 上次结果，文案或勾选已变化'
        self.score.setText(text)

    def _clip(self):
        # Qt's selectedText uses paragraph separators; keep multiline excerpts.
        text = self.body.textCursor().selectedText().replace('\u2029', '\n')
        self.clip_requested.emit(self.candidate_id, text)


class CandidateComparison(QWidget):
    edit_requested = Signal(str)
    clip_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.panes = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.hint = QLabel()
        self.hint.setObjectName('muted')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.empty = QLabel('先从左侧选入并勾选至少两篇文案，即可并排比较全文。')
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty, 1)
        self.scroll = QScrollArea()
        self.scroll.setAccessibleName('文案并排对比，横向滚动查看更多')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.columns = QHBoxLayout(self.content)
        self.columns.setContentsMargins(0, 0, 0, 0)
        self.columns.setSpacing(16)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

    def set_project(self, project):
        from ..core import content_workbench as core
        candidates = [c for c in project['candidates'] if c.get('selected', True)]
        keys = [c['id'] for c in candidates]
        for key in list(self.panes):
            if key not in keys:
                pane = self.panes.pop(key)
                self.columns.removeWidget(pane)
                pane.hide()
                pane.deleteLater()
        review = project.get('review')
        try:
            stale = bool(review and core.review_hash(project) != review['input_hash'])
        except ValueError:
            stale = True
        for index, candidate in enumerate(candidates):
            key = candidate['id']
            if key not in self.panes:
                pane = CandidatePane(key, self.content)
                pane.edit_requested.connect(self.edit_requested.emit)
                pane.clip_requested.connect(self.clip_requested.emit)
                self.panes[key] = pane
            pane = self.panes[key]
            if self.columns.indexOf(pane) != index:
                self.columns.insertWidget(index, pane, 1)
            pane.update_candidate(candidate, review, stale=stale)
        count = len(candidates)
        self.empty.setVisible(not count)
        self.scroll.setVisible(bool(count))
        self.content.setMinimumWidth(320 * count + 16 * max(0, count - 1))
        if count == 1:
            text = '已显示 1 篇；再勾选一篇，即可并排对比。'
        elif count:
            text = f'已并排显示 {count} 篇 · 各篇可独立滚动、选段；横向滚动查看更多。'
        else:
            text = '勾选后自动显示全文，无需逐篇打开。'
        if count > 8:
            text += ' AI 评分每次最多 8 篇，请减少勾选后再评分。'
        self.hint.setText(text)
