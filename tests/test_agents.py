"""Unit tests for agents.py (program layer only, no LLM calls).

Run with: .venv/Scripts/python -m unittest tests.test_agents -v
"""

import os
import unittest
from unittest import mock
from collections import Counter

from app.adapters.llm import (
    AttributionOutput,
    build_program_attribution,
    generate_question,
    get_llm,
    grade_question,
    should_skip_attribution,
)
from app.domain.grading import (
    check_is_correct,
    compute_answer,
    extract_numbers,
    pick_difficulty,
    validate_difficulty_params,
    validate_params,
)


class TestPickDifficulty(unittest.TestCase):
    """测试难度混合矩阵（spec §16.5）"""

    def test_weak_never_returns_hard(self):
        """weak 不应该出难题"""
        for _ in range(100):
            self.assertNotEqual(pick_difficulty("weak"), "hard")

    def test_weak_distribution(self):
        """weak 1000 次采样，simple 约 60% / mid 约 40%（允许 ±10%）"""
        results = [pick_difficulty("weak") for _ in range(1000)]
        counts = Counter(results)
        simple_ratio = counts["simple"] / 1000
        mid_ratio = counts["mid"] / 1000
        self.assertAlmostEqual(simple_ratio, 0.6, delta=0.1)
        self.assertAlmostEqual(mid_ratio, 0.4, delta=0.1)

    def test_strong_can_return_hard(self):
        """strong 应该可能返回 hard"""
        results = [pick_difficulty("strong") for _ in range(100)]
        self.assertIn("hard", results)

    def test_invalid_level_raises(self):
        """不合法的掌握度应该报 KeyError"""
        with self.assertRaises(KeyError):
            pick_difficulty("expert")


class TestComputeAnswer(unittest.TestCase):
    """测试程序计算答案（spec §7：不让 LLM 算）"""

    def test_two_real_roots(self):
        """x² - 5x + 6 = 0 → (x-2)(x-3) → x=2, x=3"""
        x1, x2 = compute_answer(1, -5, 6)
        self.assertEqual(x1, 3.0)
        self.assertEqual(x2, 2.0)

    def test_repeated_root(self):
        """x² - 4x + 4 = 0 → (x-2)² → x=2（重根）"""
        x1, x2 = compute_answer(1, -4, 4)
        self.assertEqual(x1, 2.0)
        self.assertEqual(x2, 2.0)

    def test_no_real_solution(self):
        """x² + 2x + 5 = 0 → 判别式 -16 < 0 → 无实数解"""
        with self.assertRaises(ValueError) as ctx:
            compute_answer(1, 2, 5)
        self.assertIn("无实数解", str(ctx.exception))

    def test_a_is_zero(self):
        """a=0 不是二次方程"""
        with self.assertRaises(ValueError) as ctx:
            compute_answer(0, 2, 3)
        self.assertIn("a 不能为 0", str(ctx.exception))

    def test_fractional_roots(self):
        """2x² + 3x - 2 = 0 → x = 0.5, x = -2"""
        x1, x2 = compute_answer(2, 3, -2)
        self.assertEqual(x1, 0.5)
        self.assertEqual(x2, -2.0)


class TestValidateParams(unittest.TestCase):
    """测试参数校验（spec §7：先校验再计算）"""

    def test_valid_params_returns_none(self):
        self.assertIsNone(validate_params(1, -5, 6))

    def test_a_zero_returns_error(self):
        result = validate_params(0, 2, 3)
        self.assertIsNotNone(result)
        self.assertIn("a 不能为 0", result)

    def test_no_solution_returns_error(self):
        result = validate_params(1, 2, 5)
        self.assertIsNotNone(result)
        self.assertIn("无实数解", result)


