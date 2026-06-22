import os
import sys

# Ensure the parent directory is in sys.path so 'core' imports work
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import re
import fitz  # PyMuPDF
from tqdm import tqdm

from core.embedder import embed_texts, get_model
from core.faiss_act_store import (
    add_documents,
    get_total_chunks,
    load_index,
    save_index,
)


class SimpleRecursiveSplitter:
    def __init__(self, chunk_size, chunk_overlap, length_function):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.length_function = length_function

    def split_text(self, text: str) -> list[str]:
        chunks = []
        words = text.split(" ")
        current_chunk = []
        current_len = 0
        
        for word in words:
            word_len = self.length_function(word) + 1  # +1 for space
            if current_len + word_len > self.chunk_size:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                # Keep last words for overlap
                overlap_words = []
                overlap_len = 0
                for w in reversed(current_chunk):
                    w_len = self.length_function(w) + 1
                    if overlap_len + w_len < self.chunk_overlap:
                        overlap_words.insert(0, w)
                        overlap_len += w_len
                    else:
                        break
                current_chunk = overlap_words
                current_len = overlap_len
                
            current_chunk.append(word)
            current_len += word_len
            
        if current_chunk:
            chunks.append(" ".join(current_chunk))
            
        return chunks


ACT_PDF_DIR = "data/output_batch"



def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_act_filename(filename: str) -> dict:
    stem = os.path.splitext(filename)[0]
    stem_without_copyable = re.sub(r"[_\s-]+copyable$", "", stem, flags=re.IGNORECASE)
    part_match = re.search(r"[_\s-]+part[_\s-]*(\d+)$", stem_without_copyable, flags=re.IGNORECASE)
    part_number = int(part_match.group(1)) if part_match else None
    act_name = re.sub(
        r"[_\s-]+part[_\s-]*\d+$",
        "",
        stem_without_copyable,
        flags=re.IGNORECASE,
    )

    document_name = stem_without_copyable.replace("_", " ")
    document_name = re.sub(r"\bpart\s*(\d+)\b", r"part \1", document_name, flags=re.IGNORECASE)

    return {
        "act_name": _normalize_spaces(act_name.replace("_", " ")) or _normalize_spaces(document_name),
        "document_name": _normalize_spaces(document_name),
        "part_number": part_number,
        "is_copyable": bool(re.search(r"[_\s-]+copyable$", stem, flags=re.IGNORECASE)),
    }


def _detect_language_and_script(text: str) -> tuple[str, str]:
    has_devanagari = bool(re.search(r"[\u0900-\u097F]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))

    if has_devanagari and has_latin:
        return "mixed", "devanagari_latin"
    if has_devanagari:
        return "hi", "devanagari"
    if has_latin:
        return "en", "latin"
    return "unknown", "unknown"


def _relative_pdf_path(path: str) -> str:
    return os.path.relpath(path).replace(os.sep, "/")


def _build_chunk_metadata(
    path: str,
    filename_info: dict,
    page_num: int,
    page_chunk_index: int,
    document_chunk_index: int,
    total_pages: int,
    chunk_text: str,
) -> dict:
    language, script = _detect_language_and_script(chunk_text)

    return {
        "source": "act",
        "index": "act",
        "corpus": ACT_PDF_DIR,
        "act_name": filename_info["act_name"],
        "document_name": filename_info["document_name"],
        "filename": os.path.basename(path),
        "pdf_path": _relative_pdf_path(path),
        "batch": os.path.basename(os.path.dirname(path)),
        "part_number": filename_info["part_number"],
        "is_copyable": filename_info["is_copyable"],
        "page_num": page_num,
        "total_pages": total_pages,
        "chunk_index": document_chunk_index,
        "page_chunk_index": page_chunk_index,
        "language": language,
        "script": script,
        "file_size_bytes": os.path.getsize(path),
    }


def ingest_acts(batch_size=10):
    """
    Ingest, parse, chunk, embed, and store PDFs from act_pdfs/.
    """
    print("\nStarting Acts database ingestion...\n")
    load_index()

    pdf_files = []
    for root, _, files in os.walk(ACT_PDF_DIR):
        for file in sorted(files):
            if file.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, file))

    pdf_files.sort()

    total_pdfs = len(pdf_files)
    print(f"Total Acts PDFs found: {total_pdfs}")

    if total_pdfs == 0:
        print(f"No PDF files found in '{ACT_PDF_DIR}/' directory.")
        return {
            "status": "error",
            "message": f"No PDF files found in '{ACT_PDF_DIR}/' directory.",
        }

    tokenizer, _ = get_model()

    def bert_token_len(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=False))

    splitter = SimpleRecursiveSplitter(
        chunk_size=512,
        chunk_overlap=64,
        length_function=bert_token_len,
    )

    processed_count = 0
    for i in tqdm(range(0, len(pdf_files), batch_size), desc="Ingesting Act batches"):
        batch = pdf_files[i:i + batch_size]
        all_chunks = []

        for path in batch:
            filename_info = _parse_act_filename(os.path.basename(path))

            try:
                doc = fitz.open(path)
                document_chunk_index = 0
                total_pages = len(doc)

                for page_num in range(total_pages):
                    page = doc[page_num]
                    page_text = page.get_text().strip()
                    if len(page_text) < 20:
                        continue

                    chunks = splitter.split_text(page_text)
                    for page_chunk_index, chunk in enumerate(chunks):
                        all_chunks.append({
                            "text": chunk,
                            "metadata": _build_chunk_metadata(
                                path=path,
                                filename_info=filename_info,
                                page_num=page_num + 1,
                                page_chunk_index=page_chunk_index,
                                document_chunk_index=document_chunk_index,
                                total_pages=total_pages,
                                chunk_text=chunk,
                            ),
                        })
                        document_chunk_index += 1

                doc.close()
                processed_count += 1
            except Exception as exc:
                print(f"\nError processing PDF: {path}")
                print(exc)

        if not all_chunks:
            continue

        texts = [chunk["text"] for chunk in all_chunks]
        print(f"\nGenerating InLegalBERT embeddings for {len(texts)} Act chunks...")
        embeddings = embed_texts(texts)
        add_documents(all_chunks, embeddings)
        save_index()
        print(f"Batch completed. Total chunks in Acts store: {get_total_chunks()}\n")

    print("\nACTS DATASET INGESTION COMPLETE!")
    return {
        "status": "success",
        "processed_pdfs": processed_count,
        "total_chunks": get_total_chunks(),
        "index_path": "faiss_index/act_index",
        "source_path": ACT_PDF_DIR,
    }


if __name__ == "__main__":
    ingest_acts()
