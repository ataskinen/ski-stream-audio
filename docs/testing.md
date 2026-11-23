# Testing and recovery checks

## Automated software tests

No microphone, speaker, driver installation or external service is used:

```sh
.venv/bin/python -m unittest -v
.venv/bin/python scripts/smoke_test.py
```

The unit suite includes real loopback UDP traffic, both directions, source filtering and recovery after peer replacement. The smoke test launches two CLI processes, stops one, waits for the other to report `waiting`, restarts it, then checks it reports `receiving` again. It cleans up its child processes and temporary configs.

## Test across the venue network without devices

Configure the normal peer addresses and ports on both hosts. Run this on each:

```sh
.venv/bin/python audio_link.py --config config.json --test --duration 30
```

Both logs should change from `waiting` to `receiving`, and `received`/`sent` should rise. Test mode sends a quiet 1 kHz tone and discards received audio. It does not open audio hardware. **If the other endpoint is in real playback mode, the test tone will be audible there.** Keep speakers muted when mixing modes.

Stop one endpoint, wait at least one status interval, and restart it. The other should report `waiting` during the outage and return to `receiving`. No lost audio is replayed.

## Hardware acceptance (required before race use)

1. List and configure the exact USB/BlackHole devices; test capture and playback at 48 kHz.
2. Check mixer line levels, phantom-power settings and interface direct monitoring. Use line input for a mixer line output.
3. Test tower-to-OBS alone. Confirm OBS meters move and record a short local sample.
4. Test interview-to-PA alone at low volume. Confirm only intended sources reach the PA.
5. Enable both with the mix-minus rules in `audio-routing.md`. Confirm no delayed announcer echo or loop.
6. Switch between race and interview scenes. Confirm interview audio stops when intended, including shared/nested-source cases.
7. Run both directions for at least an hour on the actual venue network. Listen for dropouts, clicks or drift and check status counters.
8. Disable the network for 10 seconds and restore it. Reception should resume automatically. Measure recovery time; do not infer it from unit tests.
9. Unplug/replug the USB interface. Confirm reopening or restart the Docker container if device nodes changed. Recheck device selection.
10. Reboot both hosts, check supervisor startup and Mac permissions, then repeat a brief audio test.
11. Use a clap to measure stream lip sync and separately assess PA interview delay.

## Troubleshooting

- `waiting`: wrong IP/port, peer stopped, firewall, AP client isolation, or incompatible protocol. Peer port must match the actual source/listening port.
- `receiving` but no sound: inspect physical gain/mute, channel mappings, selected device and OBS routing. Network counters do not indicate signal level.
- Bind/address-in-use error: stop the other endpoint instance, native service or container using that port.
- Audio stream error: verify device name, 48 kHz support, simultaneous input/output, permissions and power. Device indexes can change.
- Missing packets/audio warnings: check the venue network and CPU load. Increase jitter_packets modestly if needed (with max_packets >= twice it), accepting more delay.
- Occasional clicks in a long otherwise healthy session: independent device clock drift can cause buffer corrections. This version uses block drops/silence, not adaptive resampling. Do not declare the system race-ready if this is audible or frequent.
- Feedback: mute the mixer return immediately, then verify both mix-minus exclusions and microphone/speaker placement.

Docker image builds and local synthetic tests do not validate Pi USB access, RF conditions, mixer routing or macOS privacy permissions.

## Pi power check

Run `vcgencmd get_throttled` on the host. Current undervoltage/throttling must be resolved before evaluating sustained audio reliability. Check the supply and cable, then retest. Historical flags remain set until reboot; do not confuse them with a current fault. See the [Raspberry Pi power documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply).
