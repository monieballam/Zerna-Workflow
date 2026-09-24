"""Cluster retrieval priors for annotation tie-breaking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


def build_profile_text(
    top_degs: list[str] | str,
    tissue: str = "",
    cancer: str = "",
    label: str = "",
) -> str:
    """Build a normalized free-text representation for indexing and lookup."""
    if isinstance(top_degs, list):
        degs = " ".join(g.strip().upper() for g in top_degs if g)
    else:
        degs = (top_degs or "").strip().upper()
    parts = [degs, tissue.strip(), cancer.strip().upper(), label.strip()]
    return " ".join(part for part in parts if part).strip()


class LabeledClusterProfile:
    """One labeled cluster profile stored in the retrieval index."""

    def __init__(
        self,
        cluster_id: str,
        top_degs: list[str] | None = None,
        tissue: str = "",
        cancer: str = "",
        level3_label: str = "",
        species: str = "human",
        source_dataset: str = "",
    ) -> None:
        self.cluster_id = str(cluster_id)
        self.top_degs = list(top_degs) if top_degs else []
        self.tissue = tissue.strip()
        self.cancer = cancer.strip().upper()
        self.level3_label = level3_label.strip()
        self.species = species.strip() or "human"
        self.source_dataset = source_dataset.strip()

    def query_text(self) -> str:
        return build_profile_text(
            self.top_degs,
            tissue=self.tissue,
            cancer=self.cancer,
            label=self.level3_label,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LabeledClusterProfile:
        top_degs = data.get("top_degs")
        if isinstance(top_degs, str):
            top_degs = [gene.strip() for gene in top_degs.split() if gene.strip()]
        return cls(
            cluster_id=data.get("cluster_id", ""),
            top_degs=top_degs or data.get("top50_degs", []) or [],
            tissue=data.get("tissue", ""),
            cancer=data.get("cancer", ""),
            level3_label=data.get("level3_label", "") or data.get("final_level3_label", ""),
            species=data.get("species", "human"),
            source_dataset=data.get("source_dataset", ""),
        )


class ClusterPriorIndex:
    """In-memory TF-IDF index of labeled clusters."""

    def __init__(self) -> None:
        self.profiles: list[LabeledClusterProfile] = []
        self._vectorizer: Any = None
        self._matrix: Any = None

    def build(self, profiles: list[LabeledClusterProfile]) -> None:
        self.profiles = list(profiles)
        if not _SKLEARN_AVAILABLE or not self.profiles:
            self._vectorizer = None
            self._matrix = None
            return

        texts = [profile.query_text() for profile in self.profiles]
        self._vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 2),
            min_df=1,
        )
        self._matrix = self._vectorizer.fit_transform(texts)

    def retrieve_topk(
        self,
        query_text: str,
        k: int = 5,
        min_score: float = 0.0,
    ) -> list[tuple[LabeledClusterProfile, float]]:
        if not self.profiles or self._matrix is None or self._vectorizer is None:
            return []

        query_vector = self._vectorizer.transform([query_text])
        similarities = cosine_similarity(query_vector, self._matrix)[0]
        indices = similarities.argsort()[::-1][:k]

        results: list[tuple[LabeledClusterProfile, float]] = []
        for index in indices:
            score = float(similarities[index])
            if score >= min_score:
                results.append((self.profiles[index], score))
        return results

    def get_prior_and_evidence(
        self,
        query_degs: list[str],
        tissue: str = "",
        cancer: str = "",
        k: int = 5,
        min_score: float = 0.0,
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        query_text = build_profile_text(query_degs, tissue=tissue, cancer=cancer)
        retrieved = self.retrieve_topk(query_text, k=k, min_score=min_score)

        prior: dict[str, float] = {}
        evidence: list[dict[str, Any]] = []
        for profile, score in retrieved:
            if profile.level3_label:
                prior[profile.level3_label] = prior.get(profile.level3_label, 0.0) + score
            evidence.append(
                {
                    "cluster_id": profile.cluster_id,
                    "level3_label": profile.level3_label,
                    "score": round(score, 4),
                    "source_dataset": profile.source_dataset,
                }
            )

        total = sum(prior.values()) or 1.0
        normalized_prior = {label: value / total for label, value in prior.items()}
        return normalized_prior, evidence


def load_index_from_jsonl(path: str | Path) -> ClusterPriorIndex:
    """Load a JSONL prior index and build a searchable retrieval structure."""
    path = Path(path)
    profiles: list[LabeledClusterProfile] = []
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    profiles.append(LabeledClusterProfile.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue

    index = ClusterPriorIndex()
    index.build(profiles)
    return index
