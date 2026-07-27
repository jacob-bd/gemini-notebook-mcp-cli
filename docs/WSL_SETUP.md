# WSL2 Authentication Guide

This guide explains how to authenticate with Gemini Notebook (formerly Google NotebookLM) MCP when running in Windows Subsystem for Linux (WSL2).

## The Problem

On WSL2, launching GUI applications like Chrome can cause terminal display corruption:
- Screen goes black
- Terminal becomes unresponsive
- Requires terminal restart

This happens because WSL2 uses a virtual machine, and GUI apps crossing the Windows/Linux boundary can interfere with the terminal session.

## The Solution

Gemini Notebook MCP now includes WSL2-aware authentication that:
1. Launches Windows Chrome from your WSL terminal
2. Waits for Chrome DevTools Protocol to be ready
3. Extracts cookies over the WSL-Windows network bridge
4. Closes Chrome automatically

## Security Considerations

### Chrome Remote Debugging Address

Chrome (v136+) ignores `--remote-debugging-address=0.0.0.0` and binds the
DevTools Protocol to `127.0.0.1` only. Since WSL2 uses a virtual network
bridge, a **netsh port proxy** is required to forward traffic from the WSL
virtual network to Chrome's localhost listener.

The `--wsl` flag launches Chrome on port **9223** (localhost) and connects
via port **9222** (the proxy port accessible from WSL).

**One-time setup** (run in an elevated PowerShell):
```powershell
netsh interface portproxy add v4tov4 listenport=9222 listenaddress=0.0.0.0 connectport=9223 connectaddress=127.0.0.1
```

**Mitigations in place:**
- **Windows Firewall**: Only connections from `LocalSubnet` (WSL virtual network)
  are allowed to reach port 9222
- **Port proxy**: Only forwards to localhost:9223; Chrome is never exposed
  directly on the network
- **Temporary profiles**: Each Chrome instance uses a fresh, isolated profile
  on the Windows filesystem that is cleaned up after authentication
- **Short-lived**: Remote debugging is only active during the explicit `nlm login --wsl`
  command and terminated immediately after
- **No external exposure**: The Windows Firewall rule prevents connections from
  external network hosts

If you have concerns about this setup, you can use manual mode instead:
```bash
nlm login --manual --file /path/to/cookies.txt
```

## Quick Start

### 1. Ensure Chrome is installed on Windows

The `--wsl` flag requires Google Chrome installed on the **Windows** side (not just WSL).

Download: https://www.google.com/chrome/

**Important:** Before running `nlm login --wsl`, **close all Chrome windows** on Windows. Chrome's remote debugging requires a fresh instance.

### 2. Set up the port proxy (one-time)

Chrome (v136+) only binds its debug port to localhost, so a Windows port proxy
is needed to make it reachable from WSL.

Run in an **elevated PowerShell** (Run as Administrator):

```powershell
netsh interface portproxy add v4tov4 listenport=9222 listenaddress=0.0.0.0 connectport=9223 connectaddress=127.0.0.1
```

This persists across reboots. Verify with:
```powershell
netsh interface portproxy show v4tov4
```

### 3. Authenticate

```bash
nlm login --wsl
```

This will:
- Detect the WSL networking mode and Windows host address
- **Check Windows Firewall setup** (prompts with instructions)
- Launch Chrome on Windows on port 9223 with remote debugging
- Connect via the port proxy on port 9222
- Open Gemini Notebook in Chrome
- Wait for you to log in
- Extract cookies automatically
- Close Chrome
- Save credentials to your profile

### 4. Verify

```bash
nlm login --check
nlm notebook list
```

## How It Works

When you run `nlm login --wsl`:

```
WSL Terminal
    ↓  detects networking mode with wslinfo
    ↓  uses the default gateway (NAT) or 127.0.0.1 (mirrored)
    ↓  launches /mnt/c/Program Files/Google/Chrome/Application/chrome.exe
Windows Chrome
    ↓  starts on 127.0.0.1:9223 (Windows side, localhost only)
netsh portproxy
    ↓  forwards 0.0.0.0:9222 → 127.0.0.1:9223
WSL Auth Script
    ↓  connects to the Windows host on port 9222 (via port proxy)
    ↓  opens notebook.google.com tab
    ↓  waits for login
    ↓  extracts cookies via CDP
    ↓  terminates Chrome process
```

## Troubleshooting

### Chrome opens but "Chrome did not start within 30 seconds"

This usually means Chrome was already running when you launched it. Chrome's remote debugging only works with a fresh instance.

**Solution:**
1. **Close all Chrome windows** on Windows (check system tray too)
2. Retry `nlm login --wsl`

