# Battlezone 98 Redux Workshop Uploader

A desktop GUI for creating, updating, and validating Steam Workshop mods for **Battlezone 98 Redux**.

This tool is built around a project-centric workflow:
- pair a local mod folder to a Workshop item
- scan the folder for common Battlezone content issues
- review what changed since the last publish
- publish through SteamCMD with better logging and recovery than the legacy uploader

## Why Use This Instead Of The Old BZR Uploader?

- Uses SteamCMD, so failures are easier to diagnose.
- Does not force every upload public.
- Keeps local project state tied to Workshop IDs.
- Warns about common mod-breaking issues without hard-blocking every workflow.
- Can apply one-click fixes for several common file problems.

## Current Workflow

Run:

```bash
python uploader.py
```

Then use the workspace like this:

1. Configure `steamcmd.exe`, login method, and optional Steam Web API key.
2. Select or create a local mod project folder.
3. Pair the project to an existing Workshop item from the **Workshop Library** panel, or leave it unpaired to create a new item.
4. Fill in preview, title, description, visibility, tags, and change note.
5. Review findings in the **Readiness** panel.
6. Open files, apply selected fixes, apply all one-click fixes, or inspect changed files since the last publish snapshot.
7. Click `REVIEW AND PUBLISH`.

## Main Features

### Project Workspace

- Saved local projects under `profiles/`
- Automatic project autosave while editing
- Persistent Workshop pairing by local mod folder
- Last publish timestamp and changed-file tracking

### Workshop Library

- Load your Workshop items through the Steam Web API
- Pair the current local project to a selected Workshop item
- Import Workshop details such as title, description, visibility, preview, and tags into the workspace

### Safety And Validation

- ODF header and field validation using `odfHeaderList.txt` and `bzrODFparams.txt`
- Missing asset detection for `.odf` and `.material` references
- TRN duplicate `[Size]` detection
- TRN line-ending validation and correction
- Legacy `.map` file detection and cleanup
- Structure validation for required Battlezone content files

### Readiness Actions

- Open the selected file directly from a finding
- Apply selected one-click fixes
- Apply all available one-click fixes
- Inspect added, modified, and removed files since the last publish snapshot

### Publishing

- SteamCMD VDF generation
- Cached credential mode or manual login
- QR login helper
- Upload log inspection
- Experimental Workshop tag updates after successful publish

### Analysis

- Memory and VRAM estimate report
- Non-DDS texture warnings
- Orphan-file detection

## Requirements

- Python 3.x
- Dependencies from `requirements.txt`
- SteamCMD
- A Steam account that owns Battlezone 98 Redux

Install dependencies:

```bash
pip install -r requirements.txt
```

## Files Used By The App

- `uploader.py`: main application
- `project_store.py`: saved project persistence
- `mod_scanner.py`: content scanning and validation
- `memory_analyzer.py`: texture/orphan analysis
- `workshop_backend.py`: SteamCMD and Workshop API interactions
- `upload_preflight.py`: upload validation and VDF writing
- `profiles/`: saved local project state

## Notes

- The app is primarily intended for Windows-based Battlezone modding workflows.
- Steam Web API features require an API key from `https://steamcommunity.com/dev/apikey`.
- Native tag submission remains experimental and may depend on Steam-side account state.

## License

MIT. See [LICENSE](/C:/Users/istuart/Documents/GIT/Battlezone98Redux_WorkshopUploader/LICENSE).
