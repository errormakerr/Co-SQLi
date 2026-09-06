# Co-SQLi 本机运行手册

本手册面向当前 HPC2 环境中的 Co-SQLi 运行。它假定代码仓库位于
`/hpc2hdd/home/hpan285/project/Co-SQLi`，项目专用 Conda 环境为 `cosqli`。

## 运行原则

- 登录节点仅用于编辑、查看状态、运行轻量检查和提交作业；训练、推理和完整实验必须通过 Slurm 在计算节点执行。
- 仓库只保存代码、版本化输入和非敏感示例。基准数据、模型、MySQL 运行时、密钥、日志和实验产物必须位于仓库外部。
- 每次运行使用新的 `run-id`。不要复用或手动修改已有运行目录；运行元数据、日志和校验和是复现实验的依据。
- 运行前后均检查工作区状态。正常验证不应改动仓库中的受版本控制文件，也不应留下 Python 字节码或 pytest 缓存。

HPC2 的登录、交互调试、分区和作业管理请参阅
[HPC2 集群使用简明指南](</hpc2hdd/home/hpan285/explore/HPC2_集群使用简明指南.md>)；
文件位置为 `/hpc2hdd/home/hpan285/explore/HPC2_集群使用简明指南.md`。

## 1. 进入项目与环境

```bash
cd /hpc2hdd/home/hpan285/project/Co-SQLi
conda activate cosqli

which python
python --version
git status --short
```

`which python` 应指向 `cosqli` 环境。批处理脚本不依赖交互式 Conda 激活，
而是通过 `COSQLI_ENV_PREFIX` 定位该环境；激活后设置它：

```bash
export COSQLI_ENV_PREFIX="$CONDA_PREFIX"
```

本手册默认 `cosqli` 已安装项目所需依赖。若 `co-sqli` 或
`co-sqli-submit` 不存在，或确实需要变更依赖，先请项目负责人确认，再在
`cosqli` 环境中安装：

```bash
python -m pip install -e '.[training,dev]'
```

该命令只修改 Conda 环境，不应创建项目内的虚拟环境。

## 2. 在仓库外准备运行输入和输出

完整运行需要以下外部资源。路径必须不在 Co-SQLi 仓库内，运行时也会拒绝
项目内的基准目录和产物目录。

| 资源 | 环境变量或配置 | 要求 |
| --- | --- | --- |
| 基座模型 | `COSQLI_BASE_MODEL_PATH` | 已存在、只读的本地模型目录 |
| 实验产物根目录 | `COSQLI_ARTIFACTS_ROOT` | 可写的外部目录；每个 `run-id` 创建一个子目录 |
| 基准目录 | `COSQLI_BENCHMARK_DIR` 或 `--benchmark-dir` | 已完成校验的外部 benchmark 目录 |
| MySQL 运行时 | `COSQLI_RUNTIME_ROOT` | 含 `mysql/my.cnf`、`mysql/data` 和可执行的 `mysqld` |
| 运行配置 | `COSQLI_CONFIG_DIR` | 可选；推荐使用仓库外的个人配置目录 |

推荐把个人配置与输出放入外部工作目录，例如：

```bash
export COSQLI_WORK_ROOT=/hpc2hdd/home/$USER/co-sqli-work
mkdir -p "$COSQLI_WORK_ROOT/config" "$COSQLI_WORK_ROOT/artifacts"

export COSQLI_CONFIG_DIR="$COSQLI_WORK_ROOT/config"
export COSQLI_ARTIFACTS_ROOT="$COSQLI_WORK_ROOT/artifacts"
export COSQLI_BASE_MODEL_PATH=/path/to/base-model
export COSQLI_RUNTIME_ROOT=/path/to/mysql-runtime
export COSQLI_BENCHMARK_DIR=/path/to/validated-benchmark
```

`COSQLI_CONFIG_DIR` 未设置时，程序读取仓库的 `config/`。为了避免改动项目，
个人部署应将以下示例复制到外部配置目录后填写非敏感地址和模型名称：

```bash
cp config/runtime_config.yaml.example "$COSQLI_CONFIG_DIR/runtime_config.yaml"
cp config/database_connection.yaml.example "$COSQLI_CONFIG_DIR/database_connection.yaml"
cp config/gpt_config.yaml.example "$COSQLI_CONFIG_DIR/gpt_config.yaml"
```

`runtime_config.yaml` 保持 `base_model_path_env: COSQLI_BASE_MODEL_PATH` 和
`artifacts_root_env: COSQLI_ARTIFACTS_ROOT` 即可。数据库密码与 LLM API 密钥
不得写入 YAML 或提交到 Git，运行前从受控方式注入：

