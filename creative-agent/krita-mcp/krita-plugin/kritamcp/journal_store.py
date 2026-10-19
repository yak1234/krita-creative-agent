"""The plugin's operation journal for one chat, in SQLite (storage-layout phase C).

`<chat folder>/journal.sqlite` replaces `.operations.json` and `.passes.json`. It is the record
that stops a crashed action from being painted twice, so it is written with synchronous=FULL and
each change is one small transaction: an operation's intent before it paints, its receipt after,
and only the pass rows that changed. The JSON files were rewritten whole twice per action
(97 MB after one long job). Only the plugin writes this file; the companion reads it read-only.
"""
import json
import os
import sqlite3

SCHEMA = 1
FILENAME = 'journal.sqlite'


class Journal:
    def __init__(self, directory):
        self.path = os.path.join(directory, FILENAME)
        # Autocommit; transactions are explicit. Krita runs the plugin on its main thread, but the
        # connection may be closed from another one at shutdown.
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode = WAL')
        self.db.execute('PRAGMA synchronous = FULL')
        self.db.execute('PRAGMA busy_timeout = 5000')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA:
            self.db.close()
            raise RuntimeError('This chat\'s journal was written by a newer Creative Agent. Update the agent to continue it.')
        if version < 1:
            with self._transaction():
                self.db.execute('CREATE TABLE operations (operation_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, '
                                'receipt TEXT NOT NULL CHECK (json_valid(receipt)), updated_at REAL NOT NULL)')
                self.db.execute('CREATE TABLE passes (seq INTEGER PRIMARY KEY, id TEXT NOT NULL, entry TEXT NOT NULL CHECK (json_valid(entry)))')
                self.db.execute('PRAGMA user_version = %d' % SCHEMA)
        self._stored_passes = None                         # seq -> stored JSON, to write only changes

    def _transaction(self):
        journal = self

        class Transaction:
            def __enter__(self):
                journal.db.execute('BEGIN IMMEDIATE')

            def __exit__(self, kind, _value, _trace):
                journal.db.execute('COMMIT' if kind is None else 'ROLLBACK')
                return False
        return Transaction()

    def close(self):
        try:
            self.db.close()
        except sqlite3.Error:
            pass

    # Operations: id -> (fingerprint, receipt)
    def operations(self):
        return {row[0]: (row[1], json.loads(row[2])) for row in
                self.db.execute('SELECT operation_id, fingerprint, receipt FROM operations')}

    def put_operation(self, operation_id, fingerprint, receipt, at):
        self.db.execute('INSERT INTO operations(operation_id, fingerprint, receipt, updated_at) VALUES (?, ?, ?, ?) '
                        'ON CONFLICT(operation_id) DO UPDATE SET fingerprint = excluded.fingerprint, '
                        'receipt = excluded.receipt, updated_at = excluded.updated_at',
                        (operation_id, fingerprint, json.dumps(receipt), at))

    def put_operations(self, items, at):
        with self._transaction():
            for operation_id, (fingerprint, receipt) in items.items():
                self.put_operation(operation_id, fingerprint, receipt, at)

    # Passes: the ordered pass history
    def passes(self):
        rows = list(self.db.execute('SELECT seq, entry FROM passes ORDER BY seq'))
        self._stored_passes = {seq: entry for seq, entry in rows}
        return [json.loads(entry) for _seq, entry in rows]

    def sync_passes(self, entries):
        """Store the pass list, writing only rows that changed since the last read or write."""
        if self._stored_passes is None:
            self.passes()
        encoded = [json.dumps(entry, sort_keys=True) for entry in entries]
        changed = [(seq, entries[seq].get('id') or '', text) for seq, text in enumerate(encoded) if self._stored_passes.get(seq) != text]
        extra = [seq for seq in self._stored_passes if seq >= len(encoded)]
        if not changed and not extra:
            return 0
        with self._transaction():
            for seq, identifier, text in changed:
                self.db.execute('INSERT INTO passes(seq, id, entry) VALUES (?, ?, ?) ON CONFLICT(seq) DO UPDATE SET '
                                'id = excluded.id, entry = excluded.entry', (seq, identifier, text))
            for seq in extra:
                self.db.execute('DELETE FROM passes WHERE seq = ?', (seq,))
        self._stored_passes = dict(enumerate(encoded))
        return len(changed) + len(extra)
