"""Upload d10 face PNGs to a Discord guild as custom emoji.

One-shot tool. Reads dice images from `d10s/TensDie` and `d10s/OnesDie`,
uploads each as a guild emoji on the target server, and writes the
resulting <:name:id> map to `bot/dice_emoji.json` so the bot can render
percentile rolls using actual dice images instead of text fallback.

Usage:
    # In .env (or your shell env):
    #   DISCORD_BOT_TOKEN=...   (the same bot the production /rmr uses)
    #   DICE_EMOJI_GUILD_ID=689178570970628148
    python scripts/upload_dice_emoji.py
    python scripts/upload_dice_emoji.py --replace   # delete-and-reupload

Discord limits:
    * 50 static emoji per guild on the free tier (we use 20).
    * 256 KB max per emoji image (each die PNG here is ~5 KB).
    * Bot needs the "Manage Expressions" permission in the target guild.

Naming convention written into Discord:
    Tens: d10t00, d10t10, d10t20, ..., d10t90
    Ones: d10o0,  d10o1,  ...,           d10o9

The output JSON file matches what `bot/render.py` expects.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import requests  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
TENS_DIR = ROOT / "d10s" / "TensDie"
ONES_DIR = ROOT / "d10s" / "OnesDie"
OUTPUT_PATH = ROOT / "bot" / "dice_emoji.json"

API = "https://discord.com/api/v10"


def png_data_uri(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def discord_request(method: str, path: str, token: str, **kw):
    headers = kw.pop("headers", {}) | {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    r = requests.request(method, f"{API}{path}", headers=headers, timeout=30, **kw)
    if r.status_code >= 400:
        raise SystemExit(
            f"{method} {path} failed: {r.status_code} {r.reason}\n{r.text}"
        )
    return r.json() if r.text else None


def list_existing(token: str, guild_id: int) -> dict[str, dict]:
    """Return existing guild emoji indexed by name."""
    items = discord_request("GET", f"/guilds/{guild_id}/emojis", token)
    return {e["name"]: e for e in items}


def upload(token: str, guild_id: int, name: str, png_path: Path) -> dict:
    print(f"  uploading {name:<10} ← {png_path.name}")
    return discord_request(
        "POST",
        f"/guilds/{guild_id}/emojis",
        token,
        json={"name": name, "image": png_data_uri(png_path)},
    )


def delete(token: str, guild_id: int, emoji_id: str, name: str) -> None:
    print(f"  deleting  {name} ({emoji_id})")
    discord_request("DELETE", f"/guilds/{guild_id}/emojis/{emoji_id}", token)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--replace",
        action="store_true",
        help="Delete any pre-existing d10t*/d10o* emoji on the guild before uploading.",
    )
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except ImportError:
        pass

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_raw = os.environ.get("DICE_EMOJI_GUILD_ID", "").strip()
    if not token or not guild_raw:
        sys.exit("Set DISCORD_BOT_TOKEN and DICE_EMOJI_GUILD_ID in env or .env.")
    guild_id = int(guild_raw)

    if not TENS_DIR.is_dir() or not ONES_DIR.is_dir():
        sys.exit(f"Missing dice images: {TENS_DIR} or {ONES_DIR}")

    existing = list_existing(token, guild_id)
    print(f"guild {guild_id} has {len(existing)} existing emoji")

    # Build the work list: (emoji_name, source_png_path, json_section, json_key)
    work: list[tuple[str, Path, str, str]] = []
    for tens in range(0, 100, 10):
        name = f"d10t{tens:02d}"
        src = TENS_DIR / f"TensDice_{tens:02d}.png"
        work.append((name, src, "tens", str(tens)))
    for ones in range(10):
        name = f"d10o{ones}"
        src = ONES_DIR / f"OnesDie_{ones}.png"
        work.append((name, src, "ones", str(ones)))

    # Sanity-check that every source PNG actually exists before we touch Discord.
    missing = [str(s) for _, s, _, _ in work if not s.is_file()]
    if missing:
        sys.exit("Missing source PNGs:\n  " + "\n  ".join(missing))

    if args.replace:
        for name, _, _, _ in work:
            if name in existing:
                delete(token, guild_id, existing[name]["id"], name)
                del existing[name]

    out: dict[str, dict[str, str]] = {"tens": {}, "ones": {}}
    for name, src, section, key in work:
        if name in existing:
            emoji = existing[name]
            print(f"  keeping   {name:<10} (already on guild)")
        else:
            emoji = upload(token, guild_id, name, src)
        out[section][key] = f"<:{name}:{emoji['id']}>"

    OUTPUT_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUTPUT_PATH} ({len(out['tens'])} tens + {len(out['ones'])} ones emoji)")


if __name__ == "__main__":
    main()
