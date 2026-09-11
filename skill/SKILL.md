---
name: zcode-patcher
description: "[仅手动调用，禁止自动触发] ZCode 客户端本地补丁工具：①自定义模型供应商思考等级（effort/thinking/budget_tokens 真正下发到请求体）②用量页去截断（打开统计图：趋势图/饼图全量展示）③TPS 状态栏（打开状态栏：输入框工具栏统计胶囊，时间·首 token·tok/s·out）。只有当用户明确要求执行本 skill、或明确点名「zcode-patcher」时才加载；用户只是泛泛提到思考等级、用量图、状态栏、补丁等话题时，一律不要自动触发本 skill。"
---

# ZCode 客户端补丁工具

三类补丁，均幂等、可检查、可还原、ZCode 升级后需重打：

| 能力 | 说法 | 命令 | 改哪里 |
|---|---|---|---|
| 思考等级透传 | 给自定义模型配思考等级 | `python zcode_patcher.py [--check/--revert/--extract]` | 内核 zcode.cjs（原地改写，.bak 备份） |
| 打开统计图 | 用量页趋势图/饼图去截断 | `python zcode_patcher.py --usage-chart [--check/--revert]` | app.asar 内渲染文件（同长度原地改字节） |
| 打开状态栏 | 输入框工具栏 TPS 统计胶囊 | `python zcode_patcher.py --tps-footer [--check/--revert]` | app.asar（重打包级：注入脚本 + 挂载 index.html） |

两个及以上功能可一次执行：`python zcode_patcher.py --usage-chart --tps-footer`。

## 标准执行流程（AI 代执行与人工自助通用）

调用本 skill 时按以下序列执行，**AI 代执行时必须走完全部步骤，不得跳过核实与展示**：

1. **定位安装**：脚本自动探测（运行中进程 → 注册表 → 常见目录，跨 Windows/macOS/Linux，见「跨平台约定」）；探测不到就把安装根目录作为位置参数传入。
2. **只读核实**（能否生效的判断，全部只读，可放心先跑）：
   - `python zcode_patcher.py --check`：思考等级补丁状态；ZCode 版本不在「已知符号表」时跑 `--extract`——能提取出锚点即可生效，提取失败说明内核结构变了，按「新版本锚点提取」人工分析后再动。
   - `python zcode_patcher.py --usage-chart --check`：两个截断表达式是否命中。
   - `python zcode_patcher.py --tps-footer --check`：index.html 是否找到、注入状态。
   - 脚本对「表达式出现次数 ≠1」「锚点不唯一」等情况一律拒绝盲改并报告原因——报告即结论，不要绕过。
3. **确认备份就绪并展示还原命令**（打补丁前必须完成，AI 代执行时明确提示用户保存还原命令）：
   - 思考等级：首次打补丁自动生成 `zcode.cjs.bak`（整文件备份）
   - 状态栏：首次注入自动生成 `app.asar.tps.bak`（整包备份）+ `app.asar.tps-patch.json`（原始 index.html 记录）
   - 统计图：sidecar `app.asar.chart-patch.json` 记录全部原始字节
4. **展示执行命令与还原命令**——**单功能单命令，按用户点名的功能给对应命令，不要捆绑其他功能**（各补丁相互独立；低风险的思考等级/统计图 AI 可在核实与备份确认后直接代执行，重打包级的状态栏交由用户执行）。以「打开状态栏」为例：
   ```bash
   # 执行
   python "<skill目录>/scripts/zcode_patcher.py" --tps-footer
   # 还原（万一异常，保存备用；完全退出 ZCode 后执行，还原后重启 ZCode）
   python "<skill目录>/scripts/zcode_patcher.py" --tps-footer --revert
   ```
   人工自助时用户自行执行；AI 代执行时经用户确认后由 AI 运行，或用户复制命令自己跑。
