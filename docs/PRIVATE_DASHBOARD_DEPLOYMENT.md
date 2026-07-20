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

## Bounded provisioning path

The repository includes two operator scripts. They prepare the required credential and server target but do not modify GitHub secrets, enable deployment or assert that a host key is trusted.

### 1. Create the dedicated key on Windows

From a trusted local checkout in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_private_deploy_credentials.ps1
```

The script:

- requires the Windows OpenSSH `ssh-keygen` command;
- creates a dedicated Ed25519 key under `$HOME\.project-status-engine-private-deploy`;
- refuses to overwrite an existing credential unless `-Force` is explicitly supplied;
- prints the public-key fingerprint and file locations;
- does not print the private-key contents;
- writes a local provisioning manifest containing the remaining steps.

Use the generated `.pub` file on the server. Store the complete private-key file as `PRIVATE_STATUS_DEPLOY_KEY`. Do not commit either generated key.

### 2. Provision the exact server target

Copy only the public key and `scripts/provision_private_dashboard_target.sh` to a trusted administrative session on the server. Then run:

```bash
sudo bash scripts/provision_private_dashboard_target.sh /path/to/project-status-engine-private-deploy-ed25519.pub
```

The script fails closed unless:

- it is run through root or `sudo`;
- the `vaelinya` account exists with home `/home/vaelinya`;
- `/home/vaelinya/public_html/private` already exists;
- the supplied file contains exactly one Ed25519 public key.

It installs the key with forwarding, PTY and user-RC restrictions, creates only the exact project target, verifies that `vaelinya` can write it, prints trusted-console host-key fingerprints and emits a candidate Ed25519 known-hosts line.

The candidate line is not authority by itself. Compare its fingerprint through an independent trusted channel before storing it as `PRIVATE_STATUS_KNOWN_HOSTS`.

## Server preparation boundary

Generate the dedicated key pair outside GitHub Actions. Install only the public key in the `vaelinya` account's `authorized_keys`. Do not reuse a personal interactive key and do not configure an SSH password in the workflow.

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

After provisioning the server and creating both secrets:

1. create repository Actions variable `PRIVATE_STATUS_DEPLOY_ENABLED=true`;
2. run `Generate project status` manually on `main` or allow the next scheduled run;
3. verify that the credential preparation, private deployment and anonymous-access verification steps pass.

Acceptance requires:

- the exact remote directory contains the current private build;
- the authenticated URL shows real repository identities, the private top five, private `Do Next`, the owner-wide exception queue and resolution templates;
- an unauthenticated request remains blocked by Cloudflare Access;
- the public Pages artifact contains no private repository identity or authority-exception material.

Do not declare authenticated private delivery complete until this live proof has passed.
