#!/usr/bin/env python3
"""Add an IPA to apps.json as the newest version of its app.

Reads the IPA's Info.plist for the bundle id, version, build and minimum OS, so
the JSON always matches what is actually in the file. The platform (iOS or
tvOS) comes from the plist too, and picks which app entry the version goes in.

    python3 scripts/add_version.py --ipa weavr-ios-1.0-build12.ipa \
        --url https://github.com/.../weavr-ios-1.0-build12.ipa \
        --notes "What changed"

Run it with no network: it only reads the IPA and rewrites apps.json.
"""

import argparse
import datetime as dt
import json
import os
import plistlib
import re
import sys
import zipfile
from zoneinfo import ZoneInfo

# Which app entry (by "name" in apps.json) each platform's builds go in. Used
# when the IPA's bundle id is not in apps.json yet; that entry's
# bundleIdentifier is then updated to the real one, since Feather matches
# updates by bundle id.
PLATFORM_APP = {"ios": "Weavr iOS", "tvos": "Weavr tvOS"}

# Older versions are kept so a bad build can be rolled back from Feather.
KEEP_VERSIONS = 15

# Commit trailers that end up in notes taken from a commit message. They mean
# nothing to someone reading "What's new" in Feather.
TRAILER = re.compile(r"^(Co-Authored-By|Claude-Session|Signed-off-by):.*$", re.I | re.M)

# "15 Nov 16:25 GMT · " at the start of an app's subtitle: when its newest
# build was published, so Feather's app list shows it beside the version. UK
# time, so it reads BST in summer.
DATE_PREFIX = re.compile(r"^\d{1,2} [A-Z][a-z]{2}( \d{2}:\d{2}( [A-Z]{2,4})?)? · ")
LOCAL_TZ = ZoneInfo("Europe/London")


def clean_notes(text):
    return TRAILER.sub("", text).strip()


def tidy(app):
    """Strip trailers from every version's notes and date the subtitle."""
    for v in app.get("versions", []):
        if "localizedDescription" in v:
            v["localizedDescription"] = clean_notes(v["localizedDescription"])
    base = DATE_PREFIX.sub("", app.get("subtitle", ""))
    versions = app.get("versions", [])
    if versions and versions[0].get("date"):
        d = dt.datetime.strptime(versions[0]["date"], "%Y-%m-%dT%H:%M:%SZ")
        d = d.replace(tzinfo=dt.timezone.utc).astimezone(LOCAL_TZ)
        app["subtitle"] = f"{d.day} {d:%b %H:%M %Z} · {base}"
    else:
        app["subtitle"] = base


def read_info_plist(ipa_path):
    with zipfile.ZipFile(ipa_path) as z:
        names = [
            n for n in z.namelist()
            if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", n)
        ]
        if not names:
            sys.exit(f"{ipa_path}: no Payload/*.app/Info.plist; is this an IPA?")
        return plistlib.loads(z.read(names[0]))


def platform_of(info):
    name = str(info.get("DTPlatformName", "")).lower()
    if name.startswith("appletv"):
        return "tvos"
    if 3 in info.get("UIDeviceFamily", []):
        return "tvos"
    return "ios"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ipa", required=True)
    ap.add_argument("--url", required=True, help="public download URL of the IPA")
    ap.add_argument("--notes", default="", help="release notes shown in Feather")
    ap.add_argument("--source", default="apps.json")
    args = ap.parse_args()

    info = read_info_plist(args.ipa)
    bundle_id = info.get("CFBundleIdentifier")
    version = str(info.get("CFBundleShortVersionString", "")).strip()
    build = str(info.get("CFBundleVersion", "")).strip()
    min_os = str(info.get("MinimumOSVersion", "")).strip()
    platform = platform_of(info)
    if not bundle_id or not version:
        sys.exit("Info.plist is missing CFBundleIdentifier or CFBundleShortVersionString")

    with open(args.source, encoding="utf-8") as f:
        source = json.load(f)

    app = next((a for a in source["apps"] if a["bundleIdentifier"] == bundle_id), None)
    if app is None:
        wanted = PLATFORM_APP[platform]
        app = next((a for a in source["apps"] if a["name"] == wanted), None)
        if app is None:
            sys.exit(f"No app entry for bundle id {bundle_id} or name {wanted!r}")
        print(f"Setting {app['name']} bundleIdentifier: {app['bundleIdentifier']} -> {bundle_id}")
        old = app["bundleIdentifier"]
        app["bundleIdentifier"] = bundle_id
        source["featuredApps"] = [bundle_id if b == old else b for b in source.get("featuredApps", [])]

    entry = {
        "version": version,
        "buildVersion": build,
        "date": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "localizedDescription": clean_notes(args.notes) or f"Weavr {version} (build {build})",
        "downloadURL": args.url,
        "size": os.path.getsize(args.ipa),
    }
    if min_os:
        entry["minOSVersion"] = min_os

    versions = [
        v for v in app.get("versions", [])
        if not (v.get("version") == version and v.get("buildVersion") == build)
    ]
    app["versions"] = ([entry] + versions)[:KEEP_VERSIONS]
    for a in source["apps"]:
        tidy(a)

    with open(args.source, "w", encoding="utf-8") as f:
        json.dump(source, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"{app['name']} ({platform}) {version} build {build} -> {args.url}")


if __name__ == "__main__":
    main()
