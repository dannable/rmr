# rmr

Tools for running and playing **Rolemaster Fantasy Roleplaying** (RMFRP) — chart database, CLI lookups, and a Discord bot.

## What's in here

- **`schema.sql`** — SQLite schema for weapons, attack tables, critical-strike charts, and fumble tables.
- **`data/`** — Source data files. Each weapon, crit chart, and fumble table is one human-readable text file that the loader turns into rows in the DB.
- **`load.py`** — Reads `data/` and (re)builds `rmfrp.db`.
- **`core/`** — Pure-function lookup logic: weapon lookups, attack-chart lookups, crit chains, fumble chains, dice rolls. No I/O beyond SQLite reads. Imported by both the CLI and the bot.
- **`lookup.py` / `roll.py`** — CLI front-ends that print to a terminal.
- **`effects.py`** — Translates effect-code symbols (`π/∑/∏/∫`) into readable English.
- **`extract_skeletons.py`** — One-off tool that scans the source PDFs and produces skeleton data files (effect codes verbatim, narratives left as `TODO`). Used during initial population; not needed at runtime.
- **`bot/`** — Discord bot (Gateway WebSocket, slash commands).

## Quick start

```sh
# 1. Install (creates a venv and pins discord.py)
python -m venv .venv
. .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install -e .

# 2. Build the DB from data/
python load.py --reset

# 3. Use the CLI
python lookup.py attack "Battle Axe" 17 138 73
python roll.py "Battle Axe" 17 95
python lookup.py crit "Krush" E 73
python lookup.py fumble "Weapon Fumble Table" 1 75
```

## Discord bot

Set up:

```sh
cp .env.example .env       # then edit DISCORD_BOT_TOKEN and GUILD_IDS
python -m bot
```

Slash commands:

| Command | Purpose |
|---|---|
| `/rmr` | Roll a Rolemaster attack: d100 (open-ended) + OB → chart → crit chain. Two embeds: attack result, then crit result. |
| `/attack` | Static attack-chart lookup (no dice). Optional `crit_roll` chains to the crit chart. |
| `/crit` | Direct lookup on a critical strike chart. |
| `/fumble` | Direct lookup on a fumble table. |
| `/weapons` | List loaded weapons (ephemeral). |
| `/charts` | List loaded crit + fumble charts (ephemeral). |

Weapon and chart names use Discord autocomplete.

## Production deployment (Docker)

Two-host topology:

```
   Internet (TLS)            LAN
       │                       │
       ▼                       ▼
 ┌──────────────┐    ┌───────────────────────┐
 │  ravenloft   │    │      thematrix        │
 │  nginx +     │───▶│  Docker:              │
 │  Let's       │    │   rmr-init (one-shot) │
 │  Encrypt     │    │   rmr-bot             │
 │              │    │   rmr-web :8000       │
 └──────────────┘    └───────────────────────┘
```

The character builder runs three Docker services on **thematrix**, in one image:

| Service     | Lifecycle      | What it does                                  |
|-------------|----------------|-----------------------------------------------|
| `rmr-init`  | one-shot       | Refresh reference data (weapons / crits / fumbles) into `rmfrp.db`. Preserves user tables. |
| `rmr-bot`   | long-running   | Discord gateway client. (Slash commands, autocomplete.) |
| `rmr-web`   | long-running   | FastAPI + built SPA on `:8000`. The character builder. |

All three share the same image, the same `./data:/app/data` mount, and the
same `./db:/app/db` (which is where `rmfrp.db` persists). `rmr-bot` and
`rmr-web` `depends_on` `rmr-init`'s successful completion.

**ravenloft** terminates TLS and reverse-proxies `https://rolemaster.blackspiral.ca/` to thematrix's `:8000`.

### On thematrix (Docker host)

```sh
cd /opt
git clone https://github.com/dannable/rmr.git
cd rmr
cp .env.example .env
nano .env      # fill in:
               #   DISCORD_BOT_TOKEN, GUILD_IDS                  (bot)
               #   DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET      (web OAuth)
               #   WEB_SESSION_SECRET                            (web)
               #   WEB_REDIRECT_URI=https://rolemaster.blackspiral.ca/auth/discord/callback
               #   WEB_CLIENT_URL=https://rolemaster.blackspiral.ca
               #   WEB_INSECURE_COOKIES=0
               #   WEB_BIND_ADDR=192.168.1.61                    (thematrix's LAN IP)
               #   FORWARDED_ALLOW_IPS=192.168.1.64              (ravenloft's LAN IP — trust its X-Forwarded-*)

# Register the redirect URI in the Discord developer portal first:
#   https://rolemaster.blackspiral.ca/auth/discord/callback

docker compose up -d --build
docker compose logs -f rmr-bot rmr-web
```

