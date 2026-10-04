# iPad + GitHub Actions Setup

This version is intended to run in GitHub Actions. You do not need Python on your iPad.

## One-time setup

1. Create a new private GitHub repository, for example `lunarcrush-breakout-radar`.
2. Upload **the contents of this folder** to the repository, including the hidden `.github` folder.
3. In the repository, open:
   **Settings → Secrets and variables → Actions → New repository secret**
4. Name the secret exactly:
   `LUNARCRUSH_API_KEY`
5. Paste your LunarCrush API key as the secret value and save it.
6. Open the repository's **Actions** tab.
7. Select **LunarCrush Breakout Radar**.
8. Tap **Run workflow** for the first test.

Never put the LunarCrush key in a Python file, config file, issue, commit, or chat.

## Automatic schedule

The workflow is configured for 8:15 AM America/New_York every day.

GitHub scheduled workflows can be delayed during periods of heavy load, so this should be treated as a daily batch job rather than an exact-to-the-minute alert.

## On-demand scan

From the GitHub repository on iPad:

**Actions → LunarCrush Breakout Radar → Run workflow → Run workflow**

You can optionally change the number of finalists from 15.

## Where results appear

After a successful run:

- `reports/breakout_radar.csv` — latest ranked radar
- `reports/breakout_radar.json` — latest machine-readable radar
- `reports/archive/` — dated copies
- `data/` — cached universe and historical coin files

The workflow also publishes a downloadable GitHub Actions artifact for each run.

## API protection

The Python client enforces:
- 10 requests/minute
- 2,000 requests/day
- automatic local usage tracking
- clear errors for 429 rate-limit and 402 plan-gating responses

## First run

The first run may take several minutes because the scanner deliberately spaces LunarCrush requests to stay within the Light-plan 10 requests/minute limit.

## Backtest

After a successful scan, open Actions → LunarCrush Backtest → Run workflow. Use default horizon 14 and threshold 25; download the CSV artifact. See README for research limitations.

Your existing repository is public. Generated reports and cached data committed by the workflow will be public. The API key stays in Actions secrets.
