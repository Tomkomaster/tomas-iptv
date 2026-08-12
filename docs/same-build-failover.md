# Same-build verified-feed failover

Tomas IPTV can automatically choose a working alternative during the same build when a logical channel has more than one feed that was already manually confirmed as TV-safe.

## Safety boundary

Automated probing does **not** verify streams.

A feed is eligible for same-build failover only when all of these are true:

- it is a current candidate;
- it is not explicitly excluded;
- its saved manual decision is exactly `Verified` or `TV verified`;
- the same logical channel has at least one other current manually TV-safe feed.

`Needs review`, `PC only`, `Rejected`, excluded and historical-only feeds are never admitted to the failover probe set and therefore can never be promoted by automation.

## Build flow

`reliable_build.py` orchestrates the production build:

1. run the normal strict builder to collect current sources, identities and audit rows;
2. read the generated `public/audit.csv`;
3. identify logical channels with two or more current `Verified` / `TV verified` feeds;
4. probe only those redundant safe alternatives using the existing HLS/direct-stream health probe;
5. write `public/same-build-health.json` as transparent selection-only evidence;
6. rerun the normal builder with today's probe evidence layered over the previous deployed health evidence;
7. publish the final stable winner for each logical channel;
8. run the ordinary post-build `healthcheck.py` against the final stable playlist as before.

Nothing from the first pass is published separately; the second pass overwrites the generated playlist/report files before GitHub Pages upload.

## Selection rule

Current playability is considered before the existing quality score.

For manually TV-safe alternatives:

- a feed that is playable in the current build outranks an alternative whose current probe failed;
- when both feeds are playable, the existing weighted feed-quality score decides;
- when both feeds fail, both receive the same selection guard, so the existing quality score still decides and the channel is not automatically removed;
- when a previously failed feed works again on a later build, the guard disappears and it can become the winner again if its quality score is higher.

This means an official broadcaster/CDN feed can automatically regain priority after recovery, while a working verified backup can take over immediately during an outage.

## Why the selection guard is stronger than the ordinary health penalty

The normal feed-quality score intentionally uses a moderate historical health penalty. That is appropriate when yesterday's health report is only one piece of evidence.

Same-build failover has a different question: if two feeds are already manually TV-safe and one of them demonstrably failed the current probe while the other is playable now, the playable feed should win even if the failed feed has a much better provenance score.

The same-build selector therefore applies a temporary negative guard larger than the maximum possible configured quality-score spread to feeds that failed the current probe. The guard affects only this build's selection and never changes `audit.json` or manual verification state.

## Failure semantics

Expected network/playback failures are usable same-build evidence. Unexpected internal probe errors are recorded as `usable_evidence=false` and do not affect selection.

If there is no redundant manually verified alternative for a channel, same-build failover does nothing for that channel. The existing stable selection remains authoritative and the normal health/attention pipeline reports its condition afterward.

## Reports

`public/same-build-health.json` is marked:

```json
{
  "selection_only": true
}
```

It records only the redundant manually TV-safe feeds considered for automatic failover and explicitly states that automated probing cannot create verification or broaden stable-playlist eligibility.
