"""Rank jobs against a profile. Stage 1: no API keys, fully explainable."""
import re
from dataclasses import dataclass, field

from .bm25 import BM25, tokenize

# Extend this vocabulary as you see new skills in job posts.
SKILL_VOCAB = {
    "python", "java", "javascript", "typescript", "go", "c#", "c++", "php", "kotlin", "swift", "dart",
    "react", "next.js", "vue", "angular", "tailwind", "flutter", "spring boot", "fastapi", "django",
    "flask", "node.js", "express", "mysql", "postgresql", "mongodb", "sql", "supabase", "firebase",
    "docker", "kubernetes", "aws", "azure", "gcp", "git", "rest api", "graphql", "microservices",
    "excel", "tableau", "power bi", "linux", "ci/cd", "figma",
}
ALIASES = {"postgres": "postgresql", "nextjs": "next.js", "node": "node.js", "spring": "spring boot",
           "reactjs": "react", "js": "javascript", "ts": "typescript", "rest": "rest api", "restful": "rest api"}

SENIOR_WORDS = re.compile(r"\b(senior|sr\.|lead|principal|staff|manager|head of)\b", re.I)
YEARS = re.compile(r"(\d+)\s*\+?\s*(?:years|yrs)", re.I)


def normalize(skill: str) -> str:
    s = skill.lower().strip()
    return ALIASES.get(s, s)


def extract_skills(text: str, extra_vocab=()) -> set[str]:
    low = " " + re.sub(r"[^a-z0-9\+\#\./ ]", " ", text.lower()) + " "
    for alias, canon in ALIASES.items():
        low = re.sub(rf"(?<![a-z0-9\.\+\#]){re.escape(alias)}(?![a-z0-9\+\#])", f" {canon} ", low)
    found = set()
    for skill in set(SKILL_VOCAB) | {normalize(s) for s in extra_vocab}:
        if re.search(rf"(?<![a-z0-9\+\#]){re.escape(skill)}(?![a-z0-9\+\#])", low):
            found.add(skill)
    return found


@dataclass
class Match:
    job: dict
    score: float
    matched: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def profile_text(profile: dict) -> str:
    parts = [profile.get("summary", ""), " ".join(profile.get("target_roles", [])),
             " ".join(profile.get("skills", []))]
    for p in profile.get("projects", []):
        parts += [p.get("blurb", ""), " ".join(p.get("tech", []))]
    return " ".join(parts)


def rank_jobs(profile: dict, jobs: list[dict]) -> list[Match]:
    my_skills = {normalize(s) for s in profile.get("skills", [])}
    for p in profile.get("projects", []):
        my_skills |= {normalize(s) for s in p.get("tech", [])}
    my_years = profile.get("years_experience", 0)

    docs = [tokenize(f"{j['title']} {j['title']} {j['text']}") for j in jobs]  # title counted twice
    bm25 = BM25(docs)
    query = tokenize(profile_text(profile))
    raw = [bm25.score(query, i) for i in range(len(jobs))]
    top = max(raw) if raw and max(raw) > 0 else 1.0

    results = []
    for i, job in enumerate(jobs):
        full = f"{job['title']}. {job['text']}"
        wanted = extract_skills(full, my_skills)
        matched, missing = sorted(wanted & my_skills), sorted(wanted - my_skills)
        coverage = len(matched) / len(wanted) if wanted else 0.0
        score = 0.6 * coverage + 0.4 * (raw[i] / top)
        notes = []

        years = [int(y) for y in YEARS.findall(full)]
        if SENIOR_WORDS.search(job["title"]) or (years and min(years) > my_years + 2):
            score *= 0.4
            notes.append("seniority/experience gap")
        if job.get("location") and not profile.get("open_to_remote", False) \
                and "remote" in job["location"].lower():
            notes.append("remote role")
        results.append(Match(job, round(score * 100, 1), matched, missing, notes))
    return sorted(results, key=lambda m: m.score, reverse=True)
