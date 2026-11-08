import unittest

from model_iteration.diagnostics import diagnose, score


class DiagnosticTests(unittest.TestCase):
    def example(self):
        predictions = [{'fixture_id': str(i), 'season': 'synthetic', 'model': 'test',
                        'probabilities': p, 'scorelines': [{'home_goals': 0, 'away_goals': 0},
                            {'home_goals': 1, 'away_goals': 0}, {'home_goals': 1, 'away_goals': 1}]}
                       for i, p in enumerate(([.4, .4, .2], [0, 1, 0], [.2, .2, .6]))]
        targets = [{'fixture_id': str(i), 'home_goals': h, 'away_goals': a}
                   for i, (h, a) in enumerate(((1, 0), (0, 0), (1, 1)))]
        return predictions, targets

    def test_counts_ties_edges_and_coverage(self):
        p, t = self.example()
        value = diagnose(score(p, t))['test']['pooled']
        self.assertEqual(value['confusion_actual_rows_predicted_columns'], [[1, 0, 0], [0, 1, 1], [0, 0, 0]])
        self.assertEqual(value['draw_top_picks'], 1)
        self.assertEqual(value['classes']['A']['recall'], None)
        self.assertEqual(value['exact_score']['first_hits'], 1)
        self.assertEqual(value['exact_score']['top_three_hits'], 3)
        self.assertAlmostEqual(value['class_brier']['D'], (.16 + 0 + .64) / 3)
        for bins in value['reliability'].values():
            self.assertEqual(sum(b['count'] for b in bins), 3)
        self.assertEqual(value['reliability']['D'][4]['count'], 1)

    def test_incomplete_duplicate_and_missing_scores_fail(self):
        p, t = self.example()
        for forecasts, targets in ((p + p[:1], t), (p, t[:-1]), (p, t + t[:1])):
            with self.assertRaises(ValueError):
                score(forecasts, targets)
        t[0]['home_goals'] = None
        with self.assertRaises(ValueError):
            score(p, t)


if __name__ == '__main__':
    unittest.main()
