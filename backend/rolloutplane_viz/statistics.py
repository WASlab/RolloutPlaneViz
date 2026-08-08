from __future__ import annotations

import hashlib
import math
import random
import statistics

from rolloutplane_viz.models import ComparisonRequest, Estimate, Series


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate a quantile from no values")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _mean_resample(values: list[float], block_length: int, rng: random.Random) -> float:
    sampled: list[float] = []
    while len(sampled) < len(values):
        start = rng.randrange(len(values))
        sampled.extend(values[(start + offset) % len(values)] for offset in range(block_length))
    return statistics.fmean(sampled[: len(values)])


def _pooled_effect(baseline: list[float], candidate: list[float], delta: float) -> float | None:
    degrees = len(baseline) + len(candidate) - 2
    if degrees <= 0:
        return None
    baseline_variance = statistics.variance(baseline) if len(baseline) > 1 else 0.0
    candidate_variance = statistics.variance(candidate) if len(candidate) > 1 else 0.0
    pooled = math.sqrt(
        ((len(baseline) - 1) * baseline_variance + (len(candidate) - 1) * candidate_variance)
        / degrees
    )
    return delta / pooled if pooled else None


def _normal_estimate(
    metric: str,
    unit: str,
    baseline: list[float],
    candidate: list[float],
    confidence_level: float,
) -> Estimate:
    baseline_mean = statistics.fmean(baseline)
    candidate_mean = statistics.fmean(candidate)
    delta = candidate_mean - baseline_mean
    variance = statistics.variance(baseline) / len(baseline) if len(baseline) > 1 else 0.0
    variance += statistics.variance(candidate) / len(candidate) if len(candidate) > 1 else 0.0
    standard_error = math.sqrt(variance)
    # The normal approximation is retained for backwards compatibility. The
    # default 95% value is exact; other levels use a dependency-free approximation.
    probability = 0.5 + confidence_level / 2
    z_score = statistics.NormalDist().inv_cdf(probability)
    margin = z_score * standard_error
    if standard_error:
        probability_greater = 1 - statistics.NormalDist(mu=delta, sigma=standard_error).cdf(0)
    else:
        probability_greater = 1.0 if delta > 0 else 0.0 if delta < 0 else 0.5
    return Estimate(
        metric=metric,
        unit=unit,
        baseline_mean=baseline_mean,
        candidate_mean=candidate_mean,
        absolute_delta=delta,
        relative_delta=delta / abs(baseline_mean) if baseline_mean else None,
        confidence_low=delta - margin,
        confidence_high=delta + margin,
        sample_count_baseline=len(baseline),
        sample_count_candidate=len(candidate),
        standard_error=standard_error,
        standardized_effect=_pooled_effect(baseline, candidate, delta),
        probability_candidate_greater=probability_greater,
    )


def _bootstrap_estimate(
    metric: str,
    unit: str,
    baseline: list[float],
    candidate: list[float],
    request: ComparisonRequest,
) -> Estimate:
    baseline_mean = statistics.fmean(baseline)
    candidate_mean = statistics.fmean(candidate)
    delta = candidate_mean - baseline_mean
    shortest = min(len(baseline), len(candidate))
    block_length = request.block_length or max(1, round(shortest ** (1 / 3)))
    block_length = min(block_length, shortest)
    seed_material = "\0".join(
        [
            request.run_id,
            request.baseline_bundle,
            request.candidate_bundle,
            metric,
            str(request.resamples),
            str(request.block_length),
            str(request.confidence_level),
        ]
    ).encode()
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    rng = random.Random(seed)
    deltas = [
        _mean_resample(candidate, block_length, rng) - _mean_resample(baseline, block_length, rng)
        for _ in range(request.resamples)
    ]
    alpha = (1 - request.confidence_level) / 2
    standard_error = statistics.stdev(deltas) if len(deltas) > 1 else None
    greater = (
        sum(value > 0 for value in deltas) + 0.5 * sum(value == 0 for value in deltas)
    ) / len(deltas)
    return Estimate(
        metric=metric,
        unit=unit,
        baseline_mean=baseline_mean,
        candidate_mean=candidate_mean,
        absolute_delta=delta,
        relative_delta=delta / abs(baseline_mean) if baseline_mean else None,
        confidence_low=_quantile(deltas, alpha),
        confidence_high=_quantile(deltas, 1 - alpha),
        sample_count_baseline=len(baseline),
        sample_count_candidate=len(candidate),
        standard_error=standard_error,
        standardized_effect=_pooled_effect(baseline, candidate, delta),
        probability_candidate_greater=greater,
        block_length=block_length,
    )


def compare_series(series: list[Series], request: ComparisonRequest) -> list[Estimate]:
    selected = set(request.metric_names)
    estimates: list[Estimate] = []
    for item in series:
        if selected and item.name not in selected:
            continue
        baseline = [
            point.value
            for point in sorted(item.points, key=lambda point: point.timestamp_ns)
            if point.bundle_id == request.baseline_bundle
        ]
        candidate = [
            point.value
            for point in sorted(item.points, key=lambda point: point.timestamp_ns)
            if point.bundle_id == request.candidate_bundle
        ]
        if not baseline or not candidate:
            continue
        if request.method == "normal_independent":
            estimate = _normal_estimate(
                item.name, item.unit, baseline, candidate, request.confidence_level
            )
        else:
            estimate = _bootstrap_estimate(item.name, item.unit, baseline, candidate, request)
        estimates.append(estimate)
    return estimates
