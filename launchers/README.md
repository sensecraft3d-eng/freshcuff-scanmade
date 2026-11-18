# Offline launchers

These start FreshCuff Fit **on your own computer**, without internet, after you have downloaded the repository (**Code → Download ZIP** on GitHub, then unzip).

| System | Double-click |
|---|---|
| Windows | `FreshCuff-Fit-Windows.bat` |
| macOS | `FreshCuff-Fit-macOS.command` |
| Linux | `freshcuff-fit-linux.sh` (or run `bash launchers/freshcuff-fit-linux.sh` in a terminal) |

What happens:

1. The launcher looks for **Python 3.8 or newer**. Nothing is installed or downloaded.
2. It starts a small web server bound to `127.0.0.1`, so only your own computer can reach it. The server shows the `web/` folder at `http://127.0.0.1:8765/`. If that port is busy, it uses the next free one.
3. It opens that address in your default browser.
4. Keep the window open while you use the app. Close it (or press Ctrl+C) to stop.

The scan is processed by the page in your browser, exactly as on the online site. The local server only hands the page its own files.

**No Python?** Use the online version: <https://sensecraft3d-eng.github.io/freshcuff-fit/>. It is the same app, and it also keeps your scan on your computer. To install Python, go to <https://www.python.org/downloads/>. On Windows, tick "Add python.exe to PATH" during installation.

## Notes per system

- **Windows.** SmartScreen may warn about a downloaded `.bat` file. Choose *More info → Run anyway* only if you downloaded it from the official repository. If Python was installed from the Microsoft Store, it works too.
- **macOS.** The first time, Gatekeeper may refuse to open a downloaded `.command` file. Right-click it, choose *Open*, then *Open* again. If it says it is not executable, open Terminal and run `bash ` followed by the path of the file (you can drag the file into the Terminal window).
- **Linux.** If double-clicking opens a text editor, run it from a terminal, or mark it as executable (`chmod +x launchers/freshcuff-fit-linux.sh`).

## Advanced

All launchers call `start_local.py`:

```bash
python3 launchers/start_local.py --port 9000 --no-browser
```

When `tools/serve.py` is present, it is used: it sends the same security headers and file types as the hosting configuration in `web/_headers`. Otherwise the launcher falls back to Python's built-in static server.

These launchers never download or run anything from the internet.
