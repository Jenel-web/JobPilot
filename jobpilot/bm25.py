"""BM25 ranking written from scratch (the same idea a search engine uses)."""
import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9\+\#\.]+")


def tokenize(text: str) -> list[str]:
    return [t.strip(".") for t in _TOKEN.findall(text.lower()) if t.strip(".")]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in docs]
        self.lengths = [len(d) for d in docs]
        self.avg_len = (sum(self.lengths) / len(docs)) if docs else 0.0
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(docs)
        # +1 inside log keeps IDF non-negative for very common terms
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: list[str], index: int) -> float:
        tf, dl, total = self.docs[index], self.lengths[index], 0.0
        for term in set(query):
            if term not in tf:
                continue
            f = tf[term]
            denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avg_len or 1))
            total += self.idf[term] * (f * (self.k1 + 1)) / denom
        return total
