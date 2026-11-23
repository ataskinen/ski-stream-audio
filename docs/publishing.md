# Publishing safely

Each installation generates its own random admin password on first startup. There is no shared production password in the source code. The fixed password in the automated tests is a test fixture only.

## Files that stay on the device

- `local/`: generated admin password and browser configuration.
- `config.json`: standalone CLI deployment settings.
- `.env` and `.env.*`: machine-specific environment settings.
- Private keys, `secrets/`, virtual environments, logs and recordings.

Git and Docker ignore rules exclude credentials and deployment settings. Keep these rules when copying the project. Never use `git add -f` to include local settings. Ignore rules do not remove files already committed.

The files under `config/` are examples with fictional network addresses. Replace them in a local configuration, not in the published examples. Documentation uses an example SSH username and hostname.

## Before the first GitHub upload

```sh
git status --short --untracked-files=all
git add .
git diff --cached --stat
git diff --cached
```

Review all staged files before committing. Do not include passwords, private keys, real deployment settings, recordings or screenshots containing credentials. Upload the Git repository, not a ZIP of the entire working directory: ignored files can still be included in a manually created ZIP.

See the repository’s `LICENSE` file for the license terms.

## Credentials and network access

Read your generated password locally with `cat local/admin-password`. Do not paste it into issues or documentation. To change it, stop the panel, replace the file contents with a new unique password of at least 12 characters, and restart the panel.

The panel uses HTTP Basic authentication without TLS, and audio UDP packets are not encrypted. Use a trusted local network; do not expose the panel or audio ports to the public internet. See [browser control](browser-control.md) for access guidance.
