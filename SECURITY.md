# Security policy

FreshCuff ScanMade runs entirely in the browser (or on your own computer with the offline launcher and the CLI), so the main risks are:

- a malicious or malformed scan file causing the page or the CLI to misbehave;
- the page loading code or data from somewhere other than its own site;
- a generated cuff that passes the checks when it should not (a safety issue for the wearer).

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private reporting instead:

**[Report a vulnerability](https://github.com/sensecraft3d-eng/freshcuff-scanmade/security/advisories/new)** (Security tab → *Report a vulnerability*).

Include what you found, how to reproduce it, and which version (page footer, report file or commit). You can expect a first reply within about a week. This is a small, volunteer-maintained project.

If you find a case where **a cuff is accepted but should have been refused** (for example, it fails one of the manufacturing checks when measured independently), report it the same way if it could hurt a wearer. Otherwise use a normal [bug report](https://github.com/sensecraft3d-eng/freshcuff-scanmade/issues/new?template=bug.yml).

## Supported versions

Only the current version on the `main` branch (and the site built from it) is supported.

## Design notes

- No server, no upload, no accounts: there is no user data on any server to leak.
- All runtime files, including Pyodide and three.js, are served from the same site. Third-party CDNs are not used.
- `web/manifesto.json` lists SHA-256 hashes of the files the app loads into Python, and the app checks them before use.
- The offline launcher binds to `127.0.0.1` only and never downloads anything.
