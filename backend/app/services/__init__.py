"""
服务层初始化和依赖注入
"""
from pathlib import Path
import os
from app.repositories import JobRepository
from app.repositories.workflow import WorkflowRepository
from app.repositories.audit import AuditRepository
from app.services.m2_service import M2Service

# 全局路径配置
ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT_DIR / "output"
WORKFLOW_DB = str(OUTPUT_DIR / "runtime" / "workflows.db")

# 初始化 Repositories
job_repo = JobRepository()
workflow_repo = WorkflowRepository(WORKFLOW_DB)
audit_repo = AuditRepository(str(OUTPUT_DIR))

# 初始化 Services
m2_service = M2Service(job_repo, workflow_repo, audit_repo)


def get_m2_service() -> M2Service:
    """获取 M2 服务实例（FastAPI 依赖注入）"""
    return m2_service


# ==================== M3/M4 Services ====================

from pathlib import Path

_output_dir = Path(__file__).resolve().parents[3] / "output"
_bank_dir = Path(
    os.environ.get("QIHENG_BANK_DIR")
    or (Path(__file__).resolve().parents[3] / "bank")
)

from app.services.m3_service import M3Service
from app.services.m4_service import M4Service

_m3_service = M3Service(output_dir=str(_output_dir))
_m4_service = M4Service(output_dir=str(_output_dir), bank_dir=str(_bank_dir))


def get_m3_service() -> M3Service:
    """获取 M3 服务实例（用于 FastAPI Depends）"""
    return _m3_service


def get_m4_service() -> M4Service:
    """获取 M4 服务实例（用于 FastAPI Depends）"""
    return _m4_service
