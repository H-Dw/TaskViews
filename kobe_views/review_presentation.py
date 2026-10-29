"""Presentation only: terminal validation and repair budgets are unchanged."""
from .artifact_view import prompt_schema

TIMINGS = ('stage',)
BUDGETS = ('fixed_reference', 'refill')
BRIEF = 'Work on the next action. Before success inspect the result and give a public artifact_review; missing evidence remains unknown.'
BRIEF_COMPACT = 'Before success: inspect result + public artifact_review. No evidence = unknown.'


def validate(timing, budget):
    if timing not in TIMINGS or budget not in BUDGETS:
        raise ValueError('Unknown Mini review timing or information refill policy')


def schema(policy, *, finishing=False, cost=False):
    # All fixed-reference conditions admit exactly the same facts. Savings
    # cannot buy extra records until refill is explicitly frozen in the plan.
    validate(policy.get('review_timing', 'stage'), policy.get('review_budget', 'refill'))
    if cost and policy.get('review_budget', 'refill') == 'fixed_reference':
        return prompt_schema('full')
    wording = policy.get('review_prompt', 'full')
    if not finishing:
        return BRIEF if wording == 'full' else BRIEF_COMPACT
    return prompt_schema(wording)