class TestExtractNumbers(unittest.TestCase):
    """数值提取：分数、负号、上标不误提取"""

    def test_plain_numbers(self):
        self.assertEqual(extract_numbers("x1=3, x2=2"), {3.0, 2.0})

    def test_fraction(self):
        self.assertEqual(extract_numbers("x = 1/2"), {0.5})

    def test_negative(self):
        self.assertEqual(extract_numbers("x = -3"), {-3.0})

    def test_superscript_not_extracted(self):
        # x² 的 ² 是 Unicode 上标不提取；"=0" 的 0 属于方程，会被提取为额外值
        self.assertEqual(extract_numbers("x²-5x+6=0"), {-5.0, 6.0, 0.0})

    def test_variable_subscripts_stripped(self):
        # x1/x2 的下标不是数值，剥掉后只剩真正的值
        self.assertEqual(extract_numbers("x1=3, x2=2"), {3.0, 2.0})
        self.assertEqual(extract_numbers("x₁=3.0, x₂=2.0"), {3.0, 2.0})

    def test_multi_character_subscript_stripped(self):
        # 连续下标必须整体剥掉，否则残留数字会污染根集合
        self.assertEqual(extract_numbers("x₁₂=3"), {3.0})

    def test_empty(self):
        self.assertEqual(extract_numbers(""), set())


class TestCheckIsCorrect(unittest.TestCase):
    """数值集合判对错：堵旧子串比对的假阳性/假阴性"""

    def test_both_roots_normal_keyboard(self):
        self.assertTrue(check_is_correct("x1=3, x2=2", [3.0, 2.0]))

    def test_swapped_order(self):
        self.assertTrue(check_is_correct("x1=2, x2=3", [3.0, 2.0]))

    def test_partial_answer_is_wrong(self):
        # 旧子串比对的假阳性：两根只答一个
        self.assertFalse(check_is_correct("3", [3.0, 2.0]))

    def test_wrong_value(self):
        self.assertFalse(check_is_correct("x1=3, x2=4", [3.0, 2.0]))

    def test_label_digit_not_counted_as_root(self):
        # "x2=4" 里的下标 2 不能冒充根 2
        self.assertFalse(check_is_correct("x1=3, x2=4", [3.0, 2.0]))

    def test_fraction_matches_decimal(self):
        self.assertTrue(check_is_correct("x = 1/2", [0.5]))

    def test_negative_root_needs_sign(self):
        self.assertTrue(check_is_correct("x = -3", [-3.0]))
        self.assertFalse(check_is_correct("x = 3", [-3.0]))

    def test_extra_process_numbers_ok(self):
        self.assertTrue(check_is_correct("x²-5x+6=0，所以 x=2 或 x=3", [3.0, 2.0]))

    def test_extra_root_is_rejected(self):
        self.assertFalse(
            check_is_correct("x1=1, x2=2, x3=3", [1.0, 2.0])
        )
        self.assertFalse(
            check_is_correct("x=1, 2, 99/2", [1.0, 2.0])
        )

    def test_repeated_root(self):
        self.assertTrue(check_is_correct("x = 2", [2.0, 2.0]))
        self.assertTrue(check_is_correct("x1=1.5, x2=1.5", [1.5, 1.5]))
        self.assertTrue(check_is_correct("x1=1.5", [1.5, 1.5]))

    def test_empty_answer(self):
        self.assertFalse(check_is_correct("", [3.0, 2.0]))
        self.assertFalse(check_is_correct("   ", [3.0, 2.0]))


class _FakeStructuredLLM:
    """离线替身：with_structured_output 返回固定 payload，不调真实 LLM"""

    def __init__(self, payload):
        self._payload = payload
        self.prompts = []

    def with_structured_output(self, model, method=None):
        outer = self

        class _Stub:
            @staticmethod
            def invoke(prompt):
                outer.prompts.append(prompt)
                return model(**outer._payload)

        return _Stub()


