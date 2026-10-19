"""Exercise reversible native pass/stage chains on an in-memory canvas."""
import json
from pathlib import Path
import tempfile
import unittest

from test_native import Harness, Layer, request, module
Journal = module.Journal


def paint(harness, identifier, stage='stage-1-0', name='Texture'):
    item = request(); item['operation_id'] = identifier
    item['params'].update(stage_id=stage, name=name)
    return harness.cmd_creative(item)


def adjust(harness, identifier, layer_id, opacity, stage='stage-1-0'):
    return harness.cmd_creative({'operation': 'adjust_layer', 'session_id': 'session', 'operation_id': identifier,
                                'params': {'layer_id': layer_id, 'opacity': opacity, 'stage_id': stage}})


def review(harness, identifier, target, action='reject', value=None):
    params = {'pass_id': target, 'action': action}
    if value is not None: params['value'] = value
    return harness.cmd_creative({'operation': 'review_pass', 'session_id': 'session', 'operation_id': identifier, 'params': params})


class PassReviewTests(unittest.TestCase):
    def test_reject_original_paint_cascades_agent_adjustments_and_preserves_other_layers(self):
        h = Harness(); paint(h, 'paint-1'); adjust(h, 'adjust-1', 'layer-1', .5); adjust(h, 'adjust-2', 'layer-1', .25)
        artist = Layer('artist'); artist.pixels = b'hand-painted additions'; h.doc.nodes.append(artist)
        result = review(h, 'reject-1', 'paint-1')
        self.assertEqual(result['status'], 'ok'); self.assertFalse(h.doc.nodes[0].visible())
        self.assertTrue(artist.visible()); self.assertEqual(artist.pixels, b'hand-painted additions')
        self.assertEqual(result['affected_pass_ids'], ['paint-1', 'adjust-1', 'adjust-2'])
        self.assertTrue(all(entry['rejected'] for entry in h._creative_session['passes']))
        self.assertEqual(h._creative_session['operation_id'], 'reject-1')
        again = review(h, 'reject-1', 'paint-1'); self.assertTrue(again['replayed'])

    def test_reject_earlier_adjustment_reverses_later_adjustments_without_hiding_original(self):
        h = Harness(); paint(h, 'paint'); adjust(h, 'first', 'layer-1', .6); adjust(h, 'second', 'layer-1', .2)
        review(h, 'reject', 'first')
        self.assertEqual(h.doc.nodes[0].opacity(), 255); self.assertTrue(h.doc.nodes[0].visible())
        self.assertFalse(h._creative_session['passes'][0]['rejected'])
        self.assertTrue(h._creative_session['passes'][1]['rejected'])
        self.assertTrue(h._creative_session['passes'][2]['rejected'])
        # The latest baseline follows the known review, allowing another
        # authorized agent refinement without misclassifying it as manual.
        self.assertEqual(adjust(h, 'next', 'layer-1', .8)['status'], 'ok')

    def test_stage_reject_prevalidates_every_layer_before_changing_any(self):
        h = Harness(); paint(h, 'first'); paint(h, 'second')
        h.doc.nodes[1].pixels = b'later manual details'
        with self.assertRaisesRegex(ValueError, 'newer artist changes'):
            review(h, 'reject-stage', 'stage:stage-1-0')
        self.assertTrue(all(layer.visible() for layer in h.doc.nodes))
        self.assertFalse(any(entry['rejected'] for entry in h._creative_session['passes']))
        self.assertNotIn('reject-stage', h._creative_session['operations'])

    def test_stage_rejection_includes_dependent_adjustment_but_preserves_later_independent_pass(self):
        h = Harness(); paint(h, 'first'); paint(h, 'second')
        adjust(h, 'later-adjust', 'layer-1', .3, stage='stage-1-1')
        paint(h, 'independent', stage='stage-1-1')
        group = next(entry for entry in h._creative_passes(h._creative_session) if entry['id'] == 'stage:stage-1-0')
        self.assertIn('1 later agent adjustments', group['warning'])
        result = review(h, 'reject-stage', group['id'])
        self.assertEqual(result['affected_pass_ids'], ['first', 'second', 'later-adjust'])
        self.assertFalse(h.doc.nodes[0].visible()); self.assertFalse(h.doc.nodes[1].visible()); self.assertTrue(h.doc.nodes[2].visible())

    def test_stage_strength_preserves_relative_opacity_and_updates_known_baseline(self):
        h = Harness(); paint(h, 'first'); adjust(h, 'soften', 'layer-1', .4); paint(h, 'second')
        review(h, 'half', 'stage:stage-1-0', 'strength', .5)
        self.assertEqual(h.doc.nodes[0].opacity(), 51); self.assertEqual(h.doc.nodes[1].opacity(), 128)
        review(h, 'full', 'stage:stage-1-0', 'strength', 1)
        self.assertEqual(h.doc.nodes[0].opacity(), 102); self.assertEqual(h.doc.nodes[1].opacity(), 255)
        self.assertEqual(adjust(h, 'next', 'layer-1', .25)['status'], 'ok')

    def test_stage_that_adjusts_existing_layer_offers_rejection_without_blanket_visibility(self):
        h = Harness(); paint(h, 'origin', stage='stage-1-0'); adjust(h, 'tweak', 'layer-1', .25, stage='stage-1-1')
        group = next(entry for entry in h._creative_passes(h._creative_session) if entry['id'] == 'stage:stage-1-1')
        self.assertEqual(group['review_actions'], ['reject'])
        with self.assertRaisesRegex(ValueError, 'existing layers'):
            review(h, 'hide-stage', group['id'], 'visibility', False)
        self.assertTrue(h.doc.nodes[0].visible())
        review(h, 'reject-stage', group['id'])
        self.assertTrue(h.doc.nodes[0].visible()); self.assertEqual(h.doc.nodes[0].opacity(), 255)

    def test_stage_rows_are_never_persisted_or_counted_as_native_operations(self):
        h = Harness()
        with tempfile.TemporaryDirectory() as folder:
            h._creative_session['output'] = folder
            paint(h, 'first'); paint(h, 'second')
            outward = h._creative_passes(h._creative_session)
            self.assertEqual(sum(entry['kind'] == 'stage' for entry in outward), 1)
            self.assertEqual(h._creative_committed_count(h._creative_session), 2)
            journal = Journal(folder); saved = journal.passes()
            self.assertEqual(len(saved), 2); self.assertFalse(any(entry['kind'] == 'stage' for entry in saved))
            review(h, 'reject-stage', 'stage:stage-1-0')
            ledger = journal.operations()
            self.assertEqual(ledger['reject-stage'][1]['status'], 'ok')
            self.assertEqual(ledger['reject-stage'][1]['affected_pass_ids'], ['first', 'second'])

    def test_checkpoint_failure_is_durable_and_replays_without_repeating_reversal(self):
        h = Harness(); paint(h, 'first')
        def fail(*_args): raise RuntimeError('disk full')
        h._creative_checkpoint = fail
        result = review(h, 'review-failure', 'first')
        self.assertEqual(result['error_code'], 'checkpoint_failed'); self.assertFalse(h.doc.nodes[0].visible())
        self.assertTrue(review(h, 'review-failure', 'first')['replayed'])
        self.assertIn('review-failure', h._creative_unresolved(h._creative_session))


if __name__ == '__main__': unittest.main()
