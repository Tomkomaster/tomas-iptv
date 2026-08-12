# IPTV-org EPG builder revision pin

The production workflow must not execute the moving `master` branch of `iptv-org/epg` directly.

`.github/workflows/build-and-publish.yml` defines a full 40-character commit SHA in `IPTV_ORG_EPG_REV` and fetches that exact revision into `.epg-builder`.

## Why

`npm ci` locks the npm dependency tree inside the EPG repository, but it does not lock which version of the EPG repository itself is used. Building from the latest `master` would allow an upstream commit to change or break production even when this repository had not changed.

Pinning the repository revision makes the EPG builder source reproducible. Normal daily runs continue to use the same upstream code until this repository deliberately updates the SHA.

## Updating the pin

1. Choose a specific commit from `iptv-org/epg`.
2. Replace `IPTV_ORG_EPG_REV` with the full 40-character SHA.
3. Run the repository unit tests and strict playlist build.
4. Validate the EPG path with the pinned revision: fetch the exact SHA, run `npm ci`, prepare the country-aware channel list, run the grab, merge the guide, and validate XMLTV output.
5. Merge the update only after those checks pass.

Do not change the workflow back to `git clone --branch master` or another moving branch/tag.

## Current pin

`15965406e3d950433788a085a15ab256a8e0035d`

This revision was selected from the upstream `master` tip and validated against the Tomas IPTV EPG build path before being merged.
