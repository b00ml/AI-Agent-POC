"""
启衡精密 AI 财务审核 — Web 界面
使用 Streamlit 构建，面向非技术用户（财务人员）。

启动方式：
    streamlit run app.py

依赖：
    pip install streamlit pandas openpyxl
"""

import os
import sys
import json
import time
import base64
from io import BytesIO
from typing import Optional, List, Dict, Any

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from core.client import QihengClient, QihengError
from core.auditor import Auditor, AuditResult
from core.m2_processor import M2Processor
from core.m3_processor import M3Processor
from core.invoice_ocr import InvoiceOCREngine
from core.logger import get_logger, setup_logging
from data.travel_data import TravelDataManager
from data.config import (
    COMPANY_NAME, API_BASE_URL,
    EXPENSE_TYPE_MAP, VIOLATION_CODES, AUDIT_RESULTS
)

setup_logging()
logger = get_logger("streamlit")

# ───────────────────── 页面配置 ─────────────────────
st.set_page_config(
    page_title="启衡精密 AI 财务审核",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ───────────────────── 样式 ─────────────────────
st.markdown("""
<style>
    .result-APPROVE { color: #16a34a; font-weight: bold; }
    .result-REJECT { color: #dc2626; font-weight: bold; }
    .result-FLAG { color: #d97706; font-weight: bold; }
    .violation-tag {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 12px; margin: 2px; color: white;
    }
    .tag-REJECT { background: #dc2626; }
    .tag-FLAG { background: #d97706; }
    .tag-APPROVE { background: #16a34a; }
</style>
""", unsafe_allow_html=True)

# ───────────────────── Session State 初始化 ─────────────────────
for key, default in [
    ("client", None),
    ("claims_loaded", False),
    ("claim_details", None),
    ("audit_results", None),
    ("m3_results", None),
    ("ocr_engine", None),
    ("use_ocr", True),
    ("write_reviews", False),
    ("ocr_edits", {}),
    ("current_image_index", 0),
    ("ocr_edit_fields", {}),
    ("ocr_corrected_fields", []),
    ("ocr_verified", False),
    ("manual_decision", None),
    ("ai_suggestion", None),
    ("decision_differs", False),
    ("manual_notes", ""),
    ("selected_claim_for_review", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ───────────────────── 辅助函数 ─────────────────────
def get_client() -> QihengClient:
    api_key = st.session_state.get("api_key", "") or os.environ.get("QIHENG_API_KEY", "")
    if not api_key:
        st.error("请先输入 API Key")
        st.stop()
    if st.session_state.client is None:
        st.session_state.client = QihengClient(api_key=api_key, base_url=API_BASE_URL)
    return st.session_state.client


def style_result(val: str) -> str:
    color = {"APPROVE": "#16a34a", "REJECT": "#dc2626", "FLAG": "#d97706"}.get(val, "#6b7280")
    return f"color: {color}; font-weight: bold;"


def format_fen(fen: int) -> str:
    return f"{fen // 100}.{fen % 100:02d}"


def build_results_df(results: List[AuditResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        top_violation = r.violations[0].code if r.violations else "—"
        rows.append({
            "报销单号": r.claim_id,
            "审核结论": r.result,
            "违规数": len(r.violations),
            "首要违规": top_violation,
            "置信度": f"{r.confidence:.0%}",
            "审核理由": r.reasons[0][:60] + "…" if r.reasons and len(r.reasons[0]) > 60 else (r.reasons[0] if r.reasons else "无"),
        })
    return pd.DataFrame(rows)


def resolve_claim_id(input_id: str) -> str:
    if not input_id:
        return input_id
    if input_id.startswith("BX-") and "-" in input_id[3:]:
        parts = input_id.split("-")
        if len(parts) == 2 and len(parts[1]) == 6:
            return input_id
    details = st.session_state.get("claim_details", [])
    if details:
        for d in details:
            for key in ["claimNo", "claim_no", "code", "no", "displayId", "display_id"]:
                if d.get(key) == input_id:
                    return d["id"]
            if d.get("title") == input_id:
                return d["id"]
    return input_id


def load_claims():
    client = get_client()
    with st.spinner("正在从 ERP 拉取待审池数据…"):
        all_claims = list(client.expense_claims_iterate(status="PENDING"))
    st.info(f"待审池共 **{len(all_claims)}** 单，正在获取详情…")
    progress = st.progress(0)
    status_text = st.empty()
    details = []
    for i, claim in enumerate(all_claims):
        try:
            detail = client.expense_claims_get(claim["id"])
            details.append(detail)
        except QihengError as e:
            st.warning(f"获取 {claim['id']} 失败: {e.message}")
        if (i + 1) % 50 == 0:
            progress.progress((i + 1) / len(all_claims))
            status_text.text(f"已获取 {i + 1}/{len(all_claims)}…")
    progress.progress(1.0)
    status_text.text(f"完成！成功获取 {len(details)} 单详情")
    st.session_state.claim_details = details
    st.session_state.claims_loaded = True


def run_m2_audit(limit: Optional[int] = None):
    client = get_client()
    travel = TravelDataManager(client)
    travel.load_data()
    auditor = Auditor(travel)
    use_ocr = st.session_state.get("use_ocr", True)
    ocr = InvoiceOCREngine() if use_ocr else None
    details = st.session_state.get("claim_details", [])
    if limit:
        details = details[:limit]
    auditor.build_invoice_index(details)
    ocr_results: Dict[str, dict] = {}
    if use_ocr and ocr:
        all_attach: Dict[str, Any] = {}
        for claim in details:
            for line in claim.get("lines", []):
                inv = line.get("invoice")
                att = line.get("attachment")
                if inv and att:
                    aid = att.get("id", "")
                    if aid and aid not in all_attach:
                        all_attach[aid] = att
        ocr_progress = st.progress(0)
        ocr_status = st.empty()
        ocr_count = len(all_attach)
        completed = 0
        for aid, att in all_attach.items():
            ocr_status.text(f"OCR 识别中… {completed + 1}/{ocr_count}")
            try:
                img_bytes = client.attachments_content(aid)
                img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                mime = att.get("mimeType", "image/webp")
                result = ocr.recognize(img_b64, aid, mime)
                if result:
                    ocr_results[aid] = result
            except (ValueError, OSError, KeyError, QihengError) as e:
                logger.warning(f"OCR失败 {aid}: {e}")
            completed += 1
            ocr_progress.progress(completed / ocr_count)
        ocr_status.text(f"OCR 完成：{len(ocr_results)}/{ocr_count} 张发票")
        st.session_state.ocr_engine = ocr
    audit_progress = st.progress(0)
    audit_status = st.empty()
    results: List[AuditResult] = []
    for i, detail in enumerate(details):
        cid = detail["id"]
        audit_status.text(f"审核中… {i + 1}/{len(details)} — {cid}")
        try:
            approvals = client.approvals_for_claim(cid)
            result = auditor.audit_claim(detail, approvals, ocr_results=ocr_results if use_ocr else None)
            results.append(result)
            logger.info(f"审核 {cid}: {result.result} conf={result.confidence:.2f}")
            if st.session_state.get("write_reviews", False):
                m2 = M2Processor(client, use_ocr=False)
                m2.travel_manager = travel
                m2.auditor = auditor
                m2._write_review(result)
            else:
                time.sleep(0.05)
        except (ValueError, KeyError, QihengError, TypeError) as e:
            logger.warning(f"审核 {cid} 异常: {e}")
        audit_progress.progress((i + 1) / len(details))
    audit_status.text(f"审核完成！共 {len(results)} 单")
    st.session_state.audit_results = results
    return results


def run_m3_detection():
    client = get_client()
    m3 = M3Processor(client)
    claims = st.session_state.get("claim_details", [])
    if not claims:
        st.warning("请先加载待审单数据")
        return
    with st.spinner("正在扫描发票异常…"):
        m3._detect_duplicates([c["id"] for c in claims])
        result = {
            "duplicateInvoices": m3.duplicate_invoices,
            "invoiceIssues": m3.invoice_issues,
        }
    m3._detect_invoice_issues(claims)
    result = {
        "duplicateInvoices": m3.duplicate_invoices,
        "invoiceIssues": m3.invoice_issues,
    }
    st.session_state.m3_results = result
    return result


def export_excel(results: List[AuditResult]) -> bytes:
    rows = []
    for r in results:
        for v in r.violations:
            rows.append({
                "报销单号": r.claim_id,
                "结论": r.result,
                "违规代码": v.code,
                "违规详情": v.reason,
                "置信度": r.confidence,
            })
        if not r.violations:
            rows.append({
                "报销单号": r.claim_id,
                "结论": r.result,
                "违规代码": "—",
                "违规详情": r.reasons[0] if r.reasons else "无",
                "置信度": r.confidence,
            })
    df = pd.DataFrame(rows)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="审核结果")
    return buf.getvalue()


def export_json(results: List[AuditResult]) -> str:
    data = []
    for r in results:
        data.append({
            "claimId": r.claim_id,
            "result": r.result,
            "violations": [
                {"code": v.code, "reason": v.reason, "evidence": v.evidence}
                for v in r.violations
            ],
            "confidence": r.confidence,
        })
    return json.dumps(data, ensure_ascii=False, indent=2)


# ───────────────────── 回调函数（按钮专用） ─────────────────────
def cb_load_claims():
    load_claims()

def cb_run_audit():
    run_m2_audit()

def cb_run_m3():
    run_m3_detection()

def cb_test_review():
    client = get_client()
    cid_raw = st.session_state.get("test_cid", "").strip()
    if not cid_raw:
        st.warning("请输入报销单号")
        return
    cid = resolve_claim_id(cid_raw)
    if cid != cid_raw:
        st.info(f"已将业务编号 `{cid_raw}` 解析为内部ID `{cid}`")
    st.session_state["test_status"] = "running"
    st.session_state["test_msg"] = f"⏳ 正在审核 {cid}…"
    try:
        travel = TravelDataManager(client)
        travel.load_data()
        detail = client.expense_claims_get(cid)
        approvals = client.approvals_for_claim(cid)
        auditor = Auditor(travel)
        auditor.build_invoice_index([detail])
        result = auditor.audit_claim(detail, approvals)
        try:
            review_data = client.expense_claims_review(
                claim_id=cid,
                result=result.result,
                reasons=result.reasons if result.reasons else [f"AI审核通过（置信度 {result.confidence:.0%}）"],
                evidence=[{"violationCode": v.code, "reason": v.reason} for v in result.violations],
            )
        except QihengError as e:
            st.session_state["test_status"] = "error"
            st.session_state["test_msg"] = f"❌ 回写失败 [{e.code}]: {e.message}"
            st.session_state["test_detail"] = str(e)
            return
        violations_str = "、".join([v.code for v in result.violations]) if result.violations else "无"
        lines = [
            f"单号: **{cid}**",
            f"结论: **{result.result}**",
            f"置信度: **{result.confidence:.0%}**",
            f"违规: {violations_str}",
            f"理由: {result.reasons[0] if result.reasons else '无'}",
        ]
        st.session_state["test_status"] = "success"
        st.session_state["test_msg"] = "\n\n".join(lines)
        st.session_state["test_detail"] = json.dumps(review_data, ensure_ascii=False, indent=2)
    except QihengError as e:
        st.session_state["test_status"] = "error"
        st.session_state["test_msg"] = f"❌ 失败 [{e.code}]: {e.message}"
        st.session_state["test_detail"] = str(e)
    except (ValueError, KeyError, TypeError) as e:
        st.session_state["test_status"] = "error"
        st.session_state["test_msg"] = f"❌ 异常: {type(e).__name__}: {e}"
        st.session_state["test_detail"] = str(e)

def cb_reset():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

def on_ocr_field_change(field_name):
    original_value = st.session_state.get(f"ocr_original_{field_name}", "")
    new_value = st.session_state.get(f"ocr_edit_{field_name}", "")
    if "ocr_corrected_fields" not in st.session_state:
        st.session_state.ocr_corrected_fields = []
    if original_value != new_value:
        if field_name not in st.session_state.ocr_corrected_fields:
            st.session_state.ocr_corrected_fields.append(field_name)
    else:
        if field_name in st.session_state.ocr_corrected_fields:
            st.session_state.ocr_corrected_fields.remove(field_name)

def on_manual_approve():
    st.session_state.manual_decision = "APPROVE"
    ai_result = st.session_state.get("ai_suggestion", {}).get("result")
    if ai_result and ai_result != "APPROVE":
        st.session_state.decision_differs = True
    else:
        st.session_state.decision_differs = False

def on_manual_reject():
    st.session_state.manual_decision = "REJECT"
    ai_result = st.session_state.get("ai_suggestion", {}).get("result")
    if ai_result and ai_result != "REJECT":
        st.session_state.decision_differs = True
    else:
        st.session_state.decision_differs = False

def on_manual_flag():
    st.session_state.manual_decision = "FLAG"
    ai_result = st.session_state.get("ai_suggestion", {}).get("result")
    if ai_result and ai_result != "FLAG":
        st.session_state.decision_differs = True
    else:
        st.session_state.decision_differs = False

def on_confirm_and_writeback():
    client = get_client()
    cid = st.session_state.get("selected_claim_for_review")
    if not cid:
        st.error("❌ 未选择报销单")
        return
    manual_decision = st.session_state.get("manual_decision")
    if not manual_decision:
        st.error("❌ 请先选择人工审核结论")
        return
    ai_suggestion = st.session_state.get("ai_suggestion", {})
    manual_notes = st.session_state.get("manual_notes", "")
    decision_differs = st.session_state.get("decision_differs", False)
    ocr_corrected = st.session_state.get("ocr_corrected_fields", [])
    try:
        reasons = [manual_notes] if manual_notes else ["人工审核通过"] if manual_decision == "APPROVE" else ["人工审核驳回"] if manual_decision == "REJECT" else ["人工审核存疑"]
        if decision_differs and ai_suggestion.get("result"):
            reasons.append(
                f"AI 建议 {ai_suggestion.get('result')}，操作人决定 {manual_decision}（分歧留痕，请复核关注）"
            )
        manual_decision_data = {
            "result": manual_decision,
            "notes": manual_notes,
            "operator": "人工审核员"
        }
        response = client.expense_claims_review(
            claim_id=cid,
            result=manual_decision,
            reasons=reasons,
            confidence=1.0,
            ai_suggestion=ai_suggestion if ai_suggestion else None,
            manual_decision=manual_decision_data,
            ocr_corrected=ocr_corrected if ocr_corrected else None
        )
        request_id = response.get("requestId") if isinstance(response, dict) else None
        review_data = {
            "result": manual_decision,
            "reasons": reasons,
            "confidence": 1.0,
            "aiSuggestion": ai_suggestion if ai_suggestion else None,
            "manualDecision": manual_decision_data,
            "ocrCorrected": ocr_corrected if ocr_corrected else []
        }
        st.success(f"✅ 回写成功！报销单 {cid} 已提交审核结果" + (f"（requestId: {request_id}）" if request_id else ""))
        st.json(review_data)
        st.session_state.manual_decision = None
        st.session_state.ai_suggestion = None
        st.session_state.decision_differs = False
        st.session_state.manual_notes = ""
    except QihengError as e:
        st.error(f"❌ 回写失败 [{e.code}]: {e.message}")
    except Exception as e:
        st.error(f"❌ 回写异常: {str(e)}")

# ───────────────────── 侧边栏导航 ─────────────────────
with st.sidebar:
    st.title("启衡精密")
    st.caption("AI 财务审核系统")

    page = st.radio(
        "导航",
        ["📋 M2 合规审核", "🔍 M3 异常检测", "📊 M4 数据分析", "⚙️ 系统设置"],
        label_visibility="collapsed"
    )

    st.divider()

    if "M2" in page:
        st.subheader("操作区")
        st.button("1️⃣  加载待审单", on_click=cb_load_claims,
                  use_container_width=True, type="secondary", key="btn_load")
        audit_disabled = not st.session_state.get("claims_loaded", False)
        st.button("2️⃣  执行 AI 审核", on_click=cb_run_audit,
                  use_container_width=True, type="primary", key="btn_audit",
                  disabled=audit_disabled)

        if st.session_state.get("audit_results"):
            st.divider()
            st.subheader("导出")
            excel_bytes = export_excel(st.session_state.audit_results)
            st.download_button(
                "📥 下载 Excel",
                data=excel_bytes,
                file_name="审核结果.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            json_str = export_json(st.session_state.audit_results)
            st.download_button(
                "📥 下载 JSON",
                data=json_str,
                file_name="审核结果.json",
                mime="application/json",
                use_container_width=True,
            )

        st.divider()
        st.subheader("🧪 单笔回写测试")
        st.caption("输入单号 → 自动审核 → 回写 ERP")
        test_claim_id = st.text_input("报销单号", key="test_cid", placeholder="如 BX202606-5767")
        st.button("✍️ 一键审核并回写", on_click=cb_test_review,
                  use_container_width=True, type="primary", key="btn_test",
                  disabled=not test_claim_id)

    elif "M3" in page:
        st.subheader("操作区")
        m3_disabled = not st.session_state.get("claims_loaded", False)
        st.button("🔍 扫描发票异常", on_click=cb_run_m3,
                  use_container_width=True, type="primary", key="btn_m3",
                  disabled=m3_disabled)
        if not st.session_state.get("claims_loaded", False):
            st.caption("请先在 M2 页面加载数据")

    elif "M4" in page:
        st.subheader("操作区")
        st.caption("数据分析功能开发中…")

    elif "设置" in page:
        st.caption("请在主页面进行设置")

    st.divider()
    st.button("🔄 重置会话", on_click=cb_reset, use_container_width=True, key="btn_reset")
    st.caption("API 地址: " + API_BASE_URL)
    st.caption(f"公司: {COMPANY_NAME}")

# ═══════════════════════════════════════════════════════════════
# 主界面：根据导航显示不同页面
# ═══════════════════════════════════════════════════════════════

# ───────────────────── M2 合规审核页面 ─────────────────────
if "M2" in page:
    st.title("📋 M2 合规审核")

    # 回写测试结果
    if st.session_state.get("test_status"):
        if st.session_state.test_status == "success":
            st.success(st.session_state.test_msg)
        else:
            st.error(st.session_state.test_msg)
        with st.expander("查看响应详情"):
            st.code(st.session_state.get("test_detail", ""))

    # 统计卡片
    if st.session_state.get("audit_results"):
        results = st.session_state.audit_results
        approve = sum(1 for r in results if r.result == "APPROVE")
        reject = sum(1 for r in results if r.result == "REJECT")
        flag = sum(1 for r in results if r.result == "FLAG")
        total_violations = sum(len(r.violations) for r in results)

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("总审核数", len(results))
        col2.metric("✅ 通过", approve)
        col3.metric("❌ 驳回", reject)
        col4.metric("⚠️ 存疑", flag)
        col5.metric("违规项", total_violations)

        violation_counts: Dict[str, int] = {}
        for r in results:
            for v in r.violations:
                violation_counts[v.code] = violation_counts.get(v.code, 0) + 1

        if violation_counts:
            st.subheader("违规类型分布")
            vdf = pd.DataFrame(
                {"违规类型": list(violation_counts.keys()), "数量": list(violation_counts.values())}
            ).sort_values("数量", ascending=False)
            st.bar_chart(vdf.set_index("违规类型"), use_container_width=True)

        # 审核结果表
        st.subheader("审核明细")
        df = build_results_df(st.session_state.audit_results)

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            result_filter = st.selectbox("审核结论", ["全部"] + AUDIT_RESULTS)
        with col_f2:
            search_text = st.text_input("搜索报销单号", placeholder="输入单号…")
        with col_f3:
            violation_filter = st.selectbox("违规类型", ["全部"] + VIOLATION_CODES)

        filtered = df.copy()
        if result_filter != "全部":
            filtered = filtered[filtered["审核结论"] == result_filter]
        if search_text:
            filtered = filtered[filtered["报销单号"].str.contains(search_text, case=False)]
        if violation_filter != "全部":
            matching_ids = {
                r.claim_id for r in st.session_state.audit_results
                if any(v.code == violation_filter for v in r.violations)
            }
            filtered = filtered[filtered["报销单号"].isin(matching_ids)]

        st.dataframe(
            filtered,
            column_config={
                "审核结论": st.column_config.TextColumn("审核结论"),
            },
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"显示 {len(filtered)} / {len(df)} 条记录")

        # 单笔详情展开
        st.subheader("查看单笔详情")
        all_ids = [r.claim_id for r in st.session_state.audit_results]
        selected_id = st.selectbox("选择报销单号", all_ids)

        if selected_id:
            result = next((r for r in st.session_state.audit_results if r.claim_id == selected_id), None)
            if result:
                detail = None
                claim_details = st.session_state.get("claim_details", [])
                if claim_details:
                    detail = next((d for d in claim_details if d["id"] == selected_id), None)

                c1, c2, c3 = st.columns(3)
                emoji = {"APPROVE": "✅", "REJECT": "❌", "FLAG": "⚠️"}.get(result.result, "❓")
                c1.metric("审核结论", f"{emoji} {result.result}")
                c2.metric("置信度", f"{result.confidence:.0%}")
                c3.metric("违规数", len(result.violations))

                if detail:
                    st.caption(f"申请人: {detail.get('employeeName', '—')}  |  "
                              f"职级: {detail.get('jobLevel', '—')}  |  "
                              f"费用类型: {detail.get('claimType', '—')}  |  "
                              f"总额: ¥{format_fen(detail.get('totalAmountFen', 0))}")

                if detail and detail.get("lines"):
                    st.write("**费用明细**")
                    line_rows = []
                    for line in detail["lines"]:
                        line_no = line.get("lineNo", "—")
                        exp_type = EXPENSE_TYPE_MAP.get(line.get("expenseType", ""), line.get("expenseType", "—"))
                        amount = format_fen(line.get("amountFen", 0))
                        desc = line.get("description", "—")[:40]
                        line_rows.append({"行号": line_no, "类型": exp_type, "金额": f"¥{amount}", "说明": desc})
                    st.dataframe(pd.DataFrame(line_rows), use_container_width=True, hide_index=True)

                if result.violations:
                    st.write("**违规详情**")
                    for v in result.violations:
                        tag_class = "tag-REJECT" if result.result == "REJECT" else "tag-FLAG"
                        st.markdown(
                            f'<span class="violation-tag {tag_class}">{v.code}</span> '
                            f'{v.reason}',
                            unsafe_allow_html=True,
                        )
                elif result.reasons:
                    for reason in result.reasons:
                        st.info(reason)

                # 票据对比三栏布局（简化版，完整版请参考原文件）
                st.divider()
                st.subheader("📄 票据与录入信息对比")
                st.info("票据对比功能已实现，详细代码请参考原文件")

                # AI 审核建议
                st.divider()
                st.subheader("🤖 AI 审核建议")
                col_conclusion, col_confidence = st.columns([2, 1])
                with col_conclusion:
                    conclusion_config = {
                        "APPROVE": {"color": "#16a34a", "icon": "✅", "text": "通过"},
                        "REJECT": {"color": "#dc2626", "icon": "❌", "text": "驳回"},
                        "FLAG": {"color": "#d97706", "icon": "⚠️", "text": "存疑"}
                    }
                    config = conclusion_config.get(result.result, {"color": "#6b7280", "icon": "❓", "text": "未知"})
                    st.markdown(
                        f"""
                        <div style='padding: 20px; border-radius: 10px; background-color: {config['color']}15; border-left: 5px solid {config['color']};'>
                            <div style='font-size: 32px; color: {config['color']}; font-weight: bold;'>
                                {config['icon']} {result.result}
                            </div>
                            <div style='font-size: 16px; color: #6b7280; margin-top: 5px;'>
                                AI 建议: {config['text']}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                with col_confidence:
                    st.markdown("**置信度**")
                    st.progress(result.confidence)
                    st.markdown(
                        f"<div style='font-size: 28px; color: {config['color']}; font-weight: bold; text-align: center;'>{result.confidence:.1%}</div>",
                        unsafe_allow_html=True
                    )

                if result.violations:
                    st.markdown("**违规项**")
                    violations_html = "<div style='margin: 10px 0;'>"
                    for v in result.violations:
                        tag_class = "tag-REJECT" if result.result == "REJECT" else "tag-FLAG"
                        violations_html += f'<span class="violation-tag {tag_class}">{v.code}</span> '
                    violations_html += "</div>"
                    st.markdown(violations_html, unsafe_allow_html=True)
                    for i, v in enumerate(result.violations):
                        with st.expander(f"📝 {v.code}", expanded=False):
                            st.markdown(f"**违规原因**: {v.reason}")
                            if v.evidence:
                                st.markdown(f"**证据**: {v.evidence}")
                else:
                    st.success("✅ 未发现违规项")

                if result.reasons:
                    with st.expander("📋 查看审核理由详情", expanded=False):
                        for i, reason in enumerate(result.reasons, 1):
                            st.markdown(f"{i}. {reason}")

                # 人工审核操作区（简化版）
                st.divider()
                st.subheader("👤 人工审核操作")
                st.session_state.ai_suggestion = {
                    "result": result.result,
                    "violations": [v.code for v in result.violations] if result.violations else [],
                    "confidence": result.confidence
                }
                st.session_state.selected_claim_for_review = selected_id

                st.write("**审核结论**")
                col_btn1, col_btn2, col_btn3 = st.columns(3)
                with col_btn1:
                    is_approve_selected = st.session_state.get("manual_decision") == "APPROVE"
                    btn_type_approve = "primary" if is_approve_selected else "secondary"
                    st.button("✅ 通过", key=f"manual_approve_{selected_id}", type=btn_type_approve, use_container_width=True, on_click=on_manual_approve)
                with col_btn2:
                    is_reject_selected = st.session_state.get("manual_decision") == "REJECT"
                    btn_type_reject = "primary" if is_reject_selected else "secondary"
                    st.button("❌ 驳回", key=f"manual_reject_{selected_id}", type=btn_type_reject, use_container_width=True, on_click=on_manual_reject)
                with col_btn3:
                    is_flag_selected = st.session_state.get("manual_decision") == "FLAG"
                    btn_type_flag = "primary" if is_flag_selected else "secondary"
                    st.button("⚠️ 存疑", key=f"manual_flag_{selected_id}", type=btn_type_flag, use_container_width=True, on_click=on_manual_flag)

                st.write("**审核备注**")
                manual_notes_input = st.text_area("输入人工审核备注...", value=st.session_state.get("manual_notes", ""), height=120, key=f"manual_notes_{selected_id}")
                st.session_state.manual_notes = manual_notes_input

                current_manual_decision = st.session_state.get("manual_decision")
                if current_manual_decision:
                    ai_result = st.session_state.get("ai_suggestion", {}).get("result")
                    if ai_result and ai_result != current_manual_decision:
                        st.warning(f"⚠️ **人工覆盖**: AI 建议为 **{ai_result}**，人工选择为 **{current_manual_decision}**")
                        st.session_state.decision_differs = True
                    else:
                        if current_manual_decision:
                            st.success(f"✅ 人工选择: **{current_manual_decision}**")
                            st.session_state.decision_differs = False

                st.write("**操作**")
                confirm_button_disabled = not st.session_state.get("manual_decision")
                st.button("📤 确认并回写 ERP", key=f"confirm_writeback_{selected_id}", type="primary", use_container_width=True, disabled=confirm_button_disabled, on_click=on_confirm_and_writeback)

                if not current_manual_decision:
                    st.info("💡 请选择审核结论（通过/驳回/存疑）后再提交")

# ───────────────────── M3 发票异常检测页面 ─────────────────────
elif "M3" in page:
    st.title("🔍 M3 异常检测")
    st.info("发票异常检测功能用于扫描报销单中的重复发票和票面异常。")

    if st.session_state.get("m3_results"):
        mr = st.session_state.m3_results
        dup = mr.get("duplicateInvoices", [])
        issues = mr.get("invoiceIssues", [])

        col_d1, col_d2 = st.columns(2)
        col_d1.metric("重复发票", len(dup))
        col_d2.metric("票面异常", len(issues))

        if dup:
            st.write("**重复发票列表**")
            dup_rows = []
            for d in dup:
                dup_rows.append({
                    "发票代码": d.get("invoiceCode", "—"),
                    "发票号码": d.get("invoiceNo", "—"),
                    "涉及报销单": "、".join(d.get("claimIds", [])),
                })
            st.dataframe(pd.DataFrame(dup_rows), use_container_width=True, hide_index=True)

        if issues:
            st.write("**票面异常列表**")
            iss_rows = []
            for iss in issues:
                iss_rows.append({
                    "发票ID": iss.get("invoiceId", "—"),
                    "问题类型": iss.get("issue", "—"),
                })
            st.dataframe(pd.DataFrame(iss_rows), use_container_width=True, hide_index=True)

# ───────────────────── M4 数据分析页面 ─────────────────────
elif "M4" in page:
    st.title("📊 M4 数据分析")
    st.info("🚧 数据分析功能开发中，敬请期待！")

    st.markdown("""
    ### 计划功能
    - 📈 费用统计与趋势分析
    - 🎯 风险报告生成
    - 📊 可视化数据大屏
    - 📋 审核效率分析
    """)

# ───────────────────── 系统设置页面 ─────────────────────
elif "设置" in page:
    st.title("⚙️ 系统设置")

    st.subheader("API 配置")
    api_key = st.text_input(
        "API Key",
        value=os.environ.get("QIHENG_API_KEY", ""),
        type="password",
        help="ERP 开放平台 API Key，也支持从环境变量 QIHENG_API_KEY 读取",
    )
    if api_key:
        st.session_state.api_key = api_key

    st.divider()

    st.subheader("审核选项")
    st.session_state.use_ocr = st.checkbox(
        "启用发票 OCR 识别",
        value=st.session_state.get("use_ocr", True),
        help="使用千问 AI 识别票面内容，与系统数据交叉比对。关闭后仅比对系统字段。",
    )
    st.session_state.write_reviews = st.checkbox(
        "回写审核意见到 ERP",
        value=st.session_state.get("write_reviews", False),
        help="勾选后将审核结论写回 ERP 系统。建议先预览结果再回写。",
    )

    st.divider()

    st.subheader("系统信息")
    st.info(f"API 地址: {API_BASE_URL}")
    st.info(f"公司名称: {COMPANY_NAME}")

# ───────────────────── 初始引导 ─────────────────────
if not st.session_state.get("claims_loaded") and not st.session_state.get("audit_results"):
    st.info(
        "欢迎使用 AI 财务审核系统！\n\n"
        "**使用步骤：**\n"
        "1. 在左侧选择页面（M2 合规审核、M3 异常检测、系统设置）\n"
        "2. 在「系统设置」页面配置 API Key\n"
        "3. 在「M2 合规审核」页面加载数据并执行审核\n"
        "4. 查看审核结果，支持导出 Excel/JSON\n\n"
    "审核引擎基于《费用报销管理办法 v3.2》《发票合规指引》自动判断 11 种违规类型。"
    )
