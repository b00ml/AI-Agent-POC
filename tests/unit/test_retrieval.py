"""检索器单元测试：keyword 兼容行为、hybrid RRF 融合、无向量回退（假编码器，无网络）。"""

import json


from core.retrieval import PolicyRetriever, format_clauses


CHUNKS = [
    {
        "id": "办法#第五条",
        "content": "第五条 住宿费以每晚单价为口径考核，报销总额除以实际住宿天数不得超过标准。",
        "metadata": {"doc": "办法", "article": "第五条", "keywords": ["住宿"]},
    },
    {
        "id": "办法#第十六条",
        "content": "第十六条 发票抬头必须为公司全称，纳税人识别号必须正确。",
        "metadata": {"doc": "办法", "article": "第十六条", "keywords": ["发票", "税号"]},
    },
    {
        "id": "办法#第十三条",
        "content": "第十三条 加班期间的市内交通费用须于加班前取得事前审批。",
        "metadata": {"doc": "办法", "article": "第十三条", "keywords": ["交通", "加班", "审批"]},
    },
    {
        "id": "办法#废止块",
        "content": "第三条 本办法施行后，原办法（V2.1）同时废止。",
        "metadata": {"doc": "办法", "article": "第三条", "keywords": []},
    },
]


def write_index(tmp_path, chunks):
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"chunks": chunks}, ensure_ascii=False), encoding="utf-8")
    return str(path)


class FakeEncoder:
    """按查询文本返回预设向量的假编码器（余弦=向量点积，已归一化）"""

    def __init__(self, vectors_by_text):
        self.vectors_by_text = vectors_by_text
        self.loaded = True

    def _ensure(self):
        return self

    def encode(self, texts):
        out = []
        for t in texts:
            for key, vec in self.vectors_by_text.items():
                if key in t:
                    out.append(vec)
                    break
            else:
                out.append([0.0] * len(next(iter(self.vectors_by_text.values()))))
        return out


def test_keyword_mode_scores_and_tie_zhikuai(tmp_path):
    path = write_index(tmp_path, CHUNKS)
    r = PolicyRetriever(index_path=path, mode="keyword")
    chunks = r.retrieve(keywords={"住宿", "发票"}, top_k=8)
    ids = [c["id"] for c in chunks]
    assert "办法#第五条" in ids and "办法#第十六条" in ids
    # 「同时废止」补充块保持 1.x 行为
    assert "办法#废止块" in ids
    assert all(c["retrieval_source"] == "keyword" for c in chunks)


def test_keyword_mode_no_match_returns_repeal_chunk_only(tmp_path):
    """无命中时仅返回「同时废止」补充块（与 1.x 行为一致的兜底）"""
    path = write_index(tmp_path, CHUNKS)
    r = PolicyRetriever(index_path=path, mode="keyword")
    out = r.retrieve(keywords={"量子力学"}, top_k=8)
    assert [c["id"] for c in out] == ["办法#废止块"]


def test_hybrid_requires_vector_column(tmp_path):
    chunks_no_vec = [dict(c) for c in CHUNKS]
    path = write_index(tmp_path, chunks_no_vec)
    r = PolicyRetriever(index_path=path, mode="hybrid")
    assert r.mode == "keyword"  # 无向量列自动回退
    assert not r.dense_available


def test_hybrid_rrf_fuses_dense_and_keyword(tmp_path):
    # 向量维度 3；让「第十三条（加班打车）」与查询语义最近，但关键词只命中第五条/第十六条
    emb_hotel = [0.9, 0.1, 0.0]
    emb_invoice = [0.8, 0.2, 0.0]
    emb_taxi = [0.1, 0.1, 0.99]
    emb_repeal = [0.0, 0.9, 0.1]
    chunks = [
        dict(CHUNKS[0], embedding=emb_hotel),
        dict(CHUNKS[1], embedding=emb_invoice),
        dict(CHUNKS[2], embedding=emb_taxi),
        dict(CHUNKS[3], embedding=emb_repeal),
    ]
    path = write_index(tmp_path, chunks)
    encoder = FakeEncoder({"加班": [0.1, 0.1, 0.99]})  # 查询语义指向第十三条
    r = PolicyRetriever(index_path=path, mode="hybrid", encoder=encoder)
    assert r.dense_available
    out = r.retrieve(query_text="加班打车要审批", keywords={"住宿"}, top_k=3)
    sources = {c["id"]: c["retrieval_source"] for c in out}
    assert "办法#第十三条" in sources  # dense 信号把关键词没命中的条款拉进来
    assert any(v == "hybrid" for v in sources.values())


def test_dense_encoder_failure_falls_back(tmp_path):
    chunks = [dict(c, embedding=[0.1, 0.2, 0.3]) for c in CHUNKS]
    path = write_index(tmp_path, chunks)

    class BrokenEncoder:
        def _ensure(self):
            raise RuntimeError("model missing")

    r = PolicyRetriever(index_path=path, mode="hybrid", encoder=BrokenEncoder())
    out = r.retrieve(query_text="住宿标准", keywords={"住宿"}, top_k=8)
    assert r._encoder_failed
    assert out and out[0]["retrieval_source"] == "keyword"


def test_format_clauses_placeholder_and_sources():
    assert format_clauses([]) == "（未检索到与单据直接相关的制度条款）"
    text = format_clauses([CHUNKS[0]])
    assert "【办法 第五条】" in text
