# zcode-tps-footer

ZCode 桌面客户端 TPS 状态栏补丁——在输入框工具栏常驻一枚统计胶囊，实时展示当前会话最近一轮的生成指标：

```
● 21:03 · 首 token 4s · 25 tok/s · out 1.2k
```

- **tok/s**：生成速度（流式中为 4s 滑动窗口即时速度，结束后为精确值）
- **首 token**：TTFT，发出消息到第一个 token 的延迟
- **out**：本轮累计输出 token（含工具调用多请求累加，精确值随 usage 到达覆盖估算）
- **时间**：轮次时间戳，绿点生成中发亮

源自 [LINUX DO 帖子](https://linux.do/t/topic/2886711) lanvv 的 zcode-patcher，本仓库是其中「TPS 状态栏」功能的维护分支，重点修复与增强：

| 版本 | 内容 |
|---|---|
| v1.0.1 | 上游原始版（流内胶囊） |
| v1.1.0 | 修复侧栏展开时与模式切换/第三方增强按钮**重叠**、以及会话误判导致的**消失**；胶囊改 fixed 悬浮 + 几何空隙自适应 + hover tooltip |
| v1.2.0 | **段优先级调整**（tok/s > 首 token > out > 时间，宽度不足按优先级丢弃）；**逐窗格独立渲染**（多会话窗格各看各的）；MutationObserver 自身操作过滤防自激；丢段后分隔符清理 |

## 特性

- **宽度自适应**：按工具栏行水平带内真实元素矩形计算空隙，胶囊居中悬浮其中；宽度不足逐段降级（时间→out→首 token），`tok/s` 永不丢，放不下整体隐藏
- **hover 完整显示**：降级发生时悬停胶囊弹出完整指标 tooltip
- **多窗格**：按 composer 卡片逐窗格渲染，各窗格只统计本窗格会话；多窗口天然隔离
- **无常驻服务**：纯被动监听页面内已有的 MessagePort 会话事件流，无网络外发
- **幂等可还原**：整包备份 + sidecar 记录，一条命令还原；ZCode 升级后重打即可

## 安装

```bash
git clone https://github.com/<你的用户名>/zcode-tps-footer.git
# 只需要状态栏功能：把 skill/ 与 scripts/ 放进 ~/.zcode/skills/zcode-patcher/
mkdir -p ~/.zcode/skills/zcode-patcher
cp -R zcode-tps-footer/skill/* zcode-tps-footer/scripts ~/.zcode/skills/zcode-patcher/

# 打补丁（macOS；Windows 需先完全退出 ZCode）
python3.10+ ~/.zcode/skills/zcode-patcher/scripts/zcode_patcher.py /Applications/ZCode.app --tps-footer

# 完全退出并重启 ZCode 后生效
```

> macOS 上 ZCode 运行中可直接打补丁（asar 原子替换）；但**运行中重打包后 Electron 的 asar 虚拟文件系统有内存缓存**，页面 reload 仍会加载旧版——必须重启 ZCode 才能加载新版。

### 还原

```bash
python3 ~/.zcode/skills/zcode-patcher/scripts/zcode_patcher.py /Applications/ZCode.app --tps-footer --revert
```

## 命令速查

| 命令 | 作用 |
|---|---|
| `--tps-footer --check` | 查看注入状态 |
| `--tps-footer` | 注入/更新（幂等） |
| `--tps-footer --revert` | 整体还原（清理备份与 sidecar） |
| `--tps-footer --tps-src <path>` | 指定注入源脚本 |

## 行为规则

- 绿点 ● 与指标常驻于有可展示轮次的窗格；流式生成中绿点发亮
- 同一 turnId 复用（编辑重发/重试）自动清零旧统计
- 切换会话立即消失（只认「DOM 可见轮次 + 窗格会话归属」双条件）；历史会话无精确 usage 回放，只有时间戳
- 工具执行静默期速度保持最近值；点停止/出错未报 usage 时 out 以内容估算兜底
- 无假时钟：轮次无时间戳且无生成活动时不渲染

## 已知限制

- ZCode 升级覆盖 app.asar 后补丁失效，重跑注入命令即可（脚本幂等）
- 帧结构（MessagePort 会话事件流）随版本可能变化；字段变化表现为指标不更新，可旁路 `window.__ztpsPort` 监听原始帧排查
- 与 ZCode+（CDP 运行时注入的提示词增强）实测共存无冲突：数据通道、DOM 挂载点、全局变量前缀均隔离

## 致谢

- [lanvv](https://linux.do/u/lanvv/) 的原版 zcode-patcher 与 skill 设计
- [LINUX DO 社区](https://linux.do/t/topic/2886711) 的讨论与反馈

## License

MIT
