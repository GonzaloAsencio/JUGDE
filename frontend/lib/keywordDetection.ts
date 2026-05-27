import { GAME_KEYWORDS, type KeywordDef } from './gameKeywords';

export interface TextSegment {
  text: string;
  keyword?: KeywordDef;
}

const keywordByName = new Map(GAME_KEYWORDS.map(k => [k.name.toLowerCase(), k]));

// Sorted longest-first to avoid partial matches (e.g. "main phase" before "main")
const KEYWORD_PATTERN = GAME_KEYWORDS
  .map(k => k.name)
  .sort((a, b) => b.length - a.length)
  .map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  .join('|');

export function detectKeywords(text: string): TextSegment[] {
  if (!text) return [{ text }];

  const regex = new RegExp(`\\b(${KEYWORD_PATTERN})\\b`, 'gi');
  const segments: TextSegment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index) });
    }
    const keyword = keywordByName.get(match[0].toLowerCase());
    segments.push({ text: match[0], keyword });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex) });
  }

  return segments.length > 0 ? segments : [{ text }];
}