5. **重启验证**：完全退出并重启 ZCode（Windows 运行中锁 app.asar，打补丁前必须退出）后，按各功能的「验证」说明确认。
6. **失败回退**：执行上面展示的还原命令 → 重启 ZCode → 重新核实。思考等级补丁还原走 zcode.cjs.bak；状态栏还原自动清理 `.tps.bak` 与 sidecar。

## 跨平台约定

| 系统 | 安装根目录（resources 的上一级） | 典型位置 |
|---|---|---|
| Windows | `D:\ZCode`、`%LOCALAPPDATA%\Programs\ZCode` 之类 | 探测顺序：运行中进程路径 → 注册表卸载信息 → Program Files 系目录 |
| macOS | `/Applications/ZCode.app/Contents` | 探测 /Applications 与 ~/Applications 下的 `.app` 包（自动进入 `Contents`） |
| Linux | `/opt/ZCode`、`/usr/share/ZCode` 之类 | 探测 /opt、/usr/share |

- 关键文件相对安装根目录固定：`resources/glm/zcode.cjs`（内核）、`resources/app.asar`（桌面端资源包）
- Python ≥ 3.10，用系统可用的 `python3`/`python` 即可，脚本仅用标准库
- Program Files / /Applications 类目录可能需要管理员/sudo 权限
- 执行 AI 可按上述规则自行定位安装（如 `ls /Applications`、查运行中进程的 exe 路径）

## 升级后自查清单

ZCode 升级会覆盖 zcode.cjs 与 app.asar，升级后过一遍：

```bash
python zcode_patcher.py --check            # 思考等级补丁状态
python zcode_patcher.py --usage-chart --check
python zcode_patcher.py --tps-footer --check
```

失配的按「自助使用流程」重打；思考等级补丁在新内核上先 `--extract` 确认锚点可提取。

## 一、思考等级：完整结论一张表

| 场景 | 档位来源 | 是否需要 config 配置 | 是否需要内核补丁 |
|---|---|---|---|
| 模型 id 含 "ox-alpha"，ZCode ≥ 3.9.1 | 内核硬编码白名单（`isOxAlphaReasoningModelId`），天生 low/high/max，defaultLevel=max | **不需要**（配了也是冗余） | **不需要** |
| 其它模型，ZCode ≥ 3.9.1，标准档名（low/medium/high/xhigh/max） | 引擎原生通用表：anthropic → `thinking:{type:"adaptive"}` + `output_config.effort` | **需要**：模型条目配 `reasoning.variants` | **不需要** |
| 其它模型，自定义档名（如 "turbo"） | 无原生表，留空 | 需要 | **需要**：补丁兜底合成 |
| ZCode ≤ 3.8.1，任何模型任何档位 | 无原生表 | 需要 | **需要** |

判别某次请求走的哪条路：`thinking:{type:"adaptive"} + output_config.effort` = 原生路径；`thinking:{type:"enabled", budget_tokens:N}` = 补丁兜底。补丁在原生表非空时惰性（`??` 短路），留着无害但升级后要重打才有意义。

### 档位从配置到请求的完整链路（补丁原理）

```
~/.zcode/v2/config.json  模型条目 reasoning.variants      ← 档位名数组（UI 显示的就是它）
      │  桌面端 host：variants → 内部 levels（每档参数对象）
      │  内核 override 构建器 → catalogOverrides 注入模型目录
      ▼
capability.reasoning = { enabled, levels, providerOptionsByLevel }
      │  内核档位解析函数 sD(3.8.1)/AD(3.9.1)/mN(3.11.2)(modelRef, 选中档名, catalog)
      ▼
{ level, providerOptions: providerOptionsByLevel[档名] }   ← 断点：自定义模型此表为空
      │  合并进请求
      ▼
anthropic: thinking:{type:"enabled",budget_tokens:N} + effort
openai 系: reasoning_effort:"档名"
```

`providerOptionsByLevel`（档名→请求参数表）只给内核认识的白名单家族（claude/glm/deepseek 等）下发；自定义模型拿到空表，档位能选中却不产生任何请求参数。补丁 = 在取参处加 `?? zCfgEffort(档名)` 兜底，按档名现场合成参数；白名单模型表非空，`??` 短路，行为零变化。

