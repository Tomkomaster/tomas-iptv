# Research priority queue

`public/missing.csv` is the generated work queue for channels that do not yet have a stable TV-safe feed.

Research status and research priority are separate concepts:

- `status` says what is currently known about the feed (`PARTIAL`, `CANDIDATES TO TEST`, `NO WORKING FEED`, ...).
- `priority` says how valuable it is to spend research time on that channel.

## Priority tiers

- **P1 — Major national channels**: highest-value mainstream channels. Work these first.
- **P2 — Major thematic / sports / movie channels**: important genre, sports, movie, kids, news, and entertainment services.
- **P3 — Regional / local channels**: default tier for ordinary local/regional channels and uncategorized services.
- **P4 — Web / niche / low-value channels**: web-only, religious, music/radio, event, parliamentary, or similarly niche services.
- **P5 — Probably not worth pursuing**: webcams, identity-check entries, and similar items where feed hunting is usually a poor use of time.

## Work types

The queue also separates the kind of work required:

- `Finish compatibility` — a feed already works somewhere; finish VLC/Samsung compatibility testing first.
- `Test candidates` — current URLs exist and should be tested before looking for more.
- `Find first candidate` — the channel is known but no source URL has been recorded.
- `Hunt new source` — known candidates are exhausted/rejected and a replacement feed is needed.

## Policy matching

`research_priority.json` is the editable policy. Exact entries are checked before broad rules. Exact matching is scoped by country and can use either `tvg_id` or channel name. Broad `contains_any` rules are evaluated in file order. Anything not explicitly classified falls back to P3.

The policy loader rejects invalid priority values, malformed entries, and duplicate exact selectors instead of guessing.

`missing.csv` is sorted by P1 through P5, then by research status so partial/candidate work appears before blind source hunting inside the same priority tier.
