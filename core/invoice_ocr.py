"""
千问 Qwen3.6-Flash 发票OCR识别模块

使用阿里云百炼 qwen3.6-flash 多模态模型对发票图片进行OCR识别，
提取结构化字段，与系统录入数据进行比对。
"""

import os
import json
import base64
import time
from typing import Optional, Dict, Any

from openai import OpenAI
from dotenv import load_dotenv

from core.logger import get_logger
from data.config import OCR_ENGINE

load_dotenv()
logger = get_logger("ocr")


def _load_prompt() -> str:
    """从模板文件加载发票OCR提示词"""
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "prompts", "invoice_ocr.txt"
    )
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


INVOICE_EXTRACTION_PROMPT = _load_prompt()


class InvoiceOCREngine:
    """发票OCR识别引擎，支持 PaddleOCR 和千问双引擎"""

    def __init__(self) -> None:
        self.engine_type = OCR_ENGINE
        logger.info(f"初始化发票OCR引擎，使用引擎: {self.engine_type}")

        # 内存缓存（用于千问引擎）
        self._cache: Dict[str, dict] = {}

        # 统计
        self.call_count: int = 0
        self.cache_hits: int = 0

        # 根据配置初始化引擎
        if self.engine_type == "paddle":
            self._init_paddle_engine()
        else:
            self._init_qwen_engine()

    def _init_paddle_engine(self):
        """初始化 PaddleOCR 引擎"""
        from core.local_ocr import PaddleOCREngine
        self._engine = PaddleOCREngine()
        logger.info("PaddleOCR 引擎初始化完成")

    def _init_qwen_engine(self):
        """初始化千问 Qwen3.6-Flash 引擎"""
        api_key = os.getenv("DASHSCOPE_API_KEY")
        base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model: str = os.getenv("QWEN_VL_MODEL", "qwen3.6-flash")

        if not api_key:
            raise ValueError("未配置DASHSCOPE_API_KEY，请在.env中设置")

        self.client: OpenAI = OpenAI(api_key=api_key, base_url=base_url)
        logger.info("千问 OCR 引擎初始化完成")

    def ocr_invoice(self, image_bytes: bytes, mime_type: str, attachment_id: Optional[str] = None) -> dict:
        """对发票图片进行OCR识别"""
        if self.engine_type == "paddle":
            # 使用 PaddleOCR 引擎
            self.call_count += 1
            t0 = time.time()

            result = self._engine.recognize(image_bytes)

            elapsed = time.time() - t0
            logger.info(f"[{attachment_id or 'N/A'}] PaddleOCR {elapsed:.1f}s")
            return result
        else:
            # 使用千问引擎
            if attachment_id and attachment_id in self._cache:
                self.cache_hits += 1
                return self._cache[attachment_id]

            b64 = base64.b64encode(image_bytes).decode('utf-8')
            data_url = f"data:{mime_type};base64,{b64}"

            t0 = time.time()
            self.call_count += 1

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": INVOICE_EXTRACTION_PROMPT}
                    ]
                }],
                response_format={"type": "json_object"},
                temperature=0.1
            )

            elapsed = time.time() - t0
            usage = response.usage
            log_msg = (
                f"[{attachment_id or 'N/A'}] 千问OCR {elapsed:.1f}s "
                f"| in={usage.prompt_tokens}t out={usage.completion_tokens}t"
            )
            logger.info(log_msg)

            content = response.choices[0].message.content.strip()
            result = self._parse_response(content)

            if attachment_id:
                self._cache[attachment_id] = result

            return result

    def _parse_response(self, content: str) -> dict:
        """解析LLM返回的JSON"""
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            content = content.strip()

        # 兼容返回 JSON 数组（取第一个对象）
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else {}
            if isinstance(parsed, dict):
                return parsed
            logger.warning(f"OCR 返回非对象结构: {type(parsed).__name__}")
            return {}
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[\s\S]*\}', content)
            if match:
                try:
                    parsed = json.loads(match.group())
                    if isinstance(parsed, list):
                        parsed = parsed[0] if parsed else {}
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass
            logger.warning(f"OCR JSON parse failed: {content[:200]}...")
            return {}

    def compare_with_system(self, ocr_result: dict, system_invoice: dict) -> Dict[str, Any]:
        """比对OCR识别结果与系统录入数据"""
        discrepancies = []
        if not isinstance(ocr_result, dict):
            return {'discrepancies': discrepancies, 'hasDiscrepancy': False}

        field_map = {
            'buyerName': ('buyer', 'name'),
            'buyerTaxNo': ('buyer', 'taxNo'),
            'sellerName': ('seller', 'name'),
            'sellerTaxNo': ('seller', 'taxNo'),
            'invoiceCode': ('invoiceCode',),
            'invoiceNo': ('invoiceNo',),
        }

        for ocr_field, sys_path in field_map.items():
            ocr_value = ocr_result.get(ocr_field, '')
            sys_value = system_invoice
            for key in sys_path:
                sys_value = sys_value.get(key, '') if isinstance(sys_value, dict) else ''

            ocr_value = str(ocr_value).strip() if ocr_value else ''
            sys_value = str(sys_value).strip() if sys_value else ''

            if not ocr_value or not sys_value:
                continue

            # 税号比对：忽略X占位符
            if ocr_field in ('buyerTaxNo', 'sellerTaxNo'):
                ocr_clean = ocr_value.replace('X', '').replace('x', '')
                sys_clean = sys_value.replace('X', '').replace('x', '')
                if ocr_clean == sys_clean:
                    continue
                discrepancies.append({'field': ocr_field, 'ocr': ocr_value, 'system': sys_value})
                continue

            if ocr_value != sys_value:
                discrepancies.append({'field': ocr_field, 'ocr': ocr_value, 'system': sys_value})

        return {'discrepancies': discrepancies, 'hasDiscrepancy': len(discrepancies) > 0}

    def get_result(self, attachment_id: str) -> Optional[dict]:
        """获取缓存的OCR识别结果"""
        return self._cache.get(attachment_id)

    def get_stats(self) -> Dict[str, int]:
        return {'totalCalls': self.call_count, 'cacheHits': self.cache_hits, 'cacheSize': len(self._cache)}

    def recognize(self, image_b64_or_path: str, attachment_id: Optional[str] = None, mime_type: str = "image/webp") -> dict:
        """
        便捷识别接口，兼容两种输入：
        1) 文件路径
        2) base64 字符串
        """
        if os.path.exists(image_b64_or_path):
            with open(image_b64_or_path, "rb") as f:
                image_bytes = f.read()
        else:
            try:
                image_bytes = base64.b64decode(image_b64_or_path)
            except Exception:
                # 兜底：直接当做二进制字符串
                image_bytes = image_b64_or_path.encode("utf-8", errors="ignore")

        logger.debug(f"使用 {self.engine_type} 引擎处理图片，大小: {len(image_bytes)} 字节")
        return self.ocr_invoice(image_bytes, mime_type, attachment_id)

    def recognize_claim_invoices(self, claim_id: str, api_url: str = "", api_key: str = "") -> dict:
        """对指定报销单的所有发票附件执行OCR识别"""
        from core.client import QihengClient

        client = QihengClient(api_key=api_key, base_url=api_url)
        claim = client.expense_claims_get(claim_id)

        results = []
        comparisons = []

        for line in claim.get('lines', []):
            invoice = line.get('invoice')
            attachment = line.get('attachment')
            if not invoice or not attachment:
                continue

            attach_id = attachment['id']
            mime_type = attachment.get('mimeType', 'image/jpeg')

            try:
                image_bytes = client._request('GET', f'/v1/attachments/{attach_id}/content')
                ocr_result = self.ocr_invoice(image_bytes, mime_type, attach_id)
                results.append({
                    'attachmentId': attach_id,
                    'ocr': ocr_result,
                })

                comparison = self.compare_with_system(ocr_result, invoice)
                if comparison['hasDiscrepancy']:
                    comparisons.append({
                        'attachmentId': attach_id,
                        'discrepancies': comparison['discrepancies'],
                    })
            except Exception as e:
                logger.warning(f"OCR识别失败 {attach_id}: {e}")
                results.append({
                    'attachmentId': attach_id,
                    'error': str(e),
                })

        return {
            'claimId': claim_id,
            'totalInvoices': len(results),
            'ocrResults': results,
            'comparisons': comparisons,
        }


