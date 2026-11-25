"""Shared candidate-track and account-positioning forms."""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from ..core import creator_planning as planning
from .business_analysis import wrapped
from .creator_workbench import CreatorDialog, button, combo, editor, field


class PlanningPane(QWidget):
    def __init__(self, store, business_store, open_section, preview_topic, open_tool):
        super().__init__()
        self.store = planning.PlanningStore(store)
        self.business_store = business_store
        self.plan = planning.new_plan()
        self.inputs = {}
        self.loading = False
        self.section = 'track'

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        picker = QHBoxLayout()
        self.library = combo('调研记录', ())
        self.library.currentIndexChanged.connect(self.choose)
        picker.addWidget(self.library, 1)
        self.new_button = button('新建调研记录', lambda: self.load(planning.new_plan()))
        picker.addWidget(self.new_button)
        layout.addLayout(picker)

        self.direction_hint = wrapped('先用一句话定方向：我想做什么赛道，给正在遇到什么问题的谁看，第一条准备回答什么？')
        layout.addWidget(self.direction_hint)
        self.direction = self.form(planning.DIRECTION_FIELDS)
        layout.addWidget(self.direction, 1)
        self.positioning = QTabWidget()
        self.positioning.setAccessibleName('账号定位内容')
        self.positioning.addTab(self.form(planning.RESEARCH_FIELDS, content_research=True), '内容调研')
        self.positioning.addTab(self.form(planning.POSITION_FIELDS), '账号定位')
        self.positioning.addTab(self.form(planning.SCHEDULE_FIELDS), '首批内容')
        layout.addWidget(self.positioning, 1)

        self.status = wrapped()
        layout.addWidget(self.status)
        tools = QHBoxLayout()
        self.collection = button('主页采集', lambda: open_tool('collection'))
        tools.addWidget(self.collection)
        self.handoff = wrapped()
        tools.addWidget(self.handoff, 1)
        layout.addLayout(tools)
        actions = QHBoxLayout()
        self.discard_button = button('撤回未保存修改', self.reload)
        actions.addWidget(self.discard_button)
        actions.addStretch()
        self.save_button = button('保存调研', self.save)
        actions.addWidget(self.save_button)
        self.next_button = button('下一步：商业分析', lambda: open_section('business'), True)
        actions.addWidget(self.next_button)
        self.draft_button = button('预览并生成选题卡', lambda: preview_topic(self.plan), True)
        actions.addWidget(self.draft_button)
        layout.addLayout(actions)
        self.load(next(iter(self.store.plans()), self.plan))
        self.set_section('track')

    def form(self, fields, *, content_research=False):
        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        if content_research:
            self.products = combo('关联商业分析产品卡', ())
            self.products.currentIndexChanged.connect(self.changed)
            form.addRow('关联产品卡', self.products)
        for key, label, hint in fields:
            if key in ('track', 'audience', 'identity', 'first_topic'):
                widget = field(label, hint)
            else:
                widget = editor(label, hint)
                widget.setProperty('workflowField', True)
                widget.setFixedHeight(76)
            widget.textChanged.connect(self.changed)
            self.inputs[key] = widget
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def set_section(self, section):
        self.section = section
        tracking = section == 'track'
        self.direction_hint.setVisible(tracking)
        self.direction.setVisible(tracking)
        self.positioning.setVisible(not tracking)
        self.next_button.setVisible(tracking)
        self.draft_button.setVisible(not tracking)
        self.collection.setVisible(not tracking)
        self.handoff.setText('待接入 · 行业资料检索。交接市场样本和需求依据。' if tracking else
                             '待接入 · 跨平台内容调研。交接主页、视频链接和片段时间码。')
        self.refresh_choices(card_id=self.products.currentData() or '')
        self.changed()

    def refresh_choices(self, *, card_id=None):
        self.plans = {value['id']: value for value in self.store.plans()}
        with QSignalBlocker(self.library), QSignalBlocker(self.products):
            self.library.clear()
            self.library.addItem('未保存的调研记录')
            for value in self.plans.values():
                self.library.addItem(value['track'], value['id'])
            self.library.setCurrentIndex(max(0, self.library.findData(self.plan['id'])))
            self.products.clear()
            self.products.addItem('暂未关联产品卡', '')
            for card in self.business_store.cards():
                self.products.addItem(card['product'], card['id'])
            if card_id is None:
                card_id = self.plan['business_card_id']
            if card_id and self.products.findData(card_id) < 0:
                self.products.addItem('已保存的关联产品卡', card_id)
            self.products.setCurrentIndex(max(0, self.products.findData(card_id)))

    def choose(self, index):
        self.load(self.plans.get(self.library.itemData(index)) or planning.new_plan())

    def load(self, plan):
        self.loading = True
        self.plan = plan
        for key, widget in self.inputs.items():
            if hasattr(widget, 'setPlainText'):
                widget.setPlainText(plan[key])
            else:
                widget.setText(plan[key])
        self.refresh_choices()
        self.loading = False
        self.changed()

    def read(self):
        fields = {key: widget.toPlainText() if hasattr(widget, 'toPlainText') else widget.text()
                  for key, widget in self.inputs.items()}
        return dict(self.plan, business_card_id=self.products.currentData() or '', **fields)

    def dirty(self):
        return self.read() != self.plan

    def reload(self):
        saved = next((value for value in self.store.plans() if value['id'] == self.plan['id']), None)
        self.load(saved or planning.new_plan())

    def changed(self, *_):
        if self.loading:
            return
        dirty = self.dirty()
        self.library.setEnabled(not dirty)
        self.new_button.setEnabled(not dirty)
        self.save_button.setEnabled(dirty and bool(self.inputs['track'].text().strip()))
        self.discard_button.setVisible(dirty)
        self.draft_button.setEnabled(not dirty and bool(self.plan['revision']))
        self.status.setText('调研有未保存的修改。' if dirty else
                            ('已保存到本机' if self.plan['revision'] else ''))

    def save(self):
        try:
            self.load(self.store.save(self.read()))
        except (OSError, ValueError) as error:
            self.status.setText(str(error))


class PlanningDraftDialog(CreatorDialog):
    def __init__(self, plan, commit, parent):
        super().__init__(parent)
        self.setWindowTitle('预览选题卡')
        self.resize(680, 580)
        layout = QVBoxLayout(self)
        layout.addWidget(wrapped(f'来自「{plan["track"]}」第 {plan["revision"]} 版。确认后新建选题卡。'))
        form = QFormLayout()
        self.inputs = {}
        values = planning.draft_fields(plan)
        for key, label in (('title', '本期题目'), *planning.READINESS, ('references', '对标链接与时间码')):
            widget = field(label) if key == 'title' else editor(label)
            if key == 'title':
                widget.setText(values[key])
            else:
                widget.setPlainText(values[key])
                widget.setFixedHeight(76)
            self.inputs[key] = widget
            form.addRow(label, widget)
        layout.addLayout(form)
        status = wrapped()
        layout.addWidget(status)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button('取消', self.reject))

        def save():
            fields = {key: widget.toPlainText() if key != 'title' else widget.text()
                      for key, widget in self.inputs.items()}
            try:
                commit(planning.create_topic_from_plan(plan, fields))
            except (OSError, ValueError) as error:
                status.setText(str(error))
            else:
                self.accept()

        actions.addWidget(button('保存选题卡', save, True))
        layout.addLayout(actions)
