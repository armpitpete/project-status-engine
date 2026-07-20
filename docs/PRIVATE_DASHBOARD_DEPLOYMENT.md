# Private Dashboard Deployment

## Target

The owner-only dashboard is generated into `private-build/` and deployed to:

```text
SSH host: server.vaelinya.uk
SSH user: vaelinya
Remote directory: /home/vaelinya/public_html/private/project-status-engine/
Owner URL: https://command.vaelinya.uk/private/project-status-engine/
```

The URL must remain protected by Cloudflare Access. The workflow verifies that an anonymous request is rejected or redirected away from the protected application origin.

## Required GitHub configuration

Repository Actions secrets:

- `PRIVATE_STATUS_DEPLOY_KEY` — dedicated unencrypted Ed25519 key for this deployment only;
- `PRIVATE_STATUS_KNOWN_HOSTS` — independently verified pinned known-hosts entry.

Repository Actions variable:

```text
PRIVATE_STATUS_DEPLOY_ENABLED=true
```

When the variable is absent or not exactly `true`, private deployment is skipped while public generation continues.

## Provisioning boundary

Use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_private_deploy_credentials.ps1
```

The script creates a dedicated key under `$HOME\.project-status-engine-private-deploy`, refuses accidental replacement, prints only public fingerprint and paths, and never prints private-key contents.

Install only the generated public key through a trusted server session:

```bash
sudo bash scripts/provision_private_dashboard_target.sh /path/to/project-status-engine-private-deploy-ed25519.pub
```

Provisioning fails closed unless:

- it runs through root or `sudo`;
- account `vaelinya` exists with home `/home/vaelinya`;
- `/home/vaelinya/public_html/private` already exists;
- the supplied file contains exactly one Ed25519 public key.

The candidate host-key line printed by the script is not authority by itself. Verify the Ed25519 fingerprint through an independent trusted channel before storing it.

## Credential and permission controls

- generate the key outside GitHub Actions;
- never reuse a personal interactive key;
- never configure an SSH password in the workflow;
- retain forwarding, PTY and user-RC restrictions on the authorised key;
- grant write/delete access only inside the exact dashboard target;
- retain strict host-key checking and the pinned workflow known-hosts file.

The workflow refuses a host, user or target path that differs from the committed values.

## Deployment behaviour

Deployment runs only for non-pull-request events and only when private deployment is enabled.

The workflow:

1. generates public, private and internal outputs from one scan;
2. validates output schemas and public/private separation;
3. creates temporary runner credential files with restrictive permissions;
4. validates the exact host, user and target;
5. mirrors `private-build/` with `rsync --delete --checksum`;
6. verifies deployed `index.html` and `status.json`;
7. verifies anonymous access remains blocked;
8. uploads only `public/` to Pages.

`private-build/` is never uploaded as a Pages or general Actions artifact.

## Required private files

Deployment fails closed unless the generated owner package contains its required reports. The generated-output validator additionally requires these five non-empty HTML routes:

- `index.html`
- `projects.html`
- `completion.html`
- `exceptions.html`
- `operations.html`

It also requires:

- `status.json`
- `project-status.md`
- `completion-status.md`
- `authority-exceptions.md`
- `authority-resolution-templates.md`
- `home-pc-tasks.md`

## Operational acceptance

1. enable private deployment;
2. run `Generate project status` on `main`;
3. require credential preparation, deployment and anonymous-access verification to pass;
4. inspect the authenticated overview and all four secondary routes;
5. confirm **Do Next** uses only the top five;
6. confirm detailed completion and exceptions are absent from the overview but present on their dedicated pages;
7. confirm the public Pages output contains no private identity or exception material.

Do not declare authenticated private delivery complete until this live proof has passed. Rotation, incident and recovery procedures are in `docs/OPERATIONS.md`.
