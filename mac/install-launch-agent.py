#!/usr/bin/env python3
"""Install a per-user login agent after configuring and testing the endpoint."""
import argparse
import pathlib
import plistlib
parser = argparse.ArgumentParser()
parser.add_argument('--admin', action='store_true')
args = parser.parse_args()
root = pathlib.Path(__file__).resolve().parents[1]
python = root / '.venv/bin/python'
config = root / 'config.json'
if not python.exists() or (not args.admin and not config.exists()):
    raise SystemExit('Run scripts/setup.sh and create config.json first.')
logs = pathlib.Path.home() / 'Library/Logs/SkiStreamAudio'
logs.mkdir(parents=True, exist_ok=True)
agent = pathlib.Path.home() / 'Library/LaunchAgents/local.ski-stream-audio.plist'
agent.parent.mkdir(parents=True, exist_ok=True)
if agent.exists():
    raise SystemExit(f'{agent} already exists; unload and remove it before reinstalling.')
agent.write_bytes(plistlib.dumps(dict(
    Label='local.ski-stream-audio',
    ProgramArguments=([str(python), str(root/'admin.py'), '--data-dir', str(root/'local'), '--port', '8081']
                      if args.admin else [str(python), str(root/'audio_link.py'), '--config', str(config)]),
    WorkingDirectory=str(root), RunAtLoad=True, KeepAlive=True, ThrottleInterval=5,
    StandardOutPath=str(logs/'stdout.log'), StandardErrorPath=str(logs/'stderr.log'))))
print(f'Created {agent}. Follow mac/README.md to load it.')
