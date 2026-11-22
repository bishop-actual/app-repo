# Weavr app source

An AltStore-format source for Weavr's iOS and tvOS builds. Add it to Feather
(or any AltStore-compatible signer) to install Weavr and get updates in the app:

```
https://raw.githubusercontent.com/bishop-actual/app-repo/main/apps.json
```

The IPAs are stored as GitHub Release assets on this repo, so nothing goes in
Google Drive and nothing big goes in git.

## How a build gets here

1. Run the **iOS** or **AppleTV** workflow in
   [weavr-apple-mobile](https://github.com/bishop-actual/weavr-apple-mobile/actions),
   with "Publish" ticked. Fill in "What's new" if you like.
2. It builds the unsigned IPA and attaches it to a new release here.
3. That release starts this repo's **Publish** workflow, which reads the IPA's
   `Info.plist` (bundle id, version, build, minimum OS), adds it to the top of
   that app's `versions` in `apps.json`, and commits.
4. Feather shows the update the next time it refreshes the source. GitHub caches
   raw files for about five minutes.

Other ways to publish:

- **By hand on GitHub**: make a release on this repo and attach an `.ipa`.
  The release notes become the "What's new" text.
- **From a link**: Actions → Publish → Run workflow, and paste a direct download
  URL for an IPA. It is copied onto a release here and added the same way. For a
  Google Drive file use
  `https://drive.usercontent.google.com/download?id=<FILE_ID>&confirm=t`;
  the normal share link returns a web page, not the file.

iOS and tvOS builds are told apart by the IPA's `Info.plist`, so each lands in
the right app entry. If a build's bundle id isn't in `apps.json` yet, the entry
for its platform takes it over: Feather matches updates by bundle id.
The last 15 versions of each app are kept so you can roll back.

## Android builds

The Android TV app's builds (bishop-actual/weavr-android-tv, the **Build
Android APK** workflow with "Publish" ticked) are attached to releases here
too, so each one has a lasting direct download link — handy for installing on
a TV. There are two channels, each with a link that never changes for a
Downloader code:

| Channel | Built from | Releases | Newest build, always at |
|---|---|---|---|
| Stable, for everyone | `main` | `weavr-android-<version>-build<n>` | `https://github.com/bishop-actual/app-repo/releases/download/weavr-android-latest/weavr-android.apk` |
| Dev, for testing | `dev` (or any other branch) | `weavr-android-<version>-build<n>-dev`, marked pre-release | `https://github.com/bishop-actual/app-repo/releases/download/weavr-android-dev-latest/weavr-android-dev.apk` |

Feather can't use an APK,
so the Publish workflow skips these releases and they never appear in
`apps.json`. That workflow needs the same `APP_REPO_TOKEN` secret, set on the
Android repo.

## Download stats

**[STATS.md](STATS.md)** shows downloads per build, updated hourly: the last
24 hours, the last 7 days, all time, and how many each build got while it was
the newest of its platform. The Stats workflow keeps the hourly totals in
`stats/history.csv`, since GitHub only keeps a running total per file.

## One-time setup

**In weavr-apple-mobile**, add a repository secret named `APP_REPO_TOKEN`
(Settings → Secrets and variables → Actions). Make it a
[fine-grained token](https://github.com/settings/personal-access-tokens/new)
with access to `bishop-actual/app-repo` only and **Contents: Read and write**.
The default `GITHUB_TOKEN` can't write to another repository, and a release
made with it wouldn't start the Publish workflow either.

**In this repo**, the default branch has to be `main`, since that's the branch
in the source URL and the branch Publish commits to. Settings → Actions →
General → Workflow permissions doesn't need changing: Publish asks for
`contents: write` itself.

## Layout

```
apps.json                  The source
icons/weavr.png            Source and app icon. After replacing it, change the
                           ?v= on its URLs in apps.json, or Feather keeps the old one
scripts/add_version.py     Adds an IPA to apps.json (runs offline)
.github/workflows/publish.yml
```
