"""`guides --polish`: Claude rewrites data-built guides' summaries as prose, and changes nothing else.

Claude is sent each guide's own facts (each style's decks, brackets, key cards and combos; each bracket's decks and the
cards that set it apart) with the templated summaries, and returns new summaries through a tool. The cards, decks,
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
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-5-5"
EFFORT = "low"
MAX_TOKENS = 12000
TOOL_NAME = "write_summaries"
KEY_CARDS = 12
WAIT_MINUTES = 30
POLL_SECONDS = 30
# Dollars per million tokens through the Batches API (half the standard price): input, output, cache write, cache read.
BATCH_PRICES = {MODEL: (1.00, 5.00, 1.25, 0.10)}

TOOL = {
    "name": TOOL_NAME,
    "description": "Records the rewritten summaries of the guide's play styles and brackets.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["styles", "brackets", "plans"],
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
        },
    },
}

SYSTEM = """You are an expert Magic: The Gathering Commander writer. You are given one commander's guide as facts read from EDHREC and Commander Spellbook, with a plain templated summary for each play style and each Commander Bracket.

Call the write_summaries tool once, with a new summary for every style (by its id), every bracket (by its level) and every deck's plan (by its style id and level), and write nothing else.

Each summary is two or three sentences of plain, confident prose for a player choosing how to build the deck: for a style, its plan and how it wins; for a bracket, what the deck looks like at that power level. Each deck's plan is one or two sentences on how that style plays at that bracket and how it wins, from that deck's key cards, synergy groups and win lines. A win line wins as written: its pieces make the result, and its outlet, when it has one, turns that into the win. A deck with no win line wins through its payoffs and combat: never give it a combo. Use only the facts given: name only cards listed in the facts, keep every number as given, and never invent a combo, outlet, card or statistic."""


def facts(guide: dict) -> str:
    lines = [f"Commander: {guide['name']} ({guide.get('decks', 0):,} decks on EDHREC)", ""]
    for style in guide.get("styles") or []:
        lines += [
            f"## Style {style['id']}: {style['name']}",
            f"Decks: {style.get('decks', 0):,}. Brackets: {', '.join(str(level) for level in style['brackets'])}.",
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
            f"Decks: {bracket.get('decks', 0):,}. Cards that set it apart: " + ", ".join(card["name"] for card in bracket["cards"][:KEY_CARDS]),
            f"Templated summary: {bracket['summary']}",
            "",
        ]
    return "\n".join(lines)


def polish_hash(guide: dict) -> str:
    """What a polish is written from: the model, the instructions and the guide's facts. Equal hashes, equal summaries."""
    body = json.dumps({"model": MODEL, "system": SYSTEM, "tool": TOOL, "facts": facts(guide)}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def request(guide: dict) -> dict:
    """One guide's Messages request. The Batches API takes no fallbacks, and this model no forced tool choice, so the
    tool is offered (`auto`, strict) and the instructions ask for it."""
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "output_config": {"effort": EFFORT},
        "tools": [TOOL],
        "tool_choice": {"type": "auto"},
        # The instructions are below the shortest prefix a cache holds, so the log's cache tokens stay 0 for now.
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": facts(guide)}],
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

    def style_of(style: dict) -> dict:
        lists = [{**deck, "plan": plans.get((style["id"], deck["level"])) or deck.get("plan")} if "plan" in deck else deck for deck in style.get("lists") or []]
        return {**style, "summary": styles.get(style["id"]) or style["summary"], **({"lists": lists} if "lists" in style else {})}

    return {
        **guide,
        "model": model,
        "styles": [style_of(style) for style in guide["styles"]],
        "brackets": [{**bracket, "summary": brackets.get(bracket["level"]) or bracket["summary"]} for bracket in guide["brackets"]],
    }


def carry_over(guide: dict, previous: Optional[dict]) -> Optional[dict]:
    """The guide with its last polish's summaries, when that polish had the same styles and brackets; else None."""
    if not previous or not previous.get("model"):
        return None
    styles = {style["id"]: style.get("summary") for style in previous.get("styles") or []}
    brackets = {bracket["level"]: bracket.get("summary") for bracket in previous.get("brackets") or []}

    def plans_of(document: dict) -> Dict[Tuple[str, int], Optional[str]]:
        return {(style["id"], deck["level"]): deck.get("plan") for style in document.get("styles") or [] for deck in style.get("lists") or [] if "plan" in deck}

    plans = plans_of(previous)
    if (
        set(styles) != {style["id"] for style in guide["styles"]}
        or set(brackets) != {bracket["level"] for bracket in guide["brackets"]}
        or set(plans) != set(plans_of(guide))
    ):
        return None
    answer = {
        "styles": [{"id": key, "summary": value} for key, value in styles.items()],
        "brackets": [{"level": key, "summary": value} for key, value in brackets.items()],
        "plans": [{"style": style, "level": level, "plan": value} for (style, level), value in plans.items()],
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
    """What an ended batch gave: each polished guide's answer and model by slug, and why the others were not."""

    answers: Dict[str, Tuple[dict, str]] = field(default_factory=dict)
    failed: Dict[str, str] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)


@dataclass
class BatchPolisher:
    client: object
    wait_minutes: float = WAIT_MINUTES
    poll_seconds: float = POLL_SECONDS
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def submit(self, guides: List[dict]) -> Batch:
        # A slug can pass the 64 characters a custom_id may have, so the requests are numbered.
        slugs = {f"g{index}": guide["slug"] for index, guide in enumerate(guides)}
        batch = self.client.messages.batches.create(
            requests=[{"custom_id": custom_id, "params": request(guide)} for custom_id, guide in zip(slugs, guides)]
        )
        log.info("Polish: batch %s submitted with %d guides", batch.id, len(guides))
        return Batch(batch.id, slugs, {guide["slug"]: polish_hash(guide) for guide in guides})

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
            collected.usage.add(message.usage)
            try:
                collected.answers[slug] = (answer_of(message), message.model)
            except PolishError as error:
                collected.failed[slug] = str(error)
        usage = collected.usage
        log.info(
            "Polish: batch %s: %d polished, %d kept templated; tokens: %d input, %d output, %d cache write, %d cache read; cost $%.4f",
            batch.id, len(collected.answers), len(collected.failed), usage.input_tokens, usage.output_tokens,
            usage.cache_creation_input_tokens, usage.cache_read_input_tokens, usage.dollars(),
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
