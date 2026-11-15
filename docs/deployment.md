# Deploy on Arduino UNO Q (4GB)

The target is the UNO Q's Debian Linux **ARM64** host. The MCU sketch remains in
Arduino App Lab; it is not a Docker workload. The frontend, Django backend, and
optional CPU inference service run on the board. SQLite remains the only database.

## First setup

Prerequisites: Docker Engine with working user access, Docker Compose v2.24.4 or
newer, Python 3 for the setup helpers, and enough storage for images, models, and
future audio. Do not install another Docker engine over the App Lab installation.
The connected board checked during implementation has Debian 13, Docker 26.1.5,
Compose 2.26.1, `/dev/snd`, and `/var/run/arduino-router.sock`.

From the repository root on the UNO Q:

```sh
python3 deploy/init-env.py
sh deploy/unoq-preflight.sh
```

The initializer creates configuration when missing, generates a private Django
key when blank, sets `DJANGO_DEBUG=false`, and preserves existing provider keys.
Credentials stay in gitignored `backend/.env`, which is excluded from images.
`deploy/unoq.env` contains only deployment settings. Keep `localhost` in
`DJANGO_ALLOWED_HOSTS`: container health checks use it.

Edit `backend/.env` for your speech/prediction provider. Without provider keys,
history/default predictions and browser speech fallback still work; backend TTS
reports unavailable. No credentials are passed to the inference container.

## Build on the development computer

Builds use native ARM64 Linux images by default, including on Apple Silicon. Build
away from the board to avoid compilation and package downloads on its 4GB RAM:

```sh
docker compose build frontend backend inference
docker save -o /tmp/smart-aac-arm64.tar smart-aac-frontend:local smart-aac-backend:local smart-aac-inference:local
scp /tmp/smart-aac-arm64.tar arduino@BOARD_IP:/tmp/
```

On the board, load and remove the transfer archive:

```sh
docker load -i /tmp/smart-aac-arm64.tar
rm /tmp/smart-aac-arm64.tar
```

If storage is tight, avoid storing an archive on the board. From the build host:

```sh
docker save smart-aac-frontend:local smart-aac-backend:local smart-aac-inference:local | ssh arduino@BOARD_IP docker load
```

Copy the checkout/configuration to the board separately. Configure its credentials
locally; do not bake `.env` into an image or publish it. No registry is required.
For a registry, tag/push all three images and change their Compose image names.
For AMD64 Linux, build and deploy with `AAC_PLATFORM=linux/amd64`; UNO Q always
uses `linux/arm64`. ARM64 MiniLM is the validated target model.

## Start the core AAC app

```sh
sh deploy/aac up -d --no-build --wait
```

Open `http://localhost:5173` in the board's browser. `http://localhost:8000` also
reaches the gateway so existing bridge/API URLs work. Nginx serves the compiled UI,
generated audio, and Django static assets, and proxies `/api/`, `/ws/`, and `/admin/`.
No Node build process or Vite dev server runs on the board. Daphne runs exactly
one process because the Channels group is in memory; do not scale backend replicas.

Migrations and static collection run at backend startup. Demo seeding is explicit:

```sh
sh deploy/aac exec backend python manage.py seed_demo
```

Existing host-run demo servers may already occupy 8000/5173. Stop them deliberately
before switching over, or choose other ports in `deploy/unoq.env`. Update the bridge
URL, browser origins, and public audio URL if ports change. Never start two bridges
registered for `aac_token` at once.

## Enable local Conversation Mode

Provision public models once while the board has internet access:

```sh
sh deploy/aac run --rm --no-deps models
sh deploy/aac --profile conversation up -d --no-build --wait
```

The setup command downloads Moonshine tiny, Silero VAD, and revision-pinned MiniLM.
Its manifest records hashes and verifies existing files before skipping downloads.
Runtime mounts models read-only and has **no network interface**. Alternatively,
copy existing model files into the `models` volume with their documented directory
structure; see `backend/deploy_models.py`. Incomplete models prevent inference
readiness; they do not prevent core AAC from starting.

To reuse the existing host models without another download (adjust the source path):

