# Local Draw Clock Design

## Context

The current draw refresh flow depends too directly on external site responses at the moment a countdown reaches zero. For PC28, the API can temporarily keep returning the previous issue during the opening window. Because that response is structurally valid, the application accepts it as success and can keep the UI on the old issue. Parse failures also get converted into fallback `DrawInfo` values before the UI retry layer sees an exception, so retry behavior is not consistently triggered.

The desired behavior is that the application should not stay on the previous issue once the local countdown reaches zero. It should advance locally, clear current-period statistics immediately, then use external APIs only to confirm and calibrate the schedule.

## Site Intervals

The local schedule uses per-site configured intervals:

| Site | Interval |
| --- | ---: |
| `pc28` | 210 seconds |
| `macao` | 180 seconds |
| `australia` | 180 seconds |
| `norway` | 210 seconds |

For each site, the local clock tracks:

- `current_period`
- `next_period`
- `start_time`
- `next_time`
- `interval_sec`
- `source`, either `api` or `inferred`
- `last_api_success_at`

`next_time` is calculated as:

```text
next_time = start_time + interval_sec
```

## Runtime Behavior

When an API response is healthy, the parser creates a schedule from the response:

- If the response provides an absolute next open time, use it.
- If the response provides only a countdown, derive `next_time = now + countdown`.
- If the response provides neither, derive `next_time = current_time + interval_sec`.
- If the response omits `next_period`, derive it from `current_period + 1`.

When the local countdown reaches zero:

1. Advance the local schedule immediately.
2. Set `current_period` to the previous `next_period`.
3. Set `next_period` to `current_period + 1`.
4. Set `start_time` to the previous `next_time`.
5. Set `next_time = start_time + interval_sec`.
6. Mark the schedule as `source=inferred`.
7. Clear current messages, visual rows, chart layers, realtime bet text, stats, lock state, and cursor for the active site.
8. Start a delayed API calibration request for `next_time + 10 seconds`.

The 10 second delay avoids polling while the external site is still opening or updating its latest issue.

## Retry And Calibration

After local advancement, API calibration runs with bounded retry:

1. First request happens 10 seconds after the local issue transition.
2. If the request fails, parses empty data, or returns an issue older than the local inferred issue, retry after 5 seconds.
3. Retry at most 3 times.
4. If all retries fail, keep the inferred schedule and continue the local clock.
5. Future calibration attempts continue on later transitions, so inferred time never becomes permanent if the API recovers.

If the API returns the same issue as the local schedule, update countdown and timing fields from API values where available.

If the API returns a newer issue than the local schedule, adopt the API issue and clear active statistics if the effective query period changes.

If the API returns an older issue, treat it as stale and do not move the UI backward.

## Drift Control

Local inference can drift if the real site delays opening or changes its schedule. The design bounds drift in three ways:

- Use local inference only to prevent the UI from staying on an old period.
- Mark inferred schedules distinctly from API-confirmed schedules.
- Recalibrate from the API whenever a healthy non-stale response is available.

The application should never compound stale API responses into the local schedule. Stale responses may be logged, but they must not roll back the active period.

## Expected User-Visible Behavior

- At countdown zero, the visible active period advances immediately.
- The right-side chart and realtime bet text clear immediately for the new period.
- API failures during the opening window show retry/fallback status but do not freeze the old issue.
- When the API catches up, displayed timing is corrected without resurrecting previous-period betting rows.

## Test Coverage

Add tests for:

- PC28 local transition advances from current issue to next issue at countdown zero.
- Active chart rows and realtime text are cleared during local transition.
- Calibration request is delayed by 10 seconds rather than submitted immediately at zero.
- Three stale or failed responses keep the inferred issue and continue the clock.
- A later healthy API response recalibrates the schedule.
- Older API issue responses do not roll the app backward.
- Macau and Australia derive missing absolute `next_time` from interval or countdown.
