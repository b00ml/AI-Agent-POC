"""
构建官方格式 submission.json（v1）

数据来源：
- M2：output/reports/audit_report.json（300 单审核结论）
- M3：output/reports/m3_result.json（全量发票异常检测）
- eval：output/evaluation_result.json（30 单公开样例评测）

用法：python tools/build_submission.py
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.submission import SubmissionGenerator


def main() -> None:
    root = os.path.dirname(os.path.dirname(__file__))

    with open(os.path.join(root, "output", "reports", "audit_report.json"), encoding="utf-8") as f:
        audit = json.load(f)

    with open(os.path.join(root, "output", "reports", "m3_result.json"), encoding="utf-8") as f:
        m3 = json.load(f)

    m4_path = os.path.join(root, "output", "reports", "m4_result.json")
    m4 = None
    if os.path.exists(m4_path):
        with open(m4_path, encoding="utf-8") as f:
            m4 = json.load(f)
        print(f"M4: 匹配 {len(m4.get('matches', []))} 笔，未识别 {len(m4.get('unidentified', []))} 笔")

    eval_path = os.path.join(root, "output", "evaluation_result.json")
    eval_result = None
    if os.path.exists(eval_path):
        with open(eval_path, encoding="utf-8") as f:
            ev = json.load(f)
        eval_result = {
            "extractionAccuracy": round(ev.get("accuracy", 0.0), 4),
            "testSetSize": ev.get("sampleSize", 30),
            "notes": (
                f"30 单公开样例·本地 PaddleOCR（无数据出域）评测："
                f"驳回判定 F1={ev['verdictMetrics']['f1']:.4f}，"
                f"违规代码完全一致率={ev['violationAccuracy']:.4f}，"
                f"整体准确率={ev['accuracy']:.4f}"
            ),
        }

    generator = SubmissionGenerator()
    generator.meta.update({
        "team": "启衡AI财务提效小组",
        "members": ["FDE-001"],
        "seed": "qiheng-2026-v1",
        "submittedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "repoUrl": "",
        "aiModels": [
            {
                "provider": "本地部署（PaddleOCR PP-OCRv4，发票图片不出域）",
                "model": "ch_PP-OCRv4_det/rec",
                "purpose": "发票票据影像票面要素抽取（默认引擎，无数据出域）",
            },
            {
                "provider": "阿里云百炼（DashScope）",
                "model": "qwen3.6-flash",
                "purpose": "发票票据影像票面要素抽取（仅显式启用 OCR_ENGINE=qwen 时使用）",
            },
            {
                "provider": "DeepSeek",
                "model": "deepseek-v4-flash",
    "purpose": "AI 复核助手（默认开启，可在设置页关闭）：基于 OCR 票面要素文本与制度知识库独立复核"
                           "报销单/发票异常（M2 分歧转 FLAG；M3 标注确认/存疑/误报）；仅显式启用时使用",
            },
        ],
        "dataEgress": [
            {
                "field": "发票图片（base64 编码的票据影像）",
                "sentTo": "本地 PaddleOCR（默认，不出域）；仅当显式设置 OCR_ENGINE=qwen 时发送至阿里云百炼 qwen3.6-flash",
                "reason": "OCR 提取票面要素，以票面为准进行合规判定；默认本地识别保障敏感信息不出域",
            },
            {
                "field": "单据费用行/差旅标准/审批动作/OCR 票面要素文本（不含图片）",
                "sentTo": "DeepSeek deepseek-v4-flash（AI 复核助手，默认开启、可在设置页关闭）",
                "reason": "大模型独立复核报销单与发票异常，与规则引擎结论交叉验证（M2 分歧转 FLAG；M3 标注确认/存疑/误报）",
            }
        ],
        "apiScopes": [
            "master-data:read",
            "expense:read",
            "expense:review",
            "approval:read",
            "attachment:read",
            "invoice:read",
            "receivable:read",
        ],
    })

    # 复用审核结果对象（AuditResult 兼容 dict）
    from core.auditor import AuditResult, Violation
    m2_results = []
    for r in audit.get("reviews", []):
        m2_results.append(
            AuditResult(
                claim_id=r["claimId"],
                result=r["result"],
                violations=[Violation(code=v, reason="") for v in r.get("violations", [])],
                reasons=r.get("reasons", []),
                confidence=r.get("confidence", 0.0),
            )
        )

    submission = generator.build_full_submission(m2_results, m3, eval_result=eval_result, m4_result=m4)
    path = generator.save(submission)

    errors = generator.validate(path)
    if errors:
        print("本地格式自检未通过:")
        for e in errors:
            print("  -", e)
    else:
        print("本地格式自检通过")
    print("M2 reviews:", len(submission["m2"]["reviews"]))
    print("M3 duplicateInvoices:", len(submission["m3"]["duplicateInvoices"]))
    print("M3 invoiceIssues:", len(submission["m3"]["invoiceIssues"]))
    if "m4" in submission:
        print("M4 matches:", len(submission["m4"]["matches"]))
        print("M4 unidentified:", len(submission["m4"]["unidentified"]))


if __name__ == "__main__":
    main()
