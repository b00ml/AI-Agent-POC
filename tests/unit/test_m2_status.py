"""M2 审核状态持久化测试：文件锁 + 原子写（设计文档2.0 §3.8）。"""

import json
import os

from core.m2_processor import M2Processor, load_audit_status, save_audit_status


def test_status_roundtrip_and_atomic_write(tmp_path, monkeypatch):
    status_file = tmp_path / "m2_audit_status.json"
    monkeypatch.setattr(M2Processor, "AUDIT_STATUS_FILE", str(status_file))

    payload = {
        "BX-1": {"result": "REJECT", "aiReview": None, "writtenBack": True,
                 "updatedAt": "2026-09-05T00:00:00+08:00"},
    }
    save_audit_status(payload)

    assert status_file.exists()
    assert json.loads(status_file.read_text(encoding="utf-8")) == payload
    assert not os.path.exists(str(status_file) + ".tmp")  # 原子写不残留临时文件

    loaded = load_audit_status()
    assert loaded == payload


def test_status_load_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(M2Processor, "AUDIT_STATUS_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr("core.m2_processor.REPORTS_DIR", str(tmp_path))  # 无历史报告
    assert load_audit_status() == {}
