"""
困难集评测 CLI（设计文档2.0 §3.6②）：包装 core.evaluator.evaluate_hard_set。

用法：
    python tools/eval_hard_set.py            # 输出指标与失败明细
    python tools/eval_hard_set.py --gate     # 不达标 exit 1（默认双指标 ≥ 1.0）
    python tools/eval_hard_set.py --verdict-min 0.97 --violation-min 0.97 --gate
"""

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.evaluator import evaluate_hard_set


def main() -> None:
    parser = argparse.ArgumentParser(description="自建困难集评测")
    parser.add_argument("--labels", default=None, help="困难集标签文件（默认 data/labels/hard-set-labels.json）")
    parser.add_argument("--gate", action="store_true", help="启用门禁（不达标 exit 1）")
    parser.add_argument("--verdict-min", type=float, default=1.0)
    parser.add_argument("--violation-min", type=float, default=1.0)
    args = parser.parse_args()

    result = evaluate_hard_set(args.labels)
    print(f"=== 自建困难集评测（{result['cases']} 单，离线合成固件）===")
    print(f"结论准确率:   {result['verdictAccuracy']:.4f}")
    print(f"违规集一致率: {result['violationAccuracy']:.4f}")
    if result["failures"]:
        print("失败明细:")
        for f in result["failures"]:
            print(f"  {f['id']}（{f['dimension']}）: {f['expectedVerdict']}→{f['actualVerdict']} "
                  f"{f['expectedViolations']}→{f['actualViolations']}")

    # 评测报告随运行产物留存
    out = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "output", "reports", "hard_set_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✓ 结果已保存: {out}")

    if args.gate:
        ok = (result["verdictAccuracy"] >= args.verdict_min
              and result["violationAccuracy"] >= args.violation_min)
        print(f"[门禁] 结论≥{args.verdict_min} 违规≥{args.violation_min} → {'通过' if ok else '未通过'}")
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
