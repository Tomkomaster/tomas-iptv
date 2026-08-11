from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# healthcheck.py
path = Path("healthcheck.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from urllib.parse import urljoin, urlparse, urlunparse\n\n\nATTR_RE",
    "from urllib.parse import urljoin, urlparse, urlunparse\n\nfrom health_policy import compile_health_policy, resolve_health_policy\n\n\nATTR_RE",
    "health policy import",
)

apply_start = text.index("def apply_history(\n")
build_start = text.index("def build_report(\n", apply_start)
new_apply = '''def apply_history(
    entry: dict,
    probe: dict,
    previous: dict | None,
    checked_at: str,
) -> dict:
    prior_failures = int((previous or {}).get("consecutive_failures") or 0)
    success = bool(probe.get("success"))
    health_policy = str(entry.get("health_policy") or "normal")
    health_policy_reason = str(entry.get("health_policy_reason") or "")
    health_policy_match = str(entry.get("health_policy_match") or "default")
    event_inactive = health_policy == "event_based" and not success
    actionable_failure = not success and not event_inactive
    previous_checked_at = str((previous or {}).get("checked_at") or "")
    same_check_day = (
        len(previous_checked_at) >= 10
        and len(checked_at) >= 10
        and previous_checked_at[:10] == checked_at[:10]
    )

    if success or not actionable_failure:
        consecutive_failures = 0
    elif same_check_day:
        consecutive_failures = max(prior_failures, 1)
    else:
        consecutive_failures = prior_failures + 1

    if success:
        attention = "healthy" if probe.get("status") == "Online" else "warning"
    elif not actionable_failure:
        attention = "informational"
    elif consecutive_failures >= 3:
        attention = "needs_manual_retest"
    else:
        attention = "warning"

    probe_status = str(probe.get("status") or "HTTP error")
    if event_inactive:
        status = "Event inactive"
        raw_detail = str(
            probe.get("detail") or "Automated probe found no active broadcast."
        ).strip()
        detail = (
            "Event-based stream is currently inactive; this does not count as a "
            "channel failure or build a manual-retest streak. "
            f"Probe result: {probe_status}. {raw_detail}"
        )
        if health_policy_reason:
            detail += f" Policy reason: {health_policy_reason}"
    else:
        status = probe_status
        detail = probe.get("detail", "")

    manual_retest_recommended = actionable_failure and consecutive_failures >= 3

    return {
        "channel": entry.get("channel", ""),
        "playlist_name": entry.get("playlist_name", ""),
        "tvg_id": entry.get("tvg_id", ""),
        "group_title": entry.get("group_title", ""),
        "stream_url": entry.get("stream_url", ""),
        "manual_status": entry.get("manual_status", "Unknown"),
        "health_policy": health_policy,
        "health_policy_reason": health_policy_reason,
        "health_policy_match": health_policy_match,
        "probe_status": probe_status,
        "status": status,
        "success": success,
        "actionable_failure": actionable_failure,
        "attention": attention,
        "consecutive_failures": consecutive_failures,
        "manual_retest_recommended": manual_retest_recommended,
        "startup_seconds": probe.get("startup_seconds"),
        "probe_type": probe.get("probe_type", "Unknown"),
        "redirected": bool(probe.get("redirected")),
        "final_url": probe.get("final_url", entry.get("stream_url", "")),
        "http_status": probe.get("http_status"),
        "request_count": int(probe.get("request_count") or 0),
        "detail": detail,
        "tls_certificate_warning": bool(probe.get("tls_certificate_warning")),
        "tls_certificate_detail": str(probe.get("tls_certificate_detail") or ""),
        "checked_at": checked_at,
        "last_success_at": (
            checked_at if success else (previous or {}).get("last_success_at")
        ),
        "last_failure_at": (
            checked_at if actionable_failure else (previous or {}).get("last_failure_at")
        ),
        "last_inactive_at": (
            checked_at if event_inactive else (previous or {}).get("last_inactive_at")
        ),
    }


'''
text = text[:apply_start] + new_apply + text[build_start:]

