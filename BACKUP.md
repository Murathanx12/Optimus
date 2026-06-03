# Brain backup

The engine is public; the **brain is private and gitignored** (`/brain/`,
`/raw/`, `/reports/`). That separation is deliberate — but it means the brain
does **not** travel with the engine repo and has **no backup by default**. If
this machine dies right now, the brain is gone. This is a data-loss risk that
exists today, not a Phase-2 concern.

## Cheap mitigation (do this now)

Snapshot `brain/` to a second, off-machine location as a timestamped zip:

```powershell
# one-off
python tools/backup_brain.py --dest "D:\backups"

# or set once, then run with no args
$env:OPTIMUS_BACKUP_DIR = "C:\Users\mrthn\OneDrive\optimus-brain-backups"
python tools/backup_brain.py
```

- The derived SQLite index (`index.db`) is skipped — markdown is source of
  truth. Restore by unzipping and calling `Store.reindex()`.
- Point `--dest` somewhere **off-machine and encrypted**: an encrypted drive, a
  synced OneDrive/Drive folder, or a separate **private** git repo. The brain
  holds the identity tier — never back it up to anywhere public.

### Alternative: a private brain repo

```powershell
cd brain
git init
git remote add origin <PRIVATE repo url>   # MUST be private
git add -A; git commit -m "brain snapshot"; git push -u origin main
```

Keep this entirely separate from the public engine repo — different remote,
different visibility. Do not add `brain/` to the engine's history.

## Phase 2 (the real version)

Automated, encrypted, incremental sync (the daemon snapshots after each
distill), with restore tested. Not built yet — the command above is the stopgap.
