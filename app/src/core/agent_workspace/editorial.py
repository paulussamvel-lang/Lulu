"""Additive public operations on the same editorial store used by the window."""
from copy import deepcopy

from .. import content_workbench as work, library
from . import documents
from .store import encode, identity


def _revision(value):
    if type(value) is not int or value < 0:
        raise ValueError('请提供读取文案精选时的 revision。')


def _text(value, label, maximum, *, empty=False):
    if type(value) is not str or len(value.encode('utf-8')) > maximum or (not empty and not value.strip()):
        raise ValueError(label + '为空或超过本次大小上限；未截断。')
    return value


def _project(state, project_id):
    identity(project_id)
    found = next((p for p in state['projects'] if p['id'] == project_id), None)
    if found is None:
        raise FileNotFoundError(project_id)
    return found


def _summary(project):
    return dict(project_id=project['id'], title=project['title'], audience=project['audience'],
                updated_at=project['updated_at'], candidate_count=len(project['candidates']),
                clip_count=len(project['clips']))


class EditorialOperations:
    def editorial_list(self, search='', offset=0, limit=100):
        """List 文案精选 topics and the workspace revision, without model calls."""
        _text(search, '搜索词', 2048, empty=True)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('分页范围无效。')
        state = work.WorkbenchStore().load()
        rows = [p for p in state['projects'] if search.casefold() in p['title'].casefold()]
        return dict(revision=state['revision'], total=len(rows), offset=offset,
                    has_more=offset + limit < len(rows), projects=[_summary(p) for p in rows[offset:offset+limit]])

    def editorial_show(self, project_id):
        """Read a topic and candidate summaries; candidate reads return full text."""
        state = work.WorkbenchStore().load()
        project = _project(state, project_id)
        candidates = [dict(candidate_id=c['id'], title=c['title'], source=c['source'],
                           document_id=c['document_id'], selected=c.get('selected', True),
                           content_hash=work.digest(c['text']), bytes=len(c['text'].encode()))
                      for c in project['candidates']]
        return dict(revision=state['revision'], project=_summary(project), candidates=candidates)

    def editorial_candidate(self, project_id, candidate_id):
        """Read one complete candidate copy, retaining source and exact text."""
        identity(candidate_id)
        state = work.WorkbenchStore().load()
        project = _project(state, project_id)
        row = next((c for c in project['candidates'] if c['id'] == candidate_id), None)
        if row is None:
            raise FileNotFoundError(candidate_id)
        _text(row['text'], '候选正文', 8 * 1024 * 1024, empty=True)
        return dict(revision=state['revision'], project_id=project_id,
                    candidate=deepcopy(row), content_hash=work.digest(row['text']))

    def editorial_create(self, request_id, title, expected_revision, audience=''):
        """Create a topic once; replay the same request_id to read its receipt."""
        identity(request_id)
        _revision(expected_revision)
        _text(title, '选题名', 640)
        if len(title) > 160:
            raise ValueError('选题名不能超过 160 字；未截断。')
        _text(audience, '目标观众', 8192, empty=True)
        intent = work.digest(encode(['editorial.create', title, audience, expected_revision]))
        def create(state):
            project = work.new_project(title.strip())
            project['audience'] = audience
            state['projects'].append(project)
            return dict(project_id=project['id'], title=project['title'])
        return work.WorkbenchStore().commit(request_id, intent, expected_revision, create)

    def editorial_add_candidate(self, request_id, project_id, expected_revision, title=None,
                                text=None, document_id=None, expected_document_revision=None,
                                expected_document_hash=None, selected=True):
        """Append a candidate copy from text OR a version-bound existing document.

        Direct text needs title and text. A document import needs document_id,
        expected_document_revision and expected_document_hash from documents.show.
        It preserves the original, never scores, and never calls a model.
        """
        identity(request_id); identity(project_id)
        _revision(expected_revision)
        if type(selected) is not bool:
            raise ValueError('候选勾选状态必须是布尔值。')
        if title is not None:
            _text(title, '候选标题', 640)
            if len(title) > 160:
                raise ValueError('候选标题不能超过 160 字；未截断。')
        if document_id is None:
            if expected_document_revision is not None or expected_document_hash is not None:
                raise ValueError('手动文案不能带来源文稿版本。')
            _text(title, '候选标题', 640)
            _text(text, '候选正文', 1024 * 1024)
        else:
            identity(document_id)
            _revision(expected_document_revision)
            if text is not None or type(expected_document_hash) is not str or len(expected_document_hash) != 64:
                raise ValueError('来源文稿须绑定版本和正文摘要，不能同时传入另一份正文。')
        intent = work.digest(encode(['editorial.add-candidate', project_id, expected_revision,
            title, text, document_id, expected_document_revision, expected_document_hash, selected]))
        def append(state):
            project = _project(state, project_id)
            source_text, source_title = text, title
            source = 'CLI · 手动文案副本'
            if document_id is not None:
                doc = documents.snapshot(document_id)
                if (doc['revision'], doc['content_hash']) != (expected_document_revision, expected_document_hash):
                    raise library.RevisionConflict('来源文稿已有新修改，请重新读取后再选入。')
                source_text, source_title = doc['text'], title or doc['title']
                if len(source_title) > 160:
                    raise ValueError('来源标题超过 160 字，请提供候选标题；未截断。')
                source = '文稿库 · ' + doc['title']
            candidate = work.add_candidate(project, source_title, source_text,
                document_id=document_id or '', source=source)
            candidate['selected'] = selected
            if document_id is not None:
                candidate.update(source_revision=expected_document_revision, source_hash=expected_document_hash)
            project['updated_at'] = work.stamp()
            return dict(project_id=project_id, candidate_id=candidate['id'],
                        content_hash=work.digest(candidate['text']), title=candidate['title'])
        return work.WorkbenchStore().commit(request_id, intent, expected_revision, append)
