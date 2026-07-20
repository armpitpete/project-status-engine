# Project Status Engine Operations

## Normal operation

The status workflow generates public, private and internal views from one repository scan. Public Pages receives only `public/`; the private dashboard is deployed only to the pinned Oracle target; the internal dataset remains runner-local.

## Disable private deployment safely

Set the repository Actions variable `PRIVATE_STATUS_DEPLOY_ENABLED` to a value other than `true`, or remove it. Public generation and Pages deployment continue. Do not delete deployment secrets as an emergency first step unless credential compromise is suspected.

## Rotate the deployment key

1. Generate a new dedicated unencrypted Ed25519 key outside GitHub Actions.
2. Install only the new public key for the `vaelinya` deployment account with the existing forwarding, PTY and user-RC restrictions.
3. Verify the new public-key fingerprint through the trusted server console.
4. Replace `PRIVATE_STATUS_DEPLOY_KEY` with the new private key.
5. Run the workflow manually on `main` and verify private deployment plus anonymous blocking.
6. Remove the old public key only after the new key has passed live proof.

Never reuse a personal interactive key and never paste private-key material into issues, logs or chat.

## Respond to an SSH host-key change

A changed host key is a stop condition.

1. Disable private deployment.
2. Verify whether the host was rebuilt or its SSH configuration legitimately changed through the provider console and a second trusted administrative channel.
3. Compare the new Ed25519 fingerprint independently.
4. Replace `PRIVATE_STATUS_KNOWN_HOSTS` only after verification.
5. Run a manual deployment and re-enable the normal schedule.

Do not use `StrictHostKeyChecking=no`, `ssh-keyscan` as trust authority, or automatic replacement.

## Recover a damaged remote directory

The deployment command mirrors `private-build/` with deletion enabled. After confirming the target path is exactly `/home/vaelinya/public_html/private/project-status-engine/`, run the workflow manually on `main`. The next successful deployment restores the complete generated directory. Do not broaden the deployment account's filesystem permissions.

## Token expiry or access loss

Symptoms include partial discovery, API 401/403 responses or a scan-health failure.

- verify `PROJECT_STATUS_TOKEN` can read all intended owner repositories;
- verify `README_SYNC_TOKEN` has Contents and Pull requests read/write access for synchronised repositories;
- rotate only the affected token;
- run validation before allowing cross-repository writes;
- never treat a partial inventory as a successful owner-wide result.

## Cloudflare Access policy changes

After any Access change:

1. confirm an unauthenticated request is rejected or redirected away from the protected origin;
2. confirm the authenticated owner URL loads current data;
3. run the status workflow and require `Verify anonymous access remains blocked` to pass.

Disable private deployment if anonymous access becomes possible.

## Public privacy incident

1. Disable Pages deployment by stopping the workflow or disabling Pages.
2. Preserve the failing artifact and workflow logs privately.
3. Identify whether identity, URL, issue, PR, commit, authority, completion or exception data crossed the public boundary.
4. repair the redaction or validation rule;
5. add a deterministic regression test;
6. regenerate and inspect every public file before restoring Pages.

Never solve a leak by hiding only the HTML while leaving JSON or Markdown exposed.

## Acceptance checklist

- deterministic tests pass;
- generated-output validation passes;
- public output contains no private identity or authority material;
- the private deployment uses the dedicated key and pinned host key;
- remote files match the generated private build;
- anonymous access remains blocked;
- authenticated owner review confirms the landing page and detailed reports.
