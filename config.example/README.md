# config.example

Runtime credentials are **not** in this repo. Each host supplies its own:

| file | used by | contents |
|---|---|---|
| `vbottoken.txt` | `voice/gdiscord.py` | Discord bot token for Greg Local |
| `lmtoken.txt` | `voice/gdiscord.py` | local model API token |

Both are read from the process working directory. `.gitignore` already excludes them.
Endpoint/secret overrides go in `.env` — see `.env.example`.
