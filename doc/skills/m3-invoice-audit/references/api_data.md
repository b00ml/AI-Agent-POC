# 数据源与产物格式

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
