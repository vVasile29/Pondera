"""Universal fit ontology for decision analysis.

Every metric is a 0–100 fit score. Higher always means better fit.
"""

import re
from typing import List


FIT_SCORE_HELPER_TEXT = (
    "Every slider is a 0–100 fit score. Higher always means better fit."
)

FIT_SCORE_EXPORT_EXPLANATION = (
    "All scores are 0–100 fit scores. Higher means the alternative fits the "
    "decision better on that metric."
)

FIT_CATEGORY_NAMES = [
    "Resource Fit",
    "Objective Fit",
    "Time Fit",
    "Assurance Fit",
    "People Fit",
    "Practical Fit",
]

OLD_TO_NEW_CATEGORY_NAMES = {
    "Financial": {"name": "Resource Fit", "stable_id": "resource_fit"},
    "Quality": {"name": "Objective Fit", "stable_id": "objective_fit"},
    "Time": {"name": "Time Fit", "stable_id": "time_fit"},
    "Risk": {"name": "Assurance Fit", "stable_id": "assurance_fit"},
    "Experience": {"name": "People Fit", "stable_id": "people_fit"},
    "Convenience": {"name": "Practical Fit", "stable_id": "practical_fit"},
}

OLD_TO_NEW_METRIC_NAMES = {
    "Cost": {"name": "Affordability", "stable_id": "affordability"},
    "Value": {"name": "Value", "stable_id": "value"},
    "Performance": {"name": "Effectiveness", "stable_id": "effectiveness"},
    "Quality": {"name": "Quality", "stable_id": "quality"},
    "Time Required": {"name": "Timeliness", "stable_id": "timeliness"},
    "Efficiency": {"name": "Efficiency", "stable_id": "efficiency"},
    "Risk": {"name": "Reliability", "stable_id": "reliability"},
    "Safety": {"name": "Protection", "stable_id": "protection"},
    "Enjoyment": {"name": "Desirability", "stable_id": "desirability"},
    "Satisfaction": {"name": "Acceptance", "stable_id": "acceptance"},
    "Convenience": {"name": "Feasibility", "stable_id": "feasibility"},
    "Accessibility": {"name": "Flexibility", "stable_id": "flexibility"},
}

RESERVED_LEGACY_METRIC_NAMES = {
    old_name
    for old_name, mapped in OLD_TO_NEW_METRIC_NAMES.items()
    if old_name != mapped["name"]
}

