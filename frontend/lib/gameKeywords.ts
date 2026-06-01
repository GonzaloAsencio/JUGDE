export interface KeywordDef {
  name: string
  label: string
  color?: string
  textColor?: 'white' | 'black'
  description?: string
}

export const GAME_KEYWORDS: KeywordDef[] = [
  // Dark green — card keywords
  { name: 'accelerate',   label: 'ACCELERATE',   color: '#26705f', textColor: 'white', description: 'As you play this unit, you may pay 1 extra energy and matching Power to have it enter ready instead of exhausted.' },
  { name: 'legion',       label: 'LEGION',        color: '#26705f', textColor: 'white', description: "If you've already played another card this turn, this card gains its bonus ability." },
  { name: 'action',       label: 'ACTION',        color: '#26705f', textColor: 'white', description: "Can be played or activated during showdowns, on any player's turn." },
  { name: 'hidden',       label: 'HIDDEN',        color: '#26705f', textColor: 'white', description: 'You may pay any rune to hide this facedown at a battlefield. From your next turn it gains Reaction and can be played ignoring its base cost.' },
  { name: 'ambush',       label: 'AMBUSH',        color: '#26705f', textColor: 'white', description: 'May be played to a battlefield where you control units, and gains Reaction while being played there.' },
  // Medium green — card keywords
  { name: 'reaction',     label: 'REACTION',      color: '#1ba17f', textColor: 'white', description: "Can be played or activated during closed states, on any player's turn (includes Action's timings)." },
  { name: 'repeat',       label: 'REPEAT',        color: '#1ba17f', textColor: 'white', description: "Pay its extra cost as you play this spell to carry out the spell's effect one additional time." },
  { name: 'quick-draw',   label: 'QUICK-DRAW',    color: '#1ba17f', textColor: 'white', description: 'This gear has Reaction; when played, attach it to a unit you control.' },
  // Yellow-green — card keywords (black text)
  { name: 'deflect',      label: 'DEFLECT',       color: '#93af34', textColor: 'black', description: 'Opponents’ spells and abilities that choose this cost more Power for each time they target it.' },
  { name: 'temporary',    label: 'TEMPORARY',     color: '#93af34', textColor: 'black', description: "At the start of its controller's Beginning Phase, before scoring, this is killed." },
  { name: 'deathknell',   label: 'DEATHKNELL',    color: '#93af34', textColor: 'black', description: 'When this dies and goes to the trash, its effect triggers.' },
  { name: 'hunt',         label: 'HUNT',          color: '#93af34', textColor: 'black', description: 'When this unit Conquers or Holds a battlefield, you gain XP.' },
  { name: 'level',        label: 'LEVEL',         color: '#93af34', textColor: 'black', description: 'While you have enough XP, this card gains its bonus ability.' },
  { name: 'ganking',      label: 'GANKING',       color: '#93af34', textColor: 'black', description: 'This unit may move directly from one battlefield to another with its standard move.' },
  // Red — card keywords
  { name: 'assault',      label: 'ASSAULT',       color: '#bb2f65', textColor: 'white', description: 'While this unit is an attacker, it has bonus Might.' },
  { name: 'shield',       label: 'SHIELD',        color: '#bb2f65', textColor: 'white', description: 'While this unit is a defender, it has bonus Might.' },
  { name: 'tank',         label: 'TANK',          color: '#bb2f65', textColor: 'white', description: "Must be assigned lethal combat damage before your other units that don't have Tank." },
  { name: 'backline',     label: 'BACKLINE',      color: '#bb2f65', textColor: 'white', description: "Assigned lethal combat damage only after your other units that don't have Backline." },
  // Gray — card keywords
  { name: 'stun',         label: 'STUN',          color: '#696c64', textColor: 'white', description: "A stunned unit doesn't contribute its Might to combat damage; it recovers at the next Ending Step." },
  { name: 'equip',        label: 'EQUIP',         color: '#696c64', textColor: 'white', description: 'Pay its equip cost to attach this gear to a unit you control.' },
  { name: 'buff',         label: 'BUFF',          color: '#696c64', textColor: 'white', description: 'Place a buff counter on a unit; each buff gives +1 Might (a unit can hold only one).' },
  { name: 'mighty',       label: 'MIGHTY',        color: '#696c64', textColor: 'white', description: 'A unit is Mighty while its Might is 5 or greater.' },
  { name: 'weaponmaster', label: 'WEAPONMASTER',  color: '#696c64', textColor: 'white', description: 'When played, choose one of your Equipment and pay its Equip cost (reduced) to attach it to this unit.' },
  { name: 'vision',       label: 'VISION',        color: '#696c64', textColor: 'white', description: 'When this is played, look at the top card of your Main Deck; you may recycle it.' },
  { name: 'add',          label: 'ADD',           color: '#696c64', textColor: 'white', description: 'Put resources (Energy or Power) into your Rune Pool.' },
  { name: 'predict',      label: 'PREDICT',       color: '#696c64', textColor: 'white', description: 'Look at the top card of your Main Deck and choose whether to recycle it.' },
  // General game keywords — plain text, no badge (still get a tooltip)
  { name: 'banish',       label: 'banish',       description: 'Move a card to the Banishment zone (not the trash).' },
  { name: 'burn out',     label: 'burn out',     description: "When you'd draw from an empty deck: shuffle your trash back in and an opponent gains 1 point." },
  { name: 'chain',        label: 'chain',        description: 'The stack where played cards and abilities wait to resolve, last in first out.' },
  { name: 'channel',      label: 'channel',      description: 'Put runes from the top of your Rune Deck onto the board.' },
  { name: 'cleanup',      label: 'cleanup',      description: 'A game step that resolves pending state-based effects, like killing lethally damaged units.' },
  { name: 'combat',       label: 'combat',       description: 'The sequence of steps where attackers and defenders deal damage.' },
  { name: 'counter',      label: 'counter',      description: 'Negate a card or ability on the chain; it does nothing and is removed.' },
  { name: 'discard',      label: 'discard',      description: 'Move a card from your hand to your trash without playing it.' },
  { name: 'draw',         label: 'draw',         description: 'Take the top card of your Main Deck into your hand.' },
  { name: 'exhaust',      label: 'exhaust',      description: 'Rotate a card sideways to mark it as spent (often paid as a cost).' },
  { name: 'kill',         label: 'kill',         description: 'Send a permanent from the board to the trash.' },
  { name: 'main phase',   label: 'main phase',   description: 'The phase where you play cards and take actions on your turn.' },
  { name: 'priority',     label: 'priority',     description: 'The right to take the next action; players pass it back and forth.' },
  { name: 'ready',        label: 'ready',        description: "Rotate a card upright so it's available to act again." },
  { name: 'recall',       label: 'recall',       description: "Return a unit or gear from the board to its owner's hand." },
  { name: 'recycle',      label: 'recycle',      description: 'Put a card on the bottom of its corresponding deck.' },
  { name: 'replacement',  label: 'replacement',  description: 'An effect that replaces an event with a different one before it happens.' },
  { name: 'reveal',       label: 'reveal',       description: 'Show a card to all players; it stays in its current zone.' },
  { name: 'scoring',      label: 'scoring',      description: 'The step where players gain points for the battlefields they hold.' },
  { name: 'showdown',     label: 'showdown',     description: "An open window during a turn when Action cards can be played." },
  { name: 'token',        label: 'token',        description: 'A game object created by an effect; not a real card, it ceases to exist off the board.' },
  { name: 'unique',       label: 'unique',       description: 'Deck-building rule: your deck may contain only one copy of this card.' },
]

export const KEYWORD_ALIASES: Record<string, string> = {
  'action phase': 'main phase',
}
