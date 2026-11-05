from tradelens.modules.market_data import repository


class RecordingConnection:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, statement, params=None):
        self.calls += 1


def test_empty_row_lists_issue_no_statements():
    conn = RecordingConnection()
    repository.insert_calendars(conn, [])
    repository.insert_instruments(conn, [])
    repository.insert_series_status(conn, [])
    assert conn.calls == 0
