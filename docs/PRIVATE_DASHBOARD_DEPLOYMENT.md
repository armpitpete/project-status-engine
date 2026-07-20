# Private Dashboard Deployment

## Target

The owner-only dashboard is generated into `private-build/` and deployed to:

```text
SSH host: server.vaelinya.uk
SSH user: vaelinya
Remote directory: /home/vaelinya/public_html/private/project-status-engine/
Owner URL: https://command.vaelinya.uk/private/project-status-engine/
```

The URL must remain protected by the existing Cloudflare Access policy. The deployment workflow verifies that an anonymous request is rejected or redirected away from the protected application origin.

## Required GitHub configuration

Create these repository Actions secrets:

- `PRIVATE_STATUS_DEPLOY_KEY` — a dedicated unencrypted Ed25519 private key used only for this deployment;
- `PRIVATE_STATUS_KNOWN_HOSTS` — the pinned known-hosts entry for `server.vaelinya.uk`, obtained and verified through a trusted administrative channel.

Create this repository Actions variable only after the server key, target permissions and secrets are ready:

```text
PRIVATE_STATUS_DEPLOY_ENABLED=true
```

When the variable is absent or not exactly `true`, private deployment is skipped. Public generation and GitHub Pages deployment continue normally.

## Server preparation

Generate a dedicated key pair outside GitHub Actions. Install only the public key in the `vaelinya` account's `authorized_keys`. Do not reuse a personal interactive key and do not configure an SSH password in the workflow.

The `vaelinya` account must be able to:

- create and write `/home/vaelinya/public_html/private/project-status-engine/`;
- delete obsolete files inside that exact directory during synchronisation;
- read back the deployed `index.html` and `status.json` for post-deploy validation.

Do not grant broader privileges than required. The workflow refuses any host, user or target path that differs from the committed values.

## Host-key pinning

`PRIVATE_STATUS_KNOWN_HOSTS` is consumed as the only workflow known-hosts file. SSH runs with:

```text
StrictHostKeyChecking=yes
UserKnownHostsFile=<pinned workflow file>
BatchMode=yes
IdentitiesOnly=yes
```

Do not generate and trust a fresh host key inside the deployment job. Verify the server fingerprint independently before saving the known-hosts entry.

## Deployment behaviour

Deployment runs only for non-pull-request workflow events and only when `PRIVATE_STATUS_DEPLOY_ENABLED` is `true`.

The workflow:

1. builds public, private and trusted internal outputs from one scan;
2. validates public/private separation;
3. writes the dedicated key and pinned known-hosts entry into the runner's temporary directory;
4. validates the exact SSH host, user and target;
5. uses `rsync --delete --checksum` so the remote directory exactly mirrors `private-build/`;
6. checks that the deployed private `index.html` and `status.json` are non-empty and that the JSON identifies the private view;
7. checks that anonymous web access remains blocked;
8. uploads only `public/` to GitHub Pages.

`private-build/` is never uploaded as a Pages artifact or general Actions artifact.

## Required private files

Deployment fails closed unless these generated files exist and are non-empty:

- `index.html`;
- `status.json`;
- `project-status.md`;
- `completion-status.md`;
- `authority-exceptions.md`;
- `authority-resolution-templates.md`.

## Operational acceptance

After enabling deployment, run `Generate project status` manually or allow the next scheduled/main run. Acceptance requires:

- the deployment steps pass;
- the exact remote directory contains the current private build;
- the authenticated URL shows real repository identities, the private top five, private `Do Next`, the owner-wide exception queue and resolution templates;
- an unauthenticated request remains blocked by Cloudflare Access;
- the public Pages artifact contains no private repository identity or authority-exception material.

Do not declare authenticated private delivery complete until this live proof has passed.
