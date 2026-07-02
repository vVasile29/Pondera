from fastapi import HTTPException


MAX_DECISION_ALTERNATIVES = 20
MAX_DECISION_METRICS = 20
MAX_ROBUSTNESS_WORKLOAD = MAX_DECISION_ALTERNATIVES * MAX_DECISION_METRICS


def enforce_decision_size(alternative_count: int, metric_count: int) -> None:
    if alternative_count > MAX_DECISION_ALTERNATIVES:
        raise HTTPException(
            status_code=422,
            detail=f"A decision can include at most {MAX_DECISION_ALTERNATIVES} alternatives.",
        )
    if metric_count > MAX_DECISION_METRICS:
        raise HTTPException(
            status_code=422,
            detail=f"A decision can include at most {MAX_DECISION_METRICS} selected metrics.",
        )


def robustness_workload_allowed(alternative_count: int, metric_count: int) -> bool:
    return (
        alternative_count <= MAX_DECISION_ALTERNATIVES
        and metric_count <= MAX_DECISION_METRICS
        and alternative_count * metric_count <= MAX_ROBUSTNESS_WORKLOAD
    )
