# Battlezone 98 Redux Workshop Uploader

A dedicated GUI tool for uploading and managing Steam Workshop mods for **Battlezone 98 Redux**. This tool streamlines the upload process by automating VDF creation, handling SteamCMD execution, and performing extensive safety checks on mod files to prevent common crashes and bugs.

## Features

### 🚀 Streamlined Uploading
*   **SteamCMD Integration**: Wraps SteamCMD command-line arguments into a user-friendly interface.
*   **Auto-VDF Generation**: Automatically generates the required `.vdf` configuration file for Steam Workshop uploads.
*   **2FA Support**: Built-in support for Steam Guard codes during the login process.
*   **Preview Image Handling**: Automatically detects if preview images exceed the 1MB limit and offers to resize/compress them.

### 🛡️ Mod Safety & Validation
Before uploading, the tool scans your content folder for common errors that cause game crashes or bugs:
*   **ODF Validation**:
    *   Checks for unrecognized headers against `odfHeaderList.txt`.
    *   Validates parameters against `bzrODFparams.txt`.
    *   **Crash Prevention**: Detects specific configurations known to crash the game (e.g., `weaponMask=00000`, Hardpoints in `[CraftClass]`, Magnet `range=0`).
*   **File Format Checks**:
    *   **BMP**: Ensures preview images are 24-bit and do not contain color space info (which crashes the game).
    *   **TRN**: Validates and fixes line endings (must be CRLF) to prevent terrain loading issues.
    *   **Materials**: Scans for duplicate material names across files.
*   **Structure Validation**: Ensures the mod folder contains a valid `.ini` file and essential map files (`.hg2`, `.trn`, `.mat`, etc.) based on the map type.

### 🔧 Mod Management
*   **Manage Tab**: View your existing Workshop items.
*   **Update Workflow**: Select an existing mod to auto-populate fields for an update.
*   **Logs**: Built-in log viewer for SteamCMD build and transfer logs to troubleshoot failed uploads.

## Prerequisites

*   **Python 3.x**
*   **SteamCMD**: You can point the tool to an existing installation or download it separately.
*   **Steam Account**: You must own Battlezone 98 Redux on Steam to upload to its Workshop.

## Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/YourUsername/Battlezone98Redux_WorkshopUploader.git
    cd Battlezone98Redux_WorkshopUploader
    ```

2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3.  (Optional) Ensure you have the validation lists in the same directory or resource path:
    *   `odfHeaderList.txt`
    *   `bzrODFparams.txt`

## Usage

1.  Run the script:
    ```bash
    python uploader.py
    ```

2.  **Configuration**:
    *   Set the path to `steamcmd.exe`.
    *   Enter your Steam Username and Password.
    *   (Optional) Enter a Steam Web API Key to use the "Manage" tab features.

3.  **Uploading a Mod**:
    *   **Content Folder**: Browse to the folder containing your mod files.
    *   **Preview Image**: Select a JPG/PNG image (will be converted/resized if needed).
    *   **Metadata**: Fill in Title, Description, Visibility, and Change Notes.
    *   Click **UPLOAD TO STEAM WORKSHOP**.

4.  **Safety Checks**:
    *   If issues are found (e.g., invalid ODF headers, wrong BMP format), a warning window will appear.
    *   You can choose to **Open** the offending file, **Cancel** the upload, or **Ignore & Continue**.

## Configuration Files

The tool uses external text files to define valid ODF headers and parameters. These should be placed in the same directory as the script (or the `_internal` folder if frozen):

*   `odfHeaderList.txt`: A list of valid ODF class headers (e.g., `[GameObjectClass]`, `[CraftClass]`).
*   `bzrODFparams.txt`: A list of valid parameters for specific ODF classes.

## Known Issues & Limitations

*   **2FA**: You may need to check the console window spawned by SteamCMD to enter your 2FA code if the UI field doesn't pass it correctly in your specific environment, though the UI field is designed to handle it.
*   **Linux**: While Python is cross-platform, this tool is primarily tested on Windows due to the game's ecosystem.

## Credits

*   Built with Python and Tkinter.
*   Styled to match the Battlezone Mod Engine.

---

*This tool is a community creation and is not officially affiliated with Rebellion.*