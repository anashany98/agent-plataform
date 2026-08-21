"""Certificación hermética del retrieval local_tfidf para producción sin egress."""

from __future__ import annotations

import uuid

from app.config import settings
from app.database import SessionLocal
from app.models.models import RAGChunk, RAGDocument


def test_production_local_tfidf_ingest_retrieve_and_cite(
    client,
    auth_headers,
    monkeypatch,
    tmp_path,
) -> None:
    doc_id = f"tfidf-prod-{uuid.uuid4().hex}"
    marker = f"código operativo zafiro {uuid.uuid4().hex}"
    document = tmp_path / f"{doc_id}.txt"
    document.write_text(
        f"Manual operativo. El {marker} identifica el procedimiento de cierre mensual.",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local_tfidf")
    monkeypatch.setattr(settings, "RAG_ALLOWED_ROOTS", str(tmp_path))
    try:
        ingested = client.post(
            "/rag/ingest",
            headers=auth_headers,
            json={
                "doc_id": doc_id,
                "file_path": str(document),
                "metadata": {"classification": "public"},
            },
        )
        assert ingested.status_code == 200, ingested.text
        assert ingested.json()["retrieval_mode"] == "local_tfidf"

        queried = client.post(
            "/rag/query",
            headers=auth_headers,
            json={"query": marker, "top_k": 3, "min_score": 0.01},
        )
        assert queried.status_code == 200, queried.text
        result = queried.json()
        assert result["abstained"] is False
        assert result["retrieval_mode"] == "local_tfidf"
        assert result["citations"]
        assert result["citations"][0]["doc_id"] == doc_id
        assert marker in result["answer"]

        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "unreachable-provider")
        unsupported = client.post(
            "/rag/query",
            headers=auth_headers,
            json={"query": marker, "top_k": 3, "min_score": 0.01},
        )
        assert unsupported.status_code == 422
        assert "no soportado" in unsupported.json()["detail"]
    finally:
        db = SessionLocal()
        try:
            db.query(RAGChunk).filter(RAGChunk.document_id == doc_id).delete(
                synchronize_session=False
            )
            db.query(RAGDocument).filter(RAGDocument.id == doc_id).delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()
