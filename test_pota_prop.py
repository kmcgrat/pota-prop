"""
Automated unit and integration tests for POTA Hunter
"""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from data_engine import (
    ActiveSpot,
    HuntedPark,
    compare_active_spots,
    fetch_active_spots,
    frequency_to_band,
    load_hunter_csv,
    normalize_ref,
    parse_frequency_khz,
)


from propagation_engine import (
    DEFAULT_HOME_GRID,
    SolarWeather,
    calculate_distance_and_bearing,
    calculate_qso_probability,
    calculate_solar_elevation,
    fetch_live_solar_weather,
    maidenhead_to_latlon,
)


class TestPOTADataEngine(unittest.TestCase):
    def test_frequency_parsing_and_bands(self):
        cases = [
            ("7128", 7128.0, "40m"),
            ("14054.0", 14054.0, "20m"),
            ("10112.0", 10112.0, "30m"),
            ("18100.0", 18100.0, "17m"),
            ("21336.0", 21336.0, "15m"),
            ("24915.0", 24915.0, "12m"),
            ("28400.0", 28400.0, "10m"),
            ("50313", 50313.0, "6m"),
            ("144200", 144200.0, "2m"),
            ("433080", 433080.0, "70cm"),
            ("3555.00", 3555.0, "80m"),
            ("1840.0", 1840.0, "160m"),
            ("5357.0", 5357.0, "60m"),
            ("14.074", 14074.0, "20m"),  # MHz float test
        ]
        for raw, expected_khz, expected_band in cases:
            khz = parse_frequency_khz(raw)
            self.assertAlmostEqual(khz, expected_khz, delta=1.0, msg=f"Failed kHz parse for {raw}")
            band = frequency_to_band(khz)
            self.assertEqual(band, expected_band, msg=f"Failed band mapping for {raw} -> {khz}")

    def test_dynamic_operator_spot_intelligence(self):
        from propagation_engine import parse_spot_evidence, maidenhead_to_latlon

        respots = [
            {"spotter": "W1AW", "comments": "59 in MA booming!", "spotTime": "2026-08-03T19:00:00"},
            {"spotter": "K1VT", "comments": "Loud signal in New England", "spotTime": "2026-08-03T19:05:00"},
        ]
        # Operator in Massachusetts (FN31pr)
        ma_lat, ma_lon = maidenhead_to_latlon("FN31pr")
        ev_ma = parse_spot_evidence(respots, home_lat=ma_lat, home_lon=ma_lon, user_grid="FN31pr")

        self.assertIn("1-Land", ev_ma.op_land_desc)
        self.assertGreater(ev_ma.empirical_boost_pct, 0)
        self.assertGreaterEqual(len(ev_ma.local_spotters), 1)

    def test_display_location_formatting(self):
        from data_engine import ActiveSpot, ComparedSpot

        # US spot
        spot_us = ActiveSpot(
            spot_id=1, activator="K1AA", frequency_raw="14040", frequency_khz=14040.0,
            band="20m", mode="CW", reference="US-1234", park_name="Test US Park",
            spot_time_raw="", spot_time_dt=None, spotter="", comments="", source="",
            location_desc="US-WV", grid4="", grid6="", latitude=None, longitude=None, count=1, expire=0
        )
        cs_us = ComparedSpot(spot=spot_us, is_new=True, qsos_hunted=0)
        self.assertEqual(cs_us.display_location, "US-WV")

        # Non-US spot (Canada)
        spot_ca = ActiveSpot(
            spot_id=2, activator="VE3BBB", frequency_raw="7125", frequency_khz=7125.0,
            band="40m", mode="SSB", reference="VE-0001", park_name="Algonquin",
            spot_time_raw="", spot_time_dt=None, spotter="", comments="", source="",
            location_desc="CA-ON", grid4="", grid6="", latitude=None, longitude=None, count=1, expire=0
        )
        cs_ca = ComparedSpot(spot=spot_ca, is_new=True, qsos_hunted=0)
        self.assertEqual(cs_ca.display_location, "CA-ON, Canada")

        # Non-US spot (Germany)
        spot_dl = ActiveSpot(
            spot_id=3, activator="DL1ABC", frequency_raw="14074", frequency_khz=14074.0,
            band="20m", mode="FT8", reference="DL-0020", park_name="Black Forest",
            spot_time_raw="", spot_time_dt=None, spotter="", comments="", source="",
            location_desc="DL-BY", grid4="", grid6="", latitude=None, longitude=None, count=1, expire=0
        )
        cs_dl = ComparedSpot(spot=spot_dl, is_new=True, qsos_hunted=0)
        self.assertEqual(cs_dl.display_location, "DL-BY, Germany")

    def test_hunter_csv_loading(self):
        csv_path = os.path.join(os.path.expanduser("~"), "Downloads", "hunter_parks.csv")
        if not os.path.exists(csv_path):
            self.skipTest("CSV file not found")

        hunted = load_hunter_csv(csv_path)
        self.assertGreater(len(hunted), 1000, "Should have loaded over 1000 hunted parks")

        # Test specific known parks from CSV
        self.assertIn("US-7211", hunted)
        self.assertEqual(hunted["US-7211"].park_name, "Finger Lake State Recreation Site")
        self.assertEqual(hunted["US-7211"].qsos, 1)

        self.assertIn("BB-0020", hunted)
        self.assertEqual(hunted["BB-0020"].qsos, 2)

    def test_comparator_logic(self):
        hunted_map = {
            "US-1049": HuntedPark(
                reference="US-1049",
                park_name="Oak Mountain State Park",
                location="Alabama",
                dx_entity="United States",
                hasc="US-AL",
                first_qso_date="2024-01-15",
                qsos=3,
            )
        }

        mock_spots = [
            ActiveSpot(
                spot_id=1,
                activator="WN4AT",
                frequency_raw="10112.0",
                frequency_khz=10112.0,
                band="30m",
                mode="CW",
                reference="US-1049",
                park_name="Oak Mountain State Park",
                spot_time_raw="2026-08-03T13:50:04",
                spot_time_dt=None,
                spotter="N4HAC",
                comments="RBN",
                source="RBN",
                location_desc="US-AL",
                grid4="EM63",
                grid6="EM63oh",
                latitude=33.32,
                longitude=-86.75,
                count=24,
                expire=1700,
            ),
            ActiveSpot(
                spot_id=2,
                activator="K2NEW",
                frequency_raw="14054.0",
                frequency_khz=14054.0,
                band="20m",
                mode="CW",
                reference="US-99999",
                park_name="Brand New Unhunted Park",
                spot_time_raw="2026-08-03T13:50:04",
                spot_time_dt=None,
                spotter="NA2B",
                comments="",
                source="Web",
                location_desc="US-NY",
                grid4="FN30",
                grid6="FN30dq",
                latitude=40.0,
                longitude=-73.0,
                count=1,
                expire=1700,
            ),
        ]

        compared = compare_active_spots(mock_spots, hunted_map, home_grid="EM98dh")
        self.assertEqual(len(compared), 2)

        # First spot should be hunted with 3 QSOs
        self.assertFalse(compared[0].is_new)
        self.assertEqual(compared[0].qsos_hunted, 3)
        self.assertEqual(compared[0].status_label, "Hunted (3)")
        self.assertGreater(compared[0].dx_percentage, 0)
        self.assertIsNotNone(compared[0].propagation)

        # Second spot should be NEW
        self.assertTrue(compared[1].is_new)
        self.assertEqual(compared[1].qsos_hunted, 0)
        self.assertEqual(compared[1].status_label, "NEW")
        self.assertGreater(compared[1].dx_percentage, 0)

    def test_propagation_engine(self):
        home_lat, home_lon = maidenhead_to_latlon("EM98dh")
        self.assertAlmostEqual(home_lat, 38.3125, places=3)
        self.assertAlmostEqual(home_lon, -81.7083, places=3)

        # 1. 2m band over horizon (Japan PM95) -> 0%
        ja_lat, ja_lon = maidenhead_to_latlon("PM95")
        res_2m_ja = calculate_qso_probability(
            home_lat, home_lon, ja_lat, ja_lon, "PM95", 144200.0, "2m", "SSB"
        )
        self.assertEqual(res_2m_ja.probability_pct, 0)
        self.assertIn("Beyond VHF Horizon", res_2m_ja.path_summary)

        # 2. Local 2m line of sight (< 35 km) -> high %
        res_2m_local = calculate_qso_probability(
            home_lat, home_lon, home_lat + 0.1, home_lon + 0.1, "EM98dh", 144200.0, "2m", "FM"
        )
        self.assertGreaterEqual(res_2m_local.probability_pct, 80)

        # 3. 20m FT8 Skywave to US State
        al_lat, al_lon = maidenhead_to_latlon("EM63")
        res_20m_al = calculate_qso_probability(
            home_lat, home_lon, al_lat, al_lon, "EM63", 14074.0, "20m", "FT8",
            solar_weather=SolarWeather(sfi=150.0, k_index=1.0)
        )
        self.assertGreater(res_20m_al.probability_pct, 0)

    def test_qrt_comment_detection(self):
        home_lat, home_lon = maidenhead_to_latlon("EM98dh")
        mock_spot_qrt = ActiveSpot(
            spot_id=99,
            activator="W1AW",
            frequency_raw="14040.0",
            frequency_khz=14040.0,
            band="20m",
            mode="CW",
            reference="US-0001",
            park_name="Acadia National Park",
            spot_time_raw="2026-08-04T10:00:00",
            spot_time_dt=None,
            spotter="K3AA",
            comments="73 QRT now thanks for park!",
            source="Web",
            location_desc="US-ME",
            grid4="FN54",
            grid6="FN54bh",
            latitude=44.3,
            longitude=-68.2,
            count=1,
            expire=1700,
        )

        compared = compare_active_spots([mock_spot_qrt], {}, home_grid="EM98dh")
        self.assertEqual(len(compared), 1)
        self.assertEqual(compared[0].dx_percentage, 0)
        self.assertEqual(compared[0].propagation.path_summary, "Activator QRT (Off the air)")
        self.assertEqual(compared[0].propagation.path_type, "Activator QRT / Station Off Air")

    def test_goes_solar_flare_and_psk_reporter(self):
        home_lat, home_lon = maidenhead_to_latlon("EM98dh")
        al_lat, al_lon = maidenhead_to_latlon("EM63")

        # Test Solar Flare R2 Radio Blackout penalty
        flare_weather = SolarWeather(
            sfi=160.0, k_index=2.0, xray_flux=6e-5, xray_class="M6.0",
            radio_blackout_scale="R2 Moderate Radio Blackout", flare_penalty=-25
        )
        res_flare = calculate_qso_probability(
            home_lat, home_lon, al_lat, al_lon, "EM63", 14074.0, "20m", "FT8",
            solar_weather=flare_weather
        )
        self.assertIn("R2 Moderate Radio Blackout", res_flare.path_summary)

        # Test PSKReporter live decode boost
        mock_spot_psk = ActiveSpot(
            spot_id=101, activator="K8PSK", frequency_raw="14074.0", frequency_khz=14074.0,
            band="20m", mode="FT8", reference="US-0044", park_name="Test Park",
            spot_time_raw="2026-08-04T10:00:00", spot_time_dt=None, spotter="K8AA",
            comments="FT8 decode on PSKReporter in EM98", source="Web", location_desc="US-OH",
            grid4="EN90", grid6="EN9012", latitude=40.0, longitude=-82.0, count=1, expire=1700
        )
        compared = compare_active_spots([mock_spot_psk], {}, home_grid="EM98dh")
        self.assertEqual(len(compared), 1)
        self.assertTrue(compared[0].spot_evidence.has_psk_reporter_decode)

    def test_a_index_storm_penalty(self):
        home_lat, home_lon = maidenhead_to_latlon("EM98dh")
        ca_lat, ca_lon = maidenhead_to_latlon("CM87")  # California DX path

        res_quiet = calculate_qso_probability(
            home_lat, home_lon, ca_lat, ca_lon, "CM87", 14074.0, "20m", "FT8",
            solar_weather=SolarWeather(sfi=150.0, k_index=1.0, a_index=5.0)
        )
        res_storm_a = calculate_qso_probability(
            home_lat, home_lon, ca_lat, ca_lon, "CM87", 14074.0, "20m", "FT8",
            solar_weather=SolarWeather(sfi=150.0, k_index=1.0, a_index=45.0)
        )
        self.assertLess(res_storm_a.probability_pct, res_quiet.probability_pct)




    def test_spot_decay_logic(self):
        from datetime import datetime, timezone, timedelta
        from data_engine import ComparedSpot

        now = datetime.now(timezone.utc)
        spot_fresh = ActiveSpot(
            spot_id=10, activator="W1AW", frequency_raw="14040", frequency_khz=14040.0,
            band="20m", mode="CW", reference="US-0001", park_name="Acadia",
            spot_time_raw="2026-08-03T14:00:00", spot_time_dt=now - timedelta(minutes=5),
            spotter="K3AA", comments="", source="Web", location_desc="US-ME",
            grid4="FN54", grid6="FN54bh", latitude=44.3, longitude=-68.2, count=1, expire=3300
        )
        cs_fresh = ComparedSpot(spot=spot_fresh, is_new=True, qsos_hunted=0)
        self.assertAlmostEqual(cs_fresh.age_minutes, 5.0, delta=0.5)
        self.assertEqual(cs_fresh.decay_status, "Fresh")
        self.assertEqual(cs_fresh.decay_color, "#3fb950")
        self.assertEqual(cs_fresh.expire_mins_remaining, 55)

        # Aging spot (35 mins)
        spot_aging = ActiveSpot(
            spot_id=11, activator="W1AW", frequency_raw="14040", frequency_khz=14040.0,
            band="20m", mode="CW", reference="US-0001", park_name="Acadia",
            spot_time_raw="2026-08-03T13:30:00", spot_time_dt=now - timedelta(minutes=35),
            spotter="K3AA", comments="", source="Web", location_desc="US-ME",
            grid4="FN54", grid6="FN54bh", latitude=44.3, longitude=-68.2, count=1, expire=1500
        )
        cs_aging = ComparedSpot(spot=spot_aging, is_new=True, qsos_hunted=0)
        self.assertEqual(cs_aging.decay_status, "Aging")
        self.assertEqual(cs_aging.decay_color, "#e3b341")

    def test_p2p_mode_logic(self):
        hunted_map = {}
        mock_spots = [
            ActiveSpot(
                spot_id=20, activator="K1P2P", frequency_raw="7125", frequency_khz=7125.0,
                band="40m", mode="SSB", reference="US-5000", park_name="Field Park",
                spot_time_raw="2026-08-03T14:00:00", spot_time_dt=None, spotter="K8AA",
                comments="", source="Web", location_desc="US-OH", grid4="EN80", grid6="EN80aa",
                latitude=40.0, longitude=-82.0, count=1, expire=1800
            ),
            ActiveSpot(
                spot_id=21, activator="K2SAME", frequency_raw="7125", frequency_khz=7125.0,
                band="40m", mode="SSB", reference="US-1234", park_name="My Current Park",
                spot_time_raw="2026-08-03T14:00:00", spot_time_dt=None, spotter="K8BB",
                comments="", source="Web", location_desc="US-WV", grid4="EM98", grid6="EM98dh",
                latitude=38.3, longitude=-81.7, count=1, expire=1800
            ),
        ]

        compared = compare_active_spots(
            mock_spots, hunted_map, home_grid="EM98dh",
            p2p_mode=True, p2p_my_park="US-1234", p2p_grid="EM88aa"
        )
        self.assertEqual(len(compared), 2)
        # First spot is different park -> P2P eligible
        self.assertTrue(compared[0].is_p2p_eligible)
        self.assertFalse(compared[0].is_p2p_same_park)
        # Second spot is same park -> Not eligible, same park, but 99% QSO score
        self.assertFalse(compared[1].is_p2p_eligible)
        self.assertTrue(compared[1].is_p2p_same_park)
        self.assertEqual(compared[1].dx_percentage, 99)
        self.assertIn("Same Park", compared[1].propagation.path_type)


