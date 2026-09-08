#!/usr/bin/env python3
"""
启衡精密AI财务提效POC - 主命令行入口

功能：
- m2: 执行M2智能报销审核
- m3: 执行M3发票异常检测
- submit: 生成submission.json
- evaluate: 运行自建评测
- report: 生成HTML审核报告
- all: 执行全部流程（M2+M3+报告+评测+提交）

示例：
    python main.py m2                          # 执行M2审核（前10单测试）
    python main.py m2 --all                    # 执行M2审核（全部300单）
    python main.py m3                          # 执行M3检测
    python main.py submit                      # 生成submission.json
    python main.py evaluate                    # 运行评测
    python main.py report                      # 生成HTML报告
    python main.py all                         # 执行全部流程
"""

import os
import sys
import json
import argparse
import logging

from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from core.logger import setup_logging
from core.client import QihengClient
from core.m2_processor import M2Processor
from core.m3_processor import M3Processor
from core.m4_processor import M4Processor
from core.submission import SubmissionGenerator
from core.evaluator import Evaluator
from core.report_generator import ReportGenerator
from core.auditor import AuditResult, Violation
from data.config import SUBMISSION_FILE, REPORTS_DIR


def get_client(api_key: Optional[str] = None) -> QihengClient:
    """获取API客户端"""
    api_key = api_key or os.environ['QIHENG_API_KEY']
    return QihengClient(api_key=api_key)


def cmd_m2(args):
    """执行M2智能报销审核"""
    if args.llm_review:
        os.environ["LLM_REVIEW_ENABLED"] = "1"
    client = get_client(args.api_key)
    processor = M2Processor(client)

    limit = None if args.all else args.limit
    processor.run(limit=limit, write_back=not args.no_write)

    # 任务可靠性口径（设计文档2.0 §3.8）：有失败单时以非零退出码暴露，失败清单见
    # output/reports/m2_failures.json，可据此重放
    if processor.failures:
        print(f"✗ M2 存在 {len(processor.failures)} 条失败记录（详见 output/reports/m2_failures.json）")
        sys.exit(1)


def cmd_m3(args):
    """执行M3发票异常检测"""
    client = get_client(args.api_key)
    processor = M3Processor(client)

    limit = None if args.all else args.limit
    result = processor.run(limit=limit)

    # 保存M3结果
    output_path = os.path.join(REPORTS_DIR, 'm3_result.json')
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✓ M3结果已保存: {output_path}")


def cmd_m4(args):
    """执行M4银行对账"""
    api_key = args.api_key or os.environ.get('QIHENG_M4_API_KEY')
    if not api_key:
        print("✗ 缺少M4专用API Key，请设置环境变量 QIHENG_M4_API_KEY（含 receivable:read 权限）")
        return
    client = QihengClient(api_key=api_key)
    processor = M4Processor(client)
    result = processor.run()

    output_path = os.path.join(REPORTS_DIR, 'm4_result.json')
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✓ M4结果已保存: {output_path}")


def cmd_submit(args):
    """生成submission.json"""
    client = get_client(args.api_key)

    # 执行M2审核
    processor = M2Processor(client)
    m2_results = processor.run()

    # 执行M3检测
    m3_processor = M3Processor(client)
    m3_result = m3_processor.run()

    # 构建完整submission
    generator = SubmissionGenerator()
    submission = generator.build_full_submission(m2_results, m3_result)

    # 保存
    os.makedirs(os.path.dirname(SUBMISSION_FILE), exist_ok=True)
    with open(SUBMISSION_FILE, 'w', encoding='utf-8') as f:
        json.dump(submission, f, ensure_ascii=False, indent=2)

    print(f"✓ submission.json已生成: {SUBMISSION_FILE}")

    # 验证格式
    errors = generator.validate(SUBMISSION_FILE)
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        print("❌ submission.json 格式自检未通过")
    else:
        print("✓ submission.json 格式自检通过（无 error）")


def cmd_evaluate(args):
    """运行自建评测"""
    client = get_client(args.api_key)
    evaluator = Evaluator(client)
    result = evaluator.evaluate()

    # 自建困难集（离线合成固件，设计文档2.0 §3.6②）：与公开集双层门禁
    from core.evaluator import evaluate_hard_set
    hard = evaluate_hard_set()
    print(f"\n[困难集] {hard['cases']} 单 结论准确率={hard['verdictAccuracy']:.4f} "
          f"违规集一致率={hard['violationAccuracy']:.4f}")

    # 回归门禁：评测结果低于阈值则非零退出（可作 CI 检查）
    if args.gate:
        f1 = result['verdictMetrics']['f1']
        va = result['violationAccuracy']
        ok = f1 >= args.f1_min and va >= args.va_min
        print(f"\n[门禁] F1={f1:.4f} (≥{args.f1_min}) 违规一致率={va:.4f} (≥{args.va_min}) → {'通过' if ok else '未通过'}")
        ok_hard = (hard['verdictAccuracy'] >= args.hard_min
                   and hard['violationAccuracy'] >= args.hard_min)
        print(f"[门禁·困难集] 结论={hard['verdictAccuracy']:.4f} 违规={hard['violationAccuracy']:.4f} "
              f"(≥{args.hard_min}) → {'通过' if ok_hard else '未通过'}")
        import sys as _sys
        if not ok or not ok_hard:
            _sys.exit(1)


