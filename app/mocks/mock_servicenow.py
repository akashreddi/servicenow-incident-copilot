"""In-memory ServiceNow double. Same method signatures as ServiceNowClient,
so IncidentService cannot tell the difference (duck typing / dependency inversion).

Pre-seeded with demo incidents so `APP_MODE=mock` demos instantly.
"""
import itertools
import logging
import uuid
from typing import Any, Optional

from app.models import Incident

logger = logging.getLogger(__name__)

DEMO_INCIDENTS = [
    ("Cannot access VPN since this morning, keeps timing out",
     "Working from home, AnyConnect times out at 90% every attempt."),
    ("SAP purchase order screen frozen for whole procurement team",
     "Multiple users affected since 9am. Transaction ME21N unresponsive."),
    ("Strange email from CEO asking to buy Apple gift cards urgently",
     "Sender domain looks off: ceo@c0mpany.com. Several colleagues got the same mail."),
    ("Pipeline deploy failing, pods restarting continuously",
     "After this morning's release, checkout service pods are in CrashLoopBackOff."),
    ("Locked out of my account third time today",
     "Changed password yesterday; my phone's mail app still has the old one configured."),
    ("Printer on floor 3 not working for anyone",
     "Shows offline in the print dialog for the entire floor since lunch."),
]


class MockServiceNowClient:
    def __init__(self) -> None:
        self._incidents: dict[str, dict[str, Any]] = {}
        self._counter = itertools.count(10001)
        self._groups = {}  # name -> fake sys_id
        for short, desc in DEMO_INCIDENTS:
            self._create(short, desc)
        logger.info("MockServiceNow seeded with %d incidents", len(self._incidents))

    def _create(self, short: str, desc: str) -> dict[str, Any]:
        sys_id = uuid.uuid4().hex
        record = {
            "sys_id": sys_id,
            "number": f"INC{next(self._counter):07d}",
            "short_description": short,
            "description": desc,
            "category": "", "subcategory": "", "priority": "", "urgency": "",
            "impact": "", "state": "New", "assignment_group": "", "caller_id": "demo.user",
            "opened_at": "", "work_notes_log": [],
        }
        self._incidents[sys_id] = record
        return record

    # ---- same interface as ServiceNowClient ----
    async def aclose(self) -> None: ...

    async def get_incident(self, sys_id: str) -> Incident:
        rec = self._incidents[sys_id]
        return Incident(**{k: v for k, v in rec.items() if k in Incident.model_fields})

    async def list_incidents(self, query: str = "active=true", limit: int = 50) -> list[Incident]:
        return [
            Incident(**{k: v for k, v in rec.items() if k in Incident.model_fields})
            for rec in list(self._incidents.values())[:limit]
        ]

    async def update_incident(self, sys_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        rec = self._incidents[sys_id]
        note = fields.pop("work_notes", None)
        if note:
            rec["work_notes_log"].append(note)
        # resolve fake group sys_id back to name for readability
        for name, gid in self._groups.items():
            if fields.get("assignment_group") == gid:
                fields["assignment_group"] = name
        rec.update(fields)
        logger.info("Mock update %s: %s", rec["number"], {k: v for k, v in fields.items()})
        return rec

    async def add_work_note(self, sys_id: str, note: str) -> None:
        await self.update_incident(sys_id, {"work_notes": note})

    async def resolve_group_sys_id(self, group_name: str) -> Optional[str]:
        return self._groups.setdefault(group_name, f"mock-{uuid.uuid4().hex[:8]}")

    async def create_incident(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self._create(fields.get("short_description", ""), fields.get("description", ""))
