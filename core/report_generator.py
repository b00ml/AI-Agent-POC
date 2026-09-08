"""
HTML审核报告生成器

功能：生成可视化的审核报告，包含：
- 审核统计概览
- 违规类型分布
- 详细审核结果列表
"""

import os
import json
import time

from typing import Optional, List

from data.config import REPORTS_DIR
from core.auditor import AuditResult, Violation
from core.logger import get_logger

logger = get_logger("report")


class ReportGenerator:
    """HTML审核报告生成器"""

    def __init__(self):
        self.template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>启衡精密AI财务提效POC - 审核报告</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: #f5f7fa; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); overflow: hidden; }
        .header { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; padding: 30px; }
        .header h1 { font-size: 24px; margin-bottom: 8px; }
        .header p { opacity: 0.9; font-size: 14px; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; padding: 24px; background: #fafafa; border-bottom: 1px solid #eee; }
        .stat-card { background: white; padding: 20px; border-radius: 8px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.04); }
        .stat-card .value { font-size: 32px; font-weight: 700; margin-bottom: 4px; }
        .stat-card.approve .value { color: #10b981; }
        .stat-card.reject .value { color: #ef4444; }
        .stat-card.flag .value { color: #f59e0b; }
        .stat-card.total .value { color: #374151; }
        .stat-card .label { font-size: 13px; color: #6b7280; }
        .content { padding: 24px; }
        .section { margin-bottom: 24px; }
        .section-title { font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #1f2937; }
        .chart-container { display: flex; gap: 16px; flex-wrap: wrap; }
        .chart-item { flex: 1; min-width: 200px; background: #fafafa; padding: 16px; border-radius: 8px; }
        .chart-item .bar { height: 24px; background: #e5e7eb; border-radius: 4px; margin-bottom: 8px; overflow: hidden; }
        .chart-item .bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
        .chart-item .bar-label { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }
        .chart-item .bar-label .name { color: #374151; }
        .chart-item .bar-label .count { color: #6b7280; font-weight: 500; }
        .table-wrapper { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #fafafa; font-weight: 600; color: #374151; }
        td { color: #4b5563; }
        .result-APPROVE { color: #10b981; font-weight: 500; }
        .result-REJECT { color: #ef4444; font-weight: 500; }
        .result-FLAG { color: #f59e0b; font-weight: 500; }
        .violation-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
        .violation-tag.OVER_STANDARD_HOTEL { background: #fee2e2; color: #dc2626; }
        .violation-tag.OVER_STANDARD_MEAL { background: #fee2e2; color: #dc2626; }
        .violation-tag.OVER_STANDARD_CITY_TRANSPORT { background: #fee2e2; color: #dc2626; }
        .violation-tag.OVER_STANDARD_TRANSPORT_CLASS { background: #fee2e2; color: #dc2626; }
        .violation-tag.INVOICE_TITLE_MISMATCH { background: #fef3c7; color: #d97706; }
        .violation-tag.INVOICE_TAXNO_MISMATCH { background: #fef3c7; color: #d97706; }
        .violation-tag.DUPLICATE_INVOICE { background: #fecaca; color: #b91c1c; }
        .violation-tag.MISSING_APPROVAL_OVERTIME_TAXI { background: #dbeafe; color: #1d4ed8; }
        .violation-tag.MISSING_ATTACHMENT { background: #fef3c7; color: #d97706; }
        .violation-tag.AMOUNT_MISMATCH { background: #fee2e2; color: #dc2626; }
        .footer { padding: 20px; background: #fafafa; border-top: 1px solid #eee; text-align: center; font-size: 13px; color: #9ca3af; }
        .confidence-bar { width: 100px; height: 6px; background: #e5e7eb; border-radius: 3px; overflow: hidden; display: inline-block; }
        .confidence-fill { height: 100%; border-radius: 3px; }
        .confidence-fill.high { background: #10b981; }
        .confidence-fill.medium { background: #f59e0b; }
        .confidence-fill.low { background: #ef4444; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>启衡精密AI财务提效POC - 智能报销审核报告</h1>
            <p>生成时间：{generated_at}</p>
        </div>
        
        <div class="stats">
            <div class="stat-card total">
                <div class="value">{total_count}</div>
                <div class="label">审核单据总数</div>
            </div>
            <div class="stat-card approve">
                <div class="value">{approve_count}</div>
                <div class="label">建议通过</div>
            </div>
            <div class="stat-card reject">
                <div class="value">{reject_count}</div>
                <div class="label">建议驳回</div>
            </div>
            <div class="stat-card flag">
                <div class="value">{flag_count}</div>
                <div class="label">存疑待复核</div>
            </div>
        </div>
        
        <div class="content">
            <div class="section">
                <div class="section-title">违规类型分布</div>
                <div class="chart-container">
                    {violation_chart}
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">审核结果详情</div>
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th>报销单号</th>
                                <th>审核结论</th>
                                <th>违规类型</th>
                                <th>判定理由</th>
                                <th>置信度</th>
                            </tr>
                        </thead>
                        <tbody>
                            {details_table}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <div class="footer">
            启衡精密AI财务提效POC | 智能审核系统
        </div>
    </div>
</body>
</html>"""

    def generate(self, results: List[AuditResult], m3_result: Optional[dict] = None) -> str:
        """生成HTML报告内容"""
        generated_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

        # 统计
        total_count = len(results)
        approve_count = sum(1 for r in results if r.result == 'APPROVE')
        reject_count = sum(1 for r in results if r.result == 'REJECT')
        flag_count = sum(1 for r in results if r.result == 'FLAG')

        # 违规类型统计
        violation_counts = {}
        for r in results:
            for v in r.violations:
                violation_counts[v.code] = violation_counts.get(v.code, 0) + 1

        # 生成违规类型图表
        max_count = max(violation_counts.values()) if violation_counts else 1
        violation_chart = ''
        for code, count in sorted(violation_counts.items(), key=lambda x: -x[1]):
            percent = (count / max_count) * 100
            violation_chart += f"""
            <div class="chart-item">
                <div class="bar-label"><span class="name">{self._get_violation_name(code)}</span><span class="count">{count}</span></div>
                <div class="bar"><div class="bar-fill" style="width: {percent}%; background: #2563eb;"></div></div>
            </div>"""

        # 生成详情表格
        details_table = ''
        for r in results:
            violation_tags = ''.join([f'<span class="violation-tag {v.code}">{v.code}</span>' for v in r.violations]) or '-'
            reasons = '<br>'.join(r.reasons) if r.reasons else '-'
            confidence_class = 'high' if r.confidence >= 0.8 else 'medium' if r.confidence >= 0.5 else 'low'

            details_table += f"""
            <tr>
                <td>{r.claim_id}</td>
                <td><span class="result-{r.result}">{r.result}</span></td>
                <td>{violation_tags}</td>
                <td>{reasons}</td>
                <td>
                    <div class="confidence-bar"><div class="confidence-fill {confidence_class}" style="width: {r.confidence * 100}%;"></div></div>
                    {r.confidence:.2f}
                </td>
            </tr>"""

        # 替换模板变量（使用字符串替换避免CSS花括号冲突）
        html = self.template.replace('{generated_at}', generated_at)
        html = html.replace('{total_count}', str(total_count))
        html = html.replace('{approve_count}', str(approve_count))
        html = html.replace('{reject_count}', str(reject_count))
        html = html.replace('{flag_count}', str(flag_count))
        html = html.replace('{violation_chart}', violation_chart)
        html = html.replace('{details_table}', details_table)

        return html

    def _get_violation_name(self, code: str) -> str:
        """获取违规类型中文名称"""
        names = {
            'OVER_STANDARD_HOTEL': '住宿费超标',
            'OVER_STANDARD_MEAL': '伙食补助超标',
            'OVER_STANDARD_CITY_TRANSPORT': '市内交通超标',
            'OVER_STANDARD_TRANSPORT_CLASS': '舱位超标',
            'INVOICE_TITLE_MISMATCH': '发票抬头不符',
            'INVOICE_TAXNO_MISMATCH': '发票税号不符',
            'DUPLICATE_INVOICE': '重复报销',
            'MISSING_APPROVAL_OVERTIME_TAXI': '缺事前审批',
            'MISSING_ATTACHMENT': '缺附件',
            'AMOUNT_MISMATCH': '金额不符'
        }
        return names.get(code, code)

    def save(self, results: List[AuditResult], m3_result: Optional[dict] = None, filepath: Optional[str] = None) -> str:
        """生成并保存HTML报告"""
        filepath = filepath or os.path.join(REPORTS_DIR, 'audit_report.html')

        # 确保目录存在
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        html = self.generate(results, m3_result)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)

        logger.info(f"✓ HTML报告已生成: {filepath}")
        return filepath


if __name__ == "__main__":
    import os

    # 测试：从audit_report.json加载数据生成HTML
    report_path = os.path.join(REPORTS_DIR, 'audit_report.json')

    if os.path.exists(report_path):
        with open(report_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        results: List[AuditResult] = []
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
    else:
        print(f"✗ 未找到审核报告: {report_path}")
