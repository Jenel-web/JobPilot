import argparse
import json
from pathlib import Path

from .matcher import rank_jobs


def main():
    ap = argparse.ArgumentParser(description="Rank jobs against your profile")
    ap.add_argument("--profile", default="data/profile.json")
    ap.add_argument("--jobs", default="data/sample_jobs.json")
    ap.add_argument("--min", type=float, default=0, help="hide jobs scoring below this")
    a = ap.parse_args()

    profile_path = Path(a.profile)
    if not profile_path.exists():
        profile_path = Path("data/profile.example.json")
        print(f"(no {a.profile} found, using the example profile)\n")
    profile = json.loads(profile_path.read_text())
    jobs = json.loads(Path(a.jobs).read_text())

    for m in rank_jobs(profile, jobs):
        if m.score < a.min:
            continue
        print(f"{m.score:5.1f}  {m.job['title']} @ {m.job['company']} ({m.job.get('location','?')})")
        print(f"       matched: {', '.join(m.matched) or '-'}")
        print(f"       missing: {', '.join(m.missing) or '-'}")
        if m.notes:
            print(f"       notes:   {'; '.join(m.notes)}")
        print()


if __name__ == "__main__":
    main()
