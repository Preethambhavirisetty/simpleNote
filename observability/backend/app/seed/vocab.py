"""Domain vocabulary for the demo data: an IT-ops / infrastructure agent."""

PLAYBOOKS = [
    ("incident_triage", "why is {svc} throwing {code}s"),
    ("deploy_rollback", "roll back the {svc} deploy"),
    ("capacity_check", "is {svc} going to run out of headroom this week"),
    ("cert_expiry_audit", "which certs on {svc} expire soon"),
    ("log_search", "show me recent errors from {svc}"),
]

SERVICES = [
    "checkout-api", "payments-worker", "auth-gateway", "search-indexer",
    "notify-dispatch", "cart-service", "ledger-api", "media-resizer",
]
CODES = ["503", "502", "429", "500"]
NAMESPACES = ["prod", "staging", "prod-eu", "prod-us"]

RESOURCES = [
    "k8s.pod", "k8s.deployment", "aws.ec2_instance",
    "datadog.monitor", "pagerduty.incident", "vault.certificate",
]

# (operation, resource, mutating, tool used to carry it out)
OPERATIONS = [
    ("k8s.describe_pod", "k8s.pod", False, "k8s.describe_pod"),
    ("k8s.get_logs", "k8s.pod", False, "k8s.get_logs"),
    ("k8s.rollout_undo", "k8s.deployment", True, "k8s.rollout_undo"),
    ("k8s.scale_deployment", "k8s.deployment", True, "k8s.scale"),
    ("datadog.query_metrics", "datadog.monitor", False, "datadog.query"),
    ("aws.describe_instance", "aws.ec2_instance", False, "aws.describe"),
    ("aws.terminate_instance", "aws.ec2_instance", True, "aws.terminate"),
    ("pagerduty.ack_incident", "pagerduty.incident", True, "pagerduty.ack"),
    ("vault.list_certs", "vault.certificate", False, "vault.list"),
]

MODELS = ["sample-model", "sample-model", "sample-model"]

# Chatter that makes a stream feel like a real one: mundane lines you would
# actually write, which is the point -- most logs are not milestones.
DEBUG_CHATTER = [
    "loaded {n} catalog entries from cache",
    "cache {hit} for key {key}",
    "normalising arguments",
    "context window at {n}% capacity",
    "skipping disabled tool {tool}",
    "retry budget remaining: {n}",
    "resolved namespace to {ns}",
    "trimmed {n} messages from history",
    "embedding lookup returned {n} neighbours",
    "guardrail check passed",
    "serialising state snapshot ({n} keys)",
    "acquired lease on {svc}",
]

FINAL_ANSWERS = {
    "incident_triage": (
        "{svc} in {ns} is returning {code}s because 2 of 5 pods were OOMKilled "
        "after the memory limit dropped in the last deploy. I have raised the "
        "limit back to 1Gi; error rate is falling."
    ),
    "deploy_rollback": (
        "Rolled {svc} in {ns} back to the previous revision. All 5 pods are "
        "healthy and the 5xx rate is back to baseline."
    ),
    "capacity_check": (
        "{svc} is at 71% of its CPU request at peak and trending up ~3%/week, "
        "so it has roughly four weeks of headroom. I would bump replicas before "
        "the end of the month."
    ),
    "cert_expiry_audit": (
        "Two certificates on {svc} expire within 30 days: the ingress cert "
        "(11 days) and the internal mTLS cert (26 days). Neither is on auto-renew."
    ),
    "log_search": (
        "Over the last hour {svc} logged 143 errors, almost all "
        "'upstream connect timeout' against the ledger-api dependency."
    ),
}
