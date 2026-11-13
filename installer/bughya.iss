; ملفّ تنصيب «بُغية» — يُبنى بـ Inno Setup 6 بعد build_exe.bat:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\bughya.iss
; التنصيبُ للمستخدم وحده بلا صلاحيّات مدير، في %LOCALAPPDATA%\Programs\Bughya.
; بياناتُ المستخدم (الكتب المقروءة والإعدادات) في %LOCALAPPDATA%\Bughya ولا يمسّها الحذف.

#define AppVer "0.9.4"

[Setup]
AppId={{6B1F3C2E-8E1A-4D5B-9C1F-B06A0A9E2F11}
AppName=Bughya
AppVerName=Bughya {#AppVer}
AppVersion={#AppVer}
AppPublisher=Omar Elmnfi
DefaultDirName={localappdata}\Programs\Bughya
DefaultGroupName=Bughya
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Bughya-Setup-{#AppVer}
SetupIconFile=..\assets\bughya.ico
UninstallDisplayIcon={app}\Bughya.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Bughya\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\بُغية"; Filename: "{app}\Bughya.exe"
Name: "{group}\{cm:UninstallProgram,بُغية}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\بُغية"; Filename: "{app}\Bughya.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Bughya.exe"; Description: "{cm:LaunchProgram,بُغية}"; Flags: nowait postinstall skipifsilent