UNIVERSAL_DIMENSIONS = [
    {
        "stable_id": "resource_fit",
        "name": "Resource Fit",
        "question": "Is the required burden acceptable and worth it?",
        "description": "Is the required burden acceptable and worth it?",
        "keywords": ["cost", "price", "budget", "money", "effort", "resource", "value", "afford"],
        "metrics": [
            {
                "stable_id": "affordability",
                "name": "Affordability",
                "question": "How acceptable is the cost, effort, or resource burden?",
                "description": "How acceptable is the cost, effort, or resource burden?",
                "low_anchor": "Unacceptable burden",
                "mid_anchor": "Acceptable but costly",
                "high_anchor": "Excellent resource fit",
                "default_weight": 90,
                "category_id": "resource_fit",
                "category": "Resource Fit",
            },
            {
                "stable_id": "value",
                "name": "Value",
                "question": "How much benefit is created relative to the burden?",
                "description": "How much benefit is created relative to the burden?",
                "low_anchor": "Poor value",
                "mid_anchor": "Fair value",
                "high_anchor": "Excellent value",
                "default_weight": 75,
                "category_id": "resource_fit",
                "category": "Resource Fit",
            },
        ],
    },
    {
        "stable_id": "objective_fit",
        "name": "Objective Fit",
        "question": "Does this achieve the purpose of the decision?",
        "description": "Does this achieve the purpose of the decision?",
        "keywords": ["quality", "performance", "effective", "goal", "result", "outcome", "excellent"],
        "metrics": [
            {
                "stable_id": "effectiveness",
                "name": "Effectiveness",
                "question": "How well does this solve the core problem or achieve the intended goal?",
                "description": "How well does this solve the core problem or achieve the intended goal?",
                "low_anchor": "Does not solve the problem",
                "mid_anchor": "Partially solves the problem",
                "high_anchor": "Solves the problem extremely well",
                "default_weight": 80,
                "category_id": "objective_fit",
                "category": "Objective Fit",
            },
            {
                "stable_id": "quality",
                "name": "Quality",
                "question": "How good, complete, durable, robust, or excellent is the result?",
                "description": "How good, complete, durable, robust, or excellent is the result?",
                "low_anchor": "Low quality",
                "mid_anchor": "Acceptable quality",
                "high_anchor": "Excellent quality",
                "default_weight": 85,
                "category_id": "objective_fit",
                "category": "Objective Fit",
            },
        ],
    },
    {
        "stable_id": "time_fit",
        "name": "Time Fit",
        "question": "Does the timing work?",
        "description": "Does the timing work?",
        "keywords": ["time", "speed", "delay", "schedule", "deadline", "efficient", "timing"],
        "metrics": [
            {
                "stable_id": "timeliness",
                "name": "Timeliness",
                "question": "How well does the speed, delay, schedule, or time requirement fit the decision?",
                "description": "How well does the speed, delay, schedule, or time requirement fit the decision?",
                "low_anchor": "Poor timing fit",
                "mid_anchor": "Acceptable timing",
                "high_anchor": "Excellent timing fit",
                "default_weight": 70,
                "category_id": "time_fit",
                "category": "Time Fit",
            },
            {
                "stable_id": "efficiency",
                "name": "Efficiency",
                "question": "How much useful output is achieved per unit of time, effort, or input?",
                "description": "How much useful output is achieved per unit of time, effort, or input?",
                "low_anchor": "Inefficient",
                "mid_anchor": "Acceptably efficient",
                "high_anchor": "Highly efficient",
                "default_weight": 65,
                "category_id": "time_fit",
                "category": "Time Fit",
            },
        ],
    },
    {
        "stable_id": "assurance_fit",
        "name": "Assurance Fit",
        "question": "Can we trust this option to work without unacceptable downside?",
        "description": "Can we trust this option to work without unacceptable downside?",
        "keywords": ["risk", "safe", "safety", "secure", "reliable", "trust", "uncertain", "protect"],
        "metrics": [
            {
                "stable_id": "reliability",
                "name": "Reliability",
                "question": "How likely is this option to work consistently under uncertainty?",
                "description": "How likely is this option to work consistently under uncertainty?",
                "low_anchor": "Unreliable or highly uncertain",
                "mid_anchor": "Manageable uncertainty",
                "high_anchor": "Highly reliable and predictable",
                "default_weight": 80,
                "category_id": "assurance_fit",
                "category": "Assurance Fit",
            },
            {
                "stable_id": "protection",
                "name": "Protection",
                "question": "How well does this option avoid harm, violations, unacceptable consequences, or irreversible damage?",
                "description": "How well does this option avoid harm, violations, unacceptable consequences, or irreversible damage?",
                "low_anchor": "Poorly protected",
                "mid_anchor": "Acceptably protected",
                "high_anchor": "Very well protected",
                "default_weight": 75,
                "category_id": "assurance_fit",
                "category": "Assurance Fit",
            },
        ],
    },
    {
        "stable_id": "people_fit",
        "name": "People Fit",
        "question": "Does this option fit the people affected?",
        "description": "Does this option fit the people affected?",
        "keywords": ["enjoy", "appeal", "satisfaction", "stakeholder", "accept", "approve", "people"],
        "metrics": [
            {
                "stable_id": "desirability",
                "name": "Desirability",
                "question": "How attractive, motivating, or personally appealing is this option?",
                "description": "How attractive, motivating, or personally appealing is this option?",
                "low_anchor": "Undesirable",
                "mid_anchor": "Neutral or mixed appeal",
                "high_anchor": "Highly desirable",
                "default_weight": 85,
                "category_id": "people_fit",
                "category": "People Fit",
            },
            {
                "stable_id": "acceptance",
                "name": "Acceptance",
                "question": "How likely is this option to be accepted, approved, adopted, or tolerated by stakeholders?",
                "description": "How likely is this option to be accepted, approved, adopted, or tolerated by stakeholders?",
                "low_anchor": "Likely to be rejected",
                "mid_anchor": "Mixed or uncertain acceptance",
                "high_anchor": "Likely to be strongly accepted",
                "default_weight": 80,
                "category_id": "people_fit",
                "category": "People Fit",
            },
        ],
    },
    {
        "stable_id": "practical_fit",
        "name": "Practical Fit",
        "question": "Can this option realistically be done, used, accessed, operated, and adapted?",
        "description": "Can this option realistically be done, used, accessed, operated, and adapted?",
        "keywords": ["convenient", "easy", "accessible", "practical", "feasible", "flexible", "adapt"],
        "metrics": [
            {
                "stable_id": "feasibility",
                "name": "Feasibility",
                "question": "How realistic is it to obtain, implement, use, maintain, or execute this option?",
                "description": "How realistic is it to obtain, implement, use, maintain, or execute this option?",
                "low_anchor": "Not realistically feasible",
                "mid_anchor": "Feasible with effort",
                "high_anchor": "Highly feasible",
                "default_weight": 70,
                "category_id": "practical_fit",
                "category": "Practical Fit",
            },
            {
                "stable_id": "flexibility",
                "name": "Flexibility",
                "question": "How well can this option adapt, scale, reverse, or remain useful if conditions change?",
                "description": "How well can this option adapt, scale, reverse, or remain useful if conditions change?",
                "low_anchor": "Rigid or hard to change",
                "mid_anchor": "Somewhat adaptable",
                "high_anchor": "Highly flexible and adaptable",
                "default_weight": 65,
                "category_id": "practical_fit",
                "category": "Practical Fit",
            },
        ],
    },
]

