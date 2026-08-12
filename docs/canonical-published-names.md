# Canonical published channel names

Stable/public channel names are built from canonical channel identity, not from the research display label that happened to discover the stream.

For single-feed publication, the builder may carry forward only recognized trailing quality/status annotations such as `(576p)`, `(1080p)`, `[Geo-blocked]`, or `[Not 24/7]`.

Adjacent identical recognized annotations are collapsed case-insensitively. For example:

- `Minimax (576p) (576p)` -> `Minimax (576p)`
- `Demo TV (1080p) (1080p)` -> `Demo TV (1080p)`

Different annotations remain intact.

The cleanup deliberately does **not** remove arbitrary words such as `candidate` or `test`. Provider-specific research suffix cleanup remains conservative and separately enumerated in the builder.
