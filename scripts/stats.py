#!/usr/bin/env python3
"""Download stats for the builds on this repo's releases.

GitHub keeps one running total per release file and no history, so each run
appends the totals that changed to stats/history.csv. From those snapshots
this works out, per build: downloads in the last 24 hours and 7 days, and how
many it got while it was the newest build of its platform. Downloads through
the Android "newest" links (weavr-android-latest for builds from main,
weavr-android-dev-latest for dev) are credited to whichever build of that
channel was newest when they happened.

Writes STATS.md (to read on GitHub) and stats/stats.json.

    GH_TOKEN=... GITHUB_REPOSITORY=owner/repo python3 scripts/stats.py
    python3 scripts/stats.py --releases releases.json   # offline, for testing
"""

import argparse
import bisect
import csv
import datetime as dt
import json
import os
import re
import urllib.request
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/London")
HISTORY = "stats/history.csv"
PLATFORMS = [  # tag prefix, label
    ("weavr-ios-", "iOS"),
    ("weavr-appletv-", "tvOS"),
    ("weavr-android-", "Android"),
]
DEV_ANDROID = "Android dev"  # Android builds from dev: tags end in -dev

# Each Android channel's never-changing "newest" link: its release, and the
# file on it whose downloads are credited to that channel's newest build.
NEWEST_LINKS = {
    "Android": ("weavr-android-latest", "weavr-android.apk"),
    DEV_ANDROID: ("weavr-android-dev-latest", "weavr-android-dev.apk"),
}


def fetch_releases(repo, token):
    out, page = [], 1
    while True:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json",
                     **({"Authorization": f"Bearer {token}"} if token else {})})
        with urllib.request.urlopen(req) as r:
            batch = json.load(r)
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def parse_time(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def fmt_time(t):
    t = t.astimezone(LOCAL_TZ)
    return f"{t.day} {t:%b %H:%M %Z}"


def fmt_span(seconds):
    h = seconds / 3600
    if h < 1:
        return f"{int(seconds // 60)}m"
    if h < 48:
        return f"{h:.0f}h"
    return f"{h / 24:.0f}d"


def builds_from(releases):
    """One entry per build, oldest first, with its platform and publish time."""
    builds = []
    for r in releases:
        tag = r["tag_name"]
        if r.get("draft") or tag in {t for t, _ in NEWEST_LINKS.values()}:
            continue
        label = next((l for p, l in PLATFORMS if tag.startswith(p)), "Other")
        if label == "Android" and tag.endswith("-dev"):
            label = DEV_ANDROID
        m = re.search(r"-(\d[\w.]*)-build(\d+)(-dev)?$", tag)
        version = f"{m.group(1)}.{m.group(2)}" if m else tag
        if tag == "weavr-ios-1.0-build9":
            version = "1.0"  # published before versions carried the build number
        for a in r["assets"]:
            builds.append({
                "platform": label,
                "version": version,
                "build": int(m.group(2)) if m else None,
                "tag": tag,
                "file": a["name"],
                "published": parse_time(r["published_at"]),
                "total": a["download_count"],
            })
    builds.sort(key=lambda b: b["published"])
    return builds


def load_history():
    hist = {}
    if os.path.exists(HISTORY):
        with open(HISTORY, newline="") as f:
            for row in csv.DictReader(f):
                hist.setdefault(row["file"], []).append((parse_time(row["time"]), int(row["count"])))
    for v in hist.values():
        v.sort()
    return hist


def append_history(hist, counts, now):
    """Record every file whose total changed since its last snapshot."""
    new = not os.path.exists(HISTORY)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "file", "count"])
        for name, count in sorted(counts.items()):
            if not hist.get(name) or hist[name][-1][1] != count:
                w.writerow([now.strftime("%Y-%m-%dT%H:%M:%SZ"), name, count])
                hist.setdefault(name, []).append((now, count))


def running_total(series):
    """A newest-build link's file is replaced with each new build, and GitHub
    starts its count again from 0. Turn its snapshots into a total that only
    goes up: a drop means a new file, whose count is all new downloads.
    Downloads between the last snapshot and the replacement (under an hour)
    are lost."""
    out, total, prev = [], 0, 0
    for t, c in series:
        total += c - prev if c >= prev else c
        prev = c
        out.append((t, total))
    return out


