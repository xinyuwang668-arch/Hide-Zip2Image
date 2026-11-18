[Setup]
AppName=HideZipImage
AppVersion=3.1.0
AppPublisher=Xinyu
DefaultDirName={autopf}\HideZipImage
DefaultGroupName=HideZipImage
OutputDir=installer_output
OutputBaseFilename=HideZipImage_Setup_V3.1.0
Compression=lzma
SolidCompression=yes
SetupIconFile=icon_multisize.ico
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\HideZipImage_V3.1.0.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\HideZipImage"; Filename: "{app}\HideZipImage_V3.1.0.exe"
Name: "{commondesktop}\HideZipImage"; Filename: "{app}\HideZipImage_V3.1.0.exe"
[Run]
Filename: "{app}\HideZipImage_V3.1.0.exe"; Description: "启动 HideZipImage"; Flags: nowait postinstall skipifsilent
