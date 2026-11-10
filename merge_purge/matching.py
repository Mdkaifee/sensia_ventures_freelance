"""Pairwise duplicate predicate and connected components within address blocks."""

from collections import defaultdict
from typing import Mapping, Sequence

from .normalization import Identity


def duplicates(a: Identity, b: Identity, nicknames: Mapping[str, str]) -> bool:
    if a.block != b.block or not a.first or not b.first:
        return False
    if a.suffix and b.suffix and a.suffix != b.suffix:
        return False
    initial_match = ((len(a.first) == 1 and b.first.startswith(a.first))
                     or (len(b.first) == 1 and a.first.startswith(b.first)))
    return initial_match or nicknames.get(a.first, a.first) == nicknames.get(b.first, b.first)


def components(identities: Sequence[Identity], nicknames: Mapping[str, str]) -> list[list[int]]:
    """Union direct matches, retaining transitive links including suppress bridges.

    Exact address/last-name blocking avoids comparing unrelated records. Worst
    case remains quadratic within one large block, deliberately kept readable.
    """
    parent = list(range(len(identities)))
    size = [1] * len(parent)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        i, j = find(i), find(j)
        if i == j:
            return
        if size[i] < size[j]:
            i, j = j, i
        parent[j] = i
        size[i] += size[j]

    blocks: dict[tuple, list[int]] = defaultdict(list)
    for i, identity in enumerate(identities):
        for j in blocks[identity.block]:
            if duplicates(identity, identities[j], nicknames):
                union(i, j)
        blocks[identity.block].append(i)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(identities)):
        groups[find(i)].append(i)
    return list(groups.values())
