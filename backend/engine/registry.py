from backend.rules.schema import RuleType


SUPPORTED_EVALUATOR_RULE_TYPES = {
    RuleType.RECURRING_EVENT,
    RuleType.PRECEDING_EVENT_WINDOW,
    RuleType.PREREQUISITE,
    RuleType.NUMERIC_THRESHOLD,
    RuleType.VERSION_MATCH,
    RuleType.AUTHORIZATION_WINDOW,
    RuleType.QUALIFICATION_MATCH,
}


def is_supported_rule_type(rule_type: RuleType) -> bool:
    return rule_type in SUPPORTED_EVALUATOR_RULE_TYPES
