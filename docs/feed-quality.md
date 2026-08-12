# Stable feed quality scoring

When more than one manually TV-safe URL exists for the same logical channel, the stable family playlist chooses the feed with the highest quality score instead of relying mainly on source order.

The safety gate is unchanged: only feeds whose manual audit decision is `Verified` or `TV verified` can compete for stable publication. `PC only`, `Needs review`, `Rejected`, explicitly excluded and test-only feeds never become stable merely because they score well.

## Default weights

| Signal | Points |
| --- | ---: |
| Samsung works | +100 |
| VLC works | +60 |
| VLC works with warning | +50 |
| Official broadcaster source | +50 |
| Broadcaster CDN | +30 |
| HTTPS | +20 |
| Current EPG programme data | +20 |
| 1080p-or-better source | +10 |
| Recent manual test | +10 |
| Redirect | -15 |
| TLS certificate warning | -25 |
| Provider relay | -30 |
| Health warning/failure | -40 |
| Stale manual test | -50 |
| Event-only / Not 24/7 | -80 |

The values live under `stable_playlist.feed_quality.weights` in `config.json`, so the policy is editable without changing Python code.

Compatibility deliberately outweighs resolution. A 1080p annotation is only worth +10, while working on Samsung is +100 and working in VLC is another +60.

## Evidence

Manual playback remains authoritative. The selector may use the previous deployed `health.json`, `epg-coverage.json` and `epg-health.json` as optional historical evidence because the current build selects the stable playlist before the new health and EPG jobs run.

If any previous report cannot be downloaded, selection continues without that optional evidence. A network/report failure must never invalidate an otherwise good manual build.

Health evidence is matched by exact canonical stream URL. EPG evidence is matched by exact `tvg-id`.

## Source classification

Broadcaster and provider-relay hints are intentionally conservative and configurable. The default policy recognizes provenance/source text such as broadcaster streams/CDNs and common relay providers already present in this project (Antik, Panaccess, LexaNetwork, Rebit and Kabelko).

## Transparency

The selected stable feed keeps `feed_quality_score` and `feed_quality_summary` in `channels.csv` and `report.json`. When another verified alternative loses, `excluded.csv` records the winner and loser scores.

Source order remains only the final tie-breaker when two feeds receive the same quality score.
