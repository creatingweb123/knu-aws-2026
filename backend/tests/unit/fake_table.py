"""plan_service 단위 테스트용 인메모리 HaruTable.

- get_item, query(KeyCondition: =, begins_with, AND / FilterExpression: <, =)
- Query의 Limit은 필터 전에 적용하고, page_size로 페이지를 잘라 LastEvaluatedKey를 돌려준다.
- transact: Put의 attribute_not_exists(PK) 조건을 모두 확인한 뒤 한꺼번에 쓴다.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from common.ddb import ConditionFailed

INDEX_KEYS = {None: ("PK", "SK"), "GSI1": ("GSI1PK", "GSI1SK"), "GSI2": ("GSI2PK", "GSI2SK")}


def _eval(cond: Any, item: dict[str, Any]) -> bool:
    expr = cond.get_expression()
    op, vals = expr["operator"], expr["values"]
    if op == "AND":
        return _eval(vals[0], item) and _eval(vals[1], item)
    name = vals[0].name
    if name not in item:
        return False
    if op == "=":
        return item[name] == vals[1]
    if op == "<":
        return item[name] < vals[1]
    if op == "begins_with":
        return str(item[name]).startswith(vals[1])
    raise NotImplementedError(op)


class FakeTable:
    name = "HaruTable"

    def __init__(self, page_size: int = 1000) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.page_size = page_size
        self.before_transact: Callable[[], None] | None = None
        self.transact_calls = 0

    def put(self, item: dict[str, Any]) -> None:
        self.items[(item["PK"], item["SK"])] = copy.deepcopy(item)

    def get_item(self, Key: dict[str, str], ConsistentRead: bool = False) -> dict[str, Any]:
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": copy.deepcopy(item)} if item else {}

    def query(self, **kw: Any) -> dict[str, Any]:
        pk, sk = INDEX_KEYS[kw.get("IndexName")]
        matched = [i for i in self.items.values() if pk in i and sk in i and _eval(kw["KeyConditionExpression"], i)]
        matched.sort(key=lambda i: i[sk], reverse=not kw.get("ScanIndexForward", True))
        start = (kw.get("ExclusiveStartKey") or {}).get("_pos", 0)
        size = min(kw.get("Limit", len(matched)), self.page_size)
        page = matched[start : start + size]
        out: dict[str, Any] = {"Items": [copy.deepcopy(i) for i in page if "FilterExpression" not in kw or _eval(kw["FilterExpression"], i)]}
        if start + size < len(matched):
            out["LastEvaluatedKey"] = {"_pos": start + size}
        return out

    def transact(self, items: list[dict[str, Any]]) -> None:
        self.transact_calls += 1
        if self.before_transact:
            hook, self.before_transact = self.before_transact, None
            hook()
        codes = []
        for op in items:
            put = op["Put"]
            exists = (put["Item"]["PK"], put["Item"]["SK"]) in self.items
            codes.append("ConditionalCheckFailed" if exists and put.get("ConditionExpression") == "attribute_not_exists(PK)" else "None")
        if "ConditionalCheckFailed" in codes:
            raise ConditionFailed(codes)
        for op in items:
            self.put(op["Put"]["Item"])

    def count(self, prefix: str) -> int:
        return sum(1 for (pk, _) in self.items if pk.startswith(prefix))
