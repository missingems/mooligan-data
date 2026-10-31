"""`guides --polish`: Claude rewrites data-built guides' summaries as prose, and changes nothing else.

Claude is sent each guide's own facts (each style's brackets, key cards and combos; each bracket's rules and the cards
that set it apart; once for each key or synergy card, its role and trimmed rules text) with the templated
summaries, and returns new summaries, plans and one note per key or synergy card through a tool. The cards, decks,
brackets and combos stay as the data made them.

The guides of a run go to Claude as one Message Batch, at half the price of single calls: `BatchPolisher` submits it,
polls until it ends (at most POLISH_WAIT_MINUTES), and hands back each guide's answer. A batch still running then is
kept in `state/polish-batch.json` and collected by the next run (see guides.py). A guide is sent only when its facts
changed since it was last polished (`polish_hash`, kept in `state/guides.json`). Each batch's tokens and dollars are logged.

It reads ANTHROPIC_API_KEY (and ANTHROPIC_WORKSPACE_ID for a key not scoped to one workspace) from the environment, and
never logs either. With no key, or GUIDE_POLISH=0, there is no polisher and the guides keep their templated summaries.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"
EFFORT = "low"
MAX_TOKENS = 16000
TOOL_NAME = "write_summaries"
KEY_CARDS = 12
ORACLE_CHARS = 200
WAIT_MINUTES = 30
POLL_SECONDS = 30
# Dollars per million tokens through the Batches API (half the standard price): input, output, cache write, cache read.
# Sonnet stays for a batch sent on it before the switch to Haiku and collected after.
BATCH_PRICES = {MODEL: (0.05, 0.25, 0.0625, 0.005), "claude-sonnet-5-5": (1.00, 5.00, 1.25, 0.10)}

TOOL = {
    "name": TOOL_NAME,
    "description": "Records the rewritten summaries of the guide's play styles and brackets, each deck's plan and a note for each card.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["styles", "brackets", "plans", "notes"],
        "properties": {
            "styles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "summary"],
                    "properties": {"id": {"type": "string"}, "summary": {"type": "string"}},
                },
            },
            "brackets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["level", "summary"],
                    "properties": {"level": {"type": "integer"}, "summary": {"type": "string"}},
                },
            },
            "plans": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["style", "level", "plan"],
                    "properties": {"style": {"type": "string"}, "level": {"type": "integer"}, "plan": {"type": "string"}},
                },
            },
            "notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "note"],
                    "properties": {"name": {"type": "string"}, "note": {"type": "string"}},
                },
            },
        },
    },
}

SYSTEM = """You are an expert Magic: The Gathering Commander writer. You are given one commander's guide as facts read from EDHREC and Commander Spellbook, with a plain templated summary for each play style and each Commander Bracket, and a list of the cards the decks feature with each one's role and rules text.

Call the write_summaries tool once, with a new summary for every style (by its id), every bracket (by its level), every deck's plan (by its style id and level) and a note for every card in the Cards list (by its name), and write nothing else.

Each summary is two or three sentences of plain, confident prose for a player choosing how to build the deck: for a style, what the deck does, the cards it relies on and how it wins, combos included; for a bracket, what the deck looks like at that power level.

Each deck's plan is one to three plain, complete sentences on how that style plays at that bracket and how it wins. Every sentence has a subject and a verb and reads on its own: no fragments, and no reference to something unspecified such as "the same engine" or "that package"; name the card or cards you mean. Explain how the deck wins in concrete steps (what it sets up, what that makes, what finishes the game), naming only cards listed for that deck. Take the winning step only from the deck's win lines: a win line wins as written, its pieces make the result and its outlet, when it has one, turns that into the win. A deck with no win line wins through its payoffs and combat: never give it a combo.

Each card's note says, in at most 70 characters, what the card does in these decks: its job in the plan, or its part in a win line it is in. It is a short phrase, not the card's name and not its rules text copied, for example "Makes a token whenever you cast a noncreature spell" or "Sac outlet for the Ballista loop". Write it from the card's role, its rules text and the win lines it is in, and from nothing else.