UNIVERSAL_METRICS = []
for dim in UNIVERSAL_DIMENSIONS:
    for metric in dim["metrics"]:
        UNIVERSAL_METRICS.append(metric)

METRIC_METADATA_BY_NAME = {metric["name"]: metric for metric in UNIVERSAL_METRICS}
CATEGORY_METADATA_BY_NAME = {dim["name"]: dim for dim in UNIVERSAL_DIMENSIONS}


def ontology_metric_metadata(name: str) -> dict | None:
    return METRIC_METADATA_BY_NAME.get(name)


def serialize_metric_metadata(metric) -> dict:
    # Decision-scoped custom metrics: skip ontology lookup
    if getattr(metric, "decision_id", None) is not None:
        return {
            "id": metric.id,
            "stable_id": None,
            "name": metric.name,
            "category": metric.category,
            "category_id": None,
            "description": metric.description or "",
            "question": metric.description or "",
            "anchors": None,
            "scope": metric.scope,
            "source": metric.source,
            "decision_id": metric.decision_id,
        }
    metadata = ontology_metric_metadata(metric.name)
    if not metadata:
        return {
            "id": metric.id,
            "stable_id": None,
            "name": metric.name,
            "category": metric.category,
            "category_id": None,
            "description": metric.description or "",
            "question": metric.description or "",
            "anchors": None,
            "scope": "global",
            "source": "template",
            "decision_id": None,
        }
    return {
        "id": metric.id,
        "stable_id": metadata["stable_id"],
        "name": metadata["name"],
        "category": metadata["category"],
        "category_id": metadata["category_id"],
        "description": metadata["description"],
        "question": metadata["question"],
        "anchors": {
            "low": metadata["low_anchor"],
            "mid": metadata["mid_anchor"],
            "high": metadata["high_anchor"],
        },
        "scope": "global",
        "source": "template",
        "decision_id": None,
    }


