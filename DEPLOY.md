# DEPLOY.md: from zero to a live HTTPS URL

> Time budget: about 45 minutes, most of it waiting for the first Docker build.
> **Microphones only work on HTTPS.** DigitalOcean App Platform gives you HTTPS automatically. The Droplet path adds it with Caddy.

## Step 0: Get your keys (10 min, do this first, in parallel)

| What | Where | Needed? |
|---|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey → *Create API key* | **Yes** (this is Gemma 4) |
| `GROQ_API_KEY` | https://console.groq.com/keys → *Create API Key* | Strongly recommended (hosted Whisper large-v3). Without it you must build with `INSTALL_LOCAL_STT=1` and use a 4 GB+ server |
| DigitalOcean account | https://cloud.digitalocean.com | Yes for the DO route |
| **MLH $25 DigitalOcean credit** | your *My Hacktoberfest* promos page | **Expires 31 Oct 2026**; claim it now, and read its terms |

Never paste keys into code, chat or GitHub. They go only in `.env` (local) and the host's "environment variables" screen.

## Step 1: Run it on your laptop (10 min)

```bash
cd team-j
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # Windows: copy .env.example .env
# open .env in an editor and fill in GEMINI_API_KEY and GROQ_API_KEY
python app.py
```

Open http://localhost:5000 (the mic works on `localhost`). Check `http://localhost:5000/health`: `keys_present` should show both `true`.
The first spoken reply is slow (it downloads the voice model); later ones are fast.

Then, in a second terminal, run the **real-model self-test**: the voice model speaks, Whisper listens, and the results are compared:

```bash
python tests/roundtrip.py
```

You want `ALL PASS`. Screenshot it for your presentation. If `transcribe[...]` fails on similarity only, that's usually the flat TTS voice; try again before worrying.

## Step 2: Put the code on GitHub (5 min)

The prize rules need a **public repo with a license** (the MIT `LICENSE` file is already included).

```bash
git clone <ORGANIZER-REPO-URL> team-j-repo && cd team-j-repo   # the starter repo from the event
git checkout -b team-j-solution
# delete the old starter files, then copy everything from this project in:
rm -f script.js package.json
cp -r ../team-j/. .                                            # includes .gitignore; make sure .env is NOT there
git status                                                     # .env must NOT be listed. If it is, stop.
git add -A && git commit -m "Bolo: multilingual voice assistant (Whisper + Gemma 4 + MMS-TTS)"
git push -u origin team-j-solution
```

⚠️ If the organizer's repo is private, or you can't make it public, also create **your own public repo** (GitHub → New → Public) and push the same code there. The Best Open-Source AI Project judges must be able to open it. Use that URL on the submission form and keep the organizer PR as well.

## Step 3A (recommended): DigitalOcean App Platform (20 to 30 min, HTTPS included)

1. DigitalOcean → **Create → App Platform**.
2. Source: **GitHub** → authorize → pick your public repo and the `team-j-solution` branch (turn **Autodeploy** on).
3. It should detect the `Dockerfile`. If it shows "Resource Type: Web Service", good.
4. **Edit the plan:** choose an instance with **at least 2 GB RAM** (1 vCPU / 2 GB). A 512 MB or 1 GB instance will crash when the voice models load. Check the current price on the screen. The MLH credit should cover a couple of days.
5. **HTTP port: `8080`.**  Health check path: `/health`.
6. **Environment variables** (mark keys as *Encrypt/Secret*):

   | Key | Value |
   |---|---|
   | `GEMINI_API_KEY` | your key (secret) |
   | `GROQ_API_KEY` | your key (secret) |
   | `STT_BACKEND` | `groq` |
   | `GEMMA_MODEL` | `gemma-4-26b-a4b-it` |
   | `TTS_PRELOAD` | `hi,bn` |
   | `DEFAULT_CITY` | `Haldia` |

