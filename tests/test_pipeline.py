"""Synthetic regression tests for information boundaries and model mathematics."""
from dataclasses import replace
from datetime import datetime, timezone
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import poisson

from premonition_fc import cli
from premonition_fc.data import Fixture, HOLDOUT, normalize
from premonition_fc.evaluation import metrics, score_predictions, development_folds
from premonition_fc.features import FEATURES, bucket_start, matrix, prepare_features, trace
from premonition_fc.models import aligned_probabilities, fit_models, outcome, poisson_distribution, predict
from premonition_fc.storage import external_directory


SETTINGS = {"poisson":{"alpha":0.1},"forest":{"min_samples_leaf":5}}


def example_history():
    return [Fixture("2024-25","2024-08-10","alpha","beta",2,0),
            Fixture("2024-25","2024-08-11","gamma","alpha",0,0),
            Fixture("2024-25","2024-08-12","beta","gamma",1,1),
            Fixture("2024-25","2024-08-17","alpha","gamma",1,2)]


def training_example():
    rows,targets = [],[]
    for i in range(24):
        label = i%3
        rows.append({"fixture_id":f"synthetic-{i}","season":"2024-25","played_date":"2025-01-01",
            "home":"alpha","away":"beta","issue_date_london":"2025-01-01",
            "features":{name:float((i+j)%7)/3 for j,name in enumerate(FEATURES)}})
        targets.append({"fixture_id":f"synthetic-{i}","home_goals":(2,1,0)[label],"away_goals":(0,1,2)[label]})
    return rows,targets


