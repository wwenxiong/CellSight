; Inno Setup Script - CellSight
#define MyAppName "CellSight"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "wwx"
#define MyAppExeName "CellSight.exe"

[Setup]
AppId={{C6287A29-873E-4B1C-9E2D-F8798A13B44F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\CellSight
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=CellSight_Setup_v{#MyAppVersion}
SetupIconFile=app.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"

[Messages]
chinesesimplified.WelcomeLabel1=欢迎使用 [name] 安装向导
chinesesimplified.WelcomeLabel2=本向导将指引您在计算机上安装 [name]（由 {#MyAppPublisher} 提供）。%n%n建议您在继续之前关闭其他所有应用程序。%n%n单击“下一步”继续，或单击“取消”退出安装向导。
chinesesimplified.WizardSelectDir=选择目标位置
chinesesimplified.SelectDirDesc=程序将安装到哪个文件夹？
chinesesimplified.SelectDirLabel3=安装程序将把 [name] 安装到以下文件夹中。
chinesesimplified.SelectDirBrowseLabel=若要继续，请单击“下一步”。若要选择其他文件夹，请单击“浏览”。
chinesesimplified.DiskSpaceMBLabel=至少需要 [mb] MB 的可用磁盘空间。
chinesesimplified.WizardSelectTasks=选择附加任务
chinesesimplified.SelectTasksDesc=您想要执行哪些附加任务？
chinesesimplified.SelectTasksLabel2=选择您希望安装程序在安装 [name] 时执行的附加任务，然后单击“下一步”。
chinesesimplified.WizardReady=准备安装
chinesesimplified.ReadyLabel1=安装程序现在已准备好开始在您的计算机上安装 [name]。
chinesesimplified.ReadyLabel2a=单击“安装”继续安装，或者如果您想查看或更改任何设置，请单击“上一步”。
chinesesimplified.WizardInstalling=正在安装
chinesesimplified.InstallingLabel=安装程序正在您的计算机上安装 [name]，请稍候。
chinesesimplified.WizardFinished=安装完成
chinesesimplified.FinishedHeadingLabel=[name] 安装向导完成
chinesesimplified.FinishedLabelNoIcons=安装程序已在您的计算机上完成了 [name] 的安装。
chinesesimplified.FinishedLabel=安装程序已在您的计算机上完成了 [name] 的安装。可以通过选择安装的快捷方式来启动应用程序。
chinesesimplified.ClickFinish=单击“完成”退出安装向导。
chinesesimplified.ButtonNext=下一步(&N) >
chinesesimplified.ButtonInstall=安装(&I)
chinesesimplified.ButtonBack=< 上一步(&B)
chinesesimplified.ButtonFinish=完成(&F)
chinesesimplified.ButtonCancel=取消
chinesesimplified.ExitSetupTitle=退出安装程序
chinesesimplified.ExitSetupMessage=安装未完成。如果您现在退出，程序将不会被安装。%n%n您确定要退出安装程序吗？

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"; Flags: checkedonce

[Files]
Source: "dist_release\CellSight\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "edge_profile,edge_profile\*,config.local.json,window_state.json,*.log,*.tmp"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall
