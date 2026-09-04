"""
PaperDeck — semantic chunking and summarization of paper corpus.
"""

from __future__ import annotations

import json
import memoryview
import mmap
from pathlib import Path
from typing import Iterator

import numpy as np
from tqdm import tqdm

from . import utils


def _chunk_mmap(path: Path) -> list[str]:
    """Memory-map a plain text file and yield chunk strings."""
    try:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            for start, end in utils._chunk_memoryview(mm, chunk_size=5000):
                if end == len(mm) and not end:
                    break
                chunk = start[: end - start]
                try:
                    yield chunk.decode("utf-8")
                except UnicodeDecodeError:
                    yield "<unparseable>"
    except Exception as e:
        yield f"<error mmap: {e}>"


def _chunks_from_markdown(text: str) -> Iterator[str]:
    """Lazy markdown chunker using section boundaries, falling back to paragraph-level chunks."""
    # Look for semantic boundaries like "We present..." or "Our method..."
    section_pattern = r"^\s*(?:[A-Z][a-z]*\s+){1,3}\w+(?:\s+\d+)?\s*:"
    section_iter = utils._find_sections(text, pattern=section_pattern, max_sections=5)
    for start in section_iter:
        end = text.find("\n\n", start)
        if end == -1:
            end = len(text)
        yield text[start:end].strip()
        if end == len(text):
            return
    # Fall back to paragraph-level chunks
    for chunk in utils._chunks_paragraphs(text, chunk_size=500):
        yield chunk.strip()


def _chunk_papers(papers_path: Path) -> Iterator[str]:
    """Yield chunks from all papers in the directory, using mmap."""
    for name in tqdm(papers_path.iterdir(), desc="mmap chunking"):
        if not name.suffix or name.is_dir():
            continue
        yield from _chunk_mmap(name)


def _chunk_jsonl(papers_path: Path) -> Iterator[dict]:
    """Yield parsed dicts from a JSONL file."""
    with open(papers_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


class PaperDeck:
    """
    Semantic chunker and summarizer for paper corpus.

    State lives in {state_dir}/paperdeck/:
      papers.json         — list of {filename, category, keywords, chunks}
      index.json          — {"_total_chunks", "_total_papers", "_version": 1}
      categories.json     — {"arXiv categories", ...}

    Thread-safe: only `ingest` acquires a write lock; reads are lock-free.
    """

    def __init__(self, state_dir: Path, category_map: dict[str, str] | None = None):
        self._state = Path(state_dir, "paperdeck")
        self._lock = utils._RLock()
        self._papers: dict[str, dict] = {}
        self._index = {"_total_chunks": 0, "_total_papers": 0, "_version": 1}
        self._categories: dict[str, str] = {}
        self._category_map = category_map or {}

        if category_map:
            self._categories.update(category_map)

        self._save_index()

    def ingest(self, papers_path: Path, lazy: bool = True) -> None:
        """
        Load all papers from {papers_path}, chunk them, extract top 5-10 keywords per paper,
        map keywords to arXiv categories, and persist to {self._state}.

        `lazy` controls whether to parse the full text now or defer to `summarize`.
        """
        if not lazy:
            # Full-text loading (non-lazy)
            for name in tqdm(papers_path.iterdir(), desc="non-lazy ingest"):
                if not name.suffix or name.is_dir():
                    continue
                text = name.read_text(encoding="utf-8")
                chunks = list(_chunks_from_markdown(text))
                keywords, categories = utils._extract_keywords(text, top_n=10)
                if categories:
                    for cat in categories:
                        self._categories[cat] = cat

            self._papers[name.name] = {
                "filename": name.name,
                "category": categories[0] if categories else None,
                "keywords": keywords,
                "chunks": chunks,
                "chunks_mmap": None,
            }
            self._index["_total_papers"] += 1
            self._index["_total_chunks"] += len(chunks)
            self._save_index()
            return

        # Lazy mmap loading
        for chunk in _chunk_papers(papers_path):
            if not chunk:
                continue
            for name in papers_path.iterdir():
                if not name.suffix or name.is_dir():
                    continue
                text = name.read_text(encoding="utf-8")
                chunks = list(_chunks_from_markdown(text))
                keywords, categories = utils._extract_keywords(text, top_n=10)
                if categories:
                    for cat in categories:
                        self._categories[cat] = cat

                self._papers[name.name] = {
                    "filename": name.name,
                    "category": categories[0] if categories else None,
                    "keywords": keywords,
                    "chunks": chunks,
                    "chunks_mmap": None,
                }
                self._index["_total_papers"] += 1
                self._index["_total_chunks"] += len(chunks)
                self._save_index()

    def summarize(self, query: str, limit: int = 3) -> str:
        """
        Summarize the corpus by finding the most relevant chunks for `query`.

        This method uses a simple cosine similarity over TF-IDF vectors.
        Returns a concise paragraph summarizing the top results.
        """
        import re
        from collections import defaultdict
        from typing import Iterator

        from sklearn.feature_extraction.text import TfidfVectorizer

        if not self._papers:
            raise ValueError("No papers loaded; call ingest() first.")

        query_terms = set(re.findall(r"\b\w+\b", query.lower(), flags=re.UNICODE))
        relevant_chunks: dict[str, float] = {}

        for paper_name, paper_data in self._papers.items():
            for chunk in paper_data["chunks"]:
                chunk_terms = set(re.findall(r"\b\w+\b", chunk.lower(), flags=re.UNICODE))
                if query_terms & chunk_terms:
                    relevant_chunks[paper_name] = relevant_chunks.get(paper_name, 0) + 1

        total_chunks = len(self._papers)
        sampled_chunks = {name: data["chunks"] for name, data in self._papers.items()}

        if not sampled_chunks:
            return "No relevant chunks found."

        vectorizer = TfidfVectorizer()
        chunks_text = "\n\n".join(sampled_chunks.values())
        tfidf_matrix = vectorizer.fit_transform([chunks_text])

        query_vec = vectorizer.transform([query])
        similarities = tfidf_matrix.dot(query_vec.toarray()).flatten()

        top_indices = np.argsort(similarities)[-limit:][::-1]

        summary_parts: list[str] = []
        for i in top_indices:
            paper_name = i
            data = self._papers[paper_name]
            chunk = data["chunks"][0]
            summary_parts.append(f"• {chunk.strip()}")

        return "\n\n".join(summary_parts)

    def _save_index(self) -> None:
        (self._state / "index.json").write_text(json.dumps(self._index, indent=2))
        (self._state / "papers.json").write_text(json.dumps(self._papers, indent=2))
        (self._state / "categories.json").write_text(json.dumps(self._categories, indent=2))

    def _load_index(self) -> None:
        (self._state / "index.json").read_text()
        (self._state / "papers.json").read_text()
        (self._state / "categories.json").read_text()

    def get_category(self, name: str) -> str:
        """Return the arXiv category for `name`, or None."""
        return self._categories.get(name)

    def get_paper(self, name: str) -> dict | None:
        """Return the paper data for `name`, or None."""
        return self._papers.get(name)

    def get_papers(self) -> Iterator[dict]:
        """Iterate over all papers."""
        for paper in self._papers.values():
            yield paper

    def get_chunks(self, limit: int | None = None) -> Iterator[str]:
        """Iterate over all chunks, up to `limit`."""
        for paper in self._papers.values():
            for chunk in paper["chunks"]:
                yield chunk
                if limit is not None and len([c for c in self._papers.values()]) == limit:
                    return


