import numpy as np
import pytest

from habscan.constants import M_JUP_IN_EARTH
from habscan.physics import atmosphere as atm
from habscan.physics import habitable_zone as hz
from habscan.physics import mass_radius as mr
from habscan.physics import planet as pl


class TestHabitableZone:
    def test_sun_conservative_edges_match_kopparapu(self):
        # Kopparapu et al. 2014: conservative HZ of the Sun 0.95 - 1.67 AU
        inner = hz.hz_distance_au(1.0, hz.seff_boundary(5780, "runaway_greenhouse"))
        outer = hz.hz_distance_au(1.0, hz.seff_boundary(5780, "maximum_greenhouse"))
        assert inner == pytest.approx(0.950, abs=0.002)
        assert outer == pytest.approx(1.676, abs=0.002)

    def test_boundary_ordering_over_valid_range(self):
        t = np.linspace(2600, 7200, 50)
        rv, rg = hz.seff_boundary(t, "recent_venus"), hz.seff_boundary(t, "runaway_greenhouse")
        mg, em = hz.seff_boundary(t, "maximum_greenhouse"), hz.seff_boundary(t, "early_mars")
        assert np.all(rv > rg) and np.all(rg > mg) and np.all(mg > em)

    def test_runaway_greenhouse_mass_dependence(self):
        # more massive planets have a higher runaway flux (Kopparapu 2014)
        s01, s1, s5 = (hz.runaway_greenhouse_seff(5780, m) for m in (0.1, 1.0, 5.0))
        assert s01 < s1 < s5
        assert float(s1) == pytest.approx(1.107, abs=1e-3)
        # clamped outside the tabulated masses
        assert float(hz.runaway_greenhouse_seff(5780, 50.0)) == pytest.approx(float(s5))

    def test_membership_shape(self):
        s = np.array([0.2, 0.33, 0.5, 1.0, 1.5, 2.0])
        p = hz.hz_membership(s, 5780.0, 1.0)
        assert p[0] == 0.0 and p[-1] == 0.0
        assert p[2] == 1.0 and p[3] == 1.0
        assert 0 < p[1] < 1 and 0 < p[4] < 1

    def test_membership_monotone_in_inner_band(self):
        s = np.linspace(1.11, 1.77, 30)
        p = hz.hz_membership(s, 5780.0, 1.0)
        assert np.all(np.diff(p) <= 1e-12)

    def test_teff_out_of_range_flag(self):
        assert list(hz.teff_out_of_range([2000, 5000, 9000])) == [True, False, True]

    def test_eccentric_orbit_flux(self):
        assert float(hz.orbit_averaged_flux(1.0, 0.6)) == pytest.approx(1.25)


class TestMassRadius:
    def test_chen_kipping_earth_and_jupiter(self):
        assert float(mr.ck_radius_from_mass(1.0)) == pytest.approx(1.008, abs=0.005)
        rj = float(mr.ck_radius_from_mass(M_JUP_IN_EARTH))
        assert 10.0 < rj < 14.0

    def test_chen_kipping_continuity(self):
        for t in mr.CK_TRANSITIONS:
            lo, hi = mr.ck_mean_log_radius(t - 1e-9), mr.ck_mean_log_radius(t + 1e-9)
            assert float(lo) == pytest.approx(float(hi), abs=1e-6)

    def test_mass_from_radius_sampler(self):
        rng = np.random.default_rng(0)
        s = mr.MassFromRadiusSampler()
        m_earth = s.sample(np.full(20000, 1.0), rng)
        assert 0.6 < np.median(m_earth) < 1.6
        m_nep = s.sample(np.full(20000, 3.9), rng)
        assert 8 < np.median(m_nep) < 30

    def test_zeng_earth(self):
        assert float(mr.rocky_radius(1.0)) == pytest.approx(1.0, abs=0.01)
        assert float(mr.rocky_mass(mr.rocky_radius(3.0, 0.2), 0.2)) == pytest.approx(3.0)

    def test_composition_test(self):
        assert bool(mr.is_rocky_composition(1.0, 1.0))
        assert not bool(mr.is_rocky_composition(8.9, 2.37))  # K2-18 b: not rocky


class TestAtmosphere:
    def test_earth_reference(self):
        assert float(atm.relative_xuv_fluence(1.0, 1.0, 4.57)) == pytest.approx(1.0)

    def test_m_dwarf_receives_more_xuv(self):
        # same bolometric flux, 0.12 M_sun star at 5 Gyr (Proxima-like)
        assert float(atm.relative_xuv_fluence(1.0, 0.12, 5.0)) > 5.0

    def test_solar_system_classification(self):
        for name, ratio, p, obs in atm.solar_system_table():
            if obs is None or name == "Ganymede":  # Mars defines the line; Ganymede sits on it
                continue
            assert (p > 0.5) == obs, name

    def test_mars_on_the_shoreline(self):
        mars = [p for n, _, p, _ in atm.solar_system_table() if n == "Mars"][0]
        assert mars == pytest.approx(0.5, abs=1e-6)


class TestPlanet:
    def test_esi(self):
        assert float(pl.earth_similarity_index(1.0, 1.0)) == pytest.approx(1.0)
        # PHL value for TOI-700 d
        assert float(pl.earth_similarity_index(1.073, 0.8598268771)) == pytest.approx(0.94118, abs=1e-4)

    def test_kepler_third_law(self):
        assert float(pl.semi_major_axis_au(365.25, 1.0)) == pytest.approx(1.0)

    def test_luminosity(self):
        assert float(pl.luminosity_from_radius_teff(1.0, 5772.0)) == pytest.approx(1.0)

    def test_equilibrium_temperature(self):
        assert float(pl.equilibrium_temperature(1.0, albedo=0.3)) == pytest.approx(254.6, abs=1.0)

    def test_tidal_locking(self):
        earth = pl.tidal_locking_time_gyr(1.0, 1.0, 1.0, 1.0)
        proxima_b = pl.tidal_locking_time_gyr(0.0485, 0.122, 1.1, 1.03)
        assert earth > 10.0
        assert proxima_b < 0.01

    def test_stellar_mass_from_logg(self):
        assert float(pl.mass_from_logg_radius(4.438, 1.0)) == pytest.approx(1.0)
