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

## Expansion examples

- Austria: `country_code=AT`, `language_codes=[deu]`
- Germany: `country_code=DE`, `language_codes=[deu]`
- Serbia: `country_code=RS`, `language_codes=[srp, hun]`
- Romania: `country_code=RO`, `language_codes=[ron, hun]`
- Switzerland: `country_code=CH`, `language_codes=[deu, fra, ita]`

The dashboard and report expose country and spoken-language summaries separately.
