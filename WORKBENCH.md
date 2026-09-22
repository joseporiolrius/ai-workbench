# S4 workbench stack (WB-04)

Two services from the qualified immutable course images — **pi-web-ui** (chat/agent
UI) and **Qdrant** (vector DB) — run from [`compose.yml`](./compose.yml). Both bind
to **loopback** on the VM; you reach the UI over an **SSH tunnel**, never a public
port.

## Configure

```bash
cp .env.example .env            # paste ONLY your student COURSE_VIRTUAL_KEY (git-ignored)
```

`pi-config/models.json` points the UI at the course gateway
(`https://litellm.joor.net/v1`) and references `COURSE_VIRTUAL_KEY` — no key value
is stored in the repo.

## Run + inspect

```bash
docker compose up -d
docker compose ps                       # both -> healthy
docker compose logs pi-web-ui           # / qdrant
docker exec -it <container> sh          # exec inspection
```

Reach the UI from your laptop over the tunnel:

```bash
ssh -i dbai.pem -L 8787:127.0.0.1:8787 ubuntu@<VM_IP>
# open http://localhost:8787
```

## Ports, health, persistence

- `pi-web-ui` `127.0.0.1:8787`, `qdrant` `127.0.0.1:6333` — loopback only.
- Health: pi-web-ui via `node` fetch of `/health`; Qdrant via a `bash` TCP probe
  of `/healthz` (the images have no `curl`/`wget`).
- Named volumes `pi-data` + `qdrant-data` survive `docker compose down && up`.
  **Never `down -v` in the normal lab** — that erases your data.

## Before retrieval (S12)

Qdrant starts with **no collections** (`GET /collections` → `[]`); no study-guide
retrieval extension or corpus is active yet.

## Safety / evidence

- Do not expose 8787/6333 publicly — the UI has no built-in auth.
- Course secrets stay in `.env` (git-ignored) and out of logs.
- Record under `evidence/s04/`: `docker compose ps` healthy, a tunnelled UI
  screenshot, and the empty `/collections` response.
