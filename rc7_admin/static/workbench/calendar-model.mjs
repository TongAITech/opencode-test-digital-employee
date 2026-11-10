// Calendar dates are business DATE values. Never parse them in the viewer's timezone.
export function daysInMonth(year, month) {
  if (!Number.isInteger(year) || year < 1 || year > 9999 || !Number.isInteger(month) || month < 1 || month > 12) throw Error('INVALID_CALENDAR_DATE');
  return [31, year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}
export function parseDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw Error('INVALID_CALENDAR_DATE');
  const [year, month, day] = value.split('-').map(Number);
  if (day < 1 || day > daysInMonth(year, month)) throw Error('INVALID_CALENDAR_DATE');
  return {year, month, day};
}
export function formatDate(year, month, day) {
  const value = `${String(year).padStart(4,'0')}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
  parseDate(value);
  return value;
}
function utcDate(year, month, day) {
  const value = new Date(0);
  value.setUTCFullYear(year, month - 1, day);
  value.setUTCHours(0, 0, 0, 0);
  return value;
}
export function shiftDate(value, mode, step) {
  const {year, month, day} = parseDate(value);
  if (!['year','month','day'].includes(mode) || ![-1,1].includes(step)) throw Error('INVALID_CALENDAR_STEP');
  let y = year, m = month, d = day;
  if (mode === 'day') {
    const date = utcDate(year, month, day);
    date.setUTCDate(date.getUTCDate() + step);
    [y, m, d] = [date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate()];
  } else if (mode === 'year') y += step;
  else {
    const offset = (year - 1) * 12 + month - 1 + step;
    y = Math.floor(offset / 12) + 1;
    m = ((offset % 12) + 12) % 12 + 1;
  }
  if (y < 1 || y > 9999) return null;
  return formatDate(y, m, Math.min(d, daysInMonth(y, m)));
}
export function monthCells(value) {
  const {year, month} = parseDate(value);
  const padding = (utcDate(year, month, 1).getUTCDay() + 6) % 7; // Monday first.
  const cells = Array(padding).fill(null);
  for (let day = 1; day <= daysInMonth(year, month); day++) cells.push(formatDate(year, month, day));
  while (cells.length % 7) cells.push(null);
  return cells;
}
export function visibleMilestones(records, value, mode) {
  parseDate(value);
  if (!['year','month','day'].includes(mode)) throw Error('INVALID_CALENDAR_MODE');
  const length = {year:4, month:7, day:10}[mode];
  const seen = new Set();
  for (const record of records) {
    if (record.kind !== 'milestone' || typeof record.asset_id !== 'string' || !record.asset_id || seen.has(record.asset_id) || !['ACTIVE','RETIRED'].includes(record.state) || typeof record.title !== 'string') throw Error('INVALID_MILESTONE');
    parseDate(record.payload?.due_date);
    seen.add(record.asset_id);
  }
  return records.filter(record => record.payload.due_date.slice(0, length) === value.slice(0, length)).slice().sort((a,b) => a.payload.due_date.localeCompare(b.payload.due_date) || (a.asset_id < b.asset_id ? -1 : a.asset_id > b.asset_id ? 1 : 0));
}
