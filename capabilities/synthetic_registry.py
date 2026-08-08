"""Deterministic synthetic manifests for retrieval precision benchmarking."""

from __future__ import annotations

import random

from capabilities.registry import Manifest

ADJECTIVES = [
    "azure", "crimson", "emerald", "velvet", "bronze", "cedar", "quartz",
    "meadow", "pixel", "vortex", "prism", "harbor", "gazette", "lantern",
    "marble", "orbit", "pebble", "raven", "saffron", "thistle",
]
NOUNS = [
    "wobble", "sprocket", "magnet", "constellation", "manifold", "beacon",
    "cascade", "diorama", "envelope", "fable", "girder", "hollow",
    "incline", "juniper", "keystone", "lagoon", "monolith", "nectar",
    "outpost", "parcel",
]
VERBS = [
    "archives", "simulates", "renders", "catalogs", "transforms",
    "correlates", "indexes", "projects",
]


def build_synthetic_manifests(n: int = 60, seed: int = 42) -> list[Manifest]:
    rng = random.Random(seed)
    manifests: list[Manifest] = []
    for i in range(n):
        verb = rng.choice(VERBS)
        adj = rng.choice(ADJECTIVES)
        noun = rng.choice(NOUNS)
        noun2 = rng.choice(NOUNS)
        description = (
            f"{verb.capitalize()} {adj} {noun} records and {rng.choice(VERBS)} "
            f"{noun2} summaries for laboratory use."
        )
        manifests.append(
            Manifest(
                id=f"syn_{i:02d}",
                description=description,
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object", "properties": {}},
                side_effect="read",
                tags=(adj, noun),
                managers=("lab",),
                preconditions=(),
                cost_hint="low",
                source="synthetic-benchmark",
            )
        )
    return manifests