```bash
export COSQLI_MYSQL_PASSWORD='...'
export COSQLI_LLM_API_KEY='...'
```

标准 benchmark 的构建和刷新属于独立项目
`/hpc2hdd/home/hpan285/project/Co-SQLi-Benchmark` 的职责。仅使用已验证的
benchmark；需要新建、刷新或派生 benchmark 时，先获得确认并在该仓库外操作。

## 3. 运行前的轻量检查

在登录节点可以运行不产生项目内缓存的测试：

```bash
cd /hpc2hdd/home/hpan285/project/Co-SQLi
conda activate cosqli
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
git status --short
```

测试覆盖基础配置、提示词、基准契约和实验报告逻辑，但不替代 GPU、MySQL、
模型或外部 LLM 的端到端验证。依赖变更、完整训练和 GPU 检查应在 Slurm
分配的计算节点上进行。

提交前至少确认以下事项：

```bash
test -d "$COSQLI_BENCHMARK_DIR"
test -d "$COSQLI_BASE_MODEL_PATH"
test -d "$COSQLI_RUNTIME_ROOT/mysql"
test -n "$COSQLI_ENV_PREFIX"
```

## 4. 提交实验

`co-sqli-submit` 会在外部产物根目录创建隔离的运行目录，提交 Slurm 作业。
批处理脚本会在计算节点复制 MySQL 数据目录到节点本地临时空间、启动临时
MySQL、执行实验，并在结束时写入报告和资源监控数据。

先在 `debug` 分区进行一个小规模验证（分区名和资源限制以 `sinfo -s` 的实时
结果为准）：

```bash
co-sqli-submit \
  --run-id smoke-$(date +%Y%m%d-%H%M%S) \
  --benchmark-dir "$COSQLI_BENCHMARK_DIR" \
  --num-rounds 1 \
  --num-training-sqls 16 \
  --partition debug \
  --gres gpu:1 \
  --cpus-per-task 8 \
  --mem 64G \
  --time 00:30:00
```

确认小规模运行的日志、报告和 MySQL 清理均正常后，再提交完整实验：

```bash
co-sqli-submit \
  --run-id experiment-001 \
  --benchmark-dir "$COSQLI_BENCHMARK_DIR" \
  --partition <partition> \
  --gres gpu:1 \
  --cpus-per-task 8 \
  --mem 64G \
  --time 12:00:00
```

常规对照实验优先使用命令行覆盖，而不是编辑版本化 YAML：

```bash
co-sqli-submit \
  --run-id seed-123 \
  --benchmark-dir "$COSQLI_BENCHMARK_DIR" \
  --seed 123 \
  --prompt-mode query_only \
  --partition <partition> \
  --gres gpu:1
```

`--seed`、`--num-rounds`、`--num-training-sqls` 和 `--prompt-mode` 会记录在
运行元数据中。`prompt_mode` 是运行定义的一部分，不能跨模式恢复 checkpoint。
不要在登录节点直接执行完整的 `co-sqli` 训练命令。

## 5. 查看结果与排障

提交命令会输出 Slurm job ID。常用命令：

```bash
squeue -u "$USER"
scontrol show job <job-id>
sacct -j <job-id>
```

运行产物位于：

```text
$COSQLI_ARTIFACTS_ROOT/<run-id>/
  submission.json
  run_manifest.json
  logs/slurm-<job-id>.out
  logs/slurm-<job-id>.err
  logs/mysql.err
  telemetry/resource_summary.json
  reports/
  round_*/
```

排障时先看 `logs/slurm-<job-id>.err`、`logs/mysql.err` 和
`run_manifest.json`。不要为排障直接改写仓库源码、`data/source/`、提示词或
版本化实验配置；先保留日志与完整命令，再请负责人决定后续操作。

## 6. 变更与审批边界

下列操作在执行前需要请示项目负责人：

- 改动或删除 `src/`、`prompts/`、`tests/`、`scripts/`、`data/source/`，或任何受版本控制的配置和文档；
- 新增、删除、刷新或派生 benchmark，以及修改已有 benchmark 或运行结果；
- 安装、升级或删除 `cosqli` 环境中的依赖；
- 改变模型、数据库、LLM 端点、密钥来源、Slurm 资源规格，或执行正式/高成本实验；
- 清理外部产物、checkpoint、日志或 MySQL 运行时数据。

获准进行实验时，优先在仓库外创建配置、benchmark、临时文件和输出目录；
通过环境变量和命令行参数传入差异。这样能保持项目代码逻辑不变，并使每次
实验的输入和结果可以独立追踪。

进一步的实验约束见 [实验协议](experiment-protocol.md) 与
[可复现性说明](reproducibility.md)。
