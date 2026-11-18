# Privacy

A 3D scan of a hand is personal data. FreshCuff Fit is built so that **your scan never leaves your computer**.

## What happens to your scan

- The app is a set of static files: HTML, JavaScript, Python compiled to WebAssembly, and cuff geometry. Your browser downloads them from the site (GitHub Pages) or from the offline launcher on your own computer.
- When you choose a scan, the browser reads the file **from your disk into the page's memory**. All processing happens inside your browser tab.
- **Nothing is uploaded.** There is no server-side processing, no account, no database, no analytics, no tracking pixels and no cookies.
- The app loads all its code and data from the same site and makes **no requests to any other server**. You can check this yourself in your browser's developer tools (F12 → Network) while you run the app.
- When you close or reload the tab, the scan and everything computed from it are gone from memory. The browser may cache the app's own files (runtime and cuff geometry) for faster loading next time, but **not your scan**.
- The files you download (`.3mf`, `.stl`, report) are created in the page and saved by your browser, like any download.

## What the host sees

Like any website, the hosting service (GitHub Pages) can see the usual technical data of a page request, such as IP address, browser type and time, when your browser downloads the app's files. It does not see your scan or your results. See GitHub's privacy statement: <https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement>.

With the **offline launcher**, even that does not happen: the files are served from your own computer on `127.0.0.1`.

## The report file

The fit report contains measurements of the band of your hand: five 2D outlines across the 26 mm band (like what a tape measure would trace), the back-of-hand profile, the tape value you entered, the placement found, the checks, and hashes of the scan and of the output files. It does **not** contain the 3D surface of your hand. It contains the scan's file name, so rename the scan before running the app if the name identifies you.


## Sharing feedback

If you send feedback through GitHub issues, remember that **issues are public**. Share the report file if you like, **not your scan**, unless you deliberately choose to share it. The feedback form asks you to confirm this. Do not include names or health details of the person who will wear the cuff.

If you want a public report to be removed, comment on it or contact the maintainers through the repository, and it will be deleted.

## Command line

`fc_cli.py` runs on your own computer, reads the scan from disk and writes results to the folder you choose. It makes no network connections.

## Changes

If anything in this policy changes, for example if a future version offers an optional upload, the change will be described here and in the release notes **before** it ships. Any upload would be opt-in.
