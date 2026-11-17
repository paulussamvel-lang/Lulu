"""Topic → benchmark analysis → editorial, using the incumbent native controls."""
from copy import deepcopy
from pathlib import Path
import threading

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QScrollArea, QSlider, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..core import creator_workbench as core
from . import theme as T
from .control_foundation import (
    adopt_button, adopt_list_widget, adopt_select_field, adopt_text_area,
    adopt_text_field, build_consumer_page_header,
)


def apply_surface_palette(widget):
    """Keep native tabs and top-level dialogs readable in macOS dark mode."""
    palette = QPalette(widget.palette())
    for role, color in ((QPalette.Window,T.BG), (QPalette.WindowText,T.INK),
                        (QPalette.Base,T.CARD), (QPalette.AlternateBase,T.BG_DEEP),
                        (QPalette.Text,T.INK), (QPalette.Button,T.CARD),
                        (QPalette.ButtonText,T.INK), (QPalette.Highlight,T.TERRA),
                        (QPalette.HighlightedText,T.CARD), (QPalette.PlaceholderText,T.INK_SOFT)):
        palette.setColor(role,QColor(color))
    for role in (QPalette.WindowText,QPalette.Text,QPalette.ButtonText):
        palette.setColor(QPalette.Disabled,role,QColor(T.INK_SOFT))
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)


class CreatorDialog(T.TextScaledDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        apply_surface_palette(self)
        self.setObjectName('creatorDialog')
        self.setStyleSheet(f'QDialog#creatorDialog{{background:{T.BG};color:{T.INK};}} QLabel{{color:{T.INK};}}')


def prompt_text(parent,title,label):
    dialog = CreatorDialog(parent)
    dialog.setWindowTitle(title); dialog.resize(560,180)
    layout = QVBoxLayout(dialog)
    note = QLabel(label); note.setWordWrap(True); layout.addWidget(note)
    value = field(label); layout.addWidget(value)
    actions = QHBoxLayout(); actions.addStretch()
    actions.addWidget(button('取消',dialog.reject))
    confirm = button('确定',dialog.accept,True); confirm.setDefault(True)
    actions.addWidget(confirm); layout.addLayout(actions)
    value.returnPressed.connect(dialog.accept); value.setFocus()
    accepted = dialog.exec() == QDialog.Accepted
    return value.text(), accepted


def prompt_item(parent,title,label,items):
    dialog = CreatorDialog(parent)
    dialog.setWindowTitle(title); dialog.resize(600,180)
    layout = QVBoxLayout(dialog)
    note = QLabel(label); note.setWordWrap(True); layout.addWidget(note)
    value = combo(label,items); layout.addWidget(value)
    actions = QHBoxLayout(); actions.addStretch()
    actions.addWidget(button('取消',dialog.reject))
    confirm = button('确定',dialog.accept,True); confirm.setDefault(True)
    actions.addWidget(confirm); layout.addLayout(actions)
    accepted = dialog.exec() == QDialog.Accepted
    return value.currentText(), accepted


def button(text, action, primary=False):
    widget = QPushButton(text)
    adopt_button(widget, role='primary' if primary else 'secondary')
    widget.clicked.connect(action)
    return widget


def field(name, placeholder=''):
    widget = QLineEdit()
    adopt_text_field(widget, accessible_name=name)
    widget.setPlaceholderText(placeholder)
    return widget


def editor(name, placeholder=''):
    widget = QPlainTextEdit()
    adopt_text_area(widget, accessible_name=name)
    widget.setPlaceholderText(placeholder)
    return widget


def combo(name, items):
    widget = QComboBox()
    adopt_select_field(widget, accessible_name=name)
    widget.addItems(items)
    return widget


class ImportWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, loader, value, parent):
        super().__init__(parent); self.loader = loader; self.value = value

    def run(self):
        try:
            self.completed.emit(self.loader(self.value))
        except Exception as exc:
            # HTTP exceptions may carry a private signed URL or response body.
            self.failed.emit(str(exc) if isinstance(exc, ValueError) else
                '读取失败。请检查页面权限、网络和飞书连接；也可导出 TXT / CSV 后导入。')


class AnalysisWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, topic, connection, parent):
        super().__init__(parent)
        self.topic = deepcopy(topic); self.connection = deepcopy(connection)
        self.cancelled = threading.Event()

    def run(self):
        try:
            self.completed.emit(core.assist_analysis(self.topic, self.connection, cancelled=self.cancelled.is_set))
        except Exception as exc:
            self.failed.emit(str(exc) if isinstance(exc, ValueError) else '生成失败，请检查模型连接。原有拆解保留。')


class ImportPreview(CreatorDialog):
    def __init__(self, preview, parent):
        super().__init__(parent)
        self.setWindowTitle('预览收录内容'); self.resize(850, 600)
        self.preview = preview; self.rows = []
        layout = QVBoxLayout(self)
        note = QLabel('仅导入勾选项并保留已识别的筛选状态；相同来源跳过，已有内容不覆盖。')
        note.setWordWrap(True); layout.addWidget(note)
        if preview['kind'] == 'records':
            mapping = QHBoxLayout()
            self.title_column = combo('标题列', preview['fields'])
            self.link_column = combo('来源链接列', ['无链接列', *preview['fields']])
            for names, widget in [(('选题','标题','题目','选题名称','作品标题','title','name'), self.title_column),
                                  (('视频链接','作品链接','链接','来源','url','source'), self.link_column)]:
                for name in names:
                    index = widget.findText(name)
                    if index >= 0: widget.setCurrentIndex(index); break
            mapping.addWidget(QLabel('标题列')); mapping.addWidget(self.title_column, 1)
            mapping.addWidget(QLabel('来源链接列')); mapping.addWidget(self.link_column, 1)
            layout.addLayout(mapping)
            self.title_column.currentIndexChanged.connect(self.refresh)
            self.link_column.currentIndexChanged.connect(self.refresh)
        self.list = QListWidget(); adopt_list_widget(self.list, accessible_name='待导入记录')
        self.list.currentRowChanged.connect(self.show_text)
        layout.addWidget(self.list, 1)
        self.body = editor('导入正文预览'); self.body.setReadOnly(True)
        layout.addWidget(self.body, 1)
        self.notice = QLabel(); self.notice.setWordWrap(True); layout.addWidget(self.notice)
        controls = QHBoxLayout()
        controls.addWidget(button('全选', lambda: self.check_all(True)))
        controls.addWidget(button('全不选', lambda: self.check_all(False)))
        controls.addStretch()
        controls.addWidget(button('取消', self.reject))
        self.accept_button = button('收录勾选项', self.accept, True)
        controls.addWidget(self.accept_button); layout.addLayout(controls)
        self.refresh()

    def refresh(self):
        self.list.clear(); self.body.clear()
        try:
            self.rows = (core.rows_from_records(self.preview['records'],
                title_field=self.title_column.currentText(),
                link_field=self.link_column.currentText() if self.link_column.currentIndex() else '__none__',
                origin=self.preview['origin']) if self.preview['kind'] == 'records' else self.preview['rows'])
            for row in self.rows:
                item = QListWidgetItem(row['title'] + ' · ' + row.get('status', '待筛选')); item.setCheckState(Qt.Checked)
                self.list.addItem(item)
            self.notice.setText(f'读取到 {len(self.rows)} 条。请选择要收录的选题。')
            self.accept_button.setEnabled(bool(self.rows)); self.list.setCurrentRow(0)
        except ValueError as exc:
            self.rows = []; self.notice.setText(str(exc)); self.accept_button.setEnabled(False)

    def show_text(self, index):
        self.body.setPlainText((self.rows[index].get('source', '') + '\n\n' + self.rows[index].get('text', ''))
                               if 0 <= index < len(self.rows) else '')

    def check_all(self, checked):
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def selected_rows(self):
        return [row for i, row in enumerate(self.rows) if self.list.item(i).checkState() == Qt.Checked]


