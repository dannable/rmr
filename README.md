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

### One-time, on the host (e.g. thematrix)

```sh
cd /opt        # or wherever you keep deployments
git clone https://github.com/dannable/rmr.git
cd rmr
cp .env.example .env
nano .env      # fill in DISCORD_BOT_TOKEN and GUILD_IDS
docker compose up -d --build
docker compose logs -f rmr-bot
```

The container runs `load.py --reset` on every start (rebuilding `rmfrp.db`
from `data/`), then launches the bot. Healthy startup logs look like:

```
[entrypoint] building DB at /app/db/rmfrp.db from /app/data ...
[entrypoint] DB built; starting: python -m bot
... INFO bot.client: rmr-bot starting (DB_PATH=/app/db/rmfrp.db, guilds=[...])
... INFO bot.client: Synced N commands to guild ...
... INFO bot.client: Logged in as <bot> (id=...)
```

### Updates

**Code or data change:**
```sh
cd /opt/rmr
git pull
docker compose up -d --build      # rebuild image with new code/data
```

**Just a quick data tweak (no code change):**
```sh
cd /opt/rmr
git pull
docker compose restart rmr-bot    # entrypoint rebuilds DB from mounted data/
```

### Volumes

- `./data` (bind-mount, read-only inside container) — source-of-truth chart data, tracked in git.
- `./db` (bind-mount, read/write) — the generated SQLite DB. Gitignored. Inspect from the host with `sqlite3 ./db/rmfrp.db`.

## Adding a new weapon or chart

1. Add a text file under `data/weapons/`, `data/crit_tables/`, or `data/fumble_tables/`. Format: see existing files (e.g. `data/weapons/battle_axe.txt`).
2. Run `python load.py --reset` to rebuild the DB.
3. Verify with `python lookup.py` or `python roll.py`.

## Project status

A working skeleton across:
- 9 weapon attack tables fully transcribed.
- 6 critical strike charts with full narratives; 6 more loaded as effect-code skeletons.
- Both fumble tables loaded (Weapon Fumble fully transcribed; Non-Weapon Fumble skeleton).
