# 记忆已迁移（本目录不再承载内容）

> **请勿在此写入记忆。** 这里的内容已于 **2026-09-15** 全部并入
> **`.codebuddy/memory/`**，那才是本仓库的**唯一真值源**。

## 为什么要合并
仓库里曾经同时存在两套 AI 记忆目录（`.workbuddy/memory/` 与 `.codebuddy/memory/`），
内容**有重叠也有分歧** —— 同一份 `MEMORY.md` 的前端章节一度出现两个互相矛盾的版本
（一套写着"零构建原生三件套"，另一套已是 Vue 3 + Tailwind v4）。继续并存只会持续分叉。

## 现在该读哪里
| 想看什么 | 去哪里 |
|---|---|
| 长期记忆（项目约定、环境、架构、踩坑） | **`.codebuddy/memory/MEMORY.md`** |
| 某天的具体工作与决策 | **`.codebuddy/memory/YYYY-MM-DD.md`** |

原有两个日记文件已并入同名日记：
- `2026-09-13.md`（Dockerfile 多阶段构建 / CI）→ `.codebuddy/memory/2026-09-13.md`
- `2026-09-14.md`（目录监听 + 活动日志实现、踩坑）→ 追加进 `.codebuddy/memory/2026-09-14.md` 末尾

## 忽略规则（保持不变）
`.workbuddy/*` + `!.workbuddy/memory/`
—— 即只有 `memory/` 入库，其余本机状态忽略。对 `.codebuddy/` 也采用同样的对称规则。
