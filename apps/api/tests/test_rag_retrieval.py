"""Deterministic retrieval contracts; no database or embedding spend required."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from aiseoonline_api.rag.retrieval import (
    RetrievalOptions,
    reciprocal_rank_fusion,
)


def test_reciprocal_rank_fusion_rewards_agreement_and_preserves_unique_ids() -> None:
    a, b, c, d = (uuid4() for _ in range(4))
    scores = reciprocal_rank_fusion([a, b, c], [b, d, a], k=60)
    assert set(scores) == {a, b, c, d}
    assert scores[b] > scores[a] > scores[c]
    assert scores[b] > scores[d]
    assert scores[b] == pytest.approx(1 / 62 + 1 / 61)


def test_reciprocal_rank_fusion_is_deterministic() -> None:
    ids = [uuid4() for _ in range(3)]
    assert reciprocal_rank_fusion(ids, list(reversed(ids))) == reciprocal_rank_fusion(
        ids, list(reversed(ids))
    )
    with pytest.raises(ValueError):
        reciprocal_rank_fusion(ids, ids, k=0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top_k": 0}, {"top_k": 11}, {"candidate_k": 3},
        {"top_k": 10, "candidate_k": 5},
        {"max_context_tokens": 50}, {"max_context_tokens": 12001},
        {"min_semantic_similarity": 1.1}, {"min_keyword_rank": -0.1},
        {"min_fused_score": -0.1}, {"rrf_k": 0},
        {"max_age_days": 0}, {"document_types": ()},
        {"document_types": ("guide", "guide")},
        {"document_types": ("private",)},
        {"mode": "unknown"},
    ],
)
def test_retrieval_options_reject_out_of_budget_or_unknown_filters(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        RetrievalOptions(**kwargs)


def test_retrieval_options_defaults_are_bounded() -> None:
    options = RetrievalOptions()
    assert options.top_k <= options.candidate_k <= 50
    assert options.max_context_tokens <= 12000
    assert options.mode == "hybrid"
    assert options.document_types == ("web_page", "guide", "reference")
