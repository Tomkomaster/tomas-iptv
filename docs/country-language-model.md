# Country and spoken-language model

Tomas IPTV separates publication geography from spoken-language evidence.

## Authoritative fields

- `country_code`: ISO-3166-style publication/audit country, e.g. `HU`, `SK`, `CZ`, `AT`.
- `language_codes`: ISO-639-3-style spoken/content languages, e.g. `hun`, `slk`, `ces`, `deu`.
- `playlist_country_code`: country scope to which a saved audit identity belongs.
- `output_country_code`: country output chosen for a current audited stream.
- `expected_language_codes` / `observed_language_codes`: spoken-language evidence.

## Backward compatibility

Historical `language_code`, `playlist_language_code` and `output_language_code` are still accepted. They are treated as legacy country aliases, because that is what the project historically stored in them. Old spoken-language values such as `HU`, `SK`, `CZ`, `Hungarian`, `Slovak` and `Czech` remain accepted and normalize to `hun`, `slk` and `ces`.

## Routing

Language does not globally imply country. A verified cross-country move requires either an explicit `output_country_code` or a configured `verified_country_routes` rule matching both source country and observed language. Current HU/SK/CZ behavior is represented by explicit rules such as `SK + ces -> CZ`; adding Serbia later will not cause an RS Hungarian-language channel to move to HU unless a rule explicitly says so.

## Language-wide upstream sources

IPTV-org language playlists are intentionally country-neutral inputs. They use `country_mode=tvg_id`, so each entry derives geography from its IPTV-org `tvg-id` suffix instead of inheriting a country from the spoken language. For example, a Hungarian-language `PannonRTV.rs@SD` entry is `country_code=RS`, `language_codes=[hun]`, not HU.

Derived entries whose country is not currently configured in `country_outputs` are excluded from the existing shared/country/testing publication universe, but they are retained in an isolated spoken-language catalog. If such an entry is manually verified, it can be published under its real country prefix in a configured `by-language/<iso639-3>.m3u` output without requiring a country playlist first.

For example, `PannonRTV.rs@SD` with `language_codes=[hun]` can appear as `[RS] Pannon RTV` in `by-language/hun.m3u` while no `rs.m3u` exists. Exact URLs already owned by the established country build keep their current country identity in the language catalog, so adding language outputs cannot silently change existing country URL precedence.

## Expansion examples

- Austria: `country_code=AT`, `language_codes=[deu]`
- Germany: `country_code=DE`, `language_codes=[deu]`
- Serbia: `country_code=RS`, `language_codes=[srp, hun]`
- Romania: `country_code=RO`, `language_codes=[ron, hun]`
- Switzerland: `country_code=CH`, `language_codes=[deu, fra, ita]`

The dashboard and report expose country and spoken-language summaries separately.
