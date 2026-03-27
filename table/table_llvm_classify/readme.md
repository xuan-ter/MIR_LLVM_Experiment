# 分类分层实验矩阵说明 (Classified Experiment Matrix)

本文档说明了 `c:\Users\21101\Desktop\实验\Ablation experiment\table_llvm_classify\` 目录下 CSV 文件的结构。
这些矩阵是按照 **7 大 LLVM 功能类别** 拆分生成的，每个文件包含了该类别下的 **Single Disable (LLVM)** 和 **Double Disable (LLVM + MIR)** 实验配置。

---

## 1. 文件列表

共生成 7 个 CSV 文件，对应 7 个分类：

1.  `experiment_matrix_Vectorization.csv` (向量化)
2.  `experiment_matrix_Loop.csv` (循环优化)
3.  `experiment_matrix_ControlFlow.csv` (控制流)
4.  `experiment_matrix_Memory.csv` (内存优化)
5.  `experiment_matrix_DataFlow.csv` (数据流)
6.  `experiment_matrix_Pipeline_Profile_LTO.csv` (管线/画像/链接期)
7.  `experiment_matrix_CodeGen.csv` (代码生成)

## 2. 实验配置类型 (Type)

每个 CSV 文件内包含以下三种类型的实验：

1.  **Baseline (1组)**:
    *   **Type**: `Baseline`
    *   **Description**: 默认全开。
    *   **RUSTFLAGS**: 空。

2.  **Single_Disable_LLVM (N组)**:
    *   **Type**: `Single_Disable_LLVM`
    *   **含义**: 仅关闭该类别下的某一个 LLVM 参数。
    *   **用途**: 验证该 LLVM 参数的独立影响 (Pure Ablation)。
    *   **RUSTFLAGS**: `-C llvm-args=-disable-xxx`

3.  **Double_Disable (N × 20组)**:
    *   **Type**: `Double_Disable`
    *   **含义**: 关闭该类别下的某一个 LLVM 参数，**同时**关闭一个 MIR Pass。
    *   **用途**: 验证 LLVM 参数与 MIR Pass 的交互效应。
    *   **RUSTFLAGS**: `-C llvm-args=-disable-xxx -Z mir-enable-passes=-PassName`

## 3. 统计数据

| 类别 (Category) | LLVM参数数量 | MIR Pass数量 | 实验总数 (Baseline + Single + Double) |
| :--- | :--- | :--- | :--- |
| Vectorization | 8 | 20 | 1 + 8 + 160 = 169 |
| Loop | 8 | 20 | 1 + 8 + 160 = 169 |
| ControlFlow | 16 | 20 | 1 + 16 + 320 = 337 |
| Memory | 4 | 20 | 1 + 4 + 80 = 85 |
| DataFlow | 19 | 20 | 1 + 19 + 380 = 400 |
| Pipeline/Profile/LTO | 15 | 20 | 1 + 15 + 300 = 316 |
| CodeGen | 13 | 20 | 1 + 13 + 260 = 274 |
| **总计** | **83** | **20** | **1750** |

## 4. 使用说明

您可以根据关注的优化领域（如“循环优化”），直接选取对应的 CSV 文件进行实验。这种分拆方式有助于：
1.  **并行执行**: 可以在不同机器上同时跑不同类别的实验。
2.  **针对性分析**: 如果只关心向量化问题，只需跑 `experiment_matrix_Vectorization.csv`。

---
**生成脚本**: `c:\Users\21101\Desktop\实验\Ablation experiment\table_llvm_classify\generate_classified_matrix.py`
