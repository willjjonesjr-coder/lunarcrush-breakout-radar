# Sortable radar results

After each scan and fundamentals overlay, production runs `python sortable_report.py` to build `reports/radar_sortable.html`. It is a standalone snapshot: no network access, account, API key, dependencies or web hosting is needed to open it.

In GitHub Actions, open the completed LunarCrush Breakout Radar run, download the `lunarcrush-breakout-radar` artifact, unzip it, and open `radar_sortable.html` in a browser. GitHub's source-code view of HTML does not run the interactive table. You can also download the HTML file from the repository's `reports` directory. Open a newer file after the next run to see newer data; an already downloaded snapshot does not update itself.

Choose a result group, search by coin, choose any metric, and switch highest/lowest first. Click a table heading to sort; click again to reverse. Choose columns to show extra metrics. Selecting a sort metric automatically displays it even if its checkbox is off. Missing values stay last in both directions. Numeric values sort numerically, including zero and negative values, while status labels sort alphabetically. Status labels are not quality ranks.

Metrics include breakout score, daily volume/engagement spikes and multiples, raw daily values and seven-day baselines, broader social/volume trends, price changes, score components, penalties, market cap and available numeric fundamental data. Percentages are displayed as percentages; exported CSV retains raw numeric fractions and unformatted numbers. A daily acceleration of 1 means +100%. The export includes only visible columns in the current filtered/sorted order.

Finalists are shown by default. All candidates and separated assets are selectable when those files exist. Only finalists receive the fundamentals overlay; those assessed fields are joined into the all-candidates view by coin ID. Missing fundamentals on other rows stay blank rather than borrowing another coin's values. Older reports without daily spikes or supporting datasets still open, with unavailable metrics shown as dashes.

Each production run archives the HTML and includes it in its downloadable artifact. Sorting affects the displayed view only, not scoring, candidate eligibility, scheduling or API usage. The separate daily spike history CSV/JSON contains the per-day time series; this table shows the latest candidate observations.
