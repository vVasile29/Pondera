"""Question parser for free-text decision queries."""

import re

from services.ontology import (
    UNIVERSAL_METRICS,
    extract_alternatives,
    get_universal_criteria,
)


def extract_subject(query: str) -> dict:
    """Extract single subject + optional goal from DIAGNOSE-style queries.

    Patterns (ordered most-specific first):
      - "How good is {subject} for {goal}"
      - "How does {subject} perform for {goal}"
      - "How good is {subject}"
      - "How does {subject} perform"
      - "Rate my {subject}"
      - "Evaluate {subject}"
      - "Review {subject}"
      - "What do you think about {subject}"

    Returns: {
        "subject": "Tesla Model 3",
        "goal": "commuting" or None,
        "parsed": True
    }
    or on no match: {
        "subject": "This option",
        "goal": None,
        "parsed": False
    }
    """
    query = query.strip()
    if not query:
        return {"subject": "This option", "goal": None, "parsed": False}

    # Strip trailing question mark
    clean = query.rstrip("?")

    patterns = [
        # Most specific first — with goal (article optional)
        (r"^how\s+good\s+is\s+(?:(?:a|an|the)\s+)?(.+?)\s+for\s+(.+)$", True),
        (r"^how\s+does\s+(?:(?:a|an|the)\s+)?(.+?)\s+perform\s+for\s+(.+)$", True),
        # Without goal (article optional)
        (r"^how\s+good\s+is\s+(?:(?:a|an|the)\s+)?(.+)$", False),
        (r"^how\s+does\s+(?:(?:a|an|the)\s+)?(.+?)\s+perform$", False),
        (r"^rate\s+my\s+(.+)$", False),
        (r"^evaluate\s+(.+)$", False),
        (r"^review\s*(.+)$", False),
        (r"^what\s+do\s+you\s+think\s+about\s+(?:(?:a|an|the)\s+)?(.+)$", False),
    ]

    for pattern, has_goal in patterns:
        match = re.match(pattern, clean, re.IGNORECASE)
        if match:
            subject = match.group(1).strip()
            goal = match.group(2).strip() if has_goal else None

            # Clean up leading articles from subject
            subject = re.sub(
                r"^(a|an|the)\s+", "", subject, flags=re.IGNORECASE
            ).strip()

            if not subject:
                return {"subject": "This option", "goal": goal, "parsed": False}

            return {"subject": subject, "goal": goal, "parsed": True}

    # No pattern matched
    return {"subject": "This option", "goal": None, "parsed": False}


def extract_list(query: str) -> dict:
    """Detects and extracts alternatives from list-style input.

    Handles:
      - Comma-separated: "Python, Java, Go, Rust"
      - Newline-separated: multi-line text with each alternative on its own line
      - Numbered lists: "1. Python\\n2. Java\\n3. Go" or "1) Python\\n2) Java"
      - "Rank/Order" prefix: "Rank: Python, Java, Go" — strip prefix word
      - Mixed (comma + newline): "Python, Java\\nGo"

    Returns: {
        "alternatives": ["Python", "Java", "Go"],
        "parsed": True/False
    }
    """
    query = query.strip()
    if not query:
        return {"alternatives": [], "parsed": False}

    # Remove common prefixes
    prefixes = [
        r"^(?:rank|order|list|compare|sort|rate)\s*[:;]\s*",
        r"^(?:rank|order|list|compare|sort|rate)\s+",
    ]
    for prefix in prefixes:
        query = re.sub(prefix, "", query, flags=re.IGNORECASE).strip()

    def clean_item(text: str) -> str:
        text = text.strip().strip(".,;:!?\"'")
        text = re.sub(r"^\d+[.)]\s*", "", text).strip()
        if text and text[0].islower():
            text = text[0].upper() + text[1:]
        return text

    # Strategy 1: Split by newlines (multi-line input)
    if "\n" in query:
        lines = [line.strip() for line in query.split("\n") if line.strip()]
        candidates = [clean_item(line) for line in lines if clean_item(line)]
        if len(candidates) >= 3:
            return {"alternatives": candidates, "parsed": True}

    # Strategy 2: Split by comma
    if "," in query:
        parts = [p.strip() for p in query.split(",") if p.strip()]
        candidates = [clean_item(p) for p in parts if clean_item(p)]
        if len(candidates) >= 3:
            return {"alternatives": candidates, "parsed": True}

    # Strategy 3: Split by newlines (after comma split failed)
    if "\n" in query:
        lines = [line.strip() for line in query.split("\n") if line.strip()]
        candidates = [clean_item(line) for line in lines if clean_item(line)]
        if len(candidates) >= 3:
            return {"alternatives": candidates, "parsed": True}

    # Strategy 4: Split by numbered list patterns on a single line
    numbered_match = re.findall(r"\d+[.)]\s*([^,;\n]+?)(?=\s*\d+[.)]\s*|$)", query)
    if numbered_match:
        candidates = [clean_item(m) for m in numbered_match if clean_item(m)]
        if len(candidates) >= 3:
            return {"alternatives": candidates, "parsed": True}

    return {"alternatives": [], "parsed": False}


def parse_question(query: str) -> dict:
    """Parse a free-text decision question.

    Returns: {
        "alternatives": ["House", "Apartment"],
        "criteria": [{"name": "Affordability", ...}, ...],
        "category": "General",
        "parsed": True
    }
    """
    alternatives = extract_alternatives(query)
    category, criteria = get_universal_criteria()

    if not alternatives:
        return {
            "parsed": False,
            "alternatives": ["Option A", "Option B"],
            "criteria": UNIVERSAL_METRICS,
            "category": "General",
        }

    return {
        "parsed": True,
        "alternatives": alternatives,
        "criteria": criteria,
        "category": category,
    }
