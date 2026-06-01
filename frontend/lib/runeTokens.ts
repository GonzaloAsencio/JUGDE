// Riftbound game symbols arrive in answer text as Discord-style emoji tokens
// (e.g. ":rb_might:", ":rb_energy_1:", ":rb_rune_fury:"). We render the known
// ones as icons and leave any unknown ":rb_*:" noise (rb_kwargs, rb_id, …) as
// plain text by only matching a whitelist.

export type RuneToken =
  | { kind: 'img'; src: string; alt: string; desc: string; emphasis?: boolean }
  | { kind: 'energy'; value: number; alt: string; desc: string };

export interface RuneSegment {
  text: string;
  token?: RuneToken;
}

// Runes reuse the SVGs already in public/ (text-only assets; the PNGs are the
// hero page's and are not used here).
const RUNE_FILES: Record<string, string> = {
  fury: '/fury.svg',
  mind: '/mind.svg',
  calm: '/calm.svg',
  body: '/body.svg',
  chaos: '/chaos.svg',
  order: '/order.svg',
};

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

// `name` is the token without the ":rb_" prefix or trailing ":" — e.g. "might",
// "rune_fury", "energy_3". Returns undefined for anything outside the whitelist.
export function resolveRuneToken(name: string): RuneToken | undefined {
  const n = name.toLowerCase();

  if (n === 'might')
    return { kind: 'img', src: '/rb_might.svg', alt: 'Might', emphasis: true,
      desc: "A unit's power: it deals this much combat damage and dies when it takes that much." };
  if (n === 'exhaust')
    return { kind: 'img', src: '/rb_exhaust.svg', alt: 'Exhaust',
      desc: 'Rotate this card sideways as a cost, marking it spent until you ready it.' };
  if (n === 'rune_rainbow')
    return { kind: 'img', src: '/rb_rune_rainbow.svg', alt: 'Any rune',
      desc: 'Power of any domain — pay it with a rune of whichever color you like.' };

  const rune = n.match(/^rune_(fury|mind|calm|body|chaos|order)$/);
  if (rune)
    return { kind: 'img', src: RUNE_FILES[rune[1]], alt: `${cap(rune[1])} rune`,
      desc: `${cap(rune[1])} Power — pay it with a ${cap(rune[1])}-domain rune.` };

  const energy = n.match(/^energy_([0-7])$/);
  if (energy)
    return { kind: 'energy', value: Number(energy[1]), alt: `${energy[1]} energy`,
      desc: `${energy[1]} Energy — the colorless resource paid to play cards and abilities.` };

  return undefined;
}

const TOKEN_SOURCE =
  ':rb_(might|exhaust|rune_rainbow|rune_(?:fury|mind|calm|body|chaos|order)|energy_[0-7]):';

export function detectRuneTokens(text: string): RuneSegment[] {
  if (!text) return [{ text }];

  const regex = new RegExp(TOKEN_SOURCE, 'gi');
  const segments: RuneSegment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index) });
    }
    const token = resolveRuneToken(match[1]);
    segments.push({ text: match[0], token });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex) });
  }

  return segments.length > 0 ? segments : [{ text }];
}
