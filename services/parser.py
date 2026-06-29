"""Question parser for free-text decision queries."""

import re

from services.ontology import UNIVERSAL_METRICS, suggest_criteria, extract_alternatives


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


def extract_thresholds(query: str) -> list[dict]:
    """Detects per-criterion threshold constraints from free text. (Backward-compatible)

    Patterns:
      - "Cost <= 60", "cost < 30" (metric + operator + value)
      - "at least 70 Quality", "minimum quality 80" (keyword + value + metric)

    Operator aliases:
      - "<=", "<": both mapped to "<=" for simplicity (less-than threshold)
      - ">=", ">": both mapped to ">=" for simplicity (greater-than threshold)
      - "at least", "minimum", "min": mapped to ">="
      - "at most", "maximum", "max": mapped to "<="

    Returns: [
        {"metric_name": "Cost", "operator": "<=", "value": 60.0},
        ...
    ]
    """
    from services.ontology import UNIVERSAL_METRICS

    metric_names = [m["name"] for m in UNIVERSAL_METRICS]

    patterns = [
        # Pattern 1: "metric operator value" (e.g., "Cost <= 60")
        r"(?P<metric1>[A-Za-z ]+?)\s*(?P<op1><=|>=|<|>)\s*(?P<val1>\d+(?:\.\d+)?)",
        # Pattern 2: "at least / at most / minimum / maximum value metric" (e.g., "at least 80 quality")
        r"(?P<keyword>at\s+least|at\s+most|minimum|maximum|min|max)\s+(?P<val2>\d+(?:\.\d+)?)\s+(?P<metric2>[A-Za-z ]+)",
        # Pattern 3: "keyword metric value" (e.g., "maximum cost 50", "minimum quality 75")
        r"(?P<keyword3>at\s+least|at\s+most|minimum|maximum|min|max)\s+(?P<metric3>[A-Za-z ]+?)\s+(?P<val3>\d+(?:\.\d+)?)",
    ]

    results = []
    seen = set()

    def fuzzy_match(name: str) -> str | None:
        """Fuzzy match a name against universal metric names."""
        name_clean = name.strip().lower()
        # Direct match
        for mn in metric_names:
            if mn.lower() == name_clean:
                return mn
        # Partial match (one contains the other)
        for mn in metric_names:
            if name_clean in mn.lower() or mn.lower() in name_clean:
                return mn
        return None

    # Pattern 1: metric operator value
    for match in re.finditer(patterns[0], query, re.IGNORECASE):
        raw_metric = match.group("metric1").strip()
        op = match.group("op1")
        val = float(match.group("val1"))
        metric_name = fuzzy_match(raw_metric)
        if metric_name:
            key = (metric_name, op, val)
            if key not in seen:
                seen.add(key)
                results.append(
                    {
                        "metric_name": metric_name,
                        "operator": op,
                        "value": val,
                    }
                )

    # Pattern 2: keyword value metric (e.g., "at least 80 quality")
    for match in re.finditer(patterns[1], query, re.IGNORECASE):
        keyword = match.group("keyword").lower().replace("at ", "").replace(" ", "")
        raw_metric = match.group("metric2").strip()
        val = float(match.group("val2"))
        metric_name = fuzzy_match(raw_metric)
        if metric_name:
            op = ">=" if keyword in ("least", "minimum", "min") else "<="
            key = (metric_name, op, val)
            if key not in seen:
                seen.add(key)
                results.append(
                    {
                        "metric_name": metric_name,
                        "operator": op,
                        "value": val,
                    }
                )

    # Pattern 3: keyword metric value (e.g., "maximum cost 50")
    for match in re.finditer(patterns[2], query, re.IGNORECASE):
        keyword = match.group("keyword3").lower().replace("at ", "").replace(" ", "")
        raw_metric = match.group("metric3").strip()
        val = float(match.group("val3"))
        metric_name = fuzzy_match(raw_metric)
        if metric_name:
            op = ">=" if keyword in ("least", "minimum", "min") else "<="
            key = (metric_name, op, val)
            if key not in seen:
                seen.add(key)
                results.append(
                    {
                        "metric_name": metric_name,
                        "operator": op,
                        "value": val,
                    }
                )

    return results


