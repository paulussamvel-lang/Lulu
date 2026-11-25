"""Product cards and draft review within the benchmark and topic stage."""
from copy import deepcopy

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..core import business_analysis as ba
from .creator_workbench import CreatorDialog, button, combo, editor, field


def wrapped(text=''):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    return label


def section_title(text):
    heading = QLabel(text)
    heading.setTextFormat(Qt.PlainText)
    font = heading.font()
    font.setBold(True)
    heading.setFont(font)
    return heading


class EvidenceRow(QWidget):
    def __init__(self, value, edited, removed):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.note = field('证据内容', '客户原话、销售反馈、数据或可拍素材')
        self.source = field('证据来源', '链接、文件名、页码或时间码')
        self.status = combo('证据状态', ba.EVIDENCE_STATES)
        self.note.setText(value.get('note', ''))
        self.source.setText(value.get('source', ''))
        self.status.setCurrentText(value.get('status', '待验证'))
        layout.addWidget(self.note, 3)
        layout.addWidget(self.source, 3)
        layout.addWidget(self.status)
        layout.addWidget(button('移除', lambda: removed(self)))
        self.note.textChanged.connect(edited)
        self.source.textChanged.connect(edited)
        self.status.currentIndexChanged.connect(edited)

    def value(self):
        return dict(note=self.note.text(), source=self.source.text(), status=self.status.currentText())


