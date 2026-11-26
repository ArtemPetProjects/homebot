# PURPOSE: тесты ограничений модели запроса подтверждения.
import unittest

from homebot.domain.models import Ask


class ModelsTest(unittest.TestCase):
    def test_rejects_too_long_option(self):
        with self.assertRaises(ValueError):
            Ask("q1", "Вопрос?", ("x" * 100, "Нет")).validate()

    def test_accepts_short_options(self):
        Ask("q1", "Вопрос?", ("Да", "Нет")).validate()


if __name__ == "__main__":
    unittest.main()
