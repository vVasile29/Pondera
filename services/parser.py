"""Question parser for free-text decision queries."""

from services.ontology import GENERIC_CRITERIA, suggest_criteria, extract_alternatives


def parse_question(query: str) -> dict:
    """Parse a free-text decision question.

    Returns: {
        "alternatives": ["House", "Apartment"],
        "criteria": [{"name": "Cost", ...}, ...],
        "category": "Housing",
        "parsed": True
    }
    """
    alternatives = extract_alternatives(query)
    category, criteria = suggest_criteria(query)

    if not alternatives:
        return {
            "parsed": False,
            "alternatives": ["Option A", "Option B"],
            "criteria": GENERIC_CRITERIA,
            "category": "General",
        }

    return {
        "parsed": True,
        "alternatives": alternatives,
        "criteria": criteria,
        "category": category,
    }