class TestGradeQuestionIntegration(unittest.TestCase):
    """grade_question 端到端（离线）：params 重算 + 数值判分"""

    QUESTION = {
        "id": "q-1",
        "kp_id": "39",
        "stem": "已知方程 x² - 5x + 6 = 0",
        "answer": "x₁=3.0, x₂=2.0",
        "params": {"a": 1.0, "b": -5.0, "c": 6.0},
    }

    AI_PAYLOAD = {
        "error_type": "无错",
        "confidence": 1.0,
        "evidence": "ok",
        "steps_analyzed": 1,
        "insufficient_evidence": False,
    }

    def _grade(self, student_result, payload=None):
        return grade_question(
            dict(self.QUESTION),
            [{"basis": "求解", "result": student_result}],
            _FakeStructuredLLM(payload or self.AI_PAYLOAD),
        )

    def test_partial_answer_rejected_even_if_ai_says_correct(self):
        # 子串时代这里会假阳性：AI 说对，程序必须推翻
        result = self._grade("3", {**self.AI_PAYLOAD, "is_correct": True})
        self.assertFalse(result["is_correct"])

    def test_attribution_schema_has_no_verdict_field(self):
        self.assertNotIn("is_correct", AttributionOutput.model_fields)

    def test_full_answer_accepted_normal_format(self):
        result = self._grade("x1=3, x2=2")
        self.assertTrue(result["is_correct"])

    def test_no_steps_cannot_force_specific_error_type(self):
        payload = {
            "error_type": "计算",
            "confidence": 0.5,
            "evidence": "推测计算错误",
            "steps_analyzed": 0,
            "insufficient_evidence": True,
        }
        result = grade_question(
            dict(self.QUESTION),
            [],
            _FakeStructuredLLM(payload),
        )
        self.assertFalse(result["is_correct"])
        self.assertEqual(result["error"]["error_type"], "未归因")
        self.assertEqual(result["error"]["confidence"], 0.0)
        self.assertTrue(result["error"]["insufficient_evidence"])

    def test_steps_are_json_bounded_and_length_limited(self):
        llm = _FakeStructuredLLM(self.AI_PAYLOAD)
        long_basis = "x" * 240
        result = grade_question(
            dict(self.QUESTION),
            [{"basis": long_basis, "result": "x=999"}],
            llm,
        )
        self.assertFalse(result["is_correct"])
        self.assertEqual(len(llm.prompts), 1)
        prompt = llm.prompts[0]
        self.assertIn('"step_no": 1', prompt)
        self.assertIn("程序判分事实", prompt)
        self.assertIn("x" * 200, prompt)
        self.assertNotIn("x" * 201, prompt)

    def test_choice_steps_include_option_context_for_llm(self):
        llm = _FakeStructuredLLM(self.AI_PAYLOAD)
        result = grade_question(
            dict(self.QUESTION),
            [{
                "basis": "选择正确的式子",
                "result": "2",
                "options": ["x + 2", "x + 3", "2x"],
                "selected_option_text": "x + 3",
            }],
            llm,
        )
        self.assertFalse(result["is_correct"])
        prompt = llm.prompts[0]
        self.assertIn('"selected_option_text": "x + 3"', prompt)
        self.assertIn('"options": [', prompt)


class _ExplodingStructuredLLM:
    """LLM 挂掉的离线替身：结构化输出调用必炸（测全局异常兜底）"""

    def with_structured_output(self, model, method=None):
        class _Stub:
            @staticmethod
            def invoke(prompt):
                raise RuntimeError("api down")

        return _Stub()


class _TimeoutStructuredLLM:
    """LLM 超时替身：验证超时按归因失败降级，不影响程序判分事实。"""

    def with_structured_output(self, model, method=None):
        class _Stub:
            @staticmethod
            def invoke(prompt):
                raise TimeoutError("llm request timed out")

        return _Stub()


class TestLlmRuntimeConfig(unittest.TestCase):
    def tearDown(self):
        get_llm.cache_clear()

    def test_default_timeout_and_retries(self):
        get_llm.cache_clear()
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_TIMEOUT_SECONDS": "",
                "OPENAI_MAX_RETRIES": "",
            },
            clear=False,
        ):
            llm = get_llm("grade")
        self.assertEqual(llm.request_timeout, 30.0)
        self.assertEqual(llm.max_retries, 2)

    def test_timeout_and_retries_can_be_overridden(self):
        get_llm.cache_clear()
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_TIMEOUT_SECONDS": "12.5",
                "OPENAI_MAX_RETRIES": "1",
            },
            clear=False,
        ):
            llm = get_llm("grade")
        self.assertEqual(llm.request_timeout, 12.5)
        self.assertEqual(llm.max_retries, 1)

    def test_invalid_timeout_is_rejected(self):
        get_llm.cache_clear()
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_TIMEOUT_SECONDS": "0",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "OPENAI_TIMEOUT_SECONDS"):
                get_llm("grade")

    def test_invalid_retry_count_is_rejected(self):
        get_llm.cache_clear()
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MAX_RETRIES": "-1",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "OPENAI_MAX_RETRIES"):
                get_llm("grade")


