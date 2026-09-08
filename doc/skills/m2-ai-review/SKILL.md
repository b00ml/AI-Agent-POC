---
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
