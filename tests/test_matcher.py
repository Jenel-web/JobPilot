import json
from pathlib import Path

from jobpilot.bm25 import BM25, tokenize
from jobpilot.matcher import extract_skills, rank_jobs

ROOT = Path(__file__).resolve().parent.parent


def test_bm25_prefers_relevant_doc():
    docs = [tokenize("flutter dart mobile app"), tokenize("kubernetes go backend")]
    b = BM25(docs)
    q = tokenize("flutter mobile")
    assert b.score(q, 0) > b.score(q, 1)


def test_extract_skills_handles_aliases():
    assert {"postgresql", "next.js", "spring boot"} <= extract_skills("Postgres, NextJS and Spring")


def test_ranking_order():
    profile = json.loads((ROOT / "data/profile.example.json").read_text())
    jobs = json.loads((ROOT / "data/sample_jobs.json").read_text())
    ranked = [m.job["id"] for m in rank_jobs(profile, jobs)]
    assert ranked[0] in {"j1", "j3"}
    assert ranked[-1] in {"j2", "j4"}
    assert ranked.index("j2") > ranked.index("j1")
