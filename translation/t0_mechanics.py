#!/usr/bin/env python3
"""T0 mechanic taxonomy: rule tables used by t0_decompose.py to name what an unread goldfish line needs.

Scope (what a goldfish could ever do with the line):
  sim     your own resources, board, turns, or the opponents' life totals: simulatable in principle
  approx  simulatable only with a fixed stand-in for opponents or hidden information
          (--blockers boards, ~opp taxes and casts, "an opponent chooses"). Chance (coins, dice) is sim: Monte Carlo
          samples it exactly.
  disr    matters only against the disruption ladder (regenerate, hexproof, protection vs removal and wipes)
  oos     out of scope for a goldfish and harmless to ignore: answers to opponents' spells, their hands and choices,
          politics, protection from attacks that never come, timing permissions (flash)
Engine (what goldfish.py executes today for that mechanic family, per docs/GOLDFISH.md):
  has     the engine runs this family; a line needing only 'has' parts is a parse gap
  partial some forms run, this one needs new engine work
  lacks   no engine support
Heuristic tables, first match wins. docs/TRANSLATION_T0.md reports their agreement with hand labels.
"""
import re

KW = {   # keyword -> (scope, engine) for keywords goldfish.py doesn't read. Unlisted: ("sim", "lacks").
    "morph": ("sim", "lacks"), "megamorph": ("sim", "lacks"), "disguise": ("sim", "lacks"), "cloak": ("sim", "lacks"),
    "suspend": ("sim", "lacks"), "foretell": ("sim", "lacks"), "madness": ("sim", "lacks"), "storm": ("sim", "lacks"),
    "convoke": ("sim", "lacks"), "improvise": ("sim", "lacks"), "delve": ("sim", "lacks"), "emerge": ("sim", "lacks"),
    "overload": ("approx", "lacks"), "bestow": ("sim", "lacks"), "mutate": ("sim", "lacks"), "echo": ("sim", "lacks"),
    "buyback": ("sim", "lacks"), "entwine": ("sim", "lacks"), "spree": ("sim", "lacks"), "gift": ("sim", "lacks"),
    "offspring": ("sim", "lacks"), "squad": ("sim", "lacks"), "mobilize": ("sim", "lacks"), "station": ("sim", "lacks"),
    "warp": ("sim", "lacks"), "start your engines!": ("sim", "lacks"), "soulshift": ("sim", "lacks"),
    "level up": ("sim", "lacks"), "equip": ("sim", "partial"), "kicker": ("sim", "partial"), "flashback": ("sim", "partial"),
    "dash": ("sim", "lacks"), "blitz": ("sim", "lacks"), "evoke": ("sim", "lacks"), "prowl": ("sim", "lacks"),
    "ninjutsu": ("sim", "lacks"), "extort": ("sim", "lacks"), "afterlife": ("sim", "lacks"), "fabricate": ("sim", "lacks"),
    "embalm": ("sim", "lacks"), "eternalize": ("sim", "lacks"), "encore": ("sim", "lacks"), "disturb": ("sim", "lacks"),
    "aftermath": ("sim", "lacks"), "dredge": ("sim", "lacks"), "persist": ("disr", "lacks"), "undying": ("disr", "lacks"),
    "riot": ("sim", "lacks"), "exploit": ("sim", "lacks"), "devour": ("sim", "lacks"), "evolve": ("sim", "lacks"),
    "outlast": ("sim", "lacks"), "renown": ("sim", "lacks"), "bloodthirst": ("sim", "lacks"), "tribute": ("approx", "lacks"),
    "provoke": ("approx", "lacks"), "cipher": ("sim", "lacks"), "splice": ("sim", "lacks"), "replicate": ("sim", "lacks"),
    "casualty": ("sim", "lacks"), "backup": ("sim", "lacks"), "bargain": ("sim", "lacks"), "craft": ("sim", "lacks"),
    "plot": ("sim", "lacks"), "saddle": ("sim", "lacks"), "crew": ("sim", "lacks"), "surge": ("sim", "lacks"),
    "spectacle": ("sim", "lacks"), "prototype": ("sim", "lacks"), "reconfigure": ("sim", "lacks"), "enlist": ("sim", "lacks"),
    "ravenous": ("sim", "lacks"), "read ahead": ("sim", "lacks"), "for mirrodin!": ("sim", "lacks"), "exhaust": ("sim", "lacks"),
    "freerunning": ("sim", "lacks"), "impending": ("sim", "lacks"), "fading": ("sim", "lacks"), "vanishing": ("sim", "lacks"),
    "phasing": ("disr", "lacks"), "banding": ("oos", "lacks"), "ingest": ("oos", "lacks"), "hideaway": ("sim", "lacks"),
    "amplify": ("sim", "lacks"), "graft": ("sim", "lacks"), "haunt": ("sim", "lacks"), "assist": ("oos", "lacks"),
    "demonstrate": ("approx", "lacks"), "boast": ("sim", "lacks"), "compleated": ("sim", "lacks"), "decayed": ("sim", "lacks"),
    "cleave": ("sim", "lacks"), "discover": ("sim", "lacks"), "champion": ("sim", "lacks"), "conspire": ("sim", "lacks"),
    "recover": ("sim", "lacks"), "miracle": ("sim", "lacks"), "undaunted": ("oos", "lacks"), "awaken": ("sim", "lacks"),
    "living metal": ("sim", "lacks"), "more than meets the eye": ("sim", "lacks"), "specialize": ("sim", "lacks"),
    "double team": ("sim", "lacks"), "hidden agenda": ("sim", "lacks"), "double agenda": ("sim", "lacks"),
    "aura swap": ("sim", "lacks"), "fuse": ("sim", "lacks"), "gravestorm": ("sim", "lacks"), "ripple": ("sim", "lacks"),
    "sneak": ("sim", "lacks"), "job select": ("sim", "lacks"), "web-slinging": ("sim", "lacks"), "airbend": ("sim", "lacks"),
    "earthbend": ("sim", "lacks"), "firebend": ("sim", "lacks"), "waterbend": ("sim", "lacks"), "harmonize": ("sim", "partial"),
    "forage": ("sim", "lacks"), "collect evidence": ("sim", "lacks"), "solved": ("sim", "lacks"), "offering": ("sim", "lacks"),
    "frenzy": ("sim", "lacks"), "bands with other": ("oos", "lacks"), "escalate": ("sim", "lacks"), "entwine ": ("sim", "lacks"),
    "tiered": ("sim", "lacks"), "max speed": ("sim", "lacks"), "mayhem": ("sim", "lacks"), "void": ("sim", "lacks"),
    "infinity": ("sim", "lacks"), "blight": ("sim", "lacks"), "paradigm": ("sim", "lacks"), "visit": ("sim", "lacks"),
}

