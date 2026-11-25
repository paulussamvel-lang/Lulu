"""Creator strategy records shared across pre-production and topic drafts."""
import json
from uuid import uuid4

from .creator_workbench import new_topic, stamp


DIRECTION_FIELDS = (
    ('track', '候选赛道', '具体到一个人群和一个问题，例如：AI 新手做第一条教程'),
    ('audience', '目标观众', '谁正在遇到这个问题？'),
    ('scene', '真实处境', '在什么场景遇到什么困难？他现在怎么解决？'),
    ('resources', '经验与资源', '你有什么实测经验、可拍素材或能获得的资源？'),
    ('sustainability', '长期制作条件', '能持续拍什么、愿不愿做、哪些条件缺失？'),
    ('evidence', '需求与可展示证据', '观众原话、实测、可拍画面、链接或时间码。写清证据能证明什么。'),
)
RESEARCH_FIELDS = (
    ('sales', '同品类销售话术', '对方如何回答一个真实顾虑？记录原句和出处。'),
    ('interests', '同受众兴趣与开头', '找面向同一类人的账号，记录话题、开头和参考原因。'),
    ('format', '视频拍法与参考片段', '视频链接｜时间码｜参考选题、开头、拍法或剪辑｜可借鉴的动作'),
    ('values', '圈子的共同价值观（选填）', '有原话、评论或作品能支持时再记。'),
)
POSITION_FIELDS = (
    ('identity', '我是谁', '你的经验、身份和视角是什么？'),
    ('promise', '持续提供什么', '用一句话说明为这类观众提供什么。'),
    ('retention', '观众为什么留下', '关注后能持续获得什么？哪些经验或证据是你能提供的？'),
    ('homepage', '主页与内容方向', '账号简介、置顶内容、长期栏目和示例选题。'),
    ('first_topic', '第一条准备拍什么', '写一道能回答真实问题、也能拿出证据的题目。'),
)
SCHEDULE_FIELDS = (
    ('reach', '被看见', '触达目标观众。课堂练习可写两条触达题。'),
    ('need', '被需要', '让观众意识到需求。课堂练习可写两条种草题。'),
    ('trust', '被认可', '用证据回答购买顾虑。课堂练习可写两条解顾虑题。'),
    ('choose', '被选择', '解释适用条件，并给出一个明确的下一步。'),
)
FIELDS = DIRECTION_FIELDS + RESEARCH_FIELDS + POSITION_FIELDS + SCHEDULE_FIELDS
READINESS = (('audience', '目标观众'), ('scene', '真实处境'), ('evidence', '可展示证据'))
PRODUCTION_SECTIONS = ('workflow', 'script', 'shoot', 'post', 'publish')


def new_plan():
    return dict(id=uuid4().hex, revision=0, updated_at='', business_card_id='',
                **{key: '' for key, _, _ in FIELDS})


class PlanningStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS creator_plans ('
                       'id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')

    def plans(self):
        with self.store.connect() as db:
            return [json.loads(data) for data, in db.execute('SELECT payload FROM creator_plans ORDER BY rowid DESC')]

    def save(self, plan):
        value = dict(plan, track=plan['track'].strip(), revision=plan['revision'] + 1, updated_at=stamp())
        if not value['track']:
            raise ValueError('请先填写候选赛道的名称。')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT revision FROM creator_plans WHERE id=?', (plan['id'],)).fetchone()
            if (previous[0] if previous else 0) != plan['revision']:
                raise ValueError('这份调研已经在另一个窗口更新。请核对后再保存。')
            db.execute('INSERT INTO creator_plans VALUES (?, ?, ?) '
                       'ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, payload=excluded.payload',
                       (value['id'], value['revision'], json.dumps(value, ensure_ascii=False)))
        return value


def draft_fields(plan):
    return dict(title=plan['first_topic'], audience=plan['audience'], scene=plan['scene'],
                evidence=plan['evidence'], references=plan['format'])


def create_topic_from_plan(plan, draft):
    if not plan['revision']:
        raise ValueError('请先保存调研记录。')
    missing = [label for key, label in READINESS if not draft[key].strip()]
    if missing:
        raise ValueError('请补齐' + '、'.join(missing) + '。')
    topic = new_topic(draft['title'])
    topic['brief'].update({
        '目标观众': draft['audience'].strip(),
        '具体痛点': draft['scene'].strip(),
        '证据与待核实': draft['evidence'].strip(),
    })
    refs = draft['references'].strip()
    if refs:
        # A reference can appear in several topics. Keep the original text and timecodes
        # without claiming ownership of the source's unique import key.
        topic['sources'][0].update(title='账号定位的对标片段', text=refs)
    topic['planning_context'] = {key: plan[key] for key in
                                 ('id', 'revision', 'track', 'identity', 'promise', 'business_card_id')}
    return topic
