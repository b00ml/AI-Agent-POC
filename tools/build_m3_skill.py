"""
生成并安装 m3-invoice-audit 技能（UTF-8 写入，避免命令行编码问题）。
用法：python tools/build_m3_skill.py [--target C:/Users/asus/.codex/skills/m3-invoice-audit]

⚠️ 注意：doc/skills/m3-invoice-audit/SKILL.md 为手工维护的权威版本（可复用 AI 稽核工作流），
本脚本内嵌内容可能与之漂移，仅作历史重建参考，不推荐重跑覆盖。
"""

import os
import argparse

TARGET = r"E:\vibe_coding\poc\doc\skills\m3-invoice-audit"

SKILL_MD = """---
name: m3-invoice-audit
description: 全量发票台账稽核（M3）工作流：检测重复报销、发票抬头/税号/税率异常，输出可追溯的判断依据，并可结合制度知识库做 AI 复核（CONFIRM/DOUBT/FALSE_ALARM）。当用户要求执行发票异常检测、全量发票稽核、重复发票/抬头/税号/税率问题扫描、M3 审核流程、发票异常 AI 复核，或处理 output/reports/m3_result.json / m3_ai_review.json 时使用。
---

# M3 发票异常审核

对全量发票台账做合规稽核：重复报销、购方抬头错误、购方税号错误、税率异常。
判定以系统记录为准（无影像场景）；每条异常必须带**判断依据**（制度条款 + 比对值），
可选用 DeepSeek 结合制度知识库做 AI 复核。

## 运行工作流

1. **全量扫描**：`python main.py m3 --all`
   产物：`output/reports/m3_result.json`（duplicateInvoices + invoiceIssues，含 basis 与发票明细富化）
2. **校验结果**：`python scripts/check_m3_result.py output/reports/m3_result.json`
3. **AI 复核（可选）**：`python tools/review_m3_anomalies.py [--scope all|issues|duplicates]`
   产物：`output/reports/m3_ai_review.json`（每项 CONFIRM/DOUBT/FALSE_ALARM + 理由 + 置信度）
4. **提交**：`python tools/build_submission.py`（m3 段随 submission.json 输出）

运行依赖：ERP 开放平台 Key（含 `invoice:read`）；AI 复核需 `LLM_REVIEW_API_KEY`（DeepSeek）。

## 判定规则（详见 references/policy_rules.md）

- **重复报销**：同一 invoiceCode+invoiceNo 在台账出现 ≥2 次。依据《费用报销管理办法 V3.2》第十七条。
- **TITLE_WRONG**：仅 EXPENSE 类型发票，购方名称 ≠ 公司全称「启衡精密制造有限公司」。
- **TAXNO_WRONG**：仅 EXPENSE 类型发票，购方税号与公司税号比对不符（X 脱敏位按骨架比对）。
- **TAX_RATE_WRONG**：全类型，票种实际税率 ≠ 期望税率（HOTEL 6% / TRAIN 9% / TAXI 3% / FLIGHT 9% / VAT_GENERAL 6% / VAT_SPECIAL 13%）。

## 关键实现文件（启衡 POC 项目）

- `core/m3_processor.py`：检测逻辑 + 判断依据（basis）+ 台账缓存
- `core/llm_reviewer.py`：`review_m3_anomaly()` AI 复核（含知识库条款检索）
- `backend/app/routers/m3.py`：扫描 / ai-review / 结果接口 + 发票明细富化
- `frontend/src/views/M3Anomaly.vue`：异常列表、下钻弹窗（发票信息+影像+判断依据+AI 意见）
- `tools/review_m3_anomalies.py`：全量 AI 复核脚本
- `data/prompts/m3_ai_review.txt`：AI 复核提示词（运行时注入 m3-ai-review Skill）
- `data/rag_index/index.json`：制度知识库（条款分块）

## 易错点

- **X 脱敏**：公司税号 `91320594MA1TXXXX7Q` 中 X 为脱敏位，比对时剥除 X 后比骨架（`_taxno_matches`）。
- **票种税率**：期望税率按 invoiceKind 映射，见 references/policy_rules.md；普票 13%（办公采购）在制度上合法，AI 复核会标 DOUBT，需人工确认。
- **只查 EXPENSE**：抬头/税号只对 EXPENSE 类型发票稽核（销售/采购发票购方不是公司）。
- **富化兜底**：采购进项发票不在报销单里，详情下钻需用台账缓存 `output/cache/invoice_ledger.json` 兜底。
- **影像**：历史票据 `migrated=false` 无法下载，前端显示「未迁移」而非报错。
- **判断依据必带**：每条异常必须包含 `basis`（制度出处 + 比对值），缺失即视为不合格输出。
- **AI 口径**：`CONFIRM`=成立、`DOUBT`=存疑需人工、`FALSE_ALARM`=规则误报；AI 只给意见不改判定结果。
"""

