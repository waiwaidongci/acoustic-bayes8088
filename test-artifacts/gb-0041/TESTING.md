# 检修排产模块测试说明（gb-0041）

本目录不混入源码，仅包含测试与本地测试替身。生产环境仍使用 MySQL8 + Redis7（见仓库根 `docker-compose.yml`）；
本地无 Docker/MySQL/Redis 时，测试用 SQLite 与进程内队列替身完成等价验证。

## 被测能力与需求对照

| 需求 | 覆盖测试 |
| --- | --- |
| 完整折外后验（每样本各类别概率向量） | `test_planning.py` 步骤1 |
| 后验 × 故障/处置损失表，每样本选免检或一种检修，整批期望损失最小 | `test_planning.py` 步骤2（DP 对 3^n 暴力枚举 oracle） |
| 两类工位剩余工时约束、并发不超订 | `test_planning.py` 步骤3/6，`test_http.py` 步骤4/5，`test_frontend.mjs` 方案二 |
| 计算期间人工占用变化即重算、确认时过期拒绝 | `test_planning.py` 步骤6，`test_http.py` 步骤5，`test_frontend.mjs` 步骤6/8 |
| 确认后锁定工时，撤销释放，重试/重复确认不重复扣工时 | `test_planning.py` 步骤5/7，`test_http.py` 步骤4/6，`test_frontend.mjs` 步骤4/5 |
| 计算或确认中断可恢复，重算不产生锁定 | `test_planning.py` 步骤9（worker 启动孤儿重入队） |
| 整批选择与工时锁定齐备才允许执行 | `test_planning.py` 步骤8，`test_http.py` 步骤7 |
| 页面可追查采用的后验、选择原因、剩余工时与口径指纹 | `test_http.py` 步骤3，`test_frontend.mjs` 步骤3 |
| 原研究照常读取（不改造旧工作流） | `test_frontend.mjs` 步骤10，`test_http.py` 全量旧端点 |

## 三层测试

### 1. 服务/算法层（SQLite + 队列替身，无网络服务）

```bash
# 依赖安装到独立目录，不污染系统 Python（Debian 受 PEP668 管理时）
python3 get-pip.py --target=/tmp/pylibs   # 仅首次，需要联网
PYTHONPATH=/tmp/pylibs python3 -m pip install --target=/tmp/pylibs \
  fastapi==0.115.6 "SQLAlchemy==2.0.36" numpy==2.1.3 scikit-learn==1.5.2 \
  PyJWT==2.10.1 redis==5.2.1 httpx uvicorn

rm -f /tmp/planning_test.db
DATABASE_URL="sqlite:////tmp/planning_test.db" REDIS_URL="fake://" \
ARTIFACT_DIR=/tmp/artifacts JWT_SECRET=test-secret \
python3 -I test_planning.py
```

`-I` 隔离模式只认脚本内 `sys.path` 注入；`harness/fakeredis.py` 提供 `rpush/blpop/from_url/ping` 语义。

### 2. HTTP 完整流程（FastAPI TestClient + 真实 worker 线程）

```bash
rm -f /tmp/planning_http.db
python3 -I test_http.py
```

覆盖 JWT 三角色权限（viewer 403、匿名 401）、全部排产生命周期、CSV 导出、审计事件与参数校验（422/409）。

### 3. 真实前端模块（Node + jsdom，自管后端子进程）

```bash
mkdir -p /tmp/webtest && cd /tmp/webtest && npm init -y >/dev/null && npm install jsdom@25
node test_frontend.mjs
```

脚本自动以独立 `TEST_RUN_ID` 启动 `harness/serve_test_app.py`（真实 uvicorn + 真实 worker 循环 + SQLite），
结束时杀掉子进程并删除一次性数据库；在 jsdom 中加载 `frontend/src` 的真实 ES Module，
模拟登录、表单提交、点击、轮询与三角色切换，共 31 项断言。
测试 fetch 包装层模拟生产 nginx 的 `/api/` 前缀重写。

## 优化器口径

- 动作：`none` 免检（0 工时）、`quick` 快速复检（占 A 工位 20 分钟/件）、`deep` 停机检修（占 B 工位 45 分钟/件）。
- 单样本动作期望损失 = Σ_类别(折外后验概率 × 该故障/动作损失表值)。
- 双约束多选背包，稀疏字典 DP 求全局最优；同损失按总占用、再按动作序列字典序确定性破平。
- 计算容量 = 工位总工时 − 人工占用 − 其他方案未释放的锁定工时；确认时再以行级锁做二次容量校验。

## 边界与已知限制

- 本地无系统库时无法启动完整 Chromium（缺 libnss3 等），故 DOM 层用 jsdom；生产路径的 nginx 反代由测试 fetch 包装等价模拟。
- 队列替身仅实现本系统用到的 Redis 接口，不是完整 Redis；并发安全的最终保证在 MySQL `SELECT ... FOR UPDATE` 与唯一约束。
- 演示损失表/工位口径为合成数据，单位与分钟数见 `backend/src/services/planning_catalog.py`。
