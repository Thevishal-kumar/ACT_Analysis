import os
import re
import shutil
import traceback
import uuid
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dotenv import load_dotenv

load_dotenv()

try:
    from groq import Groq
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
except Exception as e:
    groq_client = None
    print("Groq client initialization failed. Is GROQ_API_KEY set?", e)

RELEVANCE_THRESHOLD = 0.50  # Cosine similarity threshold for "relevant" chunks

def verify_citations(answer: str, retrieved_chunks: list) -> str:
    """Verifies that any section/rule numbers cited by the AI actually exist in the retrieved chunks."""
    pattern = re.compile(r'(?i)\b((?:Section|Rule)\s+\d+[a-zA-Z]*(?:\([a-zA-Z0-9]+\))?)\b')
    matches = pattern.findall(answer)
    
    if not matches:
        return answer
        
    chunks_text = " ".join([c.get('text', '') for c in retrieved_chunks]).lower()
    unique_matches = set(matches)
    unverified = []
    
    for match in unique_matches:
        num_search = re.search(r'\d+', match)
        if num_search:
            core_num = num_search.group()
            if not re.search(rf'\b{core_num}\b', chunks_text):
                answer = answer.replace(match, f"~~{match}~~ ⚠️")
                unverified.append(match)
                
    if unverified:
        answer += "\n\n---\n⚠️ **Citation Notice:** The following references were NOT found in your database and may be inaccurate: " + ", ".join(f"`{u}`" for u in sorted(unverified)) + ". Please verify independently."
        
    return answer


def extract_issue_queries(statement: str) -> List[str]:
    """Uses LLM to extract multiple distinct legal issue queries from a user's statement for multi-query retrieval."""
    if not groq_client:
        return [statement]
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": """You are a legal issue extractor. Given a user's legal situation, identify the distinct legal issues and output each as a short search query on a separate line.

Rules:
- Output exactly 3 to 5 queries, one per line.
- Each query should be 3-8 words of specific legal terminology.
- No numbering, no bullets, no explanation.
- Each query should target a different legal concept.

Example input: "A landless agricultural laborer has lived in a homestead on the landlord's land for 20 years and faces forcible eviction."
Example output:
homestead rights landless laborer
protection from forcible eviction
parcha issuance settlement rights
long-term possession agricultural land
land reform homestead tenancy"""},
                {"role": "user", "content": statement}
            ],
            temperature=0.0,
            max_tokens=150,
        )
        queries = [q.strip() for q in completion.choices[0].message.content.strip().split("\n") if q.strip()]
        return queries[:5] if queries else [statement]
    except Exception:
        return [statement]


def filter_by_relevance(results: List[Dict], threshold: float = RELEVANCE_THRESHOLD) -> tuple:
    """Splits results into high-relevance and low-relevance based on FAISS cosine similarity score."""
    high_relevance = []
    low_relevance = []
    for r in results:
        if r.get("faiss_score", 0.0) >= threshold:
            high_relevance.append(r)
        else:
            low_relevance.append(r)
    return high_relevance, low_relevance


def compute_confidence(high_relevance: List[Dict], all_results: List[Dict]) -> str:
    """Returns HIGH, MEDIUM, or LOW confidence based on how many chunks passed the relevance threshold."""
    if not all_results:
        return "LOW"
    ratio = len(high_relevance) / len(all_results)
    avg_score = sum(r.get("faiss_score", 0) for r in high_relevance) / max(len(high_relevance), 1)
    if ratio >= 0.4 and avg_score >= 0.55:
        return "HIGH"
    elif ratio >= 0.2 or avg_score >= 0.45:
        return "MEDIUM"
    return "LOW"


def synthesize_answer(statement: str, high_chunks: List[Dict], low_chunks: List[Dict], confidence: str) -> str:
    if not groq_client:
        return "Groq API Key not found. Please set GROQ_API_KEY in the backend .env file to enable AI synthesis."
    
    if not high_chunks and not low_chunks:
        return "No clauses were found in the database for this statement."
        
    try:
        # Build context: act name + clause text for fact-matching
        context_parts = []
        for i, c in enumerate(high_chunks + low_chunks, 1):
            act = c.get('act_name', 'Unknown Act')
            text = c.get('text', '')
            score = c.get('faiss_score', 0)
            context_parts.append(f"[Source {i}] Act: {act} | Score: {score:.2f}\n{text}")
        context = "\n\n---\n\n".join(context_parts)

        system_message = """You are a Bihar Legal RAG system that retrieves Acts, Rules, Circulars, and Case Laws from a FAISS vector database.

