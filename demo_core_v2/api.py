"""Offline facade. No approvals, evaluation formulas, database, or network."""
import copy
import hashlib
import json
from pathlib import Path
from .rules import SCENES


class HandoffError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def to_json(value):
    """Strict UTF-8-compatible JSON; preserves null and rejects NaN."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)


def find_evidence(fragments, query, limit):
    term = query.strip().casefold()
    return [copy.deepcopy(f) for f in fragments if not term or term in to_json(f).casefold()][:limit]


class DemoService:
    def __init__(self):
        self.root = Path(__file__).resolve().parents[1]
        try:
            manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
            for item in manifest['files']:
                path = (self.root / item['path']).resolve()
                if not path.is_relative_to(self.root) or not path.is_file():
                    raise HandoffError('SNAPSHOT_CHANGED', '快照成员缺失或越界')
                if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                    raise HandoffError('SNAPSHOT_CHANGED', '快照哈希不匹配')
            self.cases = self._load('cases.json')
            self.evidence = self._load('evidence.json')
            self.history = self._load('b_history.json')
            self.verified_status = self._load('verified_status.json')
        except HandoffError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HandoffError('INVALID_SNAPSHOT', '快照不可读取或结构无效') from exc

    def _load(self, name):
        return json.loads((self.root / 'demo_data' / name).read_text(encoding='utf-8'))

    def _case(self, case_id):
        if not isinstance(case_id, str):
            raise HandoffError('INVALID_ARGUMENT', 'case_id须为字符串')
        value = next((c for c in self.cases if c['id'] == case_id), None)
        if value is None:
            raise HandoffError('CASE_NOT_FOUND', '没有该地区案例；不得套用其他地区数据')
        return copy.deepcopy(value)

    def list_cases(self):
        return copy.deepcopy(self.cases)

    def evidence_query(self, case_id, query='', limit=10):
        case = self._case(case_id)
        if not isinstance(query, str) or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 20:
            raise HandoffError('INVALID_ARGUMENT', 'query最多200字符；limit为1至20整数')
        fragments = [f for f in self.evidence['fragments'] if f['id'] in case['evidence_ids']]
        hits = find_evidence(fragments, query, limit)
        source_ids = {f['source_id'] for f in hits}
        return {'mode': 'rule_retrieval', 'case_id': case_id, 'query': query,
                'hits': hits, 'sources': copy.deepcopy([s for s in self.evidence['sources'] if s['id'] in source_ids]),
                'status': 'matched' if hits else 'insufficient_data',
                'limitations': ['仅冻结片段字面检索；未命中不等于不存在，不代表政策穷尽检索']}

    def analyze_region(self, case_id):
        case = self._case(case_id)
        rule = SCENES[case['scene']]
        return {'mode': 'rule_analysis', 'case': case, 'scene': rule['name'],
                'evidence': self.evidence_query(case_id)['hits'],
                'suggestion': rule['action'], 'verification_needed': copy.deepcopy(rule['requirements']),
                'N': None, 'D': None, 'S': None, 'G': None, 'T': None,
                'conclusion_status': 'draft_pending_A',
                'limitations': ['统计背景仅支持进一步核实场景需求，不证明适飞或可落地',
                                '设施年不等于任务年；书面裁定不替代当前本人确认与scope签发',
                                '播种面积不等同于耕地面积，不能替代B指标输入']}

    def explain_evaluation(self, case_id):
        case = self._case(case_id)
        return {'mode': 'historical_result_read', 'case_id': case_id,
                'scope': '同一黑龙江省历史快照；不是所选任务的独立计算',
                'result': copy.deepcopy(self.history),
                'explanation': '历史输入需求不完整，D/S/G/T保持null；计数0不能解释为真实零需求。当前未附本人scope签发，N未知。',
                'next_steps': ['B本人核对历史快照与版本并确认展示范围',
                               'A在受控本地环境完成当前任务审核及有限K scope签发',
                               'B独立发布来源合格的承载数据后再验收依赖它的指标'],
                'A_review': case['A_review']}

    def evaluate_online(self, case_id):
        self._case(case_id)
        raise HandoffError('B_ENGINE_NOT_BUNDLED', '本包只读历史状态，在线计算须B提供冻结引擎、输入与正式契约')

    def read_verified_result(self, case_id):
        self._case(case_id)
        return copy.deepcopy(self.verified_status)

    def call_tool(self, name, arguments):
        methods = {'list_cases': self.list_cases, 'analyze_region': self.analyze_region,
                   'explain_evaluation': self.explain_evaluation, 'evidence_query': self.evidence_query,
                   'evaluate_online': self.evaluate_online, 'read_verified_result': self.read_verified_result}
        if not isinstance(name, str) or name not in methods:
            raise HandoffError('TOOL_NOT_ALLOWED', '未开放此工具')
        if not isinstance(arguments, dict):
            raise HandoffError('INVALID_ARGUMENT', 'arguments须为对象')
        try:
            return methods[name](**arguments)
        except TypeError as exc:
            raise HandoffError('INVALID_ARGUMENT', '参数缺失或多余') from exc
