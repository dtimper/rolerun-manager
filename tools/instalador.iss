; Instalador de RoleRun Manager (Inno Setup 6).
;
; No se compila a mano: lo llama tools/construir_instalador.py, que le pasa
; AppVersion, SourceDir (el programa ya congelado), OutputDir, OutputName e
; IconFile. El programa congelado lleva dentro Python y .NET, así que aquí no
; hay requisitos que comprobar ni instalar.

#ifndef AppVersion
  #error Falta /DAppVersion: usa tools/construir_instalador.py
#endif

[Setup]
; Fijo para siempre: es lo que hace que una versión nueva se instale ENCIMA
; de la anterior en vez de al lado.
AppId={{2F6D232B-ABFE-4106-9FE9-194763C78E61}
AppName=RoleRun Manager
AppVersion={#AppVersion}
AppVerName=RoleRun Manager {#AppVersion}
AppPublisher=RoleRun
AppPublisherURL=https://github.com/dtimper/rolerun-manager
VersionInfoVersion={#AppVersion}
; Por usuario y sin pedir administrador: con permisos mínimos, {autopf} es
; %LOCALAPPDATA%\Programs. Además el programa descarga sprites dentro de su
; propia carpeta, que en "Archivos de programa" no podría escribir.
PrivilegesRequired=lowest
DefaultDirName={autopf}\RoleRun Manager
DisableProgramGroupPage=yes
; Sin esto /NOICONS no hace nada (WizardNoIcons siempre es falso) y la prueba
; automática pisaba el acceso del menú Inicio de la instalación de verdad. La
; página que lo ofrece no se muestra, así que al jugador no le cambia nada.
AllowNoIcons=yes
; Sin elegir carpeta: el jugador no tiene por qué decidirlo, y así nadie
; instala dentro de una carpeta con otras cosas.
DisableDirPage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\RoleRun Manager.exe
UninstallDisplayName=RoleRun Manager
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Si RoleRun está abierto al actualizar, se ofrece cerrarlo.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[InstallDelete]
; Una actualización sustituye el programa entero: sin esto quedarían
; archivos de la versión anterior que la nueva ya no trae. Las Runs no viven
; aquí, sino en Documentos\RoleRun Manager, y no se tocan.
Type: filesandordirs; Name: "{app}\_internal"
; El instalador de agosto de 2026 (1.13.0-alpha.25, con su propio Python y
; .NET 10 aparte) usaba esta misma carpeta con otra estructura. Solo se borra
; si de verdad es esa instalación: su desinstalador conservaba Documentos y
; aquí tampoco se toca.
Type: filesandordirs; Name: "{app}\app"; Check: HayInstalacionAntigua
Type: filesandordirs; Name: "{app}\runtime"; Check: HayInstalacionAntigua
Type: filesandordirs; Name: "{app}\data"; Check: HayInstalacionAntigua
Type: filesandordirs; Name: "{app}\engine"; Check: HayInstalacionAntigua
Type: filesandordirs; Name: "{app}\lang"; Check: HayInstalacionAntigua
Type: filesandordirs; Name: "{app}\resources"; Check: HayInstalacionAntigua
Type: files; Name: "{app}\main.py"; Check: HayInstalacionAntigua
Type: files; Name: "{app}\requirements.txt"; Check: HayInstalacionAntigua
Type: files; Name: "{app}\CHANGELOG.md"; Check: HayInstalacionAntigua
Type: files; Name: "{app}\README*.txt"; Check: HayInstalacionAntigua
Type: files; Name: "{app}\Uninstall.exe"; Check: HayInstalacionAntigua
Type: files; Name: "{app}\DESINSTALAR RoleRun Manager.cmd"; Check: HayInstalacionAntigua

[Registry]
; Y su entrada de "Agregar o quitar programas", para que no queden dos
; RoleRun Manager en la lista (la suya apuntaba a un Uninstall.exe que ya no
; existe). Solo si esa entrada apunta a esta misma carpeta.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\RoleRun Manager"; Flags: deletekey; Check: EntradaAntiguaApuntaAqui

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; /NOICONS (lo usa tools/probar_instalador.py) evita tocar el menú Inicio.
Name: "{autoprograms}\RoleRun Manager"; Filename: "{app}\RoleRun Manager.exe"; Check: not WizardNoIcons
Name: "{autodesktop}\RoleRun Manager"; Filename: "{app}\RoleRun Manager.exe"; Tasks: escritorio

[Run]
Filename: "{app}\RoleRun Manager.exe"; Description: "Abrir RoleRun Manager"; Flags: nowait postinstall skipifsilent

[Code]
const
  ClaveAntigua = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\RoleRun Manager';

var
  // 0 = sin mirar, 1 = sí, 2 = no. Se mira una sola vez: [InstallDelete]
  // evalúa el Check antes de cada borrado, y en cuanto se borra runtime\
  // la segunda marca desaparece y el resto de borrados se saltarían.
  EstadoAntigua: Integer;

// Las dos marcas juntas solo se dan en la instalación de agosto: su
// desinstalador .cmd y su Python privado en runtime\python.
function HayInstalacionAntigua(): Boolean;
begin
  if EstadoAntigua = 0 then
  begin
    if FileExists(ExpandConstant('{app}\DESINSTALAR RoleRun Manager.cmd'))
       and DirExists(ExpandConstant('{app}\runtime\python')) then
      EstadoAntigua := 1
    else
      EstadoAntigua := 2;
  end;
  Result := EstadoAntigua = 1;
end;

function EntradaAntiguaApuntaAqui(): Boolean;
var
  Ruta: String;
begin
  Result := RegQueryStringValue(HKCU, ClaveAntigua, 'InstallLocation', Ruta)
    and (CompareText(RemoveBackslashUnlessRoot(Ruta),
                     RemoveBackslashUnlessRoot(ExpandConstant('{app}'))) = 0);
end;
