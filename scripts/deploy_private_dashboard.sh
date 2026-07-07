#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${PRIVATE_STATUS_OUT_DIR:-private-build}"
SSH_HOST="${ORACLE_SSH_HOST:-server.vaelinya.uk}"
SSH_USER="${ORACLE_SSH_USER:-vaelinya}"
TARGET_DIR="${ORACLE_PRIVATE_DASHBOARD_PATH:-/home/vaelinya/public_html/private/project-status-engine/}"

if [[ ! -f "${SOURCE_DIR}/index.html" || ! -f "${SOURCE_DIR}/status.json" ]]; then
  echo "Private dashboard build is incomplete: ${SOURCE_DIR}" >&2
  exit 1
fi

rsync \
  -az \
  --delete \
  --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
  -e "ssh -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
  "${SOURCE_DIR}/" \
  "${SSH_USER}@${SSH_HOST}:${TARGET_DIR}"

echo "Private dashboard deployed to ${SSH_HOST}:${TARGET_DIR}"
