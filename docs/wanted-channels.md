# Wanted channel catalog

`wanted_channels.json` is the explicit coverage wish list for Tomas IPTV.

The research pipeline previously knew only about channels that had already appeared in `audit.csv`. That meant a channel with no IPTV-org entry, no local extra and no audit history could not appear in `missing.csv` at all.

The wanted catalog fixes that gap.

## Schema

```json
{
  "schema_version": 1,
  "channels": [
    {
      "country_code": "SK",
      "channel": "TA3",
      "tvg_id": "TA3.sk",
      "priority": "P1",
      "reason": "Major national news channel."
    }
  ]
}
```

Fields:

- `country_code` — required two-letter publication geography.
- `channel` — required human-readable channel name.
- `tvg_id` — optional but recommended when known; matching prefers this exact normalized identity.
- `priority` — optional `P1` to `P5`. When present it overrides the generic `research_priority.json` result for that wanted target.
- `reason` — optional explanation for the explicit wanted priority.
- `notes` — optional catalog notes.

Duplicate country/name identities and duplicate country/`tvg_id` identities are rejected.

## Matching and status

Wanted targets are matched to audit history deterministically:

1. exact normalized `country_code` + `tvg_id` when a wanted `tvg_id` is present;
2. otherwise exact normalized `country_code` + channel name;
3. ambiguous name matches fail instead of guessing.

The resulting coverage state follows the existing research model:

- stable current feed → `WORKING` and therefore absent from `missing.csv`;
- current unverified candidate → `CANDIDATES TO TEST`;
- partially compatible feed → `PARTIAL`;
- only rejected/historical feeds → `NO WORKING FEED`;
- no audit/source history at all → `NOT RESEARCHED` with `Find first candidate`.

A completely unseen wanted channel is synthesized into `missing.csv` with zero known/tested feeds, which makes the previously unreachable `NOT RESEARCHED` state useful.

## Backwards-compatible queue behavior

`missing.csv` remains the broader research work queue for channels already encountered by the project. Wanted targets are additive rather than filtering that backlog away.

The export adds a `wanted` column so explicit coverage targets are distinguishable, and wanted rows sort ahead of incidental rows within the same priority tier.

This preserves the existing research backlog while allowing Tomas IPTV to track channels it actively wants even before a feed has ever been found.
