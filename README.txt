ROB RUN DEATH LOG - Windows app
================================
Reads the killer's name and ID off your Rob Run elimination / arrest screen,
saves it on this PC, and shows a searchable list (Player, ID, Kills, Arrests,
First seen, Last seen). Opens by itself when Rob Run starts. Nothing leaves your PC.

GET THE INSTALLER WITHOUT INSTALLING PYTHON (GitHub builds it for you, free)
  1. Make a free GitHub account (github.com) and click New repository.
     Name it robrun-deathlog, choose Private, click Create repository.
  2. Click "uploading an existing file" and drag EVERYTHING from this folder in,
     including the .github folder. (If the .github folder won't upload, click
     Add file > Create new file, type  .github/workflows/build-windows.yml  as the
     name, paste the contents of that file, and commit.) Click Commit changes.
  3. Click the Actions tab. Pick "Build Windows installer" on the left, click
     Run workflow > Run workflow. Wait about 10-15 minutes for a green tick.
  4. Click the finished run, scroll to Artifacts, click RobRunDeathLog-Setup,
     unzip it, and run RobRunDeathLog-Setup.exe. No Python needed on your PC.
  If the run shows a red X, open it and send the red error lines to whoever is helping you.

WINDOWS WARNING
  The installer is unsigned, so Windows SmartScreen may warn. Click More info > Run anyway.

FIRST LAUNCH
  The Settings window opens. Start Rob Run, click "Pick from running programs",
  choose the game, Save. After that the app only reads the screen while Rob Run is open.
  Keep Rob Run in Borderless / Windowed Fullscreen (exclusive Fullscreen can capture black).
  Closing the window sends it to the tray (red dot near the clock). Right-click > Quit to exit.

WHERE THINGS ARE SAVED
  %APPDATA%\RobRunDeathLog\  (deaths.db = your log, config.json = settings)

BUILDING ON YOUR OWN PC INSTEAD (needs Python 3.12 + Inno Setup 6): double-click build.bat.

A kill is not proof of cheating, and names can be misread. Keep clips as evidence.
