"""The plugin's operation journal in SQLite (storage-layout phase C)."""
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from test_native import Harness, request, module

Journal = module.Journal


class JournalStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)

    def test_operations_round_trip_and_survive_reopening(self):
        journal = Journal(self.folder.name)
        journal.put_operation('op-1', 'fp', {'status': 'partial', 'error_code': 'outcome_unknown'}, 1.0)
        journal.put_operation('op-1', 'fp', {'status': 'ok', 'layer_id': 'L1'}, 2.0)
        journal.close()
        reopened = Journal(self.folder.name)
        self.assertEqual(reopened.operations(), {'op-1': ('fp', {'status': 'ok', 'layer_id': 'L1'})})
        self.assertEqual(reopened.db.execute('PRAGMA synchronous').fetchone()[0], 2, 'FULL')
        self.assertEqual(reopened.db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        reopened.close()

    def test_only_changed_pass_rows_are_written(self):
        journal = Journal(self.folder.name)
        passes = [{'id': 'p%d' % i, 'kind': 'paint_pass', 'strength': 1} for i in range(500)]
        self.assertEqual(journal.sync_passes(passes), 500)
        passes.append({'id': 'p500', 'kind': 'paint_pass', 'strength': 1})
        self.assertEqual(journal.sync_passes(passes), 1, 'one new pass writes one row')
        passes[3]['strength'] = 0.5
        self.assertEqual(journal.sync_passes(passes), 1, 'a review change writes one row')
        self.assertEqual(journal.sync_passes(passes), 0)
        self.assertEqual(journal.sync_passes(passes[:400]), 101, 'removed rows are deleted')
        journal.close()
        self.assertEqual([p['id'] for p in Journal(self.folder.name).passes()], ['p%d' % i for i in range(400)])

    def test_a_newer_journal_is_refused(self):
        Journal(self.folder.name).close()
        db = sqlite3.connect(os.path.join(self.folder.name, 'journal.sqlite')); db.execute('PRAGMA user_version = 9'); db.close()
        with self.assertRaises(RuntimeError):
            Journal(self.folder.name)

    def test_painting_writes_the_journal_not_json_files(self):
        h = Harness(); h._creative_session['output'] = self.folder.name
        h.cmd_creative(request())
        # .progress.json stays a file: the live status the companion polls while Krita paints.
        self.assertEqual(sorted(os.listdir(self.folder.name)), ['.progress.json', 'journal.sqlite', 'journal.sqlite-shm', 'journal.sqlite-wal'])
        journal = Journal(self.folder.name)
        self.assertEqual(journal.operations()['op-1'][1]['status'], 'ok')
        self.assertEqual([p['id'] for p in journal.passes()], ['op-1'])

    def test_an_interrupted_action_is_uncertain_after_restart(self):
        # Krita stops between the intent row and the receipt: the restart must not repaint it.
        h = Harness(); h.fail = True
        identifier = str(uuid.uuid4()); destination = os.path.join(self.folder.name, identifier); os.mkdir(destination)
        painting = os.path.join(self.folder.name, 'painting.kra'); open(painting, 'w').close(); h.doc.fileName = lambda: painting
        h._creative_session.update(id=identifier, output=destination)
        p = request(); p['session_id'] = identifier; h.cmd_creative(p)
        h._creative_session['journal'].close(); h._creative_session = None
        result = h.cmd_creative({'operation': 'begin', 'session_id': identifier, 'params': {
            'mode': 'resume', 'name': 'Existing', 'output_dir': destination, 'painting_path': painting}})
        self.assertEqual(result['unresolved_operations'], ['op-1'])

    def test_json_journals_from_before_are_imported_once_and_removed(self):
        identifier = str(uuid.uuid4()); destination = os.path.join(self.folder.name, identifier); os.mkdir(destination)
        with open(os.path.join(destination, '.operations.json'), 'w') as stream:
            json.dump({'old-op': ['fp', {'status': 'ok', 'image_path': '.previews/v.jpg'}]}, stream)
        with open(os.path.join(destination, '.passes.json'), 'w') as stream:
            json.dump([{'id': 'old-op', 'kind': 'paint_pass', 'layer_id': 'L9', 'title': 'Sky', 'after': {}}], stream)
        painting = os.path.join(self.folder.name, 'painting.kra'); open(painting, 'w').close()
        h = Harness(); h.doc.fileName = lambda: painting; h._creative_session = None
        h.cmd_creative({'operation': 'begin', 'session_id': identifier, 'params': {
            'mode': 'resume', 'name': 'Old', 'output_dir': destination, 'painting_path': painting}})
        session = h._creative_session
        self.assertEqual(session['operations']['old-op'][1]['image_path'], os.path.realpath(os.path.join(destination, '.previews/v.jpg')))
        self.assertEqual([p['id'] for p in session['passes']], ['old-op'])
        self.assertFalse(os.path.exists(os.path.join(destination, '.operations.json')))
        self.assertFalse(os.path.exists(os.path.join(destination, '.passes.json')))
        stored = Journal(destination)
        self.assertEqual(stored.operations()['old-op'][1]['image_path'], '.previews/v.jpg', 'paths stay relative to the chat folder')
        self.assertEqual(len(stored.passes()), 1)


    def test_import_journal_converts_a_chat_outside_a_session(self):
        identifier = str(uuid.uuid4()); destination = os.path.join(self.folder.name, identifier); os.mkdir(destination)
        with open(os.path.join(destination, '.operations.json'), 'w') as stream: json.dump({'a': ['fp', {'status': 'ok'}]}, stream)
        with open(os.path.join(destination, '.passes.json'), 'w') as stream: json.dump([{'id': 'a', 'kind': 'paint_pass'}], stream)
        h = Harness(); h._creative_session = None
        result = h.cmd_creative({'operation': 'import_journal', 'session_id': identifier, 'params': {'output_dir': destination}})
        self.assertEqual((result['operations'], result['passes']), (1, 1))
        self.assertEqual(sorted(f for f in os.listdir(destination) if not f.startswith('journal.sqlite')), [])
        again = h.cmd_creative({'operation': 'import_journal', 'session_id': identifier, 'params': {'output_dir': destination}})
        self.assertEqual(again['operations'], 1, 'idempotent')
        with self.assertRaises(ValueError):
            h.cmd_creative({'operation': 'import_journal', 'session_id': str(uuid.uuid4()), 'params': {'output_dir': destination}})

if __name__ == '__main__':
    unittest.main()
