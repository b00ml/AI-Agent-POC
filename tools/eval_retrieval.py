"""
制度知识库检索评测（设计文档 2.0 §3.4）

对 data/labels/policy_retrieval_labels.json 的场景问句计算 Recall@8 / MRR，
keyword 基线与 hybrid 混合检索同场对比。

用法：
  python tools/eval_retrieval.py                          # 两种模式都跑
  python tools/eval_retrieval.py --mode hybrid            # 只跑指定模式
  python tools/eval_retrieval.py --mode hybrid --min-recall 0.9   # 门禁（不达标 exit 1）
"""

import os
import sys
import json
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.retrieval import PolicyRetriever

LABELS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "labels", "policy_retrieval_labels.json",
)
DEFAULT_INDEX = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "rag_index", "index.json",
)

from core.retrieval import QUERY_KEYWORDS


def keywords_for(query: str) -> set:
    return {tag for key, tag in QUERY_KEYWORDS.items() if key in query}


def is_hit(chunk: dict, case: dict) -> bool:
    meta = chunk.get("metadata", {})
    for e in case.get("expect_any", []):
        if meta.get("doc") == e.get("doc") and meta.get("article") == e.get("article"):
            return True
    for s in case.get("expect_contains", []):
        if s in chunk.get("content", ""):
            return True
    return False


def evaluate(mode: str, labels: dict, index_path: str) -> dict:
    retriever = PolicyRetriever(index_path=index_path, mode=mode)
    hits = 0
    rr_sum = 0.0
    details = []
    t_all = 0.0
    for case in labels["cases"]:
        _t0 = time.perf_counter()
        chunks = retriever.retrieve(
            query_text=case["query"],
            keywords=keywords_for(case["query"]),
            top_k=8,
        )
        t_all += time.perf_counter() - _t0
        rank = next((i + 1 for i, c in enumerate(chunks) if is_hit(c, case)), None)
        if rank:
            hits += 1
            rr_sum += 1.0 / rank
        details.append({"id": case["id"], "hit": rank is not None, "rank": rank})
    n = len(labels["cases"]) or 1
    return {
        "requestedMode": mode,
        "effectiveMode": retriever.mode,
        "denseAvailable": retriever.dense_available,
        "cases": len(labels["cases"]),
        "recallAt8": round(hits / n, 4),
        "mrr": round(rr_sum / n, 4),
        "avgMsPerQuery": round(t_all * 1000 / n, 1),
        "misses": [d for d in details if not d["hit"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="制度知识库检索评测")
    parser.add_argument("--mode", choices=["keyword", "hybrid", "both"], default="both")
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--min-recall", type=float, default=None,
                        help="门禁：指定模式的 Recall@8 低于该值时 exit 1")
    args = parser.parse_args()

    with open(LABELS_PATH, "r", encoding="utf-8") as f:
        labels = json.load(f)

    modes = ["keyword", "hybrid"] if args.mode == "both" else [args.mode]
    results = {}
    for mode in modes:
        res = evaluate(mode, labels, args.index)
        results[mode] = res
        print(f"\n=== 检索评测 [{res['requestedMode']}]（实际生效 {res['effectiveMode']}，dense={res['denseAvailable']}）===")
        print(f"用例数: {res['cases']}")
        print(f"Recall@8: {res['recallAt8']:.4f}")
        print(f"MRR:      {res['mrr']:.4f}")
        print(f"单条平均耗时: {res['avgMsPerQuery']} ms")
        if res["misses"]:
            print(f"未命中: {[(m['id'], m['rank']) for m in res['misses']]}")

    if "keyword" in results and "hybrid" in results and results["hybrid"]["denseAvailable"]:
        kw, hy = results["keyword"]["recallAt8"], results["hybrid"]["recallAt8"]
        print(f"\n[对比] hybrid {hy:.4f} vs keyword 基线 {kw:.4f}（{'提升' if hy >= kw else '回退'} {abs(hy - kw):.4f}）")

    if args.min_recall is not None:
        target = results[modes[-1]]
        ok = target["recallAt8"] >= args.min_recall
        print(f"\n[门禁] {target['effectiveMode']} Recall@8={target['recallAt8']:.4f} "
              f"(≥{args.min_recall}) → {'通过' if ok else '未通过'}")
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
