import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.core import creator_workbench as core
from src.core.creator_workflow import COMMERCIAL, STAGES
from src.ui.creator_workbench import CreatorWorkbench, ImportPreview
from src.ui.content_workbench import ContentWorkbench


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_switching_topics_keeps_saved_revision_and_six_dimensions(app,tmp_path):
    store = core.CreatorStore(tmp_path)
    store.import_rows([{'title':'甲','source':'https://example.test/a'}, {'title':'乙','source':'https://example.test/b'}])
    page = CreatorWorkbench(root=tmp_path)
    page.resize(1360,850); page.show(); app.processEvents()
    assert set(page.analysis) == set(core.DIMENSIONS)
    page.title.setText('修改乙'); page.changed(); assert page.flush()
    page.list.setCurrentRow(1); page.list.setCurrentRow(0)
    page.brief['具体痛点'].setPlainText('具体场景'); assert page.flush()
    assert next(t for t in store.topics() if t['title']=='修改乙')['brief']['具体痛点'] == '具体场景'
    page.close()


def test_immediate_selection_before_autosave_opens_destination(app,tmp_path):
    store = core.CreatorStore(tmp_path)
    store.import_rows([{'title':'甲','source':'https://example.test/a'}, {'title':'乙','source':'https://example.test/b'}])
    page = CreatorWorkbench(root=tmp_path)
    source_id = page.topic['id']
    target_id = page.list.item(1).data(Qt.UserRole)['id']
    page.brief['具体痛点'].setPlainText('尚未触发计时器的编辑')
    assert page.timer.isActive()
    page.list.setCurrentRow(1)
    assert page.topic['id'] == target_id
    assert page.list.item(0).data(Qt.UserRole)['id'] == source_id
    rows = {t['id']:t for t in store.topics()}
    assert rows[source_id]['brief']['具体痛点'] == '尚未触发计时器的编辑'
    assert rows[target_id]['brief']['具体痛点'] == ''
    page.close()


def test_production_navigation_and_autosave_keep_older_projects(app, tmp_path):
    store = core.CreatorStore(tmp_path)
    for title in ('早期项目', '本期选题'):
        topic = core.new_topic(title, 'https://example.test/' + ('old' if title == '早期项目' else 'current'))
        topic['brief']['目标观众'] = '原有目标观众'
        topic['editorial_project_id'] = '已有文案项目'
        topic['transcript'] = '保留原逐字稿'
        store.save(topic)
    originals = {topic['id']: deepcopy(topic) for topic in store.topics()}
    page = CreatorWorkbench(root=tmp_path)
    page.resize(1100, 780)
    page.show()
    app.processEvents()
    assert [page.production_tabs.tabText(i) for i in range(5)] == [
        f'{i} {stage.title}' for i, stage in enumerate(STAGES, 1)
    ]
    assert page.tabs.tabText(1) == '选题判断'
    assert page.tabs.tabText(2) == '视频拆解'
    assert page.tabs.tabText(3) == '来源与逐字稿'
    current_id = page.topic['id']
    assert page.flush()
    assert {topic['id']: topic for topic in store.topics()} == originals

    page.production_tabs.setCurrentIndex(1)
    script_tabs = page.production_tabs.currentWidget()
    assert script_tabs.tabText(1) == '商单 Brief 五步'
    script_tabs.setCurrentIndex(1)
    brief = script_tabs.currentWidget()
    assert brief.steps.count() == 5
    for i, step in enumerate(COMMERCIAL.steps):
        assert step.title in brief.steps.item(i).text()
    brief.input.setPlainText('本机 Brief 原文')
    brief.output.setPlainText('卖点｜第2页原句｜观众收益｜操作画面')
    brief.complete.setChecked(True)
    brief.steps.setCurrentRow(1)
    brief.output.setPlainText('待筛思路')
    page.production_tabs.setCurrentIndex(3)
    post = page.production_tabs.currentWidget()
    post.steps.setCurrentRow(2)
    assert '相似快切' in post.guide.text()
    post.output.setPlainText('参考片段 00:08–00:15')
    page.list.setCurrentRow(1)
    page.list.setCurrentRow(0)
    assert page.topic['id'] == current_id
    brief.steps.setCurrentRow(0)
    assert brief.input.toPlainText() == '本机 Brief 原文'
    assert brief.complete.isChecked()
    page.close()

    reopened = CreatorWorkbench(root=tmp_path)
    records = reopened.topic['workflow']
    assert records['brief-ideas']['output'] == '待筛思路'
    assert records['post-visuals']['output'] == '参考片段 00:08–00:15'
    plain = {k: value for k, value in reopened.topic.items() if k not in {'workflow', 'updated_at', 'revision'}}
    original = {k: value for k, value in originals[current_id].items() if k not in {'updated_at', 'revision'}}
    assert plain == original
    assert '本机 Brief 原文' in core.topic_markdown(reopened.topic, include_workflow=True)
    assert '本机 Brief 原文' not in core.topic_markdown(reopened.topic)
    reopened.close()


