"""Video production and benchmark analysis using the incumbent native controls."""
from copy import deepcopy
from pathlib import Path
import threading

from PySide6.QtCore import Qt, QSignalBlocker, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..core import creator_workbench as core
from ..core.creator_planning import PRODUCTION_SECTIONS
from ..core.creator_status_sync import SYNC_INTERVAL_MS, TopicStatusSync
from ..core.creator_workflow import COMMERCIAL, STAGES
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


class WorkflowPane(QWidget):
    changed = Signal()

    def __init__(self, stage):
        super().__init__()
        self.stage = stage
        self.records = {}
        self.business = None
        self.active_index = -1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        artifact = QLabel(f'阶段产物 · {stage.artifact}')
        artifact.setWordWrap(True)
        layout.addWidget(artifact)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)
        navigation = QWidget()
        navigation.setMinimumWidth(154)
        nav_layout = QVBoxLayout(navigation)
        nav_layout.setContentsMargins(0, 0, 8, 0)
        self.steps = QListWidget()
        adopt_list_widget(self.steps, accessible_name=f'{stage.title}的步骤')
        self.steps.setWordWrap(True)
        self.steps.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_layout.addWidget(self.steps, 1)
        self.progress = QLabel()
        nav_layout.addWidget(self.progress)
        split.addWidget(navigation)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        split.addWidget(scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([226, 455])
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(8, 0, 6, 2)
        body.setSpacing(8)
        self.title = QLabel()
        title_font = self.title.font()
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.guide = QLabel()
        self.result = QLabel()
        for label in (self.title, self.guide, self.result):
            label.setWordWrap(True)
            body.addWidget(label)

        controls = QHBoxLayout()
        self.complete = QCheckBox('标记本步完成')
        controls.addWidget(self.complete)
        controls.addStretch()
        self.copy_prompt = button('复制提示词与输入', self.copy_current_prompt)
        self.copy_prompt.setVisible(any(step.prompt for step in stage.steps))
        controls.addWidget(self.copy_prompt)
        body.addLayout(controls)

        self.input = editor('输入与依据')
        self.output = editor('本步产物与记录')
        for label_text, widget in (('输入与依据', self.input), ('本步产物与记录', self.output)):
            label = QLabel(label_text)
            label.setBuddy(widget)
            body.addWidget(label)
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            widget.setMinimumHeight(68)
            widget.setProperty('workflowField', True)
            body.addWidget(widget, 1)
            widget.textChanged.connect(self.record_step)
        self.complete.toggled.connect(self.record_step)
        scroll.setWidget(content)
        for _ in stage.steps:
            self.steps.addItem(QListWidgetItem())
        self.steps.currentRowChanged.connect(self.show_step)
        self.steps.setCurrentRow(0)
        self.refresh_step_labels()

    def refresh_step_labels(self):
        completed = 0
        for index, step in enumerate(self.stage.steps):
            done = self.records.get(step.key, {}).get('done', False)
            completed += bool(done)
            item = self.steps.item(index)
            label = f'{index + 1}. {step.title}' + (' · 已完成' if done else '')
            item.setText(label)
            item.setToolTip(label)
        self.progress.setText(f'{completed} / {len(self.stage.steps)} 步完成')

    def load(self, records, business=None):
        self.business = business
        self.records = {
            step.key: deepcopy(records[step.key])
            for step in self.stage.steps if isinstance(records.get(step.key), dict)
        }
        self.refresh_step_labels()
        self.show_step(self.steps.currentRow())

    def show_step(self, index):
        self.active_index = index
        if index < 0:
            return
        step = self.stage.steps[index]
        record = self.records.get(step.key, {})
        self.title.setText(step.title)
        guidance = step.guidance
        if step.key == 'release-learn' and self.business:
            guidance += (f'\n按相同观察窗口核对「{self.business["goal"]}」的假设。'
                         '记录顾虑是否在评论或咨询中得到回答、有哪些证据，以及下一次怎么验证。')
        self.guide.setText(guidance)
        self.result.setText(f'本步产物 · {step.artifact}')
        self.input.setPlaceholderText(step.input_hint)
        self.output.setPlaceholderText(step.output_hint)
        prompt = self.copy_prompt
        prompt.setText('复制提示词与输入')
        prompt.setEnabled(bool(step.prompt))
        with QSignalBlocker(self.input), QSignalBlocker(self.output), QSignalBlocker(self.complete):
            self.input.setPlainText(record.get('input', ''))
            self.output.setPlainText(record.get('output', ''))
            self.complete.setChecked(bool(record.get('done', False)))

    def record_step(self, *_):
        if self.active_index < 0:
            return
        step = self.stage.steps[self.active_index]
        record = dict(self.records.get(step.key, {}), input=self.input.toPlainText(),
                      output=self.output.toPlainText(), done=self.complete.isChecked())
        if record['input'] or record['output'] or record['done'] or len(record) > 3:
            self.records[step.key] = record
        else:
            self.records.pop(step.key, None)
        self.refresh_step_labels()
        self.changed.emit()

    def copy_current_prompt(self):
        if self.active_index >= 0:
            prompt = self.stage.steps[self.active_index].prompt
            if self.input.toPlainText().strip():
                prompt += '\n\n本步输入与依据\n' + self.input.toPlainText()
            QApplication.clipboard().setText(prompt)
            self.copy_prompt.setText('已复制')


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
                item = QListWidgetItem(row['title'] + ' · ' + row.get('status', core.PENDING_STATUS)); item.setCheckState(Qt.Checked)
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
    navigation_changed = Signal()
    tool_requested = Signal(str)

    def __init__(self, parent=None, *, root=None):
        super().__init__(parent)
        apply_surface_palette(self)
        self.setObjectName('creatorWorkbench'); self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f'QWidget#creatorWorkbench{{background:{T.BG};color:{T.INK};}}'
                          f'QTabWidget::pane{{background:{T.BG};border:1px solid {T.LINE};}}'
                          f'QTabBar::tab{{background:{T.BG_DEEP};color:{T.INK};padding:7px 12px;border:1px solid {T.LINE};}}'
                          f'QTabBar::tab:selected{{background:{T.CARD};color:{T.INK};border-bottom:2px solid {T.TERRA};}}'
                          f'QPlainTextEdit[workflowField="true"]{{background:{T.CARD};border:1px solid {T.LINE};border-radius:8px;}}'
                          f'QPlainTextEdit[workflowField="true"]:focus{{border-color:{T.TERRA};}}')
        self.store = core.CreatorStore(root); self.topic = None; self.saved = None
        self.loading = False; self.worker = None; self.player = None; self.image = None
        self.status_sync = TopicStatusSync(self.store)
        self.status_sync_url = self.status_sync.configured_url()
        self.sync_worker = None
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(SYNC_INTERVAL_MS)
        self.sync_timer.timeout.connect(self.start_status_sync)
        self.sync_trigger = QTimer(self)
        self.sync_trigger.setSingleShot(True)
        self.sync_trigger.timeout.connect(self.start_status_sync)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(500)
        self.timer.timeout.connect(self.flush)
        self.list_refresh = QTimer(self)
        self.list_refresh.setSingleShot(True)
        self.list_refresh.timeout.connect(self.refresh_list)
        self.applied_filter = (0, '')
        layout = QVBoxLayout(self); layout.setContentsMargins(26, 20, 26, 22); layout.setSpacing(12)
        header, self.page_heading, self.page_subtitle = build_consumer_page_header(
            '视频制作工作台', '选定左侧项目，记录每个阶段的步骤与产物。')
        layout.addWidget(header)
        self.intake_bar = QWidget()
        intake = QHBoxLayout(self.intake_bar)
        intake.setContentsMargins(0, 0, 0, 0)
        intake.addWidget(button('新建选题', self.new_topic, True))
        local_import = button('导入本地文件', self.import_local)
        web_import = button('导入网页 / 飞书', self.import_url)
        sync = button('同步飞书状态', self.request_status_sync)
        self.intake_tools = (local_import, web_import, sync)
        intake.addWidget(local_import)
        intake.addWidget(web_import)
        intake.addWidget(button('导出当前记录', self.export_topic))
        intake.addStretch()
        intake.addWidget(sync)
        self.intake_row = intake
        layout.addWidget(self.intake_bar)
        split = self.topic_area = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)
        left = QWidget(); left.setMinimumWidth(210); ll = QVBoxLayout(left); ll.setContentsMargins(0,0,6,0)
        self.search = field('搜索选题', '搜索标题、标签、来源和内容')
        self.search.textChanged.connect(self.refresh_list); ll.addWidget(self.search)
        self.filter = combo('按状态筛选', ('全部状态', *core.STATUSES))
        filter_label = QLabel('按状态筛选'); filter_label.setBuddy(self.filter)
        ll.addWidget(filter_label)
        self.filter.currentIndexChanged.connect(self.refresh_list); ll.addWidget(self.filter)
        self.list = QListWidget(); adopt_list_widget(self.list, accessible_name='选题库')
        self.list.currentItemChanged.connect(self.select_topic); ll.addWidget(self.list, 1)
        self.count = QLabel(); ll.addWidget(self.count); split.addWidget(left)
        self.right = QWidget(); rr = QVBoxLayout(self.right); rr.setContentsMargins(6,0,0,0)
        self.empty = QLabel('从一个具体问题开始\n\n新建选题，或导入已有文件、页面和飞书资料。')
        self.empty.setAlignment(Qt.AlignCenter); self.empty.setWordWrap(True)
        self.empty_page = QWidget()
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.addStretch()
        empty_layout.addWidget(self.empty)
        self.empty_brief = QLabel('要拆解商单 Brief，请在左侧选一条选题，或新建选题。')
        self.empty_brief.setAlignment(Qt.AlignCenter)
        self.empty_brief.setWordWrap(True)
        empty_layout.addWidget(self.empty_brief)
        self.empty_business_button = button('展开商业分析', self.open_business)
        empty_layout.addWidget(self.empty_business_button, 0, Qt.AlignHCenter)
        empty_layout.addStretch()
        rr.addWidget(self.empty_page, 1)
        self.business_open = False
        self.planning_section = ''
        from .business_analysis import BusinessAnalysisPane
        from .creator_planning import PlanningPane
        self.business = BusinessAnalysisPane(
            self.store, self.close_business, self.open_business_draft,
            next_stage=lambda: self.open_section('position'))
        self.planning = PlanningPane(
            self.store, self.business.store, self.open_section, self.preview_planned_topic, self.tool_requested.emit)
        layout.addWidget(self.planning, 1)
        self.details = QWidget(); dl = QVBoxLayout(self.details); dl.setContentsMargins(0,0,0,0); rr.addWidget(self.details,1)
        self.title = field('选题名称', '给这个选题一个清楚的名称'); dl.addWidget(self.title)
        plan_row = QHBoxLayout()
        self.plan_label = QLabel()
        self.plan_label.setTextFormat(Qt.PlainText)
        self.plan_label.setWordWrap(True)
        plan_row.addWidget(self.plan_label, 1)
        self.plan_button = button('查看账号定位', self.open_topic_plan)
        plan_row.addWidget(self.plan_button)
        dl.addLayout(plan_row)
        top = QHBoxLayout(); self.status = combo('当前选题状态', core.STATUSES)
        status_label = QLabel('当前选题状态'); status_label.setBuddy(self.status)
        self.tags = field('选题标签', '标签，例如：工具实测、效率、入门')
        top.addWidget(status_label)
        top.addWidget(self.status); top.addWidget(self.tags,1)
        dl.addLayout(top)
        self.production_tabs = QTabWidget()
        self.production_tabs.setAccessibleName('视频制作阶段')
        dl.addWidget(self.production_tabs, 1)
        self.workflow_panes = [WorkflowPane(stage) for stage in (*STAGES, COMMERCIAL)]
        for pane in self.workflow_panes:
            pane.changed.connect(self.changed)
        topics, writing, shooting, editing, releasing, commercial = self.workflow_panes
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName('选题和拆解资料')
        topics_page = QWidget()
        topics_layout = QVBoxLayout(topics_page)
        topics_layout.setContentsMargins(12, 10, 12, 0)
        business_entry = QHBoxLayout()
        business_entry.addWidget(button('展开商业分析', self.open_business))
        self.business_summary = QLabel('适用于有明确产品、客户或增长目标的选题')
        self.business_summary.setWordWrap(True)
        self.business_summary.setTextFormat(Qt.PlainText)
        business_entry.addWidget(self.business_summary, 1)
        topics_layout.addLayout(business_entry)
        topics_layout.addWidget(topics, 1)
        self.tabs.addTab(topics_page, '流程与选题卡')
        self.build_brief(); self.build_analysis(); self.build_sources()
        self.script_tabs = QTabWidget()
        self.script_tabs.setAccessibleName('文案与商单流程')
        self.script_tabs.addTab(writing, '通用文案')
        self.script_tabs.addTab(commercial, COMMERCIAL.title)
        for index, (stage, page) in enumerate(zip(STAGES, (self.tabs, self.script_tabs, shooting, editing, releasing)), 1):
            self.production_tabs.addTab(page, f'{index} {stage.title}')
        rr.addWidget(self.business, 1)
        self.phase_tools = QWidget()
        tools = QHBoxLayout(self.phase_tools)
        tools.setContentsMargins(0, 0, 0, 0)
        self.phase_tool_buttons = {}
        for name, label, action in (
            ('collection', '主页采集', lambda: self.tool_requested.emit('collection')),
            ('extraction', '下载与转录', lambda: self.tool_requested.emit('extraction')),
            ('editorial', '文案精选', self.open_editorial),
            ('voice', '文案配音', lambda: self.tool_requested.emit('voice')),
            ('record_audio', '录音工作区', lambda: self.tool_requested.emit('extraction')),
            ('live', '直播录制', lambda: self.tool_requested.emit('live')),
        ):
            self.phase_tool_buttons[name] = button(label, action)
            tools.addWidget(self.phase_tool_buttons[name])
        self.phase_handoff = QLabel()
        self.phase_handoff.setWordWrap(True)
        tools.addWidget(self.phase_handoff, 1)
        dl.addWidget(self.phase_tools)
        split.addWidget(self.right); split.setSizes([250, 900]); split.setStretchFactor(1,1)
        self.notice = QLabel('资料保存在本机；网页读取与飞书导入仅在点击后进行。')
        self.notice.setWordWrap(True); layout.addWidget(self.notice)
        self.sync_notice = QLabel()
        self.sync_notice.setWordWrap(True)
        self.sync_notice.setVisible(bool(self.status_sync_url))
        layout.addWidget(self.sync_notice)
        for item in (self.title, self.tags): item.textEdited.connect(self.changed)
        self.status.currentIndexChanged.connect(self.changed)
        self.status.activated.connect(self.apply_topic_status)
        self.production_tabs.currentChanged.connect(self.update_navigation)
        self.script_tabs.currentChanged.connect(self.update_navigation)
        self.refresh_list()
        self.update_navigation()

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
        self.tabs.addTab(scroll, '选题判断')

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
        self.tabs.addTab(page, '视频拆解')

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

    def apply_topic_status(self, _index):
        # Choosing the already saved status is also a request to show that group.
        if self.topic and not self.loading and self.flush():
            self.filter.setCurrentText(self.topic['status'])

    def capture(self):
        if not self.topic: return
        self.topic.update(title=self.title.text(), tags=self.tags.text(), status=self.status.currentText(),
            brief={k:w.toPlainText() for k,w in self.brief.items()}, decision=self.decision.toPlainText(),
            analysis={k:w.toPlainText() for k,w in self.analysis.items()}, transcript=self.transcript.toPlainText())
        records = dict(self.topic.get('workflow', {}))
        for pane in self.workflow_panes:
            for step in pane.stage.steps:
                records.pop(step.key, None)
            records.update(pane.records)
        if records or 'workflow' in self.topic:
            self.topic['workflow'] = records

    def flush(self, *, follow_status=True):
        self.timer.stop()
        if self.loading or not self.topic: return True
        self.capture()
        if self.topic == self.saved: return True
        status_changed = self.topic['status'] != self.saved['status']
        try:
            self.store.save(self.topic); self.saved = deepcopy(self.topic)
            if follow_status and status_changed and self.filter.currentText() != self.topic['status']:
                with QSignalBlocker(self.filter):
                    self.filter.setCurrentText(self.topic['status'])
                    self.filter.setToolTip(self.topic['status'])
                self.list_refresh.start(0)
            # Qt selects the destination before currentItemChanged is emitted.
            # Publish edits only into the row belonging to the saved topic.
            for row in range(self.list.count()):
                item = self.list.item(row)
                if item.data(Qt.UserRole)['id'] == self.topic['id']:
                    item.setText(self.topic['title'] + '\n' + self.topic['status'])
                    item.setData(Qt.UserRole, deepcopy(self.topic))
                    if not self.matches_filter(self.topic, self.search.text().strip().casefold()):
                        # Let currentItemChanged finish before replacing its list items.
                        self.list_refresh.start(0)
                    break
            if status_changed and self.status_sync_url:
                self.sync_notice.setText('飞书状态待同步')
                self.sync_trigger.start(400)
            self.error('已保存到本机。'); return True
        except (OSError, ValueError) as exc:
            self.error(str(exc)); return False

    def matches_filter(self, topic, term):
        return (not self.filter.currentIndex() or topic['status'] == self.filter.currentText()) and (
            not term or term in str(topic).casefold())

    def showEvent(self, event):
        super().showEvent(event)
        if self.status_sync_url:
            if not self.sync_timer.isActive():
                self.sync_timer.start()
            self.sync_trigger.start(400)

    def request_status_sync(self):
        if not self.status_sync_url:
            url, ok = prompt_text(self, '同步飞书状态', '粘贴已导入的飞书数据表链接')
            if not ok:
                return
            try:
                self.status_sync.configure(url)
            except ValueError as exc:
                self.error(str(exc))
                return
            self.status_sync_url = self.status_sync.configured_url()
            self.sync_notice.show()
            self.sync_timer.start()
        self.start_status_sync()

    def start_status_sync(self):
        if not self.status_sync_url:
            return
        if self.sync_worker is not None or self.is_busy():
            self.sync_trigger.start(1200)
            return
        if not self.flush():
            self.sync_notice.setText('请先保存当前选题，再同步飞书状态。')
            return
        self.sync_trigger.stop()
        self.sync_notice.setText('正在同步飞书状态…')
        self.sync_worker = ImportWorker(self.status_sync.sync, self.status_sync_url, self)
        self.sync_worker.completed.connect(self.apply_status_sync)
        self.sync_worker.failed.connect(self.sync_notice.setText)
        self.sync_worker.finished.connect(self.finish_status_sync)
        self.sync_worker.start()

    def apply_status_sync(self, result):
        target, changes, conflicts, missing, pushed, unconfirmed = result
        if not self.flush():
            self.sync_notice.setText('请先保存当前选题，再同步飞书状态。')
            return
        try:
            pulled = self.status_sync.apply(target, changes)
        except ValueError as exc:
            self.sync_notice.setText(str(exc))
            return
        if pulled:
            self.refresh_list()
        message = f'飞书状态已检查 · 写回 {pushed} 条 · 更新本机 {pulled} 条'
        if missing:
            message += f' · {missing} 条来源记录找不到'
        if unconfirmed:
            message += f' · {unconfirmed} 条待确认'
        if conflicts:
            by_id = {topic['id']: topic['title'] for topic in self.store.topics()}
            topic_id, local, cloud = conflicts[0]
            message += (f' · {len(conflicts)} 条状态冲突，已保留双方修改。'
                        f'「{by_id.get(topic_id, "选题")}」本机为{local}，飞书为{cloud or "未知状态"}。')
        self.sync_notice.setText(message)

    def finish_status_sync(self):
        self.sync_worker.deleteLater()
        self.sync_worker = None

    def refresh_list(self, *_):
        if not self.flush(follow_status=False):
            index, term = self.applied_filter
            with QSignalBlocker(self.filter), QSignalBlocker(self.search):
                self.filter.setCurrentIndex(index)
                self.filter.setToolTip(self.filter.currentText())
                self.search.setText(term)
            return
        self.list_refresh.stop()
        self.applied_filter = (self.filter.currentIndex(), self.search.text())
        current = self.topic['id'] if self.topic else ''
        rows = self.store.topics(); term = self.search.text().strip().casefold()
        self.list.blockSignals(True); self.list.clear()
        for topic in rows:
            if not self.matches_filter(topic, term): continue
            item = QListWidgetItem(topic['title'] + '\n' + topic['status']); item.setData(Qt.UserRole, topic)
            self.list.addItem(item)
            if topic['id'] == current: self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count(): self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.count.setText(f'显示 {self.list.count()} / 共 {len(rows)} 个选题')
        self.empty.setText('没有符合当前条件的选题' if rows else
                           '从一个具体问题开始\n\n新建选题，或导入已有文件、页面和飞书资料。')
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
        self.business.set_topic(self.topic)
        self.show_work_area()
        link = self.topic.get('business_analysis') if self.topic else None
        self.business_summary.setText(
            f'{link["snapshot"]["product"]} · {link["goal"]} · 版本 {link["card_revision"]}'
            if link else '适用于有明确产品、客户或增长目标的选题')
        for pane in self.workflow_panes:
            pane.load(self.topic.get('workflow', {}) if self.topic else {}, link)
        if self.topic:
            plan = self.topic.get('planning_context')
            if plan:
                self.plan_label.setText(f'来自「{plan["track"]}」第 {plan["revision"]} 版')
            self.plan_label.setVisible(bool(plan))
            self.plan_button.setVisible(bool(plan))
            self.title.setText(self.topic['title']); self.tags.setText(self.topic['tags'])
            self.status.setCurrentText(self.topic['status']); self.decision.setPlainText(self.topic['decision'])
            for k,w in self.brief.items(): w.setPlainText(self.topic['brief'].get(k,''))
            for k,w in self.analysis.items(): w.setPlainText(self.topic['analysis'].get(k,''))
            self.sources.setPlainText('\n\n'.join(s['title'] + '\n' + s['location'] + '\n' + s['text'] for s in self.topic['sources']))
            self.transcript.setPlainText(self.topic['transcript']); self.render_segments(); self.load_media()
        self.loading = False

    def show_work_area(self):
        planning = bool(self.planning_section)
        self.intake_bar.setVisible(not planning)
        self.topic_area.setVisible(not planning)
        self.planning.setVisible(planning)
        self.notice.setVisible(not planning)
        self.sync_notice.setVisible(not planning and bool(self.status_sync_url))
        self.details.setVisible(bool(self.topic) and not self.business_open)
        self.empty_page.setVisible(not self.topic and not self.business_open)
        self.business.setVisible(self.business_open)

    def navigation_section(self):
        if self.planning_section:
            return self.planning_section
        if self.business_open:
            return 'business'
        if (self.production_tabs.currentWidget() is self.script_tabs
                and self.script_tabs.currentWidget() is self.workflow_panes[-1]):
            return 'brief'
        return PRODUCTION_SECTIONS[max(self.production_tabs.currentIndex(), 0)]

    def update_navigation(self, *_):
        section = self.navigation_section()
        briefing = section == 'brief'
        headings = {
            'track': ('候选赛道', '记录具体人群、真实问题、你能提供的帮助和需求依据。'),
            'business': ('商业分析', '查主流产品、成交与交付链路、实际付款者和购买顾虑。'),
            'position': ('账号定位', '用内容调研确定账号方向，按购买进程安排第一批内容。'),
            'brief': ('商单 Brief 拆解', COMMERCIAL.artifact),
        }
        if section in headings:
            title, subtitle = headings[section]
        else:
            phase = STAGES[PRODUCTION_SECTIONS.index(section)]
            title, subtitle = ('文案' if section == 'script' else phase.title), phase.artifact
        self.page_heading.setText(title)
        self.page_heading.setAccessibleName(title)
        self.page_subtitle.setText(subtitle)
        for widget in self.intake_tools:
            widget.setVisible(section == 'workflow')
        aids = {
            'workflow': (('collection', 'extraction'), '待接入 · 跨平台对标与评论采集。记录来源和片段时间码。'),
            'script': (('editorial', 'voice'), '待接入 · 外部文案协作。交接口播、画面与必拍镜头。'),
            'brief': (('editorial',), '待接入 · 外部 Brief 协作。交接原文依据与交付时间。'),
            'shoot': (('record_audio', 'live'), '待接入 · 相机与录屏工具。交接口播、录屏、实拍和备份。'),
            'post': (('extraction', 'voice'), '待接入 · 剪辑、字幕与混音工具。交接可播放预览和返修时间码。'),
            'publish': ((), '待接入 · 封面、发布与平台数据。记录实际链接、版本和一致的观察窗口。'),
        }
        tools, handoff = aids.get(section, ((), ''))
        for name, widget in self.phase_tool_buttons.items():
            widget.setVisible(name in tools)
        self.phase_handoff.setText(handoff)
        self.empty.setVisible(not briefing)
        self.empty_brief.setVisible(briefing)
        self.empty_business_button.setVisible(not briefing)
        self.navigation_changed.emit()

    def open_section(self, section):
        if not self.flush():
            return
        self.planning_section = section if section in ('track', 'position') else ''
        if section == 'business':
            self.open_business(self.planning.read()['business_card_id'])
            return
        self.business_open = False
        if self.planning_section:
            self.planning.set_section(self.planning_section)
        else:
            production = 'script' if section == 'brief' else section
            with QSignalBlocker(self.production_tabs), QSignalBlocker(self.script_tabs):
                self.production_tabs.setCurrentIndex(PRODUCTION_SECTIONS.index(production))
                if production == 'script':
                    self.script_tabs.setCurrentIndex(int(section == 'brief'))
        self.show_work_area()
        self.update_navigation()

    def open_business(self, preferred_card=''):
        if self.flush():
            self.planning_section = ''
            self.business.open(preferred_card)
            self.business_open = True
            self.show_work_area()
            self.update_navigation()

    def open_topic_plan(self):
        plan_id = self.topic['planning_context']['id']
        if self.planning.dirty() and self.planning.plan['id'] != plan_id:
            self.error('先保存或撤回当前的调研修改，再打开这条选题的账号定位。')
            return
        if not self.planning.dirty():
            plans = {record['id']: record for record in self.planning.store.plans()}
            if plan_id not in plans:
                self.error('原账号定位记录不可用，这条选题仍保留了带入的字段和出处。')
                return
            self.planning.load(plans[plan_id])
        self.open_section('position')

    def preview_planned_topic(self, plan):
        from .creator_planning import PlanningDraftDialog

        def commit(topic):
            self.store.save(topic)
            self.reveal_topic(topic['id'])
            self.open_section('workflow')
            self.tabs.setCurrentIndex(1)
            self.error('已创建选题卡，可以开始找对标与验证。')

        PlanningDraftDialog(plan, commit, self).exec()

    def reveal_topic(self, topic_id):
        with QSignalBlocker(self.filter), QSignalBlocker(self.search):
            self.filter.setCurrentIndex(0)
            self.filter.setToolTip(self.filter.currentText())
            self.search.clear()
        self.refresh_list()
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole)['id'] == topic_id:
                self.list.setCurrentRow(row)
                break

    def close_business(self):
        self.business_open = False
        self.show_work_area()
        self.update_navigation()

    def open_business_draft(self, card):
        if not self.flush():
            return
        from .business_analysis import BusinessDraftDialog
        draft = BusinessDraftDialog(card, deepcopy(self.topic), self.save_business_draft, self)
        if draft.exec() == QDialog.Accepted:
            self.business.notice.setText('选题已保存，已关联采用时的产品卡版本。')

    def save_business_draft(self, topic, title, card, goal, fields, selected, evidence):
        from ..core import business_analysis as ba
        creating = topic is None
        updated = ba.adopt_draft(core.new_topic(title) if creating else topic, card, goal, fields, selected, evidence)
        self.store.save(updated)
        if creating or not self.matches_filter(updated, self.search.text().strip().casefold()):
            with QSignalBlocker(self.filter), QSignalBlocker(self.search):
                self.filter.setCurrentIndex(0)
                self.filter.setToolTip(self.filter.currentText())
                self.search.clear()
        self.refresh_list()
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole)['id'] == updated['id']:
                self.list.setCurrentRow(row)
                break

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
            try: Path(path).write_text(core.topic_markdown(self.topic, include_workflow=True),encoding='utf-8'); self.error('已导出当前选题和制作记录。')
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

    def is_busy(self):
        return any(worker is not None and worker.isRunning() for worker in (self.worker, self.sync_worker))
