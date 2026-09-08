#!/usr/bin/env node
// submission.json 格式校验器（零依赖，直接 node 运行）
// 用法：node validate-submission.mjs submission.json
import { readFileSync } from 'node:fs'

const SUBMISSION_VERSION = 1;
const VIOLATION_CODES = [
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
];
const INVOICE_ISSUE_CODES = ["TITLE_WRONG", "TAXNO_WRONG", "TAX_RATE_WRONG"];
const PENDING_CLAIM_COUNT = 300;
function validateSubmission(raw) {
  const issues = [];
  const err = (path, message) => issues.push({ path, message, severity: "error" });
  const warn = (path, message) => issues.push({ path, message, severity: "warning" });
  if (typeof raw !== "object" || raw === null) {
    err("$", "\u6587\u4EF6\u6839\u8282\u70B9\u5FC5\u987B\u662F JSON \u5BF9\u8C61");
    return issues;
  }
  const s = raw;
  if (s.version !== SUBMISSION_VERSION) {
    err("version", `version \u5FC5\u987B\u4E3A ${SUBMISSION_VERSION}\uFF0C\u5B9E\u9645\u4E3A ${JSON.stringify(s.version)}`);
  }
  const m = s.meta;
  if (!m || typeof m !== "object") {
    err("meta", "meta \u7F3A\u5931");
  } else {
    if (!m.team?.trim()) err("meta.team", "\u961F\u4F0D\u540D\u79F0\u4E0D\u80FD\u4E3A\u7A7A");
    if (!Array.isArray(m.members) || m.members.length === 0) err("meta.members", "\u6210\u5458\u5217\u8868\u4E0D\u80FD\u4E3A\u7A7A");
    else if (m.members.length > 4) err("meta.members", "\u7EC4\u961F\u4EBA\u6570\u4E0A\u9650\u4E3A 4 \u4EBA");
    if (!m.seed?.trim()) err("meta.seed", "\u5FC5\u987B\u586B\u5199\u73AF\u5883 seed\uFF08\u89C1\u5B66\u5458\u5305 README \u9996\u884C\uFF09");
    if (!Array.isArray(m.aiModels) || m.aiModels.length === 0) {
      warn("meta.aiModels", "\u672A\u58F0\u660E\u6240\u7528\u6A21\u578B\u670D\u52A1\uFF1B\u82E5\u5B9E\u9645\u4F7F\u7528\u4E86\u5916\u90E8\u6A21\u578B\uFF0C\u5B89\u5168\u5206\u4F1A\u6263\u5206");
    }
    if (!Array.isArray(m.dataEgress)) {
      warn("meta.dataEgress", "\u672A\u63D0\u4EA4\u6570\u636E\u51FA\u57DF\u8BF4\u660E\uFF0C\u5B89\u5168\u5206\u4F1A\u6263\u5206");
    }
    if (!Array.isArray(m.apiScopes) || m.apiScopes.length === 0) {
      warn("meta.apiScopes", "\u672A\u58F0\u660E\u7533\u8BF7\u7684 API \u6743\u9650\u8303\u56F4\uFF0C\u6700\u5C0F\u6743\u9650\u9879\u65E0\u6CD5\u8BA1\u5206");
    }
  }
  if (!s.m2 || !Array.isArray(s.m2.reviews)) {
    err("m2.reviews", "M2 \u662F\u4E3B\u7EBF\u5FC5\u505A\u9879\uFF0Creviews \u7F3A\u5931");
  } else {
    const seen = /* @__PURE__ */ new Set();
    s.m2.reviews.forEach((r, i) => {
      const p = `m2.reviews[${i}]`;
      if (!r.claimId?.trim()) err(`${p}.claimId`, "claimId \u4E0D\u80FD\u4E3A\u7A7A");
      else if (seen.has(r.claimId)) err(`${p}.claimId`, `claimId \u91CD\u590D\uFF1A${r.claimId}`);
      else seen.add(r.claimId);
      if (!["APPROVE", "REJECT", "FLAG"].includes(r.result)) {
        err(`${p}.result`, `result \u5FC5\u987B\u662F APPROVE / REJECT / FLAG\uFF0C\u5B9E\u9645\u4E3A ${JSON.stringify(r.result)}`);
      }
      if (!Array.isArray(r.violations)) {
        err(`${p}.violations`, "violations \u5FC5\u987B\u662F\u6570\u7EC4\uFF08\u65E0\u8FDD\u89C4\u65F6\u7ED9\u7A7A\u6570\u7EC4\uFF09");
      } else {
        for (const v of r.violations) {
          if (!VIOLATION_CODES.includes(v)) {
            err(`${p}.violations`, `\u672A\u77E5\u8FDD\u89C4\u4EE3\u7801 ${JSON.stringify(v)}`);
          }
        }
      }
      if (r.result === "REJECT" && (!Array.isArray(r.reasons) || r.reasons.length === 0)) {
        warn(`${p}.reasons`, "\u5224\u5B9A\u4E3A REJECT \u4F46\u672A\u7ED9\u51FA\u7406\u7531\uFF0C\u4E3B\u89C2\u5206\u4F1A\u6263\u5206");
      }
      if (r.confidence !== void 0 && (typeof r.confidence !== "number" || r.confidence < 0 || r.confidence > 1)) {
        err(`${p}.confidence`, "confidence \u987B\u4E3A 0\u20131 \u4E4B\u95F4\u7684\u6570\u5B57");
      }
    });
    if (s.m2.reviews.length === 0) err("m2.reviews", "reviews \u4E3A\u7A7A\uFF0CM2 \u65E0\u6CD5\u8BA1\u5206");
    else if (s.m2.reviews.length < PENDING_CLAIM_COUNT) {
      warn("m2.reviews", `\u53EA\u63D0\u4EA4\u4E86 ${s.m2.reviews.length} \u6761\uFF0C\u5F85\u5BA1\u6C60\u5171 ${PENDING_CLAIM_COUNT} \u5355\uFF0C\u672A\u8986\u76D6\u7684\u6309\u672A\u5224\u5B9A\u8BA1\u5206`);
    }
  }
  if (!s.m3) {
    warn("m3", "\u672A\u63D0\u4EA4 m3\uFF0C\u8BE5\u90E8\u5206\u4E0D\u5F97\u5206");
  } else {
    if (s.m3.duplicateInvoices !== void 0 && !Array.isArray(s.m3.duplicateInvoices)) {
      err("m3.duplicateInvoices", "duplicateInvoices \u5FC5\u987B\u662F\u6570\u7EC4");
    }
    if (s.m3.invoiceIssues !== void 0 && !Array.isArray(s.m3.invoiceIssues)) {
      err("m3.invoiceIssues", "invoiceIssues \u5FC5\u987B\u662F\u6570\u7EC4");
    } else {
      (s.m3.invoiceIssues ?? []).forEach((x, i) => {
        const p = `m3.invoiceIssues[${i}]`;
        if (!x.invoiceId?.trim()) err(`${p}.invoiceId`, "invoiceId \u4E0D\u80FD\u4E3A\u7A7A");
        if (!INVOICE_ISSUE_CODES.includes(x.issue)) {
          err(`${p}.issue`, `issue \u53D6\u503C\u987B\u4E3A ${INVOICE_ISSUE_CODES.join(" / ")}\uFF0C\u5B9E\u9645\u4E3A ${JSON.stringify(x.issue)}`);
        }
      });
    }
  }
  if (s.m4) {
    if (!Array.isArray(s.m4.matches)) err("m4.matches", "matches \u5FC5\u987B\u662F\u6570\u7EC4");
    else {
      s.m4.matches.forEach((x, i) => {
        if (!x.txnId?.trim()) err(`m4.matches[${i}].txnId`, "txnId \u4E0D\u80FD\u4E3A\u7A7A");
        if (!Array.isArray(x.receivableIds) || x.receivableIds.length === 0) {
          err(`m4.matches[${i}].receivableIds`, "receivableIds \u4E0D\u80FD\u4E3A\u7A7A");
        }
      });
    }
  }
  if (!s.eval || s.eval.extractionAccuracy === void 0) {
    warn("eval", "\u672A\u63D0\u4EA4\u81EA\u5EFA\u8BC4\u6D4B\u7ED3\u679C\uFF0Ceval \u9879\u4F1A\u6263\u5206");
  }
  return issues;
}


const file = process.argv[2]
if (!file) {
  console.error('用法：node validate-submission.mjs <submission.json>')
  process.exit(1)
}

let raw
try {
  raw = JSON.parse(readFileSync(file, 'utf8'))
} catch (e) {
  console.error('✗ JSON 解析失败：' + e.message)
  process.exit(1)
}

const issues = validateSubmission(raw)
const errors = issues.filter(i => i.severity === 'error')
const warnings = issues.filter(i => i.severity === 'warning')

if (errors.length === 0 && warnings.length === 0) {
  console.log('✅ 格式检查通过，可以提交')
  process.exit(0)
}
for (const e of errors) console.log('  ✗ [错误] ' + e.path + '：' + e.message)
for (const w of warnings) console.log('  ⚠ [提示] ' + w.path + '：' + w.message)
console.log('')
if (errors.length > 0) {
  console.log('❌ 存在 ' + errors.length + ' 处错误，修正后才能提交（另有 ' + warnings.length + ' 处提示）')
  process.exit(1)
}
console.log('✅ 无阻塞性错误，可以提交（但有 ' + warnings.length + ' 处提示会影响得分）')
