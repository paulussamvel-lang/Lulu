import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.core import content_workbench as work


def project():
    value = work.new_project('工具演示')
    work.add_candidate(value, '甲稿', '先说具体问题\n再演示解决过程', document_id='original-1')
    work.add_candidate(value, '乙稿', '另一种开头\n具体结果')
    return value


def response(value):
    return dict(comparison='甲稿适合作主线，乙稿补充结果。', documents=[
        dict(id=c['id'], score=80, summary='有明确演示，需要缩短开头。', marks=[
            dict(start=0, end=0, label='improve', reason='先给出结果')]) for c in value['candidates']])


def test_review_uses_only_selected_full_text_and_preserves_model():
    value = project()
    value['candidates'][1]['selected'] = False
    generate = Mock(return_value=dict(text=json.dumps(dict(comparison='用甲稿', documents=[response(value)['documents'][0]])), calls=[]))
    result = work.run_review(value, dict(model='chosen-model', provider='chosen-provider'), generate=generate)
    assert result['model'] == 'chosen-model'
    assert generate.call_args.kwargs['tools'] == ()
    payload = generate.call_args.args[2][0]['content']
    assert '再演示解决过程' in payload and '另一种开头' not in payload
    assert value['review'] is None


@pytest.mark.parametrize('mutation', ['duplicate', 'missing', 'wrong_range', 'overlap', 'boolean_score'])
def test_invalid_reviews_cannot_be_saved(mutation):
    value, output = project(), None
    output = response(value)
    if mutation == 'duplicate': output['documents'][1]['id'] = output['documents'][0]['id']
    if mutation == 'missing': output['documents'].pop()
    if mutation == 'wrong_range': output['documents'][0]['marks'][0]['end'] = 99
    if mutation == 'overlap': output['documents'][0]['marks'] *= 2
    if mutation == 'boolean_score': output['documents'][0]['score'] = True
    with pytest.raises(ValueError): work.validate_review(value, json.dumps(output))


def test_manual_selection_and_assembly_keep_origin_and_previous_draft():
    value = project()
    candidate = value['candidates'][0]
    clip = work.add_clip(value, candidate['id'], '再演示解决过程')
    value['draft'] = '之前写好的稿子'
    assert work.assemble(value) == '再演示解决过程'
    assert value['draft_history'][-1]['text'] == '之前写好的稿子'
    assert clip['document_id'] == 'original-1'
    assert candidate['text'] == '先说具体问题\n再演示解决过程'
    assert clip['source_hash'] == work.digest(candidate['text'])


def test_changed_original_invalidates_review_and_copies_keep_clip_snapshot():
    value = project()
    before = work.review_hash(value)
    work.add_clip(value, value['candidates'][0]['id'], '先说具体问题')
    value['candidates'][0]['text'] = '修改后的副本'
    assert work.review_hash(value) != before
    assert value['clips'][0]['text'] == '先说具体问题'


def test_concurrent_save_is_refused_and_previous_version_survives(tmp_path):
    store = work.WorkbenchStore(tmp_path)
    first = store.load()
    first['projects'].append(project())
    store.save(first)
    stale = store.load()
    first['projects'][0]['draft'] = '新稿'
    store.save(first)
    with pytest.raises(RuntimeError): store.save(stale)
    assert store.load()['projects'][0]['draft'] == '新稿'
    assert json.loads((tmp_path/'workspace.previous.json').read_text())['projects'][0]['draft'] == ''


def test_no_silent_truncation_or_empty_cloud_request():
    value = project()
    value['candidates'][0]['text'] = '字' * 60000
    with pytest.raises(ValueError, match='不会自动截断'): work.review_input(value)
    value['candidates'][0]['text'] = ''
    with pytest.raises(ValueError, match='空正文'): work.review_input(value)


@pytest.mark.parametrize('schema_version', [1, 2])
def test_shiju_import_preserves_words_selections_draft_and_review_evidence(schema_version):
    original = dict(id='old-topic', title='旧选题', audience='创作者', documents=[
        dict(id='old-document', title='原文', text='完整原文\n第二段')],
        selections=[dict(documentId='old-document', documentTitle='原文', text='第二段')],
        draft='已编辑的成稿', analysis=dict(model='old-model', comparison='历史评分'))
    imported = work.import_shiju(dict(schemaVersion=schema_version, revision=4, topics=[original]))[0]
    assert imported['candidates'][0]['text'] == '完整原文\n第二段'
    assert imported['clips'][0]['text'] == '第二段'
    assert imported['draft'] == '已编辑的成稿'
    assert imported['legacy_topic']['analysis']['model'] == 'old-model'
    assert imported['review'] is None
