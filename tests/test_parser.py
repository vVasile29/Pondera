"""Tests for the parser module."""

from services.parser import extract_list, extract_subject, extract_thresholds


class TestExtractSubject:
    def test_how_good_for(self):
        result = extract_subject("How good is a Tesla for commuting?")
        assert result["parsed"] is True
        assert result["subject"] == "Tesla"
        assert result["goal"] == "commuting"

    def test_how_good_no_goal(self):
        result = extract_subject("How good is Python?")
        assert result["parsed"] is True
        assert result["subject"] == "Python"
        assert result["goal"] is None

    def test_how_does_perform_for(self):
        result = extract_subject("How does Java perform for web development?")
        assert result["parsed"] is True
        assert result["subject"] == "Java"
        assert result["goal"] == "web development"

    def test_rate_my(self):
        result = extract_subject("Rate my portfolio")
        assert result["parsed"] is True
        assert result["subject"] == "portfolio"
        assert result["goal"] is None

    def test_evaluate(self):
        result = extract_subject("Evaluate Django")
        assert result["parsed"] is True
        assert result["subject"] == "Django"

    def test_review(self):
        result = extract_subject("Review这台电脑")  # non-English
        assert result["parsed"] is True
        assert result["subject"] == "这台电脑"

    def test_what_do_you_think(self):
        result = extract_subject("What do you think about Rust?")
        assert result["parsed"] is True
        assert result["subject"] == "Rust"

    def test_no_match(self):
        result = extract_subject("Hello world")
        assert result["parsed"] is False
        assert result["subject"] == "This option"

    def test_empty_string(self):
        result = extract_subject("")
        assert result["parsed"] is False
        assert result["subject"] == "This option"

    def test_strip_articles(self):
        result = extract_subject("How good is the new iPhone?")
        assert result["subject"] == "new iPhone"

    def test_multi_word_subject(self):
        result = extract_subject("How good is a Tesla Model 3 for daily commuting?")
        assert result["subject"] == "Tesla Model 3"
        assert result["goal"] == "daily commuting"

    def test_trailing_question_mark(self):
        result = extract_subject("Evaluate Python?")
        assert result["subject"] == "Python"


class TestExtractList:
    def test_comma_separated_three(self):
        result = extract_list("Python, Java, Go")
        assert result["parsed"] is True
        assert result["alternatives"] == ["Python", "Java", "Go"]

    def test_newline_separated_three(self):
        result = extract_list("Python\nJava\nGo")
        assert result["parsed"] is True
        assert result["alternatives"] == ["Python", "Java", "Go"]

    def test_numbered_list(self):
        result = extract_list("1. Python\n2. Java\n3. Go")
        assert result["parsed"] is True
        assert result["alternatives"] == ["Python", "Java", "Go"]

    def test_numbered_list_parentheses(self):
        result = extract_list("1) Python\n2) Java\n3) Go")
        assert result["parsed"] is True
        assert result["alternatives"] == ["Python", "Java", "Go"]

    def test_rank_prefix(self):
        result = extract_list("Rank: Python, Java, Go")
        assert result["parsed"] is True
        assert result["alternatives"] == ["Python", "Java", "Go"]

    def test_order_prefix(self):
        result = extract_list("Order Python, Java, Go, Rust")
        assert result["parsed"] is True
        assert result["alternatives"] == ["Python", "Java", "Go", "Rust"]

    def test_fewer_than_three(self):
        result = extract_list("Python, Java")
        assert result["parsed"] is False

    def test_empty(self):
        result = extract_list("")
        assert result["parsed"] is False

    def test_single_item(self):
        result = extract_list("Python")
        assert result["parsed"] is False

    def test_trailing_commas_spaces(self):
        result = extract_list("Python, Java, Go, ")
        assert result["parsed"] is True
        assert result["alternatives"] == ["Python", "Java", "Go"]

    def test_items_with_punctuation(self):
        result = extract_list("Python, Java, Go.")
        assert result["parsed"] is True
        assert result["alternatives"] == ["Python", "Java", "Go"]

    def test_mixed_comma_newline(self):
        result = extract_list("Python, Java\nGo, Rust")
        assert result["parsed"] is True
        assert len(result["alternatives"]) >= 3

    def test_capitalization(self):
        result = extract_list("python, java, go")
        assert result["parsed"] is True
        assert result["alternatives"] == ["Python", "Java", "Go"]


class TestExtractThresholds:
    def test_cost_less_than_or_equal(self):
        result = extract_thresholds("Cost <= 60")
        assert len(result) == 1
        r = result[0]
        assert r["metric_name"] == "Cost"
        assert r["operator"] == "<="
        assert r["value"] == 60.0

    def test_quality_greater_than_or_equal(self):
        result = extract_thresholds("Quality >= 70")
        assert len(result) == 1
        r = result[0]
        assert r["metric_name"] == "Quality"
        assert r["operator"] == ">="
        assert r["value"] == 70.0

    def test_cost_less_than(self):
        result = extract_thresholds("cost < 30")
        assert len(result) == 1
        r = result[0]
        assert r["metric_name"] == "Cost"
        assert r["operator"] == "<"
        assert r["value"] == 30.0

    def test_at_least_quality(self):
        result = extract_thresholds("at least 80 quality")
        assert len(result) == 1
        r = result[0]
        assert r["metric_name"] == "Quality"
        assert r["operator"] == ">="
        assert r["value"] == 80.0

    def test_multiple_thresholds(self):
        result = extract_thresholds("Cost <= 60 and Quality >= 80")
        assert len(result) >= 2
        names = {r["metric_name"] for r in result}
        assert "Cost" in names
        assert "Quality" in names

    def test_no_thresholds(self):
        result = extract_thresholds("Hello world")
        assert result == []

    def test_unknown_metric_ignored(self):
        result = extract_thresholds("FooBar <= 60")
        assert result == []

    def test_maximum_cost(self):
        result = extract_thresholds("maximum cost 50")
        assert len(result) == 1
        r = result[0]
        assert r["metric_name"] == "Cost"
        assert r["operator"] == "<="
        assert r["value"] == 50.0

    def test_minimum_quality(self):
        result = extract_thresholds("minimum quality 75")
        assert len(result) == 1
        r = result[0]
        assert r["metric_name"] == "Quality"
        assert r["operator"] == ">="
        assert r["value"] == 75.0
