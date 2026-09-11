# data/inbox —— 抓取工具的落地目录

把抓取工具（如 amzrank）导出的 `.xlsx` 放进这里，然后运行：

```bash
python cli.py import-amzrank --collected-date 2026-09-11
```

它会自动取本目录里**修改时间最新**的 xlsx（自动跳过 Excel 的 `~$` 锁文件）。

也可以用环境变量指向别处：

```bash
# Windows PowerShell
$env:AMZRANK_OUT = "D:\path\to\amzrank_out"
# macOS / Linux
export AMZRANK_OUT=/path/to/amzrank_out
```

或者每次显式指定文件：

```bash
python cli.py import-amzrank --input path/to/file.xlsx --collected-date 2026-09-11
```