Your objective is to maximize relevance and minimize hallucinations.

STRICT REQUIREMENTS:

1. NEVER search for an exact factual match to the user's statement.
   Instead:
   - Identify the underlying legal issue(s).
   - Return the laws that govern those legal issues.
   - Example:
     Statement: "A landless agricultural laborer is being forcibly evicted from a homestead."
     Legal Issues:
     * Homestead rights
     * Eviction
     * Landless laborer protection
     Return laws governing those issues even if the retrieved clauses discuss different facts.

2. DO NOT summarize retrieved clauses.

3. DO NOT explain retrieval reasoning.

4. DO NOT output:
   - Confidence
   - Match Type
   - Ranking
   - Search Process
   - Legal Issue Extraction
   - Notes
   - Disclaimers
   - "No direct match found"
   - "Retrieved clauses are unrelated"
   - Mentions of laws that are NOT applicable (e.g., "Act X is not applicable, instead...")
   - Any chain-of-thought reasoning

5. HALLUCINATION PREVENTION RULES:
   - Never generate a law solely from legal intuition.
   - Before returning a law, verify that:
     * The law exists in the retrieved database OR
     * The law is a well-established and widely recognized Indian/Bihar statute.
   - If uncertain whether a law exists, exclude it.
   - Never create laws by combining legal concepts into Act names.
     Examples of invalid outputs:
     * Bihar Protection of Tenants from Eviction Act
     * Bihar Restoration of Lands to Rural Laborers Act
     * Bihar Privation of Land (Exemption from Ceiling) Act
   - Return only laws that can be verified.
   - If fewer than 5 verified laws exist, return fewer than 5 laws.
   - Quality is more important than quantity.
   - Do not attempt to fill empty slots with guessed laws.
   - If retrieved clauses are unrelated, identify the legal issue and return only verified laws governing that issue.
   - Before final output, perform a verification step for each proposed law:
     * Does this Act actually exist?
     * Is it applicable to Bihar or India?
     * Does it govern the identified legal issue?
     If any answer is uncertain, remove the law.
   - OUTPUT ONLY VERIFIED ACTS.

6. If a section number is not explicitly present in retrieved materials or is uncertain, do NOT mention the section number.

7. Prefer Act names over section citations.

8. If retrieved clauses are unrelated:
   - Ignore them.
   - Identify the legal issue from the statement.
   - Return the most relevant Bihar laws based on established legal knowledge.

9. Rank laws using:
   - Same legal issue
   - Same type of dispute
   - Same category of parties
   - Bihar-specific applicability

10. Exclude laws that are only connected through keyword overlap.

11. Never return pond laws, village common land laws, consolidation laws, or encroachment laws unless the user's statement actually concerns those issues.

12. Return a maximum of 5 laws.

13. Each law must contain only:
   - Law Name
   - One short support statement (1–2 lines)

CRITICAL OUTPUT RULES:
The final answer MUST be strictly formatted as a simple list of applicable laws.
You are FORBIDDEN from discussing rejected laws, search processes, or reasoning.
If a law is not applicable, simply omit it from your response. Do not mention it at all.

