"""当前题的分级提示策略。"""

from __future__ import annotations

from app.domain.answer_template import build_template


def build_hint(question: dict, level: int) -> str | None:
    """按提示等级生成不泄露最终答案的引导。"""
    if level <= 0:
        return None
    template = build_template(question["params"]) if question.get("params") else None
    design_id = (question.get("params") or {}).get("design_id", "")

    if level == 1:
        if design_id == "rectangle":
            return "先根据题意写出长和宽的表示，再利用面积关系列方程。"
        if design_id == "consecutive_even":
            return "先设较小的偶数为 x，再表示与它相邻的下一个偶数。"
        if design_id == "root_relation":
            return "先回忆两根和、两根积与系数的关系，再求根。"
        if design_id == "multi_step":
            return "先观察系数是否有公因数，能化简就先化简。"
        return "先把方程整理成便于配方或分解的常见形式。"

    if template:
        if level == 2:
            return f"先完成这一步：{template['blanks'][0]['basis']}"
        next_blank = template["blanks"][min(2, len(template["blanks"]) - 1)]
        return f"继续处理当前步骤：{next_blank['basis']} 检查符号和运算顺序。"

    return "按题意先设未知数，再建立等量关系，最后求解并检查结果是否合理。"
