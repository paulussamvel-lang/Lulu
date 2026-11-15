"""Public editorial writes, isolated from installed data, models and network."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.agent_cli.workspace_commands import execute
from src.core import content_workbench as work, library
from src.core.agent_workspace import documents
from src.core.agent_workspace.contracts import COMMANDS, discovery
from src.core.agent_workspace.service import WorkspaceService
from src.core.transcription_job_application import LocalTranscriptionJobError


@pytest.fixture
def editorial(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    monkeypatch.setattr(work, 'default_root', lambda: root/'editorial')
    monkeypatch.setattr(library, 'LIBRARY_DIR', root/'library')
    monkeypatch.setattr(library, 'FOLDERS_FILE', root/'library/folders.json')
    runtime = SimpleNamespace(_application=SimpleNamespace(assert_workspace_allowed=Mock()))
    def call(name, request):
        path = root/'request.json'
        path.write_text(json.dumps(request, ensure_ascii=False))
        return execute(['workspace', 'editorial', name, '--request', str(path), '--output', 'json'], runtime)
    return call, work.WorkbenchStore(), runtime


def test_public_discovery_complete_exact_text_replay_and_source_copy(editorial):
    call, store, runtime = editorial
    assert call('list', {}) == dict(revision=0, total=0, offset=0, has_more=False, projects=[])
    create = dict(request_id='topic-1', title='一期选题', audience='创作者', expected_revision=0)
    project = call('create', create)
    assert call('create', create) == project
    original = library.save_document('原文第一段\n\n真实重复\n真实重复🙂', '文稿原件')
    source = documents.snapshot(original)
    args = dict(request_id='candidate-1', project_id=project['project_id'], expected_revision=1,
                document_id=original, expected_document_revision=source['revision'],
                expected_document_hash=source['content_hash'])
    added = call('add-candidate', args)
    assert call('add-candidate', args) == added
    candidate = call('candidate', dict(project_id=project['project_id'], candidate_id=added['candidate_id']))
    assert candidate['candidate']['text'] == source['text']
    assert candidate['candidate']['source_hash'] == source['content_hash']
    assert documents.snapshot(original) == source
    shown = call('show', dict(project_id=project['project_id']))
    assert shown['revision'] == 2 and len(shown['candidates']) == 1
    assert 'text' not in shown['candidates'][0]
    assert call('list', dict(search='一期'))['projects'][0]['candidate_count'] == 1
    catalog = WorkspaceService().tool_catalog()['commands']
    assert {x['command'] for x in catalog if x['command'].startswith('editorial.')} == {
        'editorial.list', 'editorial.show', 'editorial.candidate', 'editorial.create', 'editorial.add-candidate'}
    assert len([x for x in discovery({v[0] for v in COMMANDS.values()}) if x['command_id'].startswith('workspace.editorial.') and x['executable']]) == 5
    runtime._application.assert_workspace_allowed.assert_called_with('WS-88')


def test_replay_conflicts_and_changed_source_never_overwrite(editorial):
    call, store, _ = editorial
    topic = call('create', dict(request_id='p', title='主题', expected_revision=0))
    args = dict(request_id='a', project_id=topic['project_id'], expected_revision=1,
                title='候选', text='重复的话\n重复的话')
    added = call('add-candidate', args)
    saved = store.path.read_bytes()
    for bad in (dict(args, text='换了正文'), dict(args, request_id='b')):
        with pytest.raises(LocalTranscriptionJobError) as error:
            call('add-candidate', bad)
        assert error.value.code == 'CONFLICT'
        assert store.path.read_bytes() == saved
    original = library.save_document('初稿', '来源')
    snapshot = documents.snapshot(original)
    import_args = dict(request_id='import', project_id=topic['project_id'], expected_revision=2,
        document_id=original, expected_document_revision=snapshot['revision'], expected_document_hash=snapshot['content_hash'])
    documents.save(original, '后来修改', '来源', snapshot['revision'], snapshot['content_hash'], 'changed')
    with pytest.raises(LocalTranscriptionJobError) as error:
        call('add-candidate', import_args)
    assert error.value.code == 'CONFLICT'
    assert store.path.read_bytes() == saved
    assert call('add-candidate', args) == added


@pytest.mark.parametrize('changes', [dict(text=''), dict(text='字'*350000), dict(title='字'*161),
    dict(selected=1), dict(expected_revision=True), dict(project_id='../other'),
    dict(document_id='doc', expected_document_revision=1, expected_document_hash='a'*64), dict(approved=True)])
def test_invalid_candidate_is_zero_effect(editorial, changes):
    call, store, _ = editorial
    topic = call('create', dict(request_id='p', title='主题', expected_revision=0))
    args = dict(request_id='a', project_id=topic['project_id'], expected_revision=1, title='候选', text='完整正文')
    before = store.path.read_bytes()
    with pytest.raises(LocalTranscriptionJobError):
        call('add-candidate', dict(args, **changes))
    assert store.path.read_bytes() == before


def test_two_writers_same_revision_only_one_publishes(editorial):
    _, store, _ = editorial
    def commit(index):
        try:
            return store.commit('r'+str(index), str(index), 0,
                lambda state: (state['projects'].append(work.new_project(str(index))) or {'index': index}))
        except library.RevisionConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(commit, (1, 2)))
    assert sum(x is not None for x in results) == 1
    assert store.load()['revision'] == 1 and len(store.load()['projects']) == 1


def test_window_edits_merge_only_remote_appends_and_keep_replay_receipts(editorial):
    call, store, _ = editorial
    topic = call('create', dict(request_id='p', title='主题', expected_revision=0))
    base = store.load()
    edited = deepcopy(base)
    edited['projects'][0]['draft'] = '界面中正在写的内容'
    added = call('add-candidate', dict(request_id='a', project_id=topic['project_id'],
        expected_revision=1, title='远端候选', text='完整正文'))
    assert store.save(edited, base=base)
    result = store.load()
    assert result['projects'][0]['draft'] == '界面中正在写的内容'
    assert result['projects'][0]['candidates'][0]['id'] == added['candidate_id']
    assert 'a' in result['request_receipts'] and result['revision'] == 3
    later = deepcopy(result)
    later['projects'][0]['draft'] = '另一个窗口改了原稿'
    store.save(later)
    with pytest.raises(library.RevisionConflict):
        store.save(result, base=deepcopy(result))
    assert store.load()['projects'][0]['draft'] == '另一个窗口改了原稿'
