"""Decision ontology — hierarchical knowledge base for parsing decision questions."""

import re
from typing import List, Tuple

DECISION_CATEGORIES = [
    {
        "name": "Housing",
        "keywords": ["house", "apartment", "condo", "rent", "buy", "mortgage", "home", "property", "housing", "living"],
        "patterns": ["where to live", "where should i", "buy a house", "rent an apartment"],
        "criteria": [
            {"name": "Cost", "description": "Total cost (purchase/rent + utilities)", "default_weight": 90, "higher_is_better": False},
            {"name": "Location", "description": "Convenience of the location", "default_weight": 85, "higher_is_better": True},
            {"name": "Space", "description": "Square footage and room count", "default_weight": 75, "higher_is_better": True},
            {"name": "Maintenance", "description": "Ease and cost of upkeep", "default_weight": 65, "higher_is_better": True},
            {"name": "Privacy", "description": "Level of privacy and quiet", "default_weight": 60, "higher_is_better": True},
            {"name": "Safety", "description": "Neighborhood safety and security", "default_weight": 80, "higher_is_better": True},
            {"name": "Neighborhood", "description": "Quality of neighbors and community", "default_weight": 70, "higher_is_better": True},
            {"name": "Commute", "description": "Distance to work/school/amenities", "default_weight": 75, "higher_is_better": False},
        ]
    },
    {
        "name": "Career",
        "keywords": ["job", "career", "work", "salary", "employ", "offer", "position", "company", "startup", "corporate"],
        "patterns": ["which job", "should i work", "career path", "job offer", "should i take"],
        "criteria": [
            {"name": "Salary", "description": "Total compensation including benefits", "default_weight": 85, "higher_is_better": True},
            {"name": "Growth Potential", "description": "Opportunities for advancement and learning", "default_weight": 80, "higher_is_better": True},
            {"name": "Work-Life Balance", "description": "Hours, flexibility, remote options", "default_weight": 75, "higher_is_better": True},
            {"name": "Job Security", "description": "Stability and low risk of layoffs", "default_weight": 65, "higher_is_better": True},
            {"name": "Culture", "description": "Company culture and team environment", "default_weight": 70, "higher_is_better": True},
            {"name": "Location", "description": "Commute and relocation requirements", "default_weight": 60, "higher_is_better": True},
            {"name": "Benefits", "description": "Health insurance, 401k, perks, PTO", "default_weight": 70, "higher_is_better": True},
        ]
    },
    {
        "name": "Fitness",
        "keywords": ["workout", "exercise", "gym", "sport", "sports", "fitness", "training", "run", "runner", "bodybuilder", "athlete", "swim", "yoga"],
        "patterns": ["what sport", "which exercise", "should i do", "fitness routine"],
        "criteria": [
            {"name": "Cardiovascular", "description": "Heart and lung benefits", "default_weight": 70, "higher_is_better": True},
            {"name": "Strength", "description": "Muscle building and power", "default_weight": 75, "higher_is_better": True},
            {"name": "Flexibility", "description": "Range of motion and injury prevention", "default_weight": 60, "higher_is_better": True},
            {"name": "Time Commitment", "description": "Hours required per week", "default_weight": 65, "higher_is_better": False},
            {"name": "Cost", "description": "Equipment, membership, or class fees", "default_weight": 55, "higher_is_better": False},
            {"name": "Enjoyment", "description": "How fun and engaging it is", "default_weight": 80, "higher_is_better": True},
            {"name": "Social Aspect", "description": "Community and group opportunities", "default_weight": 50, "higher_is_better": True},
        ]
    },
    {
        "name": "Education",
        "keywords": ["degree", "course", "school", "university", "college", "major", "study", "learn", "bootcamp", "certification", "class"],
        "patterns": ["which degree", "should i study", "what to learn", "education path"],
        "criteria": [
            {"name": "Cost", "description": "Tuition and fees", "default_weight": 80, "higher_is_better": False},
            {"name": "Time to Complete", "description": "Duration of program", "default_weight": 60, "higher_is_better": False},
            {"name": "Career Outcome", "description": "Job prospects after completion", "default_weight": 90, "higher_is_better": True},
            {"name": "Quality", "description": "Reputation and quality of education", "default_weight": 75, "higher_is_better": True},
            {"name": "Flexibility", "description": "Online options, part-time, schedule", "default_weight": 65, "higher_is_better": True},
            {"name": "Network", "description": "Alumni network and connections", "default_weight": 55, "higher_is_better": True},
        ]
    },
    {
        "name": "Technology",
        "keywords": ["phone", "laptop", "computer", "tablet", "gadget", "device", "software", "app", "iphone", "android", "mac", "windows", "tech"],
        "patterns": ["which phone", "what laptop", "should i buy", "best device"],
        "criteria": [
            {"name": "Price", "description": "Upfront and ongoing cost", "default_weight": 80, "higher_is_better": False},
            {"name": "Performance", "description": "Speed, power, responsiveness", "default_weight": 85, "higher_is_better": True},
            {"name": "Build Quality", "description": "Durability and materials", "default_weight": 70, "higher_is_better": True},
            {"name": "Battery Life", "description": "Hours of use per charge", "default_weight": 70, "higher_is_better": True},
            {"name": "Ecosystem", "description": "Compatibility with other devices", "default_weight": 60, "higher_is_better": True},
            {"name": "Support", "description": "Customer service and warranty", "default_weight": 55, "higher_is_better": True},
        ]
    },
    {
        "name": "Vehicle",
        "keywords": ["car", "truck", "suv", "vehicle", "drive", "electric", "gas", "hybrid", "commute"],
        "patterns": ["which car", "what vehicle", "should i buy", "car comparison"],
        "criteria": [
            {"name": "Price", "description": "Purchase price", "default_weight": 85, "higher_is_better": False},
            {"name": "Fuel Efficiency", "description": "MPG or electric range", "default_weight": 75, "higher_is_better": True},
            {"name": "Reliability", "description": "Expected maintenance and repairs", "default_weight": 80, "higher_is_better": True},
            {"name": "Safety", "description": "Crash ratings and safety features", "default_weight": 85, "higher_is_better": True},
            {"name": "Space", "description": "Cargo and passenger room", "default_weight": 65, "higher_is_better": True},
            {"name": "Performance", "description": "Power, handling, driving experience", "default_weight": 60, "higher_is_better": True},
        ]
    },
    {
        "name": "Investment",
        "keywords": ["invest", "stock", "bond", "crypto", "index fund", "etf", "real estate", "saving", "retirement", "portfolio"],
        "patterns": ["where to invest", "should i invest", "investment option"],
        "criteria": [
            {"name": "Return Potential", "description": "Expected ROI", "default_weight": 85, "higher_is_better": True},
            {"name": "Risk", "description": "Volatility and chance of loss", "default_weight": 80, "higher_is_better": False},
            {"name": "Liquidity", "description": "Ease of converting to cash", "default_weight": 65, "higher_is_better": True},
            {"name": "Time Horizon", "description": "How long until full return", "default_weight": 55, "higher_is_better": False},
            {"name": "Complexity", "description": "Ease of understanding and managing", "default_weight": 60, "higher_is_better": False},
            {"name": "Fees", "description": "Management fees and expenses", "default_weight": 70, "higher_is_better": False},
        ]
    },
    {
        "name": "Health",
        "keywords": ["diet", "nutrition", "food", "eat", "meal", "dietary", "health", "doctor", "treatment", "therapy", "medicine"],
        "patterns": ["which diet", "what should i eat", "health plan", "treatment option"],
        "criteria": [
            {"name": "Effectiveness", "description": "How well it achieves health goals", "default_weight": 90, "higher_is_better": True},
            {"name": "Cost", "description": "Monthly or per-visit cost", "default_weight": 70, "higher_is_better": False},
            {"name": "Convenience", "description": "Ease of following the plan", "default_weight": 65, "higher_is_better": True},
            {"name": "Side Effects", "description": "Negative impacts on wellbeing", "default_weight": 75, "higher_is_better": False},
            {"name": "Long-term Sustainability", "description": "Can you maintain it long term", "default_weight": 80, "higher_is_better": True},
            {"name": "Scientific Support", "description": "Evidence and research backing", "default_weight": 70, "higher_is_better": True},
        ]
    },
    {
        "name": "Travel",
        "keywords": ["vacation", "travel", "trip", "destination", "holiday", "visit", "tourist", "hotel", "flight"],
        "patterns": ["where to go", "where should i travel", "vacation destination", "travel to"],
        "criteria": [
            {"name": "Cost", "description": "Total trip cost", "default_weight": 80, "higher_is_better": False},
            {"name": "Attractions", "description": "Things to see and do", "default_weight": 85, "higher_is_better": True},
            {"name": "Safety", "description": "How safe the destination is", "default_weight": 80, "higher_is_better": True},
            {"name": "Weather", "description": "Climate during visit", "default_weight": 65, "higher_is_better": True},
            {"name": "Food", "description": "Quality of local cuisine", "default_weight": 70, "higher_is_better": True},
            {"name": "Accessibility", "description": "Ease of getting there and around", "default_weight": 55, "higher_is_better": True},
        ]
    },
    {
        "name": "Entertainment",
        "keywords": ["movie", "show", "game", "book", "stream", "watch", "play", "read", "music", "podcast", "netflix"],
        "patterns": ["what to watch", "what to read", "what to play", "should i watch", "which movie"],
        "criteria": [
            {"name": "Enjoyment", "description": "How entertaining it is", "default_weight": 90, "higher_is_better": True},
            {"name": "Cost", "description": "Price to access or purchase", "default_weight": 60, "higher_is_better": False},
            {"name": "Time Investment", "description": "Time needed to consume", "default_weight": 50, "higher_is_better": False},
            {"name": "Quality", "description": "Production value and reviews", "default_weight": 75, "higher_is_better": True},
            {"name": "Replayability", "description": "Can you enjoy it multiple times", "default_weight": 40, "higher_is_better": True},
            {"name": "Social Value", "description": "Can you share the experience with others", "default_weight": 45, "higher_is_better": True},
        ]
    },
    {
        "name": "Lifestyle",
        "keywords": ["city", "country", "suburb", "move", "relocate", "live", "lifestyle", "community"],
        "patterns": ["where should i live", "should i move", "city vs country", "relocate to"],
        "criteria": [
            {"name": "Cost of Living", "description": "Monthly expenses", "default_weight": 85, "higher_is_better": False},
            {"name": "Job Market", "description": "Employment opportunities", "default_weight": 80, "higher_is_better": True},
            {"name": "Quality of Life", "description": "Overall satisfaction and wellbeing", "default_weight": 90, "higher_is_better": True},
            {"name": "Climate", "description": "Weather and environment", "default_weight": 60, "higher_is_better": True},
            {"name": "Community", "description": "Social connections and activities", "default_weight": 70, "higher_is_better": True},
            {"name": "Amenities", "description": "Access to parks, restaurants, services", "default_weight": 65, "higher_is_better": True},
        ]
    },
    {
        "name": "Business",
        "keywords": ["startup", "business", "entrepreneur", "side hustle", "freelance", "consult", "agency", "product"],
        "patterns": ["should i start", "which business", "entrepreneur path"],
        "criteria": [
            {"name": "Profit Potential", "description": "Revenue and income potential", "default_weight": 90, "higher_is_better": True},
            {"name": "Startup Cost", "description": "Initial investment required", "default_weight": 75, "higher_is_better": False},
            {"name": "Risk", "description": "Chance of failure", "default_weight": 70, "higher_is_better": False},
            {"name": "Time Commitment", "description": "Hours needed to start and run", "default_weight": 65, "higher_is_better": False},
            {"name": "Scalability", "description": "Potential to grow", "default_weight": 75, "higher_is_better": True},
            {"name": "Passion", "description": "Personal interest in the domain", "default_weight": 80, "higher_is_better": True},
        ]
    },
    {
        "name": "Food",
        "keywords": ["restaurant", "cuisine", "food", "eat", "dining", "cook", "recipe", "meal prep", "delivery"],
        "patterns": ["where to eat", "what to cook", "which restaurant", "food choice"],
        "criteria": [
            {"name": "Taste", "description": "Flavor and quality of food", "default_weight": 90, "higher_is_better": True},
            {"name": "Price", "description": "Cost per meal", "default_weight": 75, "higher_is_better": False},
            {"name": "Healthiness", "description": "Nutritional value", "default_weight": 65, "higher_is_better": True},
            {"name": "Convenience", "description": "Ease of access or preparation", "default_weight": 60, "higher_is_better": True},
            {"name": "Variety", "description": "Range of options available", "default_weight": 50, "higher_is_better": True},
            {"name": "Service", "description": "Quality of service", "default_weight": 55, "higher_is_better": True},
        ]
    },
]

