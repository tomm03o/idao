"""Physical constants (SI) and reference values used across the package.

Values follow IAU 2015 nominal constants (Resolution B3) where applicable.
"""

G = 6.67430e-11  # m^3 kg^-1 s^-2 (CODATA 2018)

M_SUN = 1.988409870698051e30  # kg (GM_sun / G, IAU 2015)
R_SUN = 6.957e8  # m (IAU 2015 nominal)
L_SUN = 3.828e26  # W (IAU 2015 nominal)
T_SUN = 5772.0  # K (IAU 2015 nominal effective temperature)

M_EARTH = 5.972167867791379e24  # kg (GM_earth / G, IAU 2015)
R_EARTH = 6.3781e6  # m (IAU 2015 nominal equatorial)
M_JUP_IN_EARTH = 317.8284065946748
R_JUP_IN_EARTH = 11.208981

AU = 1.495978707e11  # m
DAY = 86400.0  # s
YEAR_DAYS = 365.25
GYR = 3.15576e16  # s

# Escape velocity of Earth (km/s): sqrt(2 G M_E / R_E)
V_ESC_EARTH_KMS = 11.186

# Age of the Sun (Gyr), Bonanno et al. 2002
AGE_SUN_GYR = 4.57

# Equilibrium temperature of a body at 1 AU around the Sun with zero albedo and
# full heat redistribution: T_sun * sqrt(R_sun / (2 AU)).
TEQ_EARTH_ZERO_ALBEDO = T_SUN * (R_SUN / (2.0 * AU)) ** 0.5  # ~278.3 K

# log10(g) of the Sun in cgs
LOGG_SUN = 4.438