class SegmentDialog(CreatorDialog):
    def __init__(self, position, duration, parent, value=None):
        super().__init__(parent); self.setWindowTitle('标记视频片段'); self.resize(650, 610)
        self.value = value or {}; self.duration = duration
        layout = QVBoxLayout(self); form = QFormLayout(); layout.addLayout(form)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.start = field('片段开始时间'); self.end = field('片段结束时间')
        self.start.setText(core.time_text(self.value.get('start_ms', position)))
        self.end.setText(core.time_text(self.value.get('end_ms', min(position+10000, duration) if duration else position+10000)))
        form.addRow('开始 分:秒', self.start); form.addRow('结束 分:秒', self.end)
        self.role = combo('片段作用', ('开头钩子','提出问题','展开内容','演示','证据','转折过渡','结尾行动'))
        self.role.setCurrentText(self.value.get('role', '开头钩子')); form.addRow('片段作用', self.role)
        self.fields = {}
        for key, name, hint in [('copy','这一段的文案','原话或逐字稿'),
                                ('visual','画面','主体、景别、构图、屏幕内容'),
                                ('edit','剪辑','切点、字幕、节奏、音乐与音效'),
                                ('borrow','可借鉴','这个手法为什么有效，我会怎么用')]:
            item = editor(name, hint); item.setMaximumHeight(80)
            item.setPlainText(self.value.get(key, '')); self.fields[key] = item; form.addRow(name, item)
        self.notice = QLabel(); self.notice.setWordWrap(True); layout.addWidget(self.notice)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(self.save); actions.rejected.connect(self.reject); layout.addWidget(actions)

    def save(self):
        try:
            self.result_value = core.validate_segment(dict(id=self.value.get('id'), start=self.start.text(), end=self.end.text(),
                role=self.role.currentText(), **{k: w.toPlainText() for k, w in self.fields.items()}), self.duration)
            self.accept()
        except ValueError as exc: self.notice.setText(str(exc))


