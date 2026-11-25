"""Reusable product analysis cards and explicit topic adoption."""
from copy import deepcopy
import json
from uuid import uuid4

from .creator_workbench import stamp


PRODUCT_FIELDS = (
    ('product', '产品或服务', '实际卖的是什么？写清具体商品或服务'),
    ('payer', '实际付款者', '谁决定付款？'),
    ('scene', '具体处境', '他在什么场景开始考虑购买？'),
    ('concern', '购买顾虑', '客户在比较或付款前问过什么？'),
)
DETAIL_FIELDS = (
    ('purchase', '营销与销售', '客户在哪里认识、咨询、比较并下单？'),
    ('delivery', '交付', '客户买完收到什么？如何交付？'),
    ('bottleneck_note', '主要卡点', '哪件事最影响结果？依据是什么？'),
    ('verification', '下一次验证', '可以先向谁核实，或试改哪一步？'),
    ('user', '实际使用者', '谁使用或受益？与付款者相同时可以留空'),
    ('reason', '购买理由', '在这个场景里，用户为什么愿意选这个方案？'),
    ('alternative', '备选方案', '客户会和哪个方案比较？'),
)
BOTTLENECKS = ('待判断', '产品', '营销与销售', '交付')
MOTIVES = ('', '生活必需', '自我投资', '健康维护', '休闲享乐', '亲密关系', '社交维系')
EVIDENCE_STATES = ('待验证', '已核实')
GOALS = {
    '被看见': '用真实处境里的问题让目标人群愿意停下来。',
    '被需要': '展示触发需求的场景，让观众辨认自己遇到的问题。',
    '被认可': '用实测、对照或说明，帮观众判断一个购买顾虑。',
    '被选择': '说清可兑现的条件和下一步购买路径。',
}
DRAFT_FIELDS = (
    ('audience', '为谁', '目标观众'),
    ('scene', '哪个场景', '具体痛点'),
    ('question', '要回应的疑问', '具体痛点'),
    ('benefit', '观众能得到什么', '观众收获'),
    ('proof', '可拍证明或待补证据', '证据与待核实'),
)


def new_card():
    return dict(id=uuid4().hex, revision=0, updated_at='', evidence=[], bottleneck=BOTTLENECKS[0],
                motive='', **{key: '' for key, *_ in (*PRODUCT_FIELDS, *DETAIL_FIELDS)})


class BusinessStore:
    def __init__(self, topics):
        self.topics = topics
        with topics.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS business_cards '
                       '(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')

    def cards(self):
        with self.topics.connect() as db:
            return [json.loads(payload) for payload, in db.execute(
                'SELECT payload FROM business_cards ORDER BY rowid DESC')]

    def save(self, card):
        value = deepcopy(card)
        value['product'] = value['product'].strip()
        if not value['product']:
            raise ValueError('请先填写一个具体的产品或服务。')
        if value['bottleneck'] not in BOTTLENECKS or value['motive'] not in MOTIVES:
            raise ValueError('产品卡的选项无法识别，请重新选择。')
        for evidence in value['evidence']:
            if evidence['status'] not in EVIDENCE_STATES:
                raise ValueError('证据状态无法识别。')
            if evidence['status'] == '已核实' and not (evidence['note'].strip() and evidence['source'].strip()):
                raise ValueError('标为已核实的证据需要同时填写内容和来源。')
        value.update(revision=card['revision'] + 1, updated_at=stamp())
        with self.topics.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT revision FROM business_cards WHERE id=?', (card['id'],)).fetchone()
            if (prior[0] if prior else 0) != card['revision']:
                raise ValueError('产品卡已在其他窗口更新。当前输入已保留，请先核对已保存版本。')
            db.execute('INSERT INTO business_cards VALUES (?,?,?) '
                       'ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, payload=excluded.payload',
                       (value['id'], value['revision'], json.dumps(value, ensure_ascii=False)))
        return value


def evidence_text(evidence):
    if evidence is None:
        return '待补证据：记录一项能帮助观众判断的实拍、对照或来源。'
    lines = [f'{evidence["status"]} · {evidence["note"] or "待补证据内容"}']
    if evidence['source']:
        lines.append('来源 ' + evidence['source'])
    return '\n'.join(lines)


def draft_fields(card, goal, evidence):
    lessons = {
        '被看见': '看懂这个场景中值得注意的问题',
        '被需要': '判断自己是否遇到同样的问题',
        '被认可': '知道如何验证顾虑，形成自己的判断',
        '被选择': '知道适用条件和下一步如何购买',
    }
    audience = card['payer']
    if card['user'] and card['user'] != card['payer']:
        audience = '\n'.join(part for part in (f'付款者 {audience}' if audience else '', f'使用者 {card["user"]}') if part)
    benefit = lessons[goal]
    focus = card['concern'] if goal == '被认可' else card['reason']
    if focus:
        benefit += '\n具体要帮助判断的问题：' + focus
    return dict(audience=audience, scene=card['scene'], question=card['concern'],
                benefit=benefit, proof=evidence_text(evidence))


def adopt_draft(topic, card, goal, fields, selected, evidence):
    if goal not in GOALS or card['revision'] < 1:
        raise ValueError('请保存产品卡并选择这条选题的主任务。')
    result = deepcopy(topic)
    chosen = {}
    for key, _, target in DRAFT_FIELDS:
        value = fields[key].strip()
        if key in selected and value:
            chosen[target] = '\n'.join(part for part in (chosen.get(target, ''), value) if part)
    result['brief'].update(chosen)
    result['business_analysis'] = dict(
        card_id=card['id'], card_revision=card['revision'], goal=goal,
        snapshot=deepcopy(card), evidence=deepcopy(evidence), draft=dict(fields), adopted=sorted(selected),
    )
    return result


def export_lines(link):
    card = link['snapshot']
    lines = ['', '## 商业分析', f'{card["product"]} · 版本 {link["card_revision"]}',
             f'选题主任务：{link["goal"]}']
    for key, label, _ in (*PRODUCT_FIELDS, *DETAIL_FIELDS):
        if card[key]:
            lines.append(f'{label}：{card[key]}')
    for key, label in (('bottleneck', '卡点所在环节'), ('motive', '消费动机')):
        if card[key]:
            lines.append(f'{label}：{card[key]}')
    lines.extend(('', '### 本条草稿参考的证据', evidence_text(link.get('evidence'))))
    if card['evidence']:
        lines.extend(('', '### 产品卡证据'))
        for item in card['evidence']:
            lines.extend(('', evidence_text(item)))
    return lines
