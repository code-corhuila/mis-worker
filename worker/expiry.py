import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from worker.events import InvalidAcknowledgement

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts/expiry-evaluation.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())

def confirm_evaluation(result, lot_id, window_days):
    try:
        VALIDATOR.validate(result)
        if result["lotId"] != lot_id:
            raise ValueError("Wrong lot evaluation")
        alert = result["alert"]
        if alert is not None:
            if alert["lotId"] != lot_id or type(alert["windowDays"]) is not int or alert["windowDays"] != window_days:
                raise ValueError("Wrong evaluation parameters")
            if type(alert["onHandQuantity"]) is not int:
                raise ValueError("Invalid physical balance")
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        raise InvalidAcknowledgement("Invalid expiry evaluation") from error
