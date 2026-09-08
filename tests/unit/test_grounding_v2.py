"""
M33 Grounding 升级单元测试

测试内容：
- _check_field_exists: source_id 和 field_path 验证
- _verify_grounding_v2: 三层 grounding 校验
- InvestigationReport: 新增字段（total_cost, wall_time_ms, grounding_failed_count）
"""

from core.investigator import _check_field_exists, _verify_grounding_v2
from core.contracts import InvestigationReport, Evidence


class TestCheckFieldExists:
    """测试字段存在性检查"""
    
    def test_valid_source_and_field(self):
        data = {"claim_id": "BX-001", "amount": 500.0, "lines": [{"lineNo": 1}]}
        assert _check_field_exists(data, "BX-001", "amount") is True
    
    def test_valid_nested_field(self):
        data = {"claim_id": "BX-001", "lines": [{"lineNo": 1, "description": "test"}]}
        assert _check_field_exists(data, "BX-001", "lines[0].description") is True
    
    def test_missing_source_id(self):
        data = {"claim_id": "BX-001", "amount": 500.0}
        assert _check_field_exists(data, "BX-999", "amount") is False
    
    def test_missing_field(self):
        data = {"claim_id": "BX-001", "amount": 500.0}
        assert _check_field_exists(data, "BX-001", "notexist") is False
    
    def test_empty_data(self):
        assert _check_field_exists(None, "BX-001", "amount") is False
        assert _check_field_exists({}, "BX-001", "amount") is False
    
    def test_empty_source_id(self):
        data = {"amount": 500.0}
        # source_id 为空时，只检查 field_path
        assert _check_field_exists(data, "", "amount") is True
    
    def test_empty_field_path(self):
        data = {"claim_id": "BX-001"}
        # field_path 为空时，只检查 source_id
        assert _check_field_exists(data, "BX-001", "") is True


class TestVerifyGroundingV2:
    """测试 M33 增强的 grounding 校验"""
    
    def test_all_evidence_grounded(self):
        """所有证据都落地"""
        ev1 = Evidence(
            tool="get_claim",
            call_id="call_1",
            finding="amount is 500",
            source_id="BX-001",
            field_path="amount"
        )
        ev2 = Evidence(
            tool="get_claim",
            call_id="call_1",
            finding="lines count is 2",
            source_id="BX-001",
            field_path="lines"
        )
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            evidence=[ev1, ev2]
        )
        
        transcript = [{
            "call_id": "call_1",
            "tool": "get_claim",
            "result": {
                "ok": True,
                "data": {
                    "claim_id": "BX-001",
                    "amount": 500.0,
                    "lines": [{"lineNo": 1}, {"lineNo": 2}]
                }
            }
        }]
        
        result = _verify_grounding_v2(report, transcript)
        
        assert result.grounding_ok is True
        assert result.grounding_failed_count == 0
        assert result.evidence[0].grounded is True
        assert result.evidence[1].grounded is True
    
    def test_missing_source_id(self):
        """证据缺少 source_id"""
        ev = Evidence(
            tool="get_claim",
            call_id="call_1",
            finding="amount is 500",
            source_id="",  # 缺少
            field_path="amount"
        )
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            evidence=[ev]
        )
        
        transcript = [{
            "call_id": "call_1",
            "tool": "get_claim",
            "result": {"ok": True, "data": {"amount": 500.0}}
        }]
        
        result = _verify_grounding_v2(report, transcript)
        
        assert result.grounding_ok is False
        assert result.grounding_failed_count == 1
        assert result.evidence[0].grounded is False
    
    def test_missing_call_id(self):
        """证据缺少 call_id"""
        ev = Evidence(
            tool="get_claim",
            call_id="",  # 缺少
            finding="amount is 500",
            source_id="BX-001",
            field_path="amount"
        )
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            evidence=[ev]
        )
        
        transcript = []
        
        result = _verify_grounding_v2(report, transcript)
        
        assert result.grounding_ok is False
        assert result.grounding_failed_count == 1
        assert result.evidence[0].grounded is False
    
    def test_call_id_not_in_transcript(self):
        """call_id 在 transcript 中找不到"""
        ev = Evidence(
            tool="get_claim",
            call_id="call_999",
            finding="amount is 500",
            source_id="BX-001",
            field_path="amount"
        )
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            evidence=[ev]
        )
        
        transcript = [{
            "call_id": "call_1",
            "tool": "get_claim",
            "result": {"ok": True, "data": {"amount": 500.0}}
        }]
        
        result = _verify_grounding_v2(report, transcript)
        
        assert result.grounding_ok is False
        assert result.grounding_failed_count == 1
        assert result.evidence[0].grounded is False
    
    def test_tool_call_failed(self):
        """工具调用失败"""
        ev = Evidence(
            tool="get_claim",
            call_id="call_1",
            finding="amount is 500",
            source_id="BX-001",
            field_path="amount"
        )
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            evidence=[ev]
        )
        
        transcript = [{
            "call_id": "call_1",
            "tool": "get_claim",
            "result": {"ok": False, "error": "not found"}
        }]
        
        result = _verify_grounding_v2(report, transcript)
        
        assert result.grounding_ok is False
        assert result.grounding_failed_count == 1
        assert result.evidence[0].grounded is False
    
    def test_field_not_in_data(self):
        """字段在返回数据中不存在"""
        ev = Evidence(
            tool="get_claim",
            call_id="call_1",
            finding="department is Sales",
            source_id="BX-001",
            field_path="department"  # 数据中没有这个字段
        )
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            evidence=[ev]
        )
        
        transcript = [{
            "call_id": "call_1",
            "tool": "get_claim",
            "result": {
                "ok": True,
                "data": {"claim_id": "BX-001", "amount": 500.0}
            }
        }]
        
        result = _verify_grounding_v2(report, transcript)
        
        assert result.grounding_ok is False
        assert result.grounding_failed_count == 1
        assert result.evidence[0].grounded is False
    
    def test_mixed_evidence(self):
        """部分证据落地，部分不落地"""
        ev1 = Evidence(
            tool="get_claim",
            call_id="call_1",
            finding="amount is 500",
            source_id="BX-001",
            field_path="amount"
        )
        ev2 = Evidence(
            tool="get_claim",
            call_id="call_2",
            finding="missing",
            source_id="",  # 缺少
            field_path="amount"
        )
        ev3 = Evidence(
            tool="get_clause",
            call_id="call_3",
            finding="clause found",
            source_id="C-001",
            field_path="content"
        )
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            evidence=[ev1, ev2, ev3]
        )
        
        transcript = [
            {
                "call_id": "call_1",
                "tool": "get_claim",
                "result": {"ok": True, "data": {"claim_id": "BX-001", "amount": 500.0}}
            },
            {
                "call_id": "call_3",
                "tool": "get_clause",
                "result": {"ok": True, "data": {"clause_id": "C-001", "content": "规则内容"}}
            }
        ]
        
        result = _verify_grounding_v2(report, transcript)
        
        assert result.grounding_ok is False  # 有失败的
        assert result.grounding_failed_count == 1
        assert result.evidence[0].grounded is True
        assert result.evidence[1].grounded is False
        assert result.evidence[2].grounded is True
    
    def test_no_evidence(self):
        """没有证据"""
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            evidence=[]
        )
        
        result = _verify_grounding_v2(report, [])
        
        assert result.grounding_ok is None
        assert result.grounding_failed_count == 0


