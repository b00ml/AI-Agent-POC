"""
生成 m2-ai-review 技能（UTF-8 写入项目 doc/skills/）。
用法：python tools/build_m2_skill.py

⚠️ 注意：doc/skills/m2-ai-review/SKILL.md 为手工维护的权威版本，本脚本内嵌内容
可能与之漂移，仅作历史重建参考，不推荐重跑覆盖。
"""

import os
import argparse

TARGET = r"E:\vibe_coding\poc\doc\skills\m2-ai-review"

SKILL_MD = """---
name: m2-ai-review
description: M2 智能报销审核与 AI 复核工作流：逐单合规审核（11 种违规）、以票面为准的 OCR 比对、特批豁免、审核意见回写 ERP、AI 独立复核（默认开启，由 m2-claim-review 环节 Skill 驱动；分歧转 FLAG）、30 单公开样例评测与 submission.m2 生成。当用户要求执行报销单审核、差旅费用合规检查、审核意见回写、AI 复核报销单、处理 output/reports/audit_report.json / submission.m2 / evaluation_result.json 时使用。
---

# M2 智能报销审核（含 AI 复核）

对待审报销单逐单执行 11 种违规检测，以票面影像为准（本地 OCR），查审批记录做特批豁免，
输出 APPROVE / REJECT / FLAG 并回写 ERP（AI 只给意见，不改变单据状态）。

## 运行工作流

1. **全量审核**：`python main.py m2 --all`（默认回写；`--no-write` 只计算）
2. **校验结果**：`python scripts/check_m2_result.py output/reports/audit_report.json`
3. **AI 复核**：默认开启（设置页可关闭）；环节由 `m2-claim-review` Skill 驱动（运行时注入提示词）
   规则与 LLM 结论不一致时自动转 FLAG，双意见写入理由
4. **评测**：`python main.py evaluate`（30 单公开样例，本地 OCR，无数据出域）
5. **提交**：`python tools/build_submission.py` + 官方 `validate-submission.mjs` 校验

## 判定规则（详见 references/policy_rules.md）

| # | 违规代码 | 口径 |
|---|---|---|
| R1 | OVER_STANDARD_HOTEL | 每晚单价=总额÷晚数，比对职级+城市档标准 |
| R2 | OVER_STANDARD_MEAL | 天数=住宿晚数+1，日均比对 |
| R3 | OVER_STANDARD_CITY_TRANSPORT | 总额 vs 标准×天数 |
| R4 | OVER_STANDARD_TRANSPORT_CLASS | 舱位/席别 vs 职级（员工二等/经理一等/总监经济/高管公务） |
| R5 | INVOICE_TITLE_MISMATCH | 抬头须为公司全称（OCR 票面优先） |
| R6 | INVOICE_TAXNO_MISMATCH | 税号比对（剥 X 脱敏位比骨架） |
| R7 | AMOUNT_MISMATCH | 费用行金额 vs 票面金额 |
| R8 | DUPLICATE_INVOICE | code+no 跨全量单据重复 |
| R9 | MISSING_APPROVAL_OVERTIME_TAXI | 加班打车（CITY_TRANSPORT+加班）须事前审批 |
| R10 | MISSING_ATTACHMENT | 有发票无附件 |

## 关键实现文件（启衡 POC 项目）

- `core/auditor.py`：十规则引擎 + 特批豁免 + 城市未知 FLAG
- `core/m2_processor.py`：流程编排（OCR→全量查重索引→审核→AI 复核→回写）
- `core/local_ocr.py` / `invoice_ocr.py`：本地 PaddleOCR（默认）+ 千问可选，缓存按引擎隔离
- `core/llm_reviewer.py`：AI 复核（制度知识库检索 + DeepSeek；注入 `doc/skills/m2-claim-review/SKILL.md` 作为环节工作流）
- `core/claim_store.py`：全量单据缓存与发票索引（跨历史查重）
- `backend/app/routers/m2.py`：audit/review/ocr 接口（review 同时含 AI 建议与操作人决定）
- `frontend/src/views/M2Audit.vue` / `M2Detail.vue`：批量审核、三栏比对、人工复核
- `tools/verify_results.py`：特批/加班打车/重复/附件/城市交叉验证
- `tests/ui_e2e.py`：前端 E2E

## 易错点

- **以票面为准**：OCR 结果优先于系统录入（陷阱单如系统简称但票面全称）；OCR 失败/票面无购方栏时按系统字段判定并显式标注
- **每晚单价口径**：住宿按总额÷晚数，不能拿总额比；伙食天数=晚数+1
- **税号 X 脱敏**：公司税号 `91320594MA1TXXXX7Q` 中 X 为脱敏位，剥除后比骨架；OCR 漏读 X 不影响
- **特批豁免**：必须先查审批记录（`/v1/approvals?refId=`），SPECIAL_APPROVE 豁免超标类（约三成超标单有特批）
- **全量查重**：重复报销需跨全量历史单据（5992 单），不能只查待审池
- **日常单**：业务用餐等日常费用不套差旅补助标准（仅 TRAVEL 单适用 R1-R4）
- **城市未知**：标 FLAG，不静默假设 TIER3
- **回写**：POST review 必须带 violations/reasons/confidence/evidence；不改变单据状态
- **局部运行**：`--limit`/接口局部审核不覆盖全量 audit_report.json
- **AI 复核**：默认开启，外发单据文本字段（不含图片，已申报）；分歧转 FLAG 时理由写明「规则=X，AI=Y」
"""

