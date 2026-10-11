#!/usr/bin/env python3
"""
workshop/github-snapshot.py - pull real public repositories into the vault seed.

RUN THIS AS THE PRESENTER, BEFORE THE WORKSHOP. Participants never run it.

    python workshop\\github-snapshot.py --repo octocat/Hello-World --dry-run
    python workshop\\github-snapshot.py --repo yourname/yourrepo --repo yourname/other

It reads the PUBLIC GitHub REST API. There is no login, no token and no OAuth
app. Public repository metadata, open issues and open pull requests are all
readable anonymously, which is the whole reason this is safe to ship:

  * No participant ever authenticates to anything.
  * No credential exists to leak into a prompt-injection demo.
  * Nothing you pull can be written back, because nothing here can write.

Anonymous calls are rate-limited to 60 an hour per IP. Three repositories cost
about nine calls, so that is ample for a presenter and hopeless for forty
laptops - which is the other reason participants get a file instead.

If you do hit the limit, set GITHUB_TOKEN to any classic token with no scopes
ticked. That raises the limit to 5000 an hour and still grants nothing, but
treat it the way you would treat any credential: not in the repo, and revoked
when the workshop is over.

Output is merged into workshop\\vault-seed.json under the `coding` key, which
IS committed. The health, finance and pc-assist keys are left alone, so you
can run this without running the others.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "vault-seed.json")
API = "https://api.github.com"

UA = "CastleKeep-workshop-snapshot (https://github.com/iswaryaalex/CastleKeep)"


def _get(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA,
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 403 and "rate limit" in e.read().decode("utf-8", "replace").lower():
            print("  GitHub rate limit reached (60/hour anonymous).")
            print("  Wait an hour, or set GITHUB_TOKEN to a no-scope token.")
            sys.exit(2)
        print("  HTTP %s from %s" % (e.code, url))
        return None
    except urllib.error.URLError as e:
        print("  Could not reach %s - %s" % (url, e))
        return None


def _day(iso):
    return str(iso or "")[:10]


def fetch_repo(full_name):
    """One repository: its own record, its open issues and its open pulls."""
    owner, _, name = full_name.partition("/")
    if not owner or not name:
        print("  Skipping %r - expected owner/repo." % full_name)
        return None
    repo = _get("/repos/%s/%s" % (owner, name))
    if not repo:
        return None

    issues = _get("/repos/%s/%s/issues" % (owner, name),
                  {"state": "open", "per_page": 20}) or []
    pulls = _get("/repos/%s/%s/pulls" % (owner, name),
                 {"state": "open", "per_page": 20}) or []
    return {"repo": repo, "issues": issues, "pulls": pulls}


def build(fetched, owner_hint):
    """Turn what GitHub gave us into the four records the coding agent reads.

    The shapes have to match core/vault.py exactly - id, kind, title, date at
    the top of each record - because list_records prints those three fields
    and read_record addresses the file by that id."""
    repos, issues, pulls, notes = [], [], [], []

    for got in fetched:
        r = got["repo"]
        full = r.get("full_name") or ""
        # GitHub returns pull requests from the ISSUES endpoint as well. They
        # carry a `pull_request` key. Filtered here rather than at fetch time
        # so that build() is correct whatever it is handed - counting them as
        # issues is the classic way to report twice as many open issues as the
        # repository actually has, and it would be reported identically by a
        # caller that had already filtered and one that had not.
        mine = [i for i in got["issues"] if not i.get("pull_request")]
        repos.append({
            "name": full,
            "language": r.get("language") or "unknown",
            "stars": r.get("stargazers_count", 0),
            "openIssues": len(mine),
            "openPrs": len(got["pulls"]),
            "defaultBranch": r.get("default_branch") or "main",
            "pushedAt": _day(r.get("pushed_at")),
            "description": (r.get("description") or "").strip() or "No description.",
        })

        for i in mine:
            issues.append({
                "number": i.get("number"),
                "repo": full,
                "title": i.get("title") or "(untitled)",
                "labels": [l.get("name") for l in (i.get("labels") or [])
                           if isinstance(l, dict)],
                "state": i.get("state") or "open",
                "opened": _day(i.get("created_at")),
                "comments": i.get("comments", 0),
                "body": " ".join((i.get("body") or "").split())[:600]
                        or "(no description)",
            })
            notes.append({
                "at": i.get("created_at") or "",
                "repo": full, "type": "issue",
                "subject": "Issue #%s" % i.get("number"),
                "note": "Opened by %s." % ((i.get("user") or {}).get("login") or "someone"),
            })

        for p in got["pulls"]:
            pulls.append({
                "number": p.get("number"),
                "repo": full,
                "title": p.get("title") or "(untitled)",
                "author": (p.get("user") or {}).get("login") or "unknown",
                "state": p.get("state") or "open",
                "draft": bool(p.get("draft")),
                "opened": _day(p.get("created_at")),
                "reviewers": [u.get("login") for u in
                              (p.get("requested_reviewers") or [])
                              if isinstance(u, dict)],
                "body": " ".join((p.get("body") or "").split())[:600]
                        or "(no description)",
            })
            notes.append({
                "at": p.get("created_at") or "",
                "repo": full, "type": "pull_request",
                "subject": "PR #%s" % p.get("number"),
                "note": "Opened by %s." % ((p.get("user") or {}).get("login") or "someone"),
            })

    notes.sort(key=lambda n: n["at"], reverse=True)
    today = max([r["pushedAt"] for r in repos] or [""]) or ""

    return [
        {"id": "repos", "kind": "repos",
         "title": "Repositories for %s" % owner_hint, "date": today,
         "owner": owner_hint, "repos": repos},
        {"id": "issues", "kind": "issues",
         "title": "Open issues", "date": today, "issues": issues},
        {"id": "pull-requests", "kind": "pull-requests",
         "title": "Open pull requests", "date": today, "pullRequests": pulls},
        {"id": "notifications", "kind": "notifications",
         "title": "Recent GitHub activity", "date": today,
         "notifications": notes[:20]},
    ]


def merge_out(records, dry_run):
    """Write only the `coding` key. Everything else in the file is somebody
    else's snapshot and must survive this run untouched."""
    seed = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, "r", encoding="utf-8") as f:
                seed = json.load(f) or {}
        except (OSError, ValueError):
            seed = {}
    seed.setdefault("_readme",
                    "Snapshots for the CastleKeep vault, written by the "
                    "scripts in workshop/. Each script owns one key and "
                    "leaves the others alone. Participants never run them.")
    seed["coding"] = records
    if dry_run:
        print("\n  --dry-run, nothing written. Would write the coding key of %s\n" % OUT)
        return
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(seed, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("\n  Wrote the coding key of %s" % OUT)
    print("  Commit it. Delete vault\\ on any machine to pick it up.")


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--repo", action="append", default=[], metavar="OWNER/NAME",
                    help="a public repository. Repeat for more than one.")
    ap.add_argument("--owner", default=None,
                    help="what the records should call the account. "
                         "Defaults to the owner of the first repository.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.repo:
        print("  Give it at least one --repo OWNER/NAME.")
        print("  Use repositories you own, or well-known public ones.")
        return 2

    print("  Reading the public GitHub API%s"
          % ("" if not os.environ.get("GITHUB_TOKEN") else ", with GITHUB_TOKEN"))
    fetched = []
    for full in args.repo:
        got = fetch_repo(full)
        if not got:
            continue
        print("    %-34s %d issues, %d pulls"
              % (full, len(got["issues"]), len(got["pulls"])))
        fetched.append(got)

    if not fetched:
        print("\n  Nothing fetched. The coding seed is unchanged.")
        return 1

    owner = args.owner or (args.repo[0].partition("/")[0])
    records = build(fetched, owner)

    if args.dry_run:
        for r in records:
            n = len(r.get("repos") or r.get("issues") or
                    r.get("pullRequests") or r.get("notifications") or [])
            print("    %-16s %d entries" % (r["id"], n))
    merge_out(records, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
