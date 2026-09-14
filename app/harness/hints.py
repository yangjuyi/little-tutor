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


def build_scaffold(question: dict, level: int) -> str | None:
    """生成求助后的分层脚手架；只给方法步骤，不泄露最终答案。"""
    if level <= 0:
        return None
    template = build_template(question["params"]) if question.get("params") else None
    design_id = (question.get("params") or {}).get("design_id", "")

    if level == 1:
        if template and template.get("blanks"):
            return (
                f"先完成当前步骤：{template['blanks'][0]['basis']}。"
                "只写这一步的完整式子，不要跳到最终答案。"
            )
        return "先把已知量和未知量分开，写出下一步要用的等量关系。"

    if design_id == "rectangle":
        return (
            "把过程拆成两步：先表示长和宽，再根据面积列方程；"
            "列式后先化简，再求满足题意的根。每一步只写一个等式。"
        )
    if design_id == "consecutive_even":
        return (
            "把过程拆成两步：先设较小的偶数为 x，另一个写成 x+2；"
            "再把乘积关系化成方程并移项。不要直接写最终答案。"
        )
    if design_id == "root_relation":
        return (
            "先根据两根和、两根积写出方程，再用求根方法；"
            "每一步只做一次变形，写完当前等式再进入下一步。"
        )
    if template:
        first = template["blanks"][0]["basis"]
        current = template["blanks"][min(1, len(template["blanks"]) - 1)]["basis"]
        return (
            f"把当前步骤拆成两步：先处理“{first}”，"
            f"再处理“{current}”。每一步只写一个等式。"
        )
    return "把过程拆成两步：先写等量关系，再把未知数移到一边、常数移到另一边。"
