/**
 * ServiceNow Business Rule — makes the pipeline zero-touch.
 *
 * Setup in your PDI:
 *   System Definition > Business Rules > New
 *   Table: incident | When: async | Insert: true
 *   Condition: assignment group is empty (so manual routing is never overridden)
 *
 * Also create: System Web Services > Outbound > REST Message
 *   Name: Incident Copilot Webhook
 *   Endpoint: https://<your-tunnel-or-host>/webhook/incident
 *   HTTP Method: POST, Header: x-webhook-secret = <your secret>
 *
 * Tip for local dev: expose FastAPI with `ngrok http 8000`.
 */
(function executeRule(current /*, previous*/) {
    try {
        var r = new sn_ws.RESTMessageV2('Incident Copilot Webhook', 'Default POST');
        r.setRequestHeader('Content-Type', 'application/json');
        r.setRequestBody(JSON.stringify({
            sys_id: current.sys_id.toString(),
            number: current.number.toString(),
            short_description: current.short_description.toString(),
            description: current.description.toString(),
            caller_id: current.caller_id.getDisplayValue()
        }));
        var response = r.executeAsync(); // async — never block the insert
        gs.info('Incident Copilot webhook fired for ' + current.number);
    } catch (ex) {
        gs.error('Incident Copilot webhook failed: ' + ex.message);
    }
})(current);
