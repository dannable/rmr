# rmr-client

Vite + React + TypeScript SPA for the RMSS character builder.

## Setup

```sh
cd client
npm install
npm run dev   # http://localhost:5173 (proxies /api and /auth to localhost:8000)
```

In a second terminal, run the backend:

```sh
cd ..
pip install -e ".[web]"
python -m web   # http://localhost:8000
```

Visit http://localhost:5173 → "Sign in with Discord" → after callback you'll
land back on the SPA, signed in.

## Build

```sh
npm run build
```

The static bundle goes to `dist/`. In production, serve `dist/` from any
static host and point Discord OAuth's redirect URI at the FastAPI server.
