"""模板填空（A：程序生成 + 逐空判定）。

设计定稿（A 拍板）：
- 模板由程序按题型套路生成，LLM 不参与模板（spec §7 红线延伸）
- schema 是稳定契约（两种空位：choice / expression），供给方可替换：
  固定套路题型用 TemplateBuilder；多路径题走题库自带或 LLM 起草+程序校验
- 逐空判定全在程序层，第一个错的空即断点
V2 仅支持一元二次方程（配方法路径）；新题型注册新 builder。
"""

import zlib

from app.domain.grading import compute_answer, extract_numbers

BLANK_TOLERANCE = 0.01
_CHOICE_LETTERS = ("A", "B", "C", "D")


def _choice(
    basis: str, options: list[str], correct_index: int, seed: int,
) -> dict:
    """构造选项顺序有变化的单选题。"""
    correct_text = options[correct_index]
    offset = seed % len(options)
    ordered = options[offset:] + options[:offset]
    return {
        "kind": "choice",
        "basis": basis,
        "options": ordered,
        "answer_index": ordered.index(correct_text),
    }


def _completion_blanks(
    square_add: float, after_sqrt: float, valid_roots: list[float],
    start: int = 3,
) -> tuple[list[dict], list[str]]:
    blanks = [
        {
            "id": f"b{start}", "kind": "expression",
            "basis": "配方：方程两边应同时加上哪一个数？",
            "expected": square_add,
        },
        {
            "id": f"b{start + 1}", "kind": "expression",
            "basis": "配方完成后，等号右边的值是多少？",
            "expected": after_sqrt,
        },
    ]
    if len(valid_roots) == 1:
        blank_id = f"b{start + 2}"
        blanks.append({
            "id": blank_id, "kind": "expression",
            "basis": "取符合题意的根 x =",
            "expected": valid_roots[0],
        })
        return blanks, [blank_id]
    root_ids = [f"b{start + 2}", f"b{start + 3}"]
    blanks.extend([
        {
            "id": root_ids[0], "kind": "expression",
            "basis": "求根：写出较小的根 x =",
            "expected": min(valid_roots),
        },
        {
            "id": root_ids[1], "kind": "expression",
            "basis": "求根：写出较大的根 x =",
            "expected": max(valid_roots),
        },
    ])
    return blanks, root_ids