### ox-alpha 白名单的代码依据（3.9.1+ 原生支持）

- **(a) 硬编码白名单**：内核 override 构建函数 `t2t` 首分支 `t.reasoningProfile===Iue || j5(t.modelId)` → anthropic 协议拿 `jye()` = `{defaultLevel:"max", levels:["low","high","max"], providerOptionsByLevel:每档{effort, thinking:{type:"adaptive"}}}`。其中 `Iue=iLe([111,120,45,97,108,112,104,97])="ox-alpha"`，`j5` 注册名 `isOxAlphaReasoningModelId`（正则 `/ox-alpha/i` 子串匹配 + 两个内部预览模型）。与端点协议无关，同端点其它模型无此待遇。
- **(b) 标准档名通用表**：非白名单模型配了 `reasoning.variants` 且档名为标准名，构建时也套通用表（anthropic → adaptive+effort）。config 里配的档位集合即 UI 显示的集合。

### 工作流

1. **配档位**（每模型一次，完全退出 ZCode 后改 `~/.zcode/v2/config.json`）：
   ```json
   "reasoning": {"enabled": true, "variants": ["low", "high", "max"], "defaultVariant": "max"}
   ```
   **必须同时给该模型条目补 `"zcode": {"modified": true}`**——没有该标记的条目会被客户端目录同步重写，`reasoning` 配置丢失（表现为档位退回"开启/关闭"开关，实测 deepseek-flash 踩坑）。
2. **仅当需要补丁时**（见判断表）：`--check` → 打补丁 → 完全退出并重启 ZCode。新版本无已知锚点先 `--extract`。
3. **验证**：rollout（`~/.zcode/cli/rollout/model-io-*.jsonl`）请求体里 `thinking`/`effort` 随档位变化；引擎日志（`~/.zcode/cli/log/`）无 400。**注意 rollout 请求体是脱敏的，`thinking` 字段会被剥掉（内置模型也一样），不能作为判据**——以 OpenRouter Dashboard → Activity Log 之类的外部请求日志为准。

### 内核补丁点与版本匹配

断点只有一处——内核 `resources/glm/zcode.cjs` 里的**思考档位解析函数**（见上方链路图）。zcode.cjs 是 esbuild 压缩产物，**每个版本的顶层符号名整体重排**，锚点（解析函数完整原文）必须与已安装版本逐字符一致：

| 版本 | 已知符号 |
|---|---|
| 3.8.1 | sD / G_e / Fgo / gXe |
| 3.9.1 | AD / Zye / fxo / utt |
| 3.9.2 | RD / Xye / Sxo / ptt |
| 3.11.2 | mN / k2e / CIo / _nt（本版返回处局部变量名为 s，替换逻辑已通用化） |

脚本按「全文唯一匹配」自动选择版本：对每个已知锚点统计出现次数，**恰好有一版 =1 才动手**；全为 0 或多版命中都拒绝修改。锚点匹配失败 ≠ 补丁思路失效——要改的内核点（解析函数返回处 `providerOptionsByLevel?.[X]` 查表表达式）所有版本语义不变，变的只是符号名。

**新版本锚点提取**：首选 `--extract` 自动提取——按结构特征（函数以 `{level:...providerOptionsByLevel?.[...]}:void 0}` 收尾、体内无嵌套 function）定位，已打补丁的文件自动回退 .bak 原始件，打印可直接粘贴进脚本 `ANCHORS` 字典的锚点（打印格式即条目格式，加个版本号键即可）。`--extract` 失败（候选数 ≠1）时人工提取：在内核里搜 `providerOptionsByLevel?.[`，找到以 `:void 0}` 收尾的完整解析函数整段复制为锚点；若函数体结构有变（不止符号改名），同步调整 `replacement_for()` 的拼接假设。加锚点后用 `--check` 验证恰好唯一命中再打。