def cmd_report(args):
    """生成HTML审核报告"""
    # 从audit_report.json加载数据
    report_path = os.path.join(REPORTS_DIR, 'audit_report.json')

    if not os.path.exists(report_path):
        print(f"✗ 未找到审核报告: {report_path}")
        print("  请先执行 `python main.py m2`")
        return

    with open(report_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    results: list[AuditResult] = []
    for review in data.get('reviews', []):
        violations = [Violation(code=v, reason="") for v in review['violations']]
        result = AuditResult(
            claim_id=review['claimId'],
            result=review['result'],
            violations=violations,
            reasons=review['reasons'],
            confidence=review['confidence']
        )
        results.append(result)

    generator = ReportGenerator()
    generator.save(results)


def cmd_all(args):
    """执行全部流程"""
    print("=== 执行全部流程 ===")

    # M2审核
    print("\n--- 步骤1: M2智能报销审核 ---")
    cmd_m2(argparse.Namespace(api_key=args.api_key, all=True, limit=10))

    # M3检测
    print("\n--- 步骤2: M3发票异常检测 ---")
    cmd_m3(argparse.Namespace(api_key=args.api_key, all=True, limit=None))

    # 生成报告
    print("\n--- 步骤3: 生成HTML审核报告 ---")
    cmd_report(argparse.Namespace())

    # 运行评测
    print("\n--- 步骤4: 运行自建评测 ---")
    cmd_evaluate(argparse.Namespace(api_key=args.api_key))

    # 生成submission.json
    print("\n--- 步骤5: 生成submission.json ---")
    cmd_submit(argparse.Namespace(api_key=args.api_key))

    print("\n=== 全部流程执行完成 ===")


def main():
    setup_logging(logging.INFO)
    parser = argparse.ArgumentParser(description='启衡精密AI财务提效POC')
    parser.add_argument('--api-key', help='API密钥')

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # M2命令
    m2_parser = subparsers.add_parser('m2', help='执行M2智能报销审核')
    m2_parser.add_argument('--all', action='store_true', help='处理全部300单')
    m2_parser.add_argument('--limit', type=int, default=10, help='处理单数限制（默认10，--all时忽略）')
    m2_parser.add_argument('--no-write', action='store_true', help='只计算审核结论，不回写ERP（默认回写）')
    m2_parser.add_argument('--llm-review', action='store_true', help='启用 AI 复核助手（LLM 独立复核，分歧转 FLAG）')

    # M3命令
    m3_parser = subparsers.add_parser('m3', help='执行M3发票异常检测')
    m3_parser.add_argument('--all', action='store_true', help='处理全部300单')
    m3_parser.add_argument('--limit', type=int, default=None, help='处理单数限制（--all时忽略）')

    # M4命令
    subparsers.add_parser('m4', help='执行M4银行对账')

    # submit命令
    subparsers.add_parser('submit', help='生成submission.json')

    # evaluate命令
    ev_parser = subparsers.add_parser('evaluate', help='运行自建评测')
    ev_parser.add_argument('--gate', action='store_true', help='启用回归门禁（不达标退出码 1）')
    ev_parser.add_argument('--f1-min', type=float, default=0.85, help='驳回 F1 阈值（默认 0.85）')
    ev_parser.add_argument('--va-min', type=float, default=0.80, help='违规一致率阈值（默认 0.80）')
    ev_parser.add_argument('--hard-min', type=float, default=1.0, help='困难集双指标阈值（默认 1.0）')

    # report命令
    subparsers.add_parser('report', help='生成HTML审核报告')

    # all命令
    subparsers.add_parser('all', help='执行全部流程')

    args = parser.parse_args()

    if args.command == 'm2':
        cmd_m2(args)
    elif args.command == 'm3':
        cmd_m3(args)
    elif args.command == 'm4':
        cmd_m4(args)
    elif args.command == 'submit':
        cmd_submit(args)
    elif args.command == 'evaluate':
        cmd_evaluate(args)
    elif args.command == 'report':
        cmd_report(args)
    elif args.command == 'all':
        cmd_all(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
