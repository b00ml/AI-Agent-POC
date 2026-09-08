# 数据发布说明

公开仓库只允许发布合成 Demo 数据。真实 ERP 返回的报销单、发票影像、银行流水、账户信息、员工/供应商/客户资料和内部制度原文不得提交。

推荐公开数据结构：

```text
data/demo/
├── claims.json
├── invoices.json
├── bank_transactions.csv
├── policies.md
└── expected_results.json
```

每个 fixture 应满足：

- 公司、人员、供应商、客户和账户均为虚构名称；
- 税号、发票号、银行账号和流水号使用明显的测试值；
- 不含可识别个人信息、真实票据影像或内部文档原文；
- 在数据文件或生成脚本中写明来源为 synthetic/demo；
- `expected_results.json` 只用于回归测试，不代表真实业务结论。

原始 `bank/` 和 `data/source-docs/` 内容属于私有交付/开发输入，发布前必须完成授权确认并从公开仓库移除。
