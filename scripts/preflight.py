"""Preflight doctor for live mode. Checks every integration link in dependency
order and reports exactly which one is broken.

Usage:
    python -m scripts.preflight              # check everything
    python -m scripts.preflight --fix-groups # also create missing assignment groups
"""
import asyncio
import json
import sys
from pathlib import Path

OK, FAIL, WARN = "✅", "❌", "⚠️ "


def show(status: str, name: str, detail: str = "") -> None:
    print(f"{status} {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    fix_groups = "--fix-groups" in sys.argv

    # 1. Settings / .env
    try:
        from app.config import get_settings
        settings = get_settings()
        assert settings.snow_instance_url and "devXXXXX" not in settings.snow_instance_url, \
            "SNOW_INSTANCE_URL still has the placeholder value"
        show(OK, "Config", f"instance={settings.snow_instance_url}, mode={settings.app_mode}")
    except Exception as e:
        show(FAIL, "Config", str(e))
        return 1

    # 2. ServiceNow OAuth
    from app.services.servicenow_client import ServiceNowClient
    snow = ServiceNowClient(settings)
    try:
        await snow._get_token()
        show(OK, "ServiceNow OAuth 2.0", f"grant_type={settings.snow_oauth_grant_type}")
    except Exception as e:
        show(FAIL, "ServiceNow OAuth 2.0", f"{e}\n   Check: Application Registry entry active? "
             "Client secret correct? For PDI use grant_type=password with admin credentials.")
        await snow.aclose()
        return 1

    # 3. Table API read
    try:
        incidents = await snow.list_incidents(limit=1)
        show(OK, "Table API read", f"fetched {len(incidents)} incident(s)")
    except Exception as e:
        show(FAIL, "Table API read", f"{e}\n   Check: user has itil/admin role?")
        await snow.aclose()
        return 1

    # 4. Assignment groups
    groups_file = Path(__file__).parent.parent / "data" / "assignment_groups.json"
    wanted = [g["name"] for g in json.loads(groups_file.read_text())]
    missing = [name for name in wanted if not await snow.resolve_group_sys_id(name)]
    if not missing:
        show(OK, "Assignment groups", f"all {len(wanted)} exist")
    elif fix_groups:
        for name in missing:
            desc = next(g["description"] for g in json.loads(groups_file.read_text()) if g["name"] == name)
            resp = await snow._http.post(
                "/api/now/table/sys_user_group",
                headers=await snow._headers(),
                json={"name": name, "description": desc},
            )
            resp.raise_for_status()
        show(OK, "Assignment groups", f"created {len(missing)} missing group(s): {', '.join(missing)}")
    else:
        show(WARN, "Assignment groups", f"missing: {', '.join(missing)} "
             "(rerun with --fix-groups to create them)")
    await snow.aclose()

    # 5 & 6. LLM: embeddings + function calling
    try:
        from app.services.llm import LLMClient
        llm = LLMClient(settings)
        vecs = await llm.embed(["preflight test"])
        show(OK, "Embeddings API", f"model={llm.embed_model}, dim={len(vecs[0])}")
    except Exception as e:
        show(FAIL, "Embeddings API", f"{e}\n   Check: deployment name matches Azure portal? "
             "Key/endpoint correct?")
        return 1
    try:
        args = await llm.chat_with_tool(
            messages=[{"role": "user", "content": "Reply by calling the tool with ok=true"}],
            tool={"type": "function", "function": {
                "name": "ping", "description": "health check",
                "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                               "required": ["ok"]}}},
        )
        show(OK, "Chat + function calling", f"model={llm.chat_model}, response={args}")
    except Exception as e:
        show(FAIL, "Chat + function calling", str(e))
        return 1

    # 7. Vector backend
    if settings.vector_backend == "azure_ai_search":
        try:
            from app.services.azure_search_store import AzureAISearchStore
            AzureAISearchStore(settings, llm)  # constructor ensures indexes exist
            show(OK, "Azure AI Search", f"endpoint={settings.azure_search_endpoint}")
        except Exception as e:
            show(FAIL, "Azure AI Search", f"{e}\n   Check: endpoint/key correct? "
                 "Search service running? admin key (not query key)?")
            return 1
    else:
        show(OK, "Vector backend", "chroma (local)")

    print("\n🚀 All systems go — run: uvicorn app.main:app  (APP_MODE=live)")
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