build_start = text.index("def build_report(\n")
main_start = text.index("def main() -> None:\n", build_start)
new_build = '''def build_report(
    playlist: Path,
    *,
    previous: dict | None = None,
    health_policy: dict | None = None,
    workers: int = 8,
    timeout: float = 8.0,
    slow_start_seconds: float = 6.0,
    max_segment_tries: int = 2,
    limit: int = 0,
) -> dict:
    entries = read_playlist(playlist)
    if limit > 0:
        entries = entries[:limit]

    policy_default, policy_indexes = compile_health_policy(health_policy)
    for entry in entries:
        policy = resolve_health_policy(
            entry,
            default=policy_default,
            indexes=policy_indexes,
        )
        entry["health_policy"] = str(policy.get("health_policy") or policy_default)
        entry["health_policy_reason"] = str(policy.get("reason") or "")
        entry["health_policy_match"] = str(policy.get("matched_by") or "default")

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    prior_index = previous_by_url(previous)
    results: list[dict | None] = [None] * len(entries)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                probe_stream,
                entry,
                timeout=timeout,
                slow_start_seconds=slow_start_seconds,
                max_segment_tries=max_segment_tries,
            ): index
            for index, entry in enumerate(entries)
        }

        for future in as_completed(futures):
            index = futures[future]
            entry = entries[index]
            try:
                probe = future.result()
            except Exception as exc:
                probe = {
                    "status": "HTTP error",
                    "success": False,
                    "startup_seconds": None,
                    "probe_type": "Unknown",
                    "redirected": False,
                    "final_url": entry.get("stream_url", ""),
                    "http_status": None,
                    "request_count": 0,
                    "detail": f"Unexpected checker error: {exc}",
                    "tls_certificate_warning": False,
                    "tls_certificate_detail": "",
                }

            prior = prior_index.get(
                canonical_stream_url(str(entry.get("stream_url") or ""))
            )
            results[index] = apply_history(entry, probe, prior, checked_at)

    streams = [item for item in results if item is not None]
    status_counts = Counter(item["status"] for item in streams)
    health_policy_counts = Counter(item["health_policy"] for item in streams)
    playable = sum(1 for item in streams if item["success"])
    informational_unavailable = sum(
        1
        for item in streams
        if not item["success"] and not item["actionable_failure"]
    )
    failed = sum(1 for item in streams if item["actionable_failure"])
    manual_retest = sum(1 for item in streams if item["manual_retest_recommended"])
    warnings = sum(1 for item in streams if item["attention"] == "warning")
    informational = sum(1 for item in streams if item["attention"] == "informational")

    return {
        "schema_version": 2,
        "generated_at": checked_at,
        "advisory_only": True,
        "manual_testing_authority": (
            "Automated results never replace VLC + Samsung verification and never "
            "change audit.json or stable-playlist decisions automatically."
        ),
        "policy": {
            "failure_1": "warning",
            "failure_2": "warning",
            "failure_3_plus": "needs manual retest",
            "automatic_rejection": False,
            "event_based": (
                "A failed automated probe for an explicitly event_based stream is "
                "reported as Event inactive, remains success=false, but is informational: "
                "it does not build a failure streak or recommend a manual retest."
            ),
            "tls_certificate_retry": (
                "Certificate-verification failures may be retried without certificate "
                "verification only to classify advisory playability; a successful retry "
                "is reported as TLS certificate warning and is never manual verification."
            ),
        },
        "settings": {
            "workers": max(1, workers),
            "timeout_seconds": timeout,
            "slow_start_seconds": slow_start_seconds,
            "max_segment_tries": max_segment_tries,
        },
        "summary": {
            "total": len(streams),
            "playable": playable,
            "failed": failed,
            "informational_unavailable": informational_unavailable,
            "warnings": warnings,
            "informational": informational,
            "needs_manual_retest": manual_retest,
            "health_policy_counts": dict(sorted(health_policy_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "streams": streams,
    }


'''
text = text[:build_start] + new_build + text[main_start:]

main_start = text.index("def main() -> None:\n")
guard_start = text.index('if __name__ == "__main__":\n', main_start)
new_main = '''def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Advisory health checker for stable IPTV streams. HLS checks fetch "
            "the manifest, resolve a media playlist, and read bytes from a real segment."
        )
    )
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--playlist", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--previous-url")
    parser.add_argument("--health-policy", type=Path)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--slow-start", type=float)
    parser.add_argument("--max-segment-tries", type=int)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-previous", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    health_cfg = config.get("health") or {}

    if health_cfg.get("enabled") is False:
        print("Automated stream health checking is disabled in config.json.")
        return

    playlist = args.playlist or Path(
        str(config.get("output") or "public/tv.m3u")
    )
    output = args.output or Path(
        str(health_cfg.get("output") or "public/health.json")
    )
    previous_url = (
        args.previous_url
        if args.previous_url is not None
        else str(health_cfg.get("previous_url") or "")
    )
    health_policy_path = args.health_policy or Path(
        str(health_cfg.get("policy_file") or "health_policy.json")
    )
    health_policy = (
        json.loads(health_policy_path.read_text(encoding="utf-8-sig"))
        if health_policy_path.is_file()
        else {}
    )
    workers = args.workers or int(health_cfg.get("workers") or 8)
    timeout = args.timeout or float(health_cfg.get("timeout_seconds") or 8)
    slow_start = args.slow_start or float(health_cfg.get("slow_start_seconds") or 6)
    max_segment_tries = args.max_segment_tries or int(
        health_cfg.get("max_segment_tries") or 2
    )

    previous = None if args.no_previous else load_json_url(previous_url)
    report = build_report(
        playlist,
        previous=previous,
        health_policy=health_policy,
        workers=workers,
        timeout=timeout,
        slow_start_seconds=slow_start,
        max_segment_tries=max_segment_tries,
        limit=max(0, args.limit),
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\\n",
        encoding="utf-8",
    )

    summary = report["summary"]
    print(
        "Stream health: "
        f"{summary['playable']}/{summary['total']} playable, "
        f"{summary['failed']} actionable failures, "
        f"{summary['informational_unavailable']} event-based inactive, "
        f"{summary['needs_manual_retest']} need manual retest."
    )
    for status, count in summary["status_counts"].items():
        print(f"- {status}: {count}")


'''
text = text[:main_start] + new_main + text[guard_start:]
path.write_text(text, encoding="utf-8")


