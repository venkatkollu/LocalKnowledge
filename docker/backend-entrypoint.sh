#!/bin/sh
set -eu

SECRETS_DIR="${KNOWLEDGEOS_SECRETS_DIR:-/data/secrets}"

# Support Docker/Kubernetes secret files without putting secrets in the
# environment. Explicit environment variables take precedence over files.
read_secret_file() {
    variable="$1"
    file_variable="${variable}_FILE"
    eval "file_path=\${${file_variable}:-}"
    if [ -n "$file_path" ] && [ -s "$file_path" ]; then
        eval "secret_value=\$(cat \"\$file_path\")"
        export "$variable=$secret_value"
    fi
}

read_secret_file KNOWLEDGEOS_AUTH_SECRET
read_secret_file KNOWLEDGEOS_ENCRYPTION_KEY
read_secret_file KNOWLEDGEOS_EMBEDDING_API_KEY

if [ -z "${KNOWLEDGEOS_AUTH_SECRET:-}" ] || [ -z "${KNOWLEDGEOS_ENCRYPTION_KEY:-}" ]; then
    mkdir -p "$SECRETS_DIR"
    chmod 700 "$SECRETS_DIR"
fi

if [ -z "${KNOWLEDGEOS_AUTH_SECRET:-}" ]; then
    if [ ! -s "$SECRETS_DIR/auth_secret" ]; then
        python -c "import secrets; print(secrets.token_hex(32))" > "$SECRETS_DIR/auth_secret"
        chmod 600 "$SECRETS_DIR/auth_secret"
        echo "Generated persistent auth secret in $SECRETS_DIR/auth_secret" >&2
    fi
    KNOWLEDGEOS_AUTH_SECRET="$(cat "$SECRETS_DIR/auth_secret")"
    export KNOWLEDGEOS_AUTH_SECRET
fi

if [ -z "${KNOWLEDGEOS_ENCRYPTION_KEY:-}" ]; then
    if [ ! -s "$SECRETS_DIR/encryption_key" ]; then
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > "$SECRETS_DIR/encryption_key"
        chmod 600 "$SECRETS_DIR/encryption_key"
        echo "Generated persistent provider-key encryption key in $SECRETS_DIR/encryption_key" >&2
    fi
    KNOWLEDGEOS_ENCRYPTION_KEY="$(cat "$SECRETS_DIR/encryption_key")"
    export KNOWLEDGEOS_ENCRYPTION_KEY
fi

exec "$@"
