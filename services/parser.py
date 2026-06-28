"""Question parser for free-text decision queries."""

from services.ontology import UNIVERSAL_METRICS, suggest_criteria, extract_alternatives


def parse_question(query: str) -> dict:
    """Parse a free-text decision question.

    Returns: {
        "alternatives": ["House", "Apartment"],
        "criteria": [{"name": "Cost", ...}, ...],
        "category": "General",
        "parsed": True
    }
    """
    alternatives = extract_alternatives(query)
    category, criteria = suggest_criteria(query)

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
