from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol
from uuid import UUID
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts/stock-changed.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())

class InvalidEvent(ValueError):
    pass

class InvalidAcknowledgement(RuntimeError):
    pass

@dataclass(frozen=True)
class StockEvent:
    event_id: str
    sequence: int
    payload: Mapping

class InventoryOwner(Protocol):
    def apply(self, event: StockEvent) -> Mapping: ...

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidEvent("Duplicate JSON field")
        result[key] = value
    return result

def decode(raw: bytes) -> StockEvent:
    if not raw or len(raw) > 65536:
        raise InvalidEvent("Invalid event size")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        VALIDATOR.validate(payload)
        for name in ("schemaVersion", "sequence", "quantity", "delta", "onHandQuantity"):
            if type(payload[name]) is not int:
                raise InvalidEvent("Integer field required")
        if payload["sequence"] > 9223372036854775807:
            raise InvalidEvent("Sequence out of range")
        for name in ("eventId", "movementId", "lotId", "medicationId", "supplierId", "entryId", "exitId"):
            value = payload[name]
            if value is not None and str(UUID(value)) != value:
                raise InvalidEvent("Canonical UUID required")
        delta = payload["quantity"] if payload["movementType"] == "ENTRY" else -payload["quantity"]
        if payload["eventId"] != payload["movementId"] or payload["delta"] != delta:
            raise InvalidEvent("Event identity or delta mismatch")
        return StockEvent(payload["eventId"], payload["sequence"], MappingProxyType(dict(payload)))
    except (UnicodeError, json.JSONDecodeError, ValidationError, TypeError, KeyError, ValueError) as error:
        raise InvalidEvent("Invalid stock event") from error

def consume(raw: bytes, owner: InventoryOwner, after_confirm=None) -> dict:
    event = decode(raw)
    result = owner.apply(event)
    if not isinstance(result, Mapping) or result.get("eventId") != event.event_id or type(result.get("sequence")) is not int:
        raise InvalidAcknowledgement("Invalid owner acknowledgement")
    if result["sequence"] != event.sequence or type(result.get("applied")) is not bool:
        raise InvalidAcknowledgement("Owner acknowledgement mismatch")
    if after_confirm is not None:
        after_confirm(event)
    return {"eventId": event.event_id, "sequence": event.sequence, "accepted": True}
