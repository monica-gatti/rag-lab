# 001 — Baseline: k=3, chunk 500, overlap 100

**Date:** 2026-11-08
**Status:** Done

## Goal

Establish a reference point: run the RAG pipeline with its default settings and observe how ingestion, retrieval and generation behave on a real book. All later experiments are compared against this one.

## Setup

| Parameter        | Value                                   |
|------------------|-----------------------------------------|
| LLM              | `qwen2.5:0.5b` (Ollama, CPU)            |
| Embedding model  | `nomic-embed-text` (768 dimensions)     |
| Vector DB        | Qdrant, distance `Cosine`               |
| Chunk size       | 500 characters                          |
| Overlap          | 100 characters                          |
| k (top-k)        | 3                                       |
| num_ctx          | Ollama default                          |
| Temperature      | Ollama default                          |
| Prompt           | v1 — "Answer using ONLY the context"    |
| Text cleaning    | None                                    |
| PDF loader       | `pypdf`, one source label per page      |

## Corpus

| Item               | Value                                              |
|--------------------|----------------------------------------------------|
| Document           | *Dive Into Design Patterns* — Alexander Shvets     |
| File               | `design-patterns-en.pdf` (28.2 MB)                 |
| Points in Qdrant   | 1,179                                              |
| Indexed vectors    | 0 (below `indexing_threshold`, exact search used)  |

## Question
> Explain me the singleton design pattern

## Result

### Answer

> The Singleton design pattern ensures that a class has only one instance, while providing a global access point to this instance.

### Retrieved chunks

| Rank | Score | Source  | Content (summary)                                      |
|------|-------|---------|--------------------------------------------------------|
| 1    | 0.827 | p.139   | Chapter title + definition of Singleton                |
| 2    | 0.783 | p.146   | End of Pros and Cons ("can mask bad design")           |
| 3    | 0.770 | p.140   | Start of "Problem" section (two problems, SRP)         |

### Prompt sent to the LLM (excerpt)
```
"Answer the question using ONLY the context below.\nIf the answer is not in the context, say \"I don't know\".\n\nContext:\n[design-patterns-en.pdf p.139]\nSINGLETON\nSingleton is a creational design pattern that lets you ensure\nthat a class has only one instance, while providing a global\naccess point to this instance.\n138 Creational Design Patterns / Singleton\n#163517\n<buyer_email>>\n\n[design-patterns-en.pdf p.146]\nnsibility Principle. The pattern solves\ntwo problems at the time.\nThe Singleton pattern can mask bad design, for instance, when\nthe c omponents o f the program kno w t oo much about\neach other.\n\n\n\n\n\n\n145 Creational Design Patterns / Singleton\n#163517\n<buyer_email> (#163517)\n\n[design-patterns-en.pdf p.140]\nProblem\nThe Singleton pattern solves two problems at the same time,\nviolating the Single Responsibility Principle:\n1. Ensure that a class has just a single instance. Why would any-\none want to control how many instances a class has? The most\ncommon reason for this is to control access to some shared\nresource—for example, a database or a file.\nHere’s how it works: imagine that you created an object, but\nafter a while decided to create a new one. Instead of receiving\na fresh object, you’ll get the\n\nQuestion: Explain me the singleton design pattern\nAnswer:"
```


## Observations

### Retrieval: correct chapter, poor coverage
- All 3 chunks come from the right chapter, with high, close scores (0.77–0.83).
- **Coverage check** (keyword scroll on `"Singleton"`, see `assets/001-scroll-singleton.json`):

| Where                         | Chunks matching "Singleton" |
|-------------------------------|-----------------------------|
| Singleton chapter (p.139–147) | 23                          |
| Elsewhere (TOC p.6, p.32, p.74 summary, p.235 Flyweight) | 6 |
| **Total**                     | **29**                      |

- k=3 → **3 / 25 chapter chunks ≈12% coverage**.
- Chapter sections and whether they were retrieved:

| Section             | PDF page(s) | Retrieved |
|---------------------|-------------|-----------|
| Intent (definition) | 139         | Yes       |
| Problem             | 140–141     | Partly (first chunk only) |
| Solution            | 141         | No        |
| Real-World Analogy  | 142         | No        |
| Structure (diagram) | 142         | No (diagram not extractable) |
| Pseudocode          | 143–144     | No        |
| Applicability       | 145         | No        |
| How to Implement    | 145–146     | No        |
| Pros and Cons       | 146–147     | Only a noisy tail chunk |
| Relations with Other Patterns | 147 | No      |

- **Rank #2 is a weak chunk:** the p.146 hit is the *tail* of the page (overlap + icons + header + watermark). The informative "Pros and Cons" chunk of the same page was not retrieved.

