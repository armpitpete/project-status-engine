#!/usr/bin/env bash
set -euo pipefail

EXPECTED_HOST="server.vaelinya.uk"
EXPECTED_USER="vaelinya"
EXPECTED_HOME="/home/vaelinya"
TARGET_PARENT="/home/vaelinya/public_html/private"
TARGET_DIRECTORY="${TARGET_PARENT}/project-status-engine"
AUTHORIZED_OPTIONS="no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc,no-X11-forwarding"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

if [[ $# -ne 1 ]]; then
  fail "usage: sudo bash scripts/provision_private_dashboard_target.sh /path/to/deployment-key.pub"
fi

if [[ ${EUID} -ne 0 ]]; then
  fail "run this script as root through sudo"
fi

PUBLIC_KEY_FILE=$1
[[ -f "$PUBLIC_KEY_FILE" ]] || fail "public key file does not exist: $PUBLIC_KEY_FILE"

id "$EXPECTED_USER" >/dev/null 2>&1 || fail "required account does not exist: $EXPECTED_USER"
USER_HOME=$(getent passwd "$EXPECTED_USER" | cut -d: -f6)
[[ "$USER_HOME" == "$EXPECTED_HOME" ]] || fail "unexpected home for $EXPECTED_USER: $USER_HOME"
USER_GROUP=$(id -gn "$EXPECTED_USER")

[[ -d "$TARGET_PARENT" ]] || fail "target parent does not exist: $TARGET_PARENT"

mapfile -t KEY_LINES < <(sed -e 's/\r$//' -e '/^[[:space:]]*$/d' "$PUBLIC_KEY_FILE")
[[ ${#KEY_LINES[@]} -eq 1 ]] || fail "public key file must contain exactly one non-empty line"
PUBLIC_KEY=${KEY_LINES[0]}

if [[ ! "$PUBLIC_KEY" =~ ^ssh-ed25519[[:space:]]+[A-Za-z0-9+/=]+([[:space:]].*)?$ ]]; then
  fail "public key must be one OpenSSH Ed25519 public key"
fi

read -r KEY_TYPE KEY_DATA _ <<<"$PUBLIC_KEY"
[[ "$KEY_TYPE" == "ssh-ed25519" ]] || fail "unexpected key type: $KEY_TYPE"
[[ -n "$KEY_DATA" ]] || fail "public key data is empty"

install -d -o "$EXPECTED_USER" -g "$USER_GROUP" -m 0700 "$EXPECTED_HOME/.ssh"
touch "$EXPECTED_HOME/.ssh/authorized_keys"
chown "$EXPECTED_USER:$USER_GROUP" "$EXPECTED_HOME/.ssh/authorized_keys"
chmod 0600 "$EXPECTED_HOME/.ssh/authorized_keys"

if ! awk -v key="$KEY_DATA" '{ for (i = 1; i <= NF; i++) if ($i == key) found = 1 } END { exit(found ? 0 : 1) }' \
  "$EXPECTED_HOME/.ssh/authorized_keys"; then
  printf '%s %s\n' "$AUTHORIZED_OPTIONS" "$PUBLIC_KEY" >> "$EXPECTED_HOME/.ssh/authorized_keys"
fi

install -d -o "$EXPECTED_USER" -g "$USER_GROUP" -m 0750 "$TARGET_DIRECTORY"
runuser -u "$EXPECTED_USER" -- test -w "$TARGET_DIRECTORY" \
  || fail "$EXPECTED_USER cannot write the deployment target"
runuser -u "$EXPECTED_USER" -- test -x "$TARGET_DIRECTORY" \
  || fail "$EXPECTED_USER cannot traverse the deployment target"

printf 'Provisioned deployment account and exact target.\n'
printf 'SSH host: %s\n' "$EXPECTED_HOST"
printf 'SSH user: %s\n' "$EXPECTED_USER"
printf 'Target:   %s\n' "$TARGET_DIRECTORY"
printf 'Key:      '
ssh-keygen -lf "$PUBLIC_KEY_FILE"

printf '\nTrusted-console SSH host fingerprints:\n'
found_host_key=0
for host_key in /etc/ssh/ssh_host_*_key.pub; do
  [[ -f "$host_key" ]] || continue
  found_host_key=1
  ssh-keygen -lf "$host_key"
done
[[ $found_host_key -eq 1 ]] || fail "no SSH host public keys were found under /etc/ssh"

ED25519_HOST_KEY="/etc/ssh/ssh_host_ed25519_key.pub"
if [[ -f "$ED25519_HOST_KEY" ]]; then
  printf '\nCandidate PRIVATE_STATUS_KNOWN_HOSTS line:\n'
  awk -v host="$EXPECTED_HOST" '{ print host " " $1 " " $2 }' "$ED25519_HOST_KEY"
  printf '\nVerify the printed Ed25519 host fingerprint through an independent trusted channel before saving this line as a GitHub Actions secret.\n'
else
  printf '\nNo Ed25519 SSH host key exists. Select and independently verify one printed host key before constructing PRIVATE_STATUS_KNOWN_HOSTS.\n'
fi
