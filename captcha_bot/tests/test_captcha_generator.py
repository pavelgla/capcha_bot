"""Unit tests for services/captcha_generator.py — no external dependencies."""
import pytest

from services.captcha_generator import CaptchaTask, generate_captcha


def test_returns_captcha_task():
    assert isinstance(generate_captcha(), CaptchaTask)


def test_exactly_four_options():
    for _ in range(50):
        task = generate_captcha()
        assert len(task.options) == 4, f"Expected 4 options, got {task.options}"


def test_correct_answer_in_options():
    for _ in range(50):
        task = generate_captcha()
        assert task.correct_answer in task.options, (
            f"Correct answer {task.correct_answer} not in options {task.options}"
        )


def test_no_duplicate_options():
    for _ in range(50):
        task = generate_captcha()
        assert len(set(task.options)) == 4, f"Duplicate options: {task.options}"


def test_all_options_positive():
    for _ in range(100):
        task = generate_captcha()
        for opt in task.options:
            assert opt > 0, f"Non-positive option {opt} in {task.options}"


def test_question_is_nonempty_string():
    task = generate_captcha()
    assert isinstance(task.question, str) and len(task.question) > 0


def test_correct_answer_is_positive_int():
    for _ in range(50):
        task = generate_captcha()
        assert isinstance(task.correct_answer, int)
        assert task.correct_answer > 0