class BusinessAnalysisPane(QWidget):
    def __init__(self, store, close, open_draft, *, next_stage):
        super().__init__()
        self.store = ba.BusinessStore(store)
        self.open_draft = open_draft
        self.card = ba.new_card()
        self.loading = False
        self.rows = []
        self.inputs = {}
        self.link = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        top = QHBoxLayout()
        top.addWidget(section_title('商业分析'))
        self.library = combo('已保存的产品卡', ())
        self.library.currentIndexChanged.connect(self.choose_card)
        top.addWidget(self.library, 1)
        self.new_button = button('新建产品卡', self.start_new)
        top.addWidget(self.new_button)
        top.addWidget(button('收起商业分析', close))
        layout.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(scroll, 1)
        body = QWidget()
        form = QVBoxLayout(body)
        form.setContentsMargins(0, 0, 6, 4)
        form.setSpacing(10)
        form.addWidget(section_title('产品与购买场景'))
        quick = QFormLayout()
        self.add_fields(quick, ba.PRODUCT_FIELDS)
        form.addLayout(quick)

        details_button = button('展开更多商业信息', self.toggle_details)
        details_button.setCheckable(True)
        self.details_button = details_button
        form.addWidget(details_button, 0, Qt.AlignLeft)
        self.details = QWidget()
        extras = QVBoxLayout(self.details)
        extras.setContentsMargins(0, 0, 0, 0)
        extras.addWidget(section_title('产品、营销与销售、交付'))
        delivery = QFormLayout()
        self.bottleneck = combo('卡点所在环节', ba.BOTTLENECKS)
        self.bottleneck.currentIndexChanged.connect(self.changed)
        delivery.addRow('卡点所在环节', self.bottleneck)
        self.add_fields(delivery, ba.DETAIL_FIELDS[:5])
        extras.addLayout(delivery)
        extras.addWidget(section_title('谁为什么会买'))
        buyer = QFormLayout()
        self.add_fields(buyer, ba.DETAIL_FIELDS[5:])
        self.motive = combo('消费动机（可选）', ('请选择', *ba.MOTIVES[1:]))
        self.motive.currentIndexChanged.connect(self.changed)
        buyer.addRow('消费动机（可选）', self.motive)
        extras.addLayout(buyer)
        self.details.hide()
        form.addWidget(self.details)

        form.addWidget(section_title('证据'))
        self.empty_evidence = wrapped('暂无证据。可先记一条待验证的线索。')
        form.addWidget(self.empty_evidence)
        self.evidence_layout = QVBoxLayout()
        form.addLayout(self.evidence_layout)
        form.addWidget(button('添加证据', lambda: self.add_evidence({})), 0, Qt.AlignLeft)
        form.addStretch()
        scroll.setWidget(body)

        context = QHBoxLayout()
        self.link_label = wrapped()
        context.addWidget(self.link_label, 1)
        self.version_button = button('查看采用版本', self.show_version)
        context.addWidget(self.version_button)
        layout.addLayout(context)
        self.notice = wrapped()
        self.notice.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.notice)
        layout.addWidget(wrapped('待接入 · 行业资料整理。交接主流产品、购买路径、交付和顾虑的来源。'))
        actions = QHBoxLayout()
        self.reload_button = button('撤回未保存修改', self.reload_card)
        actions.addWidget(self.reload_button)
        actions.addStretch()
        self.save_button = button('保存产品卡', self.save_card)
        actions.addWidget(self.save_button)
        self.draft_button = button('带入选题草稿', lambda: self.open_draft(self.card), True)
        actions.addWidget(self.draft_button)
        actions.addWidget(button('继续账号定位', next_stage))
        layout.addLayout(actions)
        self.set_topic(None)
        self.start_new()

    def add_fields(self, form, fields):
        for key, label, hint in fields:
            widget = field(label, hint)
            widget.textChanged.connect(self.changed)
            self.inputs[key] = widget
            form.addRow(label, widget)

    def toggle_details(self, checked):
        self.details_button.setText('收起更多商业信息' if checked else '展开更多商业信息')
        self.details.setVisible(checked)

    def set_topic(self, topic):
        self.link = topic.get('business_analysis') if topic else None
        if self.link:
            self.link_label.setText(
                f'当前选题 · {self.link["snapshot"]["product"]} · 版本 {self.link["card_revision"]} · {self.link["goal"]}')
        elif topic:
            self.link_label.setText('当前选题 · ' + topic['title'])
        else:
            self.link_label.setText('可以先保存产品卡，再建立选题。')
        self.version_button.setVisible(bool(self.link))

    def show_version(self):
        dialog = CreatorDialog(self)
        dialog.setWindowTitle('本条选题采用的产品卡')
        dialog.resize(650, 460)
        layout = QVBoxLayout(dialog)
        report = editor('采用版本和来源')
        report.setProperty('workflowField', True)
        report.setPlainText('\n'.join(ba.export_lines(self.link)[2:]))
        report.setReadOnly(True)
        layout.addWidget(report, 1)
        actions = QHBoxLayout()
        evidence = self.link.get('evidence')
        if evidence and evidence['source']:
            source = evidence['source']
            actions.addWidget(button('复制采用证据的来源', lambda: QApplication.clipboard().setText(source)))
        actions.addStretch()
        actions.addWidget(button('关闭', dialog.accept))
        layout.addLayout(actions)
        dialog.exec()

    def open(self, preferred_card=''):
        if not self.dirty():
            self.refresh_library()
            card_id = preferred_card or (self.link['card_id'] if self.link else '')
            index = self.library.findData(card_id)
            if index > 0:
                self.choose_card(index)

    def refresh_library(self):
        self.cards = {card['id']: card for card in self.store.cards()}
        with QSignalBlocker(self.library):
            self.library.clear()
            self.library.addItem('选择已保存的产品卡')
            for card in self.cards.values():
                self.library.addItem(f'{card["product"]} · 版本 {card["revision"]}', card['id'])
            self.library.setCurrentIndex(max(0, self.library.findData(self.card['id'])))
        self.changed()

    def choose_card(self, index):
        key = self.library.itemData(index)
        self.load_card(self.cards[key] if key else ba.new_card())
        self.refresh_library()

    def start_new(self):
        self.load_card(ba.new_card())
        self.refresh_library()

    def reload_card(self):
        self.refresh_library()
        self.load_card(self.cards.get(self.card['id'], ba.new_card()))
        self.refresh_library()
        self.notice.setText('已载入保存的内容。' if self.card['revision'] else '已清空未保存的输入。')

    def load_card(self, card):
        self.loading = True
        self.card = {**ba.new_card(), **deepcopy(card)}
        for key, widget in self.inputs.items():
            widget.setText(self.card[key])
        self.bottleneck.setCurrentText(card['bottleneck'])
        self.motive.setCurrentIndex(ba.MOTIVES.index(card['motive']))
        for row in self.rows[:]:
            self.remove_evidence(row)
        for value in card['evidence']:
            self.add_evidence(value)
        self.loading = False
        self.changed()

    def add_evidence(self, value):
        row = EvidenceRow(value, self.changed, self.remove_evidence)
        self.evidence_layout.addWidget(row)
        self.rows.append(row)
        self.empty_evidence.hide()
        self.changed()
        if not self.loading:
            row.note.setFocus()

    def remove_evidence(self, row):
        self.rows.remove(row)
        self.evidence_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self.empty_evidence.setVisible(not self.rows)
        self.changed()

    def read_card(self):
        value = dict(self.card, **{key: widget.text() for key, widget in self.inputs.items()})
        value['bottleneck'] = self.bottleneck.currentText()
        value['motive'] = ba.MOTIVES[self.motive.currentIndex()]
        rows = [row.value() for row in self.rows]
        value['evidence'] = [row for row in rows if row['note'].strip() or row['source'].strip()
                             or row['status'] == '已核实']
        return value

    def dirty(self):
        return self.read_card() != self.card

    def changed(self, *_):
        if self.loading:
            return
        dirty = self.dirty()
        self.library.setEnabled(not dirty)
        self.new_button.setEnabled(not dirty)
        self.save_button.setEnabled(dirty and bool(self.inputs['product'].text().strip()))
        self.reload_button.setVisible(dirty)
        self.draft_button.setEnabled(not dirty and bool(self.card['revision']))
        self.notice.setText('产品卡有未保存的修改。' if dirty else '')

    def save_card(self):
        try:
            self.load_card(self.store.save(self.read_card()))
            self.refresh_library()
            self.notice.setText(f'产品卡已保存 · 版本 {self.card["revision"]}')
        except (ValueError, OSError) as error:
            self.notice.setText(str(error))


