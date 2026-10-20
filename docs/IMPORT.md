# Import manifest — live capture 2026-10-19

Source: `C:\Users\Conman\Downloads\openclaw` on CONNORSCOMPUTER (the rig's working copy, not the old-PC deployment).

Hashes are of the **original** files as captured, before scrubbing.

| repo path | source path | sha256 | bytes | mtime (UTC) |
|---|---|---|---|---|
| `bridge/gmod_bridge.py` | `C:\Users\Conman\Downloads\openclaw\gmod_bridge.py` | `aac1b57597f1946d4d5d3fa9fe4ed08a28ca6f29b0dfb451bd89b221bdad34c7` | 43,261 | 2026-10-15 00:01:08Z |
| `bridge/keyloop.py` | `C:\Users\Conman\Downloads\openclaw\keyloop.py` | `71a618b8bfd0d3ac8c5c492a9a2c3155cfee7d85719192b3e8451ca95a013d56` | 17,923 | 2026-10-14 02:33:44Z |
| `bridge/keytype.py` | `C:\Users\Conman\Downloads\openclaw\keytype.py` | `0f58b7d60823044b808cd0dd7ee28bdbba15e5b2f7c809428b3ccbd74e963952` | 1,909 | 2026-10-14 20:11:02Z |
| `bridge/respawn_cam.py` | `C:\Users\Conman\Downloads\openclaw\respawn_cam.py` | `e586f4849b9ee561299c8e37d4aaabf9118f167689f3b1b9b78a92e32dee4583` | 3,551 | 2026-10-14 00:17:04Z |
| `bridge/vision_loop.py` | `C:\Users\Conman\Downloads\openclaw\vision_loop.py` | `b56892995bb0b36422d8a9a0375a95dc5c9e8ec03b23adfb1ee7fd746b8965a1` | 10,896 | 2026-10-13 22:14:21Z |
| `bridge/visionctl.py` | `C:\Users\Conman\Downloads\openclaw\visionctl.py` | `cedf39afcecdb14d38efddb2ebd214cdf4fa48e80a237f1d8de30dd9e4e8fc5b` | 4,115 | 2026-10-13 22:12:27Z |
| `bridge/vision_supervisor.py` | `C:\Users\Conman\Downloads\openclaw\vision_supervisor.py` | `849d34297430cdd70e263dd1ab377849acc844a03ce85b00f4d4f2deab516e2b` | 1,317 | 2026-10-13 21:41:59Z |
| `bridge/gbrain.py` | `C:\Users\Conman\Downloads\openclaw\gbrain.py` | `9fd1313431210b84d7e1409818238e0a2181d21df22bf144a211e32cf0983a4f` | 9,466 | 2026-10-06 23:49:19Z |
| `lua/_gmod_bridge.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_gmod_bridge.lua` | `0845ac577dfac8b80d91d40f192581afa242032471fdcc2ac5a296db2bb40518` | 5,303 | 2026-10-14 19:27:42Z |
| `lua/_gmod_chat_sv.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_gmod_chat_sv.lua` | `a9259118a7d4ab8e6df331232bfbeb80649365e9c65c378214343981e7475697` | 1,408 | 2026-10-14 19:27:46Z |
| `lua/_gb3.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_gb3.lua` | `f3413d49d5b216303710a261a43386931dec96a93a9b42463ac9c18860261ef8` | 5,479 | 2026-10-14 19:43:04Z |
| `lua/_cc4.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_cc4.lua` | `83c0fad2c6f86ca6e3beaf5da1a58b53e621275c523933a7d6067ee95ff26b22` | 10,235 | 2026-10-14 21:52:03Z |
| `lua/_cs7.lua` | `C:\Users\Conman\Downloads\openclaw\lua\_cs7.lua` | `e8eb3a7b1628a3f04034a24be29aa9a23964ad69b27f2a0f53d80fffd07647a6` | 6,246 | 2026-10-14 22:01:57Z |
| `playercore/gregctl.py` | `C:\Users\Conman\Downloads\openclaw\greg\gregctl.py` | `9e8d26668a4a5d65e4f886799ea647dcd3331fea93074ce4f92799346970e8d1` | 7,160 | 2026-10-13 23:54:44Z |
| `playercore/gregman.py` | `C:\Users\Conman\Downloads\openclaw\greg\gregman.py` | `33da4ddb9c71754fe323723bc7e94b36652a8d87164f223899e981f981693b6e` | 8,299 | 2026-10-13 03:23:31Z |
| `playercore/watchdog.py` | `C:\Users\Conman\Downloads\openclaw\greg\watchdog.py` | `4501ca231290c9709f67078f89199369824e39178cf5060fe9c6c97b80d0f87a` | 2,181 | 2026-10-13 03:23:32Z |
| `voice/gdiscord.py` | `C:\Users\Conman\Downloads\openclaw\greg\gdiscord.py` | `cb8c38e1974bb845e67b9cc37d5d84a57f12c0c6bbad3a725e5ca92147e6dfcd` | 32,964 | 2026-10-14 02:33:44Z |

## Known scope gaps (raised in review)

- This capture is the **rig** tree. The last-verified playercore deployment lives on the old PC
  (KELLENWORKSPACE); `greg_playercore.py` and `greg_goal_lifecycle.py` are **not** in this snapshot.
  Treat this branch as the rig baseline, not the canonical deployed revision.
- `bridge/respawn_cam.py` is **Minecraft-era** tooling (RCON/spectate), not GMod. Kept for completeness,
  documented here so it isn't mistaken for part of the GMod player loop.
- `playercore/gregctl.py` and `playercore/watchdog.py` still reference the original absolute install
  directory and PS1 helpers that were not imported; `gregman.py` expects `gdiscord.py` alongside it.

## Scrub log

- `bridge/gbrain.py`: hardcoded LM Studio token → `LM_API_TOKEN` env (was a live secret).
- `bridge/respawn_cam.py`: hardcoded RCON password → `RCON_PASS` env; RCON host/port and log path → env.
- `bridge/respawn_cam.py`: push URL → `PUSH_URL` env.
- `bridge/vision_loop.py`: context URL default → `CONTEXT_URL` env.
- `playercore/gregman.py`: `CTX_URL`/`BRAIN_URL` → env.
- `voice/gdiscord.py`: three VPS endpoints → env.
- Bot tokens are read from `vbottoken.txt` / `lmtoken.txt` at runtime — see `config.example/`.

## Not imported

Runtime state, logs, `*.bak-*` iterations, `.txt` token files, generated media, and unrelated tooling.
