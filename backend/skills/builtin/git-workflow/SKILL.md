---
name: "git-workflow（Git 工作流）"
lang: zh
translated: machine
source: backend/skills/en-originals/git-workflow/SKILL.md
description: >-
  Git 工作流、分支策略与版本控制最佳实践方面的专家指导。凡是在管理仓库、解决冲突、或为团队立下一套工作规矩时，
  都该用它。
tags: [git, version-control, branching, workflow, collaboration]
triggers:
  - "用户提到 git"
  - "用户提到分支"
  - "用户提到合并冲突"
  - "用户提到版本控制"
  - "用户提到提交、tag、变基或发布"
  - "用户询问如何开一个 pull request，或如何把它合入主干"
# `pull request` 以前在这里和 `code-review` 里都是一个裸触发词，于是“评审某个 PR”的请求会同时命中两者，
# 目录只能让模型自己去猜。评审是 code-review 的职责；本技能管的是 PR 外围的机制
# （分支、合并、冲突、发布），也就是上面这行措辞现在所表达的范围。
allowed-tools: [filesystem, shell]
author: LangConfig
---

你是 Git 工作流与版本控制方面的专家。帮助用户建立并维持有效的 Git 实践。

> **与 `code-review` 的分界。** 本技能讲的是机制：分支、合并、变基、冲突、提交、标签、发布，
> 以及如何开一个 pull request、如何把它合入主干。评审的*内容*——在 diff 里看什么、安全、性能、
> 可维护性——归 `code-review`。用户说“评审这个 PR”，用 `code-review`；用户问“我该怎么把它并进去”，
> 用本技能。

### 分支策略

#### 1. GitHub Flow（多数团队推荐）
```
main (protected)
  └── feature/add-user-auth
  └── feature/payment-integration
  └── fix/login-bug
```

**规则：**
- `main` 始终处于可部署状态
- 从 `main` 切出特性分支
- 准备好被评审时开 PR
- 批准后合并回 `main`
- 合并之后立即部署

**适用场景：** 小团队、持续部署、Web 应用

#### 2. GitFlow（发布周期复杂）
```
main (production)
  └── develop (integration)
        └── feature/new-feature
        └── release/v1.2.0
              └── hotfix/critical-bug
```

**适用场景：** 按计划发布、生产环境同时跑多个版本

#### 3. 主干开发（Trunk-Based Development，高节奏团队）
```
main (trunk)
  └── short-lived feature branches (< 2 days)
```

**适用场景：** 有经验的团队、CI/CD 过硬、用功能开关控制上线

### 分支命名约定

```bash
# Feature branches
feature/user-authentication
feature/JIRA-123-payment-gateway

# Bug fixes
fix/login-redirect-loop
fix/JIRA-456-null-pointer

# Hotfixes (production emergencies)
hotfix/security-vulnerability
hotfix/v1.2.1-critical-fix

# Release branches
release/v1.2.0
release/2024-q1

# Experimental
experiment/new-algorithm
spike/performance-testing
```

### 提交信息规范

#### Conventional Commits 格式
```
<type>(<scope>): <subject>

<body>

<footer>
```

**类型（type）：**
- `feat`：新功能
- `fix`：缺陷修复
- `docs`：仅文档改动
- `style`：代码风格（格式化、分号等）
- `refactor`：既不修缺陷也不加功能的代码改动
- `perf`：性能优化
- `test`：新增或更新测试
- `chore`：维护性杂务
- `ci`：CI/CD 相关改动

**示例：**
```bash
feat(auth): add OAuth2 Google login

Implement Google OAuth2 authentication flow with:
- Token refresh handling
- Profile sync on first login
- Session persistence

Closes #123

---

fix(api): prevent null pointer in user lookup

Check for undefined user before accessing properties.
Added defensive null checks throughout the auth flow.

Fixes #456
```

### 常见 Git 操作

#### 变基与合并
```bash
# Rebase: Clean, linear history (use for feature branches)
git checkout feature/my-feature
git rebase main
git push --force-with-lease  # Safe force push

# Merge: Preserves history (use for shared branches)
git checkout main
git merge --no-ff feature/my-feature
```

#### 交互式变基（清理历史）
```bash
# Squash last 3 commits
git rebase -i HEAD~3

# In editor:
pick abc1234 First commit
squash def5678 Second commit
squash ghi9012 Third commit
```

#### 暂存工作现场
```bash
# Save current changes
git stash push -m "WIP: user auth"

# List stashes
git stash list

# Apply and remove
git stash pop

# Apply specific stash
git stash apply stash@{2}
```

#### 拣选提交（cherry-pick）
```bash
# Apply specific commit to current branch
git cherry-pick abc1234

# Cherry-pick without committing
git cherry-pick --no-commit abc1234
```

### 解决合并冲突

#### 逐步流程
```bash
# 1. Start merge/rebase
git merge feature-branch
# CONFLICT message appears

# 2. Check status
git status
# Shows conflicted files

# 3. Open conflicted file, find markers:
<<<<<<< HEAD
current branch changes
=======
incoming branch changes
>>>>>>> feature-branch

# 4. Edit to resolve (remove markers, keep correct code)

# 5. Mark as resolved
git add <resolved-file>

# 6. Complete merge
git merge --continue
# or
git commit
```

#### 使用合并工具
```bash
# Configure merge tool
git config --global merge.tool vscode
git config --global mergetool.vscode.cmd 'code --wait $MERGED'

# Launch merge tool
git mergetool
```

### 撤销改动

```bash
# Undo last commit, keep changes staged
git reset --soft HEAD~1

# Undo last commit, keep changes unstaged
git reset HEAD~1

# Undo last commit, discard changes (DANGEROUS)
git reset --hard HEAD~1

# Revert a commit (creates new commit)
git revert abc1234

# Discard all local changes
git checkout -- .

# Restore deleted file
git checkout HEAD~1 -- path/to/file
```

### Pull Request 最佳实践

1. **保持 PR 小**
   - 改动控制在 400 行以内
   - 单一职责
   - 既好评审，也好回滚

2. **写好 PR 描述**
   ```markdown
   ## Summary
   Brief description of changes

   ## Changes
   - Added user authentication
   - Updated database schema
   - Added unit tests

   ## Testing
   - [ ] Unit tests pass
   - [ ] Manual testing completed
   - [ ] No console errors

   ## Screenshots
   (if UI changes)
   ```

3. **有分寸地请求评审**
   - 圈上真正相关的评审者
   - 为复杂改动补足上下文
   - 及时回应反馈

### Git 别名（提效）

```bash
# Add to ~/.gitconfig
[alias]
    co = checkout
    br = branch
    ci = commit
    st = status
    unstage = reset HEAD --
    last = log -1 HEAD
    visual = !gitk
    lg = log --oneline --graph --decorate
    amend = commit --amend --no-edit
    wip = !git add -A && git commit -m "WIP"
    undo = reset HEAD~1 --mixed
```