### 档名与预算映射（补丁内置）

| 档名 | anthropic budget_tokens | openai 系 reasoning_effort |
|---|---|---|
| low | 4000 | low |
| medium | 8000 | medium |
| high | 16000 | high |
| xhigh | 32000 | xhigh |
| max | 32000 | xhigh（openai 侧折算） |
| 其它任意名 | 16000 兜底 | 不带 |
| disabled / none / off / nothink | thinking disabled | thinking disabled |

改数值或加档名：编辑脚本 `HELPER` 里的映射行 `{low:4e3,medium:8e3,high:16e3,xhigh:32e3,max:32e3}[t]??16e3`，重打补丁。

**输出上限约束**：anthropic 协议要求 `budget_tokens < max_tokens`，等值会被内核钳到 max-1。模型条目不写 `limit.output` 时请求不带 max_tokens，由网关兜默认值；若写了 `limit.output`，必须大于所选档位预算（如 output 32000 配 max 档 32000 会直接 400）。

### deepseek 家族实测记录（3.11.2）

- 内核 override 构建器（`gwt`）分支顺序：ox-alpha 白名单 → glm-5.3 → kimi-k3 → **config.reasoning（自定义档位在此生效）** → 家族兜底
- 无自定义配置时 deepseek 走兜底 `CA()`：只有 enabled/disabled 两档开关、预算固定 1024
- 配了 variants + 内核补丁后：deepseek-flash 实测 max 档下发 `budget_tokens:32000 + effort:"max"`（补丁兜底路径，与内置 1024 明显区分）

### 故障排查

| 现象 | 原因与处理 |
|---|---|
| 档位能选但请求无 thinking | 内核补丁没打或打完没重启；`--check` 确认（3.9.1+ 标准档名走原生，无补丁也应生效） |
| 400: budget_tokens 必须小于 max_tokens | 所选档位预算 ≥ `limit.output`；调大上限或不设上限 |
| 400: max_tokens 缺失 | 不设 output 上限且网关不兜默认时出现；给模型设较大的 `limit.output` |
| 升级后失效 | 内核/app.asar 被覆盖；重跑补丁（无已知锚点先 `--extract`） |
| 档位选不到某名字 | `variants` 里没写，或 `defaultVariant` 不在列表内 |

## 二、打开统计图：用量页去截断

「设置 → 用量」两处展示截断，本补丁一并放开：

| 位置 | 原始行为 | 补丁点 |
|---|---|---|
| 每日 Token 趋势图 | 只画 Top 6 模型折线（`n.models.slice(0,6)`；每日 total 含全部模型） | 改为 `n.models` 全量出线 |
| 模型用量饼图 | 模型 >6 个时只画 Top 5，其余合并为「其他模型」（`i=n.length>Q,a=i?Q-1:Q`，Q=6） | 改为 `i=!1,a=1/0` 全量出块、无合并 |

```bash
python zcode_patcher.py --usage-chart            # 打补丁（asar 内同长度字节级原地覆盖）
python zcode_patcher.py --usage-chart --check    # 查状态
python zcode_patcher.py --usage-chart --revert   # 从 sidecar 还原全部原始字节
```

- 原理：解析 asar 头定位渲染文件偏移，替换截断表达式后用空格补齐到原字节长度原地写回——asar 头、offset、unpacked 结构零改动，无需重打包
- 原始字节 base64 存同目录 `app.asar.chart-patch.json`（sidecar，含全部补丁点记录）
- **sidecar 带 asar 尺寸指纹**：每条记录绑定当时的 app.asar 总大小，ZCode 升级覆盖 asar 后旧 offset 不可信，指纹失配的记录自动作废重建（实测 3.9.1→3.9.2 升级后重打正常；TPS 重打包后脚本自动同步本 sidecar 的 offset/指纹）
- 两处调色盘均 6 色循环取色，第 7+ 个模型颜色重复，靠图例/标签区分
- 定位按文件名特征 + 截断表达式匹配，与文件名哈希无关，跨版本稳定（3.9.1→3.9.2 文件名哈希变化仍能命中）

