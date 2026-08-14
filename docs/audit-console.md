# Local manual testing console

The local audit console replaces routine hand-editing of `audit.json` while keeping the public GitHub Pages dashboard read-only.

## What it does

The console reads the latest generated `public/report.json`. The build already exposes one audit row per current stream URL, including feeds that have never been manually audited.

For each exact stream URL, the normal testing screen lets you record:

- VLC playback result and note;
- Samsung playback result and note;
- observed spoken language(s);
- general notes.

Saving updates the matching exact-URL row in `audit.json`. Existing manual fields that are outside the console's scope, such as an explicit decision, output-country override or exclusion flag, are preserved.

Before a write, the previous `audit.json` is copied to `audit.json.bak`.

## Source information

Playback testing cannot tell whether a stream is an official broadcaster feed, a broadcaster CDN URL or a provider relay. For that reason source classification is not part of the normal test workflow.

An optional **More details** section shows:

- where the candidate was discovered;
- the stream URL host;
- the currently saved provenance;
- an optional known source type.

The known source type defaults to **Unknown**. Leave it there unless the source was separately researched and confirmed.

Selecting **Unknown** does not replace useful existing provenance. For example, `IPTV-org source (manual playback review)` remains preserved as discovery evidence. Only a positive confirmed classification such as **Official broadcaster**, **Broadcaster CDN** or **Provider relay** replaces provenance through this optional control.

## Windows usage

From the repository folder, first create a fresh local build so `public/report.json` represents the current candidates:

```powershell
py build.py
```

Then start the console:

```powershell
py -m tools.audit_console
```

It opens the default browser at:

```text
http://127.0.0.1:8765/
```

The server binds only to the local loopback interface. It is not exposed to the LAN or internet.

Stop it with `Ctrl+C` in the terminal.

To use another port:

```powershell
py -m tools.audit_console --port 8877
```

To start it without automatically opening the browser:

```powershell
py -m tools.audit_console --no-browser
```

## Queue modes

### Pending tests

This is the default and is intended for normal testing. A current stream stays in this queue while any of these are true:

- no exact-URL audit exists;
- VLC has not been tested;
- Samsung has not been tested;
- observed language has not been confirmed.

A failed playback result still counts as a completed test. For example, `generic_error` is a real Samsung test result and does not keep the feed pending merely because playback failed.

### Build: needs review

Shows current streams whose most recent generated build decision is `Needs review`.

### All current

Shows every current stream so an existing exact-URL audit can be reviewed or edited.

All modes can be filtered by country.

## Recommended workflow

1. Add or discover a candidate feed.
2. Run `py build.py`.
3. Start `py -m tools.audit_console`.
4. Test the shown exact URL in VLC.
5. Test the same exact URL on Samsung.
6. Confirm the spoken language.
7. Add notes when useful.
8. Ignore source type unless it has been separately researched.
9. Click **Save & next**.
10. When the testing session is finished, run the normal strict build/tests before committing the changed `audit.json`.

The console deliberately does not change automated health/EPG telemetry and does not make the public dashboard writable.