POLICY_RULES_MD = """# M3 判定规则与判断依据

## 制度依据

### 发票合规指引（2025-06）
- 一、抬头与税号：公司全称「启衡精密制造有限公司」，纳税人识别号「91320594MA1TXXXX7Q」。
  常见错误：启衡→启恒、仅写简称「启衡精密」、分公司抬头（公司无分公司）、行业词误写「精密机械」。
- 二、税率适用：

| 供应商类别/业务 | 适用税率 |
|---|---|
| 原材料采购 / 外协加工 / 办公采购 | 13% |
| 服务类（物流、检测、咨询、设备维护） | 6% |
| 住宿服务 | 6% |
| 旅客运输（铁路、航空客票） | 9% |
| 出租车客运 | 3% |

- 三、查重：同一发票代码与号码组合在台账出现两次以上即重复报销。

### 费用报销管理办法 V3.2
- 第十七条：同一张发票不得重复报销，财务部应当对发票号码查重。

## 期望税率映射（按 invoiceKind）

```python
EXPECTED_TAX_RATE = {
    "HOTEL": 0.06,      # 住宿服务
    "TRAIN": 0.09,      # 旅客运输（铁路）
    "TAXI": 0.03,       # 出租车客运
    "FLIGHT": 0.09,     # 旅客运输（航空）
    "VAT_GENERAL": 0.06,  # 增值税普通发票（服务类为主）
    "VAT_SPECIAL": 0.13,  # 增值税专用发票（货物/加工类为主）
}
```

## 判定规则

| 代码 | 范围 | 规则 | 判断依据模板 |
|---|---|---|---|
| DUPLICATE_INVOICE | 全台账 | invoiceCode+invoiceNo 出现 ≥2 次 | 依据《费用报销管理办法 V3.2》第十七条：同一张发票不得重复报销（发票代码+号码在台账中出现 2 次以上） |
| TITLE_WRONG | 仅 EXPENSE | 购方名称归一化后 ≠ 公司全称 | 依据《发票合规指引》一、抬头与税号：发票抬头必须为「启衡精密制造有限公司」全称，实为「…」 |
| TAXNO_WRONG | 仅 EXPENSE | 购方税号骨架比对不符 | 依据《发票合规指引》一、抬头与税号：纳税人识别号必须为「91320594MA1TXXXX7Q」，实为「…」 |
| TAX_RATE_WRONG | 全类型 | 票种实际税率 ≠ 期望税率 | 依据《发票合规指引》二、税率适用：{票种}应适用 {期望}% 税率，实为 {实际}% |

## 税号比对（X 脱敏）

公司税号在系统中以 `91320594MA1TXXXX7Q` 存储，X 为脱敏占位：
剥除 X/x 后比较剩余骨架，骨架不一致即违规。OCR 可能漏读/多读 X，剥除后不受影响。

## 判定口径

- M3 以系统记录为准（绝大多数发票无影像）；M2 逐单审核才以票面影像为准。
- 抬头/税号只对 type=EXPENSE 稽核；税率对全部类型稽核。
- 误报代价高：仅上报与主流不一致的少数记录，不做全量上报。
"""