## 三、打开状态栏：TPS 统计胶囊

输入框工具栏常驻一枚统计胶囊（水平居中于工具栏行，宽度上限 50%），展示**当前会话最近一轮**的生成指标：

```
生成中:  ● 21:03 · 32 tok/s · out 410
结束后:  ● 21:03 · 首 token 37s · out 1.7k
```

```bash
python zcode_patcher.py --tps-footer             # 注入（默认用本 skill scripts/zcode-tps.js）
python zcode_patcher.py --tps-footer --check     # 查状态
python zcode_patcher.py --tps-footer --revert    # 整体还原
python zcode_patcher.py --tps-footer --tps-src /path/to/zcode-tps.js   # 指定注入源
```

### 行为规则（验收标准）

- **绿点 ● 与时间常驻**：有可展示的轮次就在；流式生成中绿点发亮，空闲静态。无省略号占位。
- **分隔符 `·`** 隔开各段；标签灰、数值白、tok/s 橙、tabular-nums 对齐。
- **同一 turnId 复用（编辑重发/重试）自动清零**：检测到新一轮开始即重置旧统计，杜绝「时间变新、指标是旧的」残留。
- **out 语义**：**本轮累计输出**（最近一次提问→回答完成为止），非会话累计。
- **动态刷新**：流式中 1 秒节奏刷新——tok/s 为 4s 滑动窗口即时速度、out 为本轮估算值；基于回答文本的 token 估算（CJK 1 字≈1 token、其余 4 字符≈1 token）。`usage.delta` 精确值随每次模型请求完成到达即覆盖估算；轮结束后为精确值（精确 out ÷ 首块→末次 usage 的解码窗口）。
- **静默期保持**：工具执行期间文本停止增长，速度保持最近值不消失；点停止/出错时该次请求不报 usage，out 以内容估算兜底、速度保持最近值——已产生的数据不凭空消失。
- **切换会话立即消失**：渲染只认「DOM 可见轮次（`section[data-turn-id]`）+ `data-session-id` 匹配当前会话」双重条件，不依赖任何会话切换事件；多会话并行时各 tab 互不干扰。
- **历史会话只有 `● 时间`**：usage.delta 不回放，重新打开旧会话拿不到当时的 token 统计，属预期。
- **无假时钟**：轮次连时间戳都没有且无生成活动时不渲染，绝不拿当前时间冒充轮次时间。

### 数据链路原理（无常驻服务）

1. ZCode 桌面端 preload 把主进程的 MessagePort 经 `window.postMessage("zcode:service-port", "*", [port])` 转交渲染页面；注入脚本监听该事件接管端口（`window.__ztpsHook` 可对存量端口手动补挂，`window.__ztpsPort` 暴露端口供调试旁路监听）。
2. 会话协议帧为二进制（Uint8Array）内嵌 JSON（自首个 `{` 起），两类：
   - **version:1 事件流**（顶层带 sessionId/sourceCommandId/occurredAt）：`usage.delta`（inputTokens/outputTokens/cacheReadTokens/totalTokens/reasoningTokens，**每次模型请求完成时发**——一轮含工具调用会有多条，out 为该次请求输出）、`stream.chunk`（`assistantMessageId` + `chunkLength` + `channel`，流式期间每 50-100ms 一批）
   - **conversation 行事件**（`frame.payload.deltas`/`events`）：`turnHeader`（startedAt/endedAt/state）、`userInput`（createdAt）、`reasoning`/`assistantText`（`text` 全量 + `assistantResponseId`）、`row.delta`（`{rowId, path:"text", append:"文本增量"}`）
