# Site Persistence and AI Frequency Design

## Goal

Restore the last selected site when the application next opens, prevent the
automatic-bet engine from starting with incomplete AI credentials, and reduce
unnecessary AI skip decisions while retaining an explicit no-bet outcome for
genuinely unsupported periods.

## Persisted Site

`last_selected_site` is stored in the existing settings payload whenever the
user switches a site. During application construction the value is restored
only when it is present in the currently configured site list; otherwise the
normal default selection remains unchanged. Saving the selected site is
independent of query-period overrides, so it does not restore stale manually
entered periods.

## AI Start Validation

`StrategyConfig` owns validation for AI provider, Base URL, model, and API
key. The panel validates before changing to the running state, and the main
window repeats the validation before creating a sender or history store. The
validation error names the missing fields, preventing programmatic callers
from bypassing the UI guard.

## Higher-Frequency AI Decisions

The system prompt retains `skip` for periods with no directional evidence, but
instructs the AI to place a low-confidence `bet` whenever the supplied
quantitative data has a weak but concrete directional edge. The default
confidence gate changes from 65 to 45, while existing saved settings preserve
their chosen threshold. A valid low-confidence bet is still filtered if the
user raises the configurable threshold above it.

## Tests

Regression tests cover saving/restoring a valid site and safely ignoring an
unknown saved site, complete AI configuration validation at both UI and
integration boundaries, the 45 default and saved-value preservation, and the
prompt instruction requiring weak-evidence recommendations rather than an
automatic skip.
