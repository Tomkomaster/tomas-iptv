from pathlib import Path

ROOT = Path.cwd()


def replace_once(rel: str, old: str, new: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match in {rel}, found {count}: {old[:120]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "build.py",
    '''from country_language import (\n    configured_country_codes,\n    configured_language_codes,\n    legacy_country_scope_from_language_token,\n    normalize_country_code,\n    normalize_language_code as normalize_spoken_language_code,\n    normalize_language_codes as normalize_spoken_language_codes,\n    source_country_code,\n    source_language_codes,\n    verified_country_route,\n)\n''',
    '''from country_language import (\n    configured_country_codes,\n    configured_language_codes,\n    country_code_from_tvg_id,\n    legacy_country_scope_from_language_token,\n    normalize_country_code,\n    normalize_language_code as normalize_spoken_language_code,\n    normalize_language_codes as normalize_spoken_language_codes,\n    source_country_code,\n    source_country_mode,\n    source_language_codes,\n    verified_country_route,\n)\n''',
)
replace_once(
    "build.py",
    '''        kind = normalize_source_kind(\n            spec.get("kind"),\n            default="source",\n        )\n\n        country_code = source_country_code(spec, cfg)\n''',
    '''        kind = normalize_source_kind(\n            spec.get("kind"),\n            default="source",\n        )\n\n        country_mode = source_country_mode(spec)\n        country_code = source_country_code(spec, cfg)\n''',
)
replace_once(
    "build.py",
    '''        duplicate_urls = 0\n\n        for entry in entries:\n''',
    '''        duplicate_urls = 0\n        country_derivation_failures = 0\n        out_of_scope_country_entries = 0\n\n        for entry in entries:\n''',
)
replace_once(
    "build.py",
    '''            entry["source"] = name\n            entry["source_kind"] = kind\n            entry_country = (\n                normalize_country_code(str(entry.get("country_code") or ""))\n                or country_code\n            )\n            entry_languages = (\n''',
    '''            entry["source"] = name\n            entry["source_kind"] = kind\n            entry_country = normalize_country_code(\n                str(entry.get("country_code") or "")\n            )\n            if not entry_country and country_mode == "tvg_id":\n                entry_country = country_code_from_tvg_id(\n                    str(entry.get("tvg_id") or "")\n                )\n            if not entry_country:\n                entry_country = country_code\n            entry_languages = (\n''',
)
replace_once(
    "build.py",
    '''                    entry["language_codes"] = identity_languages\n\n            key = channel_key(entry)\n''',
    '''                    entry["language_codes"] = identity_languages\n\n            final_entry_country = normalize_country_code(\n                str(entry.get("country_code") or entry.get("language_code") or "")\n            )\n            if not final_entry_country:\n                country_derivation_failures += 1\n                print(\n                    "WARNING: skipping source entry whose country could not be "\n                    f"derived from tvg-id {entry.get('tvg_id')!r}: {url}",\n                    file=sys.stderr,\n                )\n                continue\n\n            entry["country_code"] = final_entry_country\n            entry["language_code"] = final_entry_country\n\n            if (\n                country_mode == "tvg_id"\n                and final_entry_country not in supported_country_codes\n            ):\n                out_of_scope_country_entries += 1\n                continue\n\n            key = channel_key(entry)\n''',
)
replace_once(
    "build.py",
    '''            "name": name,\n            "kind": kind,\n            "country_code": country_code,\n            "language_codes": list(language_codes),\n''',
    '''            "name": name,\n            "kind": kind,\n            "country_mode": country_mode,\n            "country_code": country_code,\n            "language_codes": list(language_codes),\n''',
)
replace_once(
    "build.py",
    '''            "duplicate_urls_ignored": (\n                duplicate_urls\n            ),\n        })\n''',
    '''            "duplicate_urls_ignored": (\n                duplicate_urls\n            ),\n            "country_derivation_failures": (\n                country_derivation_failures\n            ),\n            "out_of_scope_country_entries": (\n                out_of_scope_country_entries\n            ),\n        })\n''',
)

replace_once(
    ".github/workflows/build-and-publish.yml",
    '''          EPG_EXTERNAL_URL="$(\n            python3 -c '\n          import json\n          from pathlib import Path\n          cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))\n          epg = cfg.get("epg") or {}\n          external = (((epg.get("countries") or {}).get("HU") or {}).get("external") or {})\n          print(str(external.get("url") or "").strip())\n          '\n          )"\n\n          EPG_EXTERNAL_PROVIDER="$(\n            python3 -c '\n          import json\n          from pathlib import Path\n          cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))\n          epg = cfg.get("epg") or {}\n          external = (((epg.get("countries") or {}).get("HU") or {}).get("external") or {})\n          print(str(external.get("provider") or "epgshare01.online").strip())\n          '\n          )"\n\n''',
    '',
)
replace_once(
    ".github/workflows/build-and-publish.yml",
    '''          rm -rf .epg-builder\n          rm -f \\\n            .epg.channels.xml \\\n            .epg-iptv.xml \\\n            .epg-iptv-coverage.json \\\n            .epg-external.download \\\n            .epg-grab.log\n''',
    '''          rm -rf .epg-builder .epg-external\n          rm -f \\\n            .epg.channels.xml \\\n            .epg-iptv.xml \\\n            .epg-iptv-coverage.json \\\n            .epg-grab.log\n''',
)
replace_once(
    ".github/workflows/build-and-publish.yml",
    '''          if [ -n "$EPG_EXTERNAL_URL" ]; then\n            echo "Downloading external EPG source: $EPG_EXTERNAL_PROVIDER"\n            if ! curl \\\n              --fail \\\n              --location \\\n              --silent \\\n              --show-error \\\n              --retry 3 \\\n              --retry-delay 2 \\\n              "$EPG_EXTERNAL_URL" \\\n              -o .epg-external.download; then\n              echo "WARNING: external EPG download failed; continuing with IPTV-org fallbacks only."\n              rm -f .epg-external.download\n            fi\n          fi\n\n          MERGE_ARGS=(\n            --playlist public/tv.m3u\n            --iptv-guide .epg-iptv.xml\n            --iptv-coverage .epg-iptv-coverage.json\n            --external-provider "$EPG_EXTERNAL_PROVIDER"\n            --preferred-iptv-provider mediaklikk.hu\n            --future-days "$EPG_FUTURE_DAYS"\n            --output public/guide.xml\n            --report public/epg-coverage.json\n          )\n\n          if [ -f .epg-external.download ]; then\n            MERGE_ARGS+=(--external .epg-external.download)\n          fi\n\n          python3 epg_merge.py "${MERGE_ARGS[@]}"\n''',
    '''          mkdir -p .epg-external\n          python3 - <<'PY' > .epg-external/sources.tsv\n          import json\n          from pathlib import Path\n\n          cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))\n          for raw_code, raw_country in ((cfg.get("epg") or {}).get("countries") or {}).items():\n              code = str(raw_code or "").strip().upper()\n              country = raw_country if isinstance(raw_country, dict) else {}\n              external = country.get("external") or {}\n              if not isinstance(external, dict):\n                  continue\n              url = str(external.get("url") or "").strip()\n              provider = str(external.get("provider") or "epgshare01.online").strip()\n              if code and url:\n                  print(f"{code}\\t{provider}\\t{url}")\n          PY\n\n          while IFS=$'\\t' read -r code provider url; do\n            [ -n "$code" ] || continue\n            target=".epg-external/${code}.xml.gz"\n            echo "Downloading external EPG source for ${code}: ${provider}"\n            if ! curl \\\n              --fail \\\n              --location \\\n              --silent \\\n              --show-error \\\n              --retry 3 \\\n              --retry-delay 2 \\\n              "$url" \\\n              -o "$target"; then\n              echo "WARNING: external EPG download failed for ${code}; continuing with IPTV-org fallbacks for that country."\n              rm -f "$target"\n            fi\n          done < .epg-external/sources.tsv\n\n          python3 epg_multi_merge.py \\\n            --config config.json \\\n            --iptv-guide .epg-iptv.xml \\\n            --iptv-coverage .epg-iptv-coverage.json \\\n            --external-dir .epg-external \\\n            --preferred-iptv-provider mediaklikk.hu \\\n            --future-days "$EPG_FUTURE_DAYS" \\\n            --output public/guide.xml \\\n            --report public/epg-coverage.json\n''',
)

print("Applied remaining build and publish workflow changes.")