3. **轮关联链**（事件里的 id 有两套，务必分清）：轮的 key 是 productTurnId（`msg_xxx`，与 DOM `section[data-turn-id]` 一致）；stream.chunk 的 `assistantMessageId` 是 assistantResponseId（另一个 msg_xxx），需经行事件的 `assistantResponseId → turnId` 映射中转；usage.delta 经 `sourceCommandId` 关联（turnHeader/userInput 行携带）。关联断了的表现：out/tok/s 一直不出现。
4. 渲染：扫描 `section[data-turn-id]` + sessionId 双条件取当前会话最新轮 → 算指标 → 更新胶囊。
5. 刷新机制：MutationObserver 回调里 16ms 节流的**同步**刷新（切换会话零残留）＋ 60ms 防抖全量扫 ＋ 1s 估算刷新节奏；渲染带内容签名（stamp/ttft/tps/out/streaming），数据未变零 DOM 写，保证同步刷新不触发 observer 自激。

### 注入原理（asar 重打包级）

与统计图补丁的同长度原地覆盖不同，状态栏要**新增文件**，必须整体重打包：

1. 注入内容：`out/renderer/index.html` 的 `</body>` 前插 `<script src="./zcode-tps.js"></script>`；zcode-tps.js 作为新条目写入 `out/renderer/`。index.html 无 CSP meta、无 nonce，普通脚本标签即可（在 `type="module"` 的 React bundle 之前同步执行，注册监听早于应用挂载）。
2. asar 布局（读/写同一公式）：头 16 字节 = 4 个 uint32 LE `[4, headerSize, pickleLen, jsonLen]`，`pickleLen = 4 + jsonLen + pad4`，`headerSize = 8 + jsonLen + pad4`，数据区起点 = `16 + jsonLen + pad4`（pad4 把 JSON 补齐到 4 字节倍数）；文件条目 `offset` 为相对数据区起点的字符串，全部文件带 integrity（SHA256 全文 + 4MB 分块 hex）。
3. 重打包流程：读全量 → 树上删条目/插占位/标记覆盖 → 全部条目 offset 重排 → 覆盖与新增条目重算 integrity → 写临时文件 → **回读校验**（逐条比对注入条目字节）→ 原子替换。
4. **实现关键坑**（改 `_repack_asar` 前必读）：offset 重排会直接改写条目，此后从旧文件切片必须用**重排前快照的旧位置**，否则「新 offset + 旧数据区起点」错位读取（实测 50 个抽查文件错 11 个，且改动文件恰好走覆盖分支不受影响，极易漏测）；新增条目的树插入必须在重打包函数内部做（外层持有的树引用与函数内部重新读入的不是同一棵）。
5. 备份与记录：首次注入前整包备份 `app.asar.tps.bak`；`app.asar.tps-patch.json` 记录原始 index.html（base64）与 asar 尺寸指纹。
6. 与统计图补丁联动：重打包使 chart sidecar 的绝对 offset/指纹失效，脚本自动按「文件路径 + 尺寸」重定位同步；反向无影响（统计图是同长度覆盖，不改 offset）。

### 升级 / 回退 / 排障

| 现象 | 处理 |
|---|---|
| 升级后胶囊消失 | app.asar 被覆盖，重跑 `--tps-footer`（注入源默认 skill 自带 zcode-tps.js） |
| 重启后无胶囊 | `--tps-footer --check` 看 state；渲染进程 console 查 `window.__ztps` 是否存在 |
| console 出现 CSP 拦截报错 | 当前版本 index.html 无 CSP；若未来版本加了，需同步放宽 `script-src` 允许同目录脚本 |
| 指标一直只有「● 时间」 | usage.delta 未关联到轮（看 `window.__ztpsTurns` 里轮的 out/lastUsageAt 是否为空）；版本升级导致帧结构变化时，用 `window.__ztpsPort` 旁路监听原始帧比对字段 |
| tok/s 不出现 | 该轮从未有过文本流（纯工具调用轮）时无速度可算，属预期；有文本流后静默期（工具执行）保持最近值 |
| 想换脚本逻辑 | 改 zcode-tps.js 后 `--tps-footer --revert && --tps-footer` 重打（幂等） |
