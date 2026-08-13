# EPG identity quality

The generated `public/epg-quality.json` measures programme-guide quality at the
**stable logical-channel** level. Alternative feeds of the same station do not
inflate the denominator.

## Dashboard categories

Each stable logical channel appears in exactly one category:

- **Exact tvg-id** — an exact playlist/provider ID match with current/future programmes;
- **Alias** — an explicit hand-maintained alias (including intentional cross-country aliases) with programmes;
- **Guessed** — a deterministic quality-variant or unique-name inference with programmes;
- **Missing** — the stable logical channel has no `tvg-id`;
- **EPG unavailable** — it has a `tvg-id`, but no final mapping or the mapped provider currently has no programmes.

The underlying row also keeps `match_type`, provider, provider XMLTV ID and the
coarser `mapping_quality` (`exact`, `alias`, `guessed`, `unmapped`, `missing`).
This lets future quality logic get stricter without changing the user-facing
five-state dashboard.

## EPG completeness metric

`epg_completeness_percent` deliberately uses **all stable logical channels whose
EPG policy is `expected`** as its denominator. A missing `tvg-id` therefore
counts as incomplete instead of disappearing from the metric. Channels marked
`optional` or `not_expected` in `data/epg_policy.json` do not lower this score.

This is intended to become the next major quality metric after high-priority
stream coverage is largely solved.

## Identity reports

The quality report also exposes:

- `tvg_id_collisions`: two or more distinct logical channels sharing the same
  exact `tvg-id`; multiple feeds of one logical channel do not count;
- `verified_without_epg_mapping`: stable `Verified` / `TV verified` channels
  with no `tvg-id` or with a `tvg-id` that has no final EPG mapping;
- `verified_mapped_without_programmes`: verified channels whose mapping exists
  but currently produces no programme data.

For quick review, the build also publishes:

- `public/tvg-id-collisions.csv`
- `public/verified-without-epg.csv`

All of these files are generated telemetry/reporting output and are not written
back into the manual `audit.json`.
