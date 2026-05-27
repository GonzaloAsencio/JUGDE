export interface KeywordDef {
  name: string
  label: string
  color?: string
  textColor?: 'white' | 'black'
}

export const GAME_KEYWORDS: KeywordDef[] = [
  // Dark green — card keywords
  { name: 'accelerate',   label: 'ACCELERATE',   color: '#26705f', textColor: 'white' },
  { name: 'legion',       label: 'LEGION',        color: '#26705f', textColor: 'white' },
  { name: 'action',       label: 'ACTION',        color: '#26705f', textColor: 'white' },
  { name: 'hidden',       label: 'HIDDEN',        color: '#26705f', textColor: 'white' },
  { name: 'ambush',       label: 'AMBUSH',        color: '#26705f', textColor: 'white' },
  // Medium green — card keywords
  { name: 'reaction',     label: 'REACTION',      color: '#1ba17f', textColor: 'white' },
  { name: 'repeat',       label: 'REPEAT',        color: '#1ba17f', textColor: 'white' },
  { name: 'quick-draw',   label: 'QUICK-DRAW',    color: '#1ba17f', textColor: 'white' },
  // Yellow-green — card keywords (black text)
  { name: 'deflect',      label: 'DEFLECT',       color: '#93af34', textColor: 'black' },
  { name: 'temporary',    label: 'TEMPORARY',     color: '#93af34', textColor: 'black' },
  { name: 'deathknell',   label: 'DEATHKNELL',    color: '#93af34', textColor: 'black' },
  { name: 'hunt',         label: 'HUNT',          color: '#93af34', textColor: 'black' },
  { name: 'level',        label: 'LEVEL',         color: '#93af34', textColor: 'black' },
  { name: 'ganking',      label: 'GANKING',       color: '#93af34', textColor: 'black' },
  // Red — card keywords
  { name: 'assault',      label: 'ASSAULT',       color: '#bb2f65', textColor: 'white' },
  { name: 'shield',       label: 'SHIELD',        color: '#bb2f65', textColor: 'white' },
  { name: 'tank',         label: 'TANK',          color: '#bb2f65', textColor: 'white' },
  { name: 'backline',     label: 'BACKLINE',      color: '#bb2f65', textColor: 'white' },
  // Gray — card keywords
  { name: 'stun',         label: 'STUN',          color: '#696c64', textColor: 'white' },
  { name: 'equip',        label: 'EQUIP',         color: '#696c64', textColor: 'white' },
  { name: 'buff',         label: 'BUFF',          color: '#696c64', textColor: 'white' },
  { name: 'mighty',       label: 'MIGHTY',        color: '#696c64', textColor: 'white' },
  { name: 'weaponmaster', label: 'WEAPONMASTER',  color: '#696c64', textColor: 'white' },
  { name: 'vision',       label: 'VISION',        color: '#696c64', textColor: 'white' },
  { name: 'add',          label: 'ADD',           color: '#696c64', textColor: 'white' },
  { name: 'predict',      label: 'PREDICT',       color: '#696c64', textColor: 'white' },
  // General game keywords — plain text, no badge
  { name: 'banish',       label: 'banish' },
  { name: 'burn out',     label: 'burn out' },
  { name: 'chain',        label: 'chain' },
  { name: 'channel',      label: 'channel' },
  { name: 'cleanup',      label: 'cleanup' },
  { name: 'combat',       label: 'combat' },
  { name: 'counter',      label: 'counter' },
  { name: 'discard',      label: 'discard' },
  { name: 'draw',         label: 'draw' },
  { name: 'exhaust',      label: 'exhaust' },
  { name: 'kill',         label: 'kill' },
  { name: 'main phase',   label: 'main phase' },
  { name: 'priority',     label: 'priority' },
  { name: 'ready',        label: 'ready' },
  { name: 'recall',       label: 'recall' },
  { name: 'recycle',      label: 'recycle' },
  { name: 'replacement',  label: 'replacement' },
  { name: 'reveal',       label: 'reveal' },
  { name: 'scoring',      label: 'scoring' },
  { name: 'showdown',     label: 'showdown' },
  { name: 'token',        label: 'token' },
  { name: 'unique',       label: 'unique' },
]

export const KEYWORD_ALIASES: Record<string, string> = {
  'action phase': 'main phase',
}
