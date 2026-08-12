# Source concentration reliability

`public/source-concentration.json` is generated from the exact stable entries
that are published to `tv.m3u`. It answers a different question from per-stream
health: how much of a country can fail at once if one hostname or relay disappears?

## Source taxonomy

The report reuses `feed_quality.py` provenance evidence instead of maintaining a
second classifier:

- **Official broadcaster** — explicitly marked direct/official broadcaster source.
- **Broadcaster CDN** — explicitly marked broadcaster-owned/operated CDN path.
- **Third-party relay** — explicitly marked or recognized provider relay; this is
  the same condition that receives the feed-quality relay penalty.
- **Unclassified** — no safe provenance classification. Unknown is deliberately
  not treated as relay.

If evidence conflicts, Third-party relay wins the display classification, then
Broadcaster CDN, then Official broadcaster. Scoring still preserves all underlying
signals for backward compatibility.

## Concentration warnings

Every hostname is counted by country and gets a share of that country's stable
channels. Default alert thresholds apply only to **third-party relay channels on
the same hostname**:

- warning: at least 5 channels and 15% of the country
- high: at least 10 channels and 20% of the country
- critical: at least 20 channels and 30% of the country

Both the count and percentage threshold must be met. Broadcaster CDN concentration
is still visible in the dashboard/table, but is not labeled as third-party relay
risk. Thresholds can be overridden with a top-level `source_concentration` object
in `config.json`.

## Needs-attention integration

`attention.py` also consumes `public/source-concentration.json` and combines it
with the current audit rows. This produces two reliability signals:

- **`relay_concentration`** — one host-level attention item for every relay
  concentration flag. A source-concentration `warning` maps to medium attention,
  `high` maps to high, and `critical` remains critical. The item also says how
  many affected stable channels currently lack an independent verified backup.
- **`no_independent_backup`** — a channel-level signal for a stable third-party
  relay feed when no other current `Verified` or `TV verified` URL for the same
  logical channel exists on another hostname.

A second verified URL on the **same hostname does not count as independent
redundancy**. A verified URL on another hostname does, regardless of whether it is
currently selected as the stable winner. Unverified, rejected, excluded, and
historical-only URLs never count as backups.

For relay channels on a hostname that is already concentration-flagged, missing
an independent backup is high priority. A lone third-party relay without an
independent backup is still shown as a medium-priority fragility signal even when
the hostname is below the concentration thresholds.

The attention output includes summary counts for relay stable channels, channels
with an independent verified hostname, and channels without one. Individual
fragile channel items also expose `stable_hostname`,
`verified_backup_hostnames`, and `redundancy_status` fields. These fields are the
foundation for a future broader redundancy grade such as Excellent / Good /
Fragile without changing manual verification authority.
