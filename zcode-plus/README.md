# ZCode+ 集成（推荐安装方式）

将状态栏作为 ZCode+ 的 CDP 注入模块运行，**无需修改 app.asar**：

- ZCode 升级免疫（不碰应用文件，升级后照常工作）
- 注入即时生效（无 Electron asar 虚拟 FS 缓存问题）
- 与提示词增强按钮同一入口启动

## 安装

```bash
# 1. 把 tps.js 放进 ZCodePlus 安装目录
cp tps.js "~/Library/Application Support/ZCodePlus/"

# 2. controller.mjs 在 INJECT_SOURCE 拼接处加载 tps.js（见下方补丁）
```

controller.mjs 的接入点（读取 INJECT_SOURCE 之后追加）：

```javascript
// TPS 状态栏模块（zcode-tps-footer 项目）：存在则随增强脚本一起注入。
// 模块自带 window.__ztps 幂等守卫——asar 版补丁先注入时会自动跳过，两来源只活一个。
let TPS_SOURCE = "";
try { TPS_SOURCE = fs.readFileSync(path.join(INSTALL_DIR, "tps.js"), "utf8"); }
catch { /* tps.js 不存在 = 未启用状态栏，正常 */ }
if (TPS_SOURCE) {
  INJECT_SOURCE += "\n" + TPS_SOURCE;   // tps.js 是完整 IIFE，直接拼接
  log("TPS 状态栏模块已随注入加载");
}
```

## 与 asar 模式共存

`window.__ztps` 幂等守卫保证两种注入来源只活一个实例：asar 版先到则 CDP 版跳过，反之亦然。可平滑迁移（先装 ZCode+ 模块，再 `--tps-footer --revert` 还原 asar）。

## v2.0 渲染层事件化

- 窗格注册表 + ResizeObserver（行尺寸变化 → 重算空隙与降级）
- 行内叶子签名（tag@rect 指纹）变化才重扫全树，静止时零开销
- rAF 合帧调度：数据事件与布局事件汇入同一调度器，每帧最多渲染一次
- scroll 捕获阶段 passive 监听，仅更新胶囊坐标（实测端到端渲染延迟 4ms）