### "Chrome did not start within 30 seconds" (firewall-related)

If you pressed Enter after creating the firewall rule but Chrome still won't connect:

1. **Verify the rule was created:**
   ```powershell
   # In Windows PowerShell
   Get-NetFirewallRule -DisplayName "NotebookLM-CDP-9222"
   ```

2. **Close any running Chrome instances** and retry `nlm login --wsl`

3. **Or use manual mode** (no Chrome launch needed):
   ```bash
   # Export cookies from Chrome using Cookie-Editor extension
   nlm login --manual --file /mnt/c/Users/<username>/Downloads/cookies.txt
   ```

### "Chrome not found on Windows side"

Chrome must be installed in a standard location:

- `C:\Program Files\Google\Chrome\Application\chrome.exe`
- `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`

If installed elsewhere, you have two options:

**Option A:** Create a symlink in WSL:
```bash
sudo ln -s "/mnt/c/path/to/your/chrome.exe" /usr/local/bin/chrome.exe
```

**Option B:** Use manual mode with cookie file:
```bash
# Export cookies from Chrome using Cookie-Editor extension
# Save to /mnt/c/Users/<username>/Downloads/cookies.txt
nlm login --manual --file /mnt/c/Users/<username>/Downloads/cookies.txt
```

### "Could not determine Windows host IP"

Check your WSL network configuration:
```bash
cat /etc/resolv.conf
grep nameserver /etc/resolv.conf
```

In NAT mode, you should see an IP like `172.20.x.x`. In mirrored mode, the Windows host is
available at `127.0.0.1`.

**Workaround:**
```bash
# Find the Windows host address manually
if [ "$(wslinfo --networking-mode 2>/dev/null)" = "mirrored" ]; then
    WINDOWS_IP=127.0.0.1
else
    WINDOWS_IP=$(ip route show default | awk '{print $3; exit}')
fi
nlm login --cdp-url "http://${WINDOWS_IP}:9222"
```

### "Chrome did not start within 30 seconds"

Sometimes Windows firewall or antivirus blocks the connection.

**Solutions:**
1. Check Windows Defender Firewall allows Chrome remote debugging
2. Try launching Chrome first, then connecting:
   ```powershell
   # In Windows PowerShell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
   ```
   ```bash
   # In WSL (wait a few seconds first)
   if [ "$(wslinfo --networking-mode 2>/dev/null)" = "mirrored" ]; then
       WINDOWS_IP=127.0.0.1
   else
       WINDOWS_IP=$(ip route show default | awk '{print $3; exit}')
   fi
   nlm login --cdp-url "http://${WINDOWS_IP}:9222"
   ```

### Terminal still goes black

If `--wsl` still causes issues, use the fully manual approach:

1. Export cookies via Cookie-Editor extension in Windows Chrome
2. Save to a file accessible from WSL
3. Run: `nlm login --manual --file /path/to/cookies.txt`

## WSL vs Native Linux

| Feature | Native Linux | WSL2 |
|---------|------------|------|
| Chrome launch | Direct GUI | Cross-boundary |
| Terminal safety | ✅ Safe | ⚠️ Use `--wsl` flag |
| Cookie extraction | CDP | CDP over network |
| Profile persistence | ✅ Yes | ✅ Yes |

## Advanced: Custom Chrome Path

If Chrome is installed in a non-standard location:

```bash
# Set environment variable in WSL
export NLM_CHROME_PATH="/mnt/c/Custom/Path/Chrome/Application/chrome.exe"
nlm login --wsl
```

Or create a wrapper script:

```bash
#!/bin/bash
# ~/.local/bin/nlm-wsl-login.sh

# Launch Chrome manually
/mnt/c/Custom/Path/Chrome/Application/chrome.exe --remote-debugging-port=9222 &
CHROME_PID=$!

# Wait for startup
sleep 3

# Get the Windows host address
if [ "$(wslinfo --networking-mode 2>/dev/null)" = "mirrored" ]; then
    WINDOWS_IP=127.0.0.1
else
    WINDOWS_IP=$(ip route show default | awk '{print $3; exit}')
fi

# Login via CDP
nlm login --cdp-url "http://${WINDOWS_IP}:9222"

# Cleanup
kill $CHROME_PID
```

## Related Commands

- `nlm doctor` - Diagnose WSL2 setup
- `nlm login --check` - Verify stored credentials
- `nlm login --manual` - Import cookies from file

## See Also

- [Authentication Guide](./AUTHENTICATION.md) - General auth documentation
- [CLI Guide](./CLI_GUIDE.md) - Full CLI reference