### Answer: correct but very incomplete
- One sentence, almost copied word for word from chunk #1.
- The chapter is 9 PDF pages; the LLM saw about 1,500 characters (≈ half a page).

### Causes identified
1. **Too little context:** 3 × 500 chars = 3 of 23 relevant chunks.
2. **Restrictive prompt:** "use ONLY the context" + short context → short answer.
3. **Very small model:** 0.5B parameters, tends to copy instead of explain.
4. **Noisy chunks:**
   - Buyer watermark (`#163517` + email) at the end of every page.
   - Page header (`142 Creational Design Patterns / Singleton`) on every page.
   - Icon glyphs extracted as Private Use Area characters (`\uf292`, `\uf5e4`, `\uf00c`…).
   - Hyphenation across lines (`Sin-\ngleton`, `Single-\nton`).
   - Extraction spacing glitches (`c omponents o f the program kno w`).
5. **Noise-only chunks:** per-page chunking leaves a small leftover at the end of each page, e.g. `"Patterns / Singleton\n#163517\n<email>"` (p.141, p.147). The header makes them look relevant, both to keyword search and probably to the embedding model.
6. **Chunk boundaries ignore structure:** cuts happen mid-word (`nsibility`), mid-list (`How to Implement\n1. A`), and at page breaks, while sections continue across pages.
7. **Overlap duplicates:** consecutive chunks share 100 chars; some short chunks are almost entirely overlap (p.32, p.235, p.147), so near-duplicates compete for the top-k slots.
8. **Code is extracted but corrupted:** syntax-highlighted keywords are doubled (`classclass DatabaseDatabase isis`, `privateprivate staticstatic`) and line numbers are glued to the code (`Database7`, `isis12`).
9. **Diagrams are lost:** the Structure section (p.142) is reduced to two icon characters.
10. **Distractors outside the chapter:** TOC (p.6), intro (p.32), summary (p.74) and Flyweight (p.235) also mention Singleton; with a larger k they may take slots from chapter chunks.

### Qdrant
- `indexed_vectors_count: 0` is expected: 1,179 × 768 × 4 bytes ≈ 3.6 MB, below `indexing_threshold` (10,000 KB) → exact brute-force search.
- `payload_schema: {}`: no payload index; filters scan all payloads (≈ 10 ms here, fine at this size).
- `match.text` **without** a text index behaved as a **case-insensitive, apparently word-based (singleton16 does not match)** match (p.32 matched on lowercase `singleton`).
- Keyword matches include chunks that contain "Singleton" **only in the page header**, so the header pollutes keyword search too.
- Point IDs are random UUIDs: re-ingesting creates new IDs. Deterministic IDs (e.g. hash of source + chunk index) would make ingestion idempotent.
- Source labels use the **PDF page index**, which is the printed page number + 1 (PDF p.139 = printed p.138).

### Keyword search misses chapter chunks
Comparing with a clean copy of the chapter (`ground-truth/singleton-chapter.md`):
at least 2 chapter chunks are not returned by `match.text: "Singleton"`:
- p.144, first chunk: pseudocode lines 16–24 (thread-safe `getInstance`) — the word
  appears as `singleton16` (line number glued by pypdf).
- p.146, first chunk: How to Implement steps 2–4 (lazy initialization) — the word is
  probably hyphenated (`sin-\ngleton`).
→ Chapter = at least 25 chunks; baseline coverage = 3/25 ≈ 12%.
→ Extraction artifacts break keyword (sparse) search; dense search is more robust to them.

## Conclusion

The pipeline works end to end and retrieval finds the right chapter, but **coverage is very low (≈ 13%)** and **one of the three slots went to a noise-heavy chunk**. Ingestion quality (cleaning, chunk boundaries) matters as much as k or the model.

## Next experiments

| #   | Change                                         | Hypothesis                                         |
|-----|------------------------------------------------|----------------------------------------------------|
| 002 | k = 8                                          | Coverage 13% → ~35%; more sections reach the LLM   |
| 003 | chunk 1200 / overlap 200 (+ num_ctx 8192)      | Fewer cuts, fewer chunks per section               |
| 004 | Text cleaning (watermark, headers, PUA glyphs, de-hyphenation) | Fewer noise-only chunks, cleaner embeddings |
| 005 | Drop chunks < 100 chars after cleaning         | Noise-only tails disappear from results            |
| 006 | Chunk the whole document, not page by page     | Sections no longer split at page breaks            |
| 007 | "Teacher" structured prompt                    | Structured answer (Intent, Problem…)               |
| 008 | `qwen2.5:1.5b`                                 | Better instruction following and synthesis         |

**Metric to track in each experiment:** chapter coverage = retrieved chunks from p.139–147 / total chapter chunks.

## Artifacts

- `/ask` response: `assets/001-ask-singleton.json`
- Keyword scroll on "Singleton": `assets/001-scroll-singleton.json`