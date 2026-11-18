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
- `web/manifesto.json` lists SHA-256 hashes for these classes of files: the Pyodide loader, WebAssembly binary, standard library and lock file, every Python wheel, the app's Python files, the cuff data, the width variants and the sample scan. It does **not** cover the page's own HTML, JavaScript (including `worker.js`), CSS or the three.js viewer modules; those are protected only by being served from the same site. The worker fetches the manifest from the same site, checks each file against it **before** running or loading it (the Pyodide scripts run from the verified bytes), and refuses any Pyodide runtime file the manifest does not list. The sample scan is refused if its hash cannot be checked. The manifest itself is the root of trust: it protects against corrupted or partially updated files and caches, not against someone who can change the whole site.
- Hosting and headers: GitHub Pages cannot send custom HTTP headers, so on the public site the content-security policy is a `<meta>` tag in `index.html`. It covers the page, not the background worker, and it cannot set `frame-ancestors`. The integrity checks above do not depend on headers. `web/_headers` is used by the offline launcher and by hosts that support that file (for example Cloudflare Pages), where the full policy is sent as headers.
- The offline launcher binds to `127.0.0.1` only and never downloads anything.
