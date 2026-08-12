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

Derived entries whose country is not currently configured in `country_outputs` are ignored rather than mislabeled. When that country is enabled later, the same language source can contribute it without changing the attribution model.

## Expansion examples

- Austria: `country_code=AT`, `language_codes=[deu]`
- Germany: `country_code=DE`, `language_codes=[deu]`
- Serbia: `country_code=RS`, `language_codes=[srp, hun]`
- Romania: `country_code=RO`, `language_codes=[ron, hun]`
- Switzerland: `country_code=CH`, `language_codes=[deu, fra, ita]`

The dashboard and report expose country and spoken-language summaries separately.
