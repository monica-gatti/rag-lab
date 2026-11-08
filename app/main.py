import os, uuid, pathlib, requests
from fastapi import FastAPI
from pydantic import BaseModel
from pypdf import PdfReader

OLLAMA = os.getenv("OLLAMA_URL", "http://localhost:11434")
QDRANT = os.getenv("QDRANT_URL", "http://localhost:6333")
EMBED_MODEL = "nomic-embed-text"   # transformer ENCODER -> 768-dim vectors
LLM_MODEL = "qwen2.5:0.5b"         # small transformer DECODER (0.5B params)
COLLECTION = "docs"
DOCS_DIR = "/data/docs"

app = FastAPI()

# ---------- Block 1+2: load & chunk ----------
def load_docs():
    """Yield (source_label, text) for every supported file."""
    for p in pathlib.Path(DOCS_DIR).glob("**/*"):
        ext = p.suffix.lower()
        if ext in {".txt", ".md"}:
            yield p.name, p.read_text(encoding="utf-8", errors="ignore")
        elif ext == ".pdf":
            reader = PdfReader(p)
            for i, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                if text.strip():                 # skip empty pages
                    yield f"{p.name} p.{i}", text

def chunk_text(text, size=500, overlap=100):
    """Fixed-size chunks with overlap so sentences aren't cut off from their context."""
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks

# ---------- Block 3: embeddings ----------
def embed(texts):
    r = requests.post(f"{OLLAMA}/api/embed",
                      json={"model": EMBED_MODEL, "input": texts}, timeout=300)
    r.raise_for_status()
    return r.json()["embeddings"]          # list of vectors

# ---------- Block 4: vector DB ----------
def reset_collection(dim):
    requests.delete(f"{QDRANT}/collections/{COLLECTION}")
    requests.put(f"{QDRANT}/collections/{COLLECTION}",
                 json={"vectors": {"size": dim, "distance": "Cosine"}}).raise_for_status()

def upsert(chunks, vectors, source):
    points = [{"id": str(uuid.uuid4()), "vector": v,
               "payload": {"text": c, "source": source}}
              for c, v in zip(chunks, vectors)]
    requests.put(f"{QDRANT}/collections/{COLLECTION}/points?wait=true",
                 json={"points": points}).raise_for_status()

def search(query_vector, k=3):
    r = requests.post(f"{QDRANT}/collections/{COLLECTION}/points/search",
                      json={"vector": query_vector, "limit": k, "with_payload": True})
    r.raise_for_status()
    return r.json()["result"]              # [{score, payload:{text, source}}, ...]

# ---------- Block 5: prompt ----------
def build_prompt(question, hits):
    context = "\n\n".join(f"[{h['payload']['source']}]\n{h['payload']['text']}" for h in hits)
    return f"""Answer the question using ONLY the context below.
If the answer is not in the context, say "I don't know".

Context:
{context}

Question: {question}
Answer:"""

# ---------- Block 6: LLM ----------
def generate(prompt):
    r = requests.post(f"{OLLAMA}/api/generate",
                      json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
                      timeout=600)
    r.raise_for_status()
    return r.json()["response"]

# ---------- API ----------
@app.post("/ingest")
def ingest():
    total, created = 0, False
    for name, text in load_docs():
        chunks = [c for c in chunk_text(text) if c.strip()]
        if not chunks:
            continue
        # nomic-embed-text expects task prefixes
        vectors = embed([f"search_document: {c}" for c in chunks])
        if not created:
            reset_collection(len(vectors[0])); created = True
        upsert(chunks, vectors, name)
        total += len(chunks)
    return {"chunks_indexed": total}

class Question(BaseModel):
    question: str
    k: int = 3

@app.post("/ask")
def ask(q: Question):
    qvec = embed([f"search_query: {q.question}"])[0]
    hits = search(qvec, q.k)
    prompt = build_prompt(q.question, hits)
    answer = generate(prompt)
    # return everything so you can SEE each step
    return {
        "answer": answer,
        "retrieved": [{"score": round(h["score"], 3), "source": h["payload"]["source"],
                       "text": h["payload"]["text"][:200]} for h in hits],
        "prompt_sent_to_llm": prompt,
    }