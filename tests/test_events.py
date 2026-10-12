from dataclasses import FrozenInstanceError
import json
import unittest
from worker.events import decode, consume, InvalidEvent, InvalidAcknowledgement

ID = "11111111-1111-4111-8111-111111111111"
EVENT = dict(eventId=ID, eventType="inventory.stock.changed", schemaVersion=1, sequence=1,
             occurredAt="2026-10-11T12:00:00Z", traceId="event-test", movementId=ID,
             movementType="ENTRY", lotId=ID, medicationId=ID, supplierId=ID,
             expiresOn="2099-01-01", quantity=10, delta=10, onHandQuantity=10, entryId=ID, exitId=None)

class Owner:
    def __init__(self, result=None, error=None):
        self.calls = []; self.error = error
        self.result = result if result is not None else dict(eventId=ID, sequence=1, applied=True)
    def apply(self, event):
        self.calls.append(event)
        if self.error: raise self.error
        return self.result

class EventTest(unittest.TestCase):
    def raw(self, **patch):
        body = dict(EVENT); body.update(patch)
        return json.dumps(body).encode()

    def test_entry_and_exit(self):
        self.assertEqual(decode(self.raw()).event_id, ID)
        event = decode(self.raw(movementType="EXIT", delta=-10, entryId=None, exitId=ID))
        self.assertEqual(event.payload["delta"], -10)

    def test_rejects_types_bounds_schema_and_fields(self):
        for patch in [dict(sequence=True), dict(sequence=1.0), dict(sequence=2**63),
                      dict(quantity="10"), dict(quantity=1000001), dict(onHandQuantity=-1),
                      dict(schemaVersion=2), dict(eventType="other"), dict(authorization="forbidden"),
                      dict(occurredAt="yesterday"), dict(expiresOn="2099-02-30")]:
            with self.subTest(patch=patch), self.assertRaises(InvalidEvent): decode(self.raw(**patch))

    def test_rejects_identity_delta_and_noncanonical_ids(self):
        for patch in [dict(movementId="22222222-2222-4222-8222-222222222222"), dict(delta=9),
                      dict(lotId="ABCDEFAB-1234-4234-8234-ABCDEFABCDEF"), dict(delta=-10), dict(exitId=ID)]:
            with self.subTest(patch=patch), self.assertRaises(InvalidEvent): decode(self.raw(**patch))

    def test_rejects_bad_json_utf8_duplicates_and_size(self):
        for raw in [b"", b"{", b"\xff", b"{}"*32769, b'{"eventId":"first","eventId":"second"}', b"[]", b'{"sequence":'+b'1'*5000+b'}']:
            with self.subTest(raw=raw[:30]), self.assertRaises(InvalidEvent): decode(raw)

    def test_validated_payload_is_immutable(self):
        event = decode(self.raw())
        with self.assertRaises(TypeError): event.payload["quantity"] = 20
        with self.assertRaises(FrozenInstanceError): event.sequence = 2

    def test_ack_requires_owner_confirmation_for_applied_or_duplicate(self):
        for applied in [True, False]:
            owner = Owner(dict(eventId=ID, sequence=1, applied=applied))
            self.assertEqual(consume(self.raw(), owner), dict(eventId=ID, sequence=1, accepted=True))
            self.assertEqual(len(owner.calls), 1)
            self.assertEqual(dict(owner.calls[0].payload), EVENT)

    def test_wrong_owner_ack_is_not_accepted(self):
        for result in [{}, dict(eventId="wrong", sequence=1, applied=True),
                       dict(eventId=ID, sequence=True, applied=True), dict(eventId=ID, sequence=2, applied=True),
                       dict(eventId=ID, sequence=1, applied="yes")]:
            with self.subTest(result=result), self.assertRaises(InvalidAcknowledgement): consume(self.raw(), Owner(result))

    def test_owner_failure_is_not_acknowledged(self):
        owner = Owner(error=RuntimeError("simulated owner unavailable"))
        with self.assertRaises(RuntimeError): consume(self.raw(), owner)
        self.assertEqual(len(owner.calls), 1)

    def test_invalid_event_never_reaches_owner(self):
        owner = Owner()
        with self.assertRaises(InvalidEvent): consume(self.raw(delta=9), owner)
        self.assertEqual(owner.calls, [])

if __name__ == "__main__":
    unittest.main()
