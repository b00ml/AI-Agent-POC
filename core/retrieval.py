"""
制度知识库混合检索（设计文档 2.0 §3.4）

两种召回 + RRF 融合：
- dense：本地向量余弦（默认 bge-small-zh-v1.5，CPU 推理，不出域）
- sparse：关键词计分（与 1.x 行为一致）
- 融合：Reciprocal Rank Fusion（k=60）

配置（.env）：
- RETRIEVAL_MODE：keyword（默认，行为与 1.x 完全一致）| hybrid
- EMBEDDING_MODEL：默认 BAAI/bge-small-zh-v1.5（bge-m3 需显式启用）；模型不可用或索引无向量列时自动回退 keyword
- RERANK_ENABLED：预留（0 默认）
"""

import os
import json
import logging
from typing import List, Dict, Optional, Set

# 离线部署不出域：禁止模型加载时对 huggingface.co 的探测（否则每次加载多等数十秒重试）。
# 需在线下载新模型时显式设 HF_HUB_OFFLINE=0；须在 sentence_transformers 首次导入前生效。
os.environ.setdefault("HF_HUB_OFFLINE", "1")

logger = logging.getLogger("retrieval")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INDEX_PATH = os.path.join(REPO_ROOT, "data", "rag_index", "index.json")
RRF_K = 60

# 统一关键词映射：sparse 召回（本模块）/ 工具层（agent_tools）/ 评测（tools/eval_retrieval）
# 三处共用，避免多份映射漂移
QUERY_KEYWORDS = {
    "住宿": "住宿", "酒店": "住宿", "每晚": "住宿", "晚上": "住宿", "单价": "住宿",
    "伙食": "伙食", "餐": "伙食", "吃饭": "伙食", "餐费": "伙食",
    "市内交通": "交通", "打车": "加班", "出租车": "加班", "加班": "加班", "叫车": "加班", "车费": "交通", "网约车": "加班", "出租": "加班",
    "长途": "舱位", "舱位": "舱位", "高铁": "舱位", "机票": "舱位", "经济舱": "舱位", "商务舱": "舱位", "座位": "舱位", "席别": "舱位",
    "抬头": "发票", "发票": "发票", "票面": "发票", "入账": "发票", "凭证": "附件", "票据": "附件", "附": "附件",
    "税号": "税号", "纳税人识别号": "税号", "识别号": "税号",
    "重复报销": "查重", "重复": "查重", "查重": "查重", "两次": "查重",
    "金额": "金额", "数额": "金额", "科目": "金额", "归集": "金额",
    "特批": "特批", "特别批准": "特批", "特别审批": "特批", "审批": "审批", "批准": "审批", "手续": "审批", "事前": "审批",
    "税率": "税率",
    "供应商": "供应商", "供货商": "供应商", "档案": "供应商", "连号": "供应商", "开票": "供应商",
    "地区": "城市", "档次": "城市", "城市": "城市", "一线": "城市", "二线": "城市", "一类": "城市", "二类": "城市",
}


class DenseEncoder:
    """本地向量编码器（sentence-transformers，懒加载，失败由调用方回退）"""

    def __init__(self, model_name: Optional[str] = None) -> None:
        # 默认 bge-small-zh-v1.5（~100MB，CPU 检索毫秒级）；bge-m3 精度更高但 CPU 编码慢，
        # 性能标定后降为可选（EMBEDDING_MODEL=BAAI/bge-m3 显式启用）
        self.model_name = model_name or os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        self._model = None

    def _ensure(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    def encode(self, texts: List[str]) -> List[List[float]]:
        model = self._ensure()
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vecs]


def _cosine(a: List[float], b: List[float]) -> float:
    dot = norm_a = norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


def _ranks_desc(scores: List[float]) -> List[int]:
    """按分数从高到低返回索引序列"""
    return sorted(range(len(scores)), key=lambda i: -scores[i])


