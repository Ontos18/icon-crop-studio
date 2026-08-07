; Icon Crop Studio - Inno Setup script (v0.8.0)
[Setup]
AppId={{1293A909-C612-4B31-A153-07572F6AECEA}}
AppName=Icon Crop Studio
AppVersion=0.8.0
AppPublisher=Ontos18
AppVerName=Icon Crop Studio 0.8.0
DefaultDirName={autopf}\IconCropStudio
DefaultGroupName=Icon Crop Studio
OutputBaseFilename=IconCropStudioSetup
OutputDir=dist
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\IconCropStudio.exe
UninstallDisplayName=Icon Crop Studio

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\IconCropStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Icon Crop Studio"; Filename: "{app}\IconCropStudio.exe"
Name: "{group}\Uninstall Icon Crop Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Icon Crop Studio"; Filename: "{app}\IconCropStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\IconCropStudio.exe"; Description: "Run Icon Crop Studio"; Flags: nowait postinstall skipifsilent
