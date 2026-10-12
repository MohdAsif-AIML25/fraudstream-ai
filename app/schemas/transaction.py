from datetime import timezone 
from typing import Literal 

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

class TransactionInput(BaseModel):
    model_config=ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    schema_version:Literal["1.0"]="1.0"

    transaction_id:str=Field(
        min_length=1,
        max_length=100,
    )

    account_id:str=Field(
        min_length=1,
        max_length=100,
    )

    event_time:AwareDatetime 
    amount_minor:int=Field(
        gt=0,
        strict=True,
    )

    currency:Literal["INR"]

    merchant_category:str=Field(
        min_length=1,
        max_length=100,
    )

    channel:Literal["online","pos","atm"]

    device_id:str|None=Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    @field_validator("event_time")
    @classmethod
    def normalize_time_to_uts(cls,value):
        return value.astimezone(timezone.utc)