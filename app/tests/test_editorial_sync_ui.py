"""A real isolated Qt window observes CLI copies and retains local edits."""
from copy import deepcopy
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent

from src.core import content_workbench as work
from src.core.agent_workspace.service import WorkspaceService
from src.ui.content_workbench import ContentWorkbench


def test_editorial_external_append_appears_and_local_edits_survive(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root = tmp_path.resolve()/'editorial'
    monkeypatch.setattr(work, 'default_root', lambda: root)
    widget = ContentWorkbench(root=root, connection_reader=lambda: [])
    widget.resize(1200, 760)
    widget.show()
    app.processEvents()
    try:
        project_id = widget.project['id']
        service = WorkspaceService()
        before = deepcopy(widget.state)
        widget.flush()
        assert work.WorkbenchStore().load()['revision'] == before['revision']
        added = service.editorial_add_candidate('first', project_id, before['revision'], title='第一篇', text='完整正文')
        widget._sync_external()
        assert widget.candidates.count() == 1
        assert widget.original.toPlainText() == '完整正文'
        assert widget.candidate['id'] == added['candidate_id']
        # CLI writes while the user is still typing: no poll overwrites text.
        widget.original.setPlainText('界面里刚刚输入\n真实重复\n真实重复')
        revision = widget.state['revision']
        service.editorial_add_candidate('second', project_id, revision, title='第二篇', text='另一份完整正文')
        widget._sync_external()
        assert widget.original.toPlainText().startswith('界面里刚刚输入')
        assert widget.flush()
        assert widget.candidates.count() == 2
        assert widget.candidate['id'] == added['candidate_id']
        assert widget.original.toPlainText() == '界面里刚刚输入\n真实重复\n真实重复'
        saved = work.WorkbenchStore().load()
        assert saved['projects'][0]['candidates'][0]['text'] == widget.original.toPlainText()
        assert set(saved['request_receipts']) == {'first', 'second'}
        topic = service.editorial_create('topic2', '另一个选题', saved['revision'])
        widget._sync_external()
        assert widget.projects.count() == 2
        assert widget.project['id'] == project_id
        assert widget.projects.findData(topic['project_id']) >= 0
    finally:
        widget.refresh_timer.stop()
        widget.save_timer.stop()
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
