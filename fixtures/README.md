# 离线导入样例

`import-example.json` 展示当前 JSON 导入 API 的字段，不是可直接回导的完整业务验收包。

先在界面创建/选取对象并发布评测集，把 object_id 和 dataset_id 替换为实际 ID，case_id 替换为该评测集的逻辑题目 ID。output 应来自外部执行的真实结果并与该题规则匹配。该示例的金额和资格仅演示数据结构，不代表公司的退款政策。

导入先调用 `POST /api/v1/imports` 预览，再使用返回 ID 调用 `POST /api/v1/imports/{id}/confirm`，请求体带稳定 operation_id。服务端来源固定为 imported；不能使用导入声明创建 live。

当前 JSON Schema 位于 `../schemas/import-v1.json`。ZIP 包可用同一对象作 manifest.json，并增加 attachments 数组，每项含 path、size、sha256、purpose，附件文件必须逐一匹配；可使用 code/package_io.py 的 write_package 生成。HTTP Content-Type 使用 application/zip。任意目录项、链接、路径越级、加密包和未声明附件都会拒绝。

尝试序号当前仅支持明确的 attempt_seq=1。完整资产回导、外部配置核验和分卷尚待扩展，不可将本示例当作全部 A01—A24 验收包。
