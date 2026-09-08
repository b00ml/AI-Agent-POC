# 数据源与产物格式（M2）

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
