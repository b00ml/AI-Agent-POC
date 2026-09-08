"""
本地 PaddleOCR 发票识别模块

使用 PaddleOCR 进行本地发票识别，避免调用云端 API。
"""

import os
import re

# 必须在 import paddle 之前禁用 oneDNN 和 PIR，否则 Windows 下会崩溃
os.environ['FLAGS_use_mkldnn'] = '0'
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['OMP_NUM_THREADS'] = '1'

from paddleocr import PaddleOCR

from core.logger import get_logger

logger = get_logger("local_ocr")


class PaddleOCREngine:
    """PaddleOCR 本地发票识别引擎"""

    def __init__(self, use_gpu: bool = False, lang: str = "ch"):
        """
        初始化 PaddleOCR 引擎

        Args:
            use_gpu: 是否使用 GPU 加速（已废弃，保留参数兼容性）
            lang: 语言，默认中文
        """
        # 初始化 PaddleOCR
        # 注意：PaddleOCR 3.x 版本参数已简化
        self.ocr = PaddleOCR(
            type="ocr",
            use_angle_cls=True,
            lang=lang
        )
        # 统计信息
        self.total_calls: int = 0
        self.fail_count: int = 0
        logger.info("PaddleOCR 引擎初始化完成")

    def recognize(self, image_bytes: bytes) -> dict:
        """
        识别发票图片

        Args:
            image_bytes: 图片字节数据

        Returns:
            包含发票信息的字典，失败时返回 {"ocr_failed": True, "error": "错误信息"}
        """
        import numpy as np
        from PIL import Image
        import io

        self.total_calls += 1

        try:
            # 验证输入数据
            if not image_bytes or len(image_bytes) == 0:
                logger.error("图片数据为空")
                self.fail_count += 1
                return {"ocr_failed": True, "error": "图片数据为空"}

            # 将字节数据转换为 numpy 数组
            try:
                image = Image.open(io.BytesIO(image_bytes))
            except Exception as e:
                logger.error(f"无法解析图片: {e}")
                self.fail_count += 1
                return {"ocr_failed": True, "error": f"无法解析图片: {str(e)}"}

            # 检查图片格式
            if image.format and image.format.lower() not in ['jpeg', 'jpg', 'png', 'webp', 'bmp']:
                logger.warning(f"不支持的图片格式: {image.format}")
                self.fail_count += 1
                return {"ocr_failed": True, "error": f"不支持的图片格式: {image.format}"}

            image_array = np.array(image)

            # 执行 OCR 识别
            # 注意：PaddleOCR 3.x 版本不再需要 cls 参数
            result = self.ocr.ocr(image_array)

            # 解析结果
            parsed_result = self._parse_ocr_result(result)

            # 如果解析结果为空，也算作失败
            if not parsed_result or len(parsed_result) == 0:
                self.fail_count += 1
                return {"ocr_failed": True, "error": "无法提取有效字段"}

            return parsed_result

        except Exception as e:
            logger.error(f"OCR 识别失败: {e}", exc_info=True)
            self.fail_count += 1
            return {"ocr_failed": True, "error": str(e)}

    def recognize_from_file(self, image_path: str) -> dict:
        """
        从文件路径识别发票图片

        Args:
            image_path: 图片文件路径

        Returns:
            包含发票信息的字典
        """
        result = self.ocr.ocr(image_path)
        return self._parse_ocr_result(result)

    def _parse_ocr_result(self, ocr_result) -> dict:
        """
        解析 PaddleOCR 的识别结果，支持 2.x 和 3.x 多种输出格式

        Args:
            ocr_result: PaddleOCR 返回的原始结果

        Returns:
            结构化的发票信息字典
        """
        # 统一提取文本行和坐标信息
        ocr_items = self._normalize_ocr_output(ocr_result)

        if not ocr_items:
            logger.warning("OCR 结果为空")
            return {"ocr_failed": True, "error": "OCR 结果为空"}

        # 按 y 坐标排序（从上到下）
        ocr_items.sort(key=lambda x: x['bbox'][1] if x['bbox'] else 0)

        # 调试：打印所有识别行（logger.debug 自带级别过滤）
        logger.debug(f"OCR 识别 {len(ocr_items)} 行:")
        for i, item in enumerate(ocr_items):
            logger.debug(f"  [{i:2d}] y={item['bbox'][1]:6.0f} text={item['text']}")

        # 解析发票关键字段
        invoice_data = self._extract_invoice_fields(ocr_items)

        logger.info(f"PaddleOCR 识别完成，提取字段: {list(invoice_data.keys())}")
        return invoice_data

    def _normalize_ocr_output(self, ocr_result) -> list:
        """
        将不同版本的 PaddleOCR 输出统一为标准格式

        标准格式: [{'text': str, 'bbox': [x1,y1,x2,y2], 'confidence': float}, ...]
        """
        items = []

        if not ocr_result:
            return items

        # PaddleOCR 3.x: OCRResult 对象
        if hasattr(ocr_result, 'rec_texts') and hasattr(ocr_result, 'rec_polys'):
            texts = ocr_result.rec_texts or []
            polys = ocr_result.rec_polys or []
            scores = ocr_result.rec_scores or [1.0] * len(texts)

            for i, text in enumerate(texts):
                poly = polys[i] if i < len(polys) else None
                bbox = self._poly_to_bbox(poly) if poly else None
                items.append({
                    'text': str(text),
                    'bbox': bbox or [0, 0, 0, 0],
                    'confidence': scores[i] if i < len(scores) else 1.0
                })
            return items

        # 嵌套 list 格式（2.x 版本或 3.x 的 list 返回）
        if isinstance(ocr_result, list) and len(ocr_result) > 0:
            page = ocr_result[0]  # 第一页
            if isinstance(page, list):
                for item in page:
                    parsed = self._parse_single_item(item)
                    if parsed:
                        items.append(parsed)
            elif isinstance(page, dict):
                # 可能是 dict 格式
                items.extend(self._parse_dict_result(page))

        return items

    def _parse_single_item(self, item) -> dict | None:
        """解析单条 OCR 记录"""
        if not item:
            return None

        # 格式 1: [bbox, (text, confidence)] - 2.x 版本
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            bbox_data = item[0]
            text_info = item[1]

            # 提取 bbox
            bbox = None
            if isinstance(bbox_data, (list, tuple)) and len(bbox_data) >= 4:
                # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]] 或 [x1,y1,x2,y2]
                if isinstance(bbox_data[0], (list, tuple)):
                    bbox = self._poly_to_bbox(bbox_data)
                else:
                    bbox = list(bbox_data[:4])

            # 提取 text 和 confidence
            text = ""
            confidence = 1.0
            if isinstance(text_info, (list, tuple)):
                text = str(text_info[0]) if len(text_info) > 0 else ""
                confidence = float(text_info[1]) if len(text_info) > 1 else 1.0
            elif isinstance(text_info, str):
                text = text_info

            if text:
                return {
                    'text': text,
                    'bbox': bbox or [0, 0, 0, 0],
                    'confidence': confidence
                }

        # 格式 2: dict 格式
        if isinstance(item, dict):
            text = item.get('rec_texts', item.get('text', ''))
            if isinstance(text, list):
                text = text[0] if text else ''
            poly = item.get('rec_polys', item.get('poly', None))
            bbox = self._poly_to_bbox(poly) if poly else None
            score = item.get('rec_scores', item.get('confidence', 1.0))
            if isinstance(score, list):
                score = score[0] if score else 1.0

            if text:
                return {
                    'text': str(text),
                    'bbox': bbox or [0, 0, 0, 0],
                    'confidence': float(score) if score else 1.0
                }

        return None

    def _parse_dict_result(self, page_dict: dict) -> list:
        """解析 dict 格式的结果"""
        items = []
        texts = page_dict.get('rec_texts', [])
        polys = page_dict.get('rec_polys', [])
        scores = page_dict.get('rec_scores', [])

        if isinstance(texts, list):
            for i, text in enumerate(texts):
                poly = polys[i] if i < len(polys) else None
                bbox = self._poly_to_bbox(poly) if poly else None
                score = scores[i] if i < len(scores) else 1.0
                items.append({
                    'text': str(text),
                    'bbox': bbox or [0, 0, 0, 0],
                    'confidence': float(score) if score else 1.0
                })

        return items

    def _poly_to_bbox(self, poly) -> list:
        """将多边形坐标转换为 [x1, y1, x2, y2] 格式"""
        try:
            if not poly:
                return [0, 0, 0, 0]

            # 已经是 [x1, y1, x2, y2] 格式
            if isinstance(poly, (list, tuple)) and len(poly) == 4:
                if not isinstance(poly[0], (list, tuple)):
                    return list(poly)

            # 4 个角点格式: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            if isinstance(poly, (list, tuple)) and len(poly) > 0:
                xs = [p[0] for p in poly if isinstance(p, (list, tuple)) and len(p) >= 2]
                ys = [p[1] for p in poly if isinstance(p, (list, tuple)) and len(p) >= 2]
                if xs and ys:
                    return [min(xs), min(ys), max(xs), max(ys)]

        except Exception as e:
            logger.debug(f"bbox 转换失败: {e}")

        return [0, 0, 0, 0]

    def _extract_invoice_fields(self, ocr_items: list) -> dict:
        """
        从识别结果中提取发票关键字段，利用 bbox 坐标进行区域匹配

        Args:
            ocr_items: 标准化后的 OCR 项列表 [{'text': str, 'bbox': [x1,y1,x2,y2], 'confidence': float}, ...]

        Returns:
            发票字段字典
        """
        invoice_data = {}

        # 提取所有文本行（带 y 坐标）
        text_lines = [(item['text'], item['bbox'][1] if item['bbox'] else 0) for item in ocr_items]

        # 计算图像尺寸（用于区域划分）
        if ocr_items and ocr_items[0]['bbox']:
            max_y = max(item['bbox'][3] for item in ocr_items if item['bbox'])
        else:
            max_y = 1000

        # 区域划分（基于 y 坐标比例）
        # 头部: 0 - 20% (发票代码、发票号码、开票日期)
        # 购方: 20% - 50% (购买方名称、纳税人识别号)
        # 销方: 50% - 75% (销售方名称、纳税人识别号)
        # 底部: 75% - 100% (金额、税额)
        region_header = (0, max_y * 0.20)
        region_buyer = (max_y * 0.20, max_y * 0.50)
        region_seller = (max_y * 0.50, max_y * 0.75)
        region_bottom = (max_y * 0.75, max_y)

        # 1. 提取头部区域字段（发票代码、发票号码、开票日期）
        self._extract_header_fields(text_lines, region_header, invoice_data)

        # 2. 提取购买方信息
        self._extract_party_fields(text_lines, region_buyer, 'buyer', invoice_data)

        # 3. 提取销售方信息
        self._extract_party_fields(text_lines, region_seller, 'seller', invoice_data)

        # 4. 提取底部金额信息
        self._extract_amount_fields(text_lines, region_bottom, invoice_data)

        # 5. 全局补充：查找遗漏的日期
        if 'invoiceDate' not in invoice_data:
            self._extract_date_global(text_lines, invoice_data)

        return invoice_data

    def _extract_header_fields(self, text_lines: list, region: tuple, invoice_data: dict):
        """提取头部区域字段"""
        region_lines = [(t, y) for t, y in text_lines if region[0] <= y <= region[1]]
        if not region_lines:
            return

        # 发票代码 (通常在 "发票代码:" 标签后)
        for i, (text, y) in enumerate(region_lines):
            if '发票代码' in text or text.strip() == '代码':
                # 尝试从当前行或下一行提取数字
                code = self._extract_numeric_value(region_lines, i, min_length=8)
                if code:
                    invoice_data['invoiceCode'] = code
                    break

        # 发票号码 (通常在 "发票号码:" 标签后)
        for i, (text, y) in enumerate(region_lines):
            if '发票号码' in text or '号码' in text:
                number = self._extract_numeric_value(region_lines, i, min_length=6)
                if number:
                    invoice_data['invoiceNo'] = number
                    break

        # 开票日期
        for text, y in region_lines:
            date = self._extract_date(text)
            if date:
                invoice_data['invoiceDate'] = date
                break

    def _extract_party_fields(self, text_lines: list, region: tuple, prefix: str, invoice_data: dict):
        """提取购方/销方信息"""
        region_lines = [(t, y) for t, y in text_lines if region[0] <= y <= region[1]]
        if not region_lines:
            return

        # 先查找区域标识（购买方/销售方）
        region_start = 0
        for i, (text, y) in enumerate(region_lines):
            if prefix == 'buyer' and ('购买方' in text or '购方' in text or '买方' in text):
                region_start = i + 1
                break
            elif prefix == 'seller' and ('销售方' in text or '销方' in text or '卖方' in text):
                region_start = i + 1
                break

        # 从标识行之后开始提取
        search_lines = region_lines[region_start:]

        # 名称：优先用「称：公司名」行（发票标签可能被 OCR 拆成单字，但值行完整）
        name = self._extract_name_from_lines(search_lines)
        if not name:
            name = self._extract_field_value(search_lines, ['名称', '购买方', '销售方', '购方', '销方', '买方', '卖方'])
        if name:
            # 清理名称：移除标签前缀
            for tag in ['名称', ':', '：']:
                if tag in name:
                    name = name.split(tag)[-1].strip()
            # 进一步清理：去掉可能粘连的相邻标签
            name = re.split(
                r'(纳税人识别号|税号|统一社会信用代码|地址|电话|开户|银行)',
                name
            )[0].strip().rstrip('，,。.;；')
            if len(name) >= 2:
                invoice_data[f'{prefix}Name'] = name

        # 纳税人识别号
        tax_no = self._extract_field_value(search_lines, ['纳税人识别号', '税号', '统一社会信用代码'])
        if tax_no:
            # 清理税号：只保留字母和数字
            cleaned = re.sub(r'[^A-Za-z0-9]', '', tax_no)
            if cleaned and len(cleaned) >= 15:  # 税号通常 15-20 位
                invoice_data[f'{prefix}TaxNo'] = cleaned

    def _extract_name_from_lines(self, lines: list) -> str:
        """从文本行中提取「称：公司名」形式的名称为值"""
        for text, y in lines:
            match = re.search(r'称\s*[:：]?\s*([^\s:：]{2,})', text)
            if not match:
                continue
            name = match.group(1).strip()
            # 名称行可能粘连下一个字段标签，截断处理
            name = re.split(
                r'(纳税人识别号|税号|统一社会信用代码|地址|电话|开户|银行)',
                name
            )[0].strip().rstrip('，,。.;；')
            # 去掉行尾可能粘连的 15-20 位税号
            name = re.sub(r'\s*[A-Za-z0-9]{15,20}\s*$', '', name).strip()
            if name and len(name) >= 2 and not re.fullmatch(r'[\d\W]+', name):
                return name
        return ''

    def _extract_amount_fields(self, text_lines: list, region: tuple, invoice_data: dict):
        """提取金额信息"""
        region_lines = [(t, y) for t, y in text_lines if region[0] <= y <= region[1]]
        if not region_lines:
            # 如果底部区域没有，尝试全局搜索
            region_lines = text_lines

        # 价税合计金额：必须取「价税合计（小写）￥XXX」，不能取不含税金额/合计
        total_found = False
        for text, y in region_lines:
            if '小写' in text or '价税合计' in text:
                amount = self._extract_amount_from_line(text)
                if amount:
                    invoice_data['totalAmount'] = amount
                    total_found = True
                    break

        # 兜底：优先含 ¥ 符号的行，其次旧的「合计/金额」逻辑
        if not total_found:
            for text, y in region_lines:
                if '¥' in text or '￥' in text:
                    amount = self._extract_amount_from_line(text)
                    if amount:
                        invoice_data['totalAmount'] = amount
                        total_found = True
                        break
        if not total_found:
            for i, (text, y) in enumerate(region_lines):
                if '价税合计' in text or ('合计' in text and '税' not in text):
                    amount = self._extract_amount_from_line(text)
                    if amount:
                        invoice_data['totalAmount'] = amount
                        break
                    if i + 1 < len(region_lines):
                        next_amount = self._extract_amount_from_line(region_lines[i + 1][0])
                        if next_amount:
                            invoice_data['totalAmount'] = next_amount
                            break

        # 税额
        for i, (text, y) in enumerate(region_lines):
            if '税额' in text and '合' not in text:  # 排除"合计"中的税额
                tax = self._extract_amount_from_line(text)
                if tax:
                    invoice_data['taxAmount'] = tax
                    break

        # 税率
        for text, y in region_lines:
            if '税率' in text:
                rate = self._extract_rate(text)
                if rate:
                    invoice_data['taxRate'] = rate
                    break

    def _extract_date_global(self, text_lines: list, invoice_data: dict):
        """全局搜索日期"""
        for text, y in text_lines:
            date = self._extract_date(text)
            if date:
                invoice_data['invoiceDate'] = date
                break

    def _extract_numeric_value(self, lines: list, index: int, min_length: int = 6) -> str:
        """从指定行或后续行提取纯数字值"""
        # 先尝试当前行
        if index < len(lines):
            text = lines[index][0]
            # 如果当前行包含数字（可能是 "代码:12345678" 格式）
            nums = re.findall(r'\d+', text)
            for num in nums:
                if len(num) >= min_length:
                    return num

        # 尝试后续 1-2 行
        for offset in [1, 2]:
            if index + offset < len(lines):
                text = lines[index + offset][0]
                # 确保是纯数字行
                if re.match(r'^[\d\s]+$', text.strip()):
                    cleaned = text.replace(' ', '')
                    if len(cleaned) >= min_length:
                        return cleaned

        return ''

    def _extract_field_value(self, lines: list, keywords: list) -> str:
        """从多行中提取字段值"""
        for text, y in lines:
            for keyword in keywords:
                if keyword in text:
                    # 尝试提取冒号后的值
                    for sep in [':', '：', keyword]:
                        if sep in text:
                            parts = text.split(sep, 1)
                            if len(parts) > 1:
                                value = parts[1].strip()
                                if value:
                                    return value
                    # 如果没有冒号，返回整行
                    return text.strip()
        return ''

    def _extract_amount_from_line(self, text: str) -> float | None:
        """从文本行提取金额"""
        # 匹配金额格式：¥123.45, 123.45, 123,45
        patterns = [
            r'[¥￥]\s*([\d,]+\.?\d*)',  # ¥123.45
            r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?)',  # 1,234.56
            r'(\d+\.?\d*)',  # 123.45
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                amount_str = match.group(1).replace(',', '')
                try:
                    amount = float(amount_str)
                    if 0 < amount < 10000000:  # 合理范围
                        return amount
                except ValueError:
                    continue

        return None

    def _extract_rate(self, text: str) -> str:
        """提取税率"""
        patterns = [
            r'(\d+(?:\.\d+)?)%',  # 13%
            r'税率[：:]\s*(\d+(?:\.\d+)?)',  # 税率:13
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ''

    def _extract_date(self, text: str) -> str:
        """从文本提取日期"""
        patterns = [
            r'(\d{4}年\d{1,2}月\d{1,2}日)',  # 2024年1月1日
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',  # 2024-1-1 或 2024/1/1
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ''

    def get_stats(self) -> dict:
        """
        获取统计信息

        Returns:
            统计信息字典，包含总调用次数、失败次数和成功率
        """
        success_rate = 0.0
        if self.total_calls > 0:
            success_rate = (self.total_calls - self.fail_count) / self.total_calls

        return {
            'totalCalls': self.total_calls,
            'failCount': self.fail_count,
            'successRate': success_rate
        }


if __name__ == "__main__":
    # 测试代码 - 验证优化后的字段提取
    import time

    print("=" * 60)
    print("PaddleOCR 发票识别优化测试")
    print("=" * 60)

    engine = PaddleOCREngine()

    # 测试图片路径
    test_dir = "/app/output/attachments"
    import glob
    test_images = sorted(glob.glob(f"{test_dir}/*.jpg"))
    print(f"\n找到 {len(test_images)} 张测试图片\n")

    total_time = 0
    success_count = 0

    for img_path in test_images:
        print(f"\n{'─' * 60}")
        print(f"图片: {os.path.basename(img_path)}")
        print(f"{'─' * 60}")

        start_time = time.time()

        # 用完整引擎解析
        result = engine.recognize_from_file(img_path)

        elapsed = time.time() - start_time
        total_time += elapsed

        # 检查结果
        if result.get('ocr_failed'):
            print(f"❌ 识别失败: {result.get('error')}")
            continue

        success_count += 1

        # 打印提取的字段
        print(f"✅ 识别成功 ({elapsed:.2f}s)")
        print("\n提取字段:")
        for key, value in result.items():
            if key not in ('ocr_failed', 'error'):
                print(f"  {key}: {value}")

        # 字段覆盖统计
        expected_fields = ['buyerName', 'buyerTaxNo', 'sellerName', 'sellerTaxNo',
                          'invoiceCode', 'invoiceNo', 'invoiceDate', 'totalAmount', 'taxAmount']
        found_fields = [f for f in expected_fields if f in result]
        coverage = len(found_fields) / len(expected_fields) * 100
        print(f"\n字段覆盖率: {coverage:.0f}% ({len(found_fields)}/{len(expected_fields)})")

    # 汇总统计
    print(f"\n{'=' * 60}")
    print("汇总统计:")
    print(f"  总图片数: {len(test_images)}")
    print(f"  成功数: {success_count}")
    print(f"  失败数: {len(test_images) - success_count}")
    if total_time > 0:
        print(f"  平均耗时: {total_time / len(test_images):.2f}s")
    print(f"{'=' * 60}")
