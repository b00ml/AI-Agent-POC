# M2 判定规则与制度依据

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
