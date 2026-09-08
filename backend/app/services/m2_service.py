"""
M2 审核应用服务层
"""
from typing import Dict, Any, Optional

from app.repositories import JobRepository
from app.repositories.workflow import WorkflowRepository
from app.repositories.audit import AuditRepository
from app.schemas.m2 import (
    AuditRequest, OCRRequest, ReviewRequest, HumanGateResume,
    JobCreatedResponse, OCRResponse, ReviewResponse, AuditResultsResponse,
    PendingHumanResponse, HumanGateResumeResponse, JobStatusResponse
)


class M2Service:
    """M2 审核应用服务"""

    def __init__(self, job_repo: JobRepository, workflow_repo: WorkflowRepository, audit_repo: AuditRepository):
        self.job_repo = job_repo
        self.workflow_repo = workflow_repo
        self.audit_repo = audit_repo

    def start_audit(self, req: AuditRequest) -> JobCreatedResponse:
        """启动批量审核任务"""
        from app.jobs import update_progress
        from core.client import QihengClient
        from core.m2_processor import M2Processor

        req_data = req.model_dump()

        def worker(job_id: str) -> None:
            client = QihengClient(
                api_key=req_data["apiKey"],
                base_url=req_data["apiUrl"] or None
            )
            # Demo mode uses synthetic invoice fields and deliberately skips
            # the heavyweight OCR runtime; real ERP runs keep local OCR on.
            processor = M2Processor(client=client, use_ocr=not client.is_demo)

            def cb(total: int, processed: int, phase: str = "rules") -> None:
                self.job_repo.raise_if_cancel_requested(job_id)
                update_progress(job_id, total, processed, phase=phase)

            results = processor.run(
                claim_ids=req_data["claimIds"],
                write_back=req_data["writeBack"],
                progress_cb=cb,
            )
            update_progress(
                job_id, len(results), len(results),
                results={"results": [r.to_dict() for r in results], "total": len(results)},
                phase="done",
            )

        from app.jobs import start_job as _start_job
        job_id = _start_job("m2-audit", worker)
        return JobCreatedResponse(jobId=job_id, status="queued")

    def get_audit_status(self, job_id: str) -> Optional[JobStatusResponse]:
        """获取审核任务状态"""
        job = self.job_repo.get(job_id)
        if not job:
            return None
        return JobStatusResponse(**job)

    def cancel_audit(self, job_id: str) -> Optional[Dict[str, Any]]:
        """取消审核任务"""
        from app.schemas.m2 import JobCancelResponse
        job = self.job_repo.get(job_id)
        if not job:
            return None
        if not self.job_repo.request_cancel(job_id):
            return JobCancelResponse(
                jobId=job_id,
                status=job["status"],
                cancelRequested=job["cancelRequested"]
            )
        return JobCancelResponse(
            jobId=job_id,
            status="cancel_requested",
            cancelRequested=True
        )

    def run_ocr(self, req: OCRRequest) -> OCRResponse:
        """执行单票 OCR 识别"""
        from core.invoice_ocr import InvoiceOCREngine
        engine = InvoiceOCREngine()
        result = engine.recognize_claim_invoices(
            req.claimId,
            api_url=req.apiUrl,
            api_key=req.apiKey
        )
        return OCRResponse(**result)

    def submit_review(self, req: ReviewRequest) -> ReviewResponse:
        """
        提交人工复核意见并回写 ERP
        理由 = AI 建议理由 + 操作人意见（覆盖时明确标注）
        """
        from core.client import QihengClient

        client = QihengClient(api_key=req.apiKey, base_url=req.apiUrl or None)

        # 理由 = AI 建议理由 + 操作人意见（覆盖时明确标注）
        reasons = list(req.aiReasons or [])
        note_parts = []
        if req.aiResult and req.aiResult != req.decision:
            note_parts.append(f"AI 建议 {req.aiResult}，操作人决定 {req.decision}")
        if req.comment:
            note_parts.append(f"操作人意见：{req.comment}")
        if note_parts:
            reasons.append("；".join(note_parts))

        # 操作人与 AI 结论一致时保留违规代码，覆盖时置空（人工判断为准）
        violations = list(req.aiViolations or []) if req.decision == req.aiResult else []

        result = client.expense_claims_review(
            claim_id=req.claimId,
            result=req.decision,
            reasons=reasons,
            violations=violations,
            evidence=req.evidence or None,
            confidence=req.aiConfidence,
        )
        return ReviewResponse(status="success", claimId=req.claimId, result=result)

    def get_audit_results(self) -> AuditResultsResponse:
        """获取审核结果列表"""
        data = self.audit_repo.get_results()
        return AuditResultsResponse(**data)

    def get_pending_human(self) -> PendingHumanResponse:
        """获取待人工终审列表"""
        data = self.audit_repo.get_pending_human()
        return PendingHumanResponse(**data)

    def resume_human_gate(self, run_id: str, req: HumanGateResume) -> HumanGateResumeResponse:
        """恢复人工终审并完成审核"""
        if req.decision not in ("APPROVE", "REJECT", "FLAG"):
            raise ValueError("decision 必须是 APPROVE/REJECT/FLAG")

        # 检查 workflow run 状态和版本
        record = self.workflow_repo.get(run_id)
        if record is None:
            raise ValueError("workflow run 不存在")
        if record["status"] != "AWAITING_HUMAN":
            raise ValueError("该 workflow run 不在等待人工终审状态")
        if record["revision"] != req.expectedRevision:
            raise ValueError("人工决定版本冲突，请刷新后重试")

        # 重建或获取 runner
        runner = self._get_or_reconstruct_runner(run_id, req)

        # 执行人工决定
        state = runner.resume(
            run_id,
            decision=req.decision,
            comment=req.comment or "",
            expected_revision=req.expectedRevision,
        )
        if state is None:
            raise ValueError("人工决定并发冲突或 checkpoint 不存在")

        # 同步状态并从待审清单移除
        claim_id = record["claim_id"]
        self.audit_repo.update_claim_status(
            claim_id=claim_id,
            result=state.get("final_result"),
            ai_review=state.get("ai_review"),
            written_back=True
        )
        self.audit_repo.remove_from_pending_human(run_id)

        return HumanGateResumeResponse(
            status="success",
            claimId=claim_id,
            workflowRunId=run_id,
            finalResult=state.get("final_result")
        )

    def resume_human_gate_by_claim(self, claim_id: str, req: HumanGateResume) -> HumanGateResumeResponse:
        """通过 claim_id 恢复人工终审（兼容接口）"""
        record = self.workflow_repo.latest_for_claim(claim_id)
        if record is None:
            raise ValueError("该单没有等待人工终审的 workflow run")
        return self.resume_human_gate(record["run_id"], req)

    def _get_or_reconstruct_runner(self, run_id: str, req: HumanGateResume):
        """获取或重建 workflow runner"""
        from core.workflow import M2GraphRunner
        from core.client import QihengClient
        from data.travel_data import TravelDataManager

        # 尝试获取热 runner
        runner = M2GraphRunner.get_runner(run_id)
        if runner is not None:
            return runner

        # 重建 runner（需要 API Key）
        if not req.apiKey:
            raise ValueError("后端已重启，恢复人工终审需重新提供 ERP API Key")

        client = QihengClient(api_key=req.apiKey, base_url=req.apiUrl or None)

        def write_back(payload: dict) -> None:
            client.expense_claims_review(
                claim_id=payload.get("claimId", ""),
                result=payload.get("result"),
                reasons=payload.get("reasons") or [],
                confidence=payload.get("confidence"),
                violations=payload.get("violations") or [],
            )

        return M2GraphRunner(
            client=client,
            travel_manager=TravelDataManager(client),
            retriever=None,
            llm_reviewer=None,
            write_back_fn=write_back,
        )
