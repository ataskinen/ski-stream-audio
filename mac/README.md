# Mac installation and OBS routing

Run these commands from the project root. Keep the Mac awake during the event.

## 1. Install dependencies

Install Python 3.10+ and PortAudio. With Homebrew already installed:

```sh
brew install python portaudio
sh scripts/setup.sh
```

Install **both BlackHole 2ch and BlackHole 16ch using Homebrew** (recommended):

```sh
brew install --cask blackhole-2ch blackhole-16ch
```

Restart the Mac after installation before configuring the audio devices. These are two independent audio buses. Do not use the same bus for both directions.

Homebrew package references: [BlackHole 2ch](https://formulae.brew.sh/cask/blackhole-2ch) and [BlackHole 16ch](https://formulae.brew.sh/cask/blackhole-16ch). If you do not use Homebrew, the official [BlackHole installer](https://github.com/ExistentialAudio/BlackHole) is an alternative.

In macOS Audio MIDI Setup, set both BlackHole devices to 48,000 Hz. Set OBS Settings -> Audio -> Sample Rate to 48 kHz as well. Leave macOS system output on your normal speakers/headphones, not a BlackHole device, to avoid sending notification sounds to the PA.

## 2. Browser control (recommended)

After installing dependencies, start the panel from the project root:

```sh
.venv/bin/python admin.py --data-dir local --port 8081
```

Open **http://127.0.0.1:8081**. The user is **admin**; read the generated password in a second terminal:

```sh
cat local/admin-password
```

The Mac panel listens only on localhost by default. It stores its own settings in `local/config.json`; the Pi has a separate configuration. Choose **Send only** for the Pi headphone test. Select **Test tone** as input to test without BlackHole or a microphone. Set destination IP to the Pi's address, destination port **5001**, local port **5000**, and send volume **10%**. Save and start. Stop the test tone after checking the Pi's receive meter and headphones.

For OBS audio, choose **BlackHole 16ch** as the input, channel count **16**, mapping **1, 2**. Follow the OBS routing section below. For full duplex, choose **Send and receive**, use **BlackHole 2ch** as output with two channels, and accept incoming audio from the Pi IP and source port **5001**.

Changing mode, devices, network settings, gain or mute requires **Save and apply**. Applying restarts the audio worker if it was running. The Stop button stops it immediately. The optional boot checkbox controls automatic audio startup when the panel launches.

Read [browser control](../docs/browser-control.md) for status and password details. For automatic panel startup, use the login-agent installer with `--admin`, as described below.

### Standalone CLI alternative

Do not run the CLI and browser-managed audio simultaneously on the same UDP port. The CLI uses a separate `config.json` at the project root:


```sh
cp config/mac.example.json config.json
.venv/bin/python audio_link.py --list-devices
```

Edit `config.json`:

- `peer_ip`: the Pi's reserved IPv4 address.
- `listen_port`: 5000; `peer_port`: 5001.
- `input_device`: `BlackHole 16ch` (captures the OBS interview return).
- `input_channels`: 16; `input_map`: `[1, 2]`.
- `output_device`: `BlackHole 2ch` (delivers tower audio to OBS).
- `output_channels`: 2; `output_map`: `[1, 2]`.

Use names/indexes exactly as the device listing reports. Start in a terminal and grant macOS microphone access if prompted:

```sh
.venv/bin/python audio_link.py --config config.json --check
.venv/bin/python audio_link.py --config config.json
```

If capture fails, check System Settings -> Privacy & Security -> Microphone for the launching application. Also allow incoming connections if macOS Firewall prompts. A `receiving` status alone does not prove audio capture/playback works; watch OBS meters and listen at low volume.

## 3. Route OBS

1. Add **Audio Input Capture**, name it `Tower announcer`, and select **BlackHole 2ch**. Reuse that source across scenes as needed.
2. In OBS Settings -> Audio -> Advanced, select **BlackHole 16ch** as the **Monitoring Device**.
3. In Advanced Audio Properties, set `Tower announcer` to **Monitor Off**. It goes to the stream but must never go to the monitoring bus.
4. Set the Action 4 interview source to **Monitor and Output** when its audio should go to both the stream and PA.
5. Keep other sources on **Monitor Off** unless they are deliberately intended for the PA.
6. Disable duplicate global Mic/Aux captures of either BlackHole device. Do not capture the return bus as another OBS input.

Use headphones and low PA volume while testing. Switching away from the interview must stop/mute its audio. OBS sources can remain active through nested/shared scenes or source settings, so explicitly test the actual scenes; this program does not control OBS scenes or source muting.

The monitoring device is dedicated to the PA return. It is not your headphone monitoring output. Any separate headphone routing must preserve this separation.

## 4. Optional launch at login

Do this only after successful manual audio tests. This runs in your logged-in user session, not before login.

```sh
.venv/bin/python mac/install-launch-agent.py --admin
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/local.ski-stream-audio.plist"
```

Stop the foreground panel and any CLI instance first. Only one panel may bind port 8081 and only one audio worker may bind UDP port 5000. Omit `--admin` when installing a CLI-only agent instead. Check:

```sh
launchctl print gui/$(id -u)/local.ski-stream-audio
tail -f "$HOME/Library/Logs/SkiStreamAudio/stderr.log"
```

If macOS blocks microphone access for the launch agent, continue using the foreground terminal until permissions are resolved. Login launch and privacy permissions require testing on this Mac. Logs are ordinary files; archive/remove them periodically while the service is stopped.

To stop and remove automatic startup:

```sh
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/local.ski-stream-audio.plist"
rm "$HOME/Library/LaunchAgents/local.ski-stream-audio.plist"
```

Reinstall the agent if the project folder moves. For a temporary event session, you can run the foreground endpoint under `caffeinate -i` to prevent idle sleep.
