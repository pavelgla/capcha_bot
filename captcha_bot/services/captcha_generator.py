import random
from dataclasses import dataclass, field
from typing import List


@dataclass
class CaptchaTask:
    question: str
    correct_answer: int
    options: List[int] = field(default_factory=list)  # 4 shuffled options


def _wrong_answers(correct: int, count: int = 3) -> List[int]:
    """Generate `count` plausible wrong answers near the correct value."""
    candidates: set[int] = set()
    deltas = list(range(-12, 13))
    deltas.remove(0)
    random.shuffle(deltas)
    for d in deltas:
        candidate = correct + d
        if candidate > 0 and candidate != correct:
            candidates.add(candidate)
        if len(candidates) == count:
            break
    return list(candidates)


def generate_captcha() -> CaptchaTask:
    """Return a random math captcha with 4 shuffled answer options."""
    task_type = random.choice(["multiply", "divide", "add", "sequence", "word_problem"])

    if task_type == "multiply":
        a = random.randint(2, 12)
        b = random.randint(2, 12)
        question = f"Сколько будет {a} × {b}?"
        correct = a * b

    elif task_type == "divide":
        divisor = random.randint(2, 12)
        quotient = random.randint(2, 12)
        question = f"Сколько будет {divisor * quotient} ÷ {divisor}?"
        correct = quotient

    elif task_type == "add":
        a = random.randint(10, 50)
        b = random.randint(10, 50)
        question = f"Сколько будет {a} + {b}?"
        correct = a + b

    elif task_type == "sequence":
        start = random.randint(1, 5)
        factor = random.choice([2, 3, 4, 5])
        seq = [start * (factor ** i) for i in range(4)]
        correct = seq[-1] * factor
        question = f"Ряд чисел: {', '.join(map(str, seq))}, ___. Какое следующее?"

    else:  # word_problem
        total = random.randint(3, 7)
        eaten = random.randint(1, total - 1)
        found = random.randint(1, 5)
        correct = total - eaten + found
        question = (
            f"У меня {total} яблока, я съел {eaten}, "
            f"потом нашёл ещё {found}. Сколько у меня яблок?"
        )

    wrong = _wrong_answers(correct)
    options = [correct] + wrong
    random.shuffle(options)

    return CaptchaTask(question=question, correct_answer=correct, options=options)
