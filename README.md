# Battlezone Workshop Uploader

A desktop GUI for creating, updating, and validating Steam Workshop mods for **Battlezone 98 Redux**.

This tool is built around a folder-driven Workshop workflow:
- auto-detect SteamCMD and reuse a cached Steam login when available
- open or create a local upload profile by selecting a content folder
- load the complete set of owned Workshop items and explicitly link an existing item when needed
- scan the folder for common Battlezone content issues and review what changed since the last publish
- publish through SteamCMD with adaptive Steam Guard/mobile-approval handling and expandable diagnostics

## Release Builds

Download the latest platform archive from the [Releases](https://github.com/GrizzlyOne95/Battlezone98Redux_WorkshopUploader/releases) page.

Executable names are intentionally stable and versionless:

- Windows: `BZWorkshopUploader.exe`
- Linux/macOS: `BZWorkshopUploader`

Release archives carry the version and platform, for example:

- `Battlezone98Redux_WorkshopUploader-v1.6-windows.zip`
- `Battlezone98Redux_WorkshopUploader-v1.6-linux.tar.gz`
- `Battlezone98Redux_WorkshopUploader-v1.6-macos.tar.gz`

Official Windows builds use the shared **Battlezone Modding Tools** product identity:

```text
FileDescription: Battlezone Workshop Uploader
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZWorkshopUploader.exe
```

`FileVersion` and `ProductVersion` are derived from the release tag. Non-release CI builds use neutral `0.0.0` file metadata.

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

1. Launch the uploader. SteamCMD, cached Steam authentication, and the Workshop owner are detected automatically when possible.
2. Select a content folder. Its **Local Upload Profile** opens automatically, or a new one is created for that folder.
3. To update an existing item, choose it from **Your Workshop Items** and click **USE ITEM** or **LOAD ITEM**. Leave the profile unlinked to create a new item.
4. Fill in preview, title, description, visibility, tags, and change note in the **Workshop Item Editor**.
5. Review **Readiness**. Clean content stays compact; warnings and fixable/blocking issues expand automatically.
6. Click `REVIEW AND PUBLISH`. Steam Guard fields or mobile-approval prompts appear only if Steam requires them.
7. Use **SETUP / ADVANCED** or **SHOW LOG** only when manual setup or diagnostics are needed.

## Main Features

### Local Upload Profiles

- One saved local upload profile per content folder under `profiles/`
- Folder selection automatically opens or creates the corresponding profile
- Automatic profile autosave while editing
- Persistent Workshop-item association by local content folder
- Last publish timestamp and changed-file tracking

### Your Workshop Items

- Automatically refresh the owner's Workshop library when identity/API access is available
- Enumerate all owned items across Steam API pages instead of stopping at the first page
- Explicitly link the current upload profile to a selected Workshop item
- Load Workshop details such as title, description, visibility, preview, and tags into the editor

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

- Automatic SteamCMD discovery with manual Browse/Auto-DL fallback
- Cached SteamCMD login detection with manual sign-in only when needed
- Adaptive Steam Guard code and Steam mobile-approval states
- QR account-verification helper
- SteamCMD VDF generation
- Expandable Steam/upload diagnostics rather than an always-visible raw log
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
- `project_store.py`: saved local upload-profile persistence
- `mod_scanner.py`: content scanning and validation
- `memory_analyzer.py`: texture/orphan analysis
- `workshop_backend.py`: SteamCMD and Workshop API interactions
- `upload_preflight.py`: upload validation and VDF writing
- `profiles/`: saved local upload-profile state

## Notes

- The app is primarily intended for Windows-based Battlezone modding workflows.
- Steam Web API features require an API key from `https://steamcommunity.com/dev/apikey`.
- Native tag submission remains experimental and may depend on Steam-side account state.

## License

MIT. See [LICENSE](LICENSE).
