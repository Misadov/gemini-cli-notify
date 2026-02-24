import ctypes
import psutil
import time
import datetime
import sys
import subprocess
import os
from plyer import notification

# --- Windows API Constants ---
STD_OUTPUT_HANDLE = -11

# --- Windows API Structures for Console Manipulation ---
class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short), 
                ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]

class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [("dwSize", COORD),
                ("dwCursorPosition", COORD),
                ("wAttributes", ctypes.c_ushort),
                ("srWindow", SMALL_RECT),
                ("dwMaximumWindowSize", COORD)]

# Load necessary Windows DLLs
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

def log(msg):
    """Utility function to print timestamped logs."""
    print(f"[{datetime.datetime.now()}] {msg}")

def is_window_active(hwnd):
    """
    Checks if the specified window is currently the active (focused) window.
    It also checks the foreground window's title to properly handle Windows Terminal tabs.
    """
    if not hwnd: return False
    
    foreground_hwnd = user32.GetForegroundWindow()
    
    # Direct match (e.g., legacy conhost.exe)
    if hwnd == foreground_hwnd:
        return not user32.IsIconic(hwnd) # Ensure it's not minimized
        
    # Check window title for Windows Terminal compatibility
    length = user32.GetWindowTextLengthW(foreground_hwnd)
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(foreground_hwnd, buff, length + 1)
    fg_title = buff.value.lower()
    
    # Check for known Gemini CLI title markers
    if ("gemini" in fg_title or 
        "◇" in fg_title or 
        "✦" in fg_title):
        return not user32.IsIconic(foreground_hwnd)
    
    return False

def show_notification(title, message, hwnd=None):
    """
    Displays a desktop notification.
    Suppresses the notification if the user is already looking at the active window.
    """
    # Do not notify if the user is currently focused on the app
    if hwnd and is_window_active(hwnd):
        return

    log(f"NOTIFICATION: {title} - {message}")
    try:
        notification.notify(
            title=title,
            message=message,
            app_name='Gemini CLI',
            timeout=5
        )
    except Exception as e:
        log(f"Notification Failed: {e}")

def read_console_buffer(pid):
    """
    Attaches to a given process's console to read its window title and recent screen buffer content.
    Returns: (window_title, console_content, console_hwnd)
    """
    # Free the current console to allow attaching to another
    kernel32.FreeConsole()
    
    if kernel32.AttachConsole(pid):
        # Retrieve the console window title
        title_buffer = ctypes.create_unicode_buffer(1024)
        kernel32.GetConsoleTitleW(title_buffer, 1024)
        window_title = title_buffer.value

        # Retrieve screen buffer info
        hStdOut = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        csbi = CONSOLE_SCREEN_BUFFER_INFO()
        
        # Get the window handle for duplicate tracking
        hwnd = kernel32.GetConsoleWindow()
        content = ""
        
        if kernel32.GetConsoleScreenBufferInfo(hStdOut, ctypes.byref(csbi)):
            width = csbi.dwSize.X
            height = csbi.dwSize.Y
            
            # Read a chunk from the bottom of the buffer
            read_len = 8000 
            
            start_idx = max(0, (width * height) - read_len)
            start_y = start_idx // width
            start_x = start_idx % width
            read_coord = COORD(start_x, start_y)
            buffer = ctypes.create_unicode_buffer(read_len)
            chars_read = ctypes.c_ulong(0)
            
            # Extract text from the target console
            if kernel32.ReadConsoleOutputCharacterW(hStdOut, buffer, read_len, read_coord, ctypes.byref(chars_read)):
                 content = buffer.value
        
        # Detach from target and re-attach to the original console
        kernel32.FreeConsole()
        kernel32.AttachConsole(-1)
        
        # Restore stdout/stderr mappings
        sys.stdout = open("CONOUT$", "w", encoding="utf-8")
        sys.stderr = open("CONOUT$", "w", encoding="utf-8")
        
        return window_title, content, hwnd
    else:
        # If attach fails, restore original console immediately
        kernel32.AttachConsole(-1)
        sys.stdout = open("CONOUT$", "w", encoding="utf-8")
        sys.stderr = open("CONOUT$", "w", encoding="utf-8")
        return None, None, None

print("Gemini Watchdog (Console API) Started...")
print("Monitoring MULTIPLE Gemini instances.")

# Dictionary to track confirmed active Gemini CLI targets
# Format: { PID: { 'state': LastState, 'hwnd': ConsoleHWND } }
targets = {} 

while True:
    try:
        # 1. Clean up processes that have terminated
        dead_pids = []
        for pid in targets:
            if not psutil.pid_exists(pid):
                log(f"Target PID {pid} died. Removing.")
                dead_pids.append(pid)
        for pid in dead_pids:
            del targets[pid]

        # 2. Identify potential candidate processes based on common shell/node executables
        candidates = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = proc.info['name'].lower()
                if name in ['node.exe', 'powershell.exe', 'pwsh.exe', 'cmd.exe']:
                    # Only add if not already tracked as a target
                    if proc.info['pid'] not in targets:
                        candidates.append(proc.info['pid'])
            except: 
                continue

        # Keep track of active window handles to avoid tracking duplicates (e.g., node inside powershell)
        tracked_hwnds = {info['hwnd'] for info in targets.values() if info['hwnd']}

        # 3. Analyze candidates to see if they belong to Gemini CLI
        for pid in candidates:
            if pid == os.getpid(): continue # Skip our own process
            try:
                title, content, hwnd = read_console_buffer(pid)
                
                # Skip if this console window is already being tracked
                if hwnd and hwnd in tracked_hwnds:
                    continue

                # Verify if the process title contains known Gemini markers
                title_lower = title.lower()
                if (title and (
                    "gemini" in title_lower or
                    "gemini-cli" in title_lower or
                    "dist\\index.js" in title_lower or
                    "◇" in title or
                    "✦" in title
                )):
                    # Mark candidate as a confirmed target
                    targets[pid] = { 'state': "Unknown", 'hwnd': hwnd }
                    tracked_hwnds.add(hwnd)
            except: 
                pass

        # 4. Monitor state changes of confirmed targets
        for pid in list(targets.keys()):
            try:
                title, content, hwnd = read_console_buffer(pid)
                if title is None: continue 
                
                last_state = targets[pid]['state']
                
                if content:
                    clean_content = content.strip()
                    
                    # Check for "Awaiting Input" state
                    if ("Interactive shell awaiting input" in clean_content or 
                        "Action Required" in clean_content or 
                        "Press tab to focus shell" in clean_content):
                        
                        if last_state != "AwaitingInput":
                            show_notification("Gemini CLI", f"Action Required (PID {pid})! ✋", hwnd)
                            targets[pid]['state'] = "AwaitingInput"
                    
                    # Check for rate limits or high demand
                    elif ("Keep trying" in clean_content and "Stop" in clean_content):
                         if last_state != "HighDemand":
                            show_notification("Gemini CLI", f"Task Failed - High Demand (PID {pid}) ⚠️", hwnd)
                            targets[pid]['state'] = "HighDemand"

                    # Check if the CLI is actively working
                    elif "Working" in title or "✦" in title:
                        if last_state != "Working":
                            targets[pid]['state'] = "Working"

                    # Check if the CLI finished its task and became ready
                    elif ("Ready" in title or "◇" in title):
                        if last_state == "Working" or last_state == "AwaitingInput":
                            show_notification("Gemini CLI", f"Task Finished (PID {pid}) ✅", hwnd)
                            targets[pid]['state'] = "Ready"
            
            except Exception as e:
                log(f"Error checking PID {pid}: {e}")

    except Exception as e:
        log(f"Loop Error: {e}")

    # Polling delay
    time.sleep(2)
