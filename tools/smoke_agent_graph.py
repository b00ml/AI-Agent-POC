"""
调查 Agent 图管线冒烟（设计文档 2.0 §3.3 验收）：
对指定的分歧/FLAG 单以 M2_PIPELINE=graph + AGENT_INVESTIGATION_ENABLED=1 跑通
「规则初审 → AI 复核 → 调查 Agent → 回写（--write 时）」，并输出调查报告摘要。

用法：
    python tools/smoke_agent_graph.py BX-005693 BX-005699 BX-005748 [--write]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    args = [a for a in sys.argv[1:]]
    write_back = "--write" in args
    claim_ids = [a for a in args if not a.startswith("--")]
    if not claim_ids:
        claim_ids = ["BX-005693", "BX-005699", "BX-005748"]

    os.environ.setdefault("M2_PIPELINE", "graph")
    os.environ.setdefault("AGENT_INVESTIGATION_ENABLED", "1")

    from core.client import QihengClient
    from core.m2_processor import M2Processor

    client = QihengClient(api_key=os.environ["QIHENG_API_KEY"])
    processor = M2Processor(client, use_ocr=True)
    results = processor.run(claim_ids=claim_ids, write_back=write_back)

    print("\n===== 冒烟结果 =====")
    for r in results:
        inv = (r.ai_review or {}).get("investigation") or {}
        print(f"{r.claim_id}: 最终={r.result}")
        if inv:
            print(f"  调查: conclusion={inv.get('conclusion')} steps={inv.get('steps')}"
                  f" tool_calls={inv.get('tool_calls')} tokens={inv.get('tokens_used')}"
                  f" grounded={inv.get('grounding_ok')} degraded={inv.get('degraded')}")
            for ev in inv.get("evidence") or []:
                print(f"    - [{ev.get('tool')}] {ev.get('finding')}（{ev.get('ref')}）"
                      f" grounded={ev.get('grounded')}")
            print(f"  summary: {inv.get('summary')}")
        else:
            print("  调查: 未触发（AGENT_INVESTIGATION_ENABLED 关闭或无分歧）")
    if processor.failures:
        print(f"失败清单: {processor.failures}")


if __name__ == "__main__":
    main()
