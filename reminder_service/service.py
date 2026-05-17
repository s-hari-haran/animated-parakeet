import hashlib
import html
import json
from abc import ABC, abstractmethod
from typing import Dict, Type

from reminder_service.models import Appointment, ReminderResult


class BaseFormatter(ABC):
    @abstractmethod
    def build_ssml(self, appt: Appointment) -> str:
        raise NotImplementedError


def _escape(value: str) -> str:
    return html.escape(value, quote=False)


def _sanitize_xml_text(value: str) -> str:
    allowed = []
    for character in value:
        code_point = ord(character)
        if code_point in (0x9, 0xA, 0xD) or 0x20 <= code_point <= 0xD7FF or 0xE000 <= code_point <= 0xFFFD or 0x10000 <= code_point <= 0x10FFFF:
            allowed.append(character)
    return "".join(allowed)


def _format_time(appt: Appointment) -> str:
    return _sanitize_xml_text(appt.appointment_time.strftime("%A, %B %d at %I:%M %p").replace(" 0", " "))


class EnglishFormatter(BaseFormatter):
    def build_ssml(self, appt: Appointment) -> str:
        spaced_digits = _sanitize_xml_text(" ".join(appt.phone_number.removeprefix("+")))
        appointment_time = _escape(_format_time(appt))

        return (
            "<speak>"
            f"Hello {_escape(appt.patient_name)}, this is an automated reminder from {_escape(appt.clinic_name)}. "
            f"You have an upcoming dental appointment on {appointment_time}. "
            f"If you need to reschedule, please call us back at <prosody rate='slow'>{spaced_digits}</prosody>. "
            "<break time='300ms'/>We look forward to seeing you."
            "</speak>"
        )


class SpanishFormatter(BaseFormatter):
    def build_ssml(self, appt: Appointment) -> str:
        return f"<speak>Hola {_escape(_sanitize_xml_text(appt.patient_name))}, recordatorio de cita para {_escape(_sanitize_xml_text(appt.clinic_name))}.</speak>"


class ArabicFormatter(BaseFormatter):
    def build_ssml(self, appt: Appointment) -> str:
        return f"<speak>Marhaban {_escape(_sanitize_xml_text(appt.patient_name))}, tadhkir bialmawd mae {_escape(_sanitize_xml_text(appt.clinic_name))}.</speak>"


REGISTRY: Dict[str, Type[BaseFormatter]] = {
    "en": EnglishFormatter,
    "es": SpanishFormatter,
    "ar": ArabicFormatter,
}


def _idempotency_key(appointment: Appointment) -> str:
    payload = json.dumps(appointment.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_reminder(appointment: Appointment) -> ReminderResult:
    formatter_cls = REGISTRY[appointment.locale]
    ssml_output = formatter_cls().build_ssml(appointment)

    return ReminderResult(
        appointment_id=appointment.appointment_id,
        locale=appointment.locale,
        ssml=ssml_output,
        idempotency_key=_idempotency_key(appointment),
    )