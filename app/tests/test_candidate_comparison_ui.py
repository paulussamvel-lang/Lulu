"""Real Qt interaction: concurrent reading, correct excerpt source and CLI sync."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from src.core import content_workbench as core
from src.ui.content_workbench import ContentWorkbench


@pytest.fixture
def workbench(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = ContentWorkbench(root=tmp_path / 'editorial', connection_reader=lambda: [])
    widget.resize(1180, 780)
    widget.show()
    app.processEvents()
    yield widget, app
    widget.refresh_timer.stop()
    widget.save_timer.stop()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_both_full_texts_visible_and_excerpt_uses_its_own_source(workbench):
    widget, app = workbench
    widget._append('第一版', '第一篇的开头\n第一篇的结尾')
    widget._append('第二版', '第二篇独有的开头\n第二篇独有的结尾')
    app.processEvents()
    first, second = widget.project['candidates']
    panes = widget.comparison.panes
    assert widget.content_tabs.currentWidget() is widget.comparison
    assert all(p.isVisible() and p.body.isVisible() for p in panes.values())
    assert panes[first['id']].body.toPlainText() == first['text']
    assert panes[second['id']].body.toPlainText() == second['text']
    assert panes[first['id']].geometry().right() < panes[second['id']].x()
    assert not widget.assembly_panel.isVisible()
    # The single-editor selection is second, but extract from first directly.
    assert widget.candidate['id'] == second['id']
    pane = panes[first['id']]
    pane.body.selectAll()
    pane.clip_button.click()
    clip = widget.project['clips'][-1]
    assert clip['candidate_id'] == first['id']
    assert clip['text'] == first['text']
    assert widget.assembly_panel.isVisible()
    pane.edit_button.click()
    assert widget.content_tabs.currentIndex() == 1
    assert widget.candidate['id'] == first['id']
    widget.original.setPlainText('修改后的第一版')
    assert pane.body.toPlainText() == '修改后的第一版'
    assert widget.flush()
    saved = widget.store.load()['projects'][0]
    assert saved['candidates'][0]['text'] == '修改后的第一版'
    assert saved['clips'][0]['text'] == '第一篇的开头\n第一篇的结尾'


def test_checkboxes_all_candidates_empty_state_and_horizontal_overflow(workbench):
    widget, app = workbench
    assert widget.comparison.empty.isVisible()
    for i in range(8):
        widget._append(f'文案 {i}', f'全文 {i}\n结尾')
    app.processEvents()
    assert len(widget.comparison.panes) == 8
    assert widget.comparison.scroll.horizontalScrollBar().maximum() > 0
    last_id = widget.project['candidates'][-1]['id']
    widget.candidates.item(7).setCheckState(Qt.Unchecked)
    assert last_id not in widget.comparison.panes
    for i in range(7):
        widget.candidates.item(i).setCheckState(Qt.Unchecked)
    app.processEvents()
    assert widget.comparison.empty.isVisible()
    assert not widget.comparison.scroll.isVisible()
    widget.candidates.item(0).setCheckState(Qt.Checked)
    assert len(widget.comparison.panes) == 1
    assert '再勾选一篇' in widget.comparison.hint.text()


def test_external_append_keeps_comparison_selection_and_local_edits(workbench):
    widget, app = workbench
    widget._append('第一版', '\n'.join(f'段落{i}' for i in range(100)))
    widget.flush()
    key = widget.candidate['id']
    pane = widget.comparison.panes[key]
    cursor = pane.body.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(3, QTextCursor.KeepAnchor)
    pane.body.setTextCursor(cursor)
    pane.body.verticalScrollBar().setValue(10)
    scroll = pane.body.verticalScrollBar().value()
    remote = widget.store.load()
    core.add_candidate(remote['projects'][0], 'CLI 新增文案', 'CLI 完整正文')
    widget.store.save(remote)
    widget._sync_external()
    assert widget.comparison.panes[key] is pane
    assert pane.body.textCursor().selectedText() == '段落0'
    assert pane.body.verticalScrollBar().value() == scroll
    assert len(widget.comparison.panes) == 2
    widget.original.setPlainText('界面本地修改\n真实重复\n真实重复')
    remote = widget.store.load()
    core.add_candidate(remote['projects'][0], '另一次 CLI 新增', '第三篇正文')
    widget.store.save(remote)
    assert widget.flush()
    assert len(widget.comparison.panes) == 3
    assert widget.comparison.panes[key].body.toPlainText() == '界面本地修改\n真实重复\n真实重复'
    assert widget.content_tabs.currentWidget() is widget.comparison


def test_review_scores_are_attached_to_the_right_pane_and_marked_stale(workbench):
    widget, app = workbench
    widget._append('第一版', '第一篇正文')
    widget._append('第二版', '第二篇正文')
    first, second = widget.project['candidates']
    widget.project['review'] = {
        'input_hash': core.review_hash(widget.project), 'comparison': '比较意见', 'model': '测试模型',
        'documents': [dict(id=first['id'], score=82, summary='第一篇', marks=[]),
                      dict(id=second['id'], score=91, summary='第二篇', marks=[])],
    }
    widget._refresh_comparison()
    assert widget.comparison.panes[first['id']].score.text() == '整体分：82/100'
    assert widget.comparison.panes[second['id']].score.text() == '整体分：91/100'
    widget.original.setPlainText('修改第二篇')
    assert '上次结果' in widget.comparison.panes[second['id']].score.text()
    widget._audience_changed('换一个目标观众')
    assert '上次结果' in widget.comparison.panes[first['id']].score.text()
