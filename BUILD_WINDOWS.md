# Wmap 桌面版：Windows 打包步骤

目标：把 Wmap 打成 Windows 桌面软件（PyWebView 原生窗口，双击即用，不用开浏览器）。

> Windows 的 .exe 只能在 Windows 上打，Linux / Mac 打不了。
> 以下步骤都在你的 Windows 电脑上执行。

## 准备工作

- Windows 10 / 11（WebView2 运行时系统自带，不用另装）
- Python 3.10+（已装好，且 `py` 命令可用）
- Inno Setup 6（只在最后一步打安装包时需要，[官网下载](https://jrsoftware.org/isdl.php)）

## 1. 拉代码

```bat
cd C:\你放代码的地方
git clone https://github.com/wwenxiong/Wmap.git
cd Wmap
git pull
```

## 2. 补 7 张图标（GitHub 上没有）

`static\vendor\images\` 下的 7 张 PNG（Leaflet 地图标注图标）因故没推上 GitHub，
先从验证包 `wmap-verify-20261120.zip` 里把 `static\vendor\images\*.png`
（共 7 个：layers.png、layers-2x.png、marker-icon.png、marker-icon-2x.png、
marker-shadow.png、spritesheet.png、spritesheet-2x.png）复制到
本地仓库的 `static\vendor\images\` 里。
不补的话，地图上的标注图标会裂图。

## 3. 装依赖

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

## 4. 打包（PyInstaller）

```bat
pyinstaller --distpath dist_release 应急保障.spec
```

产物在 `dist_release\应急保障\`，主程序是 `应急保障.exe`，
旁边还有 `static\`、`data\`、`app\`、`main.py` 等配套文件（不要删）。

先双击 `dist_release\应急保障\应急保障.exe` 验证一下：
窗口应直接打开 Wmap（原生窗口，没有浏览器外壳和地址栏），地图正常加载。

## 5. （可选）补高德 Key

`config.local.json`（含高德 Key）不进包也不进仓库。
需要地图瓦片与地址搜索正常工作，把你自己的 `config.local.json`
复制一份到 `dist_release\应急保障\` 里，内容格式：

```json
{"amap_api_key": "你的 Key"}
```

不放也能跑，只是地图底图与地址搜索不可用。

## 6. 打安装包（Inno Setup）

```bat
iscc installer.iss
```

`iscc` 是 Inno Setup 的命令行编译器（装好 Inno Setup 后一般已在 PATH 里；
如果提示找不到，用 Inno Setup 图形界面打开 `installer.iss` 点编译也行）。

安装包输出在 `installer_output\应急保障_Setup_v1.0.exe`，双击即可安装，
装好后桌面与开始菜单都有“应急保障”快捷方式。

## 常见问题

- **双击 exe 没反应 / 一闪而过**：到 `dist_release\应急保障\` 里看 `server.log`
  （后端日志），或在命令行跑 `应急保障.exe` 看报错。
- **提示未安装 pywebview**：第 3 步的 `pip install -r requirements.txt` 没跑成功，
  重新跑一遍；确认是在激活了 `.venv` 的终端里执行的。
- **端口 8080 被占用**：先关掉其他在跑的 Wmap（浏览器版 `python main.py` 或旧版桌面程序），
  再启动。桌面版启动时若 8080 上已有 Wmap 服务在跑，会直接复用它。
- **托盘图标不见了**：托盘只在窗口打开期间存在；关掉窗口即退出程序，
  托盘随之消失，这是设计如此（不做后台常驻）。
