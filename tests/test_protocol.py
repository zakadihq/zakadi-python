import unittest

from zakadi import (
    SUBPROTOCOL,
    CloseCode,
    EndReason,
    ErrorCode,
    TerminalState,
    __version__,
    terminal_state_for_end,
)


class ProtocolTests(unittest.TestCase):
    def test_subprotocol(self) -> None:
        self.assertEqual(SUBPROTOCOL, "zakadi.v1")
        self.assertEqual(__version__, "0.0.1")

    def test_error_codes(self) -> None:
        self.assertEqual(len(ErrorCode), 18)
        self.assertEqual(ErrorCode("interrupted"), ErrorCode.INTERRUPTED)
        with self.assertRaises(ValueError):
            ErrorCode("not_a_code")

    def test_redial(self) -> None:
        self.assertTrue(TerminalState.INCOMPLETE.offers_redial)
        self.assertFalse(TerminalState.COMPLETED.offers_redial)
        self.assertEqual(TerminalState.INCOMPLETE.cue, "fail.one_more_step")

    def test_end_mapping(self) -> None:
        self.assertEqual(terminal_state_for_end(EndReason.OK), TerminalState.COMPLETED)
        self.assertEqual(terminal_state_for_end(EndReason.MAX_DURATION), TerminalState.INCOMPLETE)
        self.assertEqual(CloseCode.CANCELLED_BY_USER, 4010)


if __name__ == "__main__":
    unittest.main()
