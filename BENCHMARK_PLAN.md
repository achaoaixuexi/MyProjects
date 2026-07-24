# Saving-tokens-skill 基准测试计划

**生成时间**: 2026-07-23 21:42
**测试任务**: 8 个

---

## 测试方法

### 对照组（不使用 Saving-tokens-skill）
1. 开启一个新的 Copilot 对话
2. 直接输入测试 prompt
3. 完成对话，记录最终的 session ID
4. 使用 `copilot_sessionStoreSql` 查询该 session 的 token 消耗

### 实验组（使用 Saving-tokens-skill）
1. 开启一个新的 Copilot 对话
2. 先输入 `/Saving-tokens-skill` 触发 skill 诊断
3. 再输入相同的测试 prompt
4. 完成对话，记录最终的 session ID
5. 使用 `copilot_sessionStoreSql` 查询该 session 的 token 消耗

### 注意事项
- 对照组和实验组必须使用**完全相同**的测试 prompt
- 实验组中 Saving-tokens-skill 自身的 token 消耗需计入总消耗
- 每个任务完成后记录 session ID 到 `benchmark_results.json`

---

## 测试任务列表

| # | ID | 任务 | 复杂度 | 类别 | 预计轮数 |
|----|----|------|:------:|------|:------:|
| 1 | T1 | 简单代码生成 | 简单 | 代码生成 | 1-2 轮 |
| 2 | T2 | 代码审查 | 简单 | 代码审查 | 2-3 轮 |
| 3 | T3 | Bug 修复 | 中等 | 调试修复 | 3-4 轮 |
| 4 | T4 | 多文件重构 | 中等 | 重构 | 3-5 轮 |
| 5 | T5 | 项目初始化 | 复杂 | 项目初始化 | 5-8 轮 |
| 6 | T6 | 跨文件分析 | 复杂 | 代码分析 | 4-6 轮 |
| 7 | T7 | 复杂调试 | 复杂 | 调试修复 | 5-10 轮 |
| 8 | T8 | 长对话压力测试 | 高复杂 | 长对话 | 10+ 轮 |

---

## 每个任务的详细 Prompt

### T1: 简单代码生成

```
写一个 Python 函数，接收一个字符串参数，返回反转后的字符串。包含类型注解和 docstring。
```

### T2: 代码审查

```
审查以下代码的质量，指出潜在问题和改进建议：
```python
def process_data(items):
    result = []
    for i in range(len(items)):
        if items[i] != None:
            result.append(items[i].strip())
    return result
```
```

### T3: Bug 修复

```
以下代码运行时报 KeyError，请找出 bug 并修复：
```python
config = {"host": "localhost", "port": 8080}
print(f"Connecting to {config['host']}:{config['database']}")
```
```

### T4: 多文件重构

```
我有一个 Python 项目，所有模块都用 `print()` 做日志输出。请写一个方案，把项目中所有 `print()` 替换为 `logging` 模块调用。需要说明具体步骤和注意事项。
```

### T5: 项目初始化

```
请帮我创建一个 React + TypeScript 的待办事项 (Todo) 应用，包含：添加、删除、标记完成、筛选（全部/已完成/未完成）功能。使用函数组件和 hooks。
```

### T6: 跨文件分析

```
分析当前项目的 API 调用模式：找出所有 HTTP 请求的位置、使用的库、请求方法、是否有统一错误处理。生成一份 API 调用清单文档。
```

### T7: 复杂调试

```
我的 Node.js 项目 `npm run build` 失败了，报错信息是 'Module not found: Error: Can\'t resolve "@/components/Button"'。请帮我分析可能的原因，并给出排查步骤和修复方案。
```

### T8: 长对话压力测试

```
我有一个 2000 行的 Python 数据处理脚本，性能很差。请帮我：1) 分析性能瓶颈 2) 提出优化方案 3) 实现关键优化 4) 添加单元测试 5) 添加类型注解。分步骤执行，每步确认后再继续。
```
