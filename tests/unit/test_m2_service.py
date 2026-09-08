"""
M2 Service 层单元测试
"""
import sys
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest
from pydantic import ValidationError
from unittest.mock import Mock
from app.services.m2_service import M2Service
from app.repositories import JobRepository
from app.repositories.workflow import WorkflowRepository
from app.repositories.audit import AuditRepository
from app.schemas.m2 import HumanGateResume


@pytest.fixture
def temp_output_dir(tmp_path):
    """创建临时输出目录"""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "reports").mkdir()
    return output_dir


@pytest.fixture
def mock_repos(temp_output_dir, tmp_path):
    """创建 mock repositories"""
    # 使用临时路径的 workflow DB
    workflow_db = tmp_path / "workflows.db"
    
    job_repo = Mock(spec=JobRepository)
    workflow_repo = WorkflowRepository(str(workflow_db))
    audit_repo = AuditRepository(str(temp_output_dir))
    
    return job_repo, workflow_repo, audit_repo


@pytest.fixture
def m2_service(mock_repos):
    """创建 M2Service 实例"""
    job_repo, workflow_repo, audit_repo = mock_repos
    return M2Service(job_repo, workflow_repo, audit_repo)


def test_get_audit_results_empty(m2_service):
    """测试获取空审核结果"""
    result = m2_service.get_audit_results()
    assert result.total == 0
    assert result.results == []


def test_get_pending_human_empty(m2_service):
    """测试获取空待审列表"""
    result = m2_service.get_pending_human()
    assert result.count == 0
    assert result.pending == []


def test_get_audit_status_not_found(m2_service, mock_repos):
    """测试查询不存在的任务"""
    job_repo, _, _ = mock_repos
    job_repo.get.return_value = None
    
    result = m2_service.get_audit_status("non-existent-job")
    assert result is None


def test_get_audit_status_success(m2_service, mock_repos):
    """测试查询任务成功"""
    job_repo, _, _ = mock_repos
    job_data = {
        "jobId": "test-job-123",
        "name": "m2-audit",
        "status": "running",
        "total": 10,
        "processed": 5,
        "phase": "rules",
        "results": None,
        "error": None,
        "cancelRequested": False,
        "createdAt": "2026-09-08T10:00:00+00:00",
        "updatedAt": "2026-09-08T10:05:00+00:00"
    }
    job_repo.get.return_value = job_data
    
    result = m2_service.get_audit_status("test-job-123")
    assert result is not None
    assert result.jobId == "test-job-123"
    assert result.status == "running"
    assert result.processed == 5
    assert result.total == 10


def test_cancel_audit_not_found(m2_service, mock_repos):
    """测试取消不存在的任务"""
    job_repo, _, _ = mock_repos
    job_repo.get.return_value = None
    
    result = m2_service.cancel_audit("non-existent-job")
    assert result is None


def test_cancel_audit_success(m2_service, mock_repos):
    """测试取消任务成功"""
    job_repo, _, _ = mock_repos
    job_data = {
        "jobId": "test-job-123",
        "status": "running",
        "cancelRequested": False
    }
    job_repo.get.return_value = job_data
    job_repo.request_cancel.return_value = True
    
    result = m2_service.cancel_audit("test-job-123")
    assert result.jobId == "test-job-123"
    assert result.status == "cancel_requested"
    assert result.cancelRequested is True


def test_resume_human_gate_invalid_decision(m2_service):
    """测试无效的人工决定"""
    # Invalid decisions are rejected at the API boundary by the Literal field;
    # the service therefore never receives an invalid command.
    with pytest.raises(ValidationError):
        HumanGateResume(decision="INVALID", expectedRevision=1, apiKey="test-key")


def test_resume_human_gate_run_not_found(m2_service, mock_repos):
    """测试恢复不存在的 workflow run"""
    _, workflow_repo, _ = mock_repos
    
    req = HumanGateResume(
        decision="APPROVE",
        expectedRevision=1,
        apiKey="test-key"
    )
    
    with pytest.raises(ValueError, match="workflow run 不存在"):
        m2_service.resume_human_gate("non-existent-run", req)


def test_resume_human_gate_wrong_status(m2_service, mock_repos, tmp_path):
    """测试恢复非等待状态的 workflow run"""
    _, workflow_repo, _ = mock_repos
    
    # 创建一个已完成的 workflow run
    run_id = workflow_repo.store.create("BX-001")
    workflow_repo.store.mark(run_id, "COMPLETED")
    
    req = HumanGateResume(
        decision="APPROVE",
        expectedRevision=1,
        apiKey="test-key"
    )
    
    with pytest.raises(ValueError, match="不在等待人工终审状态"):
        m2_service.resume_human_gate(run_id, req)


def test_resume_human_gate_by_claim_not_found(m2_service):
    """测试通过 claim_id 恢复不存在的 workflow"""
    req = HumanGateResume(
        decision="APPROVE",
        expectedRevision=1,
        apiKey="test-key"
    )
    
    with pytest.raises(ValueError, match="没有等待人工终审"):
        m2_service.resume_human_gate_by_claim("BX-999999", req)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


