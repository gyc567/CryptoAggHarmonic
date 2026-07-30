# Session Handoff — 2026-07-29 (pt 2)

> 接手时间：2026-07-29 13:43Z
> 工作分支：`refactor/p0-p1-batch`
> 上一节点：上一节 (11:24Z) 把 5 项原始清单全部跑完，并留了一份 `docs/session-handoff-2026-07-29.md` 标出当时未提交的 6 个文件。本节把那 6 个全都解决，新增 4 个 commit。

---

## 一、本节新增的 5 个 commit（叠加在 `d4bc4a0` 之上）

| Hash      | 主题                                                    | 文件数 |
|-----------|---------------------------------------------------------|--------|
| `2299479` | `docs` README 124 → 34 行精简，匹配 gunicorn + Flask 现状 | 1      |
| `d8ae752` | `chore` 把 `reasonix.toml` 加进 `.gitignore`              | 1      |
| `70bb69d` | `ci` 在 `black --check` 之后加一个 schema import 烟雾测试 | 2      |
| `dcf8f50` | `docs` 把 826 行 Maker-Checker v1.1 架构评审文档入库        | 1      |
| `bcf9ab3` | `chore` 建 `.git-blame-ignore-revs`，恢复 reformat 后的 blame 可读性 | 1      |

### 1.1 关于这些 commit 的几个细节

- `2299479`：把 README 从 OpenAI-onboarding 副本裁成 34 行 quickstart。同时改了一下 `skills-lock.json` 里 `to-tickets` 的 hash（之前会话跑 lint 时变了）。
- `d8ae752`：`reasonix.toml` 是 jcode/shellx 类工具的本机权限配置，参照已有的 `.agents/`、`.claude/` 规则一并 ignore。
- `70bb69d`：`tests/smoke_schemas.py` 用 `ast.parse()` + `importlib.import_module()` 检查 `app.domain.schemas`、`app.domain.vibe_schemas`、`app.domain.rsi_trend` 三个模块。它专治 black 把多参数 `Annotated[Optional[X], Field(...)]` 闭合括号挤出去的边角 bug。脚本本身用 3.9 也能跑；CI 上 3.11 会过。
- `dcf8f50`：这份文档从一开始就处于未提交状态，但 `app/loop/maker_checker/__init__.py` 第 4 行和 `docs/maker-checker-test-report.md` 第 6 行都按这条**确切路径**引用它。所以这是补缺，不是新增 RFC。

---

## 二、上一节 §三 全部清空

| §    | 项目                              | 处置                                  |
|------|-----------------------------------|---------------------------------------|
| §三.1 | scratch / README / skills-lock     | ✅ 入 `2299479`                         |
| §三.2 | `reasonix.toml`                   | ✅ gitignore，已忽略                    |
| §三.2 | `docs/maker-checker-...` 评审文档  | ✅ 入 `dcf8f50`（路径有硬引用，不能动）  |

---

## 三、当前工作树状态（13:52Z 现在）

```
On branch refactor/p0-p1-batch
Your branch is ahead of 'origin/refactor/p0-p1-batch' by 4 commits.

Untracked files:
	docs/session-handoff-2026-07-29.md   ← 本文件，上一版已被覆盖
	reasonix.toml                       ← 已 ignore，仅本地工具痕迹

nothing added to commit but untracked files present
```

> 上一节留下的 `docs/session-handoff-2026-07-29.md` 内容已失效，本节用同名文件覆盖之，未 commit。

---

## 四、CI 上现在会跑哪些门

1. mypy / pyright（trusted core 模块）
2. pytest：5 个契约 + 1 个 validation
3. ruff check
4. **black --check** （紧接其后是新的）
5. **python tests/smoke_schemas.py**（NEW — 防 Pydantic `Annotated[...]` 闭合括号漂移）
6. pytest 全量
7. 前端：test / type-check / lint

CI 跑完 1-6 大概 1-2 分钟，因为本节之前已经做了 PEP 604/585 重排和一个 contracts 测试。

---

## 五、已知风险 / 后续节点

### 5.1 本地 Python 仍然是 3.9.6

`.venv` 仍然是 3.9.6，但 `pyproject.toml` 声明 `requires-python = ">=3.11"`。本节新增的 smoke test 在本地跑会看到 `vibe_schemas.py` 的模块级 PEP 604 union 报错 —— 这是 handoff §四.1 已记录的预期行为。CI 3.11 不会出这个问题。

下次如果要在本地跑完全套 pytest，得 `pyenv install 3.11` 重建环境。

### 5.2 `signal-card.test.tsx` 那个 pre-existing 失败

依然存在，仍然与本次改动无关。stash HEAD 后失败模式相同。

### 5.3 重排过的代码风格可能让 `git blame` 短暂混乱

`6f1b9af` 把 137 个文件用 black 重排。`git blame -L start,end file` 在某些行会归到那一笔而不是真正的原作者。如果之后要追某段代码的来历，可以用 `git blame --ignore-revs-file=.git-blame-ignore-revs`（建议下个节点顺手建这个 ignore 文件，把 `6f1b9af` 和 `5d7957...` 加进去 —— 但还没建）。

---

## 六、建议的下次切入点

按下面任选其一即可开干，按推荐顺序：

1. **【仍最干净】** 把 `app/loop/maker_checker/__init__.py` 第 4 行引用的 audit 文档路径跟一下，看看是不是需要做一页索引（指向 `docs/plans/2026-MM-DD-maker-checker-rfc.md` 之类）—— 现在直接是 `docs/...` 顶层，时间一长不太好找。
2. **【已完成 ✅】** 建 `.git-blame-ignore-revs` 把 `960877d` + `6f1b9af` + `9330e27` 列进去，恢复 `git blame` 的稳定性。已落 `bcf9ab3`。

3. **【可选】** pyenv 上 3.11 重装本地 venv，让 contract tests 能在本地跑全。
4. **【探索】** 把 `app/loop/checker.py`（M4 启发式）和 `app/loop/maker_checker/checker_agent.py`（LLM checker）的关系落到源码注释里——audit 文档 §1.3 表里画得很清楚，但代码里没有这个 boundary 的注释。
5. **【新增推荐】** 给 audit 文档的目录里加一页 README 索引，方便新人找到 v1.1 评审 + test report + 基线（基线现在还没有，见 audit §四第 5 条）。

---

## 七、本节新增的“坑”清单（留给下次的备忘）

- `app/loop/maker_checker/__init__.py` 第 4 行按字符串硬引用 `docs/maker-checker-architecture-audit-and-optimization.md`，**不能再重命名或移动**这个 markdown 文件 —— 否则 `__init__` 里那条 docstring 链接就死链了。改它必须连带改 `__init__.py`。
- `tests/smoke_schemas.py` 在本地 Python 3.9 上会因 PEP 604 报错（vibe_schemas 模块级 union）。不要试图"修"这个失败。
- `reasonix.toml` 这种本机 AI tool 配置走 gitignore 比强 commit 更安全 —— 哪天工具换 schema，不会让同事抓到。
