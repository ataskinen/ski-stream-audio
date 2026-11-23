# Ski Stream Audio

Two-way local-network audio between a Raspberry Pi at the timing tower and a Mac running OBS Studio. This is a separate project from Ski Stream Overlay.

- Tower to Mac: mixer announcer send -> Pi USB input -> network -> Mac -> OBS.
- Mac to tower: selected OBS interview audio -> network -> Pi USB output -> mixer -> PA.
- The announcer's local PA feed stays directly connected through the mixer.

## Implementation and status

Both endpoints support send-only, receive-only and duplex modes and run the same Python program using PortAudio (`sounddevice`). It sends uncompressed 48 kHz, 16-bit stereo PCM in small UDP packets. FFmpeg is not required. Each direction carries approximately 1.54 Mbit/s of audio, plus packet overhead.

The Pi can run natively or in Docker. The Mac audio endpoint runs natively; Docker Desktop is not the route to macOS audio devices.

Software tests cover packet reordering, loss, silence during outages, bounded buffering, sender restarts, channel mapping and two-way UDP loopback recovery. A short Mac-to-Pi 3B+ headphone test and sender-restart recovery check passed; see the [verification record](docs/verification.md). Full-duplex USB-interface and venue endurance tests are still required. This is an initial implementation, not a race-validated audio system.

## Get started

1. Follow [Raspberry Pi installation](raspberry-pi/README.md).
2. Follow [Mac installation and OBS setup](mac/README.md).
3. Check [audio routing](docs/audio-routing.md) before enabling speakers.
4. Run the [test and recovery checklist](docs/testing.md).

The browser control panel stores each endpoint’s settings in ignored `local/config.json`. The standalone CLI uses its own ignored `config.json`, copied from `config/pi.example.json` or `config/mac.example.json`. Replace the example IP addresses and audio-device names. Use DHCP reservations so addresses remain stable. No configuration is written into OBS automatically.

```sh
sh scripts/setup.sh
.venv/bin/python audio_link.py --list-devices
.venv/bin/python audio_link.py --config config.json --check
.venv/bin/python audio_link.py --config config.json
```

`--check` validates configuration only; it does not verify device availability. `--list-devices` lists the PortAudio names and indexes. Use explicit names when possible: numeric indexes may change after reboot.

## Ports and recovery

| Receiver | Default UDP port | Sender |
| --- | --- | --- |
| Mac | 5000 | Pi |
| Pi | 5001 | Mac |

The endpoint binds one socket and uses it for both send and receive. It accepts packets only from the configured source IP and source port (defaulting to the destination peer for older configs). Allow these UDP flows through local firewalls; no internet port forwarding is needed. AP/client isolation must be disabled between the endpoints.

UDP has no connection handshake. The sender keeps transmitting during network loss. Missing audio is replaced with silence; after a gap the receiver refills its short buffer and resumes. A new sender session resets the buffer. Audio-device errors cause the endpoint to reopen both streams after `retry_seconds`. A three-second audio-callback watchdog also triggers reopening if a device stops delivering callbacks. systemd, Docker or launchd can restart the process if it exits.

The program logs `STATUS` every five seconds. `link: receiving` means valid packets are arriving, not that the microphone is producing audible sound. `waiting` means no recent valid packets. Counters show missing/dropped packets, send errors and audio-device warnings. Packet delivery is not acknowledged, so the sender alone cannot confirm that the remote PA is working.

## Settings

See [configuration reference](docs/configuration.md). Default jitter buffering is eight 5 ms packets (40 ms). This is only part of end-to-end latency. Wi-Fi, audio devices, OBS and the Action 4 stream add their own delay.

The buffer stays bounded. Independent hardware clocks can cause occasional dropped or silent blocks during long runs; this version does not implement adaptive sample-rate conversion. Do the sustained listening test before race use. Increasing buffering is not a substitute for fixing an unreliable network.

## Development

Python 3.10 or later. Install the dependencies first (Python 3.13+ needs audioop-lts). No audio hardware is required for tests:

```sh
.venv/bin/python -m unittest -v
.venv/bin/python scripts/smoke_test.py
```

The authenticated browser control panel provides configuration, device selection, levels, logs, Start/Stop and a local output test. See [browser control](docs/browser-control.md). The setup scripts do not publish anything. See [publishing safely](docs/publishing.md) before uploading this project.

## References

- [python-sounddevice documentation](https://python-sounddevice.readthedocs.io/)
- [BlackHole virtual audio devices](https://github.com/ExistentialAudio/BlackHole)
- [OBS audio mixer guide](https://obsproject.com/kb/audio-mixer-guide)