class BusinessDraftDialog(CreatorDialog):
    def __init__(self, card, topic, commit, parent):
        super().__init__(parent)
        self.card = card
        self.topic = topic
        self.commit = commit
        self.setWindowTitle('带入选题草稿')
        self.resize(720, 690)
        layout = QVBoxLayout(self)
        layout.addWidget(section_title(f'{card["product"]} · 版本 {card["revision"]}'))
        if card['bottleneck'] in ('产品', '交付'):
            note = '先验证' + card['bottleneck'] + '卡点，再考虑是否拍摄。'
            if card['verification']:
                note += '\n下一次验证 · ' + card['verification']
            layout.addWidget(wrapped(note))
        form = QFormLayout()
        self.destination = combo('选题保存位置', ('新建选题',))
        if topic:
            self.destination.insertItem(0, '当前选题 · ' + topic['title'])
            self.destination.setCurrentIndex(0)
        self.title = field('新选题名称', '填写新选题名称')
        self.goal = combo('本条选题主任务', ('选择一项', *ba.GOALS))
        self.goal_help = wrapped('按观众当前的购买进程选一个主任务。')
        self.proof = combo('选用产品卡证据', ('待补证据',))
        for row in card['evidence']:
            description = row['note'] or row['source'] or '证据内容待补'
            self.proof.addItem(f'{row["status"]} · {description[:48]}', row)
        if card['evidence']:
            preferred = next((i for i, row in enumerate(card['evidence']) if row['status'] == '已核实'), 0)
            self.proof.setCurrentIndex(preferred + 1)
        self.choices = form
        form.addRow('保存到', self.destination)
        form.addRow('新选题名称', self.title)
        form.addRow('本条主任务', self.goal)
        form.addRow(self.goal_help)
        form.addRow('采用证据', self.proof)
        layout.addLayout(form)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(scroll, 1)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setColumnStretch(1, 1)
        grid.setContentsMargins(0, 0, 4, 0)
        self.fields = {}
        self.checks = {}
        self.existing = {}
        for index, (key, label, _) in enumerate(ba.DRAFT_FIELDS):
            row = index * 2
            edit = editor(label)
            edit.setProperty('workflowField', True)
            edit.setFixedHeight(62)
            caption = QLabel(label)
            caption.setBuddy(edit)
            check = QCheckBox('采纳')
            check.setAccessibleName('采纳' + label)
            original = wrapped()
            grid.addWidget(caption, row, 0, Qt.AlignTop)
            grid.addWidget(edit, row, 1)
            grid.addWidget(check, row, 2, Qt.AlignTop)
            grid.addWidget(original, row + 1, 1, 1, 2)
            self.fields[key], self.checks[key], self.existing[key] = edit, check, original
        scroll.setWidget(body)
        self.notice = wrapped()
        layout.addWidget(self.notice)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button('取消', self.reject))
        actions.addWidget(button('保存选题', self.save_topic, True))
        layout.addLayout(actions)
        self.destination.currentIndexChanged.connect(self.update_destination)
        self.goal.currentTextChanged.connect(self.choose_goal)
        self.proof.currentIndexChanged.connect(self.choose_proof)
        self.update_destination()

    def is_new(self):
        return not self.topic or self.destination.currentIndex() != 0

    def update_destination(self, *_):
        is_new = self.is_new()
        self.choices.setRowVisible(self.title, is_new)
        for key, _, target in ba.DRAFT_FIELDS:
            current = '' if is_new else self.topic['brief'].get(target, '')
            preview = current.replace('\n', ' ')
            self.existing[key].setText('已有内容 · ' + preview[:88] + ('…' if len(preview) > 88 else ''))
            self.existing[key].setToolTip(current)
            self.existing[key].setVisible(bool(current))
            self.checks[key].setChecked(not current)
            self.checks[key].setText('替换' if current else '采纳')

    def choose_goal(self, goal):
        if goal not in ba.GOALS:
            return
        self.goal_help.setText(ba.GOALS[goal])
        proposal = ba.draft_fields(self.card, goal, self.proof.currentData())
        for key, value in proposal.items():
            edit = self.fields[key]
            if not edit.document().isModified():
                edit.setPlainText(value)

    def choose_proof(self, *_):
        self.fields['proof'].setPlainText(ba.evidence_text(self.proof.currentData()))

    def save_topic(self):
        try:
            self.commit(
                None if self.is_new() else self.topic, self.title.text(), self.card, self.goal.currentText(),
                {key: edit.toPlainText() for key, edit in self.fields.items()},
                {key for key, check in self.checks.items() if check.isChecked()},
                self.proof.currentData(),
            )
        except (ValueError, OSError) as error:
            self.notice.setText(str(error))
            return
        self.accept()