class CreatorWorkbench(QWidget):
    editorial_requested = Signal(str)
    extraction_requested = Signal(str)
    configure_feishu = Signal()

    def __init__(self, parent=None, *, root=None):
        super().__init__(parent)
        apply_surface_palette(self)
        self.setObjectName('creatorWorkbench'); self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f'QWidget#creatorWorkbench{{background:{T.BG};color:{T.INK};}}'
                          f'QTabWidget::pane{{background:{T.BG};border:1px solid {T.LINE};}}'
                          f'QTabBar::tab{{background:{T.BG_DEEP};color:{T.INK};padding:7px 12px;border:1px solid {T.LINE};}}'
                          f'QTabBar::tab:selected{{background:{T.CARD};color:{T.INK};border-bottom:2px solid {T.TERRA};}}')
        self.store = core.CreatorStore(root); self.topic = None; self.saved = None
        self.loading = False; self.worker = None; self.player = None; self.image = None
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(500)
        self.timer.timeout.connect(self.flush)
        layout = QVBoxLayout(self); layout.setContentsMargins(26, 20, 26, 22); layout.setSpacing(12)
        header, _, _ = build_consumer_page_header('选题与拆解', '01 选题收录与筛选   →   02 对标视频拆解   →   03 文案')
        layout.addWidget(header)
        intake = QHBoxLayout()
        intake.addWidget(button('新建选题', self.new_topic, True))
        intake.addWidget(button('导入本地文件', self.import_local))
        intake.addWidget(button('导入网页 / 飞书', self.import_url))
        intake.addWidget(button('导出当前记录', self.export_topic)); intake.addStretch()
        self.intake_row = intake; layout.addLayout(intake)
        split = QSplitter(Qt.Horizontal); split.setChildrenCollapsible(False); layout.addWidget(split, 1)
        left = QWidget(); left.setMinimumWidth(210); ll = QVBoxLayout(left); ll.setContentsMargins(0,0,6,0)
        self.search = field('搜索选题', '搜索标题、标签、来源和内容')
        self.search.textChanged.connect(self.refresh_list); ll.addWidget(self.search)
        self.filter = combo('筛选状态', ('全部状态', *core.STATUSES))
        self.filter.currentIndexChanged.connect(self.refresh_list); ll.addWidget(self.filter)
        self.list = QListWidget(); adopt_list_widget(self.list, accessible_name='选题库')
        self.list.currentItemChanged.connect(self.select_topic); ll.addWidget(self.list, 1)
        self.count = QLabel(); ll.addWidget(self.count); split.addWidget(left)
        self.right = QWidget(); rr = QVBoxLayout(self.right); rr.setContentsMargins(6,0,0,0)
        self.empty = QLabel('从一个具体问题开始\n\n新建选题，或导入已有文件、页面和飞书资料。')
        self.empty.setAlignment(Qt.AlignCenter); self.empty.setWordWrap(True); rr.addWidget(self.empty)
        self.details = QWidget(); dl = QVBoxLayout(self.details); dl.setContentsMargins(0,0,0,0); rr.addWidget(self.details,1)
        self.title = field('选题名称', '给这个选题一个清楚的名称'); dl.addWidget(self.title)
        top = QHBoxLayout(); self.status = combo('选题状态', core.STATUSES)
        self.tags = field('选题标签', '标签，例如：工具实测、效率、入门')
        top.addWidget(self.status); top.addWidget(self.tags,1)
        top.addWidget(button('进入文案精选 →', self.open_editorial, True)); dl.addLayout(top)
        self.tabs = QTabWidget(); self.tabs.setAccessibleName('创作阶段'); dl.addWidget(self.tabs,1)
        self.build_brief(); self.build_analysis(); self.build_sources()
        split.addWidget(self.right); split.setSizes([250, 900]); split.setStretchFactor(1,1)
        self.notice = QLabel('资料保存在本机；网页读取与飞书导入仅在点击后进行。')
        self.notice.setWordWrap(True); layout.addWidget(self.notice)
        for item in (self.title, self.tags): item.textEdited.connect(self.changed)
        self.status.currentIndexChanged.connect(self.changed)
        self.refresh_list()

    def build_brief(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.NoFrame)
        page = QWidget(); form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)
        form.setLabelAlignment(Qt.AlignTop | Qt.AlignLeft)
        form.setContentsMargins(10,16,10,16); form.setSpacing(14)
        self.brief = {}
        hints = ('给谁看？他现在遇到了什么场景？', '一个能用具体场景描述的问题',
                 '看完能做成什么？', '与已有视频相比，我增加什么观点或证据？',
                 '哪些素材能证明结论？哪些信息还需要核实？', '需要的工具、拍摄条件、时间或预算')
        for key, hint in zip(core.BRIEF_FIELDS, hints):
            item = editor(key, hint); item.setMinimumHeight(80); item.setMaximumHeight(120)
            item.textChanged.connect(self.changed); self.brief[key] = item; form.addRow(key, item)
        self.decision = editor('筛选理由', '保留、暂存或不采用的理由；不采用时请填写。')
        self.decision.setMaximumHeight(100); self.decision.textChanged.connect(self.changed)
        form.addRow('筛选理由', self.decision); scroll.setWidget(page)
        self.tabs.addTab(scroll, '01 选题判断')

    def build_analysis(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(10,10,10,10)
        controls = QHBoxLayout(); controls.addWidget(button('关联本地视频', self.attach_media))
        controls.addWidget(button('下载 / 转录参考视频', self.open_extraction))
        controls.addWidget(button('从文稿库关联逐字稿', self.import_transcript))
        controls.addStretch(); layout.addLayout(controls)
        ai_row = QHBoxLayout()
        ai_row.addWidget(button('AI 辅助文字拆解', self.assist_analysis))
        self.cancel_ai = button('取消生成', self.cancel_analysis); self.cancel_ai.setEnabled(False)
        ai_row.addWidget(self.cancel_ai)
        ai_hint = QLabel('基于逐字稿和手工记录，结果先预览；不会上传视频。')
        ai_hint.setWordWrap(True); ai_row.addWidget(ai_hint,1); layout.addLayout(ai_row)
        self.media_label = QLabel('未关联视频。可以先记录文字结构；画面与剪辑请结合实际视频填写。')
        self.media_label.setWordWrap(True); layout.addWidget(self.media_label)
        split = QSplitter(Qt.Vertical); split.setChildrenCollapsible(False); layout.addWidget(split,1)
        upper = QSplitter(Qt.Horizontal); upper.setChildrenCollapsible(False); split.addWidget(upper)
        video = QWidget(); vl = QVBoxLayout(video); vl.setContentsMargins(0,0,8,0)
        self.video = QLabel('本地视频预览\n\n关联已下载的视频，不会复制大文件。')
        self.video.setAlignment(Qt.AlignCenter); self.video.setMinimumSize(220,140)
        self.video.setStyleSheet('background:#172c23;color:#f5f3e9;border-radius:12px;')
        vl.addWidget(self.video,1)
        player_row = QHBoxLayout(); self.play = button('播放', self.toggle_play)
        self.play.setEnabled(False); player_row.addWidget(self.play)
        self.seek = QSlider(Qt.Horizontal); self.seek.setAccessibleName('视频播放进度'); self.seek.setRange(0,0)
        self.seek.sliderMoved.connect(lambda pos: self.player.setPosition(pos) if self.player else None)
        player_row.addWidget(self.seek,1); self.clock = QLabel('00:00 / 00:00'); player_row.addWidget(self.clock)
        vl.addLayout(player_row); upper.addWidget(video)
        summaries = QTabWidget(); summaries.setAccessibleName('六个拆解维度'); self.analysis = {}
        for key, hint in zip(core.DIMENSIONS, ('前几秒用什么引出问题？悬念、结果还是冲突？',
                '按什么顺序讲？每一段起什么作用？', '关键表达、论据、口语节奏与信息密度',
                '人物、景别、构图、演示、素材与字幕', '镜头切换、节奏、转场、字幕、声音与停顿',
                '如何收束观点、兑现承诺、引导下一步？')):
            item = editor(key + '拆解', hint); item.textChanged.connect(self.changed)
            self.analysis[key] = item; summaries.addTab(item,key)
        upper.addWidget(summaries); upper.setSizes([420,480])
        lower = QWidget(); lo = QVBoxLayout(lower); lo.setContentsMargins(0,4,0,0)
        row = QHBoxLayout(); row.addWidget(QLabel('按时间段拆解'))
        row.addStretch(); row.addWidget(button('标记当前片段', self.add_segment))
        row.addWidget(button('修改片段', self.edit_segment)); lo.addLayout(row)
        self.segments = QTableWidget(0,5)
        self.segments.setHorizontalHeaderLabels(('时间段','作用','文案','画面 / 剪辑','可借鉴'))
        self.segments.setAccessibleName('视频分段拆解')
        self.segments.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.segments.setSelectionMode(QAbstractItemView.SingleSelection)
        self.segments.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.segments.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.segments.cellDoubleClicked.connect(self.jump_segment)
        lo.addWidget(self.segments,1); split.addWidget(lower); split.setSizes([340,180])
        self.tabs.addTab(page, '02 视频拆解')

    def build_sources(self):
        page = QWidget(); layout = QVBoxLayout(page)
        self.sources = editor('原始收录资料'); self.sources.setReadOnly(True)
        layout.addWidget(self.sources,2)
        layout.addWidget(QLabel('参考逐字稿 · 可粘贴、修改副本，原文稿保留'))
        self.transcript = editor('参考逐字稿', '粘贴逐字稿，或在视频拆解页从文稿库关联。')
        self.transcript.textChanged.connect(self.changed); layout.addWidget(self.transcript,2)
        layout.addWidget(button('补充参考链接', self.add_source))
        self.tabs.addTab(page, '来源与逐字稿')

    def error(self, text): self.notice.setText(str(text))

    def changed(self, *_):
        if not self.loading and self.topic: self.timer.start()

    def capture(self):
        if not self.topic: return
        self.topic.update(title=self.title.text(), tags=self.tags.text(), status=self.status.currentText(),
            brief={k:w.toPlainText() for k,w in self.brief.items()}, decision=self.decision.toPlainText(),
            analysis={k:w.toPlainText() for k,w in self.analysis.items()}, transcript=self.transcript.toPlainText())

    def flush(self):
        self.timer.stop()
        if self.loading or not self.topic: return True
        self.capture()
        if self.topic == self.saved: return True
        try:
            self.store.save(self.topic); self.saved = deepcopy(self.topic)
            # Qt selects the destination before currentItemChanged is emitted.
            # Publish edits only into the row belonging to the saved topic.
            for row in range(self.list.count()):
                item = self.list.item(row)
                if item.data(Qt.UserRole)['id'] == self.topic['id']:
                    item.setText(self.topic['title'] + '\n' + self.topic['status'])
                    item.setData(Qt.UserRole, deepcopy(self.topic))
                    break
            self.error('已保存到本机。'); return True
        except (OSError, ValueError) as exc:
            self.error(str(exc)); return False

    def refresh_list(self, *_):
        if self.topic and not self.flush(): return
        current = self.topic['id'] if self.topic else ''
        rows = self.store.topics(); term = self.search.text().strip().casefold()
        self.list.blockSignals(True); self.list.clear()
        for topic in rows:
            if self.filter.currentIndex() and topic['status'] != self.filter.currentText(): continue
            if term and term not in str(topic).casefold(): continue
            item = QListWidgetItem(topic['title'] + '\n' + topic['status']); item.setData(Qt.UserRole, topic)
            self.list.addItem(item)
            if topic['id'] == current: self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count(): self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.count.setText(f'显示 {self.list.count()} / 共 {len(rows)} 个选题')
        self.select_topic(self.list.currentItem())

    def select_topic(self, item, previous=None):
        if self.topic and not self.flush():
            self.list.blockSignals(True)
            if previous: self.list.setCurrentItem(previous)
            self.list.blockSignals(False); return
        if self.player: self.player.stop()
        self.loading = True
        self.topic = deepcopy(item.data(Qt.UserRole)) if item else None
        self.saved = deepcopy(self.topic)
        self.details.setVisible(bool(self.topic)); self.empty.setVisible(not self.topic)
        if self.topic:
            self.title.setText(self.topic['title']); self.tags.setText(self.topic['tags'])
            self.status.setCurrentText(self.topic['status']); self.decision.setPlainText(self.topic['decision'])
            for k,w in self.brief.items(): w.setPlainText(self.topic['brief'].get(k,''))
            for k,w in self.analysis.items(): w.setPlainText(self.topic['analysis'].get(k,''))
            self.sources.setPlainText('\n\n'.join(s['title'] + '\n' + s['location'] + '\n' + s['text'] for s in self.topic['sources']))
            self.transcript.setPlainText(self.topic['transcript']); self.render_segments(); self.load_media()
        self.loading = False

    def new_topic(self):
        if not self.flush(): return
        title, ok = prompt_text(self,'新建选题','选题名称')
        if ok and title.strip():
            topic = core.new_topic(title); self.store.save(topic); self.topic = topic; self.saved = deepcopy(topic)
            self.search.clear(); self.filter.setCurrentIndex(0); self.refresh_list()

    def import_local(self):
        path, _ = QFileDialog.getOpenFileName(self,'导入选题或参考资料','', '文本与表格 (*.txt *.md *.csv *.json *.srt *.vtt)')
        if path: self.start_import(core.local_preview,path)

    def import_url(self):
        url, ok = prompt_text(self,'导入网页或飞书资料','普通页面、飞书文档或具体数据表链接（仅读取）')
        if not ok or not url.strip(): return
        try:
            url = core.clean_url(url)
            from urllib.parse import urlsplit
            host = urlsplit(url).hostname
            loader = core.feishu_preview if host.endswith(('.feishu.cn','.larksuite.com')) else core.public_page
            self.start_import(loader,url)
        except ValueError as exc: self.error(str(exc))

    def start_import(self, loader, value):
        if self.is_busy(): self.error('正在读取上一份资料，请等待完成。'); return
        if not self.flush(): return
        self.error('正在读取并准备预览，不会自动导入或回写来源。')
        self.worker = ImportWorker(loader,value,self)
        self.worker.completed.connect(self.preview_import); self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.import_finished); self.worker.start()

    def import_finished(self):
        worker = self.sender()
        if worker: worker.deleteLater()
        self.worker = None
        self.cancel_ai.setEnabled(False)

    def preview_import(self, preview):
        dialog = ImportPreview(preview,self)
        if dialog.exec() == QDialog.Accepted:
            try:
                added, skipped = self.store.import_rows(dialog.selected_rows())
                self.search.clear(); self.filter.setCurrentIndex(0); self.refresh_list()
                self.error(f'已收录 {added} 条；跳过已有来源 {skipped} 条。')
            except (OSError, ValueError) as exc: self.error(str(exc))
        else: self.error('已取消导入。')

    def add_source(self):
        if not self.topic: return
        url, ok = prompt_text(self,'补充参考链接','参考视频或资料页面链接')
        if ok and url.strip():
            try:
                url = core.clean_url(url); key = core.identity(url)
                if any(s['key'] == key for s in self.topic['sources']): raise ValueError('这个来源已在当前选题中。')
                from uuid import uuid4
                self.topic['sources'].append(dict(id=uuid4().hex,title='参考资料',location=url,key=key,text='', imported_at=core.stamp()))
                if self.flush(): self.refresh_list()
            except ValueError as exc: self.error(str(exc))

    def attach_media(self):
        if not self.topic: return
        path, _ = QFileDialog.getOpenFileName(self,'关联本地对标视频','','视频 (*.mp4 *.mov *.mkv *.webm *.m4v *.avi)')
        if path:
            self.topic['media'] = str(Path(path).resolve()); self.flush(); self.load_media()

    def ensure_player(self):
        if self.player: return
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
        self.player = QMediaPlayer(self); self.audio = QAudioOutput(self); self.audio.setVolume(0.5)
        self.player.setAudioOutput(self.audio); self.sink = QVideoSink(self); self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self.render_frame)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.playbackStateChanged.connect(lambda state: self.play.setText('暂停' if state == QMediaPlayer.PlayingState else '播放'))
        self.player.errorOccurred.connect(lambda *_: self.error('视频无法播放，请换用 MP4 / MOV，或重新关联文件。'))

    def load_media(self):
        path = self.topic.get('media', '') if self.topic else ''
        self.image = None; self.video.clear(); self.video.setText('关联本地视频后可播放、定位片段。')
        self.play.setEnabled(False)
        if self.player: self.player.setSource(QUrl())
        if path and Path(path).is_file():
            self.ensure_player(); self.player.setSource(QUrl.fromLocalFile(path)); self.play.setEnabled(True)
            self.media_label.setText(Path(path).name + ' · 关联原文件，不复制')
        elif path: self.media_label.setText('视频已移动或不可读取，请重新关联：' + Path(path).name)
        else: self.media_label.setText('未关联视频；画面与剪辑请结合实际视频填写。')

    def render_frame(self, frame):
        image = frame.toImage()
        if not image.isNull(): self.image = image; self.paint_frame()

    def paint_frame(self):
        if self.image is not None:
            self.video.setPixmap(QPixmap.fromImage(self.image).scaled(self.video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event); self.paint_frame()

    def position_changed(self, value):
        if not self.seek.isSliderDown(): self.seek.setValue(value)
        self.clock.setText(core.time_text(value) + ' / ' + core.time_text(self.player.duration()))

    def duration_changed(self, value):
        self.seek.setRange(0,value); self.position_changed(self.player.position())

    def toggle_play(self):
        if self.player:
            from PySide6.QtMultimedia import QMediaPlayer
            self.player.pause() if self.player.playbackState() == QMediaPlayer.PlayingState else self.player.play()

    def hideEvent(self, event):
        if self.player: self.player.pause()
        self.flush(); super().hideEvent(event)

    def render_segments(self):
        rows = sorted(self.topic['segments'], key=lambda s:s['start_ms'])
        self.segments.setRowCount(len(rows))
        for i,s in enumerate(rows):
            values = (core.time_text(s['start_ms'])+'–'+core.time_text(s['end_ms']), s['role'], s['copy'], s['visual']+' / '+s['edit'], s['borrow'])
            for j,v in enumerate(values):
                item = QTableWidgetItem(v); item.setData(Qt.UserRole,s['id']); item.setToolTip(v)
                self.segments.setItem(i,j,item)

    def add_segment(self): self.segment_dialog()
    def edit_segment(self):
        row = self.segments.currentRow()
        if row < 0: self.error('请先选中一个时间段。'); return
        key = self.segments.item(row,0).data(Qt.UserRole)
        self.segment_dialog(next(s for s in self.topic['segments'] if s['id']==key))

    def segment_dialog(self, value=None):
        if not self.topic: return
        if self.player: self.player.pause()
        dialog = SegmentDialog(self.player.position() if self.player else 0,
                               self.player.duration() if self.player else 0,self,value)
        if dialog.exec() == QDialog.Accepted:
            if value: value.update(dialog.result_value)
            else: self.topic['segments'].append(dialog.result_value)
            self.render_segments(); self.flush()

    def jump_segment(self,row,_column):
        if self.player:
            key = self.segments.item(row,0).data(Qt.UserRole)
            self.player.setPosition(next(s['start_ms'] for s in self.topic['segments'] if s['id']==key))

    def import_transcript(self):
        if not self.topic: return
        from ..core import library
        rows = [r for r in library.list_entries() if r.get('kind') != 'voice']
        if not rows: self.error('文稿库暂无文稿，请先在内容提取中完成转录。'); return
        labels = [f'{i+1}. {r.get("title", "未命名文稿")}' for i,r in enumerate(rows)]
        label, ok = prompt_item(self,'关联逐字稿','选择已完成的文稿',labels)
        if ok:
            record = library.load_text(rows[labels.index(label)]['id'])
            if not record: self.error('这篇文稿已不可读取。'); return
            text = record
            if self.transcript.toPlainText().strip():
                text = self.transcript.toPlainText() + '\n\n' + text
            self.transcript.setPlainText(text); self.flush(); self.error('已追加逐字稿副本，原文稿保留。')

    def open_extraction(self):
        if self.topic:
            source = next((s['location'] for s in self.topic['sources'] if s['location'].startswith(('http://','https://'))),'')
            self.extraction_requested.emit(source)

    def open_editorial(self):
        if self.topic and self.flush(): self.editorial_requested.emit(self.topic['id'])

    def export_topic(self):
        if not self.topic: self.error('请先选择一个选题。'); return
        self.capture()
        path,_ = QFileDialog.getSaveFileName(self,'导出选题与拆解','','Markdown (*.md)')
        if path:
            try: Path(path).write_text(core.topic_markdown(self.topic),encoding='utf-8'); self.error('已导出当前选题与拆解。')
            except OSError: self.error('导出失败，请选择可写的保存位置。')

    def assist_analysis(self):
        if self.is_busy(): self.error('正在读取或生成，请等待完成。'); return
        if not self.topic or not self.flush(): return
        try:
            raw = core.analysis_input(self.topic)
            from ..core.agent_workspace.providers import available_connections
            connections = available_connections()
            if not connections:
                self.error('请先在 AI 大模型中配置一个模型连接。'); return
        except (ValueError, OSError, RuntimeError) as exc:
            self.error(str(exc)); return
        dialog = CreatorDialog(self); dialog.setWindowTitle('发送文字，生成拆解建议'); dialog.resize(620,240)
        layout = QVBoxLayout(dialog)
        models = combo('本次拆解模型', ['请选择模型', *[f'{c.get("label",c["model"])} · {c["model"]}' for c in connections]])
        layout.addWidget(models)
        note = QLabel(f'发送当前逐字稿与拆解记录，约 {len(raw.encode())//1024+1} KB。不会上传视频、访问来源页面或修改原稿。调用所选模型可能产生费用。')
        note.setWordWrap(True); layout.addWidget(note)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Ok).setText('发送文字并生成建议')
        actions.button(QDialogButtonBox.Ok).setEnabled(False)
        models.currentIndexChanged.connect(lambda i:actions.button(QDialogButtonBox.Ok).setEnabled(i>0))
        actions.accepted.connect(dialog.accept); actions.rejected.connect(dialog.reject); layout.addWidget(actions)
        if dialog.exec() != QDialog.Accepted: return
        self.analysis_topic_id = self.topic['id']; self.analysis_fingerprint = raw
        self.worker = AnalysisWorker(self.topic, connections[models.currentIndex()-1], self)
        self.worker.completed.connect(self.preview_analysis); self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.import_finished); self.cancel_ai.setEnabled(True)
        self.error('正在生成文字拆解建议，完成后可预览并决定是否追加。'); self.worker.start()

    def cancel_analysis(self):
        if isinstance(self.worker, AnalysisWorker):
            self.worker.cancelled.set(); self.cancel_ai.setEnabled(False)

    def preview_analysis(self, result):
        if not self.topic or self.topic['id'] != self.analysis_topic_id:
            self.error('当前选题已切换，生成建议未写入。'); return
        self.capture()
        if core.analysis_input(self.topic) != self.analysis_fingerprint:
            self.error('生成期间参考资料已修改，旧建议未写入，请重新生成。'); return
        dialog = CreatorDialog(self); dialog.setWindowTitle('拆解建议预览'); dialog.resize(760,600)
        layout = QVBoxLayout(dialog); text = editor('AI 拆解建议'); text.setReadOnly(True)
        text.setPlainText('\n\n'.join(k+'\n'+result[k] for k in core.DIMENSIONS)); layout.addWidget(text)
        layout.addWidget(QLabel('建议会追加到各维度，保留已有记录。'))
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Ok).setText('追加到拆解记录')
        actions.accepted.connect(dialog.accept); actions.rejected.connect(dialog.reject); layout.addWidget(actions)
        if dialog.exec() == QDialog.Accepted:
            for k,w in self.analysis.items():
                old = w.toPlainText().strip()
                w.setPlainText((old+'\n\n' if old else '')+'【AI 文字建议】\n'+result[k])
            self.flush()

    def is_busy(self): return self.worker is not None and self.worker.isRunning()
