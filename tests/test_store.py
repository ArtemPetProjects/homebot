# PURPOSE: тесты атомарного хранилища состояний HomeBot.
import tempfile
import unittest
from pathlib import Path

from homebot.models import Answer, PendingAsk
from homebot.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.store = Store(self.state, clock=lambda: 1000.0)

    def tearDown(self):
        self.tmp.cleanup()

    def _answer(self, seq, option="Да"):
        return Answer(id="q1", option=option, seq=seq, ts="2026-11-24T00:00:00")

    def _pending(self):
        return PendingAsk(
            id="q1",
            text="Продолжить?",
            options=("Да", "Нет"),
            created_at=1000.0,
            token="a:abcdef12:0",
        )

    def test_state_survives_reload(self):
        self.store.add_answer(self._answer(self.store.next_seq()))
        self.store.save_pending(self._pending())
        reloaded = Store(self.state, clock=lambda: 1000.0)
        self.assertEqual(len(reloaded.answers_since(0)), 1)
        self.assertIsNotNone(reloaded.get_pending("q1"))
        self.assertEqual(reloaded.get_pending("q1").token, "a:abcdef12:0")

    def test_offset_roundtrip(self):
        self.assertIsNone(self.store.load_offset())
        self.store.save_offset(42)
        self.assertEqual(Store(self.state, clock=lambda: 1000.0).load_offset(), 42)

    def test_atomic_write_leaves_no_tmp(self):
        self.store.add_answer(self._answer(1))
        self.store.save_offset(7)
        self.assertEqual(list(self.state.glob("*.tmp")), [])

    def test_answers_since_is_monotonic(self):
        for seq in range(1, 4):
            self.store.add_answer(self._answer(seq, option=f"вариант{seq}"))
        got = self.store.answers_since(1)
        self.assertEqual([a.seq for a in got], [2, 3])
        self.assertEqual(Store(self.state, clock=lambda: 1000.0).next_seq(), 4)


if __name__ == "__main__":
    unittest.main()