Before outputting each law perform validation:
1. Does this law actually exist?
2. Is this law applicable in Bihar or throughout India?
3. Does this law govern the legal issue identified from the statement?
4. Am I certain this law exists?
If any answer is NO or UNCERTAIN: Omit the law silently.

OUTPUT FORMAT:

### Relevant Bihar Laws

• [Exact Law Name]
  Support: [One short affirmative sentence explaining why it governs the issue.]

• [Exact Law Name]
  Support: [One short affirmative sentence explaining why it governs the issue.]

RULES FOR OUTPUT:
- You must output ONLY the "Relevant Bihar Laws" header and the bulleted list.
- You must ONLY include laws that ARE applicable.
- Do NOT output any preamble, postamble, or chain-of-thought text.
- Maximum 5 laws. Minimum 1 law.
- Return nothing except the laws above."""

        user_prompt = f"""**User's Statement:**
"{statement}"

**Retrieved Clauses from Database:**

{context}

Return the most relevant Bihar laws. Adhere strictly to the OUTPUT FORMAT. Do not include any reasoning or mention inapplicable laws."""

        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
            max_tokens=512,
        )
        raw_answer = completion.choices[0].message.content
        return verify_citations(raw_answer, high_chunks + low_chunks)
    except Exception as e:
        return f"Could not generate an answer via Groq. Error: {str(e)}"
from core.embedder import embed_query
from core.faiss_act_store import load_index as load_act_index
from core.faiss_act_store import search as act_search
from core.faiss_act_store import get_total_chunks as get_act_total_chunks
from act.ingest import ingest_acts

app = FastAPI(
    title="Judicial AI Acts Backend",
    description="Vector search and ingestion API for statutory Acts and laws",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://actanalysis.netlify.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)

class ActSearchRequest(BaseModel):
    query: str
    top_k: int = 5

class ActSearchQueryRequest(BaseModel):
    statement: Optional[str] = ""

def _clean_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()

def _normalize_top_k(value: Any) -> int:
    try:
        top_k = int(value)
    except (TypeError, ValueError):
        raise ValueError("top_k must be an integer.")
    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20.")
    return top_k

def _ok(response: Any, message: str) -> dict:
    return {"status": "success", "message": message, "response": response}

def _json_error(message: str, status_code: int = 500) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": message},
    )

@app.on_event("startup")
def startup():
    print("Loading ACTS FAISS index...")
    try:
        load_act_index()
        print(f"ACTS FAISS ready | Chunks: {get_act_total_chunks()}")
    except Exception as e:
        print(f"Error loading ACTS FAISS on startup: {str(e)}")

@app.get("/")
def root():
    return {"message": "Judicial AI Acts Backend is running"}

@app.get("/judicialAI-health")
async def health_check():
    return {
        "status": "ok",
        "database": "ok",
    }


@app.post("/judicialAI/act/search")
async def search_acts_by_statement(request: ActSearchQueryRequest):
    try:
        combined_query = request.statement.strip() if request.statement else ""
        if not combined_query:
            raise ValueError("Provide a statement for search query.")
            
        load_act_index()
        
        # === PASS 1: Search with original statement ===
        query_embedding = embed_query(combined_query)
        top_k = 15
        results = act_search(query_embedding, k=top_k, include_scores=True)
        
        formatted_results = []
        for item in results:
            metadata = item.get("metadata", {})
            formatted_results.append({
                "text": item.get("text", ""),
                "act_name": metadata.get("act_name", "Statutory Act"),
                "document_name": metadata.get("document_name", "N/A"),
                "filename": metadata.get("filename", "N/A"),
                "pdf_path": metadata.get("pdf_path", "N/A"),
                "page_num": metadata.get("page_num", "N/A"),
                "chunk_index": metadata.get("chunk_index", "N/A"),
                "faiss_score": round(float(item.get("vector_score", 0.0)), 4)
            })
        
        # === RELEVANCE FILTERING ===
        high_relevance, low_relevance = filter_by_relevance(formatted_results)
        confidence = compute_confidence(high_relevance, formatted_results)
        
        # === STAGE 2: If low confidence, extract multiple legal issue queries and search again ===
        issue_queries = None
        if confidence == "LOW" and groq_client:
            issue_queries = extract_issue_queries(combined_query)
            print(f"[STAGE 2] Issue queries: {issue_queries}")
            
            existing_texts = {r["text"] for r in formatted_results}
            for iq in issue_queries:
                query_embedding_iq = embed_query(iq)
                results_iq = act_search(query_embedding_iq, k=10, include_scores=True)
                
                for item in results_iq:
                    text = item.get("text", "")
                    if text not in existing_texts:
                        metadata = item.get("metadata", {})
                        new_result = {
                            "text": text,
                            "act_name": metadata.get("act_name", "Statutory Act"),
                            "document_name": metadata.get("document_name", "N/A"),
                            "filename": metadata.get("filename", "N/A"),
                            "pdf_path": metadata.get("pdf_path", "N/A"),
                            "page_num": metadata.get("page_num", "N/A"),
                            "chunk_index": metadata.get("chunk_index", "N/A"),
                            "faiss_score": round(float(item.get("vector_score", 0.0)), 4)
                        }
                        formatted_results.append(new_result)
                        existing_texts.add(text)
            
            # Re-filter after multi-query merge
            high_relevance, low_relevance = filter_by_relevance(formatted_results)
            confidence = compute_confidence(high_relevance, formatted_results)
            
        # === SYNTHESIZE ANSWER ===
        generated_answer = synthesize_answer(combined_query, high_relevance, low_relevance, confidence)

        return _ok(
            {
                "query": combined_query,
                "issue_queries": issue_queries,
                "top_k": top_k,
                "confidence": confidence,
                "high_relevance_count": len(high_relevance),
                "low_relevance_count": len(low_relevance),
                "results": formatted_results,
                "generated_answer": generated_answer
            },
            "Acts search completed successfully."
        )
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": str(e)
            }
        )

@app.post("/judicialAI-act/search")
async def search_acts(request: ActSearchRequest):
    try:
        query = _clean_text(request.query)
        if not query:
            raise ValueError("Query cannot be empty.")

        top_k = _normalize_top_k(request.top_k)
        load_act_index()
        query_embedding = embed_query(query)
        results = act_search(query_embedding, k=top_k, include_scores=True)

        formatted_results = []
        for item in results:
            metadata = item.get("metadata", {})
            formatted_results.append({
                "text": item.get("text", ""),
                "act_name": metadata.get("act_name", "Statutory Act"),
                "document_name": metadata.get("document_name", "N/A"),
                "filename": metadata.get("filename", "N/A"),
                "pdf_path": metadata.get("pdf_path", "N/A"),
                "page_num": metadata.get("page_num", "N/A"),
                "chunk_index": metadata.get("chunk_index", "N/A"),
                "faiss_score": round(float(item.get("vector_score", 0.0)), 4)
            })

        return _ok(
            {
                "query": query,
                "top_k": top_k,
                "result_count": len(formatted_results),
                "results": formatted_results
            },
            "Acts search completed successfully."
        )
    except Exception as exc:
        traceback.print_exc()
        return _json_error(str(exc))

@app.post("/judicialAI/ingest")
async def trigger_ingestion():
    """
    Trigger ingestion of all PDF files in the data/output_batch directory.
    Runs ingest_acts() and returns the summary result.
    """
    try:
        result = ingest_acts()
        if result.get("status") == "error":
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": result.get("message", "Ingestion failed.")}
            )
        return _ok(result, f"Ingestion complete. Processed {result.get('processed_pdfs', 0)} PDFs, {result.get('total_chunks', 0)} chunks indexed.")
    except Exception as e:
        traceback.print_exc()
        return _json_error(str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
