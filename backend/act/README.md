# Acts Search & Vector Database System

This directory contains the ingestion entry point for legislative and statutory Act PDFs.

## 1. Ingestion and Embedding Pipeline (`act/ingest.py`)

The ingestion script imports and indexes PDFs from `act_pdfs/`:

* **Reading PDFs**: It recursively scans `act_pdfs/` and extracts text page by page with PyMuPDF.
* **Token-Based Chunking**: It uses the `InLegalBERT` tokenizer to split page text into 512-token chunks with a 64-token overlap.
* **Embedding**: It reuses `core.embedder.embed_texts()` to generate 768-dimensional `law-ai/InLegalBERT` vectors.
* **Storing in FAISS**: It saves vectors and metadata through `core.faiss_act_store` at `faiss_index/act_index/index.bin` and `faiss_index/act_index/meta.json`.

Run ingestion with:

```bash
python -c "from act.ingest import ingest_acts; ingest_acts()"
```

## 2. Metadata

Each stored chunk keeps metadata that can be used for filtering, grouping, and citation:

* `source`, `index`, `corpus`
* `act_name`, `document_name`, `filename`, `pdf_path`
* `batch`, `part_number`, `is_copyable`
* `page_num`, `total_pages`, `chunk_index`, `page_chunk_index`
* `language`, `script`, `file_size_bytes`

## 3. Runtime Integration

This pipeline only builds the Act vector database. It does not connect the Act index to backend startup, RAG retrieval, judgment drafting, or any API flow yet.
