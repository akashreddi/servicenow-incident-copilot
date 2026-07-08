"""Seed the demo environment:
1. Creates realistic incidents in your ServiceNow PDI (optional, --snow flag)
2. Indexes historical 'resolved' incidents + KB articles into Chroma

Usage:
    python -m scripts.seed_data            # vector store only
    python -m scripts.seed_data --snow     # also create live incidents in the PDI
"""
import asyncio
import sys

from app.config import get_settings
from app.services.embedding_service import EmbeddingService
from app.services.llm import LLMClient
from app.services.servicenow_client import ServiceNowClient

HISTORICAL_INCIDENTS = [
    ("HIST0001", "VPN disconnects every 10 minutes", "Network Operations",
     "Increased DPD timeout on the Cisco ASA profile; pushed new AnyConnect profile."),
    ("HIST0002", "Cannot connect to corporate VPN from home", "Network Operations",
     "User's ISP blocked UDP 443; switched client to TCP fallback."),
    ("HIST0003", "SAP GUI freezes when opening purchase orders", "Enterprise Applications",
     "Cleared local SAP GUI cache and updated to patch level 7."),
    ("HIST0004", "Salesforce opportunity sync failing to ERP", "Enterprise Applications",
     "Mule integration retry queue was full; purged DLQ and replayed messages."),
    ("HIST0005", "Laptop blue screens after Windows update", "End User Computing",
     "Rolled back KB5034441; device re-imaged and drivers updated."),
    ("HIST0006", "Printer on floor 3 shows offline for everyone", "End User Computing",
     "Print spooler service hung on the print server; restarted service."),
    ("HIST0007", "Nightly ETL job timing out against Oracle DB", "Database Administration",
     "Rebuilt stale index on FACT_SALES; job runtime back to 40 minutes."),
    ("HIST0008", "Application getting connection pool exhausted errors", "Database Administration",
     "Increased max sessions and fixed connection leak in app config."),
    ("HIST0009", "Locked out of account after password change", "Identity & Access Management",
     "Stale credentials cached on mobile device kept locking account; cleared and re-enrolled."),
    ("HIST0010", "SSO login loops back to sign-in page", "Identity & Access Management",
     "Clock skew on the SP server broke SAML assertion validity window; fixed NTP."),
    ("HIST0011", "AKS pods stuck in CrashLoopBackOff after deploy", "Cloud Platform",
     "Bad liveness probe path in new Helm chart; hotfixed values.yaml."),
    ("HIST0012", "Azure DevOps pipeline agents all offline", "Cloud Platform",
     "Agent VM scale set hit subscription quota; raised quota and rescaled."),
    ("HIST0013", "Received suspicious email asking for gift cards", "Security Operations",
     "Confirmed phishing; purged from all mailboxes and blocked sender domain."),
    ("HIST0014", "USB drive found in parking lot plugged into workstation", "Security Operations",
     "Device isolated, forensics run, no malware found; user retrained."),
]

KB_ARTICLES = [
    {"id": "KB0001", "title": "VPN Troubleshooting Runbook",
     "body": "Steps for AnyConnect issues: verify UDP/TCP 443 reachability, check DPD timeout, "
             "reset client profile, escalate to Network Operations if site-wide."},
    {"id": "KB0002", "title": "SAP GUI Known Issues and Fixes",
     "body": "Freezes on PO screens: clear cache under %APPDATA%/SAP, verify patch level >= 7. "
             "Transaction dumps: capture ST22 details before escalating to Enterprise Applications."},
    {"id": "KB0003", "title": "Windows Update Rollback Procedure",
     "body": "For BSOD after updates: boot safe mode, wusa /uninstall the KB, pause updates 7 days, "
             "log device serial for the EUC remediation wave."},
    {"id": "KB0004", "title": "Database Performance Triage Guide",
     "body": "Check AWR/Query Store first. Common causes: stale statistics, missing index, "
             "connection leaks. Connection pool exhaustion requires app-side and DB-side review."},
    {"id": "KB0005", "title": "Account Lockout Investigation",
     "body": "Use lockout status tool to find source DC and caller machine. 80% of repeat lockouts "
             "are stale credentials on mobile devices or scheduled tasks."},
    {"id": "KB0006", "title": "Phishing Response Playbook",
     "body": "Never click links. Report via button, SecOps purges within 15 min SLA, "
             "block sender/domain, check for credential submission, force reset if submitted."},
    {"id": "KB0007", "title": "AKS Deployment Failure Checklist",
     "body": "kubectl describe pod for events; common: bad probes, image pull errors, quota. "
             "CrashLoopBackOff after deploy usually means config/probe regression — check Helm diff."},
]

NEW_DEMO_INCIDENTS = [
    ("Cannot access VPN since this morning, keeps timing out", "Working from home, AnyConnect times out at 90%."),
    ("SAP purchase order screen frozen for whole procurement team", "Multiple users affected since 9am IST."),
    ("Strange email from CEO asking to buy Apple gift cards urgently", "Sender domain looks off: ceo@c0mpany.com"),
    ("Pipeline deploy failing, pods restarting continuously", "After this morning's release, checkout service pods CrashLoopBackOff."),
    ("Locked out of my account third time today", "Changed password yesterday, phone email still configured with old one."),
]


async def main() -> None:
    settings = get_settings()
    llm = LLMClient(settings)
    emb = EmbeddingService(settings, llm)

    print("Indexing KB articles...")
    n = await emb.index_kb_articles(KB_ARTICLES)
    print(f"  {n} KB articles indexed")

    print("Indexing historical incidents (routing memory)...")
    for hid, desc, group, resolution in HISTORICAL_INCIDENTS:
        await emb.index_resolved_incident(hid, hid, desc, group, resolution)
    print(f"  {len(HISTORICAL_INCIDENTS)} historical incidents indexed")

    if "--snow" in sys.argv:
        snow = ServiceNowClient(settings)
        print("Creating live demo incidents in ServiceNow PDI...")
        for short, desc in NEW_DEMO_INCIDENTS:
            result = await snow.create_incident({"short_description": short, "description": desc})
            print(f"  {result['number']} ({result['sys_id']})")
        await snow.aclose()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