Healthy startup looks like:

```
rmr-init  | DB written: /app/db/rmfrp.db
rmr-init  | Critical strike tables: ...
rmr-init  | exited with code 0
rmr-bot   | [entrypoint] DB exists at /app/db/rmfrp.db; skipping init
rmr-bot   | [entrypoint] starting: python -m bot
rmr-bot   | ... INFO bot.client: rmr-bot starting (DB_PATH=...)
rmr-web   | [entrypoint] DB exists at /app/db/rmfrp.db; skipping init
rmr-web   | INFO  Uvicorn running on http://0.0.0.0:8000
```

Verify ravenloft can reach the app over the LAN:

```sh
# from ravenloft
curl -i http://192.168.1.61:8000/healthz
# expect: HTTP/1.1 200 OK and {"ok": true}
```

### Firewall (on thematrix)

`WEB_BIND_ADDR=192.168.1.61` exposes :8000 on that interface; lock it down so
only ravenloft (192.168.1.64) can reach it. With `ufw`:

```sh
sudo ufw allow from 192.168.1.64 to any port 8000 proto tcp
sudo ufw deny  to any port 8000 proto tcp   # belt-and-braces
```

### On ravenloft (nginx + Let's Encrypt)

Get a cert if you don't have one (DNS for `rolemaster.blackspiral.ca` must
already point at ravenloft):

```sh
sudo certbot certonly --nginx -d rolemaster.blackspiral.ca
```

Drop this into `/etc/nginx/sites-available/rolemaster.blackspiral.ca.conf` and
symlink to `sites-enabled/`:

```nginx
upstream rmr_web {
    # thematrix on the LAN.
    server 192.168.1.61:8000;
    keepalive 16;
}

server {
    listen 443 ssl http2;
    server_name rolemaster.blackspiral.ca;

    ssl_certificate     /etc/letsencrypt/live/rolemaster.blackspiral.ca/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rolemaster.blackspiral.ca/privkey.pem;

    # Generous body size in case character sheet uploads grow.
    client_max_body_size 4m;

    location / {
        proxy_pass http://rmr_web;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection        "";

        # SSE (used by the character sheet for live combat updates).
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 86400s;
    }
}

server {
    listen 80;
    server_name rolemaster.blackspiral.ca;
    return 301 https://$host$request_uri;
}
```

Reload with `sudo nginx -t && sudo systemctl reload nginx`.

### Updates

**Code change (bot, web, or SPA):**
```sh
cd /opt/rmr
git pull
docker compose up -d --build       # rebuild image, recreate all three services
```

**Reference data change (new weapon / crit / fumble row):**
```sh
cd /opt/rmr
git pull
docker compose up -d rmr-init      # re-runs reload-ref on the existing DB
docker compose restart rmr-bot     # bot caches some lookups at startup
```

**Quick web restart (without DB touch):**
```sh
docker compose restart rmr-web
```

### Volumes

- `./data` (bind-mount, read-only inside container) — source-of-truth chart data, tracked in git.
- `./db` (bind-mount, read/write) — the generated SQLite DB. Gitignored. Inspect from the host with `sqlite3 ./db/rmfrp.db`. User data (`app_user`, `character_*`) lives here and is preserved across restarts.

### Destructive operations

To wipe `rmfrp.db` entirely (drops user data — characters, app users):

```sh
docker compose run --rm rmr-init python load.py --reset
```

Use sparingly. `--reload-ref` (the default in `rmr-init`) is the non-destructive form.

## Adding a new weapon or chart

1. Add a text file under `data/weapons/`, `data/crit_tables/`, or `data/fumble_tables/`. Format: see existing files (e.g. `data/weapons/battle_axe.txt`).
2. Run `python load.py --reset` to rebuild the DB.
3. Verify with `python lookup.py` or `python roll.py`.

## Project status

A working skeleton across:
- 9 weapon attack tables fully transcribed.
- 6 critical strike charts with full narratives; 6 more loaded as effect-code skeletons.
- Both fumble tables loaded (Weapon Fumble fully transcribed; Non-Weapon Fumble skeleton).
