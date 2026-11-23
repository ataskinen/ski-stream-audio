# Verification record — 23 November 2026

## Automated checks

- 20 tests passed on the Mac and in the Pi’s Linux ARM64 container: configuration validation, packet handling, gain/mute/clipping, receive-only device selection, authenticated web access, cross-site request rejection, atomic settings persistence, fresh server startup and audio-device retry.
- JavaScript syntax checked; browser controls exercised for configuration, Save and apply, Start and Stop.
- Compose configuration built and ran on a Raspberry Pi 3 Model B Plus Rev 1.3 using 64-bit Debian 13.

## Real hardware test

The Mac sent a quiet 1 kHz PCM test tone over the local network. The Pi received it through the Docker worker and opened its built-in bcm2835 Headphones output at 48 kHz, stereo, with 10% receive gain.

The initial Python per-sample gain loop and low device buffer caused playback warnings. Native audioop processing, a stereo mapping fast path and a configurable 50 ms device buffer resolved the observed warnings in the repeat test. A sampled container CPU load fell from about 93% of one core to about 9%.

The repeat test received over 13,000 packets with zero reported missing packets, dropped packets or audio-device warnings at the observed checkpoint. Stopping the Mac changed the Pi to Waiting for audio with a zero receive meter; restarting the sender returned it to Receiving audio without restarting the Pi worker.

A subsequent Mac built-in microphone to Pi headphone test was audible. The listener estimated approximately 0.1 seconds of delay; this was a subjective estimate, not an instrumented latency measurement. Receive gain was tested up to 40%. Both audio workers and the Mac panel were stopped afterward, and the SSH session was closed. Saved settings were retained; audio autostart remained disabled.

## Limits and follow-up

- The Pi reported current undervoltage and throttling (`vcgencmd get_throttled`: `0x50005`). Check its power supply and cable before a sustained test.
- Headphone output was confirmed by the listener. A calibrated level or latency measurement was not performed.
- This was a short one-way headphone test, not a full-duplex USB-interface test or a venue endurance test.
- BlackHole was not present in the Mac device inventory. OBS audio routing still requires installing BlackHole 2ch/16ch and following the Mac guide. Both the tone and microphone tests bypassed OBS.
- No Mac login agent was installed and no system reboot was performed. Pi Compose starts its web service automatically; the Mac panel must be started manually unless its optional login agent is installed.