# Whole-line structural mechanics and scope markers, checked on the whole line first.
STRUCT = [
    ("vehicles / crew / saddle / station", "sim", "lacks", r"^\d+\+ \|"),
    ("dice / coin / at random", "sim", "lacks", r"^\d+(?:—\d+)? \|"),
    ("modal ability with bullet modes ('choose one —' on a trigger or ability)", "sim", "partial", r"\bchoose (?:one|two|three|up to one|up to two|one or more|any number|one or both)(?: that hasn't been chosen(?: this turn)?)? —$|^•"),
    ("commander zone / commander-specific effects", "sim", "lacks", r"\bcommand zone\b|\bcommander tax\b|\byour commander\b"),
    ("leveler (LEVEL N-M blocks)", "sim", "lacks", r"^level \d+[-+]|^level \d+$|^\d+/\d+$|^n/n$"),
    ("saga / case / room structure", "sim", "partial", r"^(?:i|ii|iii|iv|v|vi)(?:, (?:i|ii|iii|iv|v|vi))* — |^to solve — |^solved — |^unlock"),
    ("prepare (enters prepared / becomes prepared)", "sim", "lacks", r"\bprepared?\b"),
    ("transform / DFC / meld / day-night", "sim", "lacks", r"\btransforms?\b|\bmeld\b|\bconvert\b|\bbecomes? day\b|\bbecomes? night\b|\bit'?s night\b"),
    ("mutate", "sim", "lacks", r"\bmutates?\b"),
    ("face-down (morph / manifest / cloak / disguise)", "sim", "lacks", r"\bface[- ]down\b|\bmanifest\b|\bcloak\b|\bturn(?:ed)? face up\b"),
    ("vehicles / crew / saddle / station", "sim", "lacks", r"\bcrew(?:s|ed)?\b|\bvehicles?\b|\bsaddled?\b|\bstation\b"),
    ("dungeon / venture / initiative / the Ring", "approx", "lacks", r"\bventure into\b|\bdungeon\b|\binitiative\b|\bring tempts you\b|\bring-bearer\b"),
    ("monarch", "approx", "lacks", r"\bmonarch\b"),
    ("emblem", "sim", "lacks", r"\bemblem\b"),
    ("extra turn", "sim", "lacks", r"\bextra turn\b"),
    ("skip a turn / step / phase", "sim", "lacks", r"\bskips? (?:your|their|that player's|the|his or her|its)?\s*(?:next )?(?:\w+ )?(?:turns?|untap steps?|upkeeps?|draw steps?|combat|combat phases?)\b"),
    ("rooms / doors", "sim", "lacks", r"\bunlock\b|\bdoors?\b|\broom\b"),
    ("banding and other retired combat rules", "oos", "lacks", r"\bbands? with\b|\bbanding\b"),
    ("life total can't change / can't lose (defensive statics)", "oos", "lacks", r"\blife total can't change\b|\bdamage doesn't cause you to lose life\b|\byou can't lose life\b"),
    ("alt win / lose the game", "sim", "partial", r"\bwins? the game\b|\bloses? the game\b|can't lose the game|can't win the game"),
    ("copy a spell / ability (stack)", "sim", "lacks", r"\bcopy (?:target|that|it|the next|each|this|up to)?[^.]*\bspell\b|\bcopies? of (?:that|the|target) spell\b|\bcopy (?:target|that|the next) (?:activated|triggered) ability\b|\bcopy it\b|\bstorm\b"),
    ("clone (enters as a copy / becomes a copy)", "sim", "lacks", r"\benters? as a copy\b|\bbecomes? a copy\b|\bas a copy of\b"),
    ("flicker (exile, then return to the battlefield)", "sim", "lacks", r"\bexile [^.]*[.,]?\s*(?:then )?return (?:it|them|that card|those cards|the exiled card|each card exiled|that creature|the card)[^.]* to the battlefield|\breturn (?:it|them|that card|those cards) to the battlefield under (?:its|their) owners?'? control"),
    ("cheat a permanent onto the battlefield from hand", "sim", "lacks", r"\bput (?:a|an|up to \w+|any number of|that|those|x|one)?\s*[^.]*cards? from (?:your|their|a player's) hand onto the battlefield|each player may put [^.]* onto the battlefield"),
    ("dice / coin / at random", "sim", "lacks", r"\broll (?:a|two|an?)? ?(?:\w+-sided )?d\d+|\broll a die\b|\bflip (?:a|two|three|\w+) coins?\b|\bat random\b|\bcoin\b|\bplanar die\b|\bvisit\b"),
    ("energy / experience / rad / tickets (player counters)", "sim", "lacks", r"\{e\}|\benergy\b|\bexperience counters?\b|\brad counters?\b|\bticket counters?\b"),
    ("gain / exchange control", "oos", "lacks", r"\bgains? control of\b|\bexchange control\b|\bgain control\b|\benters under the control of\b|\bexchange life totals\b"),
    ("politics: vote / council / goad / 'an opponent may'", "oos", "lacks", r"\bvotes?\b|\bgoad(?:s|ed)?\b|\btempting offer\b|\bjoin forces\b|\bcouncil's dilemma\b|\bwill of the council\b|\bany player may\b|\beach opponent may\b|\ban opponent may\b|\bthat player may\b|\ba player may\b|\bfriend or foe\b|\bplayer to your (?:left|right)\b"),
    ("counter / redirect spells (stack interaction)", "oos", "has", r"\bcounter (?:target|that|it|each|up to|all|any)\b|\bcounters? (?:target )?(?:spell|ability)\b|\bchange the target\b|\bchoose new targets\b|\bcan't be countered\b|\bexile any number of target spells\b|\breturn target spell\b"),
    ("opponents' hands / discard / hidden info", "oos", "has", r"\b(?:target|each|that|defending) (?:opponent|player)'?s? hand\b|\b(?:target opponent|each opponent|that player|target player|defending player|each other player) (?:discards|reveals (?:their|his or her) hand)|look at (?:target|an|each) (?:opponent|player)'s hand|\bopponent'?s? hand\b"),
    ("prevent / redirect damage (fog)", "oos", "lacks", r"\bprevent (?:all|the next|that|any|x|\w+)\b[^.]*damage|\bdamage [^.]*(?:is|would be) prevented|damage can't be prevented"),
    ("protection / hexproof / shroud / ward / phasing grant", "disr", "partial", r"\bprotection from\b|\bhexproof\b|\bshroud\b|\bward\b|\bphases? (?:out|in)\b|\bphasing\b"),
    ("indestructible grant", "disr", "partial", r"\bindestructible\b"),
    ("regenerate", "disr", "lacks", r"\bregenerate\b|\bcan't be regenerated\b"),
    ("graveyard hate (any graveyard)", "oos", "has", r"\bexile (?:target|each|all|up to \w+ target|x target)[^.]*cards? from (?:a|target|each|all|an opponent's|target player's|any|their) graveyards?|\bexile (?:all|each) (?:cards?|graveyards?)\b|\bexile target player's graveyard\b|\bexile all graveyards\b|cards in graveyards can't|from graveyards can't"),
    ("flash / timing permission", "oos", "has", r"\bas though (?:it|they) had flash\b|\bany time you could cast an instant\b"),
    ("stax: casting / draw / untap limits (bind you too)", "sim", "lacks", r"\b(?:each player|players|your opponents|opponents|no player)\b[^.]*\bcan't\b|\bcan't cast more than\b|\bno more than (?:one|two) (?:spells?|creatures?)\b|\bplayers skip\b|\bplayers can't\b|\beach player can't\b"),
]

