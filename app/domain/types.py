"""教学领域基础类型。"""

from typing import Literal


Level = Literal["weak", "mid", "strong"]
DifficultyLevel = Literal["simple", "mid", "hard"]
ErrorType = Literal["审题", "概念", "计算", "跳步", "粗心", "漏根", "无错"]
