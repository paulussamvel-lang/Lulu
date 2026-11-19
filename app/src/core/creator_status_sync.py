"""Synchronize the status of linked topics using the locally signed-in Feishu CLI."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import parse_qs, urlsplit

from . import creator_workbench as core


FIELD = '制作状态'
TO_FEISHU = {status: status for status in core.STATUSES}
TO_FEISHU.update({'确定制作': '制作中', '不采用': '已排除'})
SYNC_INTERVAL_MS = 5 * 60 * 1000


def table_coordinates(url):
    parts = urlsplit(core.clean_url(url))
    base = re.fullmatch(r'/base/([A-Za-z0-9]+)/?', parts.path)
    tables = parse_qs(parts.query).get('table', [])
    if (parts.scheme != 'https' or not parts.hostname.endswith(('.feishu.cn', '.larksuite.com'))
            or base is None or len(tables) != 1 or not re.fullmatch(r'tbl[A-Za-z0-9]+', tables[0])):
        raise ValueError('请粘贴飞书的具体数据表链接（包含 table=）。')
    return base[1], tables[0]


def record_status(value):
    if isinstance(value, list) and len(value) > 1:
        return None
    raw = core.cell_text(value).strip()
    normalized = core.STATUS_ALIASES.get(raw, raw) if raw else core.PENDING_STATUS
    return normalized if normalized in core.STATUSES else None


def _source_binding(topic, target):
    for source in topic['sources']:
        origin, separator, record_id = source['key'].rpartition(':record:')
        if not separator or not re.fullmatch(r'rec[A-Za-z0-9_]+', record_id):
            continue
        metadata = {}
        for line in source['text'].splitlines():
            name, _, value = line.partition('：')
            metadata[name] = value
        table_key = f'feishu:base:{target[0]}:{target[1]}'
        if origin != table_key:
            # Legacy JSON imports include the table URL and original record ID.
            if not origin.endswith('.json') or metadata.get('来源记录ID') != record_id:
                continue
            try:
                if table_coordinates(metadata.get('来源表格', '')) != target:
                    continue
            except ValueError:
                continue
        return record_id, record_status(metadata.get(FIELD, ''))
    return None


class FeishuStatusClient:
    def __init__(self, target):
        local_cli = Path.home() / '.local/bin/lark-cli'
        self.cli = str(local_cli) if local_cli.is_file() else shutil.which('lark-cli')
        if not self.cli:
            raise ValueError('未找到飞书 CLI，请先安装并登录飞书。')
        self.target = target

    def _call(self, command, *arguments):
        app_token, table_id = self.target
        env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
        try:
            result = subprocess.run([self.cli, 'base', command, '--base-token', app_token,
                                     '--table-id', table_id, '--as', 'user', *arguments],
                                    capture_output=True, text=True, timeout=25, env=env)
            response = json.loads(result.stdout or result.stderr)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise ValueError('未能确认飞书同步结果，将在下次检查时重试。') from None
        if result.returncode or response.get('ok') is not True or response.get('identity') != 'user':
            error_type = response.get('error', {}).get('type')
            if error_type in ('authentication', 'authorization'):
                raise ValueError('飞书同步需要当前用户对选题表的读写权限。请检查飞书 CLI 登录。')
            raise ValueError('飞书暂时未能同步，请检查表格权限或网络后重试。')
        return response['data']

    def read(self, record_ids):
        records = {}
        for start in range(0, len(record_ids), 100):
            args = [arg for record_id in record_ids[start:start+100] for arg in ('--record-id', record_id)]
            data = self._call('+record-get', '--field-id', FIELD, '--format', 'json', *args)
            if data.get('has_more') or data.get('fields') != [FIELD]:
                raise ValueError('飞书的「制作状态」字段不可用，选题状态仍保存在本机。')
            ids, cells = data['record_id_list'], data['data']
            if len(ids) != len(cells) or any(len(row) != 1 for row in cells):
                raise ValueError('飞书返回的状态不完整。')
            records.update((record_id, record_status(row[0])) for record_id, row in zip(ids, cells))
        return records

    def write(self, outgoing):
        data = {'update_records': {record_id: {FIELD: [TO_FEISHU[status]]}
                                   for record_id, status in outgoing.items()}}
        self._call('+record-batch-update', '--json', json.dumps(data, ensure_ascii=False))


@dataclass(frozen=True)
class StatusChange:
    topic_id: str
    record_id: str
    local: str
    agreed: str
    pushed: bool = False


class TopicStatusSync:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS status_sync_config (id INTEGER PRIMARY KEY, url TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS status_sync_agreement (
                topic_id TEXT NOT NULL, record_id TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL,
                PRIMARY KEY (topic_id, record_id, target))''')

    def configured_url(self):
        with self.store.connect() as db:
            row = db.execute('SELECT url FROM status_sync_config WHERE id=1').fetchone()
        return row[0] if row else ''

    def configure(self, url):
        target = table_coordinates(url)
        if not any(_source_binding(topic, target) for topic in self.store.topics()):
            raise ValueError('当前选题库没有绑定到这个数据表的记录。请先导入该表。')
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO status_sync_config VALUES (1, ?)', (core.clean_url(url),))

    def sync(self, url, client=None):
        target = table_coordinates(url)
        target_key = ':'.join(target)
        with self.store.connect() as db:
            known = {(topic_id, record_id): status for topic_id, record_id, status in db.execute(
                'SELECT topic_id, record_id, status FROM status_sync_agreement WHERE target=?', (target_key,))}
        topics = {}
        for topic in self.store.topics():
            binding = _source_binding(topic, target)
            if binding:
                record_id, original = binding
                if record_id in topics:
                    raise ValueError('同一飞书记录关联了多条选题，请检查导入来源。')
                topics[record_id] = (topic['id'], topic['status'], known.get((topic['id'], record_id), original))
        if not topics:
            raise ValueError('找不到绑定到这个数据表的选题。')
        client = client or FeishuStatusClient(target)
        remote = client.read(list(topics))
        changes, outgoing, conflicts, missing = [], {}, [], 0
        for record_id, (topic_id, local, base) in topics.items():
            if record_id not in remote:
                missing += 1
                continue
            cloud = remote[record_id]
            if cloud is None or (local != cloud and local != base and cloud != base):
                conflicts.append((topic_id, local, cloud))
            elif local == cloud or local == base:
                changes.append(StatusChange(topic_id, record_id, local, cloud))
            else:
                outgoing[record_id] = local

        pushed = 0
        unconfirmed = 0
        for start in range(0, len(outgoing), 100):
            batch = list(outgoing)[start:start+100]
            current = client.read(batch)
            ready = {}
            for record_id in batch:
                topic_id, local, base = topics[record_id]
                cloud = current.get(record_id)
                if record_id not in current:
                    missing += 1
                elif cloud == local:
                    changes.append(StatusChange(topic_id, record_id, local, cloud))
                elif cloud != base:
                    conflicts.append((topic_id, local, cloud))
                else:
                    ready[record_id] = local
            if ready:
                client.write(ready)
                checked = client.read(list(ready))
                for record_id, local in ready.items():
                    if checked.get(record_id) == local:
                        changes.append(StatusChange(topics[record_id][0], record_id, local, local, pushed=True))
                        pushed += 1
                    else:
                        unconfirmed += 1
        return target_key, changes, conflicts, missing, pushed, unconfirmed

    def apply(self, target, changes):
        pulled = 0
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for change in changes:
                row = db.execute('SELECT payload FROM topics WHERE id=?', (change.topic_id,)).fetchone()
                if not row:
                    continue
                topic = json.loads(row[0])
                local = record_status(topic['status'])
                if local != change.local and not change.pushed:
                    continue  # The user saved another local choice while the network request ran.
                if local == change.local and local != change.agreed:
                    topic.update(status=change.agreed, revision=topic['revision'] + 1, updated_at=core.stamp())
                    if change.agreed == '不采用' and not topic['decision'].strip():
                        topic['decision'] = '飞书已标记排除。'
                    db.execute('UPDATE topics SET revision=?, payload=? WHERE id=?', (
                        topic['revision'], json.dumps(topic, ensure_ascii=False), topic['id']))
                    pulled += 1
                db.execute('INSERT OR REPLACE INTO status_sync_agreement VALUES (?, ?, ?, ?)', (
                    change.topic_id, change.record_id, target, change.agreed))
        return pulled
