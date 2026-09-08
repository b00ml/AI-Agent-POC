---
name: m3-invoice-audit
description: 发票台账 AI 稽核工作流（可复用 Skill）：对全量发票台账执行「规则扫描 → 校验门禁 → AI 复核 → AI 全量巡检 → 人工处置」的固定流程，输出可追溯的异常清单与 AI 意见。当用户要求执行发票异常检测、全量发票稽核、重复发票/抬头/税号/税率扫描、发票异常 AI 复核、AI 全量巡检，或处理 m3_result.json / m3_ai_review.json / m3_ai_scan.json 时使用。
---

# 发票台账 AI 稽核工作流（M3）

把一个「发票台账 → 合规异常清单 + AI 意见」的固定 AI 工作流封装为可复用 Skill：
规则引擎全量兜底（宁可错杀）→ AI 复核精筛（只给意见）→ 人工处置并留痕。

## 何时使用（触发）

- 用户要求稽核发票台账/发票异常/重复报销/抬头/税号/税率/连号/供应商档案；
- 用户要求对异常做 AI 复核（确认/存疑/误报）或 AI 全量巡检；
- 需要产出可下钻、可追溯（每条带判断依据）的发票异常清单。

## 输入契约

| 输入 | 说明 | 必填 |
|---|---|---|
| 发票台账 | 全量发票（含 invoiceCode/No、type、invoiceKind、taxRate、buyer/seller、totalFen、issuedOn） | 是 |
| 报销单-发票关联 | 定位重复报销落在哪些单据（无则退化为台账口径） | 否 |
| 公司基准 | 公司全称「启衡精密制造有限公司」、税号 `91320594MA1TXXXX7Q` | 是 |
| 制度版本 | 《费用报销管理办法 V3.2》等（含「同时废止」条款处理） | 是 |
| AI 凭证 | LLM API Key（AI 复核/巡检需要；缺失则跳过 AI 步骤） | 否 |

## 执行工作流（决策式）

> 步骤类型标注：**工具执行** = 由 Agent 调用确定性代码/脚本完成（非大模型推理）；
> **LLM 推理** = 调用大模型做语义判断；**人工** = 财务操作人决策。

1. **准备输入**〔工具执行〕：加载台账与单据关联；确认公司基准与制度版本（旧版 2.1 未下架陷阱：只认 V3.2）。
2. **规则扫描**〔工具执行〕：运行 `core/m3_processor.py` 规则代码做全量检测（重复/疑似重复/抬头/税号/税率/连号/供应商重复档案 + 疑似虚开画像）。
   - 分支 A 无异常 → 直接输出空清单，结束（无需 AI）；
   - 分支 B 有异常 → 继续步骤 3。
3. **校验门禁**〔工具执行〕：运行 `scripts/check_m3_result.py` 校验字段完整、**每条异常必带 basis**、issue 类型合法。
   - 校验失败 → 修复输出后重跑，禁止带着缺依据的异常交付。
4. **AI 复核异常**〔LLM 推理〕（对已筛异常逐条）：结合制度知识库，输出 `CONFIRM / DOUBT / FALSE_ALARM` + 理由 + 置信度。
   - 该环节由 `m3-ai-review` Skill 驱动：运行时把 `doc/skills/m3-ai-review/SKILL.md` 注入提示词作为执行工作流。
   - 分支：API 失败 → 按规则结论降级（不阻塞）；结果键须含异常类型（`issue:TITLE_WRONG:INV-x`），避免同发票多问题互相覆盖。
5. **AI 全量巡检**〔LLM 推理〕（可选，找规则盲区）：分批初筛（每批 60 张），AI 输出疑似清单。
   - 护栏：`invoiceId` 必须来自本批（防幻觉白名单校验）；`limit` 支持小批量演示。
6. **人工处置与提交**〔人工〕：AI 只给意见不改结论；异常/画像可下钻影像；按需生成 submission。

## 输出契约

- `duplicateInvoices[]`：`{invoiceCode, invoiceNo, claimIds?, suspected?, basis}`；
- `invoiceIssues[]`：`{invoiceId, issue, basis, invoiceIds?(SUPPLIER_DUP)}`，issue ∈ {TITLE_WRONG, TAXNO_WRONG, TAX_RATE_WRONG, CONSECUTIVE_NO, SUPPLIER_DUP}；
- `supplierProfiles[]`：疑似虚开画像（开票张数/连号段/低额占比/单月集中度 + basis）；
- AI 复核：`results["issue:{type}:{invoiceId}" | "duplicate:{code}/{no}"] = {verdict, reasons, confidence}`；
- 每条异常必须带 `basis`（制度出处 + 比对值），否则视为不合格输出。

## 护栏

- AI 只给意见，不改变规则判定与单据状态；
- 宁可错杀不可放：疑似重复/连号/科目类一律先报，交给 AI 复核与人工过滤；
- 宁缺毋滥（对账口径）：无法唯一确认的不强行匹配；
- X 脱敏：税号剥除 X 后比骨架；抬头只查 EXPENSE（销售/采购发票购方非公司）；
- 影像：历史票据 `migrated=false` 显示「未迁移」而非报错；
- 判断依据必带：缺 `basis` 即不合格（校验门禁拦截）。

## 边界

- 台账无关联单据：重复报销退化为台账口径（suspected=true 允许无 claimIds，但必须有 basis）；
- AI Key 缺失或 API 失败：跳过/降级为规则结论，不阻塞主流程；
- 未知 issue 类型 / 缺字段 / JSON 损坏：校验脚本报错并拒绝交付；
- 全量巡检批次失败：记录失败批数，不中断其余批次；
- 普票 13%（办公采购）制度合法：规则不判错，AI 复核标 DOUBT 供人工确认。

## 3 条测试结果

运行 `python -B scripts/test_m3_skill.py`（无第三方依赖）：

```text
T1 正常流程(校验通过)          : []
T2 失败场景(缺basis被拦截)     : ['TITLE_WRONG I1 缺判断依据']
T3 边界(未知issue被拦截)       : ['I2 未知 issue 类型 UNKNOWN_TYPE']
T3 边界(疑似重复无单据不误报)  : {'invoiceCode': 'C2', 'invoiceNo': 'N2', 'otherCodes': ['C3'], 'claimIds': [], 'suspected': True, 'basis': '同一发票号码出现在多个代码下，需人工确认'}

3 条测试全部通过 [OK]
```

真实报告门禁（`python -B scripts/check_m3_result.py output/reports/m3_result.json`）：

```text
重复发票组: 42
票面问题: 135
校验通过：字段完整，所有异常均带判断依据
```

## 附录：本项目映射

- `core/m3_processor.py`：规则检测 + basis + 台账缓存；`core/m3_ai_scan.py`：AI 全量巡检
- `core/llm_reviewer.py`：`review_m3_anomaly()` AI 复核（知识库检索）
- `backend/app/routers/m3.py`：scan / ai-review / ai-scan / results 接口 + 发票明细富化
- `frontend/src/views/M3Anomaly.vue`：异常/画像/巡检结果 + 影像下钻
- 提示词：`data/prompts/m3_ai_review.txt`（AI 复核，注入 `m3-ai-review` Skill）、`m3_full_scan.txt`（AI 巡检）；知识库 `data/rag_index/index.json`
- CLI：`python main.py m3 --all`；产物 `output/reports/m3_result.json` / `m3_ai_review.json` / `m3_ai_scan.json`