# Effect families (per sentence of the effect, after frames and conditions are cut off).
EFFECT = [
    ("explore / connive / investigate-like keyword actions", "sim", "lacks", r"\bexplores?\b|\bconnives?\b|\bmonstrosity\b|\bbolster\b|\badapt\b|\bsupport \d\b|\bamass\b|\bincubate\b|\bpopulate\b|\bsurveil\b"),
    ("keyword counters (flying, double strike, shield, stun...)", "sim", "lacks", r"\b(?:flying|first strike|double strike|deathtouch|hexproof|indestructible|lifelink|menace|reach|trample|vigilance|haste|shield|stun|finality)\b counters?\b"),
    ("move / double / remove counters", "sim", "lacks", r"\bmove (?:a|any number of|all|one or more) [^.]*counters?\b|\bdouble the number of [^.]*counters\b|\bremove all counters\b|\badditional counter of that kind\b"),
    ("named noncreature tokens (Blood, Powerstone, Map, Shard, Junk, Role...)", "sim", "lacks", r"\b(?:blood|powerstone|map|shard|junk|incubator|lander|mutagen|role|stoneforged blade|walker|detective|egg)\b tokens?\b"),
    ("land type change (Blood Moon, 'is a Mountain')", "sim", "lacks", r"\bnonbasic lands are\b|\blands? (?:you control )?(?:are|is) (?:a |an )?(?:mountain|forest|island|swamp|plains)s?\b|\bis every basic land type\b"),
    ("half life / half library / double life", "sim", "lacks", r"\bhalf (?:their|your|his or her|that player's) life\b|\bdouble (?:your|their) life\b"),
    ("zone- or type-aware cost changes (abilities, from exile...)", "sim", "lacks", r"\bactivated abilities [^.]*cost\b|\bspells you cast from (?:anywhere|exile|your graveyard)[^.]*cost\b|\bcosts? [^.]*less to (?:activate|cast) for each\b"),
    ("delayed trigger ('at the beginning of the next end step', 'this turn, whenever')", "sim", "lacks", r"\bat the beginning of (?:the next|your next|the next turn's)\b|\bnext end step\b|\bthis turn, whenever\b|\buntil end of turn, whenever\b|\bwhen that creature\b|\bwhen you do\b"),
    ("bounce your own permanent (re-buy ETBs)", "sim", "lacks", r"\breturn (?:target|a|an|another|up to \w+ target|two|x target)? ?[^.]*(?:you control|you own)[^.]* to (?:its|their) owners?'? hands?\b|\breturn (?:a|an|another) [^.]* you control to (?:its|their) owner's hand"),
    ("keyword actions (earthbend, airbend, endure, harness...)", "sim", "lacks", r"\b(?:earthbend|airbend|firebend|waterbend|endure|harness|forage|manifest dread|suspect|collect evidence|seek|discover|conjure|perpetually|intensify|specialize|clash|detain|exert|meld|goad|learn|scavenge|reinforce|forecast|kicker)\b"),
    ("pay any amount of life / X life", "sim", "lacks", r"\bpay any amount of life\b|\bpay x life\b"),
    ("tax / cost increase on others", "approx", "partial", r"\bcosts? \{[^}]+\}(?:\{[^}]+\})* more\b|\bcosts? (?:\w+ )?more to (?:cast|activate)\b|\bunless (?:its|that|their) controller pays\b|\bunless that player pays\b|\bunless they pay\b"),
    ("opponents' creatures: can't attack/block, tap down, must attack", "approx", "partial", r"\bcan't (?:attack|block)\b|\battacks? each (?:combat|turn) if able\b|\bmust be blocked\b|\bblocks? each combat if able\b|\btap (?:target|up to \w+ target|all|each) (?:creature|permanent|artifact|land)s?\b(?! you control)|\bdoesn't untap\b|\bdon't untap\b"),
    ("removal / damage to creatures / wipes / fight / bounce", "approx", "partial", r"\bdeals? damage equal to [^.]* to (?:another |up to one )?target (?:creature|planeswalker)\b|\b(?:destroy|exile) (?:target|up to \w+ target|each|all|another target|x target|two target|three target|any number of target)\b(?! (?:card|cards|spell)\b)|\breturn (?:target|up to \w+ target|each|all|x target)[^.]*(?:creature|permanent|artifact|enchantment|nonland)[^.]* to (?:its|their) owners?'? hands?\b|\bdeals? (?:\w+|x) damage to (?:target|each|up to|another target|any number of target)[^.]*(?:creature|planeswalker|battle)|\bfights?\b|\bgets? -\d+/-\d+|\bget -\d+/-\d+|-x/-x|\bdestroy (?:it|that creature|that permanent|them)\b|\bputs? (?:it|that permanent|that creature) on (?:the )?(?:top|bottom) of (?:its|their) owners?'? library|\bshuffles? (?:it|that permanent) into (?:its|their) owners?'? library"),
    ("animate / becomes a creature / type or ability change", "sim", "partial", r"\bbecomes? an? (?:\d+/\d+|x/x)?\s*[^.]*\bcreature\b|\bbecomes? (?:an? )?(?:artifact|enchantment|land|creature)\b|\bis an? [^.]*\bcreature in addition\b|\bare [^.]* in addition to their other types\b|\bis (?:also )?an? [^.]* in addition to its other types\b|\bloses? all (?:other )?(?:abilities|creature types|card types)\b|\bis every creature type\b|\bare every creature type\b|\bhas all activated abilities\b"),
    ("copy a permanent (token copies, special)", "sim", "partial", r"\btokens? that(?:'s| are) (?:a )?cop(?:y|ies)\b|\bcopy of (?:target|that|another|each|~)\b"),
    ("P/T set, doubled or counted", "sim", "partial", r"(?:power|toughness)(?: and toughness)? (?:is|are)(?: each)? equal to\b|\bhas base power\b|\bbase power and toughness\b|\bbase toughness\b|\bpower and toughness are each\b|\bswitch (?:its|~'s) power and toughness\b|\bdouble (?:the power|target creature's power|its power)\b"),
    ("cast / play from exile or the top of the library (impulse, Future Sight)", "sim", "partial", r"\b(?:play|cast) (?:lands|spells|cards|the top card|that card|those cards|it|them|a card|one of them|up to)[^.]*(?:from (?:the )?top of your library|from among|this turn|until (?:the )?end of|until your next)|\bplay (?:lands|cards) from the top\b|\bplay with the top card of your library revealed\b|\blook at the top card of your library any time\b|may play (?:that card|those cards|it|them)|may cast (?:that card|it|them|those cards|the exiled card|spells from among)"),
    ("cast from graveyard / grant flashback-like", "sim", "partial", r"\b(?:cast|play) [^.]*from (?:your|a|their|any) graveyard\b|\b(?:has|have|gains) (?:flashback|escape|encore|unearth|jump-start|retrace)\b"),
    ("free cast / alternative cost", "sim", "partial", r"without paying (?:its|their|that card's|the) mana cost|rather than pay\b"),
    ("cost-reduction keywords granted (convoke, improvise, affinity...)", "sim", "lacks", r"\bhave (?:convoke|improvise|affinity|delve|ripple|cascade|myriad)\b|\bhas (?:convoke|improvise|affinity|delve|ripple|cascade|myriad)\b"),
    ("untap permanents", "sim", "partial", r"\buntap (?:target|all|up to|each|another|~|it|that|them|those|two|x|another target|any number)\b"),
    ("extra combat", "sim", "partial", r"\badditional combat\b|\bafter this phase\b"),
    ("extra land drops / lands enter untapped", "sim", "partial", r"\badditional lands?\b|\bplay an additional\b|\blands you control enter untapped\b"),
    ("keep unspent mana / mana doubling variants", "sim", "lacks", r"\bdon't lose (?:unspent|this) mana\b|\bdoesn't empty\b|\bunspent\b"),
    ("self-mill", "sim", "has", r"\bmills?\b|\bhalf (?:their|your) library\b"),
    ("recursion (graveyard to hand / top / battlefield)", "sim", "has", r"\breturns? [^.]*(?:from|of) (?:your|a|his or her|their|target player's|an opponent's|all) graveyards? to\b|\bput [^.]*from (?:your|a|all) graveyards? (?:on top|into|onto|on the bottom)\b|\breturn [^.]*cards? from your graveyard\b|\bshuffle [^.]*graveyard into (?:your|their|its owner's) library\b"),
    ("tutor (search library)", "sim", "has", r"\bsearch(?:es)? (?:your|target player's|their|his or her) library\b"),
    ("look / reveal / dig at the library", "sim", "partial", r"\blook at the top\b|\breveal the top\b|\breveal cards from the top\b|\bexile the top\b|\bexiles? cards from the top\b|\breveals? (?:cards|the top)\b|\bput the top \w+ cards?\b"),
    ("tokens", "sim", "has", r"\bcreates?\b|\binvestigates?\b|\bamass\b|\bincubate\b|\bpopulate\b"),
    ("counters on permanents (+1/+1, -1/-1, others; proliferate, adapt...)", "sim", "has", r"\bcounters?\b|\bproliferate\b|\bbolster\b|\badapt\b|\bsupport \d\b|\bmonstrosity\b|\bmonstrous\b|\bconnives?\b|\bexplores?\b"),
    ("draw / loot / discard (you)", "sim", "has", r"\bdraws?\b|\bdiscards?\b"),
    ("life gain / loss / drains", "sim", "has", r"\bgains? (?:\w+|x) life\b|\bgain life\b|\blife equal to\b|\bloses? (?:\w+|x) life\b|\blose life\b|\bpay (?:\w+|x) life\b"),
    ("life total set / exchanged", "sim", "lacks", r"\blife total\b"),
    ("damage to players (burn, pingers)", "sim", "has", r"\bdeals? (?:\w+|x) damage\b|\bdeals? damage\b|\bdamage to (?:each|target|any|that)\b"),
    ("pump / anthem / keyword grant", "sim", "has", r"\bgets? [+-](?:\d+|x)/[+-](?:\d+|x)\b|\bget [+-](?:\d+|x)/[+-](?:\d+|x)\b|\b(?:gains?|has|have)\b[^.]*\b(?:flying|trample|haste|vigilance|lifelink|deathtouch|first strike|double strike|menace|reach|infect|wither|defender)\b|\bcan't be blocked\b"),
    ("mana ability / ritual variants", "sim", "partial", r"\badds?\b[^.]*(?:\{[wubrgcsx]\}|mana)|\bmana of any\b|\bspend (?:this )?mana\b"),
    ("cost reduction", "sim", "has", r"\bcosts? (?:\{[^}]+\}|\w+|x) less\b|\bcost (?:\{[^}]+\}|\w+) less\b|\bless to cast\b|\bless to activate\b"),
    ("sacrifice (self / edicts)", "sim", "partial", r"\bsacrifices?\b"),
    ("equipment / aura attach and grants", "sim", "partial", r"\bequipped creature\b|\benchanted (?:creature|permanent|land|artifact|player)\b|\battach(?:ed|es)?\b|\bequip\b|\bfortif"),
    ("chosen value (color, type, name, number)", "sim", "lacks", r"\bchoose (?:a|an|any|a number|a color|a creature type|a card type|a card name|a nonland card name)\b|\bthe chosen\b|\bnamed card\b|\bchosen (?:color|type|name|number)\b"),
    ("hand size", "sim", "has", r"\bmaximum hand size\b|\bhand size\b"),
    ("self cleanup (exile ~ / return ~ to hand)", "sim", "partial", r"^exile ~\.?$|\bexile ~\b|\breturn ~ to (?:its|their) owner's hand\b"),
    ("static rules text (other)", "sim", "lacks", r"\bcan't\b|\bcan\b|\bmay\b|\bdoesn't\b|\beach\b|\ball\b"),
]