def count_at(series, t, published):
    """A file's total at time t: its last snapshot at or before t. Before it was
    published it had none. Before the first snapshot of an older file the total
    is unknown, so the first snapshot is used and the result marked approximate."""
    if t <= published:
        return 0, False
    times = [s[0] for s in series]
    i = bisect.bisect_right(times, t)
    if i == 0:
        return (series[0][1] if series else 0), True
    return series[i - 1][1], False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--releases", help="read releases from this JSON file instead of the API")
    args = ap.parse_args()

    if args.releases:
        with open(args.releases) as f:
            releases = json.load(f)
    else:
        releases = fetch_releases(os.environ["GITHUB_REPOSITORY"], os.environ.get("GH_TOKEN"))

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    counts = {a["name"]: a["download_count"] for r in releases for a in r["assets"]}
    hist = load_history()
    append_history(hist, counts, now)

    builds = builds_from(releases)
    windows = {"24h": now - dt.timedelta(hours=24), "7d": now - dt.timedelta(days=7)}

    # When each build stopped being the newest of its platform.
    by_platform = {}
    for b in builds:
        by_platform.setdefault(b["platform"], []).append(b)
    for blist in by_platform.values():
        for b, nxt in zip(blist, blist[1:] + [None]):
            b["superseded"] = nxt["published"] if nxt else None

    # A link made after the stats began had no downloads before it was made.
    created = {r["tag_name"]: parse_time(r["published_at"]) for r in releases}
    start = _history_start()
    link_series = {}
    for p, (tag, f) in NEWEST_LINKS.items():
        series = hist.get(f, [])
        if tag in created and created[tag] > start and series:
            series = [(created[tag], 0)] + series
        link_series[p] = running_total(series)
    for b in builds:
        series = hist.get(b["file"], [])
        end = b["superseded"] or now
        newest_n, approx = count_at(series, end, b["published"])
        b["while_newest"] = newest_n
        b["approx"] = approx
        for k, start in windows.items():
            before, a2 = count_at(series, start, b["published"])
            b[k] = b["total"] - before
            b["approx"] |= a2 and start > b["published"]
        if b["platform"] in NEWEST_LINKS:
            # Credit the "newest" link's downloads to the build that was newest.
            pub = b["published"]
            latest_series = link_series[b["platform"]]
            lo = lambda t: count_at(latest_series, max(t, pub), dt.datetime.min.replace(tzinfo=dt.timezone.utc))[0]
            via_link = lo(end) - lo(pub)
            b["via_latest"] = via_link
            b["total"] += via_link
            b["while_newest"] += via_link
            for k, start in windows.items():
                s = max(start, pub)
                if s < end:
                    b[k] += lo(end) - lo(s)
        live = ((b["superseded"] or now) - b["published"]).total_seconds()
        b["newest_for"] = live
        age_days = (now - b["published"]).total_seconds() / 86400
        b["per_day"] = b["total"] / age_days if age_days >= 1 else None

    # Downloads through the newest-build link before the history began can't be
    # put against a build; they're shown on their own.
    pre_link = {p: (s[0][1] if s else 0) for p, s in link_series.items()}

    write_markdown(builds, now, pre_link)
    with open("stats/stats.json", "w") as f:
        json.dump({
            "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "builds": [{**{k: v for k, v in b.items() if k not in ("published", "superseded")},
                        "published": b["published"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "superseded": b["superseded"].strftime("%Y-%m-%dT%H:%M:%SZ") if b["superseded"] else None}
                       for b in builds],
        }, f, indent=2)
        f.write("\n")


def write_markdown(builds, now, pre_link):
    plats = [l for _, l in PLATFORMS] + [DEV_ANDROID] + (["Other"] if any(b["platform"] == "Other" for b in builds) else [])
    L = ["# Download stats", "",
         f"Updated {fmt_time(now)}, every hour. Counts are GitHub's downloads of each "
         "release file: a reinstall or an update in Feather counts again, and there is "
         "no per-device or per-person breakdown.", ""]

    L += ["## Overview", "",
          "| Platform | Newest build | Published | Last 24h | Last 7 days | All time |",
          "|---|---|---|--:|--:|--:|"]
    for p in plats:
        bl = [b for b in builds if b["platform"] == p]
        if not bl:
            continue
        n = bl[-1]
        extra = pre_link.get(p, 0)
        L.append(f"| {p} | {n['version']} | {fmt_time(n['published'])} | "
                 f"{sum(b['24h'] for b in bl)} | {sum(b['7d'] for b in bl)} | {sum(b['total'] for b in bl) + extra} |")

    for key, title in (("24h", "Last 24 hours"), ("7d", "Last 7 days")):
        rows = sorted((b for b in builds if b[key] > 0), key=lambda b: -b[key])
        L += ["", f"## {title}", ""]
        if not rows:
            L.append("No downloads.")
            continue
        L += ["| Build | Published | Downloads |", "|---|---|--:|"]
        L += [f"| {b['platform']} {b['version']} | {fmt_time(b['published'])} | {b[key]}{'*' if b['approx'] else ''} |"
              for b in rows]

    L += ["", "## Every build", "",
          "Newest first. **Newest for** is how long it was the newest build of its platform; "
          "**While newest** is the downloads in that time. **Per day** shows once a build is a day old.", ""]
    for p in plats:
        bl = [b for b in builds if b["platform"] == p]
        if not bl:
            continue
        L += [f"### {p}", "",
              "| Build | Published | Newest for | While newest | Per day | All time |",
              "|---|---|---|--:|--:|--:|"]
        for b in reversed(bl):
            nf = fmt_span(b["newest_for"]) + ("" if b["superseded"] else " (now)")
            per_day = "–" if b["per_day"] is None else f"{b['per_day']:.1f}"
            L.append(f"| {b['version']} | {fmt_time(b['published'])} | {nf} | "
                     f"{b['while_newest']}{'*' if b['approx'] else ''} | {per_day} | {b['total']} |")
        if p in NEWEST_LINKS:
            L += ["", f"Totals include downloads through the {p} newest-build link "
                  f"(`{NEWEST_LINKS[p][1]}`), credited to the build that was newest at the time."]
            if pre_link.get(p):
                L += ["", f"Plus {pre_link[p]} through that link before the stats "
                      "began, which can't be put against a build (in the overview's All time)."]
        L.append("")

    L += ["\\* Approximate: part of that period is before the stats history, which starts "
          f"{fmt_time(_history_start())}. Downloads from before then are counted as "
          "happening at that point.", ""]
    with open("STATS.md", "w") as f:
        f.write("\n".join(L))


def _history_start():
    with open(HISTORY, newline="") as f:
        rows = list(csv.DictReader(f))
    return parse_time(rows[0]["time"]) if rows else dt.datetime.now(dt.timezone.utc)


if __name__ == "__main__":
    main()