def test_status_filter_updates_after_edit_and_reflects_failed_save(app, tmp_path):
    store = core.CreatorStore(tmp_path)
    store.import_rows([
        {'title': '待判断的选题', 'source': 'https://example.test/a'},
        {'title': '完成的选题', 'source': 'https://example.test/b', 'status': '已完成'},
    ])
    page = CreatorWorkbench(root=tmp_path)
    page.filter.setCurrentText(core.PENDING_STATUS)
    assert page.list.count() == 1
    assert page.topic['title'] == '待判断的选题'

    page.status.setCurrentText('候选')
    QTest.qWait(650)
    assert page.filter.currentText() == '候选'
    assert page.list.count() == 1
    assert page.topic['title'] == '待判断的选题'
    page.filter.setCurrentText('全部状态')
    page.list.setCurrentRow(1)
    assert page.filter.currentText() == '全部状态'
    page.list.setCurrentRow(0)
    assert page.topic['title'] == '待判断的选题'
    page.status.activated.emit(page.status.currentIndex())
    assert page.filter.currentText() == '候选'
    assert page.list.count() == 1

    page.status.setCurrentText('不采用')
    page.filter.setCurrentText('已完成')
    assert page.filter.currentText() == '候选'
    assert page.status.currentText() == '不采用'
    assert '原因' in page.notice.text()

    page.decision.setPlainText('素材不足')
    assert page.flush()
    app.processEvents()
    assert page.filter.currentText() == '不采用'
    assert page.list.count() == 1
    assert page.count.text() == '显示 1 / 共 2 个选题'
    assert page.topic['title'] == '待判断的选题'
    assert page.topic['decision'] == '素材不足'
    page.filter.setCurrentText('已完成')
    assert page.topic['title'] == '完成的选题'
    page.filter.setCurrentText('暂存')
    assert page.list.count() == 0
    assert '没有符合' in page.empty.text()
    page.filter.setCurrentText('全部状态')
    assert page.list.count() == 2
    page.close()


def test_editorial_handoff_is_idempotent_and_keeps_manual_draft(app,tmp_path):
    topic = core.new_topic('一个实际问题'); topic['transcript'] = '原话。真实重复。真实重复。'
    page = ContentWorkbench(root=tmp_path,connection_reader=lambda:[])
    pid = page.open_creator_topic(topic)
    project = next(p for p in page.state['projects'] if p['id']==pid)
    assert len(project['candidates']) == 1
    page.draft.setPlainText('已经手写的文案'); assert page.flush()
    assert page.open_creator_topic(topic) == pid
    project = next(p for p in page.state['projects'] if p['id']==pid)
    assert len(project['candidates']) == 1 and project['draft'] == '已经手写的文案'
    topic['analysis']['开头'] = '补充分析'
    assert page.open_creator_topic(topic) == pid
    assert len(next(p for p in page.state['projects'] if p['id']==pid)['candidates']) == 2
    page.close()


def test_import_preview_selective_and_explicit_column_mapping(app):
    dialog = ImportPreview({'kind':'records','fields':['自定义标题','自定义链接'],
        'records':[{'自定义标题':'甲','自定义链接':'https://example.test/a'},
                   {'自定义标题':'乙','自定义链接':'https://example.test/b'}], 'origin':'/example/topics.csv'},None)
    dialog.link_column.setCurrentText('自定义链接')
    assert len(dialog.selected_rows()) == 2
    dialog.list.item(1).setCheckState(Qt.Unchecked)
    assert dialog.selected_rows()[0]['source'] == 'https://example.test/a'
    assert len(dialog.selected_rows()) == 1
    dialog.close()


def test_native_dark_system_palette_does_not_darken_creator_dialogs(app,tmp_path):
    from PySide6.QtGui import QPalette,QColor
    from src.ui import theme as T
    from src.ui.creator_workbench import CreatorDialog,SegmentDialog
    before=QPalette(app.palette());dark=QPalette(before)
    dark.setColor(QPalette.Window,QColor('#333333'));dark.setColor(QPalette.WindowText,QColor('#ffffff'))
    app.setPalette(dark)
    try:
        page=CreatorWorkbench(root=tmp_path)
        preview=ImportPreview({'kind':'documents','rows':[{'title':'示例','text':'正文','source':'https://example.test'}]},page)
        dialogs=[preview,CreatorDialog(page),SegmentDialog(0,0,page)]
        for widget in [page,*dialogs]:
            widget.show();app.processEvents()
            assert widget.palette().color(QPalette.Window).name()==QColor(T.BG).name()
            assert widget.palette().color(QPalette.WindowText).name()==QColor(T.INK).name()
        for dialog in dialogs:dialog.close()
        page.close()
    finally:app.setPalette(before)