if __name__ == "__main__":
    from core.client import QihengClient

    client = QihengClient(api_key=os.environ['QIHENG_API_KEY'])
    ocr = InvoiceOCREngine()

    claim = client.expense_claims_get('BX-005773')
    line = claim['lines'][0]
    invoice = line['invoice']
    attachment_id = line['attachment']['id']
    mime_type = line['attachment']['mimeType']

    print("系统录入发票数据:")
    print(f"  购方: {invoice['buyer']['name']} ({invoice['buyer']['taxNo']})")
    print(f"  销方: {invoice['seller']['name']}")
    print(f"  代码: {invoice['invoiceCode']}")
    print(f"  号码: {invoice['invoiceNo']}")
    print(f"  金额: {invoice['total']}")

    print("\n正在下载图片并OCR识别...")
    image_bytes = client._request('GET', f'/v1/attachments/{attachment_id}/content')

    ocr_result = ocr.ocr_invoice(image_bytes, mime_type, attachment_id)
    print("\nOCR识别结果:")
    print(json.dumps(ocr_result, ensure_ascii=False, indent=2))

    comparison = ocr.compare_with_system(ocr_result, invoice)
    print("\n比对差异:")
    for d in comparison['discrepancies']:
        print(f"  {d['field']}: OCR={d['ocr']} vs 系统={d['system']}")
