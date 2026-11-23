# Browser control

The web controller and audio worker are separate processes. The panel remains usable while audio is stopped or retrying a failed device. Start/Stop and settings updates are serialized. A worker that unexpectedly exits is restarted while the session is enabled.

## Addresses and credentials

- Pi Compose default: `http://audio-pi.local:8080` (or the Pi IP).
- Mac native default in these instructions: `http://127.0.0.1:8081`.
- Username: `admin`.
- Password: generated on first startup in `local/admin-password` (`/data/admin-password` inside the container).

Never commit `local/`, `.env`, passwords or real deployment configs. Password changes require editing that file and restarting the panel. Use at least 12 characters. Browser HTTP Basic credentials may remain cached until the browser session closes. The password is independent of SSH.

The panel uses HTTP without encryption. Use only on a trusted LAN; for other networks use a localhost binding and SSH tunnel or terminate HTTPS in front of it. API writes require authenticated same-origin JSON requests with an extra header; there is no cross-origin API access.

## Controls

- **Mode:** send only, receive only, or duplex. Inactive-direction devices are not opened.
- **Devices:** refresh the list after a USB change; choose the listed device and its channel count. Set two 1-based channel mappings; duplicate a mono input with `1, 1`.
- **Network:** destination IPv4/port, local bind IPv4/port, and accepted source IPv4/port. Changing local bind does not change the panel's HTTP address.
- **Gains:** 0–200%, with clipping protection. More than 100% can distort; start low. Gain/mute changes require Save and apply and briefly restart the audio worker.
- **Buffers/recovery:** jitter packets, maximum buffer, receive timeout and device retry delay.
- **Autostart:** persistent boot preference. Start/Stop changes current-session state only.
- **Save and apply:** validate, atomically persist, and restart active audio with the new settings. Invalid settings are rejected without replacing the previous configuration.
- **Test output:** quiet local 1 kHz tone for three seconds; respects saved receive gain/mute. It temporarily interrupts network audio and resumes it if it was running. It does not test the network. Save changes first.
- **Test tone input:** continuous network test signal until you stop or change input. The remote receiver will hear it; this is different from local Test output.

Meters show recent post-gain PCM peak levels sampled with status updates (about once per second), not calibrated loudness or guaranteed detection of brief transients. `Receiving audio` means valid network packets; silent audio can still arrive. Device warnings, lost/dropped blocks and recent errors appear alongside logs. An old error remains labelled as the last error even after recovery.

Browser device refresh launches a fresh PortAudio inventory. Device names can change after reboot and duplicate names may be ambiguous. For unusual hardware use the CLI device index in the saved JSON; verify it again after reboot. Automatic hardware-ID tracking is not implemented.

## Headphone test

1. On Pi choose Receive only and the bcm2835 Headphones output, 2 channels, mapping 1,2, receive gain 10%.
2. Accept the Mac IPv4 address, source port 5000; listen on 5001.
3. On Mac choose Send only and Test tone; send to Pi IPv4 port 5001 from local port 5000.
4. Save both. Start Pi, then Mac. Watch the Pi receive meter, then listen at a low level.
5. Stop Mac. Pi should become Waiting for audio. Restart Mac; Pi should recover.
6. Replace Test tone with BlackHole 16ch and route only the desired OBS sources to that bus.

The application can verify packets and that the output stream is running. A person must confirm audible output and acceptable latency through the actual headphones or speakers.
