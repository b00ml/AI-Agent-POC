"""
Prompt 回归测试（设计文档2.0 §3.6⑥）：对固件单据构建 AI 复核提示词，
与快照比对哈希，防止「改提示词/改检索静默劣化」。离线运行，不调用 LLM。

用法：
    python tools/prompt_regression.py            # 与快照比对
    python tools/prompt_regression.py --update   # 重新生成快照（提示词有意变更后执行）
"""

import os
import sys
import json
import hashlib
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("LLM_REVIEW_API_KEY", "dummy-for-prompt-snapshot")  # 仅构建提示词，不调用
os.environ.setdefault("RETRIEVAL_MODE", "keyword")  # 快照固定 keyword 模式（hybrid 由检索评测覆盖）

from core.llm_reviewer import LLMReviewer  # noqa: E402

SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "labels", "prompt_snapshot.json",
)

STANDARDS = [
    {"jobLevel": "STAFF", "cityTier": "TIER2", "hotelCapPerNightFen": 42000,
     "mealAllowancePerDayFen": 10000, "cityTransportPerDayFen": 2000,
     "longDistanceClass": "TRAIN_2ND"},
]
CITIES = [{"name": "成都", "tier": "TIER2"}]

FIXTURES = [
    {
        "id": "P01-住宿超标",
        "claim": {"id": "BX-P01", "claimNo": "BX-P01", "jobLevel": "STAFF",
                  "departmentName": "财务部", "claimType": "TRAVEL",
                  "trip": {"city": "成都", "nights": 2},
                  "lines": [{"lineNo": 1, "expenseType": "HOTEL",
                             "amountFen": 100000, "description": "住宿两晚"}]},
        "approvals": [],
        "ocr": {},
        "rules": {"result": "REJECT", "violations": ["OVER_STANDARD_HOTEL"],
                  "reasons": ["住宿费超标"]},
    },
    {
        "id": "P02-加班打车",
        "claim": {"id": "BX-P02", "claimNo": "BX-P02", "jobLevel": "STAFF",
                  "departmentName": "财务部", "claimType": "TRAVEL",
                  "trip": {"city": "成都", "nights": 2},
                  "lines": [{"lineNo": 1, "expenseType": "CITY_TRANSPORT",
                             "amountFen": 3000, "description": "加班打车回家"}]},
        "approvals": [{"action": "APPROVE", "stage": "事前审批", "comment": ""}],
        "ocr": {},
        "rules": {"result": "APPROVE", "violations": [], "reasons": []},
    },
    {
        "id": "P03-城市未知FLAG",
        "claim": {"id": "BX-P03", "claimNo": "BX-P03", "jobLevel": "STAFF",
                  "departmentName": "财务部", "claimType": "TRAVEL",
                  "trip": {"city": "拉萨", "nights": 2},
                  "lines": [{"lineNo": 1, "expenseType": "HOTEL",
                             "amountFen": 80000, "description": "住宿两晚"}]},
        "approvals": [],
        "ocr": {},
        "rules": {"result": "FLAG", "violations": [], "reasons": ["城市不在档次表"]},
    },
]


def build_prompts() -> dict:
    reviewer = LLMReviewer()
    tm = __import__("data.travel_data", fromlist=["TravelDataManager"]).TravelDataManager(client=None)
    tm._standards = STANDARDS
    tm._build_standards_cache()
    tm._city_tiers = CITIES
    tm._build_city_cache()

    out = {}
    for fx in FIXTURES:
        prompt = reviewer._build_prompt(
            fx["claim"], fx["approvals"],
            travel_standards=tm.list_standards(),
            ocr_fields=fx["ocr"],
            rules_opinion=fx["rules"],
        )
        out[fx["id"]] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Prompt 回归（快照比对）")
    parser.add_argument("--update", action="store_true", help="重新生成快照")
    args = parser.parse_args()

    current = build_prompts()

    if args.update or not os.path.exists(SNAPSHOT_PATH):
        with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        print(f"✓ 快照已{'更新' if args.update else '生成'}: {SNAPSHOT_PATH}")
        print(json.dumps(current, indent=2))
        return

    with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
        snapshot = json.load(f)

    mismatches = [
        {"id": k, "snapshot": snapshot.get(k), "current": v}
        for k, v in current.items() if snapshot.get(k) != v
    ]
    missing = [k for k in snapshot if k not in current]

    print("=== Prompt 回归（keyword 模式快照）===")
    for k, v in current.items():
        status = "PASS" if snapshot.get(k) == v else "FAIL"
        print(f"  [{status}] {k}")
    if missing:
        print(f"  [FAIL] 快照中存在但当前未构建: {missing}")

    if mismatches or missing:
        print(f"\n✗ 提示词与快照不一致（{len(mismatches)} 处变化，{len(missing)} 处缺失）。")
        print("  若为有意变更：python tools/prompt_regression.py --update 后重跑，并在 PR 说明。")
        sys.exit(1)
    print("✓ 全部提示词与快照一致。")


if __name__ == "__main__":
    main()