# Trigger events goldfish.py reads (parse_trigger / combat_trigger). Groups: subj -> filter checked with perm_filt,
# spell -> parse_filter.
EVENTS_OK = [
    (r"^when(?:ever)? ~ enters(?: the battlefield)?(?: or (?:attacks|dies|is put into a graveyard from the battlefield))?$", None),
    (r"^when ~ enters and whenever .+$", None),
    (r"^when(?:ever)? ~ (?:is put into a graveyard from the battlefield|leaves the battlefield|dies)$", None),
    (r"^whenever ~ attacks(?: or blocks| or becomes the target of a spell(?: or ability)?(?: an opponent controls)?)?(?: alone)?$", None),
    (r"^whenever ~ and at least \w+ other creatures? attack$", None),
    (r"^whenever ~ deals combat damage to (?:a player|an opponent)(?: or (?:a )?(?:planeswalker|battle))?$", None),
    (r"^whenever (?:~|enchanted creature|equipped creature) deals damage(?: to (?:a player|an opponent))?$", None),
    (r"^when(?:ever)? (?:equipped|enchanted) creature (?:attacks|deals combat damage to (?:a player|an opponent)|dies)$", None),
    (r"^whenever you attack(?: a player| an opponent| one or more of your opponents)?$", None),
    (r"^whenever one or more (?P<subj>.+?) attack(?: a player| an opponent| one or more of your opponents)?$", "perm"),
    (r"^whenever one or more (?P<subj>.+?) deal combat damage to (?:a player|an opponent|one or more players)$", "perm"),
    (r"^whenever (?:a|an|another) (?P<subj>.+?) deals combat damage to (?:a player|an opponent)$", "perm"),
    (r"^whenever ~ attacks and isn't blocked$", None),
    (r"^whenever ~ becomes blocked(?: by a creature)?$", None),
    (r"^whenever (?:a|an|another) (?P<subj>.+?) becomes blocked$", "perm"),
    (r"^whenever (?:a|an|another) (?P<subj>.+?) attacks(?: alone)?$", "perm"),
    (r"^at the beginning of (?:combat on your turn|each combat)$", None),
    (r"^whenever (?:~ or )?(?:a|an|another|one or more(?: other)?) (?P<subj>.+?) (?:dies|die)$", "perm"),
    (r"^when(?:ever)? (?:~ or )?(?:a|an|another|one or more) (?P<subj>.+?) enters?(?: the battlefield)?(?: or attacks)?(?: under your control)?(?: this turn)?$", "perm"),
    (r"^whenever (?:you|a player) sacrifices? (?:a|an|another|one or more) (?P<subj>.+?)$", "perm"),
    (r"^whenever you gain life(?: for the first time each turn)?$", None),
    (r"^when you cast (?:this spell|~)$", None),
    (r"^at the beginning of (?:your|each|each player's) (?:upkeep|end step|draw step|(?:first|precombat) main phase)(?: on your turn)?$", None),
    (r"^whenever you cast (?:or copy )?(?:an|a|your first|your second)?\b ?(?P<spell>.*?)spells?(?: each turn)?(?: from [^,]+)?$", "spell"),
    (r"^when you cycle ~$", None),
    (r"^whenever (?:you|a player) cycles?(?: or discards?)? (?:a|another) card$", None),
    (r"^whenever you proliferate$", None),
    (r"^whenever an opponent casts their second spell each turn$", None),
    (r"^whenever an opponent casts (?:an|a|their first)\b ?(?P<spell>.*?)spells?(?: each turn)?$", "spell"),
    (r"^whenever an opponent draws a card$", None),
    (r"^whenever you draw a card$", None),
    (r"^whenever a player casts (?:an|a)\b ?(?P<spell>.*?)spells?$", "spell"),
    (r"^whenever a land an opponent controls enters$", None),
    (r"^whenever you tap (?:a|an) (?:land|permanent|creature) for mana$", None),
]

