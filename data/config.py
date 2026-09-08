"""
系统配置文件

包含公司信息、常量定义、API配置等
"""

import os

# 公司信息。公开 Demo 使用合成身份，真实 ERP 运行保持原有配置口径。
DEMO_MODE = os.environ.get("DEMO_MODE", "0").strip().lower() in {"1", "true", "yes"}
COMPANY_NAME = os.environ.get(
    "QIHENG_COMPANY_NAME",
    "示例制造有限公司" if DEMO_MODE else "启衡精密制造有限公司",
)
COMPANY_TAX_NO = os.environ.get(
    "QIHENG_COMPANY_TAX_NO",
    "91320594MA1TEST001" if DEMO_MODE else "91320594MA1TXXXX7Q",
)

# API配置
API_BASE_URL = os.environ.get("QIHENG_BASE_URL", "http://localhost:8081")
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 5

# OCR引擎配置
# 默认 "paddle"：本地 PaddleOCR 识别，发票图片不出域（符合数据安全要求）
# 可选 "qwen"：阿里云百炼千问VL 云端识别（需 DASHSCOPE_API_KEY，数据出域需申报）
OCR_ENGINE = os.environ.get("OCR_ENGINE", "paddle")

# 违规代码枚举
VIOLATION_CODES = [
    "OVER_STANDARD_HOTEL",
    "OVER_STANDARD_MEAL",
    "OVER_STANDARD_CITY_TRANSPORT",
    "OVER_STANDARD_TRANSPORT_CLASS",
    "INVOICE_TITLE_MISMATCH",
    "INVOICE_TAXNO_MISMATCH",
    "DUPLICATE_INVOICE",
    "MISSING_APPROVAL_OVERTIME_TAXI",
    "MISSING_ATTACHMENT",
    "AMOUNT_MISMATCH"
]

# 票面问题代码
INVOICE_ISSUE_CODES = ["TITLE_WRONG", "TAXNO_WRONG", "TAX_RATE_WRONG"]

# 审核结论枚举
AUDIT_RESULTS = ["APPROVE", "REJECT", "FLAG"]

# 费用类型映射
EXPENSE_TYPE_MAP = {
    "HOTEL": "住宿费",
    "MEAL": "伙食补助",
    "LONG_TRANSPORT": "长途交通",
    "CITY_TRANSPORT": "市内交通",
    "TAXI": "打车费"
}

# 审批动作类型
APPROVAL_ACTIONS = {
    "SUBMIT": "提交",
    "APPROVE": "同意",
    "REJECT": "驳回",
    "SPECIAL_APPROVE": "特批"
}

# 城市档次映射（从API获取，此处为默认值）
DEFAULT_CITY_TIERS = {
    "上海": "TIER1",
    "北京": "TIER1",
    "广州": "TIER1",
    "深圳": "TIER1",
    "杭州": "TIER1",
    "南京": "TIER2",
    "苏州": "TIER2",
    "成都": "TIER2",
    "重庆": "TIER2",
    "武汉": "TIER2",
    "西安": "TIER2",
    "青岛": "TIER2",
    "潍坊": "TIER3",
    "其他": "TIER3"
}

# 输出路径
OUTPUT_DIR = "output"
REPORTS_DIR = "output/reports"
SUBMISSION_FILE = "output/submission.json"

# 环境配置
SEED = "qiheng-2026-v1"

# 评测配置（公开样例随仓库交付，自包含）
PUBLIC_SAMPLE_FILE = os.environ.get(
    "QIHENG_SAMPLE_LABELS"
) or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "labels", "public-sample-labels.json")
