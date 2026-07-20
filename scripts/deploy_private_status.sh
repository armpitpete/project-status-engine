#!/usr/bin/env bash
set -euo pipefail

: "${PRIVATE_STATUS_DEPLOY_HOST:?PRIVATE_STATUS_DEPLOY_HOST is required}"
: "${PRIVATE_STATUS_DEPLOY_USER:?PRIVATE_STATUS_DEPLOY_USER is required}"
: "${PRIVATE_STATUS_DEPLOY_TARGET:?PRIVATE_STATUS_DEPLOY_TARGET is required}"
: "${PRIVATE_STATUS_SSH_KEY_FILE:?PRIVATE_STATUS_SSH_KEY_FILE is required}"
: "${PRIVATE_STATUS_KNOWN_HOSTS_FILE:?PRIVATE_STATUS_KNOWN_HOSTS_FILE is required}"

EXPECTED_HOST="server.vaelinya.uk"
EXPECTED_USER="vaelinya"
EXPECTED_TARGET="/home/vaelinya/public_html/private/project-status-engine/"
SOURCE_DIR="${PRIVATE_STATUS_SOURCE_DIR:-private-build}"

if [[ "$PRIVATE_STATUS_DEPLOY_HOST" != "$EXPECTED_HOST" ]]; then
  echo "Refusing unexpected deployment host." >&2
  exit 1
fi
if [[ "$PRIVATE_STATUS_DEPLOY_USER" != "$EXPECTED_USER" ]]; then
  echo "Refusing unexpected deployment user." >&2
  exit 1
fi
if [[ "$PRIVATE_STATUS_DEPLOY_TARGET" != "$EXPECTED_TARGET" ]]; then
  echo "Refusing unexpected deployment target." >&2
  exit 1
fi
if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "Private build directory is missing." >&2
  exit 1
fi
for required in index.html status.json project-status.md completion-status.md authority-exceptions.md authority-resolution-templates.md; do
  if [[ ! -s "$SOURCE_DIR/$required" ]]; then
    echo "Private build is missing required file: $required" >&2
    exit 1
  fi
done
if [[ ! -s "$PRIVATE_STATUS_SSH_KEY_FILE" ]]; then
  echo "Dedicated SSH key file is missing or empty." >&2
  exit 1
fi
if [[ ! -s "$PRIVATE_STATUS_KNOWN_HOSTS_FILE" ]]; then
  echo "Pinned known-hosts file is missing or empty." >&2
  exit 1
fi

chmod 600 "$PRIVATE_STATUS_SSH_KEY_FILE" "$PRIVATE_STATUS_KNOWN_HOSTS_FILE"

SSH_OPTIONS=(
  -i "$PRIVATE_STATUS_SSH_KEY_FILE"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=$PRIVATE_STATUS_KNOWN_HOSTS_FILE"
  -o ConnectTimeout=20
)
REMOTE="$PRIVATE_STATUS_DEPLOY_USER@$PRIVATE_STATUS_DEPLOY_HOST"

ssh "${SSH_OPTIONS[@]}" "$REMOTE" \
  "mkdir -p -- '$PRIVATE_STATUS_DEPLOY_TARGET'"

printf -v RSYNC_RSH 'ssh -i %q -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=%q -o ConnectTimeout=20' \
  "$PRIVATE_STATUS_SSH_KEY_FILE" "$PRIVATE_STATUS_KNOWN_HOSTS_FILE"
export RSYNC_RSH

rsync \
  --archive \
  --compress \
  --delete \
  --checksum \
  --chmod=D755,F644 \
  "$SOURCE_DIR/" \
  "$REMOTE:$PRIVATE_STATUS_DEPLOY_TARGET"

ssh "${SSH_OPTIONS[@]}" "$REMOTE" \
  "test -s '${PRIVATE_STATUS_DEPLOY_TARGET}index.html' && test -s '${PRIVATE_STATUS_DEPLOY_TARGET}status.json' && grep -q '\"view\": \"private\"' '${PRIVATE_STATUS_DEPLOY_TARGET}status.json'"

echo "Private project-status dashboard deployed and verified on the pinned SSH target."
