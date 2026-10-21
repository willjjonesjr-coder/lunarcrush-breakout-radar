// Shared by the standalone report and its regression tests.
function sortRows(rows, key, direction = 'desc', kind = 'number') {
  const missing = v => v === null || v === undefined || v === '' ||
    (kind === 'number' && (typeof v !== 'number' || !Number.isFinite(v)));
  return rows.map((row, index) => ({row, index})).sort((a, b) => {
    const x = a.row[key], y = b.row[key], mx = missing(x), my = missing(y);
    if (mx || my) return mx === my ? a.index - b.index : mx ? 1 : -1;
    const cmp = kind === 'number' ? x-y : String(x).localeCompare(String(y));
    return (direction === 'asc' ? cmp : -cmp) || a.index-b.index;
  }).map(x => x.row);
}
if (typeof module !== 'undefined') module.exports = {sortRows};
