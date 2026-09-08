"""
启衡精密开放平台 · Python API客户端封装

功能：
1. 处理429限流的退避重试（平台限每个Key每秒10次）
2. 游标分页的翻页循环（自动遍历全量）
3. 统一错误结构的解析
"""

import os
import time
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Generator
import requests


class QihengError(Exception):
    """平台返回的结构化错误"""
    def __init__(self, code: str, message: str, status: int, request_id: Optional[str] = None, details: Optional[Dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.request_id = request_id
        self.details = details

    @property
    def missing_scope(self) -> Optional[str]:
        """缺权限时，details.required会告诉你差哪个scope"""
        return self.details.get('required') if isinstance(self.details, dict) else None


class QihengClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = 'http://localhost:8081', max_retries: int = 5, timeout: int = 30):
        configured_url = base_url or os.environ.get('QIHENG_BASE_URL') or 'http://localhost:8081'
        self.is_demo = (
            str(configured_url).strip().lower().startswith(('demo://', 'mock://'))
            or os.environ.get('DEMO_MODE', '').strip().lower() in {'1', 'true', 'yes'}
        )
        self.api_key = api_key or os.environ.get('QIHENG_API_KEY')
        if self.is_demo:
            self.api_key = self.api_key or 'demo'
        elif not self.api_key:
            raise ValueError('缺少apiKey。请在ERP「开发者中心」创建，或设置环境变量QIHENG_API_KEY。')
        # 支持 QIHENG_BASE_URL 环境变量（Docker 容器内指向 host.docker.internal）
        self.base_url = ('demo://local' if self.is_demo else configured_url).rstrip('/')
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({'X-Api-Key': self.api_key})
        self._demo_reviews: Dict[str, Dict[str, Any]] = {}
        self._demo_data: Optional[Dict[str, Any]] = None

    def _load_demo_data(self) -> Dict[str, Any]:
        """Load synthetic fixtures only when the explicit demo adapter is active."""
        if self._demo_data is not None:
            return self._demo_data
        root = Path(__file__).resolve().parents[1] / 'data' / 'demo'

        def load(name: str, default: Any) -> Any:
            path = root / name
            if not path.exists():
                return default
            with path.open('r', encoding='utf-8') as handle:
                return json.load(handle)

        self._demo_data = {
            'claims': load('claims.json', []),
            'invoices': load('invoices.json', []),
            'receivables': load('receivables.json', []),
            'travelStandards': load('travel_standards.json', []),
            'cities': load('cities.json', []),
            'employees': load('employees.json', []),
        }
        return self._demo_data

    def _demo_request(self, method: str, path: str, **kwargs) -> Any:
        """Small in-process ERP contract for public, credential-free demos."""
        data = self._load_demo_data()
        params = kwargs.get('params') or {}
        method = method.upper()
        if method == 'GET' and path == '/v1/me':
            return {
                'id': 'demo-user',
                'name': 'Demo reviewer',
                'scopes': ['master-data:read', 'expense:read', 'expense:review', 'invoice:read', 'receivable:read'],
            }
        if method == 'GET' and path == '/v1/expense-claims':
            claims = list(data['claims'])
            status = params.get('status')
            if status:
                claims = [item for item in claims if item.get('status') == status]
            limit = max(1, int(params.get('limit', 100)))
            cursor = int(params.get('cursor') or 0)
            page = claims[cursor:cursor + limit]
            next_cursor = cursor + limit if cursor + limit < len(claims) else None
            return {'data': page, 'hasMore': next_cursor is not None, 'nextCursor': str(next_cursor) if next_cursor is not None else None}
        if method == 'GET' and path.startswith('/v1/expense-claims/'):
            claim_id = path.rsplit('/', 1)[-1]
            claim = next((item for item in data['claims'] if item.get('id') == claim_id), None)
            if claim is None:
                raise QihengError('not_found', f'Demo claim not found: {claim_id}', 404)
            return claim
        if method == 'POST' and path.startswith('/v1/expense-claims/') and path.endswith('/review'):
            claim_id = path.split('/')[3]
            payload = kwargs.get('json') or {}
            self._demo_reviews[claim_id] = dict(payload)
            return {'status': 'recorded', 'claimId': claim_id, 'review': payload}
        if method == 'GET' and path == '/v1/approvals':
            claim_id = params.get('refId')
            claim = next((item for item in data['claims'] if item.get('id') == claim_id), None)
            approvals = claim.get('approvals', []) if claim else []
            return {'data': approvals, 'hasMore': False, 'nextCursor': None}
        if method == 'GET' and path == '/v1/travel-standards':
            return {'data': data['travelStandards']}
        if method == 'GET' and path == '/v1/cities':
            return {'data': data['cities']}
        if method == 'GET' and path == '/v1/invoices':
            invoices = list(data['invoices'])
            limit = max(1, int(params.get('limit', 100)))
            cursor = int(params.get('cursor') or 0)
            page = invoices[cursor:cursor + limit]
            next_cursor = cursor + limit if cursor + limit < len(invoices) else None
            return {'data': page, 'hasMore': next_cursor is not None, 'nextCursor': str(next_cursor) if next_cursor is not None else None}
        if method == 'GET' and path == '/v1/receivables':
            receivables = list(data['receivables'])
            limit = max(1, int(params.get('limit', 100)))
            cursor = int(params.get('cursor') or 0)
            page = receivables[cursor:cursor + limit]
            next_cursor = cursor + limit if cursor + limit < len(receivables) else None
            return {'data': page, 'hasMore': next_cursor is not None, 'nextCursor': str(next_cursor) if next_cursor is not None else None}
        if method == 'GET' and path == '/v1/employees':
            return {'data': list(data['employees']), 'hasMore': False, 'nextCursor': None}
        if method == 'GET' and path.startswith('/v1/attachments/'):
            attachment_id = path.split('/')[3]
            if path.endswith('/content'):
                return b'demo-attachment'
            return {'id': attachment_id, 'mimeType': 'image/jpeg', 'migrated': True}
        raise QihengError('demo_not_implemented', f'Demo endpoint not implemented: {method} {path}', 501)

    def _request(self, method: str, path: str, **kwargs) -> Any:
        """底层请求，429自动退避重试"""
        if self.is_demo:
            return self._demo_request(method, path, **kwargs)
        url = f'{self.base_url}{path}'
        last_err: Optional[QihengError] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)

                if 200 <= response.status_code < 300:
                    content_type = response.headers.get('content-type', '')
                    if 'application/json' in content_type:
                        return response.json()
                    return response.content

                # 解析错误响应
                try:
                    body = response.json()
                except json.JSONDecodeError:
                    body = {}

                error_info = body.get('error', {})
                last_err = QihengError(
                    code=error_info.get('code', f'http_{response.status_code}'),
                    message=error_info.get('message', f'HTTP {response.status_code}'),
                    status=response.status_code,
                    request_id=body.get('requestId'),
                    details=error_info.get('details')
                )

                if response.status_code == 429 and attempt < self.max_retries:
                    retry_after = int(response.headers.get('retry-after', '1'))
                    wait_time = max(retry_after, 0.2 * (2 ** attempt))
                    time.sleep(wait_time)
                    continue

                raise last_err

            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise QihengError('network_error', str(e), 0) from e

        raise last_err or QihengError('internal_error', '请求失败', 500)

    def _paginate(self, path: str, params: Optional[Dict] = None) -> Generator[Dict, None, None]:
        """游标分页迭代器"""
        params = params or {}
        cursor = None

        while True:
            page_params = {**params}
            if cursor:
                page_params['cursor'] = cursor

            response = self._request('GET', path, params=page_params)
            data = response.get('data', [])
            for item in data:
                yield item

            has_more = response.get('hasMore', False)
            cursor = response.get('nextCursor')

            if not has_more or not cursor:
                break

    def me(self) -> Dict:
        """当前Key的权限信息"""
        return self._request('GET', '/v1/me')

    def expense_claims_list(self, status: Optional[str] = None, period: Optional[str] = None,
                           employee_id: Optional[str] = None, limit: int = 100, cursor: Optional[str] = None) -> Dict:
        """获取报销单列表（单次分页）"""
        params = {
            'status': status,
            'period': period,
            'employeeId': employee_id,
            'limit': limit,
            'cursor': cursor
        }
        params = {k: v for k, v in params.items() if v is not None}
        return self._request('GET', '/v1/expense-claims', params=params)

    def expense_claims_iterate(self, status: Optional[str] = None, period: Optional[str] = None,
                              employee_id: Optional[str] = None, limit: int = 100) -> Generator[Dict, None, None]:
        """遍历全部报销单（自动翻页）"""
        params = {
            'status': status,
            'period': period,
            'employeeId': employee_id,
            'limit': limit
        }
        params = {k: v for k, v in params.items() if v is not None}
        return self._paginate('/v1/expense-claims', params)

    def expense_claims_get(self, claim_id: str) -> Dict:
        """获取报销单详情"""
        return self._request('GET', f'/v1/expense-claims/{claim_id}')

    def expense_claims_review(self, claim_id: str, result: str, reasons: List[str],
                             evidence: Optional[List[Dict]] = None, confidence: Optional[float] = None,
                             violations: Optional[List[str]] = None,
                             ai_suggestion: Optional[Dict] = None, manual_decision: Optional[Dict] = None,
                             ocr_corrected: Optional[List[str]] = None) -> Dict:
        """回写审核意见

        Args:
            claim_id: 报销单ID
            result: 审核结果 (APPROVE/REJECT/FLAG)
            reasons: 审核理由列表
            evidence: 证据列表（可选）
            confidence: 置信度（可选）
            ai_suggestion: AI原始建议（可选）
                {
                    "result": "REJECT",
                    "violations": ["OVER_STANDARD_HOTEL"],
                    "confidence": 0.85
                }
            manual_decision: 人工终审结果（可选）
                {
                    "result": "APPROVE",
                    "notes": "已特批",
                    "operator": "人工审核员"
                }
            ocr_corrected: OCR修正字段列表（可选）
                ["buyerName", "sellerName"]
        """
        body = {
            'result': result,
            'reasons': reasons,
            'violations': violations or []
        }
        if evidence:
            body['evidence'] = evidence
        if confidence is not None:
            body['confidence'] = confidence

        # 新增字段：AI建议、人工决策、OCR修正
        if ai_suggestion:
            body['aiSuggestion'] = ai_suggestion
        if manual_decision:
            body['manualDecision'] = manual_decision
        if ocr_corrected:
            body['ocrCorrected'] = ocr_corrected

        return self._request('POST', f'/v1/expense-claims/{claim_id}/review', json=body)

    def approvals_for_claim(self, claim_id: str) -> List[Dict]:
        """查询报销单的审批记录"""
        params = {'refId': claim_id, 'limit': 100}
        return list(self._paginate('/v1/approvals', params))

    def attachments_get(self, attachment_id: str) -> Dict:
        """获取附件信息"""
        return self._request('GET', f'/v1/attachments/{attachment_id}')

    def attachments_content(self, attachment_id: str) -> bytes:
        """下载附件内容"""
        return self._request('GET', f'/v1/attachments/{attachment_id}/content')

    def invoices_iterate(self, **params) -> Generator[Dict, None, None]:
        """遍历发票台账"""
        return self._paginate('/v1/invoices', params)

    def travel_standards(self) -> List[Dict]:
        """获取差旅标准"""
        response = self._request('GET', '/v1/travel-standards')
        return response.get('data', [])

    def cities(self) -> List[Dict]:
        """获取城市档次映射"""
        response = self._request('GET', '/v1/cities')
        return response.get('data', [])

    def employees_iterate(self, **params) -> Generator[Dict, None, None]:
        """遍历员工"""
        return self._paginate('/v1/employees', params)


def to_yuan(fen: int) -> str:
    """分 → 元字符串"""
    sign = '-' if fen < 0 else ''
    abs_fen = abs(fen)
    return f'{sign}{abs_fen // 100}.{str(abs_fen % 100).zfill(2)}'


__all__ = ['QihengClient', 'QihengError', 'to_yuan']
