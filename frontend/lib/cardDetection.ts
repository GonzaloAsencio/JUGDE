import { CARD_INDEX, type CardIndexEntry } from '@/lib/cardIndex';

export interface CardSegment {
  text: string;
  card?: CardIndexEntry;
}

const cardByName = new Map(CARD_INDEX.map(c => [c.clean_name.toLowerCase(), c]));

// Only multi-word (2+ words) card names are detected in free text. Single-word
// names (Eclipse, Detonate, Daisy...) collide with common words and would cause
// false positives, so they are deliberately excluded. Sorted longest-first so a
// longer name wins over any shorter name it contains.
const MULTIWORD_PATTERN = CARD_INDEX
  .map(c => c.clean_name)
  .filter(n => n.trim().split(/\s+/).length >= 2)
  .sort((a, b) => b.length - a.length)
  .map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  .join('|');

export function detectCards(text: string): CardSegment[] {
  if (!text || !MULTIWORD_PATTERN) return [{ text }];

  const regex = new RegExp(`\\b(${MULTIWORD_PATTERN})\\b`, 'gi');
  const segments: CardSegment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index) });
    }
    const card = cardByName.get(match[0].toLowerCase());
    segments.push({ text: match[0], card });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex) });
  }

  return segments.length > 0 ? segments : [{ text }];
}