```sh
docker run --rm --user 0:0 --network none --entrypoint sh -v /path/to/existing/models:/source:ro -v smart-aac_models:/models smart-aac-inference:local -c 'cp -a /source/. /models/ && chown -R 10001:10001 /models'
```

Check `arecord -l` and `stat -c '%g' /dev/snd/pcmC0D0c`. Set `AAC_LISTEN_DEVICE`
and `AAC_AUDIO_GID` in `deploy/unoq.env`; the checked board uses audio group 29.
`compose.unoq.yaml` maps `/dev/snd` only to inference, with that supplementary
group. No privileged container, host networking, or GPIO/5V assumptions are needed.
Card/device presence alone does not prove the microphone routing or levels work.
If needed, configure the board's ALSA routing on the host and validate a real mic.
User-specific host `.asoundrc` is not inherited: prefer explicit `plughw:CARD,DEVICE`.

Conversation Mode still requires explicit caregiver activation and has a visible
stop control. Closing the browser or backend connection stops capture and discards
queued results. Audio/transcripts exist only in memory. Playback pause is forwarded
to inference, and normal time/activity/history predictions remain available when
inference fails. CPU execution only; there is no Adreno/GPU configuration.

To stop inference without stopping the core app:

```sh
sh deploy/aac stop inference
```

## Buttons and LAN access

Keep the UNO Q router bridge on the host to preserve App Lab integration and host
LCD metrics. Use the existing bridge installation, or create a hardware venv and
install `hardware/requirements.txt`, then run:

```sh
python hardware/unoq_bridge.py --ws-url ws://127.0.0.1:8000/ws/input/
```

`deploy/unoq-bridge.service.example` is an optional systemd template; adjust paths
and check for an existing bridge before installing it. The MCU sketch and App Lab
services are not changed. The separate UNO R3 serial bridge can also run on the
host. Keyboard fallback remains Space = NEXT and Enter = SELECT.

Bindings default to loopback. For trusted LAN access set
`AAC_BIND_ADDRESS=0.0.0.0` in `deploy/unoq.env`, add the board IP/name to
`DJANGO_ALLOWED_HOSTS`, and set `DJANGO_ALLOWED_ORIGINS` to the exact frontend
origin(s), e.g. `http://localhost:5173,http://192.168.1.50:5173`. Set
`BACKEND_PUBLIC_BASE_URL=http://192.168.1.50:8000` for a Google Home speaker to fetch
audio. Then recreate the services. The optional speaker uses its configured IP;
test LAN reachability on the deployment network. This app remains unauthenticated
and intended for the device/trusted LAN.

## Health, storage, updates, and recovery

```sh
sh deploy/aac --profile conversation ps
sh deploy/aac logs --tail=50 backend inference
docker stats --no-stream
```

Containers have bounded logs, non-root users, read-only roots, no extra Linux
capabilities, restart policies, and health checks. Resource ceilings are 96 MiB
frontend, 640 MiB backend, and 1100 MiB inference. These are ceilings, not
reservations. Model threads are bounded (two transcription, one embedding), with
one decode per model at a time. The checked UNO Q rejects Docker CPU quotas with
`cpu.max: no such file or directory`; the default deliberately avoids them without
changing the board's kernel or cgroup configuration. `compose.cpu-limits.yaml` is
an optional override for other hosts that support CPU quota enforcement.
Leave headroom for Linux, App Lab and the
kiosk browser, and measure the real workload. Model setup is an explicit online
job, never part of boot. Docker must already be enabled at boot for restart policies.

Named volumes under the default `smart-aac` project:

| Volume | Purpose |
| --- | --- |
| `smart-aac_database` | SQLite application data |
| `smart-aac_media` | Generated speech audio |
| `smart-aac_static` | Regenerated Django/Swagger assets |
| `smart-aac_models` | Downloaded CPU models |
| `smart-aac_inference-socket` | Local socket, recreated by inference |

