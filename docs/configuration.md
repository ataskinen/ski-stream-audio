# Configuration reference

The program reads JSON at startup. Restart after edits. Unknown keys are rejected to catch typos.

| Key | Meaning |
| --- | --- |
| `mode` | `send`, `receive` or `duplex` (default) |
| `source_ip`, `source_port` | Accepted sender address and source port; default to peer address/port |
| `send_gain`, `receive_gain` | Linear gain 0–2 (0–200%); receive defaults to 25% |
| `send_mute`, `receive_mute` | Boolean mute switches |
| `autostart` | Start audio when the web controller boots; default false |
| `peer_ip` | Required fixed IPv4 address of the other endpoint |
| `bind_ip` | Local address; default `0.0.0.0` |
| `listen_port` | Local UDP port, 1024–65535 |
| `peer_port` | Other endpoint's listening port; also the accepted source port |
| `input_device` | Explicit PortAudio capture device name or integer index, or `Test tone`; unused in receive mode |
| `output_device` | Explicit PortAudio playback device name or integer index; unused in send mode |
| `input_channels` | Number of device channels opened, default 2 |
| `output_channels` | Number of device channels opened, default 2 |
| `input_map` | Two 1-based device channels sent as network left/right; `[1,1]` duplicates mono |
| `output_map` | Two distinct 1-based device channels receiving network left/right; others are zero |
| `device_latency_seconds` | PortAudio suggested device buffer, default 0.05 s; larger values improve scheduling tolerance at the cost of delay |
| `jitter_packets` | Packets required before playback; default 8 = 40 ms |
| `max_packets` | Buffer limit; default 32 = 160 ms; at least twice jitter_packets |
| `timeout_seconds` | No-packet interval after which old buffered audio is cleared; default 0.5 |
| `retry_seconds` | Delay before reopening failed audio/socket resources; default 2 |
| `status_seconds` | Status log interval; default 5 |

The audio format is fixed: 48,000 Hz, stereo, signed little-endian 16-bit PCM. Each packet holds 240 frames (5 ms). There is no codec negotiation. Both endpoints must run the same protocol version.

`SSA1` wire format: 4-byte magic, unsigned 64-bit session ID, unsigned 64-bit sequence number (header integers in network byte order), then 960 bytes of PCM. Each process/session starts with a random ID. Sequence numbers detect missing, late and duplicate blocks. The receiver reorders packets within a bounded buffer, inserts silence for gaps, and drops excess backlog to avoid accumulating delay. No retransmission is attempted.

The peer IP/port filter prevents accidental cross-talk from another endpoint but is not authentication. Audio is unencrypted and unauthenticated; use a trusted local network. Never expose these UDP ports to the public internet.

A device disconnect reopens both audio directions. A network interruption alone does not normally restart the process: sending continues and reception resumes when valid packets return. A process restart is handled by the OS supervisor. A silent source still sends packets, so `receiving` is a network status, not an audio-level meter.
