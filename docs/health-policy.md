# Automated stream health policy

`health_policy.json` controls whether an automated probe failure should build the normal daily failure streak.

Manual VLC + Samsung verification remains authoritative. The health policy only changes how automated failures are interpreted.

## Policies

- `normal` — default for ordinary 24/7 channels. Automated failures remain warnings, build a daily failure streak, and recommend a manual retest after three failed days.
- `event_based` — for streams that legitimately exist only while an event is being broadcast. A failed automated probe is reported as `Event inactive`, remains visible in `health.json`, and is informational rather than actionable.
- `manual_tv_verified` — for an exact stream that was recently confirmed working on the family/Samsung TV but cannot be validated by VLC or the automated PC-style probe. The raw probe failure stays visible, but it is informational and does not create a false outage/retest loop.

For an `event_based` inactive or `manual_tv_verified` probe-failure result:

- `success` remains `false` because the stream was not playable at check time;
- `actionable_failure` is `false`;
- `consecutive_failures` is reset to `0`;
- `manual_retest_recommended` is `false`;
- the unified Needs Attention queue does not create a stream-failure signal;
- the raw probe result is preserved in `probe_status` and `detail`.

This avoids pretending that an inactive/event stream or a PC-incompatible stream passed the automated probe while also avoiding a false dead-channel alarm. `manual_tv_verified` should only be used after a dated manual TV check and should be removed if that manual evidence becomes stale or playback stops working on the TV.

## Matching

Policy entries use one exact selector only, checked in this order:

1. exact canonical `stream_url`;
2. exact `tvg_id`;
3. exact channel name.

There is no fuzzy matching. Invalid policies, duplicate selectors, and entries containing more than one selector are rejected.

The initial policy classifies `Országgyűlés (Plenáris)` (`OrszaggyulesOGYplenaris.hu@SD`) as `event_based` because the parliamentary plenary feed is not expected to broadcast continuously.