`sh deploy/aac down` preserves volumes. **`down -v` deletes application data and
models.** Do not prune the board's unrelated App Lab images/volumes to make space.
Bound generated audio periodically with the existing `cleanup_audio` command
(`sh deploy/aac exec backend python manage.py cleanup_audio --help`).

For a consistent backup, stop backend and frontend, then copy the database and
media volumes together. Example from the host repository, with images already loaded:

```sh
mkdir -p backups
sh deploy/aac stop backend frontend
docker run --rm --user 0:0 --network none --entrypoint tar -v smart-aac_database:/data:ro smart-aac-backend:local -C /data -cf - . > backups/database.tar
docker run --rm --user 0:0 --network none --entrypoint tar -v smart-aac_media:/media:ro smart-aac-backend:local -C /media -cf - . > backups/media.tar
sh deploy/aac up -d --no-build --wait
```

Treat backups as private application data. To restore, stop the writers and extract
each archive into its matching volume using the same image and `tar -xpf -`; keep
numeric ownership 10001:10001. Do not overwrite a live SQLite database. A host-run
SQLite deployment can be migrated by stopping it, copying its database and audio
into these volumes, setting ownership, then starting Compose; never run both writers.

Before an upgrade, take a backup and retain the previous image tag. Load new tagged
images, set `AAC_IMAGE_TAG`, and run `up -d --no-build --wait`. Schema changes may
require restoring the matching database backup when rolling back an image.

## Verify a deployment

Using a host Python environment with `hardware/requirements.txt` installed:

```sh
sh deploy/aac exec backend python manage.py seed_demo
python deploy/smoke.py --url http://localhost:5173
```

This checks the built frontend, Swagger assets with DEBUG off, API writes with
synthetic profiles, exactly six predictions, and an input WebSocket broadcast.
It uses the seeded caregiver (or `--caregiver-id`), deletes its temporary patient,
and never calls a hosted speech provider.
`--conversation` explicitly starts capture, checks a real transcript and suggestions,
then stops; automated tests should select a prerecorded file, not activate a real mic.
For a file test, mount a WAV read-only into inference and set
`AAC_LISTEN_DEVICE=file:/fixtures/example.wav` in an additional Compose override.

Before switching the demo, verify actual physical buttons, keyboard scanning,
speaker playback, microphone capture, listening stop/pause, data after restart, and
the stack after a normal board reboot. A prerecorded fixture cannot verify physical
microphone routing or button wiring.

## Private inference interface

Public APIs and both browser WebSocket contracts are unchanged. The added internal
interface is newline-delimited JSON over `/run/aac/inference.sock` (mode 0660,
UID/GID 10001), shared only by backend and inference. No TCP endpoint exists.

- `health` returns readiness after models have loaded without opening a mic.
- `embed` accepts up to 1024 bounded strings and returns vectors.
- `pause` suppresses capture processing for a bounded number of seconds.
- `listen` claims one microphone, acknowledges readiness, then streams text/delay,
  heartbeats, and an end event. Socket close stops capture; pending results are dropped.

Frames are capped at 2 MiB, client calls have timeouts, and request/error bodies are
never logged. Models remain resident in one inference process. Patient/history
tables, provider credentials, and generated speech files are not mounted there.
Blank `INFERENCE_SOCKET` preserves the existing in-process development path.

## Implementation verification

All three ARM64 images built successfully. The backend suite passed 248 tests
(one skipped). Model setup downloaded successfully and a second run verified its
manifest without another download. Configuration initialization preserved existing
synthetic keys and remained unchanged on a second run.

An isolated stack on the connected UNO Q passed the smoke test using synthetic
profiles and a prerecorded public speech fixture, including actual CPU transcription
and conversation suggestions. Container recreation preserved the seeded SQLite data.
ALSA devices were visible inside the unprivileged inference container, generated WAV
audio was served with DEBUG off, and core AAC remained available with inference stopped.
The existing board demo was not replaced. A warm idle snapshot showed approximately
67 MiB backend, 240 MiB inference, and 2.4 MiB frontend; this is not a peak-memory or
latency benchmark. Physical microphone routing, buttons, speaker playback, browser
responsiveness under sustained load, and reboot behavior remain hands-on checks.
