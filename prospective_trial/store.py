"""A transactional append-only event ledger with canonical payload hash chaining."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from premonition_fc.storage import external_directory, object_digest


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


@contextmanager
def transaction(path, *, create=False):
    path = Path(path).resolve()
    external_directory(path.parent)
    if not create and not path.is_file():
        raise ValueError('Trial ledger does not exist')
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('BEGIN IMMEDIATE')
        if create:
            connection.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT UNIQUE NOT NULL)')
            for operation in ('UPDATE', 'DELETE'):
                connection.execute(f"CREATE TRIGGER IF NOT EXISTS forbid_{operation.lower()} BEFORE {operation} ON events BEGIN SELECT RAISE(ABORT, 'Evidence is append-only'); END")
        events = []
        previous = '0'*64
        for seq, key, kind, raw, parent, event_hash in connection.execute('SELECT * FROM events ORDER BY seq'):
            payload = json.loads(raw)
            if seq != len(events)+1 or parent != previous or canonical(payload) != raw or object_digest({'seq': seq, 'key': key, 'kind': kind, 'payload': payload, 'previous_hash': parent}) != event_hash:
                raise ValueError('Ledger hash chain failed')
            events.append({'seq': seq, 'key': key, 'kind': kind, 'payload': payload, 'previous_hash': parent, 'event_hash': event_hash})
            previous = event_hash
        yield connection, events
        connection.execute('COMMIT')
    except BaseException:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise
    finally:
        connection.close()


def append(connection, events, key, kind, payload):
    existing = next((e for e in events if e['key'] == key), None)
    if existing:
        if existing['kind'] != kind or existing['payload'] != payload:
            raise ValueError('Existing evidence cannot be replaced')
        return existing
    event = {'seq': len(events)+1, 'key': key, 'kind': kind, 'payload': payload,
             'previous_hash': events[-1]['event_hash'] if events else '0'*64}
    event['event_hash'] = object_digest(event)
    connection.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',
                       (event['seq'], key, kind, canonical(payload), event['previous_hash'], event['event_hash']))
    events.append(event)
    return event
