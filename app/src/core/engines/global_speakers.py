"""Recording-wide speaker linking from acoustic evidence, never text order.

The ASR's local IDs describe turns in one chunk. They are not identities across
chunks. A caller supplies verified, normalized voice embeddings for each local
ID; this module links only sufficiently similar, non-overlapping voices.
"""
from __future__ import annotations

from dataclasses import replace
import math


def normalized_embedding(values):
    values = tuple(float(value) for value in values)
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError('声纹结果无效，未合并发言人。')
    norm = math.sqrt(sum(value * value for value in values))
    if norm < 1e-8:
        raise ValueError('声纹结果为空，未合并发言人。')
    return tuple(value / norm for value in values)


def link_speakers(segments, embeddings, *, threshold=.65, cancelled=lambda: False, allow_unresolved=False):
    """Return copied segments and audit evidence; preserve every word and clock.

    Complete-link clustering avoids chaining A~B~C when A and C disagree. Real
    overlapping turns are a cannot-link constraint. Numbering follows the first
    occurrence of the final cluster, independent of temporary chunk numbering.
    This is an acoustic hypothesis, not recognition of a person's real name.
    """
    if not .0 < threshold <= 1.:
        raise ValueError('声纹合并阈值无效。')
    ids = list(dict.fromkeys(s.speaker_id for s in segments if s.speaker_id is not None))
    missing = set(ids) - embeddings.keys()
    if not ids or (missing and not allow_unresolved):
        raise ValueError('部分发言人没有有效声纹，未推断整场身份。')
    if len(ids) > 512:
        raise ValueError('发言人片段过多，需要分组核对，未强行聚类。')
    vectors = {key: normalized_embedding(embeddings[key]) for key in ids if key not in missing}
    dimensions = {len(vector) for vector in vectors.values()}
    if len(dimensions) != 1:
        raise ValueError('声纹维度不一致。')
    intervals = {key: [] for key in ids}
    for segment in segments:
        if (segment.start is None or segment.end is None or not
                0 <= segment.start < segment.end):
            raise ValueError('需要有效时间戳才能核对声纹与原录音。')
        if segment.speaker_id is not None:
            intervals[segment.speaker_id].append((segment.start, segment.end))
    def simultaneous(left, right):
        if (max(b for a, b in intervals[left]) <= min(a for a, b in intervals[right])
                or max(b for a, b in intervals[right]) <= min(a for a, b in intervals[left])):
            return False
        return any(min(b, d) - max(a, c) > .2
                   for a, b in intervals[left] for c, d in intervals[right])
    scores = {}
    for index, left in enumerate(ids):
        if cancelled():
            raise InterruptedError('整场发言人匹配已取消。')
        for right in ids[index + 1:]:
            scores[frozenset((left, right))] = (-1. if left in missing or right in missing or simultaneous(left, right)
                else sum(a*b for a, b in zip(vectors[left], vectors[right])))
    clusters = [{key} for key in ids]
    merges = []
    while True:
        if cancelled():
            raise InterruptedError('整场发言人匹配已取消。')
        best = None
        for i, left in enumerate(clusters):
            for j in range(i + 1, len(clusters)):
                right = clusters[j]
                score = min(scores[frozenset((a, b))] for a in left for b in right)
                if score >= threshold and (best is None or score > best[0]):
                    best = score, i, j
        if best is None:
            break
        score, i, j = best
        merges.append(dict(left=sorted(clusters[i]), right=sorted(clusters[j]), similarity=score))
        clusters[i] |= clusters.pop(j)
    order = {key: index for index, key in enumerate(ids)}
    clusters.sort(key=lambda group: min(order[key] for key in group))
    resolved = [group for group in clusters if not group & missing]
    mapping = {key: number for number, group in enumerate(resolved, 1) for key in group}
    result = [replace(segment, speaker_id=mapping.get(segment.speaker_id)) for segment in segments]
    return result, dict(scope='recording', speaker_count=len(resolved), unresolved_local_ids=sorted(missing),
        local_to_global={str(key): value for key, value in mapping.items()},
        threshold=threshold, merges=merges,
        notice='按声纹自动匹配整场发言人；编号不代表真实姓名，声线相似或重叠讲话需核对。')