Use only the facts given: name only cards listed in the facts, keep every number as given, and never invent a combo, outlet, card or statistic. Never mention EDHREC, how many decks there are or what share of decks play something: go straight to what the deck does, how it wins, the cards it relies on and its combos."""


Lookup = Callable[[str], Optional[dict]]


def oracle_text(lookup: Optional[Lookup], name: str) -> str:
    """A card's rules text without reminder text, on one line and cut at ORACLE_CHARS."""
    text = ((lookup or (lambda _: None))(name) or {}).get("oracle_text") or ""
    text = " / ".join(line.strip() for line in re.sub(r"\s*\([^)]*\)", "", text).split("\n") if line.strip())
    return text if len(text) <= ORACLE_CHARS else text[:ORACLE_CHARS].rstrip() + "..."


def noted_cards(guide: dict) -> Dict[str, Optional[str]]:
    """Each key or synergy card of the guide's decks once, by name, with its role."""
    cards: Dict[str, Optional[str]] = {}
    for style in guide.get("styles") or []:
        for deck in style.get("lists") or []:
            for card in deck.get("key_cards") or []:
                cards.setdefault(card["name"], card.get("role"))
            for group in deck.get("synergy") or []:
                for card in group["cards"]:
                    cards.setdefault(card["name"], card.get("role") or group.get("role"))
    return cards


def facts(guide: dict, lookup: Optional[Lookup] = None) -> str:
    lines = [f"Commander: {guide['name']}", ""]
    cards = noted_cards(guide)
    if cards:
        lines.append("## Cards (one note each)")
        for name, role in cards.items():
            text = oracle_text(lookup, name)
            lines.append(f"- {name} ({role or 'utility'})" + (f": {text}" if text else ""))
        lines.append("")
    for style in guide.get("styles") or []:
        lines += [
            f"## Style {style['id']}: {style['name']}",
            f"Brackets: {', '.join(str(level) for level in style['brackets'])}.",
            "Key cards: " + ", ".join(f"{card['name']} ({card['role']})" for card in style["cards"][:KEY_CARDS]),
        ]
        lines += [f"Templated summary: {style['summary']}", ""]
        for deck in style.get("lists") or []:
            lines.append(f"### Deck {style['id']} at bracket {deck['level']}")
            if deck.get("key_cards"):
                lines.append("Key cards (what this bracket's deck adds): " + ", ".join(card["name"] for card in deck["key_cards"]))
            for group in deck.get("synergy") or []:
                lines.append(f"{group['name']}: " + ", ".join(card["name"] for card in group["cards"]))
            for line in deck.get("win_lines") or []:
                outlet = f" -> outlet {' + '.join(card['name'] for card in line['outlet'])}" if line["outlet"] else ""
                lines.append(f"Win line ({line['speed']}): {' + '.join(card['name'] for card in line['pieces'])} -> {line['result']}{outlet} -> {line['win']}")
            if not deck.get("win_lines"):
                lines.append("Win lines: none (it wins through its payoffs and combat)")
            if deck.get("plan"):
                lines.append(f"Templated plan: {deck['plan']}")
            lines.append("")
    for bracket in guide.get("brackets") or []:
        lines += [
            f"## Bracket {bracket['level']}: {bracket['name']}",
            "Cards that set it apart: " + ", ".join(card["name"] for card in bracket["cards"][:KEY_CARDS]),
            f"Templated summary: {bracket['summary']}",
            "",
        ]
    return "\n".join(lines)


def polish_hash(guide: dict, lookup: Optional[Lookup] = None) -> str:
    """What a polish is written from: the model, the instructions and the guide's facts. Equal hashes, equal summaries."""
    body = json.dumps({"model": MODEL, "system": SYSTEM, "tool": TOOL, "facts": facts(guide, lookup)}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def request(guide: dict, lookup: Optional[Lookup] = None) -> dict:
    """One guide's Messages request. The Batches API takes no fallbacks, and Sonnet 5.5 took no forced tool choice, so the
    tool is offered (`auto`, strict) and the instructions ask for it."""
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "output_config": {"effort": EFFORT},
        "tools": [TOOL],
        "tool_choice": {"type": "auto"},
        # The instructions are below the shortest prefix a cache holds, so the log's cache tokens stay 0 for now.
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": facts(guide, lookup)}],
    }