def build_template(params: dict) -> dict:
    """按题型结构生成作答模板，并通过 answer_blank_ids 标记最终答案空位。"""
    a, b, c = params["a"], params["b"], params["c"]
    x1, x2 = compute_answer(a, b, c)
    design_id = params.get("design_id", "")
    if params.get("valid_roots"):
        valid_roots = [float(v) for v in params["valid_roots"]]
    elif design_id == "rectangle":
        valid_roots = [root for root in (x1, x2) if root > 0]
    else:
        valid_roots = [x1, x2]
    half = b / (2 * a)
    right_after_move = -c / a
    square_add = half * half
    after_sqrt = square_add - c / a
    seed = zlib.crc32(f"{a}:{b}:{c}:{design_id}".encode("utf-8"))

    if design_id == "root_relation":
        root_sum = -b / a
        root_product = c / a
        first = _choice(
            "根据根与系数关系，x₁+x₂ 等于多少？",
            [f"{root_sum:g}", f"{-root_sum:g}", f"{root_product:g}"],
            0, seed,
        )
        second = {
            "id": "b2", "kind": "expression",
            "basis": "根据根与系数关系，x₁x₂ 等于多少？",
            "expected": root_product,
        }
        blanks = [
            {"id": "b1", **first},
            second,
            {
                "id": "b3", "kind": "expression",
                "basis": "写出较小的根 x =", "expected": min(valid_roots),
            },
            {
                "id": "b4", "kind": "expression",
                "basis": "写出较大的根 x =", "expected": max(valid_roots),
            },
        ]
        answer_blank_ids = ["b3", "b4"]
    elif design_id == "rectangle":
        if a == 1:
            correct_length = f"x + {b:g}"
            options = [correct_length, f"x + {b + 1:g}", f"2x + {b:g}"]
        else:
            correct_length = f"{a:g}x + {b:g}"
            options = [correct_length, f"{a:g}x", f"{a + b:g}x"]
        first = _choice("设宽为 x 米，长应表示为？", options, 0, seed)
        second = _choice(
            "根据长方形面积关系，应列出的方程是？",
            [
                f"x({correct_length}) = {-c:g}",
                f"x + ({correct_length}) = {-c:g}",
                f"{correct_length} = {-c:g}",
            ],
            0, seed + 1,
        )
        third = {
            "id": "b3", "kind": "expression",
            "basis": "由面积关系化为一般形式，再两边同时除以二次项系数并移项后，等号右边是多少？",
            "expected": right_after_move,
        }
        root_blanks, answer_blank_ids = _completion_blanks(
            square_add, after_sqrt, valid_roots, start=4,
        )
        blanks = [
            {"id": "b1", **first},
            {"id": "b2", **second},
            third,
            *root_blanks,
        ]
    elif design_id == "consecutive_even":
        first = _choice(
            "设较小的偶数为 x，另一个偶数应表示为？",
            ["x + 2", "x + 1", "2x"], 0, seed,
        )
        product = -c
        second = _choice(
            "根据两个偶数的乘积关系，应列出的方程是？",
            [
                f"x(x + 2) = {product:g}",
                f"x + (x + 2) = {product:g}",
                f"x + 2 = {product:g}",
            ],
            0, seed + 1,
        )
        third = {
            "id": "b3", "kind": "expression",
            "basis": "将“两数乘积”化为一般形式并移项后，等号右边是多少？",
            "expected": right_after_move,
        }
        root_blanks, answer_blank_ids = _completion_blanks(
            square_add, after_sqrt, valid_roots, start=4,
        )
        blanks = [
            {"id": "b1", **first},
            {"id": "b2", **second},
            third,
            *root_blanks,
        ]
    elif design_id == "multi_step":
        first = _choice(
            "先化简方程，两边应同时除以哪个数？",
            [f"{a:g}", f"{2 * a:g}", f"{a * a:g}"], 0, seed,
        )
        second = {
            "id": "b2", "kind": "expression",
            "basis": "约分并移项后，等号右边是多少？",
            "expected": right_after_move,
        }
        root_blanks, answer_blank_ids = _completion_blanks(
            square_add, after_sqrt, valid_roots, start=3,
        )
        blanks = [
            {"id": "b1", **first}, second,
            *root_blanks,
        ]
    else:
        if a != 1:
            first = _choice(
                "将二次项系数化为 1，应该怎么做？",
                [f"两边同时除以 {a:g}", f"两边同时乘以 {a:g}", "直接开平方"],
                0, seed,
            )
        else:
            first = _choice(
                "移项时应把哪一项移到等号右边？",
                ["常数项", "一次项", "二次项"], 0, seed,
            )
        second = {
            "id": "b2", "kind": "expression",
            "basis": "移项后，方程等号右边应填什么数？",
            "expected": right_after_move,
        }
        root_blanks, answer_blank_ids = _completion_blanks(
            square_add, after_sqrt, valid_roots, start=3,
        )
        blanks = [
            {"id": "b1", **first}, second,
            *root_blanks,
        ]
    for blank in blanks:
        blank.setdefault("options", None)
        blank.setdefault("answer_index", None)
        blank.setdefault("expected", None)
    return {"blanks": blanks, "answer_blank_ids": answer_blank_ids}


def _judge_choice(blank: dict, student_result: str) -> bool:
    text = student_result.strip().upper()
    accepted = {str(blank["answer_index"] + 1), _CHOICE_LETTERS[blank["answer_index"]]}
    return text in accepted


def _judge_expression(blank: dict, student_result: str) -> bool:
    expected = blank["expected"]
    return any(
        abs(value - expected) < BLANK_TOLERANCE
        for value in extract_numbers(student_result)
    )


def judge_blanks(template: dict, student_steps: list) -> list:
    """逐空判定：student_steps 与模板空位按序对应；多出的步骤（最终作答）忽略。"""
    results = []
    for blank, step in zip(template["blanks"], student_steps):
        student_result = (step.get("result") or "").strip()
        if blank["kind"] == "choice":
            is_correct = _judge_choice(blank, student_result)
        else:
            is_correct = _judge_expression(blank, student_result)
        results.append({
            "blank_id": blank["id"],
            "basis": blank["basis"],
            "kind": blank["kind"],
            "student_result": student_result,
            "is_correct": is_correct,
        })
    return results


def first_wrong_blank(blank_results: list) -> dict | None:
    """断点定位：第一个判错的空；全对返回 None。"""
    return next((r for r in blank_results if not r["is_correct"]), None)


def breakpoint_label(blank_results: list) -> str | None:
    """给学生看的断点位置，不暴露内部空位编号。"""
    for index, result in enumerate(blank_results, start=1):
        if not result["is_correct"]:
            return f"第 {index} 个作答项（{result['basis']}）"
    return None