def extract_thresholds_detailed(query: str) -> dict:
    """Extract thresholds with detailed validation metadata.

    Like extract_thresholds() but returns structured information about
    valid thresholds, unknown metric constraints, and out-of-range values.

    Supports optional '%' suffix on numeric values (stripped before parsing).

    Returns: {
        "valid": [
            {"metric_name": "Cost", "operator": "<=", "value": 60.0},
        ],
        "unknown": [
            {"raw_text": "popularity > 100", "metric_name": "popularity",
             "operator": ">", "value_str": "100"},
        ],
        "out_of_range": [
            {"metric_name": "Quality", "operator": ">=", "value": 150.0,
             "reason": "value > 100"},
        ],
    }
    """
    from services.ontology import UNIVERSAL_METRICS

    metric_names = [m["name"] for m in UNIVERSAL_METRICS]

    # Patterns with optional % suffix
    patterns = [
        # Pattern 1: "metric operator value" (e.g., "Cost <= 60%")
        r"(?P<metric1>[A-Za-z ]+?)\s*(?P<op1><=|>=|<|>)\s*(?P<val1>\d+(?:\.\d+)?)\s*%?",
        # Pattern 2: "at least / at most / minimum / maximum value metric" (e.g., "at least 80% quality")
        r"(?P<keyword>at\s+least|at\s+most|minimum|maximum|min|max)\s+(?P<val2>\d+(?:\.\d+)?)\s*%?\s+(?P<metric2>[A-Za-z ]+)",
        # Pattern 3: "keyword metric value" (e.g., "maximum cost 50%", "minimum quality 75%")
        r"(?P<keyword3>at\s+least|at\s+most|minimum|maximum|min|max)\s+(?P<metric3>[A-Za-z ]+?)\s+(?P<val3>\d+(?:\.\d+)?)\s*%?",
    ]

    valid = []
    unknown = []
    out_of_range = []
    seen = set()
    seen_unknown = set()

    def fuzzy_match(name: str) -> str | None:
        """Fuzzy match a name against universal metric names."""
        name_clean = name.strip().lower()
        # Direct match
        for mn in metric_names:
            if mn.lower() == name_clean:
                return mn
        # Partial match (one contains the other)
        for mn in metric_names:
            if name_clean in mn.lower() or mn.lower() in name_clean:
                return mn
        return None

    # Strip common connector words from raw metric names before matching
    _CONNECTORS_RE = re.compile(r"^(?:and|or|&\s*)\s*", re.IGNORECASE)

    # Pattern 1: metric operator value
    for match in re.finditer(patterns[0], query, re.IGNORECASE):
        raw_metric = _CONNECTORS_RE.sub("", match.group("metric1").strip()).strip()
        op = match.group("op1")
        val_str = match.group("val1")
        val = float(val_str)
        metric_name = fuzzy_match(raw_metric)
        if metric_name:
            if val < 0.0 or val > 100.0:
                reason = "value < 0" if val < 0 else "value > 100"
                out_of_range.append(
                    {
                        "metric_name": metric_name,
                        "operator": op,
                        "value": val,
                        "reason": reason,
                    }
                )
            else:
                key = (metric_name, op, val)
                if key not in seen:
                    seen.add(key)
                    valid.append(
                        {
                            "metric_name": metric_name,
                            "operator": op,
                            "value": val,
                        }
                    )
        else:
            raw_text = f"{raw_metric} {op} {val_str}"
            unk_key = raw_text.lower()
            if unk_key not in seen_unknown:
                seen_unknown.add(unk_key)
                unknown.append(
                    {
                        "raw_text": raw_text,
                        "metric_name": raw_metric,
                        "operator": op,
                        "value_str": val_str,
                    }
                )

    # Pattern 2: keyword value metric (e.g., "at least 80% quality")
    for match in re.finditer(patterns[1], query, re.IGNORECASE):
        keyword = match.group("keyword").lower().replace("at ", "").replace(" ", "")
        raw_metric = match.group("metric2").strip()
        val_str = match.group("val2")
        val = float(val_str)
        metric_name = fuzzy_match(raw_metric)
        if metric_name:
            op = ">=" if keyword in ("least", "minimum", "min") else "<="
            if val < 0.0 or val > 100.0:
                reason = "value < 0" if val < 0 else "value > 100"
                out_of_range.append(
                    {
                        "metric_name": metric_name,
                        "operator": op,
                        "value": val,
                        "reason": reason,
                    }
                )
            else:
                key = (metric_name, op, val)
                if key not in seen:
                    seen.add(key)
                    valid.append(
                        {
                            "metric_name": metric_name,
                            "operator": op,
                            "value": val,
                        }
                    )
        else:
            op = ">=" if keyword in ("least", "minimum", "min") else "<="
            raw_text = f"{keyword} {val_str} {raw_metric}"
            unk_key = raw_text.lower()
            if unk_key not in seen_unknown:
                seen_unknown.add(unk_key)
                unknown.append(
                    {
                        "raw_text": raw_text,
                        "metric_name": raw_metric,
                        "operator": op,
                        "value_str": val_str,
                    }
                )

    # Pattern 3: keyword metric value (e.g., "maximum cost 50%")
    for match in re.finditer(patterns[2], query, re.IGNORECASE):
        keyword = match.group("keyword3").lower().replace("at ", "").replace(" ", "")
        raw_metric = match.group("metric3").strip()
        val_str = match.group("val3")
        val = float(val_str)
        metric_name = fuzzy_match(raw_metric)
        if metric_name:
            op = ">=" if keyword in ("least", "minimum", "min") else "<="
            if val < 0.0 or val > 100.0:
                reason = "value < 0" if val < 0 else "value > 100"
                out_of_range.append(
                    {
                        "metric_name": metric_name,
                        "operator": op,
                        "value": val,
                        "reason": reason,
                    }
                )
            else:
                key = (metric_name, op, val)
                if key not in seen:
                    seen.add(key)
                    valid.append(
                        {
                            "metric_name": metric_name,
                            "operator": op,
                            "value": val,
                        }
                    )
        else:
            op = ">=" if keyword in ("least", "minimum", "min") else "<="
            raw_text = f"{keyword} {raw_metric} {val_str}"
            unk_key = raw_text.lower()
            if unk_key not in seen_unknown:
                seen_unknown.add(unk_key)
                unknown.append(
                    {
                        "raw_text": raw_text,
                        "metric_name": raw_metric,
                        "operator": op,
                        "value_str": val_str,
                    }
                )

    return {
        "valid": valid,
        "unknown": unknown,
        "out_of_range": out_of_range,
    }


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
