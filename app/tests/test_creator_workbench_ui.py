import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.core import creator_workbench as core
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
