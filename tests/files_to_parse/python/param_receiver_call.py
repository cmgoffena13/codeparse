import typing as t
from typing import Optional


class DeployabilityIndex:
    def is_representative(self, snapshot: object) -> bool:
        return True


def to_table_mapping(deployability_index: DeployabilityIndex) -> bool:
    return deployability_index.is_representative(None)


def optional_typing(deployability_index: Optional[DeployabilityIndex]) -> bool:
    return deployability_index.is_representative(None)


def optional_t(deployability_index: t.Optional[DeployabilityIndex]) -> bool:
    return deployability_index.is_representative(None)
