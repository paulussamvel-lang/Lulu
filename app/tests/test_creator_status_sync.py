from src.core.creator_workbench import CreatorStore, PENDING_STATUS
from src.core.creator_status_sync import TopicStatusSync


URL = 'https://example.feishu.cn/base/TestBase?table=tblTest'


class FeishuFixture:
    def __init__(self, statuses):
        self.statuses = statuses
        self.updated = []

    def read(self, ids):
        return {key: self.statuses[key] for key in ids if key in self.statuses}

    def write(self, outgoing):
        self.updated.append(outgoing)
        self.statuses.update(outgoing)


def test_existing_import_push_pull_and_conflict(tmp_path):
    store = CreatorStore(tmp_path)
    store.import_rows([
        {'title': title, 'key': f'/private/import.json:record:{record}', 'status': status,
         'text': f'制作状态：待选\n来源表格：{URL}\n来源记录ID：{record}'}
        for record, title, status in (
            ('recPush', '工作台已改', '候选'),
            ('recPull', '飞书已改', PENDING_STATUS),
            ('recBoth', '双方已改', '候选'),
            ('recMissing', '飞书已移除', '候选'),
        )
    ])
    service = TopicStatusSync(store)
    service.configure(URL)
    remote = FeishuFixture({'recPush': PENDING_STATUS, 'recPull': '已完成', 'recBoth': '暂存'})
    target, changes, conflicts, missing, pushed, pending = service.sync(URL, remote)
    assert remote.updated == [{'recPush': '候选'}]
    assert (missing, pushed, pending) == (1, 1, 0)
    assert [conflict[1:] for conflict in conflicts] == [('候选', '暂存')]

    unaffected = next(topic for topic in store.topics() if topic['title'] == '飞书已改')
    unaffected['analysis']['开头'] = '本机的拆解'
    store.save(unaffected)
    assert service.apply(target, changes) == 1
    pulled = next(topic for topic in store.topics() if topic['title'] == '飞书已改')
    assert pulled['analysis']['开头'] == '本机的拆解'
    assert pulled['status'] == '已完成'

    remote.statuses['recPush'] = '暂存'
    target, changes, *_ = TopicStatusSync(store).sync(URL, remote)
    assert service.apply(target, changes) == 1
    assert remote.updated == [{'recPush': '候选'}]


def test_incoming_status_cannot_overwrite_an_edit_saved_during_sync(tmp_path):
    store = CreatorStore(tmp_path)
    store.import_rows([{'title': '选题', 'key': 'feishu:base:TestBase:tblTest:record:recOne',
                        'text': '制作状态：待选'}])
    service = TopicStatusSync(store)
    target, changes, *_ = service.sync(URL, FeishuFixture({'recOne': '已完成'}))
    topic = store.topics()[0]
    topic['status'] = '候选'
    store.save(topic)
    assert service.apply(target, changes) == 0
    assert store.topics()[0]['status'] == '候选'
