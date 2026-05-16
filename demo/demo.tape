# VHS tape for regenerating the Vidimus demo GIF.
#
# VHS is a tool by Charm (https://github.com/charmbracelet/vhs) that turns
# a .tape script into a reproducible terminal recording. To regenerate the
# demo GIF:
#
#     brew install vhs               # or: go install github.com/charmbracelet/vhs@latest
#     vhs demo/demo.tape             # outputs demo/demo.gif
#
# Commit the resulting demo.gif and reference it in README.md.

Output demo/demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1200
Set Height 700
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms
Set PlaybackSpeed 1.0

# Setup (hidden)
Hide
Type "cd /tmp && rm -rf vidimus-demo && mkdir vidimus-demo && cd vidimus-demo"
Enter
Type "python -m venv .venv && source .venv/bin/activate"
Enter
Sleep 500ms
Type "pip install -q vidimus 2>&1 | tail -1"
Enter
Sleep 1s
Type "clear"
Enter
Show

# The actual demo
Type "# Vidimus — instrument any agent, attest its behavior, verify offline"
Enter
Sleep 1s

Type "pip install vidimus"
Sleep 500ms
Enter
Sleep 2s

Type "python examples/basic_agent.py"
Sleep 500ms
Enter
Sleep 6s

Type "# The attestation is portable. Anyone with the public key can verify it."
Enter
Sleep 1500ms

Type "vidimus verify attestation.json"
Sleep 500ms
Enter
Sleep 3s

Type "# Now let's tamper with it and try again..."
Enter
Sleep 1500ms

Type `sed -i 's/"trace_count": 50/"trace_count": 99/' attestation.json`
Sleep 500ms
Enter
Sleep 1s

Type "vidimus verify attestation.json"
Sleep 500ms
Enter
Sleep 3s

Sleep 2s