class TestGradeFallback(unittest.TestCase):
    """P2 LLM 兜底：归因挂掉时保住程序判分事实，降级为仅程序证据"""

    QUESTION = {
        "id": "q-1",
        "kp_id": "39",
        "stem": "已知方程 x² - 5x + 6 = 0",
        "answer": "x₁=3.0, x₂=2.0",
        "params": {"a": 1.0, "b": -5.0, "c": 6.0},
    }

    def _grade(self, student_result):
        return grade_question(
            dict(self.QUESTION),
            [{"basis": "求解", "result": student_result}],
            _ExplodingStructuredLLM(),
        )

    def test_wrong_answer_falls_back_to_program_verdict(self):
        result = self._grade("3")
        self.assertFalse(result["is_correct"])                     # 程序事实保住
        self.assertEqual(result["error"]["error_type"], "未归因")
        self.assertEqual(result["error"]["evidence_source"], "program")
        self.assertTrue(result["error"]["insufficient_evidence"])

    def test_correct_answer_falls_back_cleanly(self):
        result = self._grade("x1=3, x2=2")
        self.assertTrue(result["is_correct"])
        self.assertEqual(result["error"]["error_type"], "无错")
        self.assertEqual(result["error"]["evidence_source"], "program")

    def test_timeout_falls_back_without_losing_program_facts(self):
        result = grade_question(
            dict(self.QUESTION),
            [{"basis": "求解", "result": "3"}],
            _TimeoutStructuredLLM(),
        )
        self.assertFalse(result["is_correct"])
        self.assertEqual(result["error"]["error_type"], "未归因")
        self.assertEqual(result["error"]["evidence_source"], "program")
        self.assertTrue(result["error"]["insufficient_evidence"])

    def test_unfilled_prefix_blocks_llm_attribution(self):
        program_result = {
            "final_answer_correct": False,
            "process_correct": False,
            "attribution_blocked_by_unfilled": True,
            "steps": [{"unfilled": True}],
        }
        self.assertTrue(
            should_skip_attribution(program_result, program_result["steps"])
        )
        attribution = build_program_attribution(
            dict(self.QUESTION),
            program_result,
            "fallback",
        )
        self.assertEqual(attribution["error_type"], "未归因")
        self.assertEqual(attribution["confidence"], 0.0)
        self.assertTrue(attribution["insufficient_evidence"])


