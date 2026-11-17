"""Click-to-compose must retain exact source occurrences and freeform writing."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt, QPoint, QCoreApplication, QEvent
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.core import content_workbench as core
from src.ui.content_workbench import ContentWorkbench


@pytest.fixture
def workbench(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = ContentWorkbench(root=tmp_path / 'editorial', connection_reader=lambda: [])
    widget.resize(1440, 900)
    widget.show()
    app.processEvents()
    yield widget, app
    widget.refresh_timer.stop()
    widget.save_timer.stop()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def click_sentence(pane, start, app):
    text = pane.body.toPlainText()
    cursor = pane.body.textCursor()
    cursor.setPosition(len(text[:start+1].encode('utf-16-le')) // 2)
    pane.body.setTextCursor(cursor)
    point = pane.body.cursorRect(cursor).center()
    QTest.mouseClick(pane.body.viewport(), Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()


def test_sentence_boundaries_preserve_quotes_decimals_emoji_and_real_repetition():
    text = '  😀第一句。第二句！“第三句？”\n数值是3.14；下一句\n重复。重复。\n1. 开始演示。'
    spans = core.sentence_spans(text)
    assert [text[a:b] for a,b in spans] == ['😀第一句。','第二句！','“第三句？”','数值是3.14；','下一句','重复。','重复。','1. 开始演示。']
    assert spans[5] != spans[6]


def test_clicks_append_in_order_without_assemble_or_overwriting_manual_edits(workbench):
    widget, app = workbench
    widget._append('版本 A', '😀先看实测。真实重复。真实重复。')
    widget._append('版本 B', '这是另一篇。保留不同的例子！')
    first, second = widget.project['candidates']
    assert widget.assembly_panel.isVisible() and widget.draft.toPlainText() == ''
    assert not widget.candidate_panel.isVisible()
    b_span = core.sentence_spans(second['text'])[1]
    a_spans = core.sentence_spans(first['text'])
    click_sentence(widget.comparison.panes[second['id']], b_span[0], app)
    assert widget.draft.toPlainText() == '保留不同的例子！'
    widget.draft.setPlainText('我自己的开头\n\n微调后的例子！')
    click_sentence(widget.comparison.panes[first['id']], a_spans[1][0], app)
    click_sentence(widget.comparison.panes[first['id']], a_spans[2][0], app)
    assert widget.draft.toPlainText() == '我自己的开头\n\n微调后的例子！\n\n真实重复。\n\n真实重复。'
    assert [c['candidate_id'] for c in widget.project['clips']] == [second['id'],first['id'],first['id']]
    assert widget.project['clips'][1]['sentence_start'] != widget.project['clips'][2]['sentence_start']
    assert first['text'] == '😀先看实测。真实重复。真实重复。'
    assert widget.flush()
    saved = widget.store.load()['projects'][0]
    assert saved['draft'] == widget.draft.toPlainText()
    assert saved['clips'][0]['original_text'] == '保留不同的例子！'
    widget._adopt_state(widget.store.load())
    assert widget.draft.toPlainText() == saved['draft']


def test_dragging_text_does_not_accidentally_pick_a_sentence(workbench):
    widget, app = workbench
    widget._append('可拖选', '这段文字足够长，可以拖动选择其中一部分。第二句。')
    pane = next(iter(widget.comparison.panes.values()))
    cursor = pane.body.textCursor()
    cursor.setPosition(1);start=pane.body.cursorRect(cursor).center()
    cursor.setPosition(8);end=pane.body.cursorRect(cursor).center()
    QTest.mousePress(pane.body.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(pane.body.viewport(), end)
    QTest.mouseRelease(pane.body.viewport(), Qt.LeftButton, Qt.NoModifier, end)
    assert widget.draft.toPlainText() == ''
    assert not widget.project['clips']


def test_keyboard_pick_and_draft_undo(workbench):
    widget, app = workbench
    widget._append('键盘', '第一句。第二句！')
    pane = next(iter(widget.comparison.panes.values()))
    cursor = pane.body.textCursor();cursor.setPosition(1);pane.body.setTextCursor(cursor)
    QTest.keyClick(pane.body, Qt.Key_Return)
    assert widget.draft.toPlainText() == '第一句。'
    widget.draft.undo()
    assert widget.draft.toPlainText() == ''
    assert widget.project['draft'] == ''


def test_three_sources_and_editable_output_are_simultaneously_visible(workbench):
    widget, app = workbench
    for name in ('版本一','版本二','版本三'):
        widget._append(name, '第一句。第二句。')
    app.processEvents()
    assert len(widget.comparison.panes) == 3
    assert widget.draft.isVisible() and not widget.draft.isReadOnly()
    assert widget.comparison.scroll.horizontalScrollBar().maximum() == 0
    assert all(p.body.isVisible() for p in widget.comparison.panes.values())
    assert widget.assembly_panel.x() > widget.content_tabs.x()


def test_old_draft_and_selections_are_not_reassembled_on_open(workbench):
    widget, app = workbench
    widget._append('原候选', '原来的片段。新选择。')
    candidate = widget.candidate
    core.add_clip(widget.project, candidate['id'], '原来的片段。')
    widget.draft.setPlainText('已经微调过的旧稿，保留我的补写。')
    widget.flush()
    widget._adopt_state(widget.store.load())
    assert widget.draft.toPlainText() == '已经微调过的旧稿，保留我的补写。'
    span = core.sentence_spans(candidate['text'])[1]
    click_sentence(widget.comparison.panes[candidate['id']], span[0], app)
    assert widget.draft.toPlainText() == '已经微调过的旧稿，保留我的补写。\n\n新选择。'
