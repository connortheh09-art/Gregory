# Import manifest — live capture 2026-10-19

Captured from `C:\Users\Conman\Downloads\openclaw` on CONNORSCOMPUTER (deployed working copy).
No behavior changes; only credentials and machine-specific endpoints parameterized.

| repo path | source path | sha256 (original) | bytes | mtime |
|---|---|---|---|---|
| `bridge/gmod_bridge.py` | `C:\Users\Conman\Downloads\openclaw\gmod_bridge.py` | `aac1b57597f1946d…` | 43,261 | 2026-10-15T00:01:08 |
| `bridge/keyloop.py` | `C:\Users\Conman\Downloads\openclaw\keyloop.py` | `71a618b8bfd0d3ac…` | 17,923 | 2026-10-14T02:33:44 |
| `bridge/keytype.py` | `C:\Users\Conman\Downloads\openclaw\keytype.py` | `0f58b7d60823044b…` | 1,909 | 2026-10-14T20:11:02 |
| `bridge/respawn_cam.py` | `C:\Users\Conman\Downloads\openclaw\respawn_cam.py` | `e586f4849b9ee561…` | 3,551 | 2026-10-14T00:17:04 |
| `bridge/vision_loop.py` | `C:\Users\Conman\Downloads\openclaw\vision_loop.py` | `b56892995bb0b364…` | 10,896 | 2026-10-13T22:14:21 |
| `bridge/visionctl.py` | `C:\Users\Conman\Downloads\openclaw\visionctl.py` | `cedf39afcecdb14d…` | 4,115 | 2026-10-13T22:12:27 |
| `bridge/vision_supervisor.py` | `C:\Users\Conman\Downloads\openclaw\vision_supervisor.py` | `849d34297430cdd7…` | 1,317 | 2026-10-13T21:41:59 |
| `bridge/gbrain.py` | `C:\Users\Conman\Downloads\openclaw\gbrain.py` | `9fd1313431210b84…` | 9,466 | 2026-10-06T23:49:19 |
| `lua/_gmod_bridge.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_gmod_bridge.lua` | `0845ac577dfac8b8…` | 5,303 | 2026-10-14T19:27:42 |
| `lua/_gmod_chat_sv.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_gmod_chat_sv.lua` | `a9259118a7d4ab8e…` | 1,408 | 2026-10-14T19:27:46 |
| `lua/_gb3.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_gb3.lua` | `f3413d49d5b21630…` | 5,479 | 2026-10-14T19:43:04 |
| `lua/_cc4.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_cc4.lua` | `83c0fad2c6f86ca6…` | 10,235 | 2026-10-14T21:52:03 |
| `lua/_cs7.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_cs7.lua` | `e8eb3a7b1628a3f0…` | 6,246 | 2026-10-14T22:01:57 |
| `playercore/gregctl.py` | `C:\Users\Conman\Downloads\openclaw\greg\gregctl.py` | `9e8d26668a4a5d65…` | 7,160 | 2026-10-13T23:54:44 |
| `playercore/gregman.py` | `C:\Users\Conman\Downloads\openclaw\greg\gregman.py` | `33da4ddb9c71754f…` | 8,299 | 2026-10-13T03:23:31 |
| `playercore/watchdog.py` | `C:\Users\Conman\Downloads\openclaw\greg\watchdog.py` | `4501ca231290c970…` | 2,181 | 2026-10-13T03:23:32 |
| `voice/gdiscord.py` | `C:\Users\Conman\Downloads\openclaw\greg\gdiscord.py` | `cb8c38e1974bb845…` | 32,964 | 2026-10-14T02:33:44 |

## Scrub log

- `bridge/gbrain.py`: hardcoded LM Studio token → `LM_API_TOKEN` env (was a live secret).
- `bridge/respawn_cam.py`: push URL → `PUSH_URL` env.
- `bridge/vision_loop.py`: context URL default → `CONTEXT_URL` env.
- `playercore/gregman.py`: `CTX_URL`/`BRAIN_URL` → env.
- `voice/gdiscord.py`: three VPS endpoints → env.
- Bot tokens still read from `vbottoken.txt` / `lmtoken.txt` (see `config.example/`), never committed.

## Not imported

Runtime state, logs, `*.bak-*` iterations, `.txt` token files, generated media, and unrelated tooling
(probes, benchmarks, image-gen helpers) were left on the host.