class TestInvestigationReportFields:
    """测试 InvestigationReport 新增字段"""
    
    def test_new_fields_in_model(self):
        """验证新字段存在且有默认值"""
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9
        )
        
        assert hasattr(report, "total_cost")
        assert hasattr(report, "wall_time_ms")
        assert hasattr(report, "grounding_failed_count")
        
        assert report.total_cost == 0.0
        assert report.wall_time_ms == 0
        assert report.grounding_failed_count == 0
    
    def test_new_fields_set_values(self):
        """验证新字段可以设置值"""
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            total_cost=0.00123,
            wall_time_ms=5500,
            grounding_failed_count=2
        )
        
        assert report.total_cost == 0.00123
        assert report.wall_time_ms == 5500
        assert report.grounding_failed_count == 2
    
    def test_model_dump_includes_new_fields(self):
        """验证 model_dump 包含新字段"""
        report = InvestigationReport(
            conclusion="maintain_rules",
            summary="test",
            confidence=0.9,
            total_cost=0.00123,
            wall_time_ms=5500,
            grounding_failed_count=2
        )
        
        dumped = report.model_dump()
        
        assert "total_cost" in dumped
        assert "wall_time_ms" in dumped
        assert "grounding_failed_count" in dumped
        assert dumped["total_cost"] == 0.00123
        assert dumped["wall_time_ms"] == 5500
        assert dumped["grounding_failed_count"] == 2


class TestEvidenceFields:
    """测试 Evidence 新增字段"""
    
    def test_new_fields_in_model(self):
        """验证新字段存在且有默认值"""
        ev = Evidence(
            tool="get_claim",
            call_id="call_1",
            finding="test"
        )
        
        assert hasattr(ev, "source_id")
        assert hasattr(ev, "field_path")
        assert hasattr(ev, "grounded")
        
        assert ev.source_id == ""
        assert ev.field_path == ""
        assert ev.grounded is None
    
    def test_new_fields_set_values(self):
        """验证新字段可以设置值"""
        ev = Evidence(
            tool="get_claim",
            call_id="call_1",
            finding="test",
            source_id="BX-001",
            field_path="amount",
            grounded=True
        )
        
        assert ev.source_id == "BX-001"
        assert ev.field_path == "amount"
        assert ev.grounded is True
    
    def test_model_dump_includes_new_fields(self):
        """验证 model_dump 包含新字段"""
        ev = Evidence(
            tool="get_claim",
            call_id="call_1",
            finding="test",
            source_id="BX-001",
            field_path="amount",
            grounded=True
        )
        
        dumped = ev.model_dump()
        
        assert "source_id" in dumped
        assert "field_path" in dumped
        assert "grounded" in dumped
        assert dumped["source_id"] == "BX-001"
        assert dumped["field_path"] == "amount"
        assert dumped["grounded"] is True
