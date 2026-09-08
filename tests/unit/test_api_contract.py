"""
API 契约测试：验证所有端点的 OpenAPI schema 和 response models
"""
import sys
from pathlib import Path

# 确保可以导入 backend 模块
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """测试客户端"""
    return TestClient(app)


def test_openapi_schema_generated(client):
    """验证 OpenAPI schema 可以成功生成"""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema
    assert "paths" in schema
    assert len(schema["paths"]) > 0


def test_all_endpoints_have_tags(client):
    """验证所有端点都有 tags（用于 API 分组）"""
    response = client.get("/openapi.json")
    schema = response.json()
    
    for path, methods in schema["paths"].items():
        # 跳过健康检查端点（不需要 tags）
        if path == "/api/health":
            continue
        for method, spec in methods.items():
            assert "tags" in spec, f"{method.upper()} {path} missing tags"
            assert len(spec["tags"]) > 0, f"{method.upper()} {path} has empty tags"


def test_m2_endpoints_exist(client):
    """验证 M2 所有端点存在于 OpenAPI schema"""
    response = client.get("/openapi.json")
    schema = response.json()
    paths = schema["paths"]
    
    expected_m2_paths = [
        "/api/m2/audit",
        "/api/m2/audit-status/{job_id}",
        "/api/m2/ocr",
        "/api/m2/results",
        "/api/m2/review",
        "/api/m2/pending-human",
        "/api/m2/human-gate/run/{run_id}/resume",
        "/api/m2/human-gate/{claim_id}/resume",
    ]
    
    for path in expected_m2_paths:
        assert path in paths, f"M2 endpoint missing: {path}"


def test_m3_endpoints_exist(client):
    """验证 M3 所有端点存在于 OpenAPI schema"""
    response = client.get("/openapi.json")
    schema = response.json()
    paths = schema["paths"]
    
    expected_m3_paths = [
        "/api/m3/scan",
        "/api/m3/results",
        "/api/m3/ai-review",
        "/api/m3/ai-review-status/{job_id}",
        "/api/m3/ai-review-results",
        "/api/m3/ai-scan",
        "/api/m3/ai-scan-status/{job_id}",
        "/api/m3/ai-scan-results",
    ]
    
    for path in expected_m3_paths:
        assert path in paths, f"M3 endpoint missing: {path}"


def test_m4_endpoints_exist(client):
    """验证 M4 所有端点存在于 OpenAPI schema"""
    response = client.get("/openapi.json")
    schema = response.json()
    paths = schema["paths"]
    
    expected_m4_paths = [
        "/api/m4/reconcile",
        "/api/m4/results",
    ]
    
    for path in expected_m4_paths:
        assert path in paths, f"M4 endpoint missing: {path}"


def test_post_endpoints_have_request_body(client):
    """验证所有 POST 端点都定义了 requestBody"""
    response = client.get("/openapi.json")
    schema = response.json()
    
    for path, methods in schema["paths"].items():
        if "post" in methods:
            spec = methods["post"]
            # 部分 POST 可能不需要 body（如取消任务），所以只检查审核/扫描类
            # 排除取消类端点
            if any(keyword in path for keyword in ["/audit", "/scan", "/review", "/reconcile"]) and "/cancel" not in path:
                assert "requestBody" in spec, f"POST {path} missing requestBody"


def test_all_endpoints_have_responses(client):
    """验证所有端点都定义了 responses"""
    response = client.get("/openapi.json")
    schema = response.json()
    
    for path, methods in schema["paths"].items():
        for method, spec in methods.items():
            assert "responses" in spec, f"{method.upper()} {path} missing responses"
            assert any(code in spec["responses"] for code in ("200", "202")), \
                f"{method.upper()} {path} missing successful response"


def test_response_models_have_schemas(client):
    """验证所有 200 响应都有 schema 定义"""
    response = client.get("/openapi.json")
    schema = response.json()
    
    for path, methods in schema["paths"].items():
        for method, spec in methods.items():
            if "200" in spec.get("responses", {}):
                resp_spec = spec["responses"]["200"]
                # 有些端点可能返回 plain text，不是所有都需要 content
                if "content" in resp_spec:
                    assert "application/json" in resp_spec["content"], \
                        f"{method.upper()} {path} 200 response not JSON"


def test_active_job_errors_use_stable_envelope(client):
    """A missing job must return a machine-readable error, not an ad-hoc detail string."""
    response = client.get("/api/m2/audit-status/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "JOB_NOT_FOUND"
    assert body["message"]
    assert body["requestId"].startswith("req_")
    assert response.headers["X-Request-ID"] == body["requestId"]


def test_request_models_reject_unknown_fields(client):
    response = client.post(
        "/api/m2/audit",
        json={"claimIds": ["BX-1"], "unrecognized": True},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["requestId"].startswith("req_")


def test_m3_and_m4_use_named_response_models(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    m3_scan_schema = paths["/api/m3/scan"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    m4_schema = paths["/api/m4/reconcile"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert m3_scan_schema["$ref"].endswith("/ScanResultsResponse")
    assert m4_schema["$ref"].endswith("/ReconcileResultsResponse")


def test_m2_result_schema_exposes_decision_strength(client):
    schema = client.get("/openapi.json").json()
    item = schema["components"]["schemas"]["AuditResultItem"]["properties"]
    assert "decisionStrength" in item


def test_health_endpoint(client):
    """验证健康检查端点"""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "ok"
    assert "version" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
