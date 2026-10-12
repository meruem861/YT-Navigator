# 📱 YT Navigator on Android

Everything runs on the phone:

- **Termux** runs the YT Navigator server (Django + SQLite) on `http://127.0.0.1:8000`.
- The **YT Navigator app** (a small WebView APK) starts that server through Termux and shows it full screen.
- Only the AI calls go to the internet: **Groq** (chat models) and **Cohere** (embeddings + reranking). No ML model runs on the phone.

Target device: Samsung Galaxy S21. Any Android 8+ phone with ~1.5 GB of free storage should work.

## 1. Get the API keys (free)

| Service | Used for | Where |
|---|---|---|
| Groq | Chat answers | https://console.groq.com/keys |
| Cohere | Semantic search (embeddings + rerank) | https://dashboard.cohere.com/api-keys |

Cohere trial keys are free but rate-limited, which is fine for personal use. Without a working Cohere key the search still works, using keywords only.

## 2. Install Termux

Install Termux from **F-Droid** (https://f-droid.org/packages/com.termux/) or its GitHub releases.
Do **not** use the Play Store version: it is outdated and cannot install packages.

Then, on the S21: *Settings → Apps → Termux → Battery → Unrestricted*, so Android doesn't kill the server in the background.

## 3. Install YT Navigator inside Termux

Open Termux and run:

```bash
pkg update -y && pkg install -y git
git clone -b claude/app-summary-b0454r https://github.com/meruem861/YT-Navigator
cd YT-Navigator
bash mobile/termux-setup.sh
```

If the repository is private, `git clone` asks for a username and password: use your GitHub username and a
[personal access token](https://github.com/settings/tokens) (with read access to the repository) as the password.

The script installs Python and the Rust toolchain, builds the Python packages, asks for your two API keys, creates the database and enables the link with the Android app.
**The first install compiles a few packages and takes 20–40 minutes.** Keep the screen on and Termux open.

Start the server at any time with:

```bash
ytnav
```

## 4. Install the YT Navigator app (APK)

The APK is built by GitHub Actions (`.github/workflows/android-apk.yml`):

1. On GitHub, open the repository → **Actions** → **Build Android APK** (if Actions are disabled on your fork, click *Enable* first; you can also start a build with *Run workflow*).
2. Open the latest successful run → **Artifacts** → download **yt-navigator-apk** (a zip).
3. Extract the zip with *My Files* and tap `yt-navigator.apk`. Allow *Install unknown apps* for your browser / My Files when asked.

Install Termux **before** the APK, otherwise Android can't grant the app its Termux permission (if that happens, uninstall and reinstall the APK).

On first launch, allow **"Run commands in Termux environment"**. From then on, tapping the YT Navigator icon starts the server automatically (it can take ~10 s) and opens the app.
YouTube links open in the YouTube app.

> No APK? Run `ytnav` in Termux, open `http://127.0.0.1:8000` in Chrome, then *⋮ → Add to Home screen*.

## Everyday use

| Task | How |
|---|---|
| Start | Tap the YT Navigator icon (or run `ytnav` in Termux) |
| Stop | In the Termux notification tap *Exit*, or `pkill -f uvicorn` |
| Update | `cd ~/YT-Navigator && git pull && .venv/bin/pip install -e .`, then restart |
| Change keys / models | Edit `~/YT-Navigator/.env` (`nano .env`), then restart |
| Your data | `~/YT-Navigator/data/` (`db.sqlite3` = channels, videos, transcripts; `checkpoints.sqlite3` = chat history) |

## Troubleshooting

- **"Server not running" in the app**: open Termux and run `ytnav` to see the error. If the app never manages to start it, check that `~/.termux/termux.properties` contains `allow-external-apps = true` and run `termux-reload-settings`.
- **A package fails to build during setup**: run `pkg upgrade -y` and then `bash mobile/termux-setup.sh` again; already-built packages are reused.
- **Scanning finds 0 transcripts**: YouTube sometimes blocks transcript requests. Try again later or on another network (Wi-Fi vs mobile data).
- **Chat says a model was not found**: Groq retires models from time to time. Set `INSTANT_LLM` / `POWERFUL_LLM` in `.env` to models listed on https://console.groq.com/docs/models.
- **Search results look wrong after changing `EMBEDDING_MODEL`**: delete the videos and scan them again, so all embeddings come from the same model.
