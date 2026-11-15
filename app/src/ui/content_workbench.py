"""Native editorial workspace; originals are copied and cloud review is explicit."""
from copy import deepcopy
import threading

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from ..core import content_workbench as core
from . import theme as T
from .control_foundation import adopt_button, adopt_list_widget, adopt_select_field, adopt_text_area, adopt_text_field, build_consumer_page_header


class ReviewWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, project, connection, parent):
        super().__init__(parent)
        self.project, self.connection = deepcopy(project), deepcopy(connection)
        self.cancelled = threading.Event()

    def run(self):
        try:
            self.completed.emit(core.run_review(self.project, self.connection, cancelled=self.cancelled.is_set))
        except Exception as exc:
            self.failed.emit(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else '评分未完成，原稿与上次结果保留。')


class ContentWorkbench(QWidget):
    configure_models = Signal()
    library_changed = Signal()

    def __init__(self, parent=None, *, root=None, connection_reader=None):
        super().__init__(parent)
        self.setObjectName('contentWorkbench')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f'QWidget#contentWorkbench{{background:{T.BG};color:{T.INK};}}')
        self.store = core.WorkbenchStore(root)
        self.state = self.store.load()
        self.project = self.candidate = None
        self.worker = None
        self.loading = False
        self.connections = []
        self.connection_reader = connection_reader
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(450)
        self.save_timer.timeout.connect(self.flush)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(26, 20, 26, 22)
        root_layout.setSpacing(14)
        header, _, _ = build_consumer_page_header('文案精选', '原文对比 · 挑选片段 · 组稿')
        root_layout.addWidget(header)
        top = QHBoxLayout()
        self.projects = QComboBox()
        self.projects.setAccessibleName('选题')
        adopt_select_field(self.projects, accessible_name='选题')
        self.projects.currentIndexChanged.connect(self._switch_project)
        top.addWidget(self.projects, 1)
        top.addWidget(self._button('新建选题', self._new_project))
        top.addWidget(self._button('修改选题名', self._rename_project))
        top.addWidget(self._button('导入拾句', self._import_shiju))
        root_layout.addLayout(top)
        self.audience = QLineEdit()
        self.audience.setPlaceholderText('目标观众，例如：第一次接触 AI 工具的创作者')
        self.audience.setAccessibleName('目标观众')
        adopt_text_field(self.audience, accessible_name='目标观众')
        self.audience.textEdited.connect(self._audience_changed)
        root_layout.addWidget(self.audience)
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        self.splitter = split
        root_layout.addWidget(split, 1)

        left, layout = self._column('候选文案', '勾选本次对比的 1–8 篇')
        split.addWidget(left)
        self.candidates = QListWidget()
        self.candidates.setAccessibleName('候选文案列表')
        adopt_list_widget(self.candidates, accessible_name='候选文案列表')
        self.candidates.currentRowChanged.connect(self._switch_candidate)
        self.candidates.itemChanged.connect(self._selection_changed)
        layout.addWidget(self.candidates, 1)
        layout.addWidget(self._button('从文稿库选入', self._import_library))
        layout.addWidget(self._button('导入 TXT / Markdown', self._import_files))
        layout.addWidget(self._button('粘贴为新文案', self._paste))

        center, layout = self._column('原文与评分', '编辑的是候选副本，原文稿保留')
        split.addWidget(center)
        self.title = QLineEdit()
        self.title.setPlaceholderText('候选文案标题')
        self.title.setAccessibleName('候选文案标题')
        adopt_text_field(self.title, accessible_name='候选文案标题')
        self.title.textEdited.connect(self._candidate_changed)
        layout.addWidget(self.title)
        self.source = QLabel('')
        self.source.setWordWrap(True)
        self.source.setObjectName('muted')
        layout.addWidget(self.source)
        self.original = QPlainTextEdit()
        self.original.setPlaceholderText('从左侧选入文稿，或粘贴一篇文案。')
        self.original.setAccessibleName('候选文案正文')
        adopt_text_area(self.original)
        self.original.textChanged.connect(self._candidate_changed)
        layout.addWidget(self.original, 3)
        layout.addWidget(self._button('将选中文字加入精选', self._add_clip))
        self.review_view = QPlainTextEdit()
        self.review_view.setReadOnly(True)
        self.review_view.setPlaceholderText('评分会给出同题比较、整体分数及关键段落建议。')
        self.review_view.setAccessibleName('文案评分与段落建议')
        adopt_text_area(self.review_view)
        layout.addWidget(self.review_view, 2)

        right, layout = self._column('精选与组稿', '拖动片段排序，组稿后可继续编辑')
        split.addWidget(right)
        self.clips = QListWidget()
        self.clips.setAccessibleName('精选片段，支持拖动排序')
        adopt_list_widget(self.clips, accessible_name='精选片段，支持拖动排序')
        self.clips.setDragDropMode(QAbstractItemView.InternalMove)
        self.clips.model().rowsMoved.connect(self._reorder_clips)
        self.clips.itemDoubleClicked.connect(self._locate_clip)
        layout.addWidget(self.clips, 2)
        buttons = QHBoxLayout()
        buttons.addWidget(self._button('移除片段', self._remove_clip))
        buttons.addWidget(self._button('按顺序组稿', self._assemble))
        layout.addLayout(buttons)
        self.draft = QPlainTextEdit()
        self.draft.setPlaceholderText('选入片段后点击“按顺序组稿”，也可以直接写稿。')
        self.draft.setAccessibleName('精选组稿正文')
        adopt_text_area(self.draft)
        self.draft.textChanged.connect(self._draft_changed)
        layout.addWidget(self.draft, 3)
        buttons = QHBoxLayout()
        buttons.addWidget(self._button('复制', lambda: QApplication.clipboard().setText(self.draft.toPlainText())))
        buttons.addWidget(self._button('导出', self._export))
        buttons.addWidget(self._button('上次组稿', self._restore_draft))
        layout.addLayout(buttons)
        layout.addWidget(self._button('另存到文稿库', self._save_to_library))
        split.setSizes([205, 490, 380])
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 2)

        model_row = QHBoxLayout()
        self.family = QComboBox()
        self.family.setAccessibleName('评分模型备选')
        adopt_select_field(self.family, accessible_name='评分模型备选')
        for key, label in core.FAMILIES:
            self.family.addItem(label, key)
        self.family.currentIndexChanged.connect(self._family_changed)
        model_row.addWidget(self.family)
        self.model = QComboBox()
        self.model.setAccessibleName('本次评分使用的已配置模型')
        adopt_select_field(self.model, accessible_name='本次评分使用的已配置模型')
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self._button('模型连接', self.configure_models.emit))
        self.score_button = self._button('发送所选文案并评分', self._score)
        model_row.addWidget(self.score_button)
        self.cancel_button = self._button('取消评分', self._cancel)
        self.cancel_button.setEnabled(False)
        model_row.addWidget(self.cancel_button)
        root_layout.addLayout(model_row)
        self.notice = QLabel('文案与精选保存在本地；点击评分才向所选模型发送勾选的全文。')
        self.notice.setWordWrap(True)
        self.notice.setObjectName('muted')
        root_layout.addWidget(self.notice)
        if not self.state['projects']:
            self.state['projects'].append(core.new_project())
            self.store.save(self.state)
        self._saved_state = deepcopy(self.state)
        self._refresh_projects()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self._sync_external)
        self.refresh_timer.start()

    @staticmethod
    def _button(text, callback):
        button = QPushButton(text)
        adopt_button(button, accessible_name=text)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _column(title, hint):
        widget, layout = QWidget(), QVBoxLayout()
        widget.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        label = QLabel(title)
        label.setObjectName('sectionTitle')
        layout.addWidget(label)
        sub = QLabel(hint)
        sub.setWordWrap(True)
        sub.setObjectName('muted')
        layout.addWidget(sub)
        return widget, layout

    def _error(self, text):
        self.notice.setText(str(text))

    def flush(self):
        self.save_timer.stop()
        if self.state == self._saved_state:
            return True
        try:
            merged = self.store.save(self.state, base=self._saved_state)
            self._saved_state = deepcopy(self.state)
            if merged:
                self._adopt_state(self.state)
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            self._error(str(exc))
            return False

    def _adopt_state(self, state):
        project_id = self.project['id'] if self.project else None
        candidate_id = self.candidate['id'] if self.candidate else None
        positions = [(editor, editor.textCursor().position(), editor.textCursor().anchor(),
                      editor.verticalScrollBar().value()) for editor in (self.original, self.draft)]
        self.state = state
        self._saved_state = deepcopy(state)
        self.project = self.candidate = None
        index = next((i for i, p in enumerate(state['projects']) if p['id'] == project_id), 0)
        self._refresh_projects(index)
        if candidate_id:
            index = next((i for i, c in enumerate(self.project['candidates']) if c['id'] == candidate_id), 0)
            self.candidates.setCurrentRow(index)
        for editor, position, anchor, scroll in positions:
            cursor = editor.textCursor()
            end = editor.document().characterCount() - 1
            cursor.setPosition(min(anchor, end))
            cursor.setPosition(min(position, end), QTextCursor.KeepAnchor)
            editor.setTextCursor(cursor)
            editor.verticalScrollBar().setValue(scroll)

    def _sync_external(self):
        if not self.isVisible() or self.loading or self.is_busy() or self.state != self._saved_state:
            return
        try:
            state = self.store.load()
            if state['revision'] != self.state['revision']:
                self._adopt_state(state)
        except (OSError, ValueError, RuntimeError) as exc:
            self._error(str(exc))

    def _changed(self):
        if not self.loading:
            self.project['updated_at'] = core.stamp()
            self.save_timer.start()

    def _refresh_projects(self, selected=0):
        self.projects.blockSignals(True)
        self.projects.clear()
        for project in self.state['projects']:
            self.projects.addItem(project['title'], project['id'])
        self.projects.setCurrentIndex(selected)
        self.projects.blockSignals(False)
        self._switch_project(selected)

    def _switch_project(self, index):
        if self.project is not None and not self.flush():
            self.projects.blockSignals(True)
            self.projects.setCurrentIndex(self.projects.findData(self.project['id']))
            self.projects.blockSignals(False)
            return
        self.loading = True
        self.project = self.state['projects'][index]
        self.audience.setText(self.project['audience'])
        self.family.setCurrentIndex(max(0, self.family.findData(self.project.get('family', ''))))
        self.draft.setPlainText(self.project['draft'])
        self.loading = False
        self._refresh_candidates()
        self._refresh_clips()
        self.refresh_connections()

    def _new_project(self):
        title, ok = QInputDialog.getText(self, '新建选题', '选题名称')
        if ok and title.strip():
            if not self.flush(): return
            self.state['projects'].append(core.new_project(title.strip()[:160]))
            self._refresh_projects(len(self.state['projects']) - 1)
            self.flush()

    def _rename_project(self):
        title, ok = QInputDialog.getText(self, '修改选题名', '选题名称', text=self.project['title'])
        if ok and title.strip():
            self.project['title'] = title.strip()[:160]
            self.projects.setItemText(self.projects.currentIndex(), self.project['title'])
            self._changed()

    def _import_shiju(self):
        from pathlib import Path
        import json
        path, _ = QFileDialog.getOpenFileName(self, '导入拾句工作台', '', 'JSON (*.json)')
        if not path: return
        try:
            if Path(path).stat().st_size > 16 * 1024 * 1024:
                raise ValueError('拾句文件超过 16 MB，请先单独导出需要的选题。')
            projects = core.import_shiju(json.loads(Path(path).read_text(encoding='utf-8-sig')))
            known = {p.get('legacy_source_hash') for p in self.state['projects']}
            projects = [p for p in projects if p['legacy_source_hash'] not in known]
            if projects:
                self.state['projects'].extend(projects)
                self._refresh_projects(len(self.state['projects']) - 1)
                if not self.flush(): return
            self._error(f'已导入 {len(projects)} 个选题副本，拾句原数据保留。')
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self._error(str(exc))

    def _refresh_candidates(self, selected=0):
        self.candidates.blockSignals(True)
        self.candidates.clear()
        for candidate in self.project['candidates']:
            item = QListWidgetItem(candidate['title'])
            item.setToolTip(candidate['title'])
            item.setData(Qt.UserRole, candidate['id'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if candidate.get('selected', True) else Qt.Unchecked)
            self.candidates.addItem(item)
        self.candidates.setCurrentRow(selected)
        self.candidates.blockSignals(False)
        self._switch_candidate(selected)

    def _switch_candidate(self, index):
        self.loading = True
        rows = self.project['candidates']
        self.candidate = rows[index] if 0 <= index < len(rows) else None
        self.title.setText(self.candidate['title'] if self.candidate else '')
        self.original.setPlainText(self.candidate['text'] if self.candidate else '')
        self.source.setText(('来源：' + self.candidate['source']) if self.candidate else '')
        self.loading = False
        self._render_review()

    def _candidate_changed(self):
        if self.loading or not self.candidate: return
        self.candidate.update(title=self.title.text(), text=self.original.toPlainText())
        item = self.candidates.currentItem()
        if item: item.setText(self.candidate['title'] or '候选文案')
        self._changed()
        self._render_review()

    def _selection_changed(self, item):
        candidate = next(c for c in self.project['candidates'] if c['id'] == item.data(Qt.UserRole))
        candidate['selected'] = item.checkState() == Qt.Checked
        self._changed()
        self._render_review()

    def _audience_changed(self, text):
        if self.loading: return
        self.project['audience'] = text
        self._changed()

    def _append(self, title, text, **source):
        try:
            core.add_candidate(self.project, title, text, **source)
            self._refresh_candidates(len(self.project['candidates']) - 1)
            self._changed()
        except ValueError as exc:
            self._error(str(exc))

    def _paste(self):
        text = QApplication.clipboard().text()
        self._append('粘贴文案', text)

    def _import_files(self):
        from pathlib import Path
        paths, _ = QFileDialog.getOpenFileNames(self, '导入候选文案', '', '文本 (*.txt *.md)')
        for name in paths:
            try:
                path = Path(name)
                if path.stat().st_size > 1024 * 1024: raise ValueError('文本超过 1 MB。')
                self._append(path.stem, path.read_text(encoding='utf-8-sig'), source=path.name)
            except (OSError, UnicodeError, ValueError) as exc:
                self._error(str(exc))

    def _import_library(self):
        from ..core import library
        try:
            rows = [r for r in library.list_entries() if r.get('kind') != 'voice']
            dialog = QDialog(self)
            dialog.setWindowTitle('选入候选文案')
            dialog.resize(580, 500)
            layout = QVBoxLayout(dialog)
            search, listing = QLineEdit(), QListWidget()
            search.setPlaceholderText('搜索文稿标题')
            search.setAccessibleName('搜索文稿标题')
            listing.setSelectionMode(QAbstractItemView.ExtendedSelection)
            for row in rows:
                item = QListWidgetItem(row.get('title') or '未命名文稿')
                item.setData(Qt.UserRole, row['id'])
                listing.addItem(item)
            search.textChanged.connect(lambda text: [listing.item(i).setHidden(text.casefold() not in listing.item(i).text().casefold()) for i in range(listing.count())])
            layout.addWidget(search)
            layout.addWidget(listing)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() == QDialog.Accepted:
                for item in listing.selectedItems():
                    key = item.data(Qt.UserRole)
                    self._append(item.text(), library.load_text(key), document_id=key, source='文稿库 · ' + item.text())
        except (ValueError, RuntimeError, OSError) as exc:
            self._error(str(exc))

    def _add_clip(self):
        if not self.candidate: return
        try:
            core.add_clip(self.project, self.candidate['id'], self.original.textCursor().selectedText())
            self._refresh_clips()
            self._changed()
        except ValueError as exc: self._error(str(exc))

    def _refresh_clips(self):
        self.clips.blockSignals(True)
        self.clips.clear()
        for clip in self.project['clips']:
            item = QListWidgetItem(clip['text'].replace('\n', ' ')[:100] + '\n来源：' + clip['title'])
            item.setData(Qt.UserRole, clip['id'])
            item.setToolTip(clip['text'] + '\n\n来源：' + clip['title'])
            self.clips.addItem(item)
        self.clips.blockSignals(False)

    def _reorder_clips(self, *_):
        by_id = {c['id']:c for c in self.project['clips']}
        self.project['clips'] = [by_id[self.clips.item(i).data(Qt.UserRole)] for i in range(self.clips.count())]
        self._changed()

    def _remove_clip(self):
        index = self.clips.currentRow()
        if index >= 0:
            self.project['clips'].pop(index)
            self._refresh_clips()
            self._changed()

    def _locate_clip(self, item):
        clip = next(c for c in self.project['clips'] if c['id'] == item.data(Qt.UserRole))
        index = next((i for i,c in enumerate(self.project['candidates']) if c['id'] == clip['candidate_id']), -1)
        if index >= 0:
            self.candidates.setCurrentRow(index)
            self.original.moveCursor(QTextCursor.Start)
            self.original.find(clip['text'])
            if core.digest(self.candidate['text']) != clip['source_hash']:
                self._error('来源副本已修改，精选片段仍保留选入时的文字。')

    def _assemble(self):
        try:
            self.draft.setPlainText(core.assemble(self.project))
            self._changed()
        except ValueError as exc: self._error(str(exc))

    def _draft_changed(self):
        if self.loading: return
        self.project['draft'] = self.draft.toPlainText()
        self._changed()

    def _restore_draft(self):
        history = self.project['draft_history']
        if not history:
            self._error('还没有历史组稿。每次重新组稿会保留之前的稿件。')
            return
        previous = history.pop()
        current = self.project['draft']
        self.draft.setPlainText(previous['text'])
        history.append(dict(at=core.stamp(), text=current))
        self._changed()

    def _export(self):
        from pathlib import Path
        if not self.draft.toPlainText().strip(): return
        path, _ = QFileDialog.getSaveFileName(self, '导出组稿', '精选稿.md', 'Markdown (*.md);;文本 (*.txt)')
        if not path: return
        try:
            body = self.draft.toPlainText()
            if Path(path).suffix.lower() == '.md' and self.project['clips']:
                body += '\n\n---\n\n## 精选片段来源\n\n' + '\n'.join(
                    f'{i+1}. {c["title"]} · 文稿 {c["document_id"] or "手动导入"}' for i,c in enumerate(self.project['clips']))
            Path(path).write_text(body, encoding='utf-8')
            self._error('组稿已导出，原文稿保留。')
        except OSError as exc: self._error(str(exc))

    def _save_to_library(self):
        from ..core import library
        if not self.draft.toPlainText().strip(): return
        try:
            library.save_document(self.draft.toPlainText(), self.project['title'] + ' · 精选稿',
                source='文案精选', meta=dict(content_project=self.project['id'], clip_sources=deepcopy(self.project['clips'])))
            self.library_changed.emit()
            self._error('已另存为文稿库中的新文稿。')
        except (ValueError, RuntimeError, OSError) as exc: self._error(str(exc))

    def _family_changed(self):
        if self.loading or self.project is None: return
        self.project['family'] = self.family.currentData()
        self._changed()
        self.refresh_connections()

    def refresh_connections(self):
        try:
            if self.connection_reader is not None:
                self.connections = self.connection_reader()
            else:
                from ..core.agent_workspace.providers import available_connections
                self.connections = available_connections()
        except (ValueError, RuntimeError, OSError):
            self.connections = []
        self.model.clear()
        self.model.addItem('请选择已配置的模型连接', '')
        family = self.family.currentData()
        aliases = {'doubao': ('doubao', 'volc', 'ark'), 'qwen': ('qwen', 'bailian', 'dashscope'),
                   'gemini': ('gemini', 'google'), 'deepseek': ('deepseek',)}
        for connection in self.connections:
            if family and not any(word in (connection.get('provider', '')+' '+connection.get('model', '')).lower() for word in aliases[family]): continue
            self.model.addItem(f'{connection.get("label", connection["model"])} · {connection["model"]}', connection['id'])

    def _score(self):
        if self.is_busy(): return
        key = self.model.currentData()
        connection = next((c for c in self.connections if c['id'] == key), None)
        if connection is None:
            self._error('请先在“模型连接”配置并选择模型；不会自动选择或调用。')
            return
        try:
            core.review_input(self.project)
        except ValueError as exc:
            self._error(str(exc))
            return
        if not self.flush(): return
        self.worker_project_id = self.project['id']
        self.worker = ReviewWorker(self.project, connection, self)
        self.worker.completed.connect(self._review_completed)
        self.worker.failed.connect(self._error)
        self.worker.finished.connect(self._review_finished)
        self.score_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._error(f'正在向 {connection["model"]} 发送勾选文案并评分…')
        self.worker.start()

    def _review_completed(self, result):
        project = next(p for p in self.state['projects'] if p['id'] == self.worker_project_id)
        try:
            if self.worker.cancelled.is_set() or core.review_hash(project) != result['input_hash']:
                raise ValueError('评分期间原稿或勾选项发生变化，本次结果未覆盖上次评分。')
            project['review'] = result
            if not self.flush(): return
            self._render_review()
            self._error('评分已保存；原文未修改。')
        except ValueError as exc: self._error(str(exc))

    def _review_finished(self):
        self.score_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        worker, self.worker = self.worker, None
        worker.deleteLater()

    def _render_review(self):
        review = self.project.get('review')
        if not review:
            legacy = self.project.get('legacy_topic', {}).get('analysis')
            if legacy and isinstance(legacy, dict):
                import json
                self.review_view.setPlainText('拾句导入时的评分记录，未重新调用模型：\n' + json.dumps(legacy, ensure_ascii=False, indent=2))
            else:
                self.review_view.clear()
            return
        try: stale = core.review_hash(self.project) != review['input_hash']
        except ValueError: stale = True
        lines = [('原文或勾选项已改变，以下为上次评分。\n' if stale else '') + review['comparison'],
                 '模型：' + review['model']]
        if self.candidate:
            item = next((d for d in review['documents'] if d['id'] == self.candidate['id']), None)
            if item:
                lines.extend([f'\n整体分：{item["score"]}/100', item['summary']])
                labels = {'recommend':'可采纳', 'improve':'需优化', 'skip':'不建议用'}
                for mark in item['marks']:
                    lines.append(f'第 {mark["start"]+1}–{mark["end"]+1} 段 · {labels[mark["label"]]}：{mark["reason"]}')
        self.review_view.setPlainText('\n'.join(lines))

    def _cancel(self):
        if self.worker:
            self.worker.cancelled.set()
            self.cancel_button.setEnabled(False)
            self._error('正在停止接收评分；不会自动重发。')

    def is_busy(self):
        return bool(self.worker and self.worker.isRunning())

    def showEvent(self, event):
        if hasattr(self, '_saved_state'):
            self._sync_external()
        self.refresh_connections()
        super().showEvent(event)