# Unsupported trigger events, named by what they listen for.
EVENT_CLASS = [
    ("event: is dealt damage", r"\bis dealt damage\b|\bare dealt damage\b|\bdealt damage\b"),
    ("event: blocks / becomes blocked (variants)", r"\bblocks?\b|\bblocked\b"),
    ("event: becomes the target", r"\bbecomes? the target\b"),
    ("event: becomes tapped / untapped", r"\bbecomes? (?:tapped|untapped)\b|\byou tap\b|\bis tapped\b|\buntaps?\b"),
    ("event: counters put or removed", r"\bcounters? (?:is|are) (?:put|placed|removed)\b|\bput one or more\b.*\bcounters?\b|\bcounter is put\b|\bremove (?:one or more )?[^,]*counters?\b"),
    ("event: activate an ability", r"\bactivate\b|\bactivates\b"),
    ("event: discard", r"\bdiscards?\b"),
    ("event: spells cast with conditions (Nth spell, targets, mana value, from zones)", r"\bcasts?\b|\bcopy\b"),
    ("event: attacks (variants: you, a player, while ...)", r"\battacks?\b"),
    ("event: combat damage (variants)", r"\bcombat damage\b|\bdeals damage\b"),
    ("event: dies / leaves / exiled / to graveyard (variants)", r"\bdies\b|\bdie\b|\bleaves?\b|\bexiled?\b|\bput into (?:a|your|an opponent's) graveyard\b|\bgraveyard from anywhere\b|\bmilled\b"),
    ("event: enters (variants)", r"\benters?\b|\bturned face up\b"),
    ("event: tokens created", r"\bcreate(?:s)? (?:one or more|a|an)? ?[^,]*tokens?\b"),
    ("event: life gained / lost (variants)", r"\bgains? life\b|\bloses? life\b|\blife total\b"),
    ("event: draw (variants: Nth card, opponents)", r"\bdraws?\b"),
    ("event: sacrifice (variants)", r"\bsacrifices?\b"),
    ("event: scry / surveil / mill / explore / investigate / other actions", r"\bscry\b|\bsurveil\b|\bmills?\b|\bexplores?\b|\binvestigate\b|\bconnive\b|\bexpend\b|\bcommit a crime\b|\bventure\b|\bcycle\b|\bsearch\b"),
    ("event: step or phase (variants: end of combat, second main, opponents' steps)", r"^at the beginning of\b|^at end of\b|^at the end of\b"),
    ("event: land / mana (landfall variants, tapped for mana)", r"\blands?\b|\bmana\b"),
    ("event: spell or ability resolves / chapter / level / roll", r"\bresolves?\b|\blevel\b|\broll\b|\bchapter\b"),
]

