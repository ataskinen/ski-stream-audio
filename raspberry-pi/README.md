# Raspberry Pi installation with Docker Compose

Use a 64-bit Raspberry Pi OS Lite installation. Raspberry Pi 3B+ is the target. A receive-only headphone test works with the built-in 3.5 mm output; capture requires a USB microphone or USB audio interface.

## 1. Install Docker and Compose

On Debian 13 / Raspberry Pi OS based on Debian 13:

```sh
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl enable --now docker
sudo docker compose version
```

The Debian 13 `docker-compose` package provides Compose v2. For other OS releases, follow [Docker's Debian installation guide](https://docs.docker.com/engine/install/debian/) instead. Docker Machine is not needed. Use `sudo docker` unless you deliberately grant your user membership in the Docker group.

## 2. Copy the project

From the Mac, in the project directory (replace `pi-user` with your SSH username and `audio-pi.local` with your Pi hostname):

```sh
rsync -av --exclude '._*' --exclude .git --exclude .venv --exclude __pycache__ --exclude .env --exclude local --exclude config.json ./ pi-user@audio-pi.local:~/ski-stream-audio/
```

Do not copy the Mac's virtualenv or local settings. On the Pi:

```sh
cd ~/ski-stream-audio
mkdir -p local
printf 'AUDIO_UID=%s\nAUDIO_GID=%s\nAUDIO_GROUP_ID=%s\n' "$(id -u)" "$(id -g)" "$(getent group audio | cut -d: -f3)" > .env
sudo docker compose up -d --build
sudo docker compose logs --tail=30
cat local/admin-password
```

Compose runs one non-privileged container, gives it `/dev/snd` access and the host audio group, uses Linux host networking, persists settings under `local/`, caps Docker logs and restarts the service automatically. The container runs with your UID/GID. Keep `local/` writable by that user.

## 3. Open the browser control panel

Open **http://audio-pi.local:8080** from the Mac, or use the Pi's IPv4 address. Log in as **admin** with the password printed by `cat local/admin-password`.

The first boot generates a random password and starts with audio **stopped**. This password is separate from SSH. All routes, including status and device lists, require login. HTTP Basic authentication is appropriate only on the trusted test LAN: it does not encrypt the password. For an untrusted/shared venue network, bind the panel to localhost and use an SSH tunnel or add TLS before use. Do not forward port 8080 to the internet.

In the panel:

1. Choose **Receive only** for the headphone test.
2. Refresh devices and select **bcm2835 Headphones**. Use the exact listed name; the PortAudio index is not the same as ALSA's card index.
3. Set output channels to **2**, mapping **1, 2**, and receive volume to **10%** initially.
4. Set the accepted source IP to the Mac's IPv4 address and source UDP port to **5000**. Set the local UDP port to **5001**.
5. Set the send destination to the same Mac IP/port for future duplex use; sending is disabled in receive-only mode.
6. **Save and apply**, then **Test output · 3 seconds**. Start with headphones off your ears until the level is comfortable.
7. **Start audio** and send a test tone from the Mac. The state should change to Receiving audio.

The source filter requires both IP and source port to match. Use stable/reserved IPv4 addresses. All configuration, channel mapping, gains/mutes, buffers and automatic audio startup are editable in the browser. Gain/mute changes apply on **Save and apply**, which restarts the audio process; they are not live faders. Stop is immediate. A local output tone temporarily pauses network audio and resumes its previous running state afterward.

## Operations

```sh
sudo docker compose ps
sudo docker compose logs -f
sudo docker compose restart
sudo docker compose down
```

The **Start audio when the server boots** checkbox controls audio startup. Compose always starts the web control panel. The Start/Stop buttons affect the current session; they do not change the saved boot preference. The controller restarts an unexpectedly exited audio worker while audio is enabled.

Restart/recreate the container after USB replug if device nodes change. Refresh devices afterward. Do not run a native service and Compose on the same UDP port.

To update, copy the new source files without overwriting `.env` or `local/`, then run `sudo docker compose up -d --build`.

## Native alternative

```sh
sudo apt-get install -y python3 python3-venv libportaudio2 alsa-utils
sh scripts/setup.sh
.venv/bin/python admin.py --host 0.0.0.0 --data-dir local
```

This provides the same panel. Your user needs access to the audio devices (normally membership in `audio`). The included `ski-stream-audio.service` is a separate CLI-only option using `/etc/ski-stream-audio/config.json`; it does not start the panel. Prefer Compose for the managed Pi installation.