GENERIC_CRITERIA = [
    {"name": "Cost", "description": "Financial cost", "default_weight": 85, "higher_is_better": False},
    {"name": "Quality", "description": "Overall quality and value", "default_weight": 80, "higher_is_better": True},
    {"name": "Time", "description": "Time required or saved", "default_weight": 65, "higher_is_better": False},
    {"name": "Convenience", "description": "Ease of use or access", "default_weight": 60, "higher_is_better": True},
    {"name": "Reliability", "description": "Dependability and consistency", "default_weight": 70, "higher_is_better": True},
    {"name": "Satisfaction", "description": "Expected personal satisfaction", "default_weight": 90, "higher_is_better": True},
]

STOP_WORDS = {
    "a", "an", "the", "is", "am", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "can", "could", "shall", "should", "may",
    "might", "i", "you", "he", "she", "it", "we", "they", "my",
    "your", "his", "her", "its", "our", "their", "me", "him",
    "us", "them", "this", "that", "these", "those", "to", "for",
    "of", "in", "on", "with", "at", "by", "from", "or", "and",
    "not", "no", "but", "if", "so", "about", "what", "which",
    "who", "whose", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "some", "any", "up",
    "out", "off", "over", "into", "than", "then", "also", "just",
    "buy", "get", "make", "take", "need", "want", "should",
}


