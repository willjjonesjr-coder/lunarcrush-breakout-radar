# Research shortlist reliability (no alerts)

[Refresh current provisional EMA research](../.github/workflows/refresh-provisional-ema-research.yml)
builds a baseline shortlist from the current production scores, verified EMA inventory,
and checked-in [identity seed](../config/provisional_research_seed.json). The workflow
pins the expected completed UTC day once. It does not publish a stale snapshot or
publish a shortlist if it cannot validate the seed.

The baseline uses no historical artifact downloads and no market data calls. Known
price and identity conflicts remain on hold. Fresh verified EMA can still be displayed;
missing provisional EMA stays unevaluated and never controls rank or score eligibility.
Select `score_only` to exercise just this baseline, or leave it off to attempt the
previously corroborated pairs and the alternate spot venue check.

The two historical run ID overrides are optional and must be supplied together. The
workflow verifies their workflow names and conclusions. If the overrides cannot be
read, the default inputs still work. Overrides cannot remove conflict holds from the
pinned baseline. For review, use `combined_shortlist.csv`, `combined_screen_audit.csv`,
and `research_workflow_status.json` together. An optional failure is not a completed
exchange check. This workflow neither promotes assets nor sends production alerts.

## Seed provenance and maintenance

The seed is a projection of two GitHub artifact ZIPs whose SHA-256 digests were checked
against GitHub's artifact metadata:
[original identity](https://github.com/willjjonesjr-coder/lunarcrush-breakout-radar/actions/runs/41746836284/artifacts/13292082440)
and [provisional ranking](https://github.com/willjjonesjr-coder/lunarcrush-breakout-radar/actions/runs/45280254375/artifacts/14869400733).
It keeps the ranking entries and only the identity, decision, and exact pair fields
needed to reproduce their plans. It does not contain market candle series or credentials.
The loader pins the file SHA-256. A PR updating the seed must verify new source
digests, audit any removed holds, and update the pin and regression tests together.
The separate historical ranking rebuild still has its own upstream artifact dependencies.
