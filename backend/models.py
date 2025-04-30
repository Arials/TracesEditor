from pydantic import BaseModel, Field
from pydantic.config import ConfigDict
from typing import List


class Rule(BaseModel):
    """
    A CIDR transformation rule. We accept either the new field names
    (`source`, `target`) or the legacy names (`from_cidr`, `to_cidr`)
    so that old JSON payloads do not break.
    """
    source: str = Field(..., alias='from_cidr')
    target: str = Field(..., alias='to_cidr')

    # Pydantic v2 — use ConfigDict to allow population by field name
    model_config = ConfigDict(populate_by_name=True)


class RuleInput(BaseModel):
    session_id: str
    rules: List[Rule]