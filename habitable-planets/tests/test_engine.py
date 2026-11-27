from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from habscan.benchmark import _sun_row, solar_system_table, solar_system_validation
from habscan.data.catalogs import SCHEMA_COLUMNS
from habscan.habitability import HabitabilityConfig, HabitabilityEngine
from habscan.ml.rocky import fixed_rocky_model
from habscan.sampling import isotropic_sin_inclination, positive_split_lognormal, split_normal


@pytest.fixture(scope="module")
def engine():
    return HabitabilityEngine(HabitabilityConfig(n_samples=3000, seed=1), fixed_rocky_model())


class TestSampling:
    def test_split_normal_asymmetry(self):
        rng = np.random.default_rng(0)
        x = split_normal([10.0], [2.0], [-1.0], 200000, rng)[0]
        assert np.median(x) == pytest.approx(10.0, abs=0.02)
        assert np.percentile(x, 84) - 10 > 1.5 * (10 - np.percentile(x, 16))

    def test_lognormal_positive_and_median(self):
        rng = np.random.default_rng(0)
        x = positive_split_lognormal([1.0, 2.0], [0.9, 0.1], [-0.9, -0.1], 50000, rng)
        assert np.all(x > 0)
        assert np.median(x[1]) == pytest.approx(2.0, rel=0.01)

    def test_missing_value_gives_nan(self):
        rng = np.random.default_rng(0)
        assert np.isnan(positive_split_lognormal([np.nan], [np.nan], [np.nan], 10, rng)).all()

    def test_default_error_when_missing(self):
        rng = np.random.default_rng(0)
        x = positive_split_lognormal([5.0], [np.nan], [np.nan], 100000, rng, default_rel=0.1)[0]
        # +10 % -> log(1.1) above, -10 % -> -log(0.9) below; the split normal's spread is their mean
        assert np.std(np.log(x)) == pytest.approx(0.5 * (np.log1p(0.1) - np.log1p(-0.1)), rel=0.02)

    def test_isotropic_inclination(self):
        rng = np.random.default_rng(0)
        s = isotropic_sin_inclination((1, 200000), rng, min_sin=0.0)
        # E[sin i] for isotropic orbits = pi / 4
        assert s.mean() == pytest.approx(np.pi / 4, abs=0.005)


class TestSolarSystem:
    def test_earth_venus_mars_giants(self, engine):
        t = solar_system_validation(engine).set_index("name")["p_habitable"]
        assert t["Earth"] > 0.9
        assert t["Venus"] < 0.01 and t["Mercury"] < 0.01
        assert max(t["Jupiter"], t["Saturn"], t["Uranus"], t["Neptune"]) < 0.01
        assert 0.3 < t["Mars"] < 0.7

    def test_earth_seen_as_transit(self, engine):
        t = solar_system_validation(engine).set_index("name")
        assert t.loc["Earth (transit-only, 3% radius)", "case"] == "B"
        assert t.loc["Earth (transit-only, 3% radius)", "p_habitable"] > 0.9

    def test_earth_seen_by_rv(self, engine):
        t = solar_system_validation(engine).set_index("name")
        assert t.loc["Earth (RV-only, Msini 10%)", "case"] == "D"
        # true mass is >= M sin i, so the RV-only Earth must look less certain than the real one
        assert t.loc["Earth (RV-only, Msini 10%)", "p_habitable"] <= t.loc["Earth", "p_habitable"]

    def test_point_estimate_mode(self):
        eng = HabitabilityEngine(HabitabilityConfig(point_estimate=True), fixed_rocky_model())
        t = solar_system_validation(eng).set_index("name")["p_habitable"]
        assert t["Earth"] > 0.9 and t["Venus"] == 0.0

    def test_reproducible(self):
        cfg = HabitabilityConfig(n_samples=500, seed=7)
        a = HabitabilityEngine(cfg, fixed_rocky_model()).evaluate(solar_system_table())
        b = HabitabilityEngine(cfg, fixed_rocky_model()).evaluate(solar_system_table())
        pd.testing.assert_frame_equal(a, b)


