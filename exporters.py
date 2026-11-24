"""Calendar (.ics) and spreadsheet (.csv) export for a leave plan."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from optimizer import Break

OUT_DIR = "output"


def _ics_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def _esc(s: str) -> str:
    return s.replace(chr(92), chr(92) * 2).replace(",", chr(92) + ",").replace(";", chr(92) + ";")


def to_ics(breaks: list[Break], calendar_name: str = "PTO-Hacker plan") -> str:
    """All-day VEVENTs, one per break. DTEND is exclusive per RFC 5545."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PTO-Hacker//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_esc(calendar_name)}",
    ]
    for i, b in enumerate(breaks):
        cost = "free" if b.is_free else f"{b.cost} leave"
        desc = (f"{b.span} days off for {cost}. "
                + (f"Bridges: {', '.join(dict.fromkeys(b.reasons))}." if b.reasons else ""))
        lines += [
            "BEGIN:VEVENT",
            f"UID:pto-hacker-{b.start.isoformat()}-{i}@local",
            f"DTSTAMP:{date.today().strftime('%Y%m%dT000000Z')}",
            f"DTSTART;VALUE=DATE:{_ics_date(b.start)}",
            f"DTEND;VALUE=DATE:{_ics_date(b.end + timedelta(days=1))}",
            f"SUMMARY:{_esc('Off — ' + cost)}",
            f"DESCRIPTION:{_esc(desc)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def to_csv(breaks: list[Break]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Start", "End", "Days off", "Leave used", "Leverage",
                "Leave dates", "Holidays bridged"])
    for b in breaks:
        w.writerow([
            b.start.isoformat(),
            b.end.isoformat(),
            b.span,
            b.cost,
            f"{b.leverage:.2f}" if b.cost else "free",
            " ".join(d.isoformat() for d in b.leave_days),
            "; ".join(dict.fromkeys(b.reasons)),
        ])
    return buf.getvalue()
