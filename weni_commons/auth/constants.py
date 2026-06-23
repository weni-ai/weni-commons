CACHE_KEY_TEMPLATE = "auth:session-token:{hash}"

DYNAMODB_PARTITION_KEY = "token_hash"

MAX_REDIS_TTL_SECONDS = 86400

# Shared DynamoDB table for session tokens. The region is the same across
# environments; the table name differs per environment and must be set per
# branch (staging vs production) once the table is deployed. While the table
# is None the repository is a no-op and validation/generation fall back to
# Redis only. A service can still override these via Django settings
# (WENI_SESSION_TOKEN_DYNAMODB_TABLE / WENI_SESSION_TOKEN_DYNAMODB_REGION).
DEFAULT_DYNAMODB_TABLE = None
DEFAULT_DYNAMODB_REGION = "us-east-1"