def get_universal_criteria() -> tuple[str, list]:
    """Return the universal fit criteria set."""
    return "General", UNIVERSAL_METRICS


def extract_alternatives(query: str) -> List[str]:
    """Extract alternatives from a decision query."""
    match = re.search(
        r"(.+?)\s+(?:or|vs\.?|versus)\s+(.+)",
        query,
        re.IGNORECASE,
    )
    if not match:
        return []

    before = match.group(1).strip()
    after = match.group(2).strip()

    def clean(alt: str) -> str:
        alt = alt.strip().strip("?.,;:!")
        alt = re.sub(
            r"^(?:should\s+(?:i|we)|"
            r"am\s+i|"
            r"what\s+about|how\s+about|what\s+is|what\s+are|"
            r"tell\s+me|"
            r"should\s+(?:an\s+ai\s+agent|the\s+ai\s+agent|the\s+user|someone)|"
            r"do\s+(?:i|we)|"
            r"would\s+you|should\s+you)\s+",
            "",
            alt,
            flags=re.IGNORECASE,
        )
        alt = re.sub(r"^(?:a|an|the)\s+", "", alt, flags=re.IGNORECASE)
        alt = alt.strip()
        if alt and alt[0].islower():
            alt = alt[0].upper() + alt[1:]
        return alt

    before_clean = before
    for prefix in [
        "should i",
        "should we",
        "am i",
        "do i",
        "do we",
        "would you",
        "should you",
        "i want to",
        "i need to",
        "i should",
        "i am",
    ]:
        before_clean = re.sub(
            r"^" + prefix, "", before_clean, flags=re.IGNORECASE
        ).strip()
    for agent_prefix in [
        "should an ai agent",
        "should the ai agent",
        "should the user",
        "should someone",
    ]:
        before_clean = re.sub(
            r"^" + agent_prefix, "", before_clean, flags=re.IGNORECASE
        ).strip()

    before_clean = re.sub(
        r"^(?:buy|get|choose|pick|select|take|go\s+(?:for|to)|opt\s+for|decide\s+between|compare|be|become|do|play|learn|use|try|have)\s+",
        "",
        before_clean,
        flags=re.IGNORECASE,
    ).strip()

    alt_parts = re.split(
        r"\s+(?:or|and|vs\.?|versus)\s+", before_clean, flags=re.IGNORECASE
    )
    alternatives = []
    for part in list(alt_parts) + [after]:
        cleaned = clean(part)
        if cleaned and len(cleaned) > 1:
            alternatives.append(cleaned)

    if len(alternatives) < 2:
        alts_combined = re.split(
            r"\s+(?:or|vs\.?|versus)\s+", query, flags=re.IGNORECASE
        )
        alternatives = [
            clean(a) for a in alts_combined if clean(a) and len(clean(a)) > 1
        ]

    # Post-processing: detect shared-object pattern.
    # E.g., ["Build", "Buy this software"] → ["Build this software", "Buy this software"]
    if len(alternatives) == 2:
        _decision_verbs = {
            "buy", "build", "choose", "pick", "select", "use", "send",
            "get", "have", "play", "do", "learn", "take", "try", "make",
        }
        alt0_lower = alternatives[0].lower()
        alt1_lower = alternatives[1].lower()
        alt0_words = alt0_lower.split()
        alt1_words = alt1_lower.split()
        if (
            len(alt0_words) == 1
            and len(alt1_words) >= 2
            and alt0_words[0] in _decision_verbs
            and alt1_words[0] in _decision_verbs
            and alt0_words[0] != alt1_words[0]
        ):
            shared_obj = " ".join(alternatives[1].split()[1:])
            alternatives[0] = f"{alternatives[0]} {shared_obj}"

    return alternatives
