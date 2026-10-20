"""`guides --polish`: Claude rewrites a data-built guide's summaries as prose, and changes nothing else.

Claude is sent the guide's own facts (each style's decks, brackets, key cards and combos; each bracket's decks and the
cards that set it apart) with the templated summaries, and returns new summaries through a tool. The cards, decks,
brackets and combos stay as the data made them. It reads ANTHROPIC_API_KEY (and ANTHROPIC_WORKSPACE_ID for a key not
scoped to one workspace) from the environment.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-5-5"
EFFORT = "low"
MAX_TOKENS = 8000
BETAS = ["server-side-fallback-2026-07-01"]
TOOL_NAME = "write_summaries"
KEY_CARDS = 12

TOOL = {
    "name": TOOL_NAME,
    "description": "Records the rewritten summaries of the guide's play styles and brackets.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["styles", "brackets"],
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
        },
    },
}

SYSTEM = """You are an expert Magic: The Gathering Commander writer. You are given one commander's guide as facts read from EDHREC and Commander Spellbook, with a plain templated summary for each play style and each Commander Bracket.

Call the write_summaries tool once, with a new summary for every style (by its id) and every bracket (by its level), and write nothing else.

Each summary is two or three sentences of plain, confident prose for a player choosing how to build the deck: for a style, its plan and how it wins; for a bracket, what the deck looks like at that power level. Use only the facts given: name only cards listed in the facts, keep every number as given, and never invent a combo, card or statistic."""


def facts(guide: dict) -> str:
    lines = [f"Commander: {guide['name']} ({guide.get('decks', 0):,} decks on EDHREC)", ""]
    combos = {combo["id"]: combo for combo in guide.get("combos") or []}
    for style in guide.get("styles") or []:
        lines += [
            f"## Style {style['id']}: {style['name']}",
            f"Decks: {style.get('decks', 0):,}. Brackets: {', '.join(str(level) for level in style['brackets'])}.",
            "Key cards: " + ", ".join(f"{card['name']} ({card['role']})" for card in style["cards"][:KEY_CARDS]),
        ]
        ids = list(dict.fromkeys(each for deck in style.get("lists") or [] for each in deck.get("combos") or []))
        for combo in (combos[each] for each in ids if each in combos):
            lines.append(f"Combo (bracket {combo['bracket']}): {' + '.join(card['name'] for card in combo['cards'])} -> {', '.join(combo['results'])}")
        lines += [f"Templated summary: {style['summary']}", ""]
    for bracket in guide.get("brackets") or []:
        lines += [
            f"## Bracket {bracket['level']}: {bracket['name']}",
            f"Decks: {bracket.get('decks', 0):,}. Cards that set it apart: " + ", ".join(card["name"] for card in bracket["cards"][:KEY_CARDS]),
            f"Templated summary: {bracket['summary']}",
            "",
        ]
    return "\n".join(lines)


def request(guide: dict) -> dict:
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "betas": BETAS,
        "fallbacks": "default",
        "output_config": {"effort": EFFORT},
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": TOOL_NAME},
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": facts(guide)}],
    }


class PolishError(Exception):
    pass


def ask(client, call: dict):
    """The tool's input and the model that answered."""
    with client.beta.messages.stream(**call) as stream:
        message = stream.get_final_message()
    if message.stop_reason in ("refusal", "max_tokens"):
        raise PolishError(f"stopped: {message.stop_reason}")
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
            return block.input, message.model
    raise PolishError(f"no {TOOL_NAME} call (stop reason {message.stop_reason})")


def apply(guide: dict, answer: dict, model: str) -> dict:
    """The guide with every summary Claude rewrote; a style or bracket it skipped keeps its templated one."""
    styles = {each.get("id"): str(each.get("summary") or "").strip() for each in answer.get("styles") or []}
    brackets = {each.get("level"): str(each.get("summary") or "").strip() for each in answer.get("brackets") or []}
    return {
        **guide,
        "model": model,
        "styles": [{**style, "summary": styles.get(style["id"]) or style["summary"]} for style in guide["styles"]],
        "brackets": [{**bracket, "summary": brackets.get(bracket["level"]) or bracket["summary"]} for bracket in guide["brackets"]],
    }


@dataclass
class Polisher:
    client: object

    def __call__(self, guide: dict) -> dict:
        try:
            answer, model = ask(self.client, request(guide))
        except Exception as error:  # noqa: BLE001 - the templated guide is still a guide
            log.warning("Polish %s failed, keeping the templated summaries: %s", guide.get("slug"), error)
            return guide
        return apply(guide, answer, model)


def make_polisher() -> Optional[Callable[[dict], dict]]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic

    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    return Polisher(anthropic.Anthropic(api_key=key, default_headers=headers))


if __name__ == "__main__":
    import sys

    print(facts(json.loads(open(sys.argv[1]).read())))