class PolicyRetriever:
    """制度知识库检索器：hybrid（dense+sparse RRF）或 keyword（1.x 兼容）"""

    def __init__(self, index_path: Optional[str] = None, mode: Optional[str] = None,
                 encoder: Optional[DenseEncoder] = None) -> None:
        self.index_path = index_path or DEFAULT_INDEX_PATH
        self.mode = (mode or os.environ.get("RETRIEVAL_MODE", "keyword")).strip().lower()
        self.chunks: List[Dict] = []
        self._encoder = encoder
        self._encoder_failed = False
        self._vectors: Optional[List[List[float]]] = None
        self._load_index()

    def _load_index(self) -> None:
        if not os.path.exists(self.index_path):
            logger.warning("知识库索引不存在: %s", self.index_path)
            return
        with open(self.index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.chunks = data.get("chunks", [])
        if self.mode == "hybrid":
            if not self.chunks or any("embedding" not in c for c in self.chunks):
                logger.warning(
                    "索引缺少向量列（%d 块），回退 keyword 模式；请执行 python tools/build_policy_kb.py 重建",
                    len(self.chunks),
                )
                self.mode = "keyword"
            else:
                self._vectors = [c["embedding"] for c in self.chunks]

    @property
    def dense_available(self) -> bool:
        return self.mode == "hybrid" and self._vectors is not None

    def _get_encoder(self) -> Optional[DenseEncoder]:
        if self._encoder_failed:
            return None
        if self._encoder is None:
            try:
                enc = DenseEncoder()
                enc._ensure()  # 触发模型加载，失败即回退
                self._encoder = enc
            except Exception as e:  # 模型缺失/依赖缺失等，一律回退关键词模式
                logger.warning("向量编码器不可用（%s），回退 keyword 模式", e)
                self._encoder_failed = True
                return None
        return self._encoder

    # ---------- sparse：关键词计分（1.x 原逻辑） ----------

    def keyword_scores(self, keywords: Set[str]) -> List[float]:
        scores = []
        for chunk in self.chunks:
            text = chunk.get("content", "")
            kws = chunk.get("metadata", {}).get("keywords", []) or []
            score = 2 * sum(1 for kw in keywords if kw in text)
            score += 3 * sum(1 for kw in kws if kw in keywords)
            if len(text) > 400:
                score -= 1
            scores.append(score)
        return scores

    # ---------- dense：向量余弦 ----------

    def dense_scores(self, query_text: str) -> Optional[List[float]]:
        if not self.dense_available or not query_text:
            return None
        enc = self._get_encoder()
        if enc is None:
            return None
        try:
            qv = enc.encode([query_text])[0]
        except Exception as e:
            # 本地编码失败属于持久性故障（模型/依赖缺失），永久回退 keyword 模式
            logger.warning("向量编码失败（%s），永久回退 keyword 模式", e)
            self._encoder_failed = True
            return None
        return [_cosine(qv, v) for v in self._vectors]

    # ---------- 对外入口 ----------

    def retrieve(self, query_text: str = "", keywords: Optional[Set[str]] = None,
                 top_k: int = 8) -> List[Dict]:
        """混合检索，返回 top_k 个条款块（含 retrieval_score / retrieval_source）。

        query_text 为自然语言场景描述（dense 信号）；
        keywords 为业务关键词集合（sparse 信号），来自单据特征与违规代码。
        """
        keywords = keywords or set()
        if not self.chunks:
            return []

        dense = self.dense_scores(query_text) if self.mode == "hybrid" else None
        if self.mode != "hybrid" or dense is None:
            return self._top_by_keyword(keywords, top_k)

        kw_scores = self.keyword_scores(keywords)
        rrf: Dict[int, float] = {}
        for rank, idx in enumerate(_ranks_desc(dense)[: top_k * 3]):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
        for rank, idx in enumerate(_ranks_desc(kw_scores)[: top_k * 3]):
            if kw_scores[idx] > 0:
                rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)

        top = sorted(rrf.items(), key=lambda kv: -kv[1])[:top_k]
        results = []
        for idx, score in top:
            chunk = dict(self.chunks[idx])
            chunk["retrieval_score"] = round(score, 4)
            chunk["retrieval_source"] = "hybrid"
            results.append(chunk)
        return results

    def _top_by_keyword(self, keywords: Set[str], top_k: int) -> List[Dict]:
        """keyword 模式（与 1.x _retrieve_by_keywords 行为一致，含「同时废止」补充块）"""
        scores = self.keyword_scores(keywords)
        scored = [(s, i) for i, s in enumerate(scores) if s > 0]
        scored.sort(key=lambda x: -x[0])
        picked = [i for _, i in scored[:top_k]]
        for i, chunk in enumerate(self.chunks):
            if "同时废止" in chunk.get("content", "") and i not in picked:
                picked.append(i)
                break
        results = []
        for idx in picked:
            chunk = dict(self.chunks[idx])
            chunk["retrieval_score"] = round(scores[idx], 4)
            chunk["retrieval_source"] = "keyword"
            results.append(chunk)
        return results


def format_clauses(chunks: List[Dict]) -> str:
    """把检索结果格式化为提示词条款段（带出处），空结果返回占位文案"""
    if not chunks:
        return "（未检索到与单据直接相关的制度条款）"
    lines = []
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        lines.append(
            f"【{meta.get('doc', '制度')} {meta.get('article', '')}】\n{chunk.get('content', '')}"
        )
    return "\n\n".join(lines)
