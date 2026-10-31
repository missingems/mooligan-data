---
archetype: modern-eldrazi
format: Modern
title: Eldrazi Ramp
author: Greg
written: 2026-10-18
updated: 2026-10-19
type: [ramp, combo]
---

## The deck

Eldrazi is the most played deck in Modern: 19.9% of the field over the last 30 days. It ramps with lands that make two colorless mana, and it has a two-card combo that makes as much mana as you like. Read it as two decks in one:

- **The ramp deck.** [[Eldrazi Temple]] and [[Ugin's Labyrinth]] each tap for {C}{C}. [[Sowing Mycospawn]] puts a land onto the battlefield as you cast it. By turn three or four you cast seven-drops like [[Devourer of Destiny]] and [[Sire of Seven Deaths]].
- **The combo deck.** [[Basking Broodscale]] wearing [[Blade of the Bloodchief]] turns every Eldrazi Spawn into another Spawn, a +1/+1 counter and {C}. That mana casts [[Emrakul, the Promised End]].

Most games you take whichever plan your opening hand supports, and switch when the opponent shows you how they mean to stop it.

## Main cards

:::cards
4 [[Basking Broodscale]] Combo piece. Makes a Spawn whenever it gets +1/+1 counters.
2 [[Blade of the Bloodchief]] Combo piece. A creature dying puts a counter on the equipped creature.
4 [[Urza's Saga]] Chapter III finds Blade, which costs {1}.
4 [[Eldrazi Temple]] {C}{C} for colorless Eldrazi spells and abilities.
4 [[Ugin's Labyrinth]] {C}{C} once a seven-drop is exiled with it.
4 [[Sowing Mycospawn]] Gets a land as you cast it. Kicked, it exiles one.
4 [[Kozilek's Command]] Instant-speed Spawns, removal, card draw or graveyard hate.
4 [[Malevolent Rumble]] Finds a permanent, makes a Spawn and fills the graveyard.
4 [[Emrakul, the Promised End]] The finisher. You take the opponent's next turn.
2 [[Devourer of Destiny]] Exiles a colored permanent as you cast it.
:::

## The combo

You need Broodscale with Blade attached and one Spawn. Sacrificing the Spawn is a mana ability. The two triggers that follow use the stack, so this loop runs as long as you choose.

```playgraph
flow "Broodscale + Blade: endless mana" verified
[[Basking Broodscale]] with [[Blade of the Bloodchief]] "Blade attached"
  -> "sacrifice a Spawn: {C}" -> token [[Eldrazi Spawn]] "dies"
  -> "Blade: +1/+1 counter" -> trigger "Broodscale: you may make a new Spawn"
  -> repeat "{∞} {C}, counters and Spawns"
note "Sacrificing a Spawn is a mana ability, so nobody can respond to it. Blade's trigger and Broodscale's trigger both use the stack, so the opponent can answer every trip."

panel "How opponents stop it" verified
[[Fatal Push]] "Kills Broodscale (mana value 2) with a trigger on the stack"
[[Thoughtseize]] "Takes Emrakul before you cast it"
[[Kozilek's Command]] "In the mirror: exiles Broodscale with X = 2"
footnote "Nobody can answer the Spawn's sacrifice, but they can answer every trigger in the loop."
end
```

### Putting it together

With no Spawn yet, Broodscale's own adapt ability starts the loop. [[Malevolent Rumble]] and [[Kozilek's Command]] make Spawns too, and any creature dying triggers Blade.

```playgraph
flow "Starting the loop" verified
[[Blade of the Bloodchief]] -> "equip {1}" -> [[Basking Broodscale]] "wearing Blade"
  -> "adapt {1}{G}" -> trigger "+1/+1 counter: make a Spawn"
  -> token [[Eldrazi Spawn]] "now sacrifice it"
[[Malevolent Rumble]] "makes a Spawn" + [[Kozilek's Command]] "makes X Spawns at instant speed"
  -> "or" -> state "Any creature dying triggers Blade"
```

### Turning the mana into a win

The loop's mana empties when the step ends, so spend it in the same main phase. Emrakul costs thirteen minus the card types in your graveyard. With the loop running, the cost doesn't matter.

```playgraph
flow "Turning the mana into a win" verified
mana "{∞} {C}" -> "cast" -> [[Emrakul, the Promised End]] "costs {1} less per card type in your graveyard"
  -> cast-trigger "You control the opponent during their next turn"
  -> "then they take an extra turn" -> win "A 13/13 flier with protection from instants"
```

## Ramp lines

[[Sowing Mycospawn]] has two cast triggers. Both happen as you cast it, before it resolves, so a counterspell on Mycospawn doesn't stop either one. Kicker costs {1}{C}, which [[Eldrazi Temple]] pays.

```playgraph
flow "Sowing Mycospawn, kicked" verified
[[Sowing Mycospawn]] "cast with kicker {1}{C}"
  -> cast-trigger "Put a land from your library onto the battlefield"
  + cast-trigger "Kicked: exile target land"
note "Both trigger as you cast it, so countering Mycospawn stops neither. You choose the order they go on the stack."
```

## Gotchas and tips

:::gotcha The loop has two openings
Sacrificing a Spawn uses no stack, but Blade's trigger and Broodscale's trigger both do. Removal on Broodscale in response to either trigger ends the loop with whatever mana you already made. Start it when the opponent is tapped out, or bait their answer first.
:::

:::tip Broodscale's trigger is optional
"You may create a Spawn." Stop the loop whenever you have enough.
:::

:::gotcha Mana empties between steps
The loop's {C} disappears at the end of the step. Cast what you need right away, in the same main phase.
:::

:::tip What Eldrazi Temple pays for
Temple's {C}{C} pays for colorless Eldrazi spells and abilities. That covers [[Basking Broodscale]]'s adapt (it has devoid, so it's colorless), [[Kozilek's Command]] (an Eldrazi kindred instant), [[Sowing Mycospawn]] and its kicker. It doesn't pay for [[Blade of the Bloodchief]], [[Malevolent Rumble]] or [[Ancient Stirrings]].
:::

:::tip Ugin's Labyrinth wants a seven-drop
Its imprint only happens as it enters. Exile [[Devourer of Destiny]], [[Sire of Seven Deaths]] or [[Emrakul, the Promised End]] from your hand to make it tap for {C}{C}. Its second ability returns that card to your hand when you're ready to cast it.
:::

:::tip Feeding Emrakul
Emrakul costs {1} less for each card type in your graveyard. [[Urza's Saga]] counts twice (enchantment and land). [[Malevolent Rumble]] puts the cards you don't take there, then goes there itself as a sorcery. [[Shifting Woodland]]'s delirium also wants four card types there.
:::

:::gotcha Cast triggers don't need the spell to resolve
[[Emrakul, the Promised End]], [[Devourer of Destiny]] and [[Sowing Mycospawn]] all trigger as you cast them. Countering the creature leaves the trigger on the stack.
:::

:::tip Urza's Saga's chapter III
It finds an artifact with mana cost {0} or {1}. [[Blade of the Bloodchief]] completes the combo, while [[Haywire Mite]], [[Soul-Guide Lantern]], [[Springleaf Drum]] and [[Vexing Bauble]] answer specific decks.
:::

## Matchups and sideboarding

Mooligan has no head-to-head records yet, so these list what to bring in and why, based on the 53 lists from the last 7 days.

:::matchup "Izzet Prowess" archetype=modern-izzet-prowess
about: Cheap spells and creatures that grow with every spell they cast.
key: [[Cori-Steel Cutter]], [[Dragon's Rage Channeler]]
in: 2 [[Trinisphere]], 2 [[Nature's Claim]]
out: 2 [[Devourer of Destiny]], 1 [[Soul-Guide Lantern]], 1 [[Vexing Bauble]]
Trinisphere makes each of their cheap spells cost three. Nature's Claim destroys Cori-Steel Cutter, and Urza's Saga can find Haywire Mite to exile it.
:::

:::matchup "Affinity" archetype=modern-affinity
about: Artifact aggro: cheap artifacts power out threats like Kappa Cannoneer.
key: [[Kappa Cannoneer]], [[Engineered Explosives]]
in: 2 [[Nature's Claim]], 1 [[Thief of Existence]]
out: 1 [[Soul-Guide Lantern]], 1 [[Vexing Bauble]], 1 [[Devourer of Destiny]]
Nature's Claim and Thief of Existence both hit artifacts. Thief only takes a noncreature, nonland permanent with mana value 4 or less.
:::

:::matchup "Goryo's Vengeance" archetype=modern-goryo-s-vengeance
about: Discards a huge creature like Atraxa, then returns it from the graveyard at instant speed.
key: [[Goryo's Vengeance]], [[Atraxa, Grand Unifier]]
in: 1 [[Grafdigger's Cage]], 2 [[Thought-Knot Seer]]
out: 2 [[Sire of Seven Deaths]], 1 [[Devourer of Destiny]]
Grafdigger's Cage stops creature cards entering from graveyards. Thought-Knot Seer takes the reanimation spell from their hand. Kozilek's Command can exile their graveyard at instant speed.
:::

:::matchup "Living End" archetype=modern-living-end
about: Cycles creatures into its graveyard, then cascades into Living End to bring them all back.
key: [[Shardless Agent]], [[Force of Negation]]
in: 1 [[Grafdigger's Cage]], 1 [[Vexing Bauble]], 1 [[Warping Wail]]
out: 2 [[Devourer of Destiny]], 1 [[Sire of Seven Deaths]]
Living End is a sorcery cast without paying its mana cost. Vexing Bauble counters a spell cast with no mana spent, and Warping Wail counters a sorcery. Cage stops the creatures coming back.
:::

:::matchup "Ruby Storm" archetype=modern-ruby-storm
about: Chains rituals and cost reducers into one turn of many spells.
key: [[Desperate Ritual]]
in: 2 [[Trinisphere]], 2 [[Thought-Knot Seer]], 1 [[Warping Wail]]
out: 2 [[Devourer of Destiny]], 2 [[Sire of Seven Deaths]], 1 [[Soul-Guide Lantern]]
Trinisphere makes Desperate Ritual cost three, so it nets no mana. Warping Wail counters a sorcery, and Thought-Knot Seer takes a key spell before they go off.
:::

:::matchup "Boros Energy" archetype=modern-boros-energy
about: Cheap creatures, energy and burn that start attacking on turn one.
key: [[Ajani, Nacatl Pariah]], [[Galvanic Discharge]]
in: 1 [[Sire of Seven Deaths]]
out: 1 [[Vexing Bauble]]
Sire's lifelink and first strike stop their attacks, and its ward makes them pay 7 life to target it.
:::

:::matchup "Eldrazi (mirror)" archetype=modern-eldrazi
about: The same ramp and Broodscale combo, so speed and disruption decide it.
key: [[Basking Broodscale]], [[Eldrazi Temple]]
in: 1 [[Pithing Needle]]
out: 1 [[Vexing Bauble]]
Pithing Needle naming Basking Broodscale stops its adapt, which isn't a mana ability. Kicked Mycospawn exiling their Temple or Labyrinth sets them back a turn.
:::
