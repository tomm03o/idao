import numpy as np
import pandas as pd
import pytest

from habscan.data.catalogs import harmonise_confirmed, harmonise_toi, scan_mask, build_planet_table
from habscan.ml.rocky import GATES, MU_ROCKY, TAU_ROCKY, fit_em
from habscan.ml.vetting import train_vetting_model


def _ps_row(**kw):
    base = {
        "pl_name": "X b", "hostname": "X", "discoverymethod": "Transit", "pl_controv_flag": 0, "tran_flag": 1,
        "ttv_flag": 0, "sy_pnum": 1, "sy_dist": 10.0, "sy_vmag": 10.0, "ra": 0.0, "dec": 0.0,
        "pl_bmassprov": "Mass", "pl_bmasselim": 0, "pl_radelim": 0, "pl_orbeccenlim": 0,
        "pl_orbper": 10.0, "pl_rade": 1.5, "pl_radeerr1": 0.1, "pl_radeerr2": -0.1,
        "pl_bmasse": 4.0, "pl_bmasseerr1": 0.5, "pl_bmasseerr2": -0.5,
        "st_teff": 5000.0, "st_rad": 0.8, "st_mass": 0.8, "st_lum": -0.4, "st_lumerr1": 0.02, "st_lumerr2": -0.02,
        "st_logg": 4.5, "st_age": 3.0,
    }
    base.update(kw)
    return base


class TestCatalogs:
    def test_mass_provenance(self):
        ps = pd.DataFrame([
            _ps_row(pl_name="a"),
            _ps_row(pl_name="b", pl_bmassprov="M-R relationship"),
            _ps_row(pl_name="c", pl_bmassprov="Msini", tran_flag=0),
            _ps_row(pl_name="d", pl_bmasselim=1),
            _ps_row(pl_name="e", pl_bmasselim=-1),
        ])
        h = harmonise_confirmed(ps).set_index("name")
        assert list(h["mass_kind"]) == ["measured", "none", "msini", "upper", "lower"]
        assert np.isnan(h.loc["b", "mass"])  # M-R forecast is not a measurement
        assert not h.loc["c", "radius_measured"] and np.isnan(h.loc["c", "radius"])  # RV planet radius = forecast
        assert h.loc["a", "st_lum"] == pytest.approx(10**-0.4)

    def test_toi_stellar_mass_from_logg(self):
        toi = pd.DataFrame([{"toi": 700.04, "tid": 1, "tfopwg_disp": "PC", "pl_orbper": 37.0, "pl_rade": 1.1,
                             "st_teff": 3480.0, "st_logg": 4.438, "st_rad": 1.0, "pl_pnum": 4}])
        h = harmonise_toi(toi)
        assert h.loc[0, "st_mass"] == pytest.approx(1.0)
        assert h.loc[0, "name"] == "TOI-700.04" and np.isnan(h.loc[0, "label_real"])

    def test_scan_mask_excludes_resolved_candidates(self):
        toi = pd.DataFrame([{"toi": t, "tid": i, "tfopwg_disp": d, "pl_orbper": 5.0, "pl_rade": 1.0}
                            for i, (t, d) in enumerate([(1.01, "PC"), (2.01, "FP"), (3.01, "CP"), (4.01, "APC")])])
        df = build_planet_table(pd.DataFrame([_ps_row()]), toi, None)
        assert scan_mask(df).sum() == 3  # confirmed + PC + APC


class TestRockyEM:
    def test_recovers_synthetic_gate(self):
        """Simulate a population with known P(rocky | R) and noisy composition offsets."""
        rng = np.random.default_rng(3)
        n = 1500
        radius = np.exp(rng.uniform(np.log(0.7), np.log(3.5), n))
        p_true = 1 / (1 + np.exp((radius - 1.7) / 0.12))
        rocky = rng.random(n) < p_true
        sigma = rng.uniform(0.01, 0.05, n)
        delta_true = np.where(rocky, rng.normal(MU_ROCKY, TAU_ROCKY, n), rng.normal(0.18, 0.07, n))
        delta = delta_true + rng.normal(0, sigma)
        flux = np.full(n, 10.0)
        spec = [g for g in GATES if g.name == "logistic_size"][0]
        m = fit_em("radius", spec, radius, flux, delta, sigma)
        assert m.mu_g == pytest.approx(0.18, abs=0.03)
        grid = np.array([1.0, 1.5, 1.7, 2.0, 2.5])
        p_hat = m.predict(grid, np.full_like(grid, 10.0))
        p_ref = 1 / (1 + np.exp((grid - 1.7) / 0.12))
        assert np.max(np.abs(p_hat - p_ref)) < 0.12

    def test_posterior_beats_flat_prior_for_earth_twin(self):
        """An Earth twin measured with typical errors must be classified rocky with high confidence."""
        rng = np.random.default_rng(0)
        spec = [g for g in GATES if g.name == "logistic_size"][0]
        n = 800
        radius = np.exp(rng.uniform(np.log(0.7), np.log(3.5), n))
        rocky = rng.random(n) < 1 / (1 + np.exp((radius - 1.7) / 0.12))
        sigma = np.full(n, 0.03)
        delta = np.where(rocky, rng.normal(0, 0.02, n), rng.normal(0.18, 0.07, n)) + rng.normal(0, sigma)
        m = fit_em("radius", spec, radius, np.full(n, 10.0), delta, sigma)
        assert float(m.posterior(np.array([0.0]), np.array([0.05]), np.array([1.0]), np.array([10.0]))[0]) > 0.95


class TestVetting:
    def test_grouped_training_and_calibration(self):
        rng = np.random.default_rng(0)
        n_hosts = 600
        host = np.repeat(np.arange(n_hosts), 2)
        n = host.size
        y = (rng.random(n) < 0.4).astype(float)
        x = pd.DataFrame({
            "signal": y * 1.5 + rng.normal(0, 1, n),
            "noise": rng.normal(0, 1, n),
            "with_nan": np.where(rng.random(n) < 0.3, np.nan, rng.normal(0, 1, n)),
            "constant": np.ones(n),
        })
        labels = pd.Series(np.where(rng.random(n) < 0.15, np.nan, y))
        m = train_vetting_model(x, labels, pd.Series(host), "synthetic", seed=0)
        assert "constant" in m.dropped_features
        assert m.holdout_metrics["roc_auc"] > 0.8
        p = m.predict(x)
        assert np.all((p >= 0) & (p <= 1))
        assert abs(m.holdout_metrics["ece"]) < 0.1