class PolishError(Exception):
    pass


def answer_of(message) -> dict:
    """The tool's input from a finished message."""
    if message.stop_reason in ("refusal", "max_tokens"):
        raise PolishError(f"stopped: {message.stop_reason}")
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
            return block.input
    raise PolishError(f"no {TOOL_NAME} call (stop reason {message.stop_reason})")


def apply(guide: dict, answer: dict, model: str) -> dict:
    """The guide with every summary Claude rewrote; a style or bracket it skipped keeps its templated one."""
    styles = {each.get("id"): str(each.get("summary") or "").strip() for each in answer.get("styles") or []}
    brackets = {each.get("level"): str(each.get("summary") or "").strip() for each in answer.get("brackets") or []}
    plans = {(each.get("style"), each.get("level")): str(each.get("plan") or "").strip() for each in answer.get("plans") or []}
    notes = {each.get("name"): str(each.get("note") or "").strip() for each in answer.get("notes") or []}

    def noted(card: dict) -> dict:
        return {**card, "note": notes[card["name"]]} if notes.get(card["name"]) else card

    def deck_of(style: dict, deck: dict) -> dict:
        changes = {}
        if "plan" in deck:
            changes["plan"] = plans.get((style["id"], deck["level"])) or deck.get("plan")
        if "key_cards" in deck:
            changes["key_cards"] = [noted(card) for card in deck["key_cards"]]
        if "synergy" in deck:
            changes["synergy"] = [{**group, "cards": [noted(card) for card in group["cards"]]} for group in deck["synergy"]]
        return {**deck, **changes}

    def style_of(style: dict) -> dict:
        lists = [deck_of(style, deck) for deck in style.get("lists") or []]
        return {**style, "summary": styles.get(style["id"]) or style["summary"], **({"lists": lists} if "lists" in style else {})}

    return {
        **guide,
        "model": model,
        "styles": [style_of(style) for style in guide["styles"]],
        "brackets": [{**bracket, "summary": brackets.get(bracket["level"]) or bracket["summary"]} for bracket in guide["brackets"]],
    }


def noted_in(deck: dict):
    """The (name, card) of a deck's key cards and synergy cards."""
    for card in deck.get("key_cards") or []:
        yield card["name"], card
    for group in deck.get("synergy") or []:
        for card in group["cards"]:
            yield card["name"], card


def carry_over(guide: dict, previous: Optional[dict]) -> Optional[dict]:
    """The guide with its last polish's summaries, when that polish had the same styles and brackets; else None."""
    if not previous or not previous.get("model"):
        return None
    styles = {style["id"]: style.get("summary") for style in previous.get("styles") or []}
    brackets = {bracket["level"]: bracket.get("summary") for bracket in previous.get("brackets") or []}

    def plans_of(document: dict) -> Dict[Tuple[str, int], Optional[str]]:
        return {(style["id"], deck["level"]): deck.get("plan") for style in document.get("styles") or [] for deck in style.get("lists") or [] if "plan" in deck}

    def notes_of(document: dict) -> Dict[str, Optional[str]]:
        return {name: card.get("note") for style in document.get("styles") or [] for deck in style.get("lists") or [] for name, card in noted_in(deck)}

    plans = plans_of(previous)
    notes = notes_of(previous)
    if (
        set(styles) != {style["id"] for style in guide["styles"]}
        or set(brackets) != {bracket["level"] for bracket in guide["brackets"]}
        or set(plans) != set(plans_of(guide))
        or set(notes) != set(notes_of(guide))
    ):
        return None
    answer = {
        "styles": [{"id": key, "summary": value} for key, value in styles.items()],
        "brackets": [{"level": key, "summary": value} for key, value in brackets.items()],
        "plans": [{"style": style, "level": level, "plan": value} for (style, level), value in plans.items()],
        "notes": [{"name": name, "note": value} for name, value in notes.items() if value],
    }
    return apply(guide, answer, previous["model"])


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, usage) -> None:
        for name in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            setattr(self, name, getattr(self, name) + (getattr(usage, name, 0) or 0))

    def dollars(self, model: str = MODEL) -> float:
        prices = BATCH_PRICES.get(model, BATCH_PRICES[MODEL])
        counts = (self.input_tokens, self.output_tokens, self.cache_creation_input_tokens, self.cache_read_input_tokens)
        return sum(count * price for count, price in zip(counts, prices)) / 1_000_000