def test_business_card_from_workbench_keeps_evidence_and_existing_topic(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QPushButton
    from src.ui.business_analysis import BusinessDraftDialog

    store = core.CreatorStore(tmp_path)
    original = core.new_topic('旧项目')
    original['brief']['目标观众'] = '原来就填好了的观众'
    original['brief']['具体痛点'] = '原来就填好的痛点'
    original['analysis'][core.DIMENSIONS[0]] = '对标拆解原文'
    original['workflow'] = {COMMERCIAL.steps[0].key: {'input': '原 Brief', 'done': True}}
    store.save(original)
    page = CreatorWorkbench(root=tmp_path)
    page.resize(1100, 780)
    page.show()
    app.processEvents()
    entry = next(button for button in page.findChildren(QPushButton)
                 if button.text() == '展开商业分析' and button.isVisible())
    QTest.mouseClick(entry, Qt.LeftButton)
    business = page.business
    assert business.isVisible()
    assert not business.details.isVisible()

    business.inputs['product'].setText('测试二手车')
    business.inputs['payer'].setText('预算已定的首次购车者')
    business.inputs['scene'].setText('试驾后准备交订金')
    business.inputs['concern'].setText('怎么确认车况？')
    QTest.mouseClick(business.details_button, Qt.LeftButton)
    business.bottleneck.setCurrentText('交付')
    business.inputs['verification'].setText('核对检测文件和现场车辆一致')
    business.add_evidence({})
    row = business.rows[0]
    row.note.setText('镜头拍检测记录和现场车身编号')
    row.status.setCurrentText('已核实')
    QTest.mouseClick(business.save_button, Qt.LeftButton)
    assert '需要同时填写' in business.notice.text()
    assert not business.store.cards()
    row.source.setText('测试车辆检测单第2页')
    QTest.mouseClick(business.save_button, Qt.LeftButton)
    saved_card = deepcopy(business.card)
    assert saved_card['revision'] == 1
    assert store.topics() == [original]
    page.close()

    page = CreatorWorkbench(root=tmp_path)
    page.resize(1100, 780)
    page.show()
    page.open_business()
    business = page.business
    business.library.setCurrentIndex(1)
    assert business.card == saved_card

    def cancel_draft(dialog):
        dialog.goal.setCurrentText('被认可')
        assert '测试车辆检测单第2页' in dialog.fields['proof'].toPlainText()
        dialog.proof.setCurrentIndex(0)
        assert '待补证据' in dialog.fields['proof'].toPlainText()
        assert not dialog.checks['audience'].isChecked()
        assert not dialog.checks['scene'].isChecked()
        assert not dialog.checks['question'].isChecked()
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(BusinessDraftDialog, 'exec', cancel_draft)
    QTest.mouseClick(business.draft_button, Qt.LeftButton)
    assert store.topics() == [original]

    def save_draft(dialog):
        dialog.goal.setCurrentText('被认可')
        dialog.proof.setCurrentIndex(1)
        assert '测试车辆检测单第2页' in dialog.fields['proof'].toPlainText()
        dialog.fields['benefit'].setPlainText('学会核对检测单与现场车辆')
        dialog.save_topic()
        assert dialog.result() == QDialog.Accepted
        return dialog.result()

    monkeypatch.setattr(BusinessDraftDialog, 'exec', save_draft)
    QTest.mouseClick(business.draft_button, Qt.LeftButton)
    saved = store.topics()[0]
    assert saved['brief']['目标观众'] == original['brief']['目标观众']
    assert saved['brief']['具体痛点'] == original['brief']['具体痛点']
    assert saved['brief']['观众收获'] == '学会核对检测单与现场车辆'
    assert saved['analysis'] == original['analysis']
    assert saved['workflow'] == original['workflow']
    assert saved['business_analysis']['snapshot'] == saved_card
    assert saved['business_analysis']['evidence']['source'] == '测试车辆检测单第2页'
    assert business.version_button.isVisible()
    release = page.workflow_panes[4]
    release.steps.setCurrentRow(next(i for i, step in enumerate(release.stage.steps) if step.key == 'release-learn'))
    assert '「被认可」' in release.guide.text()

    def save_new_draft(dialog):
        dialog.destination.setCurrentIndex(1)
        dialog.title.setText('更换一个题目复用同一张卡')
        dialog.goal.setCurrentText('被需要')
        dialog.proof.setCurrentIndex(0)
        dialog.save_topic()
        return dialog.result()

    monkeypatch.setattr(BusinessDraftDialog, 'exec', save_new_draft)
    QTest.mouseClick(business.draft_button, Qt.LeftButton)
    second, first = store.topics()
    assert second['business_analysis']['card_id'] == first['business_analysis']['card_id']
    assert second['brief']['证据与待核实'].startswith('待补证据')
    business.inputs['concern'].setText('更新后，过去的题目仍可回查')
    QTest.mouseClick(business.save_button, Qt.LeftButton)
    assert business.card['revision'] == 2
    assert store.topics()[1]['business_analysis']['snapshot'] == saved_card
    page.close()
