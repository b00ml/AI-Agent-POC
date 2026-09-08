"""
重建制度知识库（RAG 索引）：解析 docs/*.docx 制度文档 → 条款级分块。

覆盖：费用报销管理办法_v3.2、发票合规指引、审批权限矩阵、供应商管理办法。
产物：data/rag_index/index.json（chunks: content + metadata{doc, article, keywords}）

用法：python tools/build_policy_kb.py [--docs-dir <path>]
"""

import os
import re
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


DEFAULT_DOCS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "source-docs",
)
OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "rag_index", "index.json",
)

KEYWORDS = {
    "住宿": "住宿", "酒店": "住宿", "每晚": "住宿",
    "伙食": "伙食", "餐": "伙食",
    "市内交通": "交通", "打车": "加班", "出租车": "加班", "加班": "加班",
    "长途": "舱位", "舱位": "舱位", "高铁": "舱位", "机票": "舱位",
    "抬头": "发票", "发票": "发票", "税号": "税号", "纳税人识别号": "税号",
    "重复": "查重", "查重": "查重",
    "金额": "金额", "票面金额": "金额",
    "特批": "特批", "审批": "审批", "事前": "审批",
    "附件": "附件", "票据": "附件",
    "税率": "税率", "适用": "税率", "增值税": "税率",
    "供应商": "供应商", "连号": "供应商",
}


def extract_docx_text(path: str) -> str:
    from docx import Document
    doc = Document(path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    # 表格内容（差旅标准表、税率表等）
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            paras.append(" | ".join(cells))
    return "\n".join(paras)


def split_clauses(text: str) -> list:
    """按「第X条」/「一、二、三」切分条款"""
    parts = re.split(r"\n(?=(?:第[一二三四五六七八九十百0-9]+条|一、|二、|三、|四、|五、|六、))", text)
    return [p.strip() for p in parts if len(p.strip()) > 8]


def infer_keywords(text: str) -> list:
    kws = set()
    for key, tag in KEYWORDS.items():
        if key in text:
            kws.add(tag)
    return sorted(kws)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-dir", default=DEFAULT_DOCS_DIR)
    args = parser.parse_args()

    docs_dir = args.docs_dir
    docs = [
        ("费用报销管理办法_v3.2", os.path.join(docs_dir, "费用报销管理办法_v3.2.docx")),
        ("发票合规指引", os.path.join(docs_dir, "发票合规指引.docx")),
        ("审批权限矩阵", os.path.join(docs_dir, "审批权限矩阵.docx")),
        ("供应商管理办法", os.path.join(docs_dir, "供应商管理办法.docx")),
    ]

    chunks = []
    for doc_name, path in docs:
        if not os.path.exists(path):
            print(f"跳过（不存在）: {path}")
            continue
        text = extract_docx_text(path)
        clauses = split_clauses(text)
        for c in clauses:
            m = re.match(r"^(第[一二三四五六七八九十百0-9]+条|一、|二、|三、|四、|五、|六、)", c)
            article = m.group(1) if m else ""
            chunks.append({
                "content": c,
                "metadata": {
                    "doc": doc_name,
                    "article": article,
                    "keywords": infer_keywords(c),
                },
            })
        print(f"{doc_name}: {len(clauses)} 条")

    # 静态补充块：出差城市档次表（城市→TIER 映射不在 docx 中，单独维护，保证 AI 能核验差旅标准）
    chunks.append({
        "content": (
            "差旅标准-出差城市档次表：判断差旅住宿/交通标准前，先查本表确定出差城市的档次。"
            "上海/北京/广州/深圳/杭州=一线（TIER1）；南京/苏州/成都/重庆/武汉/西安/青岛=二线（TIER2）；"
            "潍坊/其他=三线（TIER3）。例：出差城市成都按二线（TIER2）标准执行，员工二线住宿每晚上限 420 元。"
        ),
        "metadata": {
            "doc": "费用报销管理办法_v3.2",
            "article": "差旅城市档次表",
            "keywords": ["住宿", "每晚", "城市", "差旅"],
        },
    })

    # 条款块 ID（检索评测与引用溯源用；doc#article，重复时追加序号）
    seen: dict = {}
    for i, chunk in enumerate(chunks):
        meta = chunk["metadata"]
        base = f"{meta['doc']}#{meta['article'] or f'块{i}'}"
        if base in seen:
            seen[base] += 1
            base = f"{base}#{seen[base]}"
        else:
            seen[base] = 0
        chunk["id"] = base

    # 向量列（可选）：BGE-M3 本地 CPU 编码（不出域）。模型不可用时保持纯关键词索引，
    # 检索端自动回退 keyword 模式（core/retrieval.py）。
    # 默认 bge-small-zh-v1.5（CPU 检索毫秒级）；bge-m3 精度更高但 CPU 编码慢，按需显式启用
    embed_model = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    embedded = 0
    if os.environ.get("EMBEDDING_ENABLED", "1") != "0":
        try:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            from core.retrieval import DenseEncoder
            encoder = DenseEncoder(embed_model)
            vecs = encoder.encode([c["content"] for c in chunks])
            for c, v in zip(chunks, vecs):
                c["embedding"] = v
            embedded = len(vecs)
            print(f"向量编码完成: {embedded} 块（{embed_model}，本地 CPU）")
        except Exception as e:
            print(f"⚠ 向量编码跳过（{e}）；索引保持关键词模式可用")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"embeddingModel": embed_model if embedded else None, "chunks": chunks},
                  f, ensure_ascii=False, indent=1)
    print(f"知识库已重建: {OUT_PATH}（{len(chunks)} 块，向量 {embedded} 块）")


if __name__ == "__main__":
    main()