POLICY_RULES_MD = """# M2 判定规则与制度依据

## 制度依据

### 费用报销管理办法 V3.2（现行，V2.1 已废止）
- 第五条：住宿费以每晚单价为口径（总额÷实际住宿天数）。
- 第六条：伙食补助按天，出差天数=住宿晚数+1。
- 第七条：城市分档（一类：上海/北京/广州/深圳；二类：南京/厦门/天津/宁波/成都/杭州/武汉/西安/郑州/重庆/长沙/青岛；三类：东莞/佛山/南通/合肥/嘉兴/常州/无锡/昆山/株洲/洛阳/潍坊/烟台/珠海/绍兴）。
- 第八条：长途交通不得超标准乘坐（员工二等座/经理一等座/总监经济舱/高管公务舱）。
- 第九~十一条：超标需事前财务总监特批（SPECIAL_APPROVE），已特批不认定为违规。
- 第十三条：加班期间市内交通（含出租车/网约车）须事前主管审批。
- 第十六条：发票抬头必须为公司全称、税号必须为 `91320594MA1TXXXX7Q`。
- 第十七条：同一发票不得重复报销。
- 第十八条：报销金额应与票面金额一致。

### 差旅标准（接口 /v1/travel-standards）
按 (jobLevel, cityTier) 提供：hotelCapPerNightFen / mealAllowancePerDayFen /
cityTransportPerDayFen / longDistanceClass。金额一律用分（整数）计算。

## 违规代码与判断依据模板

| 代码 | 判定 | 判断依据模板 |
|---|---|---|
| OVER_STANDARD_HOTEL | 每晚单价>标准 | `费用行N发票{code/no}住宿{实报}元/晚，超过{职级}{档}标准{标准}元/晚` |
| OVER_STANDARD_MEAL | 日均>标准 | `{职级}伙食补助标准{标准}元/天，实报{日均}元/天` |
| OVER_STANDARD_CITY_TRANSPORT | 总额>标准×天数 | `市内交通标准{标准}元/天×{天数}天，实报{实报}元` |
| OVER_STANDARD_TRANSPORT_CLASS | 舱位>职级 | `{职级}长途交通标准为{标准}，实报{描述}` |
| INVOICE_TITLE_MISMATCH | 抬头≠公司全称 | `{loc}抬头为「{实报}」，与公司名称「启衡精密制造有限公司」不符{basis}` |
| INVOICE_TAXNO_MISMATCH | 税号骨架不符 | `{loc}购方税号为「{实报}」，与公司税号不符{basis}` |
| AMOUNT_MISMATCH | 行金额≠票面 | `报销金额{行}元，票面{票面}元` |
| DUPLICATE_INVOICE | code+no 跨单重复 | `发票{code/no}已在其他报销单中使用过` |
| MISSING_APPROVAL_OVERTIME_TAXI | 加班打车无事前审批 | `制度要求加班打车须事前审批，本单无审批记录` |
| MISSING_ATTACHMENT | 有发票无附件 | `费用行{lineNo}缺少票据附件` |

说明：`loc` 包含费用行号与发票代码/号码；`basis` 标注「OCR票面识别」或
「票面无购方信息，按系统录入判定」。

## 特批豁免与边界

- `SPECIAL_APPROVE` 动作存在 → 豁免所有 OVER_STANDARD_* 违规
- 城市不在档次表 → FLAG（不做默认档次假设）
- 附件 `migrated=false` → 无法下载影像 → FLAG
- OCR 为空（高铁票无购方栏）→ 不判票面差异，按系统录入判定并标注
"""

