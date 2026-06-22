# JudicialAI-BE — Complete Project Flow

> Every box below maps to **an actual file and function** in the codebase.  
> Arrows show **who calls whom** at runtime.  
> AI models (LLMs, Embeddings) and Vector DBs are explicitly highlighted.

---

## 1. Application Startup

When the server starts (`uvicorn main:app`), the `startup()` event in [main.py](file:///Users/nsppasinnovations/Desktop/NS%20APPS%20PROJECTS/judicialAI-BE/main.py#L391-L403) loads all three FAISS indexes into memory so they are ready for queries.

```mermaid
flowchart LR
    START(["uvicorn main:app"]) --> S["main.py :: startup()"]
    S --> F1["core/faiss_store.py :: load_index()"]
    S --> F2["core/faiss_dataset_store.py :: load_index()"]
    S --> F3["core/faiss_act_store.py :: load_index()"]

    F1 --> D1[("Case FAISS Index\n[Vector DB]")]
    F2 --> D2[("Dataset FAISS Index\n[Vector DB]")]
    F3 --> D3[("Act FAISS Index\n[Vector DB]")]

    style START fill:#a5d6a7,stroke:#2e7d32,color:#000
    style D1 fill:#ffcdd2,stroke:#c62828,color:#000
    style D2 fill:#ffcdd2,stroke:#c62828,color:#000
    style D3 fill:#ffcdd2,stroke:#c62828,color:#000
```

---

## 2. Router & Module Map

All routes are registered in [main.py](file:///Users/nsppasinnovations/Desktop/NS%20APPS%20PROJECTS/judicialAI-BE/main.py). Two sub-routers are also mounted:

```mermaid
flowchart TD
    APP["main.py\n(FastAPI app)"]

    APP -->|"include_router"| R1["legal_extraction/router.py\n/extract, /embed"]
    APP -->|"include_router"| R2["routers/thread_router.py\n/judicialAI/threads/*"]

    APP --> E1["POST /judicialAI-caseAnalysis/start"]
    APP --> E1b["GET  /judicialAI-caseAnalysis/status/:id"]
    APP --> E2["POST /judicialAI/find-findings"]
    APP --> E3["POST /judicialAI-judgmentDraft/generate"]
    APP --> E3b["GET  /judicialAI-judgmentDraft/status/:id"]
    APP --> E4["POST /judicialAI/precedent-retrieval"]
    APP --> E4b["GET  /judicialAI/precedent-retrieval/:id"]
    APP --> E5["POST /judicialAI-act/search"]
    APP --> E6["POST /judicialAI-previousOrder/extract"]
    APP --> E7["POST /judicialAI-appellant/extract"]
    APP --> E8["POST /judicialAI-respondent/extract"]

    style APP fill:#bbdefb,stroke:#1565c0,color:#000
    style R1 fill:#c8e6c9,stroke:#2e7d32,color:#000
    style R2 fill:#c8e6c9,stroke:#2e7d32,color:#000
```

---

## 3. Flow A — Case Analysis (Facts + Conflicts)

**Endpoint:** `POST /judicialAI-caseAnalysis/start`

This is an **async job**. The endpoint returns a `job_id` immediately and runs the analysis in a background thread. Uses the LLM twice (once for facts, once for conflicts).

```mermaid
flowchart TD
    subgraph CLIENT ["Frontend"]
        FE["POST /judicialAI-caseAnalysis/start\n{caseDetails, previousOrder,\n appellant, respondent}"]
    end

    FE -->|"returns job_id"| API["main.py :: start_case_analysis()"]
    API -->|"Background Thread"| PC["main.py :: process_case()"]

    PC --> FP["pipelines/final_pipeline.py\n:: run_facts_conflicts_pipeline()"]

    FP --> STEP1["STEP 1: Extract Facts"]
    FP --> STEP2["STEP 2: Generate Conflicts"]

    STEP1 --> EF["pipelines/extract_file.py\n:: extract_facts()"]
    EF -->|"Build Fact Prompt"| LLM1["core/llm.py :: call_llm()"]

    STEP2 --> CG["legal_extraction/conflict_generator_llm.py\n:: ConflictGeneratorLLM.generate()"]
    CG -->|"Build Conflict Prompt"| LLM2["core/llm.py :: call_llm()"]

    LLM1 -->|"Execute LLM Call"| OC["core/ollama_client.py\n:: generate_with_ollama()"]
    LLM2 -->|"Execute LLM Call"| OC

    OC -->|"HTTP POST"| OLLAMA[("Ollama Server\nqwen3:8b\n[LLM]")]

    PC -->|"Stores result"| JOBS["In-Memory JOBS dict"]
    POLL["GET /judicialAI-caseAnalysis/status/:id"] -.->|"Frontend polls"| JOBS

    style FE fill:#e1f5fe,stroke:#0277bd,color:#000
    style OLLAMA fill:#e1bee7,stroke:#6a1b9a,color:#000,stroke-width:2px
    style JOBS fill:#fff9c4,stroke:#f9a825,color:#000
```

> [!NOTE]
> `extract_facts()` here is from [pipelines/extract_file.py](file:///Users/nsppasinnovations/Desktop/NS%20APPS%20PROJECTS/judicialAI-BE/pipelines/extract_file.py) (v2 — direct LLM call). No FAISS is used in this path.

---

## 4. Flow B — Find Findings

**Endpoint:** `POST /judicialAI/find-findings`

Takes the facts + conflicts from Flow A and generates structured judicial findings. Uses the LLM in strict JSON mode.

```mermaid
flowchart TD
    FE["POST /judicialAI/find-findings\n{facts, conflicts, context_text}"]

    FE --> API["main.py :: api_find_findings()"]

    API -->|"converts to text"| GF["pipelines/generate_findings.py\n:: generate_findings()"]

    GF -->|"sanitize conflicts"| SC["sanitize_conflicts()"]
    GF -->|"Build prompt\n[LLM Call]"| OC["core/ollama_client.py\n:: generate_with_ollama()\n(json_mode=True)"]
    OC -->|"HTTP POST"| OLLAMA[("Ollama Server\nqwen3:8b\n[LLM]")]
    OLLAMA -->|"JSON response"| GF
    GF -->|"json.loads()"| PARSED["Parsed Findings JSON\n{summary, facts, findings[],\nevidence_based_observations,\nlegal_position}"]

    style FE fill:#e1f5fe,stroke:#0277bd,color:#000
    style OLLAMA fill:#e1bee7,stroke:#6a1b9a,color:#000,stroke-width:2px
    style PARSED fill:#c8e6c9,stroke:#2e7d32,color:#000
```

---

## 5. Flow C — Judgment Draft Generation

**Endpoint:** `POST /judicialAI-judgmentDraft/generate`

Another **async job**. Takes facts, conflicts, findings, verdict, case details, and optional precedent/act text, and feeds it all into the LLM.

```mermaid
flowchart TD
    FE["POST /judicialAI-judgmentDraft/generate\n{facts, conflicts, findings, verdict,\ncaseDetails, precedents_text, acts_text}"]

    FE -->|"returns job_id"| API["main.py ::\ngenerate_frontend_judgment_draft()"]
    API -->|"Background Thread"| PJ["main.py :: process_judgment_draft()"]

    PJ --> HEADER["main.py :: _build_court_header()\n(builds revenue court format header)"]
    PJ --> GJD["pipelines/generate.py\n:: generate_judgment_draft()"]

    GJD -->|"Build massive prompt\nwith all context\n[LLM Call]"| LLM["core/llm.py :: call_llm()"]
    LLM --> OC["core/ollama_client.py\n:: generate_with_ollama()"]
    OC -->|"HTTP POST"| OLLAMA[("Ollama Server\nqwen3:8b\n[LLM]")]

    PJ -->|"courtHeader + draft"| JOBS["In-Memory JOBS dict"]
    POLL["GET /judicialAI-judgmentDraft/status/:id"] -.-> JOBS

    style FE fill:#e1f5fe,stroke:#0277bd,color:#000
    style OLLAMA fill:#e1bee7,stroke:#6a1b9a,color:#000,stroke-width:2px
    style JOBS fill:#fff9c4,stroke:#f9a825,color:#000
```

---

## 6. Flow D — Precedent Retrieval

**Endpoint:** `POST /judicialAI/precedent-retrieval`

Another **async job**. Highly complex path: embeds query, searches 2 Vector DBs, then uses the LLM to analyze *each* retrieved precedent.

```mermaid
flowchart TD
    FE["POST /judicialAI/precedent-retrieval\n{summary}"]

    FE -->|"returns job_id"| API["main.py :: precedent_retrieval()"]
    API -->|"Background Thread"| PPR["main.py :: process_precedent_retrieval()"]

    PPR --> RP["retrieve_precedents.py\n:: retrieve_precedents()"]

    RP --> S1["STEP 1: Build Query"]
    S1 --> BQ["core/legal_retrieval.py\n:: build_legal_research_query()"]

    RP --> S2["STEP 2: Vector Search"]
    S2 --> SP["retrieve_precedents.py\n:: search_precedents()"]
    SP --> SLK["core/legal_retrieval.py\n:: search_legal_knowledge()"]

    SLK -->|"Encode Query\n[Embedding]"| EMB["core/embedder.py\n:: embed_query()"]
    EMB -->|"Uses"| ILB[("InLegalBERT\n[Embedding Model]")]
    
    SLK -->|"Vector Similarity Search"| DS["core/faiss_dataset_store.py :: search()"]
    SLK -->|"Vector Similarity Search"| AS["core/faiss_act_store.py :: search()"]

    DS --> D2[("Dataset FAISS Index\n[Vector DB]")]
    AS --> D3[("Act FAISS Index\n[Vector DB]")]

    RP --> S3["STEP 3: LLM Analysis\n(Loop over each precedent)"]
    S3 --> AP["retrieve_precedents.py\n:: analyze_precedent()"]
    AP -->|"Execute LLM Call\n(JSON mode)"| CO["retrieve_precedents.py\n:: call_ollama()"]
    CO -->|"HTTP POST"| OLLAMA[("Ollama Server\nqwen3:8b\n[LLM]")]

    RP --> S4["STEP 4: Rank by LLM relevance_score"]
    RP --> S5["STEP 5: Return top N"]

    PPR --> JOBS["In-Memory JOBS dict"]
    POLL["GET /judicialAI/precedent-retrieval/:id"] -.-> JOBS

    style FE fill:#e1f5fe,stroke:#0277bd,color:#000
    style ILB fill:#fff3e0,stroke:#e65100,color:#000,stroke-width:2px
    style OLLAMA fill:#e1bee7,stroke:#6a1b9a,color:#000,stroke-width:2px
    style D2 fill:#ffcdd2,stroke:#c62828,color:#000,stroke-width:2px
    style D3 fill:#ffcdd2,stroke:#c62828,color:#000,stroke-width:2px
    style JOBS fill:#fff9c4,stroke:#f9a825,color:#000
```

---

## 7. Flow E — Act Search

**Endpoint:** `POST /judicialAI-act/search`

A **synchronous** endpoint. Embeds query, searches Acts FAISS index. No LLM used here.

```mermaid
flowchart LR
    FE["POST /judicialAI-act/search\n{query, top_k}"] --> API["main.py :: search_acts()"]

    API -->|"Encode Query\n[Embedding]"| EMB["core/embedder.py\n:: embed_query()"]
    EMB --> MODEL[("InLegalBERT\n(768-dim)\n[Embedding Model]")]

    API -->|"Vector Similarity Search"| AS["core/faiss_act_store.py\n:: search()"]
    AS --> D3[("Act FAISS Index\n[Vector DB]")]

    API --> RES["Formatted Results\n{text, act_name, filename,\npage_num, faiss_score}"]

    style FE fill:#e1f5fe,stroke:#0277bd,color:#000
    style D3 fill:#ffcdd2,stroke:#c62828,color:#000,stroke-width:2px
    style MODEL fill:#fff3e0,stroke:#e65100,color:#000,stroke-width:2px
    style RES fill:#c8e6c9,stroke:#2e7d32,color:#000
```

---

## 8. Flow F — Structured Legal Extraction

**Endpoint:** `POST /extract` (via [legal_extraction/router.py](file:///Users/nsppasinnovations/Desktop/NS%20APPS%20PROJECTS/judicialAI-BE/legal_extraction/router.py))

Uses the LLM extensively to extract JSON from raw PDFs.

```mermaid
flowchart TD
    FE["POST /extract\n{file OR text, doc_type}"]
    FE --> ROUTER["legal_extraction/router.py\n:: extract_structured_judgment()"]

    ROUTER -->|"if PDF"| PDF["legal_extraction/pdf_utils.py\n:: extract_pdf_text()"]
    PDF -->|"PyMuPDF or pdfplumber"| TEXT["Extracted Text"]

    ROUTER --> SVC["legal_extraction/service.py\n:: LegalExtractionService.extract()"]

    SVC --> CLEAN["text_utils.py :: clean_legal_text()"]
    SVC --> CHUNK["text_utils.py :: chunk_text()"]
    SVC --> PASS["Multi-Pass Extraction\n:: _run_pass() → _extract_from_chunk()"]

    PASS -->|"Build Extraction Prompt"| LLMC["legal_extraction/llm.py\n:: LLMClient.generate_json()"]
    LLMC -->|"Execute LLM Call\n(JSON mode)"| OC["core/ollama_client.py\n:: generate_with_ollama()"]
    OC --> OLLAMA[("Ollama Server\nqwen3:8b\n[LLM]")]

    LLMC -->|"if malformed"| REPAIR["LLMClient._repair_json()\n(sends back for fix)"]
    REPAIR -->|"Execute Repair LLM Call"| OC

    SVC --> MERGE["service.py :: merge_results()"]
    SVC --> POST["Role-specific post-processing\n_post_process_lower()\n_post_process_appellant()\n_post_process_respondent()"]

    POST --> RESULT["Validated Pydantic Model\nLowerCourtExtraction /\nAppellantExtraction /\nRespondentExtraction"]

    style FE fill:#e1f5fe,stroke:#0277bd,color:#000
    style OLLAMA fill:#e1bee7,stroke:#6a1b9a,color:#000,stroke-width:2px
    style RESULT fill:#c8e6c9,stroke:#2e7d32,color:#000
```

**Embedding endpoint:** `POST /embed`

```mermaid
flowchart LR
    FE["POST /embed\n{doc_type, data}"] --> ROUTER["router.py :: embed_structured_judgment()"]
    ROUTER --> EMB["legal_extraction/embeddings.py\n:: InLegalBERTEmbeddingService\n.embed_extraction()"]
    EMB -->|"Uses"| ILB[("InLegalBERT\n[Embedding Model]")]
    EMB --> VEC["3 embeddings:\nprimary / secondary / tertiary\n(768-dim each)"]

    style FE fill:#e1f5fe,stroke:#0277bd,color:#000
    style ILB fill:#fff3e0,stroke:#e65100,color:#000,stroke-width:2px
    style VEC fill:#c8e6c9,stroke:#2e7d32,color:#000
```

---

## 9. Thread History (Save/Load)

**Endpoints:** `POST/GET/DELETE /judicialAI/threads/*`

```mermaid
flowchart LR
    FE["Frontend"] --> TR["routers/thread_router.py"]
    TR --> TC["controllers/thread_controller.py"]
    TC --> DB["db/mongodb.py"]
    DB --> MONGO[("MongoDB Atlas\njudicial_ai.threads")]

    style FE fill:#e1f5fe,stroke:#0277bd,color:#000
    style MONGO fill:#ffcdd2,stroke:#c62828,color:#000
```

| Endpoint | Action |
|---|---|
| `POST /judicialAI/threads/save` | Save or update a thread (upsert by `thread_id`) |
| `GET /judicialAI/threads/` | List recent threads (sidebar history) |
| `GET /judicialAI/threads/:id` | Load a specific thread |
| `DELETE /judicialAI/threads/:id` | Delete a thread |

---

## 10. Document Text Intake (Simple Normalization)

These three endpoints just validate and normalize text. **No AI or FAISS is involved.**

```mermaid
flowchart LR
    E1["POST /judicialAI-previousOrder/extract"] --> DP["main.py :: _document_payload()"]
    E2["POST /judicialAI-appellant/extract"] --> DP
    E3["POST /judicialAI-respondent/extract"] --> DP
    DP --> RES["{ documentType, source,\ntext, characterCount }"]

    style RES fill:#c8e6c9,stroke:#2e7d32,color:#000
```

---

## 11. Offline Ingestion (Dataset & Acts)

These are run **manually** from the command line, not from API endpoints. Embeds PDFs and inserts vectors into FAISS.

```mermaid
flowchart TD
    subgraph Dataset Ingestion
        CMD1["python -c 'from pipelines.ingest_dataset\nimport ingest_dataset; ingest_dataset()'"]
        CMD1 --> ID["pipelines/ingest_dataset.py\n:: ingest_dataset()"]
        ID --> PDF["core/pdf_extractor.py\n:: extract_pdf_content()"]
        ID -->|"Encode\n[Embedding]"| EMB1["core/embedder.py :: embed_texts()"]
        EMB1 -.-> ILB[("InLegalBERT\n[Embedding Model]")]
        ID -->|"Insert Vectors"| FAISS1["core/faiss_dataset_store.py\n:: add_documents() → save_index()"]
        PDF --> SRC1[("supreme_court_judgments/\n*.pdf")]
        FAISS1 --> D2[("faiss_index/dataset_index/\n[Vector DB]")]
    end

    subgraph Act Ingestion
        CMD2["python -c 'from act.ingest\nimport ingest_acts; ingest_acts()'"]
        CMD2 --> IA["act/ingest.py :: ingest_acts()"]
        IA -->|"Encode\n[Embedding]"| EMB2["core/embedder.py :: embed_texts()"]
        EMB2 -.-> ILB
        IA -->|"Insert Vectors"| FAISS2["core/faiss_act_store.py\n:: add_documents() → save_index()"]
        IA --> SRC2[("act_pdfs/ *.pdf")]
        FAISS2 --> D3[("faiss_index/act_index/\n[Vector DB]")]
    end

    style SRC1 fill:#b0bec5,color:#000
    style SRC2 fill:#b0bec5,color:#000
    style ILB fill:#fff3e0,stroke:#e65100,color:#000,stroke-width:2px
    style D2 fill:#ffcdd2,stroke:#c62828,color:#000,stroke-width:2px
    style D3 fill:#ffcdd2,stroke:#c62828,color:#000,stroke-width:2px
```

---

## 12. Core Module Dependency Map

This shows how the **core/** modules wrap the external AI/DB services.

```mermaid
flowchart TD
    subgraph "core/"
        EMBED["embedder.py"]
        CHUNK["chunker.py"]
        LLM["llm.py"]
        OC["ollama_client.py"]
        RER["reranker.py"]
        FS["faiss_store.py"]
        FDS["faiss_dataset_store.py"]
        FAS["faiss_act_store.py"]
        LR["legal_retrieval.py"]
        PDFX["pdf_extractor.py"]
    end

    LLM --> OC
    OC -->|"HTTP"| OLLAMA[("Ollama Server\n[LLM]")]
    LR --> EMBED
    LR -->|"Vector Search"| FDS
    LR -->|"Vector Search"| FAS

    subgraph External Models
        ILB[("law-ai/InLegalBERT\n[Embedding Model]")]
        CE[("cross-encoder/\nms-marco-MiniLM-L-6-v2\n[Reranker Model]")]
    end

    EMBED -->|"Load & Execute"| ILB
    RER -->|"Load & Execute"| CE
    
    FDS --> DB1[("Dataset FAISS Index\n[Vector DB]")]
    FAS --> DB2[("Act FAISS Index\n[Vector DB]")]

    style OLLAMA fill:#e1bee7,stroke:#6a1b9a,color:#000,stroke-width:2px
    style ILB fill:#fff3e0,stroke:#e65100,color:#000,stroke-width:2px
    style CE fill:#fff3e0,stroke:#e65100,color:#000,stroke-width:2px
    style DB1 fill:#ffcdd2,stroke:#c62828,color:#000,stroke-width:2px
    style DB2 fill:#ffcdd2,stroke:#c62828,color:#000,stroke-width:2px
```

---

## 13. Full End-to-End User Journey

This is the complete flow a user follows through the frontend, annotated with AI model usage.

```mermaid
flowchart TD
    U["👤 User"] -->|"1. Paste 3 documents"| INTAKE["Text Intake Endpoints\n/previousOrder/extract\n/appellant/extract\n/respondent/extract"]

    INTAKE -->|"2. Start Analysis"| CASE["POST /caseAnalysis/start\n→ Background Thread"]

    CASE -->|"LLM Call 1"| FACTS["Facts\n(extract_file.py)"]
    CASE -->|"LLM Call 2"| CONFLICTS["Conflicts\n(conflict_generator_llm.py)"]

    FACTS --> FC["facts + conflicts → Frontend"]
    CONFLICTS --> FC

    FC -->|"3. Generate Findings"| FIND["POST /find-findings\n→ generate_findings.py"]

    FIND -->|"LLM Call 3"| FINDINGS["Structured Findings"]

    FINDINGS -->|"4. Retrieve Precedents"| PREC["POST /precedent-retrieval\n→ Background Thread"]
    PREC -->|"Embedding Call"| SEARCH["FAISS Search\n(Dataset + Acts indexes)"]
    SEARCH -->|"LLM Call 4\n(Loops over results)"| ANALYZE["LLM analyzes each\nprecedent for relevance"]
    ANALYZE --> PRECRES["Ranked Precedents"]

    FINDINGS -->|"5. Search Acts"| ACTS["POST /act/search"]
    ACTS -->|"Embedding Call"| SEARCHACT["FAISS Search\n(Act index)"]
    SEARCHACT --> ACTRES["Relevant Act Provisions"]

    FINDINGS -->|"6. Generate Judgment"| JUDG["POST /judgmentDraft/generate\n→ Background Thread"]
    PRECRES -.->|"precedents_text"| JUDG
    ACTRES -.->|"acts_text"| JUDG
    JUDG -->|"LLM Call 5\n(Massive Context)"| DRAFT["Complete Judgment Draft\n(with court header)"]

    DRAFT -->|"7. Save"| SAVE["POST /threads/save\n→ MongoDB"]

    style U fill:#a5d6a7,stroke:#2e7d32,color:#000
    style DRAFT fill:#c8e6c9,stroke:#2e7d32,color:#000
    style SAVE fill:#fff9c4,stroke:#f9a825,color:#000
    style FACTS fill:#e1bee7,stroke:#6a1b9a,color:#000
    style CONFLICTS fill:#e1bee7,stroke:#6a1b9a,color:#000
    style FINDINGS fill:#e1bee7,stroke:#6a1b9a,color:#000
    style ANALYZE fill:#e1bee7,stroke:#6a1b9a,color:#000
    style SEARCH fill:#ffcdd2,stroke:#c62828,color:#000
    style SEARCHACT fill:#ffcdd2,stroke:#c62828,color:#000
```
