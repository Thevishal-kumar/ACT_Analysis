import json
import os
import shutil

import faiss
import numpy as np


DIM = 768

BASE_PATH = "faiss_index/act_index"
INDEX_PATH = f"{BASE_PATH}/index.bin"
META_PATH = f"{BASE_PATH}/meta.json"

index = None
metadata_store = []


def load_index():
    global index, metadata_store

    os.makedirs(BASE_PATH, exist_ok=True)

    if os.path.exists(INDEX_PATH):
        index = faiss.read_index(INDEX_PATH)

        if os.path.exists(META_PATH):
            with open(META_PATH, "r", encoding="utf-8") as f:
                metadata_store = json.load(f)
        else:
            metadata_store = []

        print(f"Acts FAISS loaded | Chunks: {len(metadata_store)}")
    else:
        index = faiss.IndexFlatIP(DIM)
        metadata_store = []
        print("New Acts FAISS created")


def save_index():
    if index is None:
        raise ValueError("Acts FAISS index is not initialized")

    os.makedirs(BASE_PATH, exist_ok=True)
    faiss.write_index(index, INDEX_PATH)

    temp_path = META_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(metadata_store, f, ensure_ascii=False)

    os.replace(temp_path, META_PATH)
    print(f"Saved Acts FAISS | Total chunks: {len(metadata_store)}")


def add_documents(chunks, embeddings):
    global metadata_store, index

    if index is None:
        raise ValueError("Acts FAISS index not loaded. Call load_index() first.")

    if not chunks or not embeddings:
        return

    vectors = np.array(embeddings).astype("float32")

    if vectors.shape[0] != len(chunks):
        raise ValueError("Number of embeddings does not match number of chunks")

    if vectors.shape[1] != DIM:
        raise ValueError(f"Embedding dimension mismatch. Expected {DIM}")

    faiss.normalize_L2(vectors)
    index.add(vectors)

    for chunk in chunks:
        metadata_store.append({
            "text": chunk["text"],
            "metadata": chunk["metadata"],
        })


def search(query_embedding, k=7, include_scores=False):
    if index is None:
        raise ValueError("Acts FAISS index not loaded")

    if len(metadata_store) == 0:
        return []

    query = np.array(query_embedding).astype("float32").reshape(1, -1)
    if query.shape[1] != DIM:
        raise ValueError(f"Query embedding dimension mismatch. Expected {DIM}")

    faiss.normalize_L2(query)
    distances, indices = index.search(query, k)

    results = []
    for rank, idx in enumerate(indices[0]):
        if idx == -1 or idx >= len(metadata_store):
            continue

        item = dict(metadata_store[idx])
        if include_scores:
            item["vector_score"] = float(distances[0][rank])
            item["rank"] = rank + 1

        results.append(item)

    return results


def get_total_chunks():
    return len(metadata_store)


def reset_index():
    global index, metadata_store

    if os.path.exists(BASE_PATH):
        shutil.rmtree(BASE_PATH)

    index = None
    metadata_store = []

    print("Acts FAISS reset complete")
