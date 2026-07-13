import os

from dotenv import load_dotenv


def _load_aws_secrets() -> None:
    """Populate os.environ from an AWS Secrets Manager secret when configured.

    In production set AWS_SECRETS_MANAGER_SECRET_ID (and AWS_REGION) to the id/ARN of a
    secret whose value is a JSON object of ENV_KEY: value pairs; each pair is loaded into
    the environment. Values already present in the environment win, so nothing set by the
    orchestrator (or a local .env) is overwritten. No-op when the variable is unset, so
    local and test runs keep using plain environment variables.
    """
    secret_id = os.getenv("AWS_SECRETS_MANAGER_SECRET_ID")
    if not secret_id:
        return

    import json

    try:
        import boto3
    except ImportError as exc:  # boto3 is only needed when this feature is used
        raise RuntimeError(
            "AWS_SECRETS_MANAGER_SECRET_ID is set but boto3 is not installed. "
            "Install boto3 to load secrets from AWS Secrets Manager."
        ) from exc

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    client = boto3.client("secretsmanager", region_name=region)
    secret_string = client.get_secret_value(SecretId=secret_id).get("SecretString")
    if not secret_string:
        raise RuntimeError("AWS Secrets Manager secret has no SecretString value.")

    for key, value in json.loads(secret_string).items():
        os.environ.setdefault(key, str(value))


load_dotenv()
_load_aws_secrets()


def _require_env(name: str, default:str=None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


SECRET_KEY = _require_env("SECRET_KEY")
HASH_ALGORITHM = _require_env("HASH_ALGORITHM", "HS256")
# Send the auth cookie only over HTTPS. Enable in production (COOKIE_SECURE=true);
# keep off for local/plain-HTTP development.
COOKIE_SECURE = _require_env("COOKIE_SECURE", "false").lower() == "true"

# Note field encryption at rest (opt-in via the notes.encryption feature flag).
# NOTES_ENCRYPTION_KEY is base64 of 32 random bytes; required only when the flag is on.
# Rotate by moving the current key into NOTES_ENCRYPTION_KEYS_RETIRED (a JSON {id: key}
# map used for decryption) and setting a new key + bumped NOTES_ENCRYPTION_KEY_ID.
NOTES_ENCRYPTION_KEY = _require_env("NOTES_ENCRYPTION_KEY", "")
NOTES_ENCRYPTION_KEY_ID = _require_env("NOTES_ENCRYPTION_KEY_ID", "1")
NOTES_ENCRYPTION_KEYS_RETIRED = _require_env("NOTES_ENCRYPTION_KEYS_RETIRED", "")
POSTGRES_DB_URL = _require_env("POSTGRES_DB_URL")
MESSAGE_BROKER_URL = _require_env("MESSAGE_BROKER_URL")
CELERY_RESULT_BACKEND = _require_env("CELERY_RESULT_BACKEND")
INGESTION_TASK_STRING = _require_env("INGESTION_TASK_STRING")
INGESTION_QUEUE = _require_env("INGESTION_QUEUE", "ingestion")

# Shared secret for service-to-service calls from the notelite_agent.
AGENT_API_KEY = _require_env("AGENT_API_KEY")
AGENT_INTERNAL_URL = _require_env("AGENT_INTERNAL_URL", "http://localhost:3002")
AGENT_WORKFLOW_INTERNAL_URL = _require_env("AGENT_WORKFLOW_INTERNAL_URL", "http://agent-workflow:5453")
AGENT_WORKFLOW_API_KEY = _require_env("AGENT_WORKFLOW_API_KEY", AGENT_API_KEY)
AGENT_WORKFLOW_CONFIG_NAME = _require_env("AGENT_WORKFLOW_CONFIG_NAME", "notelite")
INGESTION_DEBOUNCE_SECONDS = int(_require_env("INGESTION_DEBOUNCE_SECONDS", "10"))
INGESTION_COALESCE_TTL_SECONDS = int(_require_env("INGESTION_COALESCE_TTL_SECONDS", "120"))