# attention.py
path = Path("attention.py")
text = path.read_text(encoding="utf-8")
old = '''    for stream in health.get("streams", []) or []:
        if not isinstance(stream, dict) or truthy(stream.get("success")):
            continue

        url = str(stream.get("stream_url") or "").strip()
'''
new = '''    for stream in health.get("streams", []) or []:
        if not isinstance(stream, dict) or truthy(stream.get("success")):
            continue
        if (
            stream.get("actionable_failure") is False
            or str(stream.get("attention") or "").strip().casefold() == "informational"
        ):
            continue

        url = str(stream.get("stream_url") or "").strip()
'''
text = replace_once(text, old, new, "attention actionable failure guard")
path.write_text(text, encoding="utf-8")


# build.py dashboard
path = Path("build.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    playlist membership automatically. Three consecutive automated failures only recommend
    a manual retest.
''',
    '''    playlist membership automatically. Three consecutive automated failures on normal 24/7
    streams only recommend a manual retest. Explicit event-based streams may be reported as
    informationally inactive outside broadcast hours without building a failure streak.
''',
    "dashboard health explanation",
)
text = replace_once(
    text,
    '''      <option value="failed">Failed</option>
      <option value="needs_manual_retest">Needs manual retest</option>
''',
    '''      <option value="failed">Actionable failures</option>
      <option value="Event inactive">Event inactive</option>
      <option value="needs_manual_retest">Needs manual retest</option>
''',
    "dashboard health filters",
)
text = replace_once(
    text,
    "|| (status === 'failed' && row.dataset.healthSuccess === 'no')\n",
    "|| (status === 'failed' && row.dataset.healthActionable === 'yes')\n",
    "dashboard failed filter",
)
text = replace_once(
    text,
    '''    <div class="card"><div class="value">${{summary.failed ?? 0}}</div><div class="label">Failed this check</div></div>
    <div class="card"><div class="value">${{summary.needs_manual_retest ?? 0}}</div><div class="label">Needs manual retest</div></div>
''',
    '''    <div class="card"><div class="value">${{summary.failed ?? 0}}</div><div class="label">Actionable failures</div></div>
    <div class="card"><div class="value">${{summary.informational_unavailable ?? 0}}</div><div class="label">Event-based inactive</div></div>
    <div class="card"><div class="value">${{summary.needs_manual_retest ?? 0}}</div><div class="label">Needs manual retest</div></div>
''',
    "dashboard health summary",
)
text = replace_once(
    text,
    '''    const autoClass = item.manual_retest_recommended
      ? 'rejected'
      : (item.status === 'Online'
          ? 'verified'
          : (item.status === 'Redirected' ? 'tv' : 'review'));
    const failureSuffix = item.success
      ? ''
      : ` ×${{item.consecutive_failures || 1}}`;
''',
    '''    const autoClass = item.manual_retest_recommended
      ? 'rejected'
      : (item.attention === 'informational'
          ? 'base'
          : (item.status === 'Online'
              ? 'verified'
              : (item.status === 'Redirected' ? 'tv' : 'review')));
    const failureSuffix = item.actionable_failure
      ? ` ×${{item.consecutive_failures || 1}}`
      : '';
''',
    "dashboard health badge",
)
text = replace_once(
    text,
    '''      <tr data-health-status="${{healthEsc(item.status)}}" data-health-success="${{item.success ? 'yes' : 'no'}}" data-health-attention="${{healthEsc(item.attention)}}">
''',
    '''      <tr data-health-status="${{healthEsc(item.status)}}" data-health-success="${{item.success ? 'yes' : 'no'}}" data-health-actionable="${{item.actionable_failure ? 'yes' : 'no'}}" data-health-attention="${{healthEsc(item.attention)}}">
''',
    "dashboard health actionable data",
)
path.write_text(text, encoding="utf-8")
