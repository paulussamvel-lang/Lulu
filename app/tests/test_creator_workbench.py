import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.core import creator_workbench as core


def test_import_is_transactional_deduplicated_and_retains_edits(tmp_path):
    store = core.CreatorStore(tmp_path)
    rows = [dict(title='参考', source='https://www.douyin.com/video/123?utm_source=a', text='原始内容')]
    assert store.import_rows(rows) == (1,0)
    topic = store.topics()[0]
    topic['analysis']['开头'] = '手工分析'; store.save(topic)
    rows[0]['source'] = 'https://www.douyin.com/video/123?utm_source=b'
    rows[0]['text'] = '新的原文'
    assert store.import_rows(rows) == (0,1)
    assert store.topics()[0]['analysis']['开头'] == '手工分析'
    assert store.topics()[0]['sources'][0]['text'] == '原始内容'
    with pytest.raises(ValueError):
        store.import_rows([dict(title='应回滚', source='https://example.test/a'),dict(title='')])
    assert len(store.topics()) == 1


def test_concurrent_edit_cannot_overwrite_and_different_topics_can_save(tmp_path):
    store = core.CreatorStore(tmp_path)
    topic = core.new_topic('甲'); store.save(topic)
    other = deepcopy(topic)
    topic['title'] = '已经保存的甲'; store.save(topic)
    other['title'] = '过期甲'
    with pytest.raises(ValueError, match='其他窗口'): store.save(other)
    second = core.new_topic('乙'); store.save(second)
    assert {t['title'] for t in store.topics()} == {'已经保存的甲','乙'}


def test_csv_multiple_rows_with_no_link_are_not_collapsed(tmp_path):
    path = tmp_path/'topics.csv'; path.write_text('标题,痛点\n甲,问题甲\n乙,问题乙\n',encoding='utf-8-sig')
    preview = core.local_preview(path)
    rows = core.rows_from_records(preview['records'], origin=preview['origin'])
    store = core.CreatorStore(tmp_path/'db')
    assert store.import_rows(rows) == (2,0)
    assert store.import_rows(rows) == (0,2)


def test_feishu_cells_link_and_record_identity():
    rows = core.rows_from_records([{'record_id':'recExample','fields':{'标题':[{'text':'原始标题'}],
        '视频链接':{'text':'点击查看','link':'https://example.test/video'},'理由':'具体问题'}}],
        origin='https://example.feishu.cn/base/ExampleBase?table=tblExample')
    assert rows[0]['source'] == 'https://example.test/video'
    assert rows[0]['title'] == '原始标题'
    assert ':record:recExample' in rows[0]['key']
    assert '具体问题' in rows[0]['text']


def test_rejected_status_requires_reason_and_private_source_urls_blocked(tmp_path):
    store = core.CreatorStore(tmp_path); topic = core.new_topic('一')
    topic['status'] = '不采用'
    with pytest.raises(ValueError,match='原因'): store.save(topic)
    topic['decision'] = '没有可演示的结果'; store.save(topic)
    for url in ('https://user:password@example.test/a','file:///tmp/a','https://example.test/a?access_token=example'):
        with pytest.raises(ValueError): core.clean_url(url)


@pytest.mark.parametrize('value', ['NaN','-1','1:61','1:2:3:4','inf','nonsense'])
def test_invalid_time_rejected(value):
    with pytest.raises(ValueError): core.parse_time(value)


def test_segments_validate_real_duration_and_keep_repeated_copy():
    assert core.parse_time('01:02.5') == 62500
    value = core.validate_segment(dict(start='1',end='4',role='开头',copy='真的重复。真的重复。'),5000)
    assert value['copy'] == '真的重复。真的重复。'
    with pytest.raises(ValueError): core.validate_segment(dict(start='1',end='6'),5000)


def test_feishu_readonly_pagination_and_document_revision(monkeypatch):
    from src.core import feishu, feishu_documents
    from contextlib import nullcontext
    monkeypatch.setattr(feishu,'user_session',nullcontext)
    monkeypatch.setattr(feishu,'_user_token',lambda:'not-a-real-token')
    calls = []
    def api(method,path,token,**kwargs):
        calls.append((method,path,kwargs))
        if '/fields' in path: return {'items':[{'field_name':'标题'}]}
        if '/records' in path:
            if kwargs.get('params',{}).get('page_token'): return {'items':[{'record_id':'b','fields':{'标题':'乙'}}]}
            return {'items':[{'record_id':'a','fields':{'标题':'甲'}}],'has_more':True,'page_token':'next'}
        return {'document':{'title':'文档'}}
    monkeypatch.setattr(feishu,'_api',api)
    value = core.feishu_preview('https://example.feishu.cn/base/Example?table=tblExample')
    assert len(value['records']) == 2
    monkeypatch.setattr(feishu_documents,'snapshot',lambda _: (4,[{'text':{'elements':[{'text_run':{'content':'原文'}}]}}]))
    value = core.feishu_preview('https://example.feishu.cn/docx/Example')
    assert value['rows'][0]['source_revision'] == 4
    assert all(c[0] == 'GET' for c in calls)


def test_ai_text_only_explicit_model_no_tools_and_no_invented_visuals():
    topic = core.new_topic('测试'); topic['transcript'] = '先给出结果，然后演示，最后总结。'
    response = {k:'模型建议' for k in core.DIMENSIONS}
    generate = Mock(return_value={'text':json.dumps(response,ensure_ascii=False),'calls':[]})
    result = core.assist_analysis(topic,{'model':'chosen'},generate=generate)
    assert result['画面'] == '需观看视频后补充。'
    assert result['剪辑'] == '需观看视频后补充。'
    assert generate.call_args.kwargs['tools'] == ()
    assert generate.call_args.args[0]['model'] == 'chosen'
    assert topic['analysis']['开头'] == ''
    generate.return_value = {'text':'{}','calls':[]}
    with pytest.raises(ValueError): core.assist_analysis(topic,{'model':'chosen'},generate=generate)


def test_public_page_rejects_private_network_before_fetch(monkeypatch):
    monkeypatch.setattr(core.socket,'getaddrinfo',lambda *_:[(None,None,None,None,('127.0.0.1',80))])
    get = Mock()
    with pytest.raises(ValueError): core.public_page('https://example.test',get=get)
    get.assert_not_called()


def test_markdown_video_links_and_imported_screening_status_are_preserved(tmp_path):
    records = [dict(题目='历史排除',链接='[参考](https://www.douyin.com/video/123)',制作状态=['已排除'],排除原因='没有事实依据',标签='工具'),
               dict(题目='历史完成',链接='[参考](https://www.douyin.com/video/456)',制作状态=['已完成'])]
    rows = core.rows_from_records(records,origin='/example/topics.json')
    assert rows[0]['source']=='https://www.douyin.com/video/123'
    store=core.CreatorStore(tmp_path);assert store.import_rows(rows)==(2,0)
    topics={t['title']:t for t in store.topics()}
    assert topics['历史排除']['status']=='不采用'
    assert topics['历史排除']['decision']=='没有事实依据'
    assert topics['历史排除']['tags']=='工具'
    assert topics['历史完成']['status']=='已完成'
    assert core.clean_url('[参考](https://example.test/a)')=='https://example.test/a'
