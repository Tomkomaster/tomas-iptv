# EPG coverage expansion validation

Validated on 2026-08-15.

## Methodology

The comparison below uses the generated `epg-coverage.json` and `epg-health.json` reports at the **playlist `tvg-id` level** so the before and after denominators are identical.

- Baseline: `main` workflow run `31888618546`, commit `99f07dc5763aa76b854306ceca2cdce70d754f24`.
- Updated branch validation: workflow run `31891114701`, commit `e0106a70618aebde7799b7fafbe347b016e84875`.
- Both builds used the pinned `iptv-org/epg` revision `15965406e3d950433788a085a15ab256a8e0035d`.
- The comparison set contains 435 playlist `tvg-id` values in both builds.
- **Mapping coverage** means a playlist `tvg-id` was linked to an EPG source.
- **Actual programme coverage** means the linked channel had current/future programme entries in the generated guide.

The dashboard's logical-channel completeness cards use a different denominator from these `tvg-id` reports. Their percentages should therefore not be compared directly with the table below.

## Overall result

| Metric | Before | After | Change |
| --- | ---: | ---: | ---: |
| Mapped playlist `tvg-id` values | 224/435 (51.5%) | 305/435 (70.1%) | +81, +18.6 pp |
| Channels with current/future programmes | 221/435 (50.8%) | 295/435 (67.8%) | +74, +17.0 pp |
| XMLTV programme entries | 25,312 | 28,433 | +3,121 |

## Actual programme coverage by country

| Country | Before | After | Change |
| --- | ---: | ---: | ---: |
| Hungary | 75/106 (70.8%) | 75/106 (70.8%) | unchanged |
| Slovakia | 36/56 (64.3%) | 36/56 (64.3%) | unchanged net |
| Czechia | 72/81 (88.9%) | 72/81 (88.9%) | unchanged |
| Romania | 32/74 (43.2%) | 33/74 (44.6%) | +1, +1.4 pp |
| Austria | 6/118 (5.1%) | 79/118 (66.9%) | +73, +61.8 pp |

## Mapping coverage by country

| Country | Before | After | Change |
| --- | ---: | ---: | ---: |
| Hungary | 77/106 (72.6%) | 77/106 (72.6%) | unchanged |
| Slovakia | 36/56 (64.3%) | 44/56 (78.6%) | +8, +14.3 pp |
| Czechia | 72/81 (88.9%) | 72/81 (88.9%) | unchanged |
| Romania | 33/74 (44.6%) | 33/74 (44.6%) | unchanged |
| Austria | 6/118 (5.1%) | 79/118 (66.9%) | +73, +61.8 pp |

## Source findings

### Austria

The DACH Pluto guide is the main gain. It supplied **73/73 selected channels with current programme data**, adding 3,032 programme entries with no captured HTTP errors. Of the Austrian IPTV-org mappings prepared from the added sources, 30 were supplied by the conservative unique-name fallback for rows whose provider `xmltv_id` is blank.

`tvheute.at` also worked: the validation fetched current ORF 2 schedules successfully. The final merge continued to select EPGShare for that identity, so `tvheute.at` acts as a functioning additional source/fallback rather than changing the selected-provider count.

`tv.magenta.at` was tested during development but deliberately **removed** from the final configuration. It mapped three selected channels but all programme requests returned HTTP 403 and it contributed no fresh programme data.

### Romania

`programetv.ro` supplied one final fresh gap, `TVRTarguMures.ro@SD`, while EPGShare remained preferred for the overlapping Romanian channels. The provider's selected contribution was 1/1 current with no captured HTTP errors.

### Slovakia

`webtv.sk` increased mapping coverage by eight IDs and supplied current programme data for `TVPovazie.sk@SD`. The source is only partially healthy in the current snapshot: 2/10 selected mapped channels produced programmes and 16 HTTP 404 responses were captured. It is retained because it exposes useful regional mappings, but its health remains visible rather than being treated as fully reliable.

The net Slovak current-programme count is unchanged in this particular before/after snapshot because one newly covered channel was offset by source-time variation for another channel. The important structural gain is the increase from 36 to 44 mapped Slovak IDs.

## Matcher safety rules

The new name fallback is intentionally conservative:

1. Exact `tvg-id` matching remains highest priority.
2. Quality-variant matching (`@SD`, `@HD`, etc.) remains second priority.
3. Name matching is used only after both ID strategies fail.
4. The provider name must normalize to one unique candidate across the configured country-scoped selectors.
5. Name fallback is allowed only when that provider row has a blank `xmltv_id`; a different non-empty provider ID is treated as conflicting identity evidence and is not overridden.
6. Name normalization is exact after case, accents, punctuation/spacing, and trailing quality markers are normalized; it is not fuzzy matching.
7. Multi-market providers can be scoped to one exact `*.channels.xml` file, which is used for the German/DACH Pluto dataset instead of loading every Pluto market.

## Validation

The final branch validation completed successfully with:

- 326 unit/regression tests passing;
- the strict reliable playlist build passing;
- the full pinned IPTV-org EPG grab completing;
- country-aware external merging and the local EPG overlay completing;
- 28,433 programme entries in the resulting guide.

These figures are a time-sensitive EPG snapshot. Provider availability and programme freshness can change between scheduled builds; the project health reports should remain authoritative for ongoing operations.
