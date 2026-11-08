| Block              | Role                                                                | Container                 |
| ------------------ | ------------------------------------------------------------------- | ------------------------- |
| 1. Loader          | Reads your files                                                    | app                       |
| 2. Chunker         | Splits the text into small overlapping pieces                       | app                       |
| 3. Embedding model | Turns text into a vector (meaning → numbers)                        | ollama (nomic-embed-text) |
| 4. Vector DB       | Stores the vectors and finds the closest ones (cosine similarity)   | qdrant                    |
| 5. Prompt builder  | Puts the retrieved chunks into the prompt                           | app                       |
| 6. LLM             | Generates the answer, one token at a time, like the GPT from before | ollama (qwen2.5:0.5b)     |

# Run
```
docker compose up -d --build
```

## download the models into the ollama container (once)
```
docker compose exec ollama ollama pull qwen2.5:0.5b
docker compose exec ollama ollama pull nomic-embed-text
```

## put some text files in ./docs, then index them
```
curl -X POST localhost:8000/ingest
```
## ask a question
```
curl -s -X POST localhost:8000/ask -H "Content-Type: application/json" \
-d '{"question": "What is our deployment process?"}' | python3 -m json.tool
```

## ask a question saving it in `experiments/assets`
```
mkdir -p experiments/assets
curl -s -X POST localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question": "Explain me the singleton design pattern", "k": 3}' \
  | python3 -m json.tool > experiments/assets/001-ask-singleton.json
```

## See the tools in action
- http://localhost:8000/docs: Swagger UI for testing the API

- http://localhost:6333/dashboard: the Qdrant UI, where you can see the stored vectors and payloads
```

                ┌──────────────── INDEXING (done once) ────────────────┐
  docs/*.txt ──► 1. Loader ──► 2. Chunker ──► 3. Embedding model ──► 4. Vector DB
                                              (transformer encoder)    (Qdrant)
                 └──────────────────────────────────────────────────────┘

                 ┌──────────────── QUERYING (each question) ────────────┐
  question ──► 3. Embedding model ──► 4. Vector DB: top-k similar chunks
                                              │
                                              ▼
                                 5. Prompt builder: context + question
                                              │
                                              ▼
                                 6. LLM (transformer decoder) ──► answer
                 └──────────────────────────────────────────────────────┘

```

### Vector database
Qudrant is a vector database that can perform 
- dense query: vector query
- sparse query: words match
- hybrid: both

### Nomic Embed Text
Nomic Embed Text is an open-source, fully auditable text embedding model created by Nomic AI. It converts text into numerical vectors for semantic search, retrieval-augmented generation (RAG), clustering, and classification

The embedding model turns any text into a list of exactly 768 numbers (the number of coordinates in the vector).

A sentence, a paragraph, or a 500-character chunk always comes out as 768 numbers, whatever its length.

The model was trained so that texts with similar meanings end up close together. The meaning is spread across all 768 values together.

EMBED_MODEL = "nomic-embed-text"   # transformer ENCODER -> 768-dim vectors

### How RAG uses it
Qdrant compares vectors with cosine similarity, which measures the angle between two vectors:

$$
\cos(a, b) = \frac{a \cdot b}{\|a\| \|b\|}
$$
​
 
- close to 1: same direction, so similar meaning
- close to 0: unrelated

#### Dense: what our app does
The 768 numbers from nomic-embed-text are a dense vector, meaning almost every value is non-zero:

`[0.021, -0.184, 0.097, 0.003, -0.052, ... ]   ← 768 values, all used`

These vectors capture meaning, so "start a container" can match "docker run launches a container" even with different words. The collection was created with:
`{"vectors": {"size": 768, "distance": "Cosine"}}`

That "Cosine" is the dense comparison. Qdrant also offers Dot, Euclid, and Manhattan for dense vectors.


#### Sparse: word matching
A sparse vector has one slot per word in the vocabulary (tens of thousands of slots), and almost all of them are 0. Only the words in the text get a weight:

```
text:
"docker run container"  →  {1532: 0.8, 8810: 0.5, 2047: 0.6}   ← only non-zero entries stored
```

The weights come from methods like BM25 (classic keyword scoring) or SPLADE (a learned model). The score is a dot product: only the words the query and the document share add to it. Qdrant uses dot product for sparse vectors, not cosine.

It's good for exact terms such as error codes, function names, or product IDs (`ERR_CONNECTION_REFUSED`, `useEffect`). Dense search can miss these.

#### Hybrid: both
You run both searches, then merge the two ranked lists, often with `Reciprocal Rank Fusion (RRF)`. That way you get both meaning ("similar ideas") and exact keywords ("this specific term").


LLM_MODEL = "qwen2.5:0.5b"         # small transformer DECODER (0.5B params)
