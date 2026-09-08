"""
OCR模式自建评测脚本

使用千问VL OCR识别发票图片，基于票面数据审核，
对比公开样例标签计算评测指标。
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from core.client import QihengClient, QihengError
from core.auditor import Auditor
from core.invoice_ocr import InvoiceOCREngine
from data.travel_data import TravelDataManager


def run_ocr_evaluation():
    """执行OCR模式的评测"""
    print("=== OCR模式自建评测 ===")
    
    # 初始化
    api_key = os.environ['QIHENG_API_KEY']
    client = QihengClient(api_key=api_key)
    tm = TravelDataManager(client)
    auditor = Auditor(tm)
    ocr = InvoiceOCREngine()
    
    # 加载差旅数据
    tm.load_data()
    
    # 加载标签
    labels_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'qiheng-env-v1.0-windows-intel-mac',
        'public-sample-labels.json'
    )
    with open(labels_path, 'r', encoding='utf-8') as f:
        labels = json.load(f)
    
    claims_info = labels['claims']
    claim_ids = list(claims_info.keys())
    print(f"加载 {len(claim_ids)} 条样例标签")
    
    # 获取所有待审单用于发票索引
    all_claims = list(client.expense_claims_iterate(status="PENDING"))
    auditor.build_invoice_index(all_claims)
    
    # 第一步：获取报销单详情 + OCR识别
    print("\n--- 步骤1: 获取详情并在千问VL OCR ---")
    ocr_results_map = {}
    claim_details_list = []
    
    for i, claim_id in enumerate(claim_ids, 1):
        print(f"  [{i}/{len(claim_ids)}] {claim_id}...")
        
        detail = client.expense_claims_get(claim_id)
        claim_details_list.append(detail)
        
        # OCR识别每张发票
        for line in detail.get('lines', []):
            invoice = line.get('invoice')
            attachment = line.get('attachment')
            if invoice and attachment:
                attach_id = attachment['id']
                if attach_id not in ocr_results_map:
                    try:
                        image_bytes = client._request('GET', f'/v1/attachments/{attach_id}/content')
                        ocr_result = ocr.ocr_invoice(
                            image_bytes, attachment.get('mimeType', 'image/jpeg'), attach_id
                        )
                        if ocr_result:
                            ocr_results_map[attach_id] = ocr_result
                    except (ValueError, IOError, QihengError) as e:
                        print(f"    ✗ OCR失败 {attach_id}: {e}")
        
        time.sleep(0.2)
    
    print(f"\n  OCR识别 {ocr.call_count} 张，缓存命中 {ocr.cache_hits} 次")
    
    # 第二步：逐单审核并对比标签
    print("\n--- 步骤2: 逐单审核并对比 ---")
    
    tp = tn = fp = fn = 0
    violation_match_count = 0
    total_reject_cases = 0
    details = []
    
    for claim_detail in claim_details_list:
        claim_id = claim_detail['id']
        expected = claims_info[claim_id]
        expected_verdict = expected['expectedVerdict']
        expected_violations = set(expected['violations'])
        
        approvals = client.approvals_for_claim(claim_id)
        
        # 执行审核（传入OCR结果）
        result = auditor.audit_claim(claim_detail, approvals, ocr_results=ocr_results_map)
        actual_verdict = result.result
        actual_violations = set([v.code for v in result.violations])
        
        # 混淆矩阵
        predicted_reject = actual_verdict == 'REJECT'
        actual_reject = expected_verdict == 'REJECT'
        
        if predicted_reject and actual_reject:
            tp += 1
        elif predicted_reject and not actual_reject:
            fp += 1
        elif not predicted_reject and actual_reject:
            fn += 1
        else:
            tn += 1
        
        if actual_reject:
            total_reject_cases += 1
            if actual_violations == expected_violations:
                violation_match_count += 1
        
        details.append({
            'claimId': claim_id,
            'expected': expected_verdict,
            'actual': actual_verdict,
            'expectedViolations': sorted(list(expected_violations)),
            'actualViolations': sorted(list(actual_violations)),
            'match': predicted_reject == actual_reject,
            'violationMatch': actual_violations == expected_violations
        })
    
    # 计算指标
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    violation_accuracy = violation_match_count / total_reject_cases if total_reject_cases > 0 else 0
    accuracy = (tp + tn) / len(claim_ids)
    
    print("\n=== 评测报告 (OCR模式) ===")
    print(f"样例数: {len(claim_ids)}")
    print(f"混淆矩阵: TP={tp} TN={tn} FP={fp} FN={fn}")
    print(f"驳回F1: {f1:.4f} (P={precision:.4f} R={recall:.4f})")
    print(f"违规一致率: {violation_accuracy:.4f}")
    print(f"整体准确率: {accuracy:.4f}")
    
    print("\n详细结果:")
    for d in details:
        s = "✓" if d['match'] else "✗"
        vs = "✓" if d['violationMatch'] else "✗"
        print(f"  {s} {d['claimId']}: 预期={d['expected']} 实际={d['actual']} 违规={vs}")
        if not d['match']:
            print(f"    预期违规: {d['expectedViolations']}")
            print(f"    实际违规: {d['actualViolations']}")
    
    # 保存结果
    output = {
        'sampleSize': len(claim_ids),
        'confusionMatrix': {'tp': tp, 'tn': tn, 'fp': fp, 'fn': fn},
        'verdictMetrics': {'precision': precision, 'recall': recall, 'f1': f1},
        'violationAccuracy': violation_accuracy,
        'accuracy': accuracy,
        'ocrCalls': ocr.call_count,
        'details': details
    }
    
    out_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'output', 'evaluation_ocr.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 结果已保存: {out_path}")
    
    return output


if __name__ == "__main__":
    start = time.time()
    result = run_ocr_evaluation()
    elapsed = time.time() - start
    print(f"\n总耗时: {elapsed:.1f} 秒")
