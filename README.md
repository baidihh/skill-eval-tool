# Skill Lab · 技能评测工作台

本机网页工具，用于管理评测集、记录专家执行结果、检查业务规则、人工复核与比较 Skill 版本。技术基线见 [技术方案 v0.2](docs/技术方案-v0.2.md)。

界面按 AgentKit 技能评测导览页复刻，包含技能详情（基本信息/技能详情/版本管理/技能评测）、评测集、发起评测、评测报告、评测洞察与版本对比。报告展示六维雷达和展示用综合得分；综合得分只汇总存在已判定检查的维度，不参与门禁判定，与需求 §8.2 的差异按本轮产品决定执行。

当前开发版本可用于演示和离线评测联调。公司平台的真实调用需要提供经核实的接口与测试环境；界面的演示结果不代表真实专家已经运行。

## 本机启动

需要 macOS/Linux、Python 3.9+、Node.js 22 和 npm。安装过程会从 Python 与 npm 包仓库下载依赖。

在终端执行：

```sh
cd '/Users/wh/Documents/workspace/ai_mac/开发/评测工具-dy/code'
python3 setup.py
python3 start.py
```

打开 <http://127.0.0.1:8765>。首次为空数据，在页面点击初始化演示数据，可创建明确标记为 `demo` 的退款审核样例，查看错误版本和修复版本的报告与对比。

`setup.py` 为后端创建 `backend/.venv` 并按锁定要求安装依赖，前端使用 `npm ci` 和生产构建。已有依赖时可运行 `python3 setup.py --skip-install` 仅重新构建页面。

```sh
# 自定义端口或数据目录
python3 start.py --port 8765 --data-dir '/private/tmp/skill-lab-data'
```

服务只监听本机回环地址。按 Ctrl+C 同时停止 API 和后台 worker；worker 异常退出会有限重启，连续异常时启动器退出并显示错误。不要同时用其他命令启动同一数据目录的 worker。

## 使用顺序

1. 查看评测对象，登记 Skill 与镜像专家配置。
2. 在评测集中编辑题目、执行资料和仅供裁判使用的参考资料，校验后发布固定版本。
3. 创建实验，明确区分 `demo`、`imported` 与 `live` 来源。
4. 查看运行结果、检查项结论、证据和判分覆盖；运行完成与业务门禁分别判断。
5. 必要时进行人工复核，保存依据和理由；报告产生新修订，旧修订仍可查看。
6. 选择两个报告修订对比。条件未知或不一致时，只能描述性并排查看。

离线导入支持 JSON 或 `manifest.json` + 附件的 ZIP。ZIP 附件须声明相对路径、大小和 SHA-256；附件只登记原始内容，不会自动成为某题有效评分证据。报告可导出固定修订 JSON、HTML 和证据 ZIP；报告 ZIP 是归档文件，不能用来冒充外部执行导入。具体格式见 `schemas` 和 `fixtures`。

公司真实接口尚未配置时，在线执行应明确拒绝启动，不会自动改用样例。演示/导入不是首期真实闭环验收的替代品。

## 数据与运维边界

默认持久数据位于 `code/.data`，不应加入 Git。服务端保存配置、实验和文件内容，浏览器仅访问本机 API。凭证不得放入评测输入、日志或导出文件。

启动器在数据目录创建实例身份，在本机临时目录保持谱系互斥锁，防止同一谱系副本同时由启动器执行。它不能阻止另一台机器运行副本，也不能使业务操作回滚。备份与恢复能力的实际实现范围见 [开发状态](docs/开发状态.md)；不要直接复制正在运行的 SQLite 主数据库文件作为完整备份。

```sh
# 目标目录必须尚不存在。运行中的服务会短暂停机维护，备份后恢复。
python3 backup.py backup '/private/tmp/skill-lab-backup-001'
python3 backup.py verify '/private/tmp/skill-lab-backup-001'
python3 backup.py restore '/private/tmp/skill-lab-backup-001' '/private/tmp/skill-lab-restored'
```

恢复仅产生离线验证副本，不启动服务或外部调用。确认原实例（包括其他机器）已停止后，才可显式执行 `python3 start.py --data-dir '/private/tmp/skill-lab-restored' --takeover`。备份必须针对由本启动器管理的数据目录，直接启动的 API/worker 不参加维护协调。当前尚无真实外部平台调用；未来接入后还需验证在途调用收尾与未知状态处理。

API/worker 只适合单人本机部署。多人共享、公司认证、远程访问和生产绑定不在当前本机启动方式内。

## 开发

前端目录为 `frontend`，后端目录为 `backend`。`start.py` 使用 `backend/.venv/bin/python` 运行 `app.main:app` 和 `app.worker`，并将前端 `dist` 路径传给 API。

```sh
cd frontend
npm run dev
```

开发前端使用 5173 端口时需同时运行后端；具体代理在 Vite 配置中定义。后端自动接口说明位于 <http://127.0.0.1:8765/docs>（以实际路由配置为准）。

代码与测试的实际验证记录由主开发流程更新，未完成的平台能力会保留明确缺口。