7. **Create Resources** and wait. The first build takes **10 to 15 minutes** (PyTorch + baking the voice models into the image). Watch the *Build logs*; "WARNING: could not prefetch MMS voices" is not fatal (they download on first use).
8. When it says *Live*, copy the URL (`https://…ondigitalocean.app`).

## Step 3B (alternative): a DigitalOcean Droplet with automatic HTTPS

Use this if App Platform's build fails or you want more control.

1. **Create → Droplets** → Ubuntu 24.04 → **Basic, 2 GB RAM or more** → add your SSH key → Create. Note its public IP, e.g. `203.0.113.10`.
2. SSH in: `ssh root@203.0.113.10`, then:

```bash
apt-get update && apt-get install -y docker.io docker-compose-v2 git
# small servers build more reliably with swap:
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile

git clone <YOUR-PUBLIC-REPO-URL> app && cd app && git checkout team-j-solution
cp .env.example .env
nano .env        # fill in GEMINI_API_KEY, GROQ_API_KEY; also add this line (dashes, not dots):
                 # DOMAIN=203-0-113-10.sslip.io
docker compose up -d --build
docker compose logs -f           # Ctrl+C to leave; wait for "Listening at"
```

`203-0-113-10.sslip.io` is a free name that points at that IP, so Caddy can get a real HTTPS certificate with no domain purchase. Open `https://203-0-113-10.sslip.io`.
Set `STT_BACKEND=groq` in `.env` too. To update later: `git pull && docker compose up -d --build`.

## Step 3C (last-resort fallback): Hugging Face Spaces

Create a Space → **Docker** SDK → push this repo's files into it (keep the `README.md` front-matter the Space generates, and add `app_port: 8080` to it). Add the keys under *Settings → Variables and secrets*. Free tier has 16 GB RAM, which is plenty. This is a fallback only; the DigitalOcean route is the one that fits the sponsor prize.

## Step 4: Verify the live site (5 min)

```bash
curl https://<LIVE-URL>/health                      # status "ok", keys_present both true
python tests/roundtrip.py https://<LIVE-URL>        # real models, live server: want ALL PASS
```

Then, **on a phone**, open the URL: tap the mic, say something in Hindi, then Bengali. Attach a photo and ask about it. Turn on airplane mode and send a message to see the offline fallback.

Put the live URL at the top of `README.md`, fill in the team names, and push again.

## Step 5: Submit

1. Open the Pull Request from `team-j-solution` into `main` of the organizer repo. Paste the text from `SUBMISSION.md`.
2. On **OrganizerHQ**, one team member submits the project: repo URL, live URL, description, technologies, and select **both** *Best Open-Source AI Project* **and** *Best Use of Gemma 4*.
3. Sanity check as a stranger: open the repo in a private window. Can you find the LICENSE, the models table and the live URL in under a minute?

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Mic button says "Microphone blocked" | Page isn't on HTTPS, or the browser permission was denied |
| `/health` shows `"gemini": false` | `GEMINI_API_KEY` env var missing or misspelled; redeploy after setting |
| Replies say "Something went wrong" in Hindi | Look at the server logs; usually a bad or rate-limited API key |
| `gemma_models_available` is empty | Key invalid, or the Gemini API doesn't list that id yet; set `GEMMA_MODEL=gemma-4-31b-it` |
| App crashes / restarts on startup | Not enough RAM; use ≥ 2 GB |
| Very slow first voice reply | Voice model still downloading/loading; hit `/api/speak` once to warm up before the demo |
| Odia mic says "type instead" | By design: Whisper has no Odia. Type it |
| Replies are cut off on the host | A proxy is buffering the stream; the Caddyfile already disables that |
| 429 / "service busy" | Free API quota; wait a minute, or use a second key |
| Build can't pull the MMS models | Build still succeeds; the models download at first use instead |

## Before you present

- Two minutes before: open `/health`, then speak one sentence in Hindi and one in Bengali to warm everything.
- Keep a short screen recording as a backup in case the venue Wi-Fi dies.
