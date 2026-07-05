// The rulebook markdown packs every sub-rule of a section (133.1, 133.4.a.1, …)
// plus its "Example:" notes into ONE run-on paragraph line, which renders as an
// unreadable wall of text. This splits each such line into one clause per line
// (blank-line separated) so ReactMarkdown emits a paragraph per clause, letting
// the renderer hang the rule number and indent by depth.
//
// A clause marker looks like "133.", "133.1.", "133.4.a.", "135.2.e.5.a." — a
// number head followed by dot-separated numeric/alpha segments. Cross-references
// ("See rule 428.") are deliberately NOT split: their number is preceded by the
// word "rule"/"rules", which we detect and skip.

const CLAUSE = /(^|\s)((?:\d{1,3})(?:\.(?:\d+|[a-z]))*\.)\s+(?=\S)/g;
const EXAMPLE = /(^|\s)(Example:)/g;

function splitLine(line: string): string {
  const points: number[] = [];

  let m: RegExpExecArray | null;
  CLAUSE.lastIndex = 0;
  while ((m = CLAUSE.exec(line)) !== null) {
    const start = m.index + m[1].length; // index of the number itself
    const before = line.slice(Math.max(0, start - 6), start).toLowerCase();
    if (/rule[s]?\s$/.test(before)) continue; // "See rule 428." → keep inline
    points.push(start);
  }

  EXAMPLE.lastIndex = 0;
  while ((m = EXAMPLE.exec(line)) !== null) {
    points.push(m.index + m[1].length); // break before "Example:"
  }

  points.sort((a, b) => a - b);
  if (points.length === 0) return line;

  const pieces: string[] = [];
  const head = line.slice(0, points[0]).trim();
  if (head) pieces.push(head);
  for (let i = 0; i < points.length; i++) {
    const to = i + 1 < points.length ? points[i + 1] : line.length;
    pieces.push(line.slice(points[i], to).trim());
  }
  return pieces.filter(Boolean).join('\n\n');
}

/** Explodes run-on rule paragraphs into one clause per markdown paragraph. */
export function structureClauses(md: string): string {
  return md
    .split('\n')
    .map((line) => {
      if (!line || line.startsWith('#') || line.startsWith('[//]')) return line;
      CLAUSE.lastIndex = 0;
      const hasClause = CLAUSE.test(line);
      if (!hasClause && !/\sExample:/.test(line)) return line;
      return splitLine(line);
    })
    .join('\n');
}

/** Splits a leading rule-number marker off a clause: "133.4.a. text" → parts. */
export function parseClause(text: string): { num: string; depth: number; rest: string } | null {
  const m = text.match(/^((?:\d{1,3})(?:\.(?:\d+|[a-z]))*)\.\s+/);
  if (!m) return null;
  const num = m[1];
  return { num, depth: num.split('.').length, rest: text.slice(m[0].length) };
}
