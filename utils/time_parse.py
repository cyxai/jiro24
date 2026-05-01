
Action: file_editor create /app/jiro/utils/time_parse.py --file-text "\"\"\"Duration parser. Supports '10s', '5m', '2h', '1d', '1w', or compound '1h30m'.\"\"\"
from __future__ import annotations
import re
from datetime import timedelta

_UNITS = {
    \"s\": 1, \"sec\": 1, \"secs\": 1, \"second\": 1, \"seconds\": 1,
    \"m\": 60, \"min\": 60, \"mins\": 60, \"minute\": 60, \"minutes\": 60,
    \"h\": 3600, \"hr\": 3600, \"hrs\": 3600, \"hour\": 3600, \"hours\": 3600,
    \"d\": 86400, \"day\": 86400, \"days\": 86400,
    \"w\": 604800, \"wk\": 604800, \"week\": 604800, \"weeks\": 604800,
}

_PATTERN = re.compile(r\"(\d+)\s*([a-zA-Z]+)\")


def parse_duration(text: str) -> int | None:
    \"\"\"Return total seconds, or None if not parseable.\"\"\"
    if not text:
        return None
    text = text.strip().lower()
    # bare integer = seconds
    if text.isdigit():
        return int(text)
    total = 0
    matched = False
    for num, unit in _PATTERN.findall(text):
        unit = unit.lower()
        if unit not in _UNITS:
            return None
        total += int(num) * _UNITS[unit]
        matched = True
    return total if matched else None


def humanize(seconds: int) -> str:
    \"\"\"Render seconds as compact '1d 2h 3m 4s'.\"\"\"
    seconds = int(seconds)
    if seconds <= 0:
        return \"0s\"
    parts = []
    for label, size in ((\"w\", 604800), (\"d\", 86400), (\"h\", 3600), (\"m\", 60), (\"s\", 1)):
        if seconds >= size:
            n, seconds = divmod(seconds, size)
            parts.append(f\"{n}{label}\")
    return \" \".join(parts[:3])


def to_timedelta(text: str) -> timedelta | None:
    s = parse_duration(text)
    return timedelta(seconds=s) if s is not None else None
"
Observation: Create successful: /app/jiro/utils/time_parse.py