class TestConstraintsAndMissingData:
    def test_mass_upper_limit_constraint(self, engine):
        # transit radius 1.5 R_E; an upper mass limit below the rocky mass (~4.5 M_E) is incompatible
        # with a rocky composition everywhere -> constraint ignored (documented fallback), not a crash
        base = _sun_row("x", 1.0, 0.0, 1.5, 1.0, mass_kind="none")
        tight = dict(base, mass=2.0, mass_kind="upper")
        loose = dict(base, mass=100.0, mass_kind="upper")
        df = pd.DataFrame([base, tight, loose])[SCHEMA_COLUMNS]
        r = engine.evaluate(df)
        assert r["evaluable"].all()
        assert r.loc[2, "p_habitable"] == pytest.approx(r.loc[0, "p_habitable"], abs=0.03)

    def test_missing_teff_not_evaluable(self, engine):
        row = _sun_row("noteff", 1.0, 0.0, 1.0, 1.0)
        row.update(st_teff=np.nan)
        r = engine.evaluate(pd.DataFrame([row])[SCHEMA_COLUMNS])
        assert not bool(r.loc[0, "evaluable"]) and np.isnan(r.loc[0, "p_habitable"])

    def test_no_mass_no_radius(self, engine):
        row = _sun_row("nothing", 1.0, 0.0, 1.0, 1.0, mass_kind="none", radius_measured=False)
        r = engine.evaluate(pd.DataFrame([row])[SCHEMA_COLUMNS])
        assert r.loc[0, "case"] == "none" and not bool(r.loc[0, "evaluable"])

    def test_evolved_star_excluded(self, engine):
        row = _sun_row("giant", 1.0, 0.0, 1.0, 1.0)
        row.update(st_logg=2.5, st_logg_e1=0.05, st_logg_e2=-0.05)
        r = engine.evaluate(pd.DataFrame([row])[SCHEMA_COLUMNS])
        assert r.loc[0, "p_habitable"] < 1e-6
        eng2 = HabitabilityEngine(replace(engine.cfg, exclude_evolved=False), engine.rocky)
        assert eng2.evaluate(pd.DataFrame([row])[SCHEMA_COLUMNS]).loc[0, "p_habitable"] > 0.5

    def test_m_dwarf_atmosphere_penalty(self, engine):
        sun = _sun_row("sunlike", 1.0, 0.0, 1.0, 1.0)
        md = dict(sun, name="mdwarf", st_teff=3000.0, st_rad=0.15, st_mass=0.12, st_lum=0.0015,
                  st_lum_e1=1e-4, st_lum_e2=-1e-4, st_logg=5.17, a_au=np.sqrt(0.0015 / 0.9), period=np.nan)
        r = engine.evaluate(pd.DataFrame([sun, md])[SCHEMA_COLUMNS])
        assert r.loc[1, "p_atm_retention"] < r.loc[0, "p_atm_retention"]
        assert r.loc[1, "p_tidally_locked"] > 0.9 and r.loc[0, "p_tidally_locked"] < 0.1


def test_sensitivity_ranks_by_habitable_times_real():
    from habscan.benchmark import sensitivity_study

    rows = [_sun_row(f"p{i}", 1.0, 0.0, 1.0, 1.0) for i in range(3)]
    df = pd.DataFrame(rows)[SCHEMA_COLUMNS]
    p_real = pd.Series([1.0, 0.0, 1.0], index=df.index)
    frac, _ = sensitivity_study(df, HabitabilityConfig(n_samples=200), fixed_rocky_model(), k=2,
                                log10_k_shifts=(0.0,), widths=(0.25,), cmf_ranges=((0.15, 0.45),), p_real=p_real)
    assert frac.loc[1] == 0.0 and frac.loc[0] == 1.0 and frac.loc[2] == 1.0