API_DATA_MD = """# 数据源与产物格式（M2）

## 数据源（ERP 开放平台）

| 接口 | 权限 | 用途 |
|---|---|---|
| GET /v1/expense-claims | expense:read | 待审单列表（游标分页，limit≤200） |
| GET /v1/expense-claims/{id} | expense:read | 单据详情（lines→invoice/attachment/trip） |
| GET /v1/approvals?refId= | approval:read | 审批记录（特批/事前审批） |
| GET /v1/travel-standards | master-data:read | 差旅标准 |
| GET /v1/cities | master-data:read | 城市档次 |
| GET /v1/attachments/{id}/content | attachment:read | 票据影像 |
| POST /v1/expense-claims/{id}/review | expense:review | 回写审核意见（不改变状态） |

## 本地缓存（output/cache/）

| 文件 | 内容 |
|---|---|
| all_claims.json | 全量 5,992 单详情（跨历史查重索引） |
| ocr_all_paddle.json / ocr_samples_paddle.json | 本地 OCR 票面要素（按附件 id） |

## 产物

### output/reports/audit_report.json

```json
{
  "generatedAt": "...", "totalClaims": 300,
  "approveCount": 138, "rejectCount": 162, "flagCount": 0,
  "reviews": [
    {"claimId": "BX-005693", "result": "REJECT",
     "violations": ["INVOICE_TITLE_MISMATCH"],
     "reasons": ["费用行3发票908249853275/47011402抬头为「启衡精密机械有限公司」…"],
     "confidence": 0.75}
  ]
}
```

### submission.json m2 段（机器评分）

```json
"m2": {
  "reviews": [
    {"claimId": "...", "result": "APPROVE|REJECT|FLAG",
     "violations": ["..."], "reasons": ["..."], "confidence": 0.0-1.0}
  ]
}
```

评分口径：REJECT 与 FLAG 同等视为「提请关注」；违规代码需与标答完全一致；
陷阱单（看似违规实则合规）判错额外扣分。

## 回写格式

POST /v1/expense-claims/{id}/review 请求体：`result`、`reasons`、`violations`、
`confidence`、`evidence`（可选 policy 引用）。操作人复核提交时理由合并
「AI 建议理由 + 操作人意见」，违规代码在操作人与 AI 一致时保留。
"""

CHECK_SCRIPT = '''"""校验 M2 审核结果：条数、claimId 唯一、结论合法、理由与违规代码完整。"""

import sys
import json

VALID_RESULTS = {"APPROVE", "REJECT", "FLAG"}
VALID_VIOLATIONS = {
    "OVER_STANDARD_HOTEL", "OVER_STANDARD_MEAL", "OVER_STANDARD_CITY_TRANSPORT",
    "OVER_STANDARD_TRANSPORT_CLASS", "INVOICE_TITLE_MISMATCH", "INVOICE_TAXNO_MISMATCH",
    "DUPLICATE_INVOICE", "MISSING_APPROVAL_OVERTIME_TAXI", "MISSING_ATTACHMENT",
    "AMOUNT_MISMATCH",
}


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "output/reports/audit_report.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    reviews = data.get("reviews", [])
    problems = []
    seen = set()
    for r in reviews:
        cid = r.get("claimId")
        if not cid:
            problems.append("存在缺 claimId 的审核记录")
        elif cid in seen:
            problems.append(f"claimId 重复: {cid}")
        else:
            seen.add(cid)
        if r.get("result") not in VALID_RESULTS:
            problems.append(f"{cid} result 非法: {r.get('result')}")
        if r.get("result") == "REJECT" and not r.get("reasons"):
            problems.append(f"{cid} REJECT 但无理由")
        for v in r.get("violations") or []:
            if v not in VALID_VIOLATIONS:
                problems.append(f"{cid} 未知违规代码: {v}")
        conf = r.get("confidence")
        if conf is not None and not (0 <= conf <= 1):
            problems.append(f"{cid} confidence 越界: {conf}")

    from collections import Counter
    dist = Counter(r.get("result") for r in reviews)
    print(f"审核记录: {len(reviews)} 条 | {dict(dist)}")
    if len(seen) != len(reviews):
        problems.append(f"claimId 唯一数 {len(seen)} != 记录数 {len(reviews)}")
    if problems:
        print(f"发现 {len(problems)} 个问题:")
        for p in problems[:20]:
            print("  -", p)
        sys.exit(1)
    print("校验通过：记录完整、结论/违规代码/理由合法。")


if __name__ == "__main__":
    main()
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=TARGET)
    args = parser.parse_args()
    target = args.target
    for sub in ("references", "scripts", "agents"):
        os.makedirs(os.path.join(target, sub), exist_ok=True)

    files = {
        "SKILL.md": SKILL_MD,
        "references/policy_rules.md": POLICY_RULES_MD,
        "references/api_data.md": API_DATA_MD,
        "scripts/check_m2_result.py": CHECK_SCRIPT,
        "agents/openai.yaml": (
            'interface:\n'
            '  display_name: "M2 智能报销审核（AI 复核）"\n'
            '  short_description: "报销单合规审核、AI 复核与回写 ERP 工作流"\n'
            '  default_prompt: "Use $m2-ai-review to run and verify the M2 expense claim review '
            '(10 rules, invoice-image-first OCR, special approval exemption, AI second opinion '
            'with FLAG on disagreement) and write back review opinions."\n'
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
