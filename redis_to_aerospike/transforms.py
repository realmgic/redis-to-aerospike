"""Optional post-conversion hooks -- the data-modeling extension seam.

A :class:`Transform` receives the :class:`AerospikeRecord` produced by a converter
and returns a (possibly modified) record. The migrator applies transforms in order
after conversion and before writing. This is where a future *data-modeling*
migration step lives: implement a transform, add it to the migrator's list, and
the rest of the pipeline is untouched.

``IdentityTransform`` is the do-nothing default and doubles as a copy-paste
starting point.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .models import AerospikeRecord


class Transform(ABC):
    """Base class for post-conversion record transforms."""

    @abstractmethod
    def apply(self, record: AerospikeRecord) -> AerospikeRecord:  # pragma: no cover
        raise NotImplementedError


class IdentityTransform(Transform):
    """Returns the record unchanged. Use as a template for real transforms."""

    def apply(self, record: AerospikeRecord) -> AerospikeRecord:
        return record


def apply_all(record: AerospikeRecord, transforms: Iterable[Transform]) -> AerospikeRecord:
    """Run ``record`` through every transform, in order."""
    for transform in transforms:
        record = transform.apply(record)
    return record


# Example of a real data-modeling transform. It is NOT enabled by default and is
# not wired by the CLI; it exists to show how little is needed to extend the
# pipeline. It adds a provenance bin recording where the record came from.
class AddSourceTagTransform(Transform):
    """Annotate every migrated record with a constant ``source`` bin (library example)."""

    def __init__(self, source: str = "redis", bin_name: str = "source"):
        self.source = source
        self.bin_name = bin_name

    def apply(self, record: AerospikeRecord) -> AerospikeRecord:
        record.bins[self.bin_name] = self.source
        return record