COST_CLASS = [
    ("cost: sacrifice a land or unread fodder", r"\bsacrifice (?:a|an|another|two|three|x|\w+) [^,:]*"),
    ("cost: discard", r"\bdiscard\b"),
    ("cost: exile from graveyard or hand", r"\bexile [^,:]*(?:from (?:your|a) graveyard|from your hand)\b"),
    ("cost: tap untapped creatures / permanents you control", r"\btap (?:an?|two|three|four|five|x|any number of|\w+) untapped\b"),
    ("cost: return a permanent to hand", r"\breturn [^,:]* to (?:its|their) owner'?s? hand\b"),
    ("cost: counters (remove X / put)", r"\bremove\b|\bput [^,:]*counters?\b"),
    ("cost: energy / other resource", r"\{e\}|\bpay \w+ energy\b"),
    ("cost: exert / mill / reveal / other", r"\bexert\b|\bmill\b|\breveal\b|\bpay\b|\{q\}|\bexile ~\b"),
]

COND_CLASS = [
    ("cond: 'as long as' static", r"\bas long as\b"),
    ("cond: morbid / a creature died this turn", r"\bdied this turn\b|\bdies this turn\b|\bput into (?:a|your) graveyard [^,]*this turn\b"),
    ("cond: spells cast this turn / storm count", r"\bcast [^,]*this turn\b|\bspells? (?:you've|you have|that player has) cast\b|\bsecond spell\b"),
    ("cond: delirium / card types in graveyard", r"\bcard types among\b|\bdelirium\b"),
    ("cond: revolt / permanent left the battlefield", r"\bleft the battlefield\b"),
    ("cond: adamant / mana spent", r"\bmana was spent\b|\bmana spent\b|\bwas spent to cast\b"),
    ("cond: attacking / blocking / tapped state of a creature", r"\battacking\b|\bblocking\b|\bis tapped\b|\bis untapped\b|\bblocked\b"),
    ("cond: cards drawn / life gained / damage dealt this turn", r"\bthis turn\b"),
    ("cond: opponents' state (life, cards, permanents)", r"\bopponents?\b|\bdefending player\b|\ba player\b|\beach player\b|\bthat player\b"),
    ("cond: you control / have (counts not read)", r"\byou control\b|\byou have\b|\byour graveyard\b|\byour hand\b|\byour library\b"),
    ("cond: this permanent's state (counters, power, attached)", r"\b~\b|\bit\b|\bequipped\b|\benchanted\b|\bits\b"),
    ("cond: from a zone / how it was cast", r"\bfrom (?:your|a|exile|the)\b|\bcast\b|\bkicked\b|\bgift\b|\bpromised\b"),
]

def first(table, t):
    for row in table:
        if re.search(row[-1], t): return row
    return None