class TestValidateDifficultyParams(unittest.TestCase):
    """难度带校验（B2：难度受控化）"""

    def test_simple_valid(self):
        self.assertIsNone(validate_difficulty_params(1, -6, 8, "simple"))

    def test_simple_rejects_leading_coefficient(self):
        result = validate_difficulty_params(2, -7, 3, "simple")
        self.assertIn("不在 simple 难度范围", result)

    def test_rejects_non_integer_coefficients(self):
        result = validate_difficulty_params(1, -5.5, 6, "simple")
        self.assertIn("系数必须为整数", result)

    def test_rejects_irrational_roots(self):
        # x² + x - 1 = 0：判别式 5 不是完全平方数
        result = validate_difficulty_params(1, 1, -1, "simple")
        self.assertIn("完全平方数", result)

    def test_mid_valid_with_clean_completion(self):
        # 2x² - 8x + 6 = 0 → 除以 2 后 x² - 4x + 3，配方中间值均为整数
        self.assertIsNone(validate_difficulty_params(2, -8, 6, "mid"))

    def test_mid_rejects_unclean_completion(self):
        # 2x² - 7x + 3 = 0 的根简单，但配方法会出现 3.0625
        result = validate_difficulty_params(2, -7, 3, "mid")
        self.assertIn("整数", result)

    def test_mid_rejects_a_out_of_band(self):
        result = validate_difficulty_params(6, -13, 6, "mid")
        self.assertIn("不在 mid 难度范围", result)

    def test_rejects_negative_discriminant(self):
        result = validate_difficulty_params(2, 2, 5, "mid")
        self.assertIn("无实数解", result)

    def test_rejects_b_out_of_bound(self):
        result = validate_difficulty_params(2, -25, 0, "mid")
        self.assertIn("超出 mid 难度上限", result)

    def test_hard_requires_structure_tag(self):
        result = validate_difficulty_params(3, -12, 9, "hard", "")
        self.assertIn("结构标记", result)

    def test_hard_valid_with_structure_tag(self):
        self.assertIsNone(validate_difficulty_params(3, -12, 9, "hard", "多步化简"))

    def test_all_zero_rejected(self):
        result = validate_difficulty_params(0, 0, 0, "simple")
        self.assertIn("a 不能为 0", result)


class _QueueStructuredLLM:
    """按序返回 payload 的离线替身，用于测试重试与降级路径"""

    def __init__(self, *payloads):
        self._payloads = list(payloads)
        self.prompts = []

    def with_structured_output(self, model, method=None):
        outer = self

        class _Stub:
            @staticmethod
            def invoke(prompt):
                outer.prompts.append(prompt)
                return model(**outer._payloads.pop(0))

        return _Stub()


class TestGenerateQuestionDifficulty(unittest.TestCase):
    """generate_question 难度带校验 + 降级 + 重试（离线，不调真实 LLM）"""

    def _generate(self, difficulty, *payloads):
        fake_llm = _QueueStructuredLLM(*payloads)
        with mock.patch(
            "app.adapters.llm.pick_difficulty", return_value=difficulty
        ):
            question = generate_question("weak", "配方法", fake_llm)
        return question, fake_llm

    def test_valid_hard_question(self):
        question, _ = self._generate(
            "hard",
            {"a": 3, "b": -12, "c": 9, "stem_context": "工程配比", "structure_tag": "多步化简"},
        )
        self.assertEqual(question["difficulty"], "hard")
        self.assertEqual(question["params"]["a"], 3)
        self.assertEqual(question["params"]["structure_tag"], "多步化简")
        self.assertIn("x²", question["stem"])

    def test_valid_simple_question(self):
        question, _ = self._generate(
            "simple",
            {"a": 1, "b": -6, "c": 8, "stem_context": "面积问题", "structure_tag": ""},
        )
        self.assertEqual(question["difficulty"], "simple")

    def test_hard_without_tag_downgrades_to_mid(self):
        # a=3 落在 mid 带内：缺结构标记不整题作废，降级为 mid
        question, _ = self._generate(
            "hard",
            {"a": 3, "b": -12, "c": 9, "stem_context": "工程配比", "structure_tag": ""},
        )
        self.assertEqual(question["difficulty"], "mid")

    def test_hard_big_coefficient_no_tag_retries(self):
        # a=6 超出 mid 带：不能降级，必须带边界信息重试
        question, fake_llm = self._generate(
            "hard",
            {"a": 6, "b": -12, "c": 0, "stem_context": "间距设计", "structure_tag": ""},
            {"a": 3, "b": -12, "c": 9, "stem_context": "工程配比", "structure_tag": "多步化简"},
        )
        self.assertEqual(question["difficulty"], "hard")
        self.assertIn("结构标记", fake_llm.prompts[1])

    def test_double_invalid_raises(self):
        with self.assertRaises(ValueError):
            self._generate(
                "hard",
                {"a": 6, "b": -12, "c": 0, "stem_context": "间距设计", "structure_tag": ""},
                {"a": 6, "b": -12, "c": 0, "stem_context": "间距设计", "structure_tag": ""},
            )


if __name__ == "__main__":
    unittest.main()