class TestPOTAComparatorGUIHeadless(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_gui_initialization_and_filtering(self):
        from pota_prop import POTAPropApp
        window = POTAPropApp()
        self.assertIsNotNone(window)
        if not window.hunted_parks:
            window.hunted_parks = {
                "US-0001": HuntedPark(
                    reference="US-0001", park_name="Acadia National Park", location="Maine",
                    dx_entity="United States", hasc="US-ME", first_qso_date="2024-01-01", qsos=5
                )
            }
        self.assertGreater(len(window.hunted_parks), 0)

        # Check % DX filter
        window.combo_dx.setCurrentIndex(1)  # >= 25%
        window.apply_filters()

        # Check status filter
        window.combo_status.setCurrentIndex(1)  # New Only
        window.apply_filters()

        window.combo_band.setCurrentIndex(window.combo_band.findText("20m"))
        window.apply_filters()

        window.reset_filters()
        self.assertEqual(window.combo_status.currentIndex(), 0)
        self.assertEqual(window.combo_dx.currentIndex(), 0)

        # Test on_spots_fetched & P2P mode toggling
        mock_spot = ActiveSpot(
            spot_id=1, activator="W1AW", frequency_raw="14040", frequency_khz=14040.0,
            band="20m", mode="CW", reference="US-0001", park_name="Acadia",
            spot_time_raw="2026-08-03T14:00:00", spot_time_dt=None,
            spotter="K3AA", comments="", source="Web", location_desc="US-ME",
            grid4="FN54", grid6="FN54bh", latitude=44.3, longitude=-68.2, count=1, expire=3300
        )
        window.on_spots_fetched([mock_spot], SolarWeather(sfi=145.0, k_index=2.0))
        self.assertEqual(window.table.rowCount(), 1)

        # Test callsign lookup
        window.chk_p2p.setChecked(False)
        window.txt_my_call.setText("W1AW")
        window.on_my_call_changed()
        self.assertEqual(window.txt_grid.text().upper(), "FN31PR")
        self.assertEqual(window.current_grid.upper(), "FN31PR")

        # Toggle P2P mode
        window.chk_p2p.setChecked(True)
        window.txt_p2p_park.setText("US-0001")
        window.on_p2p_park_changed()
        self.assertEqual(window.card_unique_parks.lbl_title.text(), "P2P AVAILABLE")
        # Should auto-detect Acadia grid FN54bh and update single Grid window
        self.assertEqual(window.txt_grid.text().upper(), "FN54BH")
        self.assertEqual(window.current_grid.upper(), "FN54BH")

        # Toggle P2P mode off -> should revert Grid back to Home QTH FN31PR
        window.chk_p2p.setChecked(False)
        self.assertEqual(window.txt_grid.text().upper(), "FN31PR")
        self.assertEqual(window.current_grid.upper(), "FN31PR")

        window.refresh_timer.stop()
        window.threadpool.waitForDone(1000)
        window.close()

    def test_manually_worked_park_tracking(self):
        from pota_prop import POTAPropApp
        window = POTAPropApp()

        # Mock active spot
        mock_spot = ActiveSpot(
            spot_id=50, activator="W8XYZ", frequency_raw="14040", frequency_khz=14040.0,
            band="20m", mode="CW", reference="US-9999", park_name="Test Unhunted Park",
            spot_time_raw="", spot_time_dt=None, spotter="", comments="", source="",
            location_desc="US-WV", grid4="EM98", grid6="EM98dh", latitude=38.3, longitude=-81.7,
            count=1, expire=3000
        )
        window.on_spots_fetched([mock_spot], SolarWeather(sfi=140.0, k_index=1.0))

        window.manually_worked_parks.discard("US-9999")

        # Initially unworked
        self.assertNotIn("US-9999", window.manually_worked_parks)


        # Mark as WORKED
        window.toggle_park_worked("US-9999", force_state=True)
        self.assertIn("US-9999", window.manually_worked_parks)

        # Test status filter 3 (Manually Worked Only)
        window.combo_status.setCurrentIndex(3)
        window.apply_filters()
        self.assertEqual(window.table.rowCount(), 1)

        # Unmark WORKED
        window.toggle_park_worked("US-9999", force_state=False)
        self.assertNotIn("US-9999", window.manually_worked_parks)

        window.refresh_timer.stop()
        window.threadpool.waitForDone(1000)
        window.close()

    def test_filter_menu_persistence(self):
        from pota_prop import POTAPropApp
        window1 = POTAPropApp()

        # Set specific filters
        idx_band = window1.combo_band.findText("20m")
        if idx_band >= 0:
            window1.combo_band.setCurrentIndex(idx_band)

        idx_mode = window1.combo_mode.findText("CW")
        if idx_mode >= 0:
            window1.combo_mode.setCurrentIndex(idx_mode)

        window1.combo_status.setCurrentIndex(1)  # New Only
        window1.combo_dx.setCurrentIndex(2)      # >= 50
        window1.combo_refresh.setCurrentIndex(3) # Every 2 min

        window1.apply_filters()
        window1.refresh_timer.stop()
        window1.threadpool.waitForDone(1000)
        window1.close()

        # Open new instance to test QSettings restoration
        window2 = POTAPropApp()
        self.assertEqual(window2.combo_band.currentText(), "20m")
        self.assertEqual(window2.combo_mode.currentText(), "CW")
        self.assertEqual(window2.combo_status.currentIndex(), 0)  # Always defaults to 'All' (0) on startup
        self.assertEqual(window2.combo_dx.currentIndex(), 2)
        self.assertEqual(window2.combo_refresh.currentIndex(), 3)
        self.assertTrue(window2.refresh_timer.isActive(), "refresh_timer should be active on startup when set to 2 min")
        self.assertEqual(window2.refresh_timer.interval(), 120000)

        window2.refresh_timer.stop()
        window2.threadpool.waitForDone(1000)
        window2.close()


class TestStationPropagationModeling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_antenna_presets(self):
        from propagation_engine import ANTENNA_PRESETS, resolve_antenna_preset
        self.assertIn("EFHW", ANTENNA_PRESETS)
        self.assertIn("DIPOLE", ANTENNA_PRESETS)
        self.assertIn("VERTICAL", ANTENNA_PRESETS)
        self.assertIn("BEAM", ANTENNA_PRESETS)
        self.assertIn("MAG_LOOP", ANTENNA_PRESETS)
        self.assertIn("RANDOM_WIRE", ANTENNA_PRESETS)

        # Test resolution
        efhw = resolve_antenna_preset("EFHW")
        self.assertEqual(efhw["key"], "EFHW")
        beam = resolve_antenna_preset("Beam / Yagi / Hexbeam")
        self.assertEqual(beam["key"], "BEAM")

    def test_antenna_elevation_gain_patterns(self):
        from propagation_engine import calculate_antenna_elevation_gain

        # 1. Low angle DX path (10 deg takeoff) on 20m (14 MHz)
        g_beam_dx, _ = calculate_antenna_elevation_gain("BEAM", takeoff_angle_deg=10.0, freq_mhz=14.0)
        g_vert_dx, _ = calculate_antenna_elevation_gain("VERTICAL", takeoff_angle_deg=10.0, freq_mhz=14.0)
        g_dip_dx, _ = calculate_antenna_elevation_gain("DIPOLE", takeoff_angle_deg=10.0, freq_mhz=14.0)
        g_rand_dx, _ = calculate_antenna_elevation_gain("RANDOM_WIRE", takeoff_angle_deg=10.0, freq_mhz=14.0)

        self.assertGreater(g_beam_dx, g_vert_dx)
        self.assertGreater(g_vert_dx, g_dip_dx)
        self.assertGreater(g_dip_dx, g_rand_dx)
        self.assertGreaterEqual(g_beam_dx, 9.0)

        # 2. High angle NVIS path (55 deg takeoff) on 40m (7 MHz)
        g_dip_nvis, _ = calculate_antenna_elevation_gain("DIPOLE", takeoff_angle_deg=55.0, freq_mhz=7.0)
        g_vert_nvis, _ = calculate_antenna_elevation_gain("VERTICAL", takeoff_angle_deg=55.0, freq_mhz=7.0)
        g_beam_nvis, _ = calculate_antenna_elevation_gain("BEAM", takeoff_angle_deg=55.0, freq_mhz=7.0)

        # Dipole has high NVIS lobe; Vertical has deep overhead null!
        self.assertGreater(g_dip_nvis, g_beam_nvis)
        self.assertGreater(g_dip_nvis, 5.0)
        self.assertLess(g_vert_nvis, -4.0)

    def test_power_and_antenna_link_budget_impact(self):
        from propagation_engine import calculate_qso_probability
        from datetime import datetime, timezone

        noon_utc = datetime(2026, 8, 4, 18, 0, 0, tzinfo=timezone.utc)
        
        # 5W QRP with Mag Loop vs 1500W Legal limit with Beam on 20m SSB to California
        res_qrp = calculate_qso_probability(
            home_lat=38.31,
            home_lon=-81.71,
            target_lat=34.0,
            target_lon=-118.0,
            target_grid="DM04",
            freq_khz=14225.0,
            band="20m",
            mode="SSB",
            tx_power_watts=5.0,
            antenna_type="MAG_LOOP",
            dt_utc=noon_utc,
        )
        res_qro = calculate_qso_probability(
            home_lat=38.31,
            home_lon=-81.71,
            target_lat=34.0,
            target_lon=-118.0,
            target_grid="DM04",
            freq_khz=14225.0,
            band="20m",
            mode="SSB",
            tx_power_watts=1500.0,
            antenna_type="BEAM",
            dt_utc=noon_utc,
        )

        self.assertLess(res_qrp.probability_pct, res_qro.probability_pct)
        self.assertLess(res_qrp.station_offset_db, 0.0)
        self.assertGreater(res_qro.station_offset_db, 10.0)
        self.assertGreater(res_qro.predicted_snr_db, res_qrp.predicted_snr_db + 25.0)

    def test_antenna_type_differentiation_at_same_power(self):
        from propagation_engine import calculate_qso_probability
        from datetime import datetime, timezone

        noon_utc = datetime(2026, 8, 4, 18, 0, 0, tzinfo=timezone.utc)
        
        # Fixed 100W power on 20m SSB DX path (WV to CA, ~3300 km)
        res_beam = calculate_qso_probability(
            home_lat=38.31,
            home_lon=-81.71,
            target_lat=34.0,
            target_lon=-118.0,
            target_grid="DM04",
            freq_khz=14225.0,
            band="20m",
            mode="SSB",
            tx_power_watts=100.0,
            antenna_type="BEAM",
            dt_utc=noon_utc,
        )
        res_dipole = calculate_qso_probability(
            home_lat=38.31,
            home_lon=-81.71,
            target_lat=34.0,
            target_lon=-118.0,
            target_grid="DM04",
            freq_khz=14225.0,
            band="20m",
            mode="SSB",
            tx_power_watts=100.0,
            antenna_type="DIPOLE",
            dt_utc=noon_utc,
        )
        res_random = calculate_qso_probability(
            home_lat=38.31,
            home_lon=-81.71,
            target_lat=34.0,
            target_lon=-118.0,
            target_grid="DM04",
            freq_khz=14225.0,
            band="20m",
            mode="SSB",
            tx_power_watts=100.0,
            antenna_type="RANDOM_WIRE",
            dt_utc=noon_utc,
        )

        # Beam should have higher gain, higher SNR, and higher probability than Dipole and Random Wire
        self.assertGreater(res_beam.antenna_gain_dbi, res_dipole.antenna_gain_dbi)
        self.assertGreater(res_dipole.antenna_gain_dbi, res_random.antenna_gain_dbi)
        self.assertGreater(res_beam.predicted_snr_db, res_dipole.predicted_snr_db)
        self.assertGreater(res_dipole.predicted_snr_db, res_random.predicted_snr_db)
        self.assertGreaterEqual(res_beam.probability_pct, res_dipole.probability_pct)
        self.assertGreater(res_dipole.probability_pct, res_random.probability_pct)

    def test_voacap_ray_tracing_and_skip_zone(self):
        from propagation_engine import calculate_qso_probability, SolarWeather
        from datetime import datetime, timezone

        # 1. 20m nighttime short distance (e.g. 250 miles) under degraded solar condition
        # FoF2 drops at night -> 14.1 MHz penetrates into space (skip zone)
        night_time = datetime(2026, 8, 4, 4, 0, 0, tzinfo=timezone.utc)  # 04:00 UTC = Nighttime US
        res_night_20m = calculate_qso_probability(
            home_lat=38.31,
            home_lon=-81.71,
            target_lat=40.0,
            target_lon=-83.0,
            target_grid="EN80",
            freq_khz=14040.0,
            band="20m",
            mode="CW",
            solar_weather=SolarWeather(sfi=80.0, k_index=4.0),
            dt_utc=night_time,
        )
        self.assertIn("Skip Zone", res_night_20m.path_summary)
        self.assertLessEqual(res_night_20m.probability_pct, 15)

        # 2. DX Multi-Hop 2F2 / 3F2 path across Atlantic (US to Europe ~6500 km)
        res_eu = calculate_qso_probability(
            home_lat=38.31,
            home_lon=-81.71,
            target_lat=51.5,
            target_lon=-0.12,
            target_grid="IO91",
            freq_khz=14074.0,
            band="20m",
            mode="FT8",
            solar_weather=SolarWeather(sfi=150.0, k_index=1.0),
            dt_utc=datetime(2026, 6, 21, 15, 0, 0, tzinfo=timezone.utc),
        )
        self.assertIn(res_eu.ray_mode, ("2F2", "3F2"))
        self.assertGreater(res_eu.hop_count, 1)
        self.assertGreater(res_eu.takeoff_angle_deg, 0.0)
        self.assertIsNotNone(res_eu.predicted_snr_db)

    def test_lightning_engine_and_qrn_noise_surge(self):
        from lightning_engine import RegionalLightningSummary, StormCell
        from propagation_engine import calculate_qso_probability

        # Simulate a severe thunderstorm cluster 85 miles away
        storms = [
            StormCell(latitude=39.0, longitude=-82.5, intensity_weight=2.0, event_type="Severe Thunderstorm", distance_miles=85.0)
        ]
        summary = RegionalLightningSummary(
            active_storm_count=1,
            closest_storm_miles=85.0,
            storm_cells=storms,
        )

        qrn_80m = summary.get_qrn_surge_db(3.7)
        qrn_20m = summary.get_qrn_surge_db(14.1)

        self.assertGreater(qrn_80m, 10.0)
        self.assertGreater(qrn_80m, qrn_20m)  # Lower HF frequencies suffer greater QRN

        # Compare QSO score with and without lightning QRN
        res_clean = calculate_qso_probability(
            home_lat=38.31, home_lon=-81.71, target_lat=35.0, target_lon=-85.0,
            target_grid="EM75", freq_khz=7150.0, band="40m", mode="SSB",
        )
        res_storm = calculate_qso_probability(
            home_lat=38.31, home_lon=-81.71, target_lat=35.0, target_lon=-85.0,
            target_grid="EM75", freq_khz=7150.0, band="40m", mode="SSB",
            lightning_summary=summary,
        )
        self.assertLess(res_storm.probability_pct, res_clean.probability_pct)
        self.assertGreater(res_storm.qrn_surge_db, 0.0)

    def test_multicore_parallel_spot_evaluation(self):
        from data_engine import ActiveSpot, compare_active_spots

        mock_spots = [
            ActiveSpot(
                spot_id=i,
                activator=f"K{i}ABC",
                frequency_raw="14040.0",
                frequency_khz=14040.0 + (i % 50),
                band="20m",
                mode="CW",
                reference=f"US-{i:04d}",
                park_name=f"Park {i}",
                spot_time_raw="2026-08-04T12:00:00",
                spot_time_dt=None,
                spotter="K8AA",
                comments="",
                source="Web",
                location_desc="US-OH",
                grid4="EN90",
                grid6="EN90ab",
                latitude=40.0 + (i * 0.05),
                longitude=-82.0 - (i * 0.05),
                count=1,
                expire=1700,
            )
            for i in range(25)
        ]

        compared = compare_active_spots(mock_spots, {}, home_grid="EM98dh")
        self.assertEqual(len(compared), 25)
        for c in compared:
            self.assertIsNotNone(c.propagation)
            self.assertIsNotNone(c.propagation.predicted_snr_db)
            self.assertGreaterEqual(c.propagation.probability_pct, 0)

    def test_lightning_activity_1_to_10_scale(self):
        from lightning_engine import RegionalLightningSummary, StormCell

        # 1. Clear - Level 1
        summary_clear = RegionalLightningSummary()
        act1 = summary_clear.get_activity_level()
        self.assertEqual(act1.level, 1)
        self.assertEqual(act1.label, "Clear")
        self.assertFalse(act1.is_disconnect_advisory)

        # 2. Notable - Level 6 (160 miles: within 100-150 mi threshold = level 6 via new scale,
        #    actually 150-250 = 5, so 160 = 5 now.  Let's test 130 miles = level 6)
        summary_l5 = RegionalLightningSummary(
            active_storm_count=2,
            closest_storm_miles=160.0,
            closest_storm_bearing=270.0,
            storm_cells=[
                StormCell(latitude=38.0, longitude=-84.5, distance_miles=160.0, bearing_deg=270.0, headline="Severe Storm")
            ],
        )
        act5 = summary_l5.get_activity_level()
        self.assertEqual(act5.level, 5)  # 150-250 mi = level 5 (Elevated)
        self.assertEqual(act5.label, "Elevated")
        self.assertFalse(act5.is_disconnect_advisory)

        summary_l6 = RegionalLightningSummary(
            active_storm_count=1,
            closest_storm_miles=120.0,
            closest_storm_bearing=270.0,
            storm_cells=[
                StormCell(latitude=38.0, longitude=-84.5, distance_miles=120.0, bearing_deg=270.0, headline="Severe Storm")
            ],
        )
        act6 = summary_l6.get_activity_level()
        self.assertEqual(act6.level, 6)  # 100-150 mi = level 6 (Notable)
        self.assertEqual(act6.label, "Notable")
        self.assertFalse(act6.is_disconnect_advisory)

        # 3. Very Close Proximity - Level 9 (18 miles -> Disconnect Advisory)
        summary_sev = RegionalLightningSummary(
            active_storm_count=1,
            closest_storm_miles=18.0,
            closest_storm_bearing=180.0,
            storm_cells=[
                StormCell(latitude=38.0, longitude=-81.7, distance_miles=18.0, bearing_deg=180.0, headline="Tornado Warning")
            ],
        )
        act9 = summary_sev.get_activity_level()
        self.assertEqual(act9.level, 9)
        self.assertEqual(act9.label, "Very Close Proximity")
        self.assertTrue(act9.is_disconnect_advisory)
        self.assertIn("WARNING", act9.advisory)

        # 4. Extreme Immediate Hazard - Level 10 (5 miles -> Immediate Unplug)
        summary_danger = RegionalLightningSummary(
            active_storm_count=1,
            closest_storm_miles=5.0,
            storm_cells=[
                StormCell(latitude=38.3, longitude=-81.7, distance_miles=5.0)
            ],
        )
        act10 = summary_danger.get_activity_level()
        self.assertEqual(act10.level, 10)
        self.assertTrue(act10.is_disconnect_advisory)
        self.assertIn("DANGER", act10.advisory)

        # 5. Frequent Lightning Boost (closest 58 miles is base Level 7; boosted to Level 8 with frequent clusters)
        summary_freq = RegionalLightningSummary(
            active_storm_count=6,
            closest_storm_miles=58.0,
            closest_storm_bearing=240.0,
            storm_cells=[
                StormCell(latitude=38.0, longitude=-82.5, distance_miles=58.0, bearing_deg=240.0),
                StormCell(latitude=38.2, longitude=-82.8, distance_miles=65.0, bearing_deg=250.0),
                StormCell(latitude=37.8, longitude=-82.1, distance_miles=75.0, bearing_deg=230.0),
                StormCell(latitude=38.5, longitude=-83.0, distance_miles=90.0, bearing_deg=270.0),
                StormCell(latitude=37.5, longitude=-81.5, distance_miles=95.0, bearing_deg=190.0),
                StormCell(latitude=39.0, longitude=-82.0, distance_miles=130.0, bearing_deg=330.0),
            ],
        )
        act_freq = summary_freq.get_activity_level()
        self.assertEqual(act_freq.level, 8)
        self.assertEqual(act_freq.label, "Frequent Lightning")
        self.assertFalse(act_freq.is_disconnect_advisory)
        self.assertIn("~58 mi", act_freq.description)
        self.assertIn("Frequent lightning", act_freq.description)
        self.assertIn("~58 mi", act_freq.advisory)

        # Test tooltip HTML formatting
        html = summary_sev.format_tooltip_html()
        self.assertIn("Nearest NWS Warning", html)
        self.assertIn("18.0 miles @ 180°", html)
        self.assertIn("Nearest Lightning Activity", html)
        self.assertIn("Station Safety Advisory", html)
        self.assertIn("Disconnect", html)

    def test_gui_lightning_card_telemetry(self):
        from pota_prop import POTAPropApp
        from lightning_engine import RegionalLightningSummary, StormCell
        from propagation_engine import SolarWeather
        from data_engine import ActiveSpot

        window = POTAPropApp()
        self.assertIsNotNone(window.card_lightning)
        self.assertEqual(window.card_lightning.lbl_title.text(), "LIGHTNING")
        self.assertIn(window.card_lightning.lbl_value.text(), [str(i) for i in range(1, 11)])

        # Simulate receiving active spot with severe level 9 storm
        sev_summary = RegionalLightningSummary(
            active_storm_count=3,
            total_strikes_detected=900,
            strike_rate_per_min=60,
            closest_storm_miles=20.0,
            closest_storm_bearing=220.0,
            storm_cells=[
                StormCell(
                    latitude=38.0,
                    longitude=-81.9,
                    distance_miles=20.0,
                    bearing_deg=220.0,
                    estimated_strikes_per_min=20,
                    estimated_strikes_15m=300,
                )
            ],
            qrn_surge_40m_db=22.0,
        )

        mock_spot = ActiveSpot(
            spot_id=99, activator="W8LGT", frequency_raw="7150", frequency_khz=7150.0,
            band="40m", mode="SSB", reference="US-0001", park_name="Acadia",
            spot_time_raw="", spot_time_dt=None, spotter="", comments="", source="",
            location_desc="US-ME", grid4="FN54", grid6="FN54bh", latitude=44.3, longitude=-68.2,
            count=1, expire=3000
        )

        window.on_spots_fetched([mock_spot], SolarWeather(sfi=150.0, k_index=2.0), sev_summary)

        # Check Lightning Card telemetry
        self.assertEqual(window.card_lightning.lbl_value.text(), "9")
        self.assertEqual(window.card_lightning.lbl_value.alignment(), Qt.AlignmentFlag.AlignCenter)
        self.assertIn("Nearest Lightning Activity", window.card_lightning.toolTip())

        # Check Space Weather Card text & tooltip
        self.assertIsNotNone(window.card_solar)
        self.assertIn("Flare: B1.0", window.card_solar.lbl_value.text())
        self.assertEqual(window.card_solar.lbl_value.alignment(), Qt.AlignmentFlag.AlignCenter)
        solar_tooltip = window.card_solar.toolTip()
        self.assertIn("Solar Flux (SFI)", solar_tooltip)
        self.assertIn("Planetary K-Index", solar_tooltip)
        self.assertIn("Planetary A-Index", solar_tooltip)
        self.assertIn("GOES Solar Flare", solar_tooltip)
        self.assertIn("SFI 150 sfu", solar_tooltip)

        window.refresh_timer.stop()
        window.threadpool.waitForDone(1000)
        window.close()

    def test_solar_weather_assessments_and_tooltip(self):
        """Test NOAA SWPC category ratings, color coding, and HTML tooltip generation."""
        # 1. Excellent Solar Weather
        sw_exc = SolarWeather(sfi=165.0, k_index=1.0, a_index=4.0, xray_class="B1.2", radio_blackout_scale="R0 (Normal)")
        sfi_lbl, sfi_col, sfi_desc = sw_exc.get_sfi_assessment()
        self.assertIn("Excellent", sfi_lbl)
        self.assertEqual(sfi_col, "#3fb950")

        k_lbl, k_col, _ = sw_exc.get_k_assessment()
        self.assertIn("Quiet", k_lbl)
        self.assertEqual(k_col, "#3fb950")

        ov_lbl, ov_col, _ = sw_exc.get_overall_assessment()
        self.assertIn("Excellent", ov_lbl)
        self.assertEqual(ov_col, "#3fb950")

        html = sw_exc.format_tooltip_html()
        self.assertIn("165 sfu", html)
        self.assertIn("NOAA Space Weather", html)
        self.assertIn("GOES-16/18 Solar Telemetry", html)

        # 2. Severe Storm / X-Class Flare Blackout
        sw_storm = SolarWeather(
            sfi=65.0, k_index=7.0, a_index=65.0, xray_class="X2.3", radio_blackout_scale="R3 (Strong Blackout)"
        )
        sfi_lbl2, sfi_col2, _ = sw_storm.get_sfi_assessment()
        self.assertIn("Poor", sfi_lbl2)
        self.assertEqual(sfi_col2, "#f85149")

        k_lbl2, k_col2, _ = sw_storm.get_k_assessment()
        self.assertIn("G3 Strong Storm", k_lbl2)

        xr_lbl2, xr_col2, _ = sw_storm.get_xray_assessment()
        self.assertIn("X2.3", xr_lbl2)
        self.assertEqual(xr_col2, "#ff2a55")

        ov_lbl2, ov_col2, _ = sw_storm.get_overall_assessment()
        self.assertIn("Storm Blackout", ov_lbl2)
        self.assertEqual(ov_col2, "#f85149")

    def test_self_spot_exclusion_and_qrt_handling(self):
        from propagation_engine import (
            is_self_spot,
            parse_spot_evidence,
            maidenhead_to_latlon,
            calculate_qso_probability,
        )
        from data_engine import ActiveSpot, compare_active_spots

        # 1. Callsign matching unit tests
        self.assertTrue(is_self_spot("K8XYZ", "K8XYZ"))
        self.assertTrue(is_self_spot("K8XYZ/P", "K8XYZ"))
        self.assertTrue(is_self_spot("VE3/K8XYZ", "K8XYZ"))
        self.assertTrue(is_self_spot("K8XYZ", "K8XYZ/QRP"))
        self.assertFalse(is_self_spot("W1AW", "K8XYZ"))
        self.assertFalse(is_self_spot("K8AA", "K8XYZ"))

        home_lat, home_lon = maidenhead_to_latlon("EM98dh")  # Charleston, WV

        # 2. Self-spots only: should NOT give local spotter + boost or inflate respot count
        self_respots = [
            {"spotter": "W8WV", "comments": "CQ POTA on 7225", "spotTime": "2026-08-04T12:00:00"},
            {"spotter": "W8WV/P", "comments": "Still active 7225 SSB", "spotTime": "2026-08-04T12:05:00"},
            {"spotter": "W8WV", "comments": "59 in park", "spotTime": "2026-08-04T12:10:00"},
        ]
        ev_self = parse_spot_evidence(
            self_respots, home_lat=home_lat, home_lon=home_lon,
            activator_call="W8WV", user_grid="EM98dh"
        )
        self.assertEqual(len(ev_self.local_spotters), 0)
        self.assertEqual(ev_self.recent_respots_45m, 0)
        self.assertEqual(ev_self.empirical_boost_pct, 0)
        self.assertFalse(ev_self.is_qrt)

        # 3. Self-spot with QRT comment: MUST trigger is_qrt=True and 0 score
        qrt_respots = [
            {"spotter": "W8WV", "comments": "Going QRT 73 thanks all", "spotTime": "2026-08-04T12:15:00"},
        ]
        ev_qrt = parse_spot_evidence(
            qrt_respots, home_lat=home_lat, home_lon=home_lon,
            activator_call="W8WV", user_grid="EM98dh"
        )
        self.assertTrue(ev_qrt.is_qrt)
        self.assertEqual(ev_qrt.empirical_boost_pct, -100)

        prop_qrt = calculate_qso_probability(
            home_lat=home_lat, home_lon=home_lon, target_lat=home_lat, target_lon=home_lon,
            target_grid="EM98", freq_khz=7225.0, band="40m", mode="SSB",
            spot_evidence=ev_qrt,
        )
        self.assertEqual(prop_qrt.probability_pct, 0)
        self.assertEqual(prop_qrt.path_type, "Activator QRT / Station Off Air")

        # 4. Compare spots in data engine: ensure self-spotting activator does NOT get '+' local evidence badge
        spot_self_only = ActiveSpot(
            spot_id=201, activator="W8WV", frequency_raw="7225", frequency_khz=7225.0,
            band="40m", mode="SSB", reference="US-1234", park_name="Kanawha State Forest",
            spot_time_raw="", spot_time_dt=None, spotter="W8WV", comments="CQ POTA from park", source="",
            location_desc="US-WV", grid4="EM98", grid6="EM98dh", latitude=home_lat, longitude=home_lon,
            count=3, expire=3000, respots=self_respots
        )
        compared_self = compare_active_spots([spot_self_only], {}, home_grid="EM98dh")
        self.assertEqual(len(compared_self), 1)
        self.assertFalse(compared_self[0].has_local_evidence)

        # 5. Legitimate 3rd-party spotter from local area: DOES trigger local verification + badge
        third_party_respots = [
            {"spotter": "K8AA", "comments": "59 in Charleston WV loud!", "spotTime": "2026-08-04T12:05:00"},
        ]
        
        # Inject mock cache to ensure K8AA is within 200 miles
        from propagation_engine import CallsignResolver
        resolver = CallsignResolver()
        resolver.memory_cache["K8AA"] = {
            "state": "WV",
            "grid": "EM98dh",
            "latitude": home_lat,
            "longitude": home_lon,
            "name": "Test Mock"
        }
        
        ev_3rd = parse_spot_evidence(
            third_party_respots, home_lat=home_lat, home_lon=home_lon,
            activator_call="W8WV", user_grid="EM98dh", resolver=resolver
        )
        self.assertGreaterEqual(len(ev_3rd.local_spotters), 1)
        self.assertGreater(ev_3rd.empirical_boost_pct, 0)
        self.assertFalse(ev_3rd.is_qrt)

    def test_hunter_csv_age_check(self):
        """Test detection of hunter_parks.csv age (>24 hours) and startup advisory."""
        import tempfile
        import time
        from pota_prop import POTAPropApp

        # 1. Create a dummy CSV file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Reference,Name,QSOs\nUS-0001,Acadia National Park,5\n")
            temp_csv = f.name

        try:
            # Set mtime to 36 hours ago
            past_time = time.time() - (36 * 3600)
            os.utime(temp_csv, (past_time, past_time))

            mtime = os.path.getmtime(temp_csv)
            age_hours = (time.time() - mtime) / 3600.0
            self.assertGreater(age_hours, 24.0)

            app = QApplication.instance()
            if app is None:
                app = QApplication(sys.argv)

            window = POTAPropApp()
            window.txt_csv_path.setText(temp_csv)
            window.load_initial_csv()

            self.assertEqual(len(window.hunted_parks), 1)
            self.assertIn("US-0001", window.hunted_parks)

        finally:
            if 'window' in locals():
                window.refresh_timer.stop()
                if hasattr(window, "utc_clock_timer") and window.utc_clock_timer.isActive():
                    window.utc_clock_timer.stop()
                if hasattr(window, "utc_rollover_timer") and window.utc_rollover_timer.isActive():
                    window.utc_rollover_timer.stop()
                window.threadpool.waitForDone(1000)
                window.close()
            if os.path.exists(temp_csv):
                os.unlink(temp_csv)

    def test_lzw_and_websocket_frame_decoding(self):
        """Test pure-Python LZW decompression and WebSocket frame encoding/decoding."""
        from lightning_engine import lzw_decode, make_ws_frame, decode_ws_frame

        # 1. Test LZW decompression with known compressed strings
        test_str = '{"time":1785946376,"lat":38.31,"lon":-81.79}'
        # A simple string where every char < 256 decompresses trivially if uncompressed dict
        self.assertEqual(lzw_decode("ABCABC"), "ABCABC")

        # 2. Test WebSocket masked frame creation
        frame = make_ws_frame('{"a":111}')
        self.assertGreater(len(frame), 6)
        self.assertEqual(frame[0], 0x81)  # Text frame, FIN bit set

        # 3. Test unmasked frame decoding
        payload_bytes = b'{"status":"ok"}'
        server_frame = bytes([0x81, len(payload_bytes)]) + payload_bytes
        decoded, rem = decode_ws_frame(server_frame)
        self.assertIsNotNone(decoded)
        opcode, payload = decoded
        self.assertEqual(opcode, 1)
        self.assertEqual(payload, payload_bytes)
        self.assertEqual(len(rem), 0)

    def test_strike_buffer_time_decay_and_clustering(self):
        """Test StrikeBuffer sliding window, time-decay weighting, and spatial clustering."""
        import time
        from lightning_engine import StrikeBuffer, LightningStrike

        buf = StrikeBuffer(max_age_seconds=3600.0)
        now = time.time()

        # Add strikes at various age intervals
        s_recent = LightningStrike(timestamp_utc=now - 120.0, latitude=38.5, longitude=-81.5, distance_miles=25.0, bearing_deg=45.0)     # 2 min ago (weight 1.0)
        s_15m = LightningStrike(timestamp_utc=now - 720.0, latitude=38.52, longitude=-81.48, distance_miles=26.0, bearing_deg=46.0)     # 12 min ago (weight 0.70)
        s_25m = LightningStrike(timestamp_utc=now - 1500.0, latitude=38.51, longitude=-81.49, distance_miles=25.5, bearing_deg=45.5)   # 25 min ago (weight 0.45)
        s_45m = LightningStrike(timestamp_utc=now - 2700.0, latitude=39.5, longitude=-82.5, distance_miles=95.0, bearing_deg=315.0)     # 45 min ago (weight 0.20)

        buf.add_strike(s_recent)
        buf.add_strike(s_15m)
        buf.add_strike(s_25m)
        buf.add_strike(s_45m)

        c15, c30, c60, weighted_score = buf.get_strike_counts_and_rate()
        self.assertEqual(c15, 2)  # 2m and 12m
        self.assertEqual(c30, 3)  # 2m, 12m, 25m
        self.assertEqual(c60, 4)  # all 4
        expected_score = 1.0 + 0.70 + 0.45 + 0.20
        self.assertAlmostEqual(weighted_score, expected_score, places=2)

        # Test spatial clustering
        clusters = buf.cluster_strikes(home_lat=38.31, home_lon=-81.79, cluster_radius_miles=35.0)
        self.assertGreaterEqual(len(clusters), 1)
        closest = clusters[0]
        self.assertAlmostEqual(closest.distance_miles, 21.3, delta=2.0)
        self.assertTrue(closest.is_live_cluster)

    def test_nws_polygon_real_strike_counting(self):
        """Test point-in-polygon correlation to count real Blitzortung strikes within NWS warnings."""
        from lightning_engine import point_in_polygon, NWSWarning, LightningStrike

        # Polygon around Charleston WV (approx lat 38.2 to 38.5, lon -81.9 to -81.5)
        charleston_poly = [
            (-81.9, 38.2),
            (-81.5, 38.2),
            (-81.5, 38.5),
            (-81.9, 38.5),
        ]

        # Strike inside Charleston
        self.assertTrue(point_in_polygon(-81.7, 38.35, charleston_poly))

        # Strike outside Charleston (e.g. Columbus OH)
        self.assertFalse(point_in_polygon(-83.0, 39.96, charleston_poly))

        warning = NWSWarning(
            event_type="Severe Thunderstorm Warning",
            headline="Severe Thunderstorm Warning for Kanawha County",
            distance_miles=20.0,
            bearing_deg=90.0,
            polygon_coords=charleston_poly,
            issued_minutes_ago=10,
            expires_in_minutes=25,
        )
        self.assertEqual(warning.actual_strikes_in_polygon, 0)
        self.assertEqual(warning.expires_in_minutes, 25)

    def test_nws_warning_expiration_tooltip_display(self):
        """Test that lightning tooltip formats expiration time (e.g. 'expires in 25m' / 'expires in 1h 15m') instead of issued age."""
        from lightning_engine import NWSWarning, RegionalLightningSummary

        w1 = NWSWarning(
            event_type="Tornado Warning",
            headline="Tornado Warning Issued",
            distance_miles=15.0,
            bearing_deg=180.0,
            issued_minutes_ago=5,
            expires_in_minutes=25,
        )
        summary1 = RegionalLightningSummary(nws_warnings=[w1])
        html1 = summary1.format_tooltip_html()
        self.assertIn("expires in 25m", html1)
        self.assertNotIn("issued 5m ago", html1)

        w2 = NWSWarning(
            event_type="Severe Thunderstorm Warning",
            headline="Severe Thunderstorm Warning",
            distance_miles=30.0,
            bearing_deg=45.0,
            issued_minutes_ago=15,
            expires_in_minutes=75,
        )
        summary2 = RegionalLightningSummary(nws_warnings=[w2])
        html2 = summary2.format_tooltip_html()
        self.assertIn("expires in 1h 15m", html2)

    def test_hybrid_lightning_summary_generation(self):
        """Test hybrid summary generation, HTML tooltip rendering, and QRN calculation."""
        from lightning_engine import LightningEngine, StormCell, RegionalLightningSummary

        summary = RegionalLightningSummary(
            active_storm_count=2,
            total_strikes_detected=450,
            strike_rate_per_min=30,
            strike_rate_per_hour=1200,
            closest_storm_miles=45.0,
            closest_storm_bearing=210.0,
            storm_cells=[
                StormCell(
                    latitude=37.8, longitude=-82.1, intensity_weight=1.2,
                    event_type="Live Lightning Cluster", headline="45 strikes detected",
                    distance_miles=45.0, bearing_deg=210.0,
                    estimated_strikes_per_min=30, estimated_strikes_15m=450,
                    is_live_cluster=True,
                )
            ],
            source="Blitzortung Real-Time Live WebSocket",
            is_live_stream_active=True,
            live_strikes_tracked=450,
        )

        act = summary.get_activity_level()
        self.assertEqual(act.level, 8)  # 30-60 miles = Level 8 (Close Storms)
        self.assertEqual(act.label, "Close Storms")

        html = summary.format_tooltip_html()
        self.assertIn("Level 8/10", html)
        self.assertIn("Nearest Lightning Activity", html)
        self.assertIn("45.0 mi", html)
        self.assertIn("210°", html)
        self.assertIn("450 strikes", html)
        self.assertIn("Band Atmospheric Noise Surges (QRN)", html)
        self.assertIn("Station Safety Advisory", html)
        self.assertIn("Scale: 1-3", html)

    def test_smooth_blending_nws_to_blitzortung(self):
        """Test continuous averaging/cross-fade between NWS warnings and Blitzortung data over warmup window."""
        import time
        from lightning_engine import (
            LightningEngine,
            NWSWarning,
            LightningStrike,
            RegionalLightningSummary,
        )

        engine = LightningEngine()
        engine.strike_buffer.clear()
        # Mock active NWS warning
        poly = [(-81.9, 38.2), (-81.5, 38.2), (-81.5, 38.5), (-81.9, 38.5)]
        engine.cached_nws_warnings = [
            NWSWarning(
                event_type="Severe Thunderstorm Warning",
                headline="Severe Storm with Lightning",
                distance_miles=40.0,
                bearing_deg=220.0,
                polygon_coords=poly,
                issued_minutes_ago=10,
                expires_in_minutes=45,
            )
        ]
        from datetime import datetime, timezone
        engine.last_nws_fetch_time = datetime.now(timezone.utc)

        # 1. At startup (t = 0s, no live connection yet) -> 100% NWS bootstrap
        engine.start_time = time.time()
        engine.stream_thread = None
        s0 = engine._compute_hybrid_summary(38.3, -81.6)
        self.assertIn("NOAA NWS", s0.source)
        self.assertEqual(len(s0.storm_cells), 1)
        self.assertGreaterEqual(s0.strike_rate_per_min, 10)
        self.assertGreaterEqual(s0.total_strikes_detected, 150)
        html0 = s0.format_tooltip_html()
        self.assertIn("Modeled Activity in Polygon", html0)
        self.assertIn("Nearest Lightning Activity", html0)
        self.assertIn("40.0 mi", html0)

        # 2. At t = 15s (startup warmup phase 1) with stream connected
        class MockStreamThread:
            is_connected = True
            def is_alive(self):
                return True
            def update_home_location(self, lat, lon, reset_buffer=False):
                pass

        engine.stream_thread = MockStreamThread()
        engine.start_time = time.time() - 15.0
        s15 = engine._compute_hybrid_summary(38.3, -81.6)
        self.assertIn("Hybrid NWS + Blitzortung", s15.source)
        self.assertEqual(len(s15.storm_cells), 1)
        self.assertGreater(s15.strike_rate_per_min, 0)
        self.assertGreater(s15.total_strikes_detected, 0)

        # 3. At t = 300s (5 min uptime with live stream) -> ~33% Blitzortung, 67% NWS
        engine.start_time = time.time() - 300.0
        # Add 3 strikes inside the polygon
        engine.strike_buffer.add_strike(LightningStrike(timestamp_utc=time.time(), latitude=38.35, longitude=-81.7, distance_miles=35.0, bearing_deg=215.0))
        engine.strike_buffer.add_strike(LightningStrike(timestamp_utc=time.time(), latitude=38.36, longitude=-81.72, distance_miles=36.0, bearing_deg=216.0))
        s300 = engine._compute_hybrid_summary(38.3, -81.6)
        self.assertIn("Hybrid NWS + Blitzortung", s300.source)
        self.assertGreater(s300.storm_cells[0].actual_strikes_in_polygon, 0)
        html300 = s300.format_tooltip_html()
        self.assertIn("Live Activity in Polygon", html300)

        # 4. At t = 1000s (full saturation) -> 100% Blitzortung
        engine.start_time = time.time() - 1000.0
        s1000 = engine._compute_hybrid_summary(38.3, -81.6)
        self.assertIn("Blitzortung", s1000.source)
        engine.stream_thread = None

    def test_adaptive_startup_lightning_timer(self):
        """Test that GUI adaptive startup lightning timer runs every 5s for first 30s, 10s for next 30s, then stops."""
        import time
        from pota_prop import POTAPropApp

        window = POTAPropApp()
        self.assertTrue(window.startup_lightning_timer.isActive())
        self.assertEqual(window.startup_lightning_timer.interval(), 5000)

        # Phase 1: 0 - 30 seconds (interval remains 5000ms)
        window.startup_lightning_start_time = time.time() - 15.0
        window._on_startup_lightning_tick()
        self.assertTrue(window.startup_lightning_timer.isActive())
        self.assertEqual(window.startup_lightning_timer.interval(), 5000)

        # Phase 2: 30 - 60 seconds (interval updates to 10000ms)
        window.startup_lightning_start_time = time.time() - 35.0
        window._on_startup_lightning_tick()
        self.assertTrue(window.startup_lightning_timer.isActive())
        self.assertEqual(window.startup_lightning_timer.interval(), 10000)

        # Phase 3: > 60 seconds (timer stops)
        window.startup_lightning_start_time = time.time() - 65.0
        window._on_startup_lightning_tick()
        self.assertFalse(window.startup_lightning_timer.isActive())

        # Cleanup
        window.startup_lightning_timer.stop()
        window.refresh_timer.stop()
        window.utc_rollover_timer.stop()
        window.utc_clock_timer.stop()
        window.threadpool.clear()
        window.threadpool.waitForDone(2000)
        window.close()

    def test_cluster_motion_and_toa_approaching(self):
        """Test calculation of speed, heading, approach determination, and TOA for an approaching storm cluster."""
        import time
        from lightning_engine import compute_cluster_motion_and_toa, LightningStrike

        # Home location: Charleston, WV area (38.3125, -81.7083)
        home_lat, home_lon = 38.3125, -81.7083

        # Storm cluster starting 35 miles SW (around 38.0, -82.1) and moving NE towards home at ~30 mph over 10 min
        now = time.time()
        strikes = [
            LightningStrike(timestamp_utc=now - 600.0, latitude=37.95, longitude=-82.15, distance_miles=35.0, bearing_deg=225.0),
            LightningStrike(timestamp_utc=now - 550.0, latitude=37.96, longitude=-82.14, distance_miles=34.0, bearing_deg=225.0),
            LightningStrike(timestamp_utc=now - 300.0, latitude=38.00, longitude=-82.08, distance_miles=30.0, bearing_deg=225.0),
            LightningStrike(timestamp_utc=now - 50.0, latitude=38.05, longitude=-82.02, distance_miles=27.0, bearing_deg=225.0),
            LightningStrike(timestamp_utc=now, latitude=38.06, longitude=-82.01, distance_miles=26.0, bearing_deg=225.0),
        ]

        speed, heading, is_approaching, toa_min, toa_lbl = compute_cluster_motion_and_toa(
            strikes, home_lat, home_lon, current_dist_mi=26.0, current_bearing_deg=225.0
        )

        self.assertIsNotNone(speed)
        self.assertGreater(speed, 10.0)
        self.assertLess(speed, 65.0)
        self.assertTrue(is_approaching)
        self.assertIsNotNone(toa_min)
        self.assertGreater(toa_min, 0)
        self.assertLess(toa_min, 120)
        self.assertTrue(toa_lbl.endswith("m") or "h" in toa_lbl)
        self.assertNotEqual(toa_lbl, "NA")

    def test_cluster_motion_and_toa_receding_or_divergent(self):
        """Test that clusters moving away or passing perpendicular return is_approaching=False and toa_label='NA'."""
        import time
        from lightning_engine import compute_cluster_motion_and_toa, LightningStrike

        home_lat, home_lon = 38.3125, -81.7083
        now = time.time()

        # Receding cluster moving further east away from QTH
        receding_strikes = [
            LightningStrike(timestamp_utc=now - 600.0, latitude=38.31, longitude=-81.30, distance_miles=22.0, bearing_deg=90.0),
            LightningStrike(timestamp_utc=now - 500.0, latitude=38.31, longitude=-81.28, distance_miles=23.0, bearing_deg=90.0),
            LightningStrike(timestamp_utc=now - 50.0, latitude=38.31, longitude=-81.10, distance_miles=33.0, bearing_deg=90.0),
            LightningStrike(timestamp_utc=now, latitude=38.31, longitude=-81.08, distance_miles=34.0, bearing_deg=90.0),
        ]
        speed, heading, is_appr, toa_min, toa_lbl = compute_cluster_motion_and_toa(
            receding_strikes, home_lat, home_lon, current_dist_mi=34.0, current_bearing_deg=90.0
        )
        self.assertFalse(is_appr)
        self.assertEqual(toa_lbl, "NA")
        self.assertIsNone(toa_min)

        # Insufficient strike history (< 60s span)
        brief_strikes = [
            LightningStrike(timestamp_utc=now - 10.0, latitude=38.0, longitude=-82.0, distance_miles=30.0, bearing_deg=220.0),
            LightningStrike(timestamp_utc=now - 5.0, latitude=38.01, longitude=-81.99, distance_miles=29.0, bearing_deg=220.0),
            LightningStrike(timestamp_utc=now, latitude=38.02, longitude=-81.98, distance_miles=28.0, bearing_deg=220.0),
        ]
        s2, h2, is_appr2, toa_min2, toa_lbl2 = compute_cluster_motion_and_toa(
            brief_strikes, home_lat, home_lon, current_dist_mi=28.0, current_bearing_deg=220.0
        )
        self.assertFalse(is_appr2)
        self.assertEqual(toa_lbl2, "NA")

    def test_cluster_motion_tooltip_table_rendering(self):
        """Test that format_tooltip_html correctly includes Motion / TOA column header and approaching/NA badges."""
        from lightning_engine import RegionalLightningSummary, StormCell

        summary = RegionalLightningSummary(
            storm_cells=[
                StormCell(
                    latitude=38.0, longitude=-82.0,
                    distance_miles=25.0, bearing_deg=220.0,
                    estimated_strikes_per_min=12,
                    total_strikes_in_cluster=180,
                    movement_speed_mph=28.4,
                    movement_heading_deg=40.0,
                    is_approaching=True,
                    estimated_toa_minutes=35,
                    toa_label="35m",
                ),
                StormCell(
                    latitude=39.5, longitude=-80.0,
                    distance_miles=110.0, bearing_deg=45.0,
                    estimated_strikes_per_min=2,
                    total_strikes_in_cluster=30,
                    movement_speed_mph=15.0,
                    movement_heading_deg=180.0,
                    is_approaching=False,
                    toa_label="NA",
                ),
            ]
        )
        html = summary.format_tooltip_html()
        self.assertIn(">Motion / TOA</th>", html)
        self.assertIn("28 mph → NE (TOA 35m)", html)
        self.assertIn("15 mph → S (TOA: NA)", html)

    def test_itur_p372_diurnal_atmospheric_noise(self):
        """Test ITU-R P.372 frequency-dependent day/night atmospheric noise curve."""
        from datetime import datetime, timezone
        from propagation_engine import calculate_qso_probability, SolarWeather

        solar = SolarWeather(sfi=150, k_index=2, a_index=7, xray_class="B1.0")

        # 160m (1.840 MHz): Compare daytime vs nighttime noise figures
        dt_day = datetime(2026, 6, 21, 18, 0, 0, tzinfo=timezone.utc)   # Midday solar noon
        dt_night = datetime(2026, 6, 21, 5, 0, 0, tzinfo=timezone.utc)  # Nighttime 05:00 UTC

        res_day = calculate_qso_probability(
            home_lat=38.3, home_lon=-81.6,
            target_lat=41.7, target_lon=-72.7, target_grid="FN31",
            freq_khz=1840.0, band="160m", mode="SSB",
            solar_weather=solar, dt_utc=dt_day,
        )
        res_night = calculate_qso_probability(
            home_lat=38.3, home_lon=-81.6,
            target_lat=41.7, target_lon=-72.7, target_grid="FN31",
            freq_khz=1840.0, band="160m", mode="SSB",
            solar_weather=solar, dt_utc=dt_night,
        )

        self.assertIsNotNone(res_day.noise_floor_dbw)
        self.assertIsNotNone(res_night.noise_floor_dbw)
        # Night noise power on 160m (in dBW) is higher than day due to lack of D-layer absorption & distant global sferics
        self.assertGreater(res_night.noise_floor_dbw, res_day.noise_floor_dbw)
        self.assertGreaterEqual(res_night.noise_floor_dbw - res_day.noise_floor_dbw, 10.0)

    def test_location_change_resets_lightning_engine(self):
        """Test that changing operator location or callsign resets the strike buffer, cache, and starts fresh bootstrap."""
        import time
        from lightning_engine import (
            LightningEngine,
            StrikeBuffer,
            LightningStrike,
            reset_lightning_engine_location,
            _GLOBAL_LIGHTNING_ENGINE,
        )

        engine = _GLOBAL_LIGHTNING_ENGINE
        # Add some initial strikes for location 1 (EM98)
        engine.strike_buffer.add_strike(
            LightningStrike(
                timestamp_utc=time.time(),
                latitude=38.3,
                longitude=-81.7,
                distance_miles=10.0,
                bearing_deg=180.0,
            )
        )
        self.assertGreaterEqual(len(engine.strike_buffer.get_all_strikes()), 1)

        # Now reset location to Florida (EL98: ~28.5, -81.4)
        if engine.stream_thread and hasattr(engine.stream_thread, "stop"):
            engine.stream_thread.stop()
        summary = reset_lightning_engine_location(28.5, -81.4)
        self.assertAlmostEqual(engine.current_home_lat, 28.5)
        self.assertAlmostEqual(engine.current_home_lon, -81.4)
        self.assertIsNotNone(summary)

    def test_gui_callsign_and_grid_change_triggers_lightning_reset(self):
        """Test that GUI callsign lookup and grid change update the lightning summary to new location."""
        from pota_prop import POTAPropApp
        from propagation_engine import CallsignLocation

        window = POTAPropApp()
        window.chk_p2p.setChecked(False)
        self.assertIsNotNone(window.lightning_summary)

        # Simulate callsign lookup finishing for W4ABC in Florida (EL98ja)
        loc = CallsignLocation(callsign="W4ABC", grid="EL98ja", name="Florida Op", state="FL")
        window.my_call = "W4ABC"
        window.on_callsign_lookup_finished(loc)

        self.assertEqual(window.current_grid, "EL98JA")
        self.assertIsNotNone(window.lightning_summary)

        # Simulate manual grid edit to Seattle (CN87uk)
        window.txt_grid.setText("CN87uk")
        window.on_grid_changed()
        self.assertEqual(window.current_grid, "CN87UK")
        self.assertIsNotNone(window.lightning_summary)

        window.startup_lightning_timer.stop()
        window.refresh_timer.stop()
        window.utc_rollover_timer.stop()
        window.utc_clock_timer.stop()
        window.threadpool.clear()
        window.threadpool.waitForDone(2000)
        window.close()

    def test_compute_band_noise_matrix_all_bands(self):
        """Test compute_band_noise_matrix returns all 11 amateur bands with valid Fa and S-meter metrics."""
        from datetime import datetime, timezone
        from propagation_engine import compute_band_noise_matrix, SolarWeather

        dt_utc = datetime(2026, 6, 21, 18, 0, 0, tzinfo=timezone.utc)
        solar = SolarWeather(sfi=150, k_index=2, a_index=7, xray_class="B1.0")

        matrix = compute_band_noise_matrix(
            home_lat=38.3,
            home_lon=-81.6,
            solar_weather=solar,
            lightning_summary=None,
            dt_utc=dt_utc,
        )

        self.assertEqual(len(matrix), 11)
        bands = [b.band for b in matrix]
        self.assertIn("160m", bands)
        self.assertIn("80m", bands)
        self.assertIn("40m", bands)
        self.assertIn("20m", bands)
        self.assertIn("10m", bands)
        self.assertIn("6m", bands)

        # 160m atmospheric noise figure should exceed 10m atmospheric noise figure
        b_160 = next(b for b in matrix if b.band == "160m")
        b_10 = next(b for b in matrix if b.band == "10m")
        self.assertGreater(b_160.f_atm_total_db, b_10.f_atm_total_db)

        # S-meter values should be present and valid
        for b in matrix:
            self.assertIsNotNone(b.s_units_label)
            self.assertGreater(b.f_a_total_db, 0.0)
            self.assertLess(b.noise_power_dbm, 0.0)

    def test_band_noise_matrix_lightning_qrn_surge(self):
        """Test that live regional lightning activity injects QRN surges into band noise breakdown."""
        from datetime import datetime, timezone
        from propagation_engine import compute_band_noise_matrix
        from lightning_engine import RegionalLightningSummary, StormCell

        cell = StormCell(
            latitude=38.4,
            longitude=-81.5,
            intensity_weight=1.5,
            distance_miles=12.0,
            bearing_deg=45.0,
            estimated_strikes_per_min=10,
        )
        summary = RegionalLightningSummary(
            active_storm_count=1,
            total_strikes_detected=600,
            strike_rate_per_min=10,
            closest_storm_miles=12.0,
            closest_storm_bearing=45.0,
            storm_cells=[cell],
        )

        matrix = compute_band_noise_matrix(
            home_lat=38.3,
            home_lon=-81.6,
            lightning_summary=summary,
        )

        b_160 = next(b for b in matrix if b.band == "160m")
        b_40 = next(b for b in matrix if b.band == "40m")

        # 160m and 40m should experience significant QRN surges
        self.assertGreaterEqual(b_160.qrn_surge_db, 10.0)
        self.assertGreaterEqual(b_40.qrn_surge_db, 3.0)
        self.assertTrue(b_160.is_elevated_qrn)

    def test_band_noise_dialog_gui_instantiation(self):
        """Test that BandNoiseDialog instantiates and populates table without UI exceptions."""
        from pota_prop import BandNoiseDialog
        from propagation_engine import SolarWeather
        from lightning_engine import RegionalLightningSummary, StormCell

        solar = SolarWeather(sfi=140, k_index=2, a_index=5)
        cell = StormCell(
            latitude=38.5,
            longitude=-81.4,
            distance_miles=45.0,
            bearing_deg=60.0,
        )
        lightning = RegionalLightningSummary(
            active_storm_count=1,
            total_strikes_detected=25,
            closest_storm_miles=45.0,
            closest_storm_bearing=60.0,
            storm_cells=[cell],
        )

        dlg = BandNoiseDialog(
            home_lat=38.3,
            home_lon=-81.6,
            solar_weather=solar,
            lightning_summary=lightning,
        )

        self.assertEqual(dlg.table.rowCount(), 11)
        self.assertEqual(dlg.table.columnCount(), 8)
        # Check first row has 160m
        item_band = dlg.table.item(0, 0)
        self.assertIsNotNone(item_band)
        self.assertIn("160m", item_band.text())
        dlg.close()


class TestUtcDayRolloverAndWorkedStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_worked_parks_tracker(self):
        from datetime import datetime, timezone
        from pota_prop import WorkedParksTracker
        tracker = WorkedParksTracker()
        self.assertEqual(len(tracker), 0)

        # Add with default today's date
        tracker.add("US-1845")
        self.assertIn("US-1845", tracker)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertEqual(tracker["US-1845"], today_str)

        # Add with explicit previous date
        tracker.add("K-0001", "2026-01-01")
        self.assertEqual(tracker["K-0001"], "2026-01-01")

        # Discard
        tracker.discard("US-1845")
        self.assertNotIn("US-1845", tracker)
        self.assertIn("K-0001", tracker)

    def test_get_worked_status_transitions(self):
        from propagation_engine import SolarWeather
        from pota_prop import POTAPropApp
        from data_engine import ActiveSpot
        from datetime import datetime, timezone

        window = POTAPropApp()
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Mock single active spot
        mock_spot = ActiveSpot(
            spot_id=99999,
            activator="W8TEST",
            frequency_raw="14074",
            frequency_khz=14074.0,
            band="20m",
            mode="FT8",
            reference="US-9999",
            park_name="Test Rollover Park",
            spot_time_raw="2026-08-05T23:45:00",
            spot_time_dt=None,
            spotter="TESTER",
            comments="POTA test",
            source="POTA",
            location_desc="US-WV",
            grid4="EM98",
            grid6="EM98dh",
            latitude=38.3,
            longitude=-81.7,
            count=1,
            expire=3000,
        )
        window.on_spots_fetched([mock_spot], SolarWeather(sfi=140.0, k_index=1.0))

        # 1. Unworked state
        window.manually_worked_parks.discard("US-9999")
        self.assertIsNone(window.get_worked_status("US-9999"))

        # 2. Worked today (before 00Z)
        window.toggle_park_worked("US-9999", force_state=True)
        self.assertEqual(window.get_worked_status("US-9999"), "TODAY")
        window.recompute_comparisons()
        window.populate_table(window.compared_spots)
        
        # Verify [WORKED] in cell widget or text
        item_status = window.table.item(0, 0)
        self.assertEqual(item_status.text(), "[WORKED]")

        # 3. Simulate 00Z Day Rollover (worked yesterday)
        window.manually_worked_parks["US-9999"] = "2020-01-01"
        self.assertEqual(window.get_worked_status("US-9999"), "PREVIOUS_DAY")
        window.recompute_comparisons()
        window.populate_table(window.compared_spots)

        # Verify Hunted(W) badge display
        item_status = window.table.item(0, 0)
        self.assertIn("Hunted(W)", item_status.text())

        # Reset filter controls to All
        window.combo_dx.setCurrentIndex(0)
        window.combo_band.setCurrentIndex(0)
        window.combo_mode.setCurrentIndex(0)
        window.txt_search.setText("")

        # Test filters with Hunted(W)
        # Status Filter 1 (New Only) -> Should not show US-9999
        window.combo_status.setCurrentIndex(1)
        window.apply_filters()
        self.assertEqual(window.table.rowCount(), 0)

        # Status Filter 2 (Hunted) -> Should show US-9999
        window.combo_status.setCurrentIndex(2)
        window.apply_filters()
        self.assertEqual(window.table.rowCount(), 1)

        # Status Filter 3 ([WORKED] Today Only) -> Should NOT show US-9999 (eligible to hunt again)
        window.combo_status.setCurrentIndex(3)
        window.apply_filters()
        self.assertEqual(window.table.rowCount(), 0)

        # 4. Work the park on the new day -> Transitions back to [WORKED]
        window.toggle_park_worked("US-9999", force_state=True)
        self.assertEqual(window.get_worked_status("US-9999"), "TODAY")
        self.assertEqual(window.manually_worked_parks["US-9999"], today_utc)
        window.apply_filters()
        self.assertEqual(window.table.rowCount(), 1)

        # Cleanup
        window.refresh_timer.stop()
        window.utc_rollover_timer.stop()
        window.utc_clock_timer.stop()
        window.threadpool.waitForDone(1000)
        window.close()

    def test_utc_clock_display(self):
        from pota_prop import POTAPropApp
        from datetime import datetime, timezone
        window = POTAPropApp()
        
        expected_prefix = "Time: "
        expected_suffix = " UTC"
        current_time_utc = datetime.now(timezone.utc).strftime("%H:%M")

        self.assertTrue(window.lbl_utc_clock_top.text().startswith(expected_prefix))
        self.assertTrue(window.lbl_utc_clock_top.text().endswith(expected_suffix))
        self.assertIn(current_time_utc, window.lbl_utc_clock_top.text())

        self.assertTrue(window.lbl_utc_clock_bottom.text().startswith(expected_prefix))
        self.assertTrue(window.lbl_utc_clock_bottom.text().endswith(expected_suffix))
        self.assertIn(current_time_utc, window.lbl_utc_clock_bottom.text())

        # Cleanup
        window.refresh_timer.stop()
        window.utc_rollover_timer.stop()
        window.utc_clock_timer.stop()
        window.threadpool.waitForDone(1000)
        window.close()

    def test_wmo_weather_code_mapping(self):
        """Test WMO weather code to description/icon translation and cardinal direction mapping."""
        from weather_engine import get_wmo_info, degrees_to_cardinal

        desc0, icon0, short0 = get_wmo_info(0)
        self.assertEqual(desc0, "Clear Sky")
        self.assertEqual(icon0, "")
        self.assertEqual(short0, "Clear")

        desc63, icon63, short63 = get_wmo_info(63)
        self.assertEqual(desc63, "Moderate Rain")
        self.assertEqual(icon63, "")

        desc95, icon95, short95 = get_wmo_info(95)
        self.assertEqual(desc95, "Thunderstorm")
        self.assertEqual(icon95, "")

        self.assertEqual(degrees_to_cardinal(0.0), "N")
        self.assertEqual(degrees_to_cardinal(90.0), "E")
        self.assertEqual(degrees_to_cardinal(180.0), "S")
        self.assertEqual(degrees_to_cardinal(270.0), "W")
        self.assertEqual(degrees_to_cardinal(225.0), "SW")

    def test_weather_engine_parsing_and_tooltip_formatting(self):
        """Test WeatherForecastSummary formatting, 12-hour hourly forecast, and Open-Meteo attribution."""
        from datetime import datetime, timezone
        from weather_engine import (
            WeatherForecastSummary,
            CurrentWeatherItem,
            HourlyForecastItem,
        )

        dt_now = datetime(2026, 8, 7, 14, 0, 0, tzinfo=timezone.utc)
        summary = WeatherForecastSummary(
            current=CurrentWeatherItem(
                temp_f=72.4,
                weather_code=2,
                weather_desc="Partly Cloudy",
                weather_icon="⛅",
                short_label="Part Cloud",
                wind_speed_mph=8.5,
                wind_dir_deg=315.0,
                wind_dir_cardinal="NW",
                humidity_pct=45.0,
            ),
            hourly_forecast=[
                HourlyForecastItem(
                    dt_utc=dt_now,
                    temp_f=73.0,
                    weather_code=2,
                    weather_desc="Partly Cloudy",
                    weather_icon="⛅",
                    wind_speed_mph=9.0,
                    wind_dir_deg=320.0,
                    wind_dir_cardinal="NW",
                    precip_prob=10,
                    humidity_pct=50.0,
                ),
                HourlyForecastItem(
                    dt_utc=datetime(2026, 8, 7, 15, 0, 0, tzinfo=timezone.utc),
                    temp_f=75.0,
                    weather_code=0,
                    weather_desc="Clear Sky",
                    weather_icon="☀️",
                    wind_speed_mph=7.0,
                    wind_dir_deg=300.0,
                    wind_dir_cardinal="NW",
                    precip_prob=0,
                    humidity_pct=40.0,
                ),
            ],
            home_lat=38.3,
            home_lon=-81.6,
            fetch_time_utc=dt_now,
            is_live=True,
        )

        html = summary.format_tooltip_html()
        self.assertIn("Local Weather: <b>72°F</b> · Partly Cloudy", html)
        self.assertIn("Wind: <b>8 mph</b> from <b>NW</b>", html)
        self.assertIn("12-Hour Hourly Forecast:", html)
        self.assertIn(">Time (UTC)</th>", html)
        self.assertIn("14:00", html)
        self.assertIn(">Temp</th>", html)
        self.assertIn(">Condition</th>", html)
        self.assertIn(">Wind</th>", html)
        self.assertIn("73°F", html)
        self.assertIn("Clear Sky", html)
        self.assertIn("Open-Meteo.com", html)

    def test_gui_weather_card_integration(self):
        """Test GUI card_weather initialization and update upon weather fetch."""
        from pota_prop import POTAPropApp
        from weather_engine import WeatherForecastSummary, CurrentWeatherItem

        window = POTAPropApp()
        self.assertIsNotNone(window.card_weather)
        self.assertEqual(window.card_weather.lbl_title.text(), "WEATHER (CLICK FOR RADAR)")

        summary = WeatherForecastSummary(
            current=CurrentWeatherItem(
                temp_f=68.0,
                weather_code=0,
                weather_desc="Clear Sky",
                weather_icon="☀️",
                short_label="Clear",
                wind_speed_mph=5.0,
                wind_dir_deg=180.0,
                wind_dir_cardinal="S",
                humidity_pct=45.0,
            )
        )
        window._on_weather_fetched(summary)
        self.assertIn("68°F", window.card_weather.lbl_value.text())
        self.assertIn("☀️", window.card_weather.lbl_value.text())
        self.assertIn("Open-Meteo.com", window.card_weather.toolTip())

        # Cleanup
        window.weather_timer.stop()
        window.refresh_timer.stop()
        window.utc_rollover_timer.stop()
        window.utc_clock_timer.stop()
        window.threadpool.waitForDone(1000)
        window.close()

    def test_p2p_park_name_location_tooltip(self):
        """Test that setting a P2P park reference resolves the park name and updates tooltips."""
        from pota_prop import POTAPropApp
        window = POTAPropApp()
        window.chk_p2p.setChecked(True)
        window.txt_p2p_park.setText("US-1845")
        window.p2p_my_park = "US-1845"
        window.on_p2p_park_lookup_finished({"reference": "US-1845", "name": "Kanawha State Forest", "grid": "EM98dh"})
        self.assertEqual(window.p2p_my_park_name, "Kanawha State Forest")
        self.assertIn("Kanawha State Forest", window.txt_p2p_park.toolTip())

        # Cleanup
        window.chk_p2p.setChecked(False)
        window.weather_timer.stop()
        window.startup_lightning_timer.stop()
        window.refresh_timer.stop()
        window.utc_rollover_timer.stop()
        window.utc_clock_timer.stop()
        window.threadpool.clear()
        window.threadpool.waitForDone(2000)
        window.close()


if __name__ == "__main__":
    unittest.main()