class DataAndCutoffTests(unittest.TestCase):
    def test_nested_array_zero_and_pending_scores(self):
        base = {"date":"2025-08-16","team1":"Aston Villa FC","team2":"Newcastle United FC"}
        fixtures = normalize([dict(base,score=s) for s in ({"ft":[0,0]},[0,0],None)],"2025-26")
        self.assertEqual([m.complete for m in fixtures],[True,True,False])
        self.assertEqual(fixtures[0].key,fixtures[1].key)

    def test_malformed_scores_are_not_draws(self):
        base = {"date":"2025-08-16","team1":"Aston Villa FC","team2":"Newcastle United FC"}
        for score in ([True,0],[-1,0],[0.5,0],[],{}, {"ft":[0,0],"ht":[1,0]}):
            with self.subTest(score=score),self.assertRaises(ValueError):
                normalize([dict(base,score=score)],"2025-26")

    def test_tuesday_monday_and_london_dst_dates(self):
        self.assertEqual(bucket_start("2026-11-09"),"2026-11-03")
        self.assertEqual(bucket_start("2026-11-10"),"2026-11-10")
        self.assertEqual(datetime(2026,8,14,23,30,tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/London")).date().isoformat(),"2026-08-15")

    def test_target_same_day_and_future_mutations_leave_full_trace_unchanged(self):
        history = example_history()
        target = Fixture("2024-25","2024-08-17","alpha","gamma",None,None)
        baseline = trace(history,target,"2024-08-17")
        changed = [replace(m,home_goals=99,away_goals=0) if m.played_date>="2024-08-17" else m for m in history]
        changed += [Fixture("2024-25","2024-08-17","alpha","beta",99,0),Fixture("2024-25","2025-01-01","alpha","beta",99,0)]
        self.assertEqual(baseline,trace(changed,replace(target,home_goals=99,away_goals=99),"2024-08-17"))

    def test_short_history_blend_and_zero_history(self):
        history = example_history()[:3]
        target = Fixture("2024-25","2024-08-17","alpha","promoted")
        result = trace(history,target,"2024-08-17")
        # Three games: four goals and seven total points over six team appearances.
        self.assertEqual(result["prior_totals"],{"goals":4,"points":7,"team_appearances":6})
        self.assertEqual(result["home_trace"]["count"],2)
        self.assertEqual(result["home_trace"]["totals"],{"gf":2,"ga":0,"points":4})
        self.assertAlmostEqual(result["features"]["home_gf"],(2+3*(4/6))/5)
        self.assertEqual(result["away_trace"]["count"],0)
        self.assertEqual(result["features"]["away_points"],7/6)

    def test_history_does_not_reach_two_seasons_back(self):
        target = Fixture("2025-26","2025-08-15","alpha","promoted")
        old = Fixture("2023-24","2024-05-01","promoted","alpha",99,0)
        result = trace(example_history()+[old],target,"2025-08-15")
        self.assertEqual(result["away_trace"]["count"],0)

    def test_no_league_prior_is_explicit_warmup(self):
        with self.assertRaisesRegex(ValueError,"warm-up"):
            trace([],Fixture("2024-25","2024-08-17","alpha","beta"),"2024-08-17")

    def test_fixture_only_preparation_and_shared_slate_cutoff(self):
        history = example_history()
        targets = [Fixture("2024-25","2024-08-16","alpha","beta"),Fixture("2024-25","2024-08-18","gamma","alpha")]
        rows,_,_ = prepare_features(targets,history)
        self.assertEqual(len(rows),2)
        self.assertEqual({r["issue_date_london"] for r in rows},{"2024-08-16"})
        self.assertTrue(all(r["prior_latest_date"]<"2024-08-16" for r in rows))

    def test_rescheduled_date_not_round_identity(self):
        target = Fixture("2024-25","2025-02-12","everton","liverpool")
        self.assertEqual(bucket_start(target.played_date),"2025-02-11")

    def test_estimator_matrix_excludes_metadata_and_targets(self):
        rows,_ = training_example()
        rows[0].update(home_goals=99,played_date="2099-01-01",home_count=500)
        self.assertEqual(matrix(rows).shape,(24,6))
        rows[0]["features"]["home_goals"] = 99
        with self.assertRaises(ValueError):
            matrix(rows)


class ProbabilityTests(unittest.TestCase):
    def test_equal_means_are_symmetric(self):
        distribution = poisson_distribution(1.6,1.6)
        h,d,a = distribution["probabilities"]
        self.assertAlmostEqual(h,a,places=13)
        self.assertAlmostEqual(h+d+a,1,places=13)

    def test_probability_ranges_mass_and_ranked_scores(self):
        for h,a in ((0,0),(0,2),(2,0),(0.03,5),(2.2,0.4),(12,20)):
            with self.subTest(means=(h,a)):
                result = poisson_distribution(h,a)
                self.assertTrue(all(0<=p<=1 for p in result["probabilities"]))
                self.assertAlmostEqual(sum(result["probabilities"]),1,places=12)
                self.assertLessEqual(result["tail_mass_bound"],1e-12)
                ranked = result["scorelines"]
                self.assertEqual(len({(r["home_goals"],r["away_goals"]) for r in ranked}),3)
                self.assertEqual(ranked,sorted(ranked,key=lambda r:(-r["probability"],r["home_goals"],r["away_goals"])))
                for score in ranked:
                    self.assertAlmostEqual(score["probability"],poisson.pmf(score["home_goals"],h)*poisson.pmf(score["away_goals"],a),places=14)

    def test_top_three_matches_larger_independent_grid(self):
        h,a = 2.2,1.1
        actual = poisson_distribution(h,a)["scorelines"]
        grid = [(float(poisson.pmf(i,h)*poisson.pmf(j,a)),i,j) for i in range(40) for j in range(40)]
        expected = sorted(grid,key=lambda r:(-r[0],r[1],r[2]))[:3]
        self.assertEqual([(r["probability"],r["home_goals"],r["away_goals"]) for r in actual],expected)

    def test_outcomes_match_independent_score_sum(self):
        h,a = 1.8,0.7
        expected = np.zeros(3)
        for i in range(35):
            for j in range(35):
                expected[0 if i>j else 1 if i==j else 2] += poisson.pmf(i,h)*poisson.pmf(j,a)
        np.testing.assert_allclose(poisson_distribution(h,a)["probabilities"],expected,rtol=0,atol=2e-13)

    def test_classifier_classes_map_by_identity(self):
        class Shuffled:
            classes_ = np.array(["A","H","D"])
            def predict_proba(self,x):
                return np.tile([0.2,0.5,0.3],(len(x),1))
        np.testing.assert_equal(aligned_probabilities(Shuffled(),np.zeros((2,6))),[[0.5,0.3,0.2]]*2)

    def test_invalid_means_fail(self):
        for value in (-1,float("nan"),float("inf")):
            with self.assertRaises(ValueError):
                poisson_distribution(value,1)


class FitAndScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows,cls.targets = training_example()
        cls.fitted = fit_models(cls.rows,cls.targets,SETTINGS)

    def test_fit_rejects_holdout_and_duplicate_targets(self):
        rows,targets = training_example()
        rows[0]["season"] = HOLDOUT
        with self.assertRaisesRegex(ValueError,"development"):
            fit_models(rows,targets,SETTINGS)
        rows[0]["season"] = "2024-25"
        with self.assertRaisesRegex(ValueError,"one-to-one"):
            fit_models(rows,targets[:-1]+[targets[0]],SETTINGS)

    def test_preprocessing_fits_training_partition_only(self):
        scaler = self.fitted.home_poisson.steps[0][1]
        np.testing.assert_allclose(scaler.mean_,matrix(self.rows).mean(axis=0),rtol=0,atol=1e-15)
        self.assertEqual(scaler.n_samples_seen_,24)

    def test_frozen_predictions_ignore_target_contents(self):
        before = predict(self.fitted,self.rows,"synthetic")
        self.targets[0]["home_goals"] = 99
        try:
            self.assertEqual(before,predict(self.fitted,self.rows,"synthetic"))
        finally:
            self.targets[0]["home_goals"] = 2

    def test_predictions_reconcile_and_score_one_to_one(self):
        forecasts = predict(self.fitted,self.rows,"synthetic")
        scored = score_predictions(forecasts,self.targets,24)
        result = metrics(scored)
        self.assertEqual({m["fixtures"] for m in result.values()},{24})
        self.assertTrue(all(np.isfinite(m["log_loss"]) for m in result.values()))
        with self.assertRaises(ValueError):
            score_predictions(forecasts+[forecasts[0]],self.targets)
        with self.assertRaises(ValueError):
            score_predictions(forecasts,self.targets[:-1])

    def test_deterministic_result_tie_uses_declared_order(self):
        forecasts = predict(self.fitted,self.rows[:1],"synthetic")
        for r in forecasts:
            r["probabilities"] = [0.4,0.4,0.2]
        scored = score_predictions(forecasts,self.targets[:1],1)
        self.assertTrue(all(r["predicted_result"]=="H" for r in scored))

    def test_development_entry_rejects_holdout_rows(self):
        rows,_ = training_example()
        rows[0]["season"] = HOLDOUT
        with self.assertRaises(ValueError):
            list(development_folds(rows))

    def test_forecast_entry_never_opens_holdout_targets(self):
        from argparse import Namespace
        from premonition_fc.storage import write_json
        with TemporaryDirectory() as folder:
            root = Path(folder)
            fake_rows = [dict(self.rows[0],fixture_id=f"holdout-{i}",season=HOLDOUT) for i in range(380)]
            write_json(root/"holdout_features.json",fake_rows)
            from premonition_fc.storage import digest
            manifest = {"files":{"holdout_features.json":digest(root/"holdout_features.json"),
                                  "holdout_targets.json":"sealed","development_features.json":"dev-x","development_targets.json":"dev-y"}}
            frozen = {"fit_sha256":"fit","development_features_sha256":"dev-x","development_targets_sha256":"dev-y","holdout_target_file_sha256":"sealed"}
            write_json(root/"freeze.json",frozen)
            original = cli.read_json
            opened = []
            def checked(path):
                opened.append(Path(path).name)
                if "targets" in str(path):
                    raise AssertionError("Forecast opened scoring targets")
                return original(path)
            with patch.object(cli,"check_prepared",return_value=(root,manifest)),patch.object(cli,"frozen_manifest",return_value=(root,frozen)),patch.object(cli.joblib,"load",return_value=self.fitted),patch.object(cli,"predict",return_value=[{"synthetic":True}]),patch.object(cli,"read_json",side_effect=checked),patch("sys.stdout",new=io.StringIO()):
                cli.forecast(Namespace(prepared=root,frozen=root,output=root/"forecasts"))
            self.assertEqual(opened,["holdout_features.json"])

    def test_outputs_inside_a_git_worktree_are_rejected(self):
        with self.assertRaises(ValueError):
            external_directory(Path(__file__).resolve().parent.parent/"outputs")


if __name__=="__main__":
    unittest.main()
