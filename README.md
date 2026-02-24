# Gemini CLI Watchdog

A lightweight background process monitor that tracks multiple instances of the Gemini CLI running in Windows console environments. It reads console output buffers and window titles to provide system notifications for important state changes, ensuring developers are alerted when tasks complete or require attention without needing to actively watch the terminal.

## Features

*   **Multi-Instance Support:** Simultaneously monitors multiple running instances of the Gemini CLI, regardless of whether they are executed via Node.js directly or within PowerShell/Command Prompt.
*   **Console Buffer Inspection:** Uses the Windows Win32 API to temporarily attach to background console processes and parse their screen buffers and window titles.
*   **State Detection:** Identifies distinct application states based on terminal output and title markers, including:
    *   Task Started ("Working")
    *   Task Finished ("Ready")
    *   Action Required (User input needed)
    *   High Demand / Rate Limiting
*   **Smart Notifications:** Triggers Windows desktop notifications for significant state changes.
*   **Focus Awareness:** Suppresses notifications if the specific console window (or Windows Terminal tab) running the active CLI instance is currently focused, preventing redundant alerts.
*   **Deduplication:** Tracks console window handles (HWND) to prevent duplicate monitoring of the same session (e.g., distinguishing between the host shell and the child Node process).

## Technical Implementation

The application relies on the `ctypes` library to interface with the Windows API (`kernel32.dll` and `user32.dll`). It utilizes the `AttachConsole` and `ReadConsoleOutputCharacterW` functions to access the internal text buffer of target processes. 

Process discovery is handled via `psutil`, scanning for common shell and runtime executables before verifying them against known application markers. Notifications are dispatched using the `plyer` library.

## Requirements

*   Windows Operating System
*   Python 3.x
*   Dependencies: `psutil`, `plyer`

## Usage

Ensure the required dependencies are installed:

```bash
pip install psutil plyer
```

Run the watchdog script in the background:

```bash
python watchdog-console.py
```

The script will run continuously, automatically discovering and attaching to any new or existing Gemini CLI instances.
