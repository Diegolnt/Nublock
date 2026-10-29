from helpers import make_window

from nublock.classifier import UNCATEGORIZED, Classification, Classifier
from nublock.config import ClassificationRule


def rule(productivity: str, subcategory: str | None = None, **match: str) -> ClassificationRule:
    return ClassificationRule.model_validate(
        {"match": match, "productivity": productivity, "subcategory": subcategory}
    )


def test_process_matcher_is_case_insensitive() -> None:
    classifier = Classifier([rule("productive", "dev", process="code")])
    assert classifier.classify(make_window("Code")) == Classification("productive", "dev")
    assert classifier.classify(make_window("CODE")) == Classification("productive", "dev")


def test_process_matcher_is_exact_not_substring() -> None:
    classifier = Classifier([rule("productive", "dev", process="Code")])
    assert classifier.classify(make_window("Code Helper")) == UNCATEGORIZED


def test_title_regex_matches_anywhere_in_title() -> None:
    classifier = Classifier([rule("distracting", "video", title_regex="(?i) - YouTube")])
    window = make_window("Google Chrome", "Lofi beats - YouTube - Google Chrome")
    assert classifier.classify(window) == Classification("distracting", "video")


def test_title_regex_respects_case_flag() -> None:
    sensitive = Classifier([rule("distracting", "social", title_regex="Reddit")])
    assert sensitive.classify(make_window("Safari", "reddit: the front page")) == UNCATEGORIZED
    insensitive = Classifier([rule("distracting", "social", title_regex="(?i)reddit")])
    assert (
        insensitive.classify(make_window("Safari", "reddit: the front page")).subcategory
        == "social"
    )


def test_title_regex_never_matches_missing_title() -> None:
    classifier = Classifier([rule("distracting", "video", title_regex=".*")])
    assert classifier.classify(make_window("Google Chrome", None)) == UNCATEGORIZED


def test_first_matching_rule_wins() -> None:
    video = rule("distracting", "video", title_regex="YouTube")
    browser = rule("neutral", "browser", process="Google Chrome")
    window = make_window("Google Chrome", "Python tutorial - YouTube")
    assert Classifier([video, browser]).classify(window).subcategory == "video"
    assert Classifier([browser, video]).classify(window).subcategory == "browser"


def test_later_rule_applies_when_earlier_ones_do_not_match() -> None:
    rules = [
        rule("distracting", "video", title_regex="YouTube"),
        rule("neutral", "browser", process="Google Chrome"),
    ]
    window = make_window("Google Chrome", "Google Docs")
    assert Classifier(rules).classify(window) == Classification("neutral", "browser")


def test_unmatched_app_is_neutral_uncategorized() -> None:
    classifier = Classifier([rule("productive", "dev", process="Code")])
    result = classifier.classify(make_window("Finder"))
    assert result == UNCATEGORIZED == Classification("neutral", "uncategorized")


def test_no_rules_means_everything_uncategorized() -> None:
    assert Classifier([]).classify(make_window("Anything", "title")) == UNCATEGORIZED