@dataclass
class Batch:
    """A submitted batch: its id, the guide each request is for, and the polish hash each was asked from."""

    id: str
    slugs: Dict[str, str]
    hashes: Dict[str, str]

    def json(self) -> dict:
        return {"id": self.id, "slugs": self.slugs, "hashes": self.hashes}

    @staticmethod
    def of(body: dict) -> "Batch":
        return Batch(body["id"], dict(body.get("slugs") or {}), dict(body.get("hashes") or {}))


@dataclass
class Collected:
    """What an ended batch gave: each polished guide's answer and model by slug, why the others were not, its tokens and
    what it cost at batch prices."""

    answers: Dict[str, Tuple[dict, str]] = field(default_factory=dict)
    failed: Dict[str, str] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    dollars: float = 0.0


@dataclass
class BatchPolisher:
    client: object
    wait_minutes: float = WAIT_MINUTES
    poll_seconds: float = POLL_SECONDS
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    lookup: Optional[Lookup] = None

    def submit(self, guides: List[dict]) -> Batch:
        # A slug can pass the 64 characters a custom_id may have, so the requests are numbered.
        slugs = {f"g{index}": guide["slug"] for index, guide in enumerate(guides)}
        batch = self.client.messages.batches.create(
            requests=[{"custom_id": custom_id, "params": request(guide, self.lookup)} for custom_id, guide in zip(slugs, guides)]
        )
        log.info("Polish: batch %s submitted with %d guides", batch.id, len(guides))
        return Batch(batch.id, slugs, {guide["slug"]: polish_hash(guide, self.lookup) for guide in guides})

    def ended(self, batch: Batch) -> bool:
        return self.client.messages.batches.retrieve(batch.id).processing_status == "ended"

    def wait(self, batch: Batch) -> bool:
        """True once the batch has ended; False when it is still running after `wait_minutes`."""
        deadline = self.clock() + self.wait_minutes * 60
        while not self.ended(batch):
            if self.clock() >= deadline:
                log.warning("Polish: batch %s is still running after %.0f minutes; the next run collects it", batch.id, self.wait_minutes)
                return False
            self.sleep(self.poll_seconds)
        return True

    def collect(self, batch: Batch) -> Collected:
        collected = Collected()
        for result in self.client.messages.batches.results(batch.id):
            slug = batch.slugs.get(result.custom_id)
            if slug is None:
                continue
            if result.result.type != "succeeded":
                collected.failed[slug] = result.result.type
                continue
            message = result.result.message
            priced = Usage()
            priced.add(message.usage)
            collected.usage.add(message.usage)
            collected.dollars += priced.dollars(message.model)
            try:
                collected.answers[slug] = (answer_of(message), message.model)
            except PolishError as error:
                collected.failed[slug] = str(error)
        usage = collected.usage
        log.info(
            "Polish: batch %s: %d polished, %d kept templated; tokens: %d input, %d output, %d cache write, %d cache read; cost $%.4f",
            batch.id, len(collected.answers), len(collected.failed), usage.input_tokens, usage.output_tokens,
            usage.cache_creation_input_tokens, usage.cache_read_input_tokens, collected.dollars,
        )
        for slug, reason in sorted(collected.failed.items()):
            log.warning("Polish %s failed, keeping the templated summaries: %s", slug, reason)
        return collected


def make_polisher() -> Optional[BatchPolisher]:
    """The batch polisher, or None when there is no ANTHROPIC_API_KEY or GUIDE_POLISH=0."""
    if os.environ.get("GUIDE_POLISH", "1") == "0":
        return None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic

    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    return BatchPolisher(
        anthropic.Anthropic(api_key=key, default_headers=headers),
        wait_minutes=float(os.environ.get("POLISH_WAIT_MINUTES", WAIT_MINUTES)),
    )


if __name__ == "__main__":
    import sys

    print(facts(json.loads(open(sys.argv[1]).read())))