API_DATA_MD = """# 数据源与产物格式

## 数据源（ERP 开放平台）

| 接口 | 权限 | 用途 |
|---|---|---|
| GET /v1/invoices | invoice:read | 全量发票台账（约 23,461 张，游标分页 limit≤200） |
| GET /v1/expense-claims | expense:read | 报销单列表/详情（发票→单据关联） |
| GET /v1/expense-claims/{id} | expense:read | 单据详情（lines→invoice/attachment） |

## 本地缓存（output/cache/）

| 文件 | 内容 |
|---|---|
| all_claims.json | 全量 5,992 单详情（发票→单据/附件映射） |
| invoice_ledger.json | 全量发票台账原始记录（M3 扫描时写入） |
| ocr_all_paddle.json / ocr_samples_paddle.json | 本地 OCR 票面要素缓存（按附件 id） |

## 产物

### output/reports/m3_result.json

```json
{
  "duplicateInvoices": [
    {
      "invoiceCode": "924849539658", "invoiceNo": "00010763",
      "claimIds": ["BX-000107", "BX-005692"],
      "basis": "依据《费用报销管理办法 V3.2》第十七条：…",
      "invoices": [
        {"invoiceId": "INV-…", "claimNo": "…", "lineNo": 2, "buyerName": "…",
         "sellerName": "…", "totalFen": 12345, "taxRate": 0.06,
         "attachmentId": "ATT-…", "migrated": false}
      ]
    }
  ],
  "invoiceIssues": [
    {"invoiceId": "INV-…", "issue": "TITLE_WRONG",
     "basis": "依据《发票合规指引》一、抬头与税号：…",
     "invoice": {"invoiceCode": "…", "invoiceNo": "…", "buyerName": "…",
                 "buyerTaxNo": "…", "sellerName": "…", "taxRate": 0.06,
                 "totalFen": 100, "attachmentId": "ATT-…", "migrated": true}}
  ]
}
```

### output/reports/m3_ai_review.json

```json
{
  "generatedAt": "…", "model": "deepseek-v4-flash",
  "total": 153, "failed": 0,
  "results": {
    "issue:INV-003265": {"verdict": "DOUBT", "reasons": ["…"], "confidence": 0.7},
    "duplicate:924849539658/00010763": {"verdict": "CONFIRM", "reasons": ["…"], "confidence": 0.9}
  }
}
```

结果键：`issue:{invoiceId}` 或 `duplicate:{invoiceCode}/{invoiceNo}`。

### submission.json m3 段（机器评分）

```json
"m3": {
  "duplicateInvoices": [{"invoiceCode": "…", "invoiceNo": "…", "claimIds": ["…"]}],
  "invoiceIssues": [{"invoiceId": "…", "issue": "TITLE_WRONG|TAXNO_WRONG|TAX_RATE_WRONG"}]
}
```

提交口径：评分按 invoiceId+issue 精确匹配；误报同样扣分，只上报真正异常。
"""

CHECK_SCRIPT = '''"""校验 M3 扫描结果文件：字段完整、判断依据必带。

注意：m3_result.json 只包含原始判定（含 basis），发票明细富化（invoices/invoice）
由后端接口在响应时从缓存补齐，不在文件中校验。
"""

import sys
import json


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "output/reports/m3_result.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    dups = data.get("duplicateInvoices", [])
    issues = data.get("invoiceIssues", [])
    problems = []

    for d in dups:
        if not d.get("invoiceCode") or not d.get("invoiceNo"):
            problems.append("重复组缺发票代码/号码")
        if not d.get("claimIds"):
            problems.append(f"重复组 {d.get('invoiceCode')}/{d.get('invoiceNo')} 缺关联单据")
        if not d.get("basis"):
            problems.append(f"重复组 {d.get('invoiceCode')}/{d.get('invoiceNo')} 缺判断依据")

    for it in issues:
        if not it.get("invoiceId"):
            problems.append("票面问题缺 invoiceId")
        if it.get("issue") not in ("TITLE_WRONG", "TAXNO_WRONG", "TAX_RATE_WRONG"):
            problems.append(f"{it.get('invoiceId')} 未知 issue 类型 {it.get('issue')}")
        if not it.get("basis"):
            problems.append(f"{it.get('issue')} {it.get('invoiceId')} 缺判断依据")

    print(f"重复发票组: {len(dups)}")
    print(f"票面问题: {len(issues)}")
    if problems:
        print(f"发现 {len(problems)} 个问题:")
        for p in problems[:20]:
            print("  -", p)
        sys.exit(1)
    print("校验通过：字段完整，所有异常均带判断依据。")


if __name__ == "__main__":
    main()
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=TARGET)
    args = parser.parse_args()
    target = args.target
    os.makedirs(os.path.join(target, "references"), exist_ok=True)
    os.makedirs(os.path.join(target, "scripts"), exist_ok=True)
    os.makedirs(os.path.join(target, "agents"), exist_ok=True)

    files = {
        "SKILL.md": SKILL_MD,
        "references/policy_rules.md": POLICY_RULES_MD,
        "references/api_data.md": API_DATA_MD,
        "scripts/check_m3_result.py": CHECK_SCRIPT,
        "agents/openai.yaml": (
            'interface:\n'
            '  display_name: "M3 发票异常审核"\n'
            '  short_description: "发票台账全量稽核、异常判定（重复/抬头/税号/税率）与 AI 复核工作流"\n'
            '  default_prompt: "Use $m3-invoice-audit to run and verify the M3 invoice anomaly audit '
            '(duplicates, title/taxno/rate issues) with judgment basis and AI review."\n'
        ),
    }
    for rel, content in files.items():
        path = os.path.join(target, rel)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("written:", path)
    print("done")


if __name__ == "__main__":
    main()
