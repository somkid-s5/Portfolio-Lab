"""Compare a downloaded report with exact source fixture bytes. No cloud calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from csv_domain import summarize


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def verify(source, report, *, processor_version="v1"):
    with Path(source).open("rb") as handle:
        data = handle.read(5242881)
    expected = summarize(data, max_bytes=5242880, max_rows=50000,
                         processor_version=processor_version)
    with Path(report).open("rb") as handle:
        body = handle.read(8388609)
    if len(body) > 8388608:
        raise ValueError("report_too_large")
    actual = json.loads(body, object_pairs_hook=unique_object,
                        parse_constant=lambda _: (_ for _ in ()).throw(
                            ValueError("invalid_json_constant")))
    if actual != expected:
        raise ValueError("report_does_not_match_fixture")
    return {"event": "report_matches_fixture", "rows": expected["rows"],
            "units": expected["units"], "total_satang": expected["total_satang"],
            "input_sha256": expected["input_sha256"],
            "processor_version": processor_version}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--processor-version", default="v1")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.source, args.report,
                                processor_version=args.processor_version), sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"event": "report_verification_failed",
                          "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
