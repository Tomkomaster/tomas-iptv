# EPG pin validation record

Pinned revision: `15965406e3d950433788a085a15ab256a8e0035d`

Validation on 2026-08-12 used the exact commit SHA, not a branch or tag. The runner:

- fetched the exact SHA into a fresh repository;
- verified `git rev-parse HEAD` exactly matched the configured pin;
- completed `npm ci`;
- prepared the Tomas IPTV country-aware EPG channel list;
- ran the IPTV-org `grab` command with the generated channel list;
- produced valid XMLTV output.

Observed result: 59 XMLTV channels, 9,137 programmes, 4,318,764 bytes.

This record is informational. The regression test and production workflow remain the enforcement mechanisms.
