from datetime import datetime
from typing import Literal
import re

from pydantic import BaseModel, Field, field_validator


class Appointment(BaseModel):
    appointment_id: str = Field(..., description="Unique, immutable identifier for the appointment")
    patient_name: str = Field(..., min_length=1, max_length=100)
    phone_number: str = Field(..., description="Strict E.164 formatted telephone number string")
    appointment_time: datetime = Field(..., description="Target scheduled timestamp")
    locale: Literal["en", "es", "ar"] = Field("en", description="Language targeting context code")
    clinic_name: str = Field("Teraleads Dental", min_length=1)

    @field_validator("phone_number")
    @classmethod
    def validate_e164_format(cls, value: str) -> str:
        pattern = r"^\+[1-9]\d{1,14}$"
        if not re.fullmatch(pattern, value):
            raise ValueError("Phone number field must comply strictly with international E.164 formatting rules.")
        return value


class ReminderResult(BaseModel):
    appointment_id: str
    locale: str
    ssml: str
    idempotency_key: str