def suggest_criteria(query: str) -> Tuple[str, list]:
    """Given a free-text query, suggest decision criteria and category.

    Returns (category_name, criteria_list).
    Falls back to GENERIC_CRITERIA with category "General" if no match.
    """
    query_lower = query.lower().strip()
    words = [w for w in query_lower.split() if w not in STOP_WORDS and len(w) > 2]

    best_score = 0
    best_category = None

    for cat in DECISION_CATEGORIES:
        score = 0
        # Check patterns first (higher weight)
        for pattern in cat["patterns"]:
            if pattern in query_lower:
                score += 5
        # Check keywords
        for kw in cat["keywords"]:
            if kw in query_lower:
                score += 2
            for w in words:
                if kw in w or w in kw:
                    score += 1
        if score > best_score:
            best_score = score
            best_category = cat

    if best_score == 0 or best_category is None:
        return "General", GENERIC_CRITERIA

    return best_category["name"], best_category["criteria"]


def extract_alternatives(query: str) -> List[str]:
    """Extract alternatives from a decision query.

    Splits on " or ", " vs ", " versus ", " vs. " (case-insensitive),
    and cleans up each alternative.
    Returns empty list if no comparison markers are found.
    """
    # Try to find "or", "vs", "versus" patterns
    patterns = [
        r'\b(.+?)\s+(?:or|vs\.?|versus)\s+(.+?)\s*$',
        r'\b(.+?)\s+vs\.?\s+(.+?)\b',
    ]

    # First try to find a clear alternative split
    match = re.search(
        r'(.+?)\s+(?:or|vs\.?|versus)\s+(.+)',
        query,
        re.IGNORECASE,
    )
    if not match:
        return []

    before = match.group(1).strip()
    after = match.group(2).strip()

    # Clean up common prefixes/suffixes
    def clean(alt: str) -> str:
        alt = alt.strip().strip('?.,;:!')
        # Remove leading phrases like "should i", "am i", "what about"
        alt = re.sub(r'^(?:should\s+i|am\s+i|what\s+about|how\s+about|what\s+is|what\s+are|tell\s+me)\s+', '', alt, flags=re.IGNORECASE)
        alt = alt.strip()
        # Capitalize first letter
        if alt and alt[0].islower():
            alt = alt[0].upper() + alt[1:]
        return alt

    # The 'before' part might contain more than just the first alternative
    # e.g. "should I buy a house or an apartment" → need to extract just "house"
    # Let's split intelligently
    before_clean = before
    for prefix in ["should i", "am i", "do i", "would you", "should you", "i want to", "i need to", "i should", "i am"]:
        before_clean = re.sub(r'^' + prefix, '', before_clean, flags=re.IGNORECASE).strip()

    # Remove leading verbs/prepositions
    before_clean = re.sub(r'^(?:buy|get|choose|pick|select|take|go\s+for|opt\s+for|decide\s+between|compare|be|become|use|try|have)\s+', '', before_clean, flags=re.IGNORECASE).strip()

    # Split by remaining "or"/"and" in before_clean if it contains multiple items
    alt_parts = re.split(r'\s+(?:or|and|vs\.?|versus)\s+', before_clean, flags=re.IGNORECASE)
    alternatives = []
    for part in list(alt_parts) + [after]:
        cleaned = clean(part)
        if cleaned and len(cleaned) > 1:
            alternatives.append(cleaned)

    # If we have exactly 2 alternatives from the full match, use those
    if len(alternatives) < 2:
        # Try the simpler split
        alts_combined = re.split(r'\s+(?:or|vs\.?|versus)\s+', query, flags=re.IGNORECASE)
        alternatives = [clean(a) for a in alts_combined if clean(a) and len(clean(a)) > 1]

    return alternatives
