# v8.7.6.1 — Local launcher fix

Built directly from v8.7.6.0.

## Fix

The local launcher now:

- requires Python 3.10 or newer
- prefers Python 3.12, 3.11, then 3.10
- detects and removes a virtual environment created with an unsupported or different Python
- rebuilds the environment with the selected interpreter
- gives a clear installation command when no supported Python is available
- displays the correct release version

## Unchanged

- application code
- top navigation
- workflows
- data model and workbook
- staging deployment configuration
