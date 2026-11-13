GrainGuard simulation - how to run

1. Unzip this folder somewhere WITHOUT spaces in the path, for example C:\grainguard
2. In VS Code: File > Open Folder > choose that folder.
3. Press F5 (or Run > Start Debugging). Pick "GrainGuard: run with Lagos CSV".
   It reads lagos_style_hourly_weather.csv and writes grainguard_data.csv in the same folder.

Without VS Code: double-click run.bat.

To use real weather instead: run "pip install requests" once, then pick
"GrainGuard: download real Lagos weather" in the F5 menu (needs internet